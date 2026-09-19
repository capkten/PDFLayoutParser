import os
import hashlib
import json
import math
import traceback
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple

from . import _pdf_fast

Line4 = Tuple[float, float, float, float]

VALID_MODES = {"python", "shadow", "rust"}
_ROUTING_DIAGNOSTICS: List[Dict[str, Any]] = []


def _normalize_diagnostic_path(path: Any) -> str:
    if isinstance(path, str) and path.strip():
        return path.strip()
    return "unknown"


def get_diagnostics() -> List[Dict[str, Any]]:
    """Return a copy of the current routing diagnostics."""
    return list(_ROUTING_DIAGNOSTICS)


def clear_diagnostics() -> None:
    """Clear collected routing diagnostics."""
    _ROUTING_DIAGNOSTICS.clear()


def get_rust_mode(path: str = "") -> str:
    """Get the active rust execution mode for the given path or globally."""
    mode = None
    if path:
        env_key = f"PDF_RUST_MODE_{path.upper().replace('/', '_').replace('-', '_')}"
        mode = os.environ.get(env_key)
    if not mode:
        mode = os.environ.get("PDF_RUST_MODE", "python")
    mode = mode.strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid PDF_RUST_MODE '{mode}'. Allowed modes are: {sorted(list(VALID_MODES))}"
        )
    return mode


def assert_equivalent(path: str, python_value: Any, rust_value: Any) -> None:
    """Assert that python and rust outputs are equivalent, recording mismatch diagnostic on difference."""
    if python_value != rust_value:
        diag = {
            "schema_version": 1,
            "status": "rust_output_mismatch",
            "path": _normalize_diagnostic_path(path),
            "field": "__root__",
            "python_value": {"str_val": str(python_value)},
            "rust_value": {"str_val": str(rust_value)},
            "classification": "defect",
        }
        _ROUTING_DIAGNOSTICS.append(diag)
        raise AssertionError(f"Output mismatch on path '{path}': Python={python_value!r} != Rust={rust_value!r}")


def run_python_or_rust(mode: str, python_fn, rust_fn, input_dto: Any = None, path: str = ""):
    """Execute Python or Rust according to mode contract."""
    if not isinstance(mode, str):
        raise ValueError(f"Invalid mode '{mode}'. Allowed modes are: {sorted(list(VALID_MODES))}")
    m = mode.strip().lower()
    if m not in VALID_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Allowed modes are: {sorted(list(VALID_MODES))}")
    diagnostic_path = _normalize_diagnostic_path(path)

    if m == "python":
        return python_fn()

    if m == "rust":
        try:
            if input_dto is not None:
                return rust_fn(input_dto)
            return rust_fn()
        except Exception as exc:
            tb_str = traceback.format_exc()
            diag = {
                "schema_version": 1,
                "status": "rust_fallback",
                "path": diagnostic_path,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback_id": tb_str[-200:],
            }
            _ROUTING_DIAGNOSTICS.append(diag)
            return python_fn()

    if m == "shadow":
        py_res = python_fn()
        try:
            if input_dto is not None:
                r_res = rust_fn(input_dto)
            else:
                r_res = rust_fn()
            if py_res != r_res:
                diag = {
                    "schema_version": 1,
                    "status": "rust_output_mismatch",
                    "path": diagnostic_path,
                    "field": "__root__",
                    "python_value": {"str_val": str(py_res)},
                    "rust_value": {"str_val": str(r_res)},
                    "classification": "defect",
                }
                _ROUTING_DIAGNOSTICS.append(diag)
        except Exception as exc:
            tb_str = traceback.format_exc()
            diag = {
                "schema_version": 1,
                "status": "rust_fallback",
                "path": diagnostic_path,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback_id": tb_str[-200:],
            }
            _ROUTING_DIAGNOSTICS.append(diag)
        return py_res


