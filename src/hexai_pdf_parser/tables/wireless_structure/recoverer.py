"""Production adapter for the isolated Chinese wireless-table pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from collections.abc import Mapping
from typing import Any

import fitz

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox, Cell
from hexai_pdf_parser.tables.wireless_table_recovery import (
    _rust_cells_to_project,
    collect_native_spans,
    collect_native_spans_from_snapshot,
)

from .columns import (
    infer_column_bands,
    prune_paired_cjk_artifact_bands,
    prune_sparse_alignment_artifact_bands,
)
from .continuations import merge_column_continuations
from .grid import build_grid
from .header_topology import (
    annotate_columns,
    refine_leaf_bands,
    rescue_header_only_leaf_bands,
    rescue_header_only_note_bands,
    rescue_sparse_body_bands,
)
from .logical_grid import build_logical_grid, materialize_empty_cells, merge_header_spans
from .merged_cells import (
    merge_multiline_cells,
    merge_same_slot_fragments,
    resolve_exact_slot_conflicts,
)
from .span_chain import region_spans
from .text_runs import (
    build_text_runs,
    infer_output_order_mode,
    merge_same_band_native_line_runs,
)


def _bbox(values: list[float]) -> BBox:
    return BBox(*values)


def _to_cells(
    cells: list[dict[str, Any]],
) -> tuple[int, int, list[Cell]]:
    if not cells:
        return 0, 0, []

    converted = [
        Cell(
            text=str(item.get("text", "")).strip(),
            row_index=max(0, int(item["row_start"]) - 1),
            col_index=max(0, int(item["col_start"]) - 1),
            rowspan=max(1, int(item.get("rowspan", 1))),
            colspan=max(1, int(item.get("colspan", 1))),
            bbox=_bbox(item["bbox"]),
        )
        for item in cells
        if item.get("bbox")
    ]
    converted.sort(key=lambda cell: (cell.row_index, cell.col_index))
    row_count = max(
        (cell.row_index + max(1, cell.rowspan) for cell in converted),
        default=0,
    )
    col_count = max(
        (cell.col_index + max(1, cell.colspan) for cell in converted),
        default=0,
    )
    return row_count, col_count, converted


def _has_occupancy_conflict(cells: list[dict[str, Any]]) -> bool:
    occupied: set[tuple[int, int]] = set()
    for cell in cells:
        for row in range(cell["row_start"], cell["row_end"] + 1):
            for column in range(cell["col_start"], cell["col_end"] + 1):
                slot = (row, column)
                if slot in occupied:
                    return True
                occupied.add(slot)
    return False


def _commit_header_spans_or_keep_base(
    cells: list[dict[str, Any]], header_cutoff: float | None
) -> list[dict[str, Any]]:
    base = [dict(cell) for cell in cells]
    proposed = merge_header_spans([dict(cell) for cell in base], header_cutoff)
    return base if _has_occupancy_conflict(proposed) else proposed


def _native_region_rect(region_bbox: BBox) -> dict[str, Any]:
    return _native_rect_from_bbox(
        [region_bbox.x0, region_bbox.y0, region_bbox.x1, region_bbox.y1],
        "region bbox",
    )


_MISSING = object()
_SPAN_REF = re.compile(r"^S(\d+)(?:\.\d+)?$")


def _native_strict_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _native_strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _native_strict_finite_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite float")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _native_rect_from_bbox(bbox: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(bbox, (list, tuple)):
        raise TypeError(f"{field_name} must be a four-item sequence")
    if len(bbox) != 4:
        raise ValueError(f"{field_name} must contain four coordinates")
    x0, y0, x1, y1 = (
        _native_strict_finite_float(value, f"{field_name}[{index}]")
        for index, value in enumerate(bbox)
    )
    if x0 >= x1 or y0 >= y1:
        raise ValueError(f"{field_name} must have x0 < x1 and y0 < y1")
    return {
        "schema_version": 1,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
    }


def _native_validate_span_bbox(span: Any) -> None:
    bbox = span.bbox
    _native_rect_from_bbox(
        [bbox.x0, bbox.y0, bbox.x1, bbox.y1], "native span bbox"
    )


def _native_validate_snapshot_span_bboxes(snapshot: Any) -> None:
    text_blocks = getattr(snapshot, "text_blocks", _MISSING)
    if text_blocks is _MISSING:
        raise KeyError("snapshot.text_blocks")
    if not isinstance(text_blocks, (list, tuple)):
        raise TypeError("snapshot.text_blocks must be a list or tuple")
    for block_index, block in enumerate(text_blocks):
        if not isinstance(block, Mapping):
            raise TypeError(f"text_blocks[{block_index}] must be an object")
        if "type" not in block:
            raise KeyError(f"text_blocks[{block_index}].type")
        block_type = block["type"]
        if isinstance(block_type, bool) or not isinstance(block_type, int):
            raise TypeError(f"text_blocks[{block_index}].type must be an integer")
        if block_type != 0:
            continue
        if "lines" not in block:
            raise KeyError(f"text_blocks[{block_index}].lines")
        lines = block["lines"]
        if not isinstance(lines, (list, tuple)):
            raise TypeError(f"text_blocks[{block_index}].lines must be a list or tuple")
        for line_index, line in enumerate(lines):
            if not isinstance(line, Mapping):
                raise TypeError(
                    f"text_blocks[{block_index}].lines[{line_index}] must be an object"
                )
            if "spans" not in line:
                raise KeyError(
                    f"text_blocks[{block_index}].lines[{line_index}].spans"
                )
            spans = line["spans"]
            if not isinstance(spans, (list, tuple)):
                raise TypeError(
                    f"text_blocks[{block_index}].lines[{line_index}].spans "
                    "must be a list or tuple"
                )
            for span_index, span in enumerate(spans):
                if not isinstance(span, Mapping):
                    raise TypeError(
                        "text_blocks[{}].lines[{}].spans[{}] must be an object".format(
                            block_index, line_index, span_index
                        )
                    )
                if "bbox" not in span:
                    raise KeyError(
                        "text_blocks[{}].lines[{}].spans[{}].bbox".format(
                            block_index, line_index, span_index
                        )
                    )
                _native_rect_from_bbox(
                    span["bbox"],
                    "text_blocks[{}].lines[{}].spans[{}].bbox".format(
                        block_index, line_index, span_index
                    ),
                )


def _native_strict_int_list(value: Any, field_name: str) -> list[int]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a list of integers")
    result = [
        _native_strict_int(item, f"{field_name}[{index}]")
        for index, item in enumerate(value)
    ]
    if any(item < 0 for item in result):
        raise ValueError(f"{field_name} must contain non-negative integers")
    return result


def _native_run_refs(
    atom: dict[str, Any],
    atom_index: int,
    valid_span_orders: set[int] | None = None,
) -> list[int]:
    if "span_refs" in atom:
        references = atom["span_refs"]
        if not isinstance(references, (list, tuple)):
            raise TypeError("span_refs must be a list or tuple")
        parsed = []
        for reference_index, reference in enumerate(references):
            if not isinstance(reference, str):
                raise TypeError(f"span_refs[{reference_index}] must be a string")
            match = _SPAN_REF.fullmatch(reference)
            if match is None:
                raise ValueError(
                    f"span_refs[{reference_index}] must match S<number> or S<number>.<fragment>"
                )
            order = int(match.group(1))
            if valid_span_orders is not None and order not in valid_span_orders:
                raise ValueError(f"span_refs[{reference_index}] has unknown span order {order}")
            parsed.append(order)
        return parsed

    for key in ("native_span_order", "span_order"):
        value = atom.get(key, _MISSING)
        if value is _MISSING:
            continue
        value = _native_strict_int(value, key)
        if value < 0:
            raise ValueError(f"{key} must be non-negative")
        if valid_span_orders is not None and value not in valid_span_orders:
            raise ValueError(f"{key} has unknown span order {value}")
        return [value]
    return [atom_index]


def _native_optional_int(
    atom: dict[str, Any], field_name: str, default: int | None = None
) -> int | None:
    value = atom.get(field_name, _MISSING)
    if value is _MISSING or value is None:
        return default
    return _native_strict_int(value, field_name)


def _native_optional_nonnegative_int(
    atom: dict[str, Any], field_name: str, default: int | None = None
) -> int | None:
    value = _native_optional_int(atom, field_name, default)
    if value is not None and value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _native_atom_evidence(
    atom: dict[str, Any], atom_index: int
) -> dict[str, Any]:
    flow_start = _native_strict_int(
        atom.get("flow_start", atom_index), "flow_start"
    )
    flow_end = _native_strict_int(atom.get("flow_end", flow_start), "flow_end")
    if flow_start < 0 or flow_end < 0:
        raise ValueError("flow evidence must be non-negative")
    if flow_end < flow_start:
        raise ValueError("flow_end must be greater than or equal to flow_start")
    source_blocks = _native_strict_int_list(
        atom.get("source_blocks", []), "source_blocks"
    )
    source_line_start = _native_strict_int(
        atom.get("source_line_start", 0), "source_line_start"
    )
    source_line_end = _native_strict_int(
        atom.get("source_line_end", source_line_start), "source_line_end"
    )
    if source_line_start < 0 or source_line_end < 0:
        raise ValueError("source line evidence must be non-negative")
    if source_line_end < source_line_start:
        raise ValueError(
            "source_line_end must be greater than or equal to source_line_start"
        )
    source_position_known = _native_strict_bool(
        atom.get("source_position_known", False), "source_position_known"
    )
    column_id = _native_optional_nonnegative_int(atom, "column_id")
    return {
        "flow_start": flow_start,
        "flow_end": flow_end,
        "source_blocks": list(source_blocks),
        "source_line_start": source_line_start,
        "source_line_end": source_line_end,
        "source_position_known": source_position_known,
        "column_id": column_id,
    }


def _native_atom_core(
    atom: dict[str, Any], atom_index: int, valid_span_orders: set[int] | None = None
) -> dict[str, Any]:
    text = atom["text"]
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    rect = _native_rect_from_bbox(atom["bbox"], "bbox")
    evidence = _native_atom_evidence(atom, atom_index)
    row_hint = _native_optional_nonnegative_int(atom, "row_hint")
    column_id = evidence["column_id"]
    return {
        "schema_version": 1,
        "text": text,
        "rect": rect,
        "run_refs": _native_run_refs(atom, atom_index, valid_span_orders),
        "row_hint": row_hint,
        "col_hint": column_id,
        "order": evidence["flow_start"],
        **evidence,
    }


def _native_band_evidence(band: dict[str, Any], band_index: int) -> dict[str, Any]:
    band_id = _native_strict_int(band.get("id", band_index + 1), "id")
    if band_id < 0:
        raise ValueError("id must be non-negative")
    kind = band.get("kind")
    if kind is not None and not isinstance(kind, str):
        raise TypeError("kind must be a string or None")
    support = _native_strict_int(band.get("support", 0), "support")
    y_support = _native_strict_int(band.get("y_support", 0), "y_support")
    if support < 0 or y_support < 0:
        raise ValueError("support evidence must be non-negative")
    parent_x0 = band.get("parent_x0")
    parent_x1 = band.get("parent_x1")
    if parent_x0 is not None:
        parent_x0 = _native_strict_finite_float(parent_x0, "parent_x0")
    if parent_x1 is not None:
        parent_x1 = _native_strict_finite_float(parent_x1, "parent_x1")
    if (parent_x0 is None) != (parent_x1 is None):
        raise ValueError("parent_x0 and parent_x1 must be provided together")
    if parent_x0 is not None and parent_x0 >= parent_x1:
        raise ValueError("parent_x0 must be less than parent_x1")
    parent_leaf_count = _native_optional_int(band, "parent_leaf_count")
    if parent_leaf_count is not None and parent_leaf_count <= 0:
        raise ValueError("parent_leaf_count must be positive")
    return {
        "id": band_id,
        "kind": kind,
        "support": support,
        "y_support": y_support,
        "parent_x0": parent_x0,
        "parent_x1": parent_x1,
        "parent_leaf_count": parent_leaf_count,
    }


def _native_band_core(
    band: dict[str, Any], band_index: int, atoms: list[dict[str, Any]]
) -> dict[str, Any]:
    x0 = _native_strict_finite_float(band["x0"], "x0")
    x1 = _native_strict_finite_float(band["x1"], "x1")
    if x0 >= x1:
        raise ValueError("band requires x0 < x1")
    source_atoms = [
        atom_index
        for atom_index, atom in enumerate(atoms)
        if min(atom["rect"]["x1"], x1) > max(atom["rect"]["x0"], x0)
    ]
    return {
        "schema_version": 1,
        "x0": x0,
        "x1": x1,
        "source_atoms": source_atoms,
        "order": band_index,
        **_native_band_evidence(band, band_index),
    }


def _normalize_native_region_atoms_and_bands(
    atoms: list[dict[str, Any]],
    bands: list[dict[str, Any]],
    valid_span_orders: set[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_atoms = [
        _native_atom_core(atom, atom_index, valid_span_orders)
        for atom_index, atom in enumerate(atoms)
    ]
    normalized_bands = [
        _native_band_core(band, band_index, normalized_atoms)
        for band_index, band in enumerate(bands)
    ]
    return normalized_atoms, normalized_bands


@dataclass(frozen=True)
class _PreparedNativeRegion:
    rust_input: dict[str, Any]
    python_atoms: list[dict[str, Any]]
    python_bands: list[dict[str, Any]]
    output_mode: str
    header_cutoff: float | None


def _prepare_native_region_from_snapshot(
    snapshot: Any,
    region_bbox: BBox,
    *,
    validate_spans: bool = False,
) -> _PreparedNativeRegion | None:
    """Build the shared Python-derived input for the next native transition."""
    region_rect = _native_region_rect(region_bbox)
    if validate_spans:
        _native_validate_snapshot_span_bboxes(snapshot)
    native_spans = list(
        collect_native_spans_from_snapshot(snapshot, allowed_regions=[region_bbox])
    )
    if validate_spans:
        for span in native_spans:
            _native_validate_span_bbox(span)
    spans = region_spans(native_spans, region_bbox)
    output_mode = infer_output_order_mode(spans)
    atoms = build_text_runs(spans, output_mode=output_mode)
    bands = infer_column_bands(atoms, region_bbox)
    bands = prune_paired_cjk_artifact_bands(atoms, bands)
    bands = prune_sparse_alignment_artifact_bands(atoms, bands)
    if not atoms or len(bands) < 2:
        return None

    atoms = merge_same_band_native_line_runs(atoms, bands)
    bands, header_cutoff = refine_leaf_bands(atoms, bands)
    bands = rescue_sparse_body_bands(atoms, bands, header_cutoff)
    bands = rescue_header_only_note_bands(atoms, bands, header_cutoff)
    bands = rescue_header_only_leaf_bands(atoms, bands, header_cutoff)
    if len(bands) < 1:
        return None

    annotate_columns(atoms, bands, header_cutoff, region_bbox)
    python_atoms = [dict(atom) for atom in atoms]
    python_bands = [dict(band) for band in bands]
    normalized_atoms, normalized_bands = _normalize_native_region_atoms_and_bands(
        python_atoms,
        python_bands,
        {span.order for span in native_spans} if validate_spans else None,
    )
    rust_input = {
        "schema_version": 1,
        "region": {
            "schema_version": 1,
            "rect": region_rect,
            "source_order": 0,
            "allowed": True,
        },
        "atoms": normalized_atoms,
        "bands": normalized_bands,
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }
    return _PreparedNativeRegion(
        rust_input=rust_input,
        python_atoms=python_atoms,
        python_bands=python_bands,
        output_mode=output_mode,
        header_cutoff=header_cutoff,
    )


def _build_native_region_input_from_snapshot(
    snapshot: Any,
    region_bbox: BBox,
) -> dict[str, Any] | None:
    prepared = _prepare_native_region_from_snapshot(
        snapshot, region_bbox, validate_spans=True
    )
    if prepared is None:
        return None
    return prepared.rust_input


def _recover_native_region_from_snapshot_rust(
    snapshot: Any,
    region_bbox: BBox,
) -> dict[str, Any] | None:
    input_dto = _build_native_region_input_from_snapshot(snapshot, region_bbox)
    if input_dto is None:
        return None
    return rust_adapter.recover_native_region(input_dto)


def _recover_cells_from_snapshot_python(
    snapshot: Any,
    region_bbox: BBox,
) -> tuple[int, int, list[Cell]]:
    try:
        prepared = _prepare_native_region_from_snapshot(snapshot, region_bbox)
        if prepared is None:
            return 0, 0, []
        atoms = prepared.python_atoms
        bands = prepared.python_bands
        output_mode = prepared.output_mode
        header_cutoff = prepared.header_cutoff
        candidates = merge_column_continuations(atoms, bands)
        physical_rows, columns, grid_cells, _issues = build_grid(candidates, bands)
        if not grid_cells:
            return 0, 0, []

        cells = merge_same_slot_fragments(grid_cells, header_cutoff)
        if _has_occupancy_conflict(cells):
            resolved_cells = resolve_exact_slot_conflicts(cells)
            if len(resolved_cells) < len(cells):
                physical_rows, columns, grid_cells, _issues = build_grid(
                    resolved_cells, bands
                )
                cells = merge_same_slot_fragments(grid_cells, header_cutoff)
        cells = merge_multiline_cells(
            cells, header_cutoff, output_mode=output_mode
        )
        if _has_occupancy_conflict(cells):
            return 0, 0, []
        logical_rows, logical_columns, logical_cells = build_logical_grid(
            physical_rows, columns, cells, header_cutoff
        )
        if _has_occupancy_conflict(logical_cells):
            return 0, 0, []
        logical_cells = _commit_header_spans_or_keep_base(
            logical_cells, header_cutoff
        )
        logical_cells = materialize_empty_cells(
            logical_rows,
            physical_rows,
            logical_columns,
            logical_cells,
            region_bbox,
        )
        return _to_cells(logical_cells)
    except Exception:
        return 0, 0, []


def _recover_cells_from_region_python(
    page: fitz.Page | Any,
    region_bbox: BBox,
) -> tuple[int, int, list[Cell]]:
    if hasattr(page, "schema_version") and hasattr(page, "text_blocks"):
        snapshot = page
    else:
        from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot

        snapshot = capture_page_snapshot(
            page,
            page_index=getattr(page, "number", 0),
            allowed_regions=[region_bbox],
        )
    return _recover_cells_from_snapshot_python(snapshot, region_bbox)


def _recover_cells_from_rust(
    output: dict[str, Any],
    region_bbox: BBox,
) -> tuple[int, int, list[Cell]]:
    if not isinstance(output, dict):
        raise TypeError("Rust native recovery output must be a mapping")
    grid_output = output.get("grid", {})
    if not isinstance(grid_output, dict):
        raise TypeError("Rust native recovery grid must be a mapping")
    grid = grid_output.get("grid", grid_output)
    if not isinstance(grid, dict):
        raise TypeError("Rust native recovery inner grid must be a mapping")
    diagnostics = output.get("diagnostics", [])
    if any(
        isinstance(item, dict) and item.get("status") == "occupancy_conflict"
        for item in diagnostics
    ):
        raise ValueError("Rust native recovery reported an occupancy conflict")
    rows = int(grid["rows"])
    columns = int(grid["cols"])
    cells = output.get("cells", grid_output.get("cells", []))
    if rows <= 0 or columns <= 0 or not cells:
        raise ValueError("Rust native recovery returned an empty grid")
    return rows, columns, _rust_cells_to_project(
        cells, rows, columns
    )


def recover_cells_from_region(
    page: fitz.Page | Any,
    region_bbox: BBox,
) -> tuple[int, int, list[Cell]]:
    """Recover Chinese/mixed wireless cells from one trusted table region."""
    if hasattr(page, "schema_version") and hasattr(page, "text_blocks"):
        snapshot = page
    else:
        from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot

        snapshot = capture_page_snapshot(
            page,
            page_index=getattr(page, "number", 0),
            allowed_regions=[region_bbox],
        )

    mode = rust_adapter.get_rust_mode("wireless_structure")
    if mode in ("rust", "shadow"):
        def _recover_cells_from_region_rust():
            result = rust_adapter.recover_cells_from_snapshot(snapshot, region_bbox)
            if not isinstance(result, tuple) or len(result) != 3:
                raise TypeError("Rust native recovery result must be a (rows, cols, cells) tuple")
            rows, columns, cells = result
            if rows <= 0 or columns <= 0 or not cells:
                raise ValueError("Rust native recovery returned an empty grid")
            return result

        return rust_adapter.run_python_or_rust(
            mode=mode,
            python_fn=lambda: _recover_cells_from_snapshot_python(snapshot, region_bbox),
            rust_fn=_recover_cells_from_region_rust,
            path="wireless_structure.recover_cells_from_region",
        )
    else:
        return _recover_cells_from_snapshot_python(snapshot, region_bbox)
