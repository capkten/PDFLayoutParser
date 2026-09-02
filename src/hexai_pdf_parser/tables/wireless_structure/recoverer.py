"""Production adapter for the isolated Chinese wireless-table pipeline."""

from __future__ import annotations

from typing import Any

import fitz

from hexai_pdf_parser.core.models import BBox, Cell
from hexai_pdf_parser.tables.wireless_table_recovery import collect_native_spans

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
    rescue_sparse_body_bands,
)
from .logical_grid import build_logical_grid, materialize_empty_cells, merge_header_spans
from .merged_cells import merge_multiline_cells, merge_same_slot_fragments
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


def recover_cells_from_region(
    page: fitz.Page,
    region_bbox: BBox,
) -> tuple[int, int, list[Cell]]:
    """Recover Chinese/mixed wireless cells from one trusted table region."""
    try:
        native_spans = collect_native_spans(page, allowed_regions=[region_bbox])
        spans = region_spans(native_spans, region_bbox)
        output_mode = infer_output_order_mode(spans)
        atoms = build_text_runs(spans, output_mode=output_mode)
        bands = infer_column_bands(atoms, region_bbox)
        bands = prune_paired_cjk_artifact_bands(atoms, bands)
        bands = prune_sparse_alignment_artifact_bands(atoms, bands)
        if not atoms or len(bands) < 2:
            return 0, 0, []

        atoms = merge_same_band_native_line_runs(atoms, bands)
        bands, header_cutoff = refine_leaf_bands(atoms, bands)
        bands = rescue_sparse_body_bands(atoms, bands, header_cutoff)
        if len(bands) < 1:
            return 0, 0, []

        annotate_columns(atoms, bands, header_cutoff, region_bbox)
        candidates = merge_column_continuations(atoms, bands)
        physical_rows, columns, grid_cells, _issues = build_grid(candidates, bands)
        if not grid_cells:
            return 0, 0, []

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