def _snapshot_value(value: Any, path: str = "snapshot") -> Any:
    if isinstance(value, Mapping):
        return {str(key): _snapshot_value(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    raise TypeError(f"{path} contains unsupported value type {type(value).__name__}")


def _snapshot_field(snapshot: Any, name: str) -> Any:
    try:
        return getattr(snapshot, name)
    except AttributeError as exc:
        raise ValueError(f"snapshot is missing required field '{name}'") from exc


def _rect_input(value: Any, path: str) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        if "bbox" in value:
            value = value["bbox"]
        elif "rect" in value and not all(name in value for name in ("x0", "y0", "x1", "y1")):
            value = value["rect"]
        elif not all(name in value for name in ("x0", "y0", "x1", "y1")):
            raise ValueError(f"{path} must contain x0, y0, x1, y1")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        if isinstance(value, Mapping):
            values = [value[name] for name in ("x0", "y0", "x1", "y1")]
        else:
            raise ValueError(f"{path} must be a four-coordinate sequence")
    else:
        values = list(value)
    return {
        "schema_version": 1,
        "x0": float(values[0]),
        "y0": float(values[1]),
        "x1": float(values[2]),
        "y1": float(values[3]),
    }


def _raw_position(record: Mapping[str, Any], length: int, path: str) -> List[int]:
    value = record.get("raw_source_position", record.get("source_position"))
    if isinstance(value, Mapping):
        value = [value.get("block"), value.get("line")]
    if not isinstance(value, (list, tuple)) or len(value) < length:
        raise ValueError(f"{path} must contain a source position of length {length}")
    return [int(item) for item in value[:length]]


def _character_to_rust_input(character: Mapping[str, Any], order: int) -> Dict[str, Any]:
    position = character.get("source_order", order)
    return {
        "schema_version": 1,
        "text": str(character.get("c", character.get("text", ""))),
        "rect": _rect_input(character.get("bbox", character.get("rect")), "character.rect"),
        "order": int(position),
    }


def _span_to_rust_input(span: Mapping[str, Any], fallback_order: int) -> Dict[str, Any]:
    position = _raw_position(span, 3, "span.raw_source_position")
    characters = span.get("chars", span.get("characters", ())) or ()
    return {
        "schema_version": 1,
        "text": str(span.get("text", "")),
        "rect": _rect_input(span.get("bbox", span.get("rect")), "span.rect"),
        "font": None if span.get("font") is None else str(span.get("font")),
        "size": None if span.get("size") is None else float(span["size"]),
        "flags": None if span.get("flags") is None else int(span["flags"]),
        "order": int(span.get("source_order", span.get("order", fallback_order))),
        "characters": [
            _character_to_rust_input(character, index)
            for index, character in enumerate(characters)
        ],
        "source_position": {
            "schema_version": 1,
            "block": position[0],
            "line": position[1],
        },
        "block": position[0],
        "line": position[1],
    }


def _text_line_to_rust_input(line: Mapping[str, Any], fallback_order: int) -> Dict[str, Any]:
    position = _raw_position(line, 2, "line.raw_source_position")
    spans = line.get("spans", ()) or ()
    return {
        "schema_version": 1,
        "rect": _rect_input(line.get("bbox", line.get("rect")), "line.rect"),
        "spans": [
            _span_to_rust_input(span, index) for index, span in enumerate(spans)
        ],
        "source_position": position,
        "source_order": int(line.get("source_order", fallback_order)),
    }


def _text_block_to_rust_input(block: Mapping[str, Any], fallback_order: int) -> Dict[str, Any]:
    position = _raw_position(block, 1, "block.raw_source_position")
    lines = block.get("lines", ()) or ()
    return {
        "schema_version": 1,
        "rect": _rect_input(block.get("bbox", block.get("rect")), "block.rect"),
        "lines": [
            _text_line_to_rust_input(line, index) for index, line in enumerate(lines)
        ],
        "source_position": position,
        "source_order": int(block.get("source_order", fallback_order)),
    }


def _drawing_to_rust_input(drawing: Mapping[str, Any], fallback_order: int) -> Dict[str, Any]:
    known = {
        "type", "kind", "rect", "color", "fill", "stroke", "clip", "opacity",
        "fill_opacity", "width", "items", "source_order", "schema_version",
    }
    result: Dict[str, Any] = {
        "schema_version": 1,
        "kind": str(drawing.get("kind", drawing.get("type", ""))),
        "lines": [],
        "rect": _rect_input(drawing.get("rect"), "drawing.rect"),
        "fill": _snapshot_value(drawing.get("fill")),
        "stroke": _snapshot_value(drawing.get("stroke")),
        "clip": None if drawing.get("clip") is None else _rect_input(drawing["clip"], "drawing.clip"),
        "source_order": int(drawing.get("source_order", fallback_order)),
    }
    for key in ("color", "opacity", "fill_opacity", "width", "items"):
        if key in drawing:
            result[key] = _snapshot_value(drawing[key])
    extra = {key: _snapshot_value(value) for key, value in drawing.items() if key not in known}
    if extra:
        result["extra"] = extra
    return result


def _region_to_rust_input(region: Any, source_order: int, allowed: bool) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "rect": _rect_input(region, "region.rect"),
        "source_order": int(source_order),
        "allowed": bool(allowed),
    }


def page_snapshot_to_rust_input(snapshot: Any) -> Dict[str, Any]:
    """Copy the algorithm-facing, owned DTO from an already captured snapshot."""
    schema_version = int(_snapshot_field(snapshot, "schema_version"))
    if schema_version != 1:
        raise ValueError(f"Unsupported schema_version: {schema_version}, expected 1")
    geometry = _snapshot_field(snapshot, "geometry")
    if not isinstance(geometry, Mapping):
        raise ValueError("snapshot.geometry must be an object")
    page = {
        "schema_version": 1,
        "width": float(geometry["width"]),
        "height": float(geometry["height"]),
        "rotation": int(geometry["rotation"]),
    }
    blocks = _snapshot_field(snapshot, "text_blocks")
    spans = _snapshot_field(snapshot, "spans")
    words = _snapshot_field(snapshot, "words")
    drawings = _snapshot_field(snapshot, "drawings")
    allowed_regions = _snapshot_field(snapshot, "allowed_regions")
    excluded_regions = _snapshot_field(snapshot, "excluded_regions")
    extraction_options = _snapshot_field(snapshot, "extraction_options")
    return {
        "schema_version": 1,
        "page_index": int(_snapshot_field(snapshot, "page_index")),
        "page": page,
        "text_blocks": [
            _text_block_to_rust_input(block, index) for index, block in enumerate(blocks)
        ],
        "spans": [_span_to_rust_input(span, index) for index, span in enumerate(spans)],
        "words": [
            {
                "schema_version": 1,
                "text": str(word["text"]),
                "rect": _rect_input(word.get("bbox", word.get("rect")), "word.rect"),
                "order": int(word.get("source_order", word.get("order", index))),
                "block": int(word.get("block_index", word.get("block", 0))),
                "line": int(word.get("line_index", word.get("line", 0))),
            }
            for index, word in enumerate(words)
        ],
        "drawings": [
            _drawing_to_rust_input(drawing, index)
            for index, drawing in enumerate(drawings)
        ],
        "allowed_regions": [
            _region_to_rust_input(region, index, True)
            for index, region in enumerate(allowed_regions)
        ],
        "excluded_regions": [
            _region_to_rust_input(region, index, False)
            for index, region in enumerate(excluded_regions)
        ],
        "extraction_options": {
            "schema_version": 1,
            "options": _snapshot_value(extraction_options),
        },
    }


def stage_input_digest(stage_dto: Mapping[str, Any]) -> str:
    """Hash an owned stage DTO using the shared canonical JSON contract."""
    if not isinstance(stage_dto, Mapping):
        raise ValueError("stage DTO must be an object")
    encoded = json.dumps(
        _snapshot_value(stage_dto),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def page_snapshot_digest(snapshot_dto: Mapping[str, Any]) -> str:
    """Validate and hash a normalized PageSnapshotDto through Rust."""
    return _pdf_fast.page_snapshot_digest(dict(snapshot_dto))


def recover_native_text_input(
    snapshot: Any,
    *,
    region: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the raw-span stage input without rereading the captured page."""
    snapshot_dto = (
        page_snapshot_to_rust_input(snapshot)
        if not isinstance(snapshot, Mapping)
        else _snapshot_value(snapshot)
    )
    input_digest = stage_input_digest(snapshot_dto)
    selected_region = region
    if selected_region is None:
        selected_region = snapshot_dto["allowed_regions"][0] if snapshot_dto["allowed_regions"] else None
    return {
        "schema_version": 1,
        "stage": "recover_native_text_input",
        "input_snapshot_digest": input_digest,
        "page_index": snapshot_dto["page_index"],
        "region": None if selected_region is None else _snapshot_value(selected_region),
        "spans": _snapshot_value(snapshot_dto["spans"]),
    }



def merge_h_lines(lines: List[Line4], merge_group_tol: float) -> List[Line4]:
    owned_lines = [tuple(float(value) for value in line) for line in lines]
    merged_lines = _pdf_fast.merge_h_lines(owned_lines, float(merge_group_tol))
    return [tuple(float(value) for value in line) for line in merged_lines]


def merge_v_lines(
    lines: List[Line4],
    h_lines: Optional[List[Line4]] = None,
    merge_group_tol: float = 0.3,
    line_tolerance: float = 2.3,
) -> List[Line4]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    owned_h = [tuple(float(v) for v in line) for line in (h_lines or [])]
    merged = _pdf_fast.merge_v_lines(
        owned_lines, owned_h, float(merge_group_tol), float(line_tolerance)
    )
    return [tuple(float(v) for v in line) for line in merged]


def merge_region_line_coordinates(
    lines: List[Line4],
    horizontal: bool,
    tolerance: float = 2.3,
) -> List[Line4]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    merged = _pdf_fast.merge_region_line_coordinates(
        owned_lines, bool(horizontal), float(tolerance)
    )
    return [tuple(float(v) for v in line) for line in merged]


def lines_intersect(
    h_line: Line4,
    v_line: Line4,
    tolerance: float = 2.3,
) -> bool:
    return _pdf_fast.lines_intersect(
        tuple(float(v) for v in h_line),
        tuple(float(v) for v in v_line),
        float(tolerance),
    )


def find_table_regions(
    h_lines: List[Line4],
    v_lines: List[Line4],
    tolerance: float = 2.3,
) -> List[Tuple[Dict[str, Any], List[Line4], List[Line4]]]:
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    regions = _pdf_fast.find_table_regions(owned_h, owned_v, float(tolerance))
    res = []
    for bbox, comp_h, comp_v in regions:
        res.append((
            bbox,
            [tuple(float(v) for v in l) for l in comp_h],
            [tuple(float(v) for v in l) for l in comp_v],
        ))
    return res


def snap_coordinates(
    coords: List[float],
    anchor_coords: List[float],
    tol: float = 1.5,
) -> List[float]:
    return _pdf_fast.snap_coordinates(
        [float(c) for c in coords],
        [float(a) for a in anchor_coords],
        float(tol),
    )


def snap_grid_coordinates(
    start: float,
    end: float,
    orthogonal_start: float,
    orthogonal_end: float,
    lines: List[Line4],
    horizontal: bool,
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> List[float]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    return _pdf_fast.snap_grid_coordinates(
        float(start),
        float(end),
        float(orthogonal_start),
        float(orthogonal_end),
        owned_lines,
        bool(horizontal),
        float(tolerance),
        float(merge_group_tol),
    )


def complete_partial_outer_boundaries(
    bbox: Dict[str, Any],
    h_lines: List[Line4],
    v_lines: List[Line4],
    h_ys: List[float],
    v_xs: List[float],
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> Tuple[List[Line4], List[Line4]]:
    if "schema_version" not in bbox:
        bbox = {"schema_version": 1, **bbox}
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    eff_h, eff_v = _pdf_fast.complete_partial_outer_boundaries(
        bbox,
        owned_h,
        owned_v,
        [float(y) for y in h_ys],
        [float(x) for x in v_xs],
        float(tolerance),
        float(merge_group_tol),
    )
    return (
        [tuple(float(v) for v in line) for line in eff_h],
        [tuple(float(v) for v in line) for line in eff_v],
    )


def build_cells_for_region(
    bbox: Dict[str, Any],
    h_lines: List[Line4],
    v_lines: List[Line4],
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> List[Dict[str, Any]]:
    if "schema_version" not in bbox:
        bbox = {"schema_version": 1, **bbox}
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    return _pdf_fast.build_cells_for_region(
        bbox,
        owned_h,
        owned_v,
        float(tolerance),
        float(merge_group_tol),
    )


def trim_ghost_edge_rows(
    cells: List[Dict[str, Any]],
    h_lines: List[Line4],
    tol: float = 2.0,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    return _pdf_fast.trim_ghost_edge_rows(owned_cells, owned_h, float(tol))


def merge_oversegmented_line_columns(
    cells: List[Dict[str, Any]],
    tolerance: float = 2.3,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)
    return _pdf_fast.merge_oversegmented_line_columns(owned_cells, float(tolerance))


def assign_text_to_line_cells(
    cells: List[Dict[str, Any]],
    words: List[Dict[str, Any]],
    chars: Optional[List[Dict[str, Any]]] = None,
    tolerance: float = 2.3,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)

    owned_words = []
    for w in words:
        w_dict = dict(w)
        if "schema_version" not in w_dict:
            w_dict["schema_version"] = 1
        rect = w_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            w_dict["rect"] = {"schema_version": 1, **rect}
        owned_words.append(w_dict)

    owned_chars = []
    if chars:
        for ch in chars:
            ch_dict = dict(ch)
            if "schema_version" not in ch_dict:
                ch_dict["schema_version"] = 1
            rect = ch_dict["rect"]
            if isinstance(rect, dict) and "schema_version" not in rect:
                ch_dict["rect"] = {"schema_version": 1, **rect}
            owned_chars.append(ch_dict)

    return _pdf_fast.assign_text_to_line_cells(
        owned_cells,
        owned_words,
        owned_chars,
        float(tolerance),
    )


def extract_wired_region(input_data: Dict[str, Any]) -> Dict[str, Any]:
    if "schema_version" not in input_data:
        input_data = {"schema_version": 1, **input_data}
    return _pdf_fast.extract_wired_region(input_data)


def roundtrip_dto(dto_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _pdf_fast.roundtrip_dto(str(dto_type), data)


def rect_overlap(
    a: Dict[str, Any],
    b: Dict[str, Any],
    strict: bool = True,
) -> bool:
    a_dict = dict(a)
    if "schema_version" not in a_dict:
        a_dict["schema_version"] = 1
    b_dict = dict(b)
    if "schema_version" not in b_dict:
        b_dict["schema_version"] = 1
    return _pdf_fast.rect_overlap(a_dict, b_dict, bool(strict))


def filter_regions(
    regions: List[Dict[str, Any]],
    excluded: Optional[List[Dict[str, Any]]] = None,
    allowed: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    owned_regions = []
    for r in regions:
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_regions.append(d)
    owned_excluded = []
    for r in (excluded or []):
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_excluded.append(d)
    owned_allowed = []
    for r in (allowed or []):
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_allowed.append(d)
    return _pdf_fast.filter_regions(owned_regions, owned_excluded, owned_allowed)


def cluster_rows(
    items: List[Dict[str, Any]],
    tolerance: float,
) -> List[Dict[str, Any]]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.cluster_rows(owned_items, float(tolerance))


def cluster_columns(
    items: List[Dict[str, Any]],
    tolerance: float,
) -> List[Dict[str, Any]]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.cluster_columns(owned_items, float(tolerance))


def stable_output_order(
    tables: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    owned_tables = []
    for t in tables:
        d = dict(t)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        cells = d.get("cells", [])
        owned_cells = []
        for c in cells:
            cd = dict(c)
            if "schema_version" not in cd:
                cd["schema_version"] = 1
            cr = cd.get("rect")
            if isinstance(cr, dict) and "schema_version" not in cr:
                cd["rect"] = {"schema_version": 1, **cr}
            owned_cells.append(cd)
        d["cells"] = owned_cells
        owned_tables.append(d)
    return _pdf_fast.stable_output_order(owned_tables)


def build_text_runs(
    spans: List[Dict[str, Any]],
    region: Dict[str, Any],
) -> List[Dict[str, Any]]:
    owned_region = dict(region)
    if "schema_version" not in owned_region:
        owned_region["schema_version"] = 1
    owned_spans = []
    for s in spans:
        d = dict(s)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        sp = d.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            d["source_position"] = {"schema_version": 1, **sp}
        chars = d.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        d["characters"] = owned_chars
        owned_spans.append(d)
    return _pdf_fast.build_text_runs(owned_spans, owned_region)


def build_atoms(
    runs: List[Dict[str, Any]],
    region: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    owned_runs = []
    for r in runs:
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_runs.append(d)
    owned_region = None
    if region is not None:
        owned_region = dict(region)
        if "schema_version" not in owned_region:
            owned_region["schema_version"] = 1
    return _pdf_fast.build_atoms(owned_runs, owned_region)


def merge_wrapped_rows(
    atoms: List[Dict[str, Any]],
    tolerance: float = 5.0,
) -> List[Dict[str, Any]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    return _pdf_fast.merge_wrapped_rows(owned_atoms, float(tolerance))


def infer_output_order_mode(
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.infer_output_order_mode(owned_items)


def recover_native_candidates(
    input_dto: Dict[str, Any],
) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    page = dict(d["page"])
    if "schema_version" not in page:
        page["schema_version"] = 1
    d["page"] = page
    region = dict(d["region"])
    if "schema_version" not in region:
        region["schema_version"] = 1
    r_rect = region.get("rect")
    if isinstance(r_rect, dict) and "schema_version" not in r_rect:
        region["rect"] = {"schema_version": 1, **r_rect}
    d["region"] = region
    config = dict(d["config"])
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config
    owned_spans = []
    for s in d.get("spans", []):
        sd = dict(s)
        if "schema_version" not in sd:
            sd["schema_version"] = 1
        rect = sd.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            sd["rect"] = {"schema_version": 1, **rect}
        sp = sd.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            sd["source_position"] = {"schema_version": 1, **sp}
        chars = sd.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        sd["characters"] = owned_chars
        owned_spans.append(sd)
    d["spans"] = owned_spans
    return _pdf_fast.recover_native_candidates(d)


def infer_column_bands(
    atoms: List[Dict[str, Any]],
    region: Dict[str, Any],
) -> List[Dict[str, Any]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    r = dict(region)
    if "schema_version" not in r:
        r["schema_version"] = 1
    return _pdf_fast.infer_column_bands(owned_atoms, r)


def refine_leaf_bands(
    atoms: List[Dict[str, Any]],
    bands: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    owned_bands = []
    for b in bands:
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        owned_bands.append(bd)
    return _pdf_fast.refine_leaf_bands(owned_atoms, owned_bands)


def build_grid(
    atoms: List[Dict[str, Any]],
    bands: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    owned_bands = []
    for b in bands:
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        owned_bands.append(bd)
    return _pdf_fast.build_grid(owned_atoms, owned_bands)


def _ensure_atom_dto(a: Any, idx: int = 0) -> Dict[str, Any]:
    ad = dict(a) if isinstance(a, dict) else (a.__dict__.copy() if hasattr(a, "__dict__") else {})
    if "schema_version" not in ad:
        ad["schema_version"] = 1
    rect = ad.get("rect")
    if isinstance(rect, dict) and "schema_version" not in rect:
        ad["rect"] = {"schema_version": 1, **rect}
    elif isinstance(rect, (list, tuple)) and len(rect) >= 4:
        ad["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif "bbox" in ad:
        b = ad["bbox"]
        if isinstance(b, (list, tuple)) and len(b) >= 4:
            ad["rect"] = {"schema_version": 1, "x0": float(b[0]), "y0": float(b[1]), "x1": float(b[2]), "y1": float(b[3])}
        elif isinstance(b, dict):
            ad["rect"] = {"schema_version": 1, "x0": float(b["x0"]), "y0": float(b["y0"]), "x1": float(b["x1"]), "y1": float(b["y1"])}
        elif hasattr(b, "x0") and hasattr(b, "y0"):
            ad["rect"] = {"schema_version": 1, "x0": float(b.x0), "y0": float(b.y0), "x1": float(b.x1), "y1": float(b.y1)}
    ad.setdefault("run_refs", [idx])
    ad.setdefault("row_hint", None)
    ad.setdefault("col_hint", None)
    ad.setdefault("order", idx)
    ad.setdefault("text", "")
    return ad


def build_logical_grid(
    atoms: List[Dict[str, Any]],
    grid: Dict[str, Any],
) -> Dict[str, Any]:
    owned_atoms = [_ensure_atom_dto(a, idx) for idx, a in enumerate(atoms)]
    g = dict(grid)
    if "schema_version" not in g:
        g["schema_version"] = 1
    return _pdf_fast.build_logical_grid(owned_atoms, g)


def recover_native_region(
    input_dto: Dict[str, Any],
) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    region = dict(d["region"])
    if "schema_version" not in region:
        region["schema_version"] = 1
    r_rect = region.get("rect")
    if isinstance(r_rect, dict) and "schema_version" not in r_rect:
        region["rect"] = {"schema_version": 1, **r_rect}
    d["region"] = region
    config = dict(d.get("config", {}))
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config
    owned_atoms = [_ensure_atom_dto(a, idx) for idx, a in enumerate(d.get("atoms", []))]
    d["atoms"] = owned_atoms
    owned_bands = []
    for idx, b in enumerate(d.get("bands", [])):
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        bd.setdefault("source_atoms", [])
        bd.setdefault("order", idx)
        owned_bands.append(bd)
    d["bands"] = owned_bands
    return _pdf_fast.recover_native_region(d)


def table_quality(candidate: Dict[str, Any]) -> float:
    c = dict(candidate)
    if "schema_version" not in c:
        c["schema_version"] = 1
    rect = c.get("rect")
    if isinstance(rect, dict) and "schema_version" not in rect:
        c["rect"] = {"schema_version": 1, **rect}
    owned_cells = []
    for cell in c.get("cells", []):
        cd = dict(cell)
        if "schema_version" not in cd:
            cd["schema_version"] = 1
        c_rect = cd.get("rect")
        if isinstance(c_rect, dict) and "schema_version" not in c_rect:
            cd["rect"] = {"schema_version": 1, **c_rect}
        owned_cells.append(cd)
    c["cells"] = owned_cells
    return float(_pdf_fast.table_quality(c))


def select_candidates(
    candidates: List[Dict[str, Any]],
    excluded: Optional[List[Dict[str, Any]]] = None,
    allowed: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    owned_candidates = []
    for cand in candidates:
        c = dict(cand)
        if "schema_version" not in c:
            c["schema_version"] = 1
        rect = c.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            c["rect"] = {"schema_version": 1, **rect}
        owned_cells = []
        for cell in c.get("cells", []):
            cd = dict(cell)
            if "schema_version" not in cd:
                cd["schema_version"] = 1
            c_rect = cd.get("rect")
            if isinstance(c_rect, dict) and "schema_version" not in c_rect:
                cd["rect"] = {"schema_version": 1, **c_rect}
            owned_cells.append(cd)
        c["cells"] = owned_cells
        owned_candidates.append(c)

    owned_excluded = []
    for ex in (excluded or []):
        d = dict(ex)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_excluded.append(d)

    owned_allowed = []
    for al in (allowed or []):
        d = dict(al)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_allowed.append(d)

    return _pdf_fast.select_candidates(owned_candidates, owned_excluded, owned_allowed)


def recover_wireless_tables(input_dto: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    page = dict(d["page"])
    if "schema_version" not in page:
        page["schema_version"] = 1
    d["page"] = page

    owned_spans = []
    for s in d.get("spans", []):
        sd = dict(s)
        if "schema_version" not in sd:
            sd["schema_version"] = 1
        rect = sd.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            sd["rect"] = {"schema_version": 1, **rect}
        sp = sd.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            sd["source_position"] = {"schema_version": 1, **sp}
        chars = sd.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        sd["characters"] = owned_chars
        owned_spans.append(sd)
    d["spans"] = owned_spans

    owned_regions = []
    for r in d.get("regions", []):
        rd = dict(r)
        if "schema_version" not in rd:
            rd["schema_version"] = 1
        r_rect = rd.get("rect")
        if isinstance(r_rect, dict) and "schema_version" not in r_rect:
            rd["rect"] = {"schema_version": 1, **r_rect}
        owned_regions.append(rd)
    d["regions"] = owned_regions

    config = dict(d["config"])
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config

    return _pdf_fast.recover_wireless_tables(d)
def _ensure_background_dto(bg: Dict[str, Any], default_order: int = 0) -> Dict[str, Any]:
    b = dict(bg)
    if "schema_version" not in b:
        b["schema_version"] = 1
    rect = b.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        b["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        b["rect"] = {"schema_version": 1, **rect}
    if "source_order" not in b:
        b["source_order"] = default_order
    if "color" not in b:
        b["color"] = None
    if "opacity" not in b:
        b["opacity"] = None
    return b


def _ensure_word_dto(word: Dict[str, Any], default_order: int = 0) -> Dict[str, Any]:
    w = dict(word)
    if "schema_version" not in w:
        w["schema_version"] = 1
    rect = w.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        w["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        w["rect"] = {"schema_version": 1, **rect}
    if "order" not in w:
        w["order"] = default_order
    if "block" not in w:
        w["block"] = None
    if "line" not in w:
        w["line"] = None
    return w


def _ensure_region_dto(reg: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(reg)
    if "schema_version" not in r:
        r["schema_version"] = 1
    rect = r.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        r["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        r["rect"] = {"schema_version": 1, **rect}
    if "source_order" not in r:
        r["source_order"] = 0
    if "allowed" not in r:
        r["allowed"] = True
    return r


def _ensure_config_dto(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = dict(cfg or {})
    if "schema_version" not in c:
        c["schema_version"] = 1
    c.setdefault("line_tolerance", 2.0)
    c.setdefault("row_tolerance", 2.0)
    c.setdefault("column_tolerance", 2.0)
    c.setdefault("span_tolerance", 2.0)
    c.setdefault("numeric_tolerance", 2.0)
    return c


def group_backgrounds(
    backgrounds: List[Dict[str, Any]],
    gap_threshold: float = 30.0,
) -> List[List[Dict[str, Any]]]:
    owned = [_ensure_background_dto(b, idx) for idx, b in enumerate(backgrounds)]
    return _pdf_fast.group_backgrounds(owned, float(gap_threshold))


def detect_zebra_rows(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    page = dict(d.get("page", {}))
    if "schema_version" not in page:
        page["schema_version"] = 1
    d["page"] = page
    d["backgrounds"] = [_ensure_background_dto(b, idx) for idx, b in enumerate(d.get("backgrounds", []))]
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.detect_zebra_rows(d)


def assign_words_to_zebra_rows(
    words: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    row_tol: float = 2.0,
) -> List[Dict[str, Any]]:
    owned_words = [_ensure_word_dto(w, idx) for idx, w in enumerate(words)]
    owned_rows = []
    for idx, r in enumerate(rows):
        rd = dict(r)
        if "schema_version" not in rd:
            rd["schema_version"] = 1
        rect = rd.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            rd["rect"] = {"schema_version": 1, **rect}
        elif isinstance(rect, (list, tuple)) and len(rect) >= 4:
            rd["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
        rd.setdefault("row_index", idx)
        rd.setdefault("source_backgrounds", [])
        rd.setdefault("words", [])
        rd.setdefault("cells", [])
        owned_rows.append(rd)
    return _pdf_fast.assign_words_to_zebra_rows(owned_words, owned_rows, float(row_tol))


def infer_english_columns(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["backgrounds"] = [_ensure_background_dto(b, idx) for idx, b in enumerate(d.get("backgrounds", []))]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.infer_english_columns(d)


def build_english_cells(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["backgrounds"] = [_ensure_background_dto(b, idx) for idx, b in enumerate(d.get("backgrounds", []))]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.build_english_cells(d)


def build_general_wireless_cells(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    owned_atoms = []
    for idx, a in enumerate(d.get("atoms", [])):
        ad = dict(a)
        if "schema_version" not in ad:
            ad["schema_version"] = 1
        rect = ad.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            ad["rect"] = {"schema_version": 1, **rect}
        elif isinstance(rect, (list, tuple)) and len(rect) >= 4:
            ad["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
        ad.setdefault("run_refs", [idx])
        ad.setdefault("row_hint", None)
        ad.setdefault("col_hint", None)
        ad.setdefault("order", idx)
        owned_atoms.append(ad)
    d["atoms"] = owned_atoms
    owned_bands = []
    for idx, b in enumerate(d.get("bands", [])):
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        bd.setdefault("source_atoms", [])
        bd.setdefault("order", idx)
        owned_bands.append(bd)
    d["bands"] = owned_bands
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.build_general_wireless_cells(d)


def build_legacy_text_alignment(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.build_legacy_text_alignment(d)


def _ensure_cell_dto(c: Dict[str, Any]) -> Dict[str, Any]:
    cd = dict(c)
    if "schema_version" not in cd:
        cd["schema_version"] = 1
    rect = cd.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        cd["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        cd["rect"] = {"schema_version": 1, **rect}
    cd.setdefault("text", "")
    cd.setdefault("row", 0)
    cd.setdefault("col", 0)
    cd.setdefault("rowspan", 1)
    cd.setdefault("colspan", 1)
    cd.setdefault("source", None)
    return cd


def _ensure_inner_grid_dto(g: Dict[str, Any]) -> Dict[str, Any]:
    gd = dict(g)
    if "schema_version" not in gd:
        gd["schema_version"] = 1
    gd.setdefault("rows", 0)
    gd.setdefault("cols", 0)
    gd.setdefault("row_edges", [])
    gd.setdefault("col_edges", [])
    gd.setdefault("occupancy", [])
    return gd


def infer_header_structure(input_dto: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    grid = dict(d.get("grid", {}))
    if "schema_version" not in grid:
        grid["schema_version"] = 1
    inner_g = _ensure_inner_grid_dto(grid.get("grid", {}))
    grid["grid"] = inner_g
    grid["cells"] = [_ensure_cell_dto(c) for c in grid.get("cells", [])]
    grid.setdefault("empty_slots", [])
    d["grid"] = grid
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.infer_header_structure(d)


def merge_header_spans(input_dto: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    grid = dict(d.get("grid", {}))
    if "schema_version" not in grid:
        grid["schema_version"] = 1
    inner_g = _ensure_inner_grid_dto(grid.get("grid", {}))
    grid["grid"] = inner_g
    grid["cells"] = [_ensure_cell_dto(c) for c in grid.get("cells", [])]
    grid.setdefault("empty_slots", [])
    d["grid"] = grid
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.merge_header_spans(d)


def normalize_financial_header_tokens(input_dto: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["cells"] = [_ensure_cell_dto(c) for c in d.get("cells", [])]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.normalize_financial_header_tokens(d)
