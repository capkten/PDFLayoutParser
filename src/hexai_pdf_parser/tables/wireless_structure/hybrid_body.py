"""Recover the borderless body of a partially ruled Chinese table."""

from __future__ import annotations

import math
from typing import Any, Sequence

import fitz

from hexai_pdf_parser.core.models import BBox, Cell
from hexai_pdf_parser.tables.wireless_table_recovery import collect_native_spans

from .continuations import merge_column_continuations
from .grid import build_grid
from .logical_grid import build_logical_grid, materialize_empty_cells
from .merged_cells import merge_multiline_cells, merge_same_slot_fragments
from .span_chain import region_spans
from .text_runs import build_text_runs, infer_output_order_mode


def _column_bands(column_edges: Sequence[float]) -> list[dict[str, Any]]:
    """Turn trusted wired boundaries into stable one-based column bands."""
    ordered: list[float] = []
    for value in sorted(float(edge) for edge in column_edges):
        if not math.isfinite(value):
            continue
        if not ordered or value - ordered[-1] > 0.5:
            ordered.append(value)
    return [
        {"id": index, "x0": left, "x1": right, "support": 0, "y_support": 0}
        for index, (left, right) in enumerate(zip(ordered, ordered[1:]), 1)
        if right > left
    ]


def _overlap(left: float, right: float, band: dict[str, Any]) -> float:
    return max(0.0, min(right, band["x1"]) - max(left, band["x0"]))


def _assign_fixed_column_span(
    atom: dict[str, Any], bands: Sequence[dict[str, Any]]
) -> tuple[int, int] | None:
    """Assign an atom to fixed wired columns without treating line bleed as span."""
    if not bands:
        return None
    left = float(atom["bbox"][0])
    right = float(atom["bbox"][2])
    center = (left + right) / 2.0
    overlaps = [_overlap(left, right, band) for band in bands]
    center_index = min(
        range(len(bands)),
        key=lambda index: abs(center - (bands[index]["x0"] + bands[index]["x1"]) / 2.0),
    )

    significant: list[int] = []
    atom_width = max(1.0, right - left)
    for index, (band, overlap) in enumerate(zip(bands, overlaps)):
        band_width = max(1.0, float(band["x1"]) - float(band["x0"]))
        if overlap >= max(2.0, min(atom_width, band_width) * 0.18):
            significant.append(index)

    if len(significant) >= 2 and significant == list(
        range(significant[0], significant[-1] + 1)
    ):
        return significant[0] + 1, significant[-1] + 1
    return center_index + 1, center_index + 1


def _has_occupancy_conflict(cells: Sequence[dict[str, Any]]) -> bool:
    occupied: set[tuple[int, int]] = set()
    for cell in cells:
        for row in range(int(cell["row_start"]), int(cell["row_end"]) + 1):
            for column in range(int(cell["col_start"]), int(cell["col_end"]) + 1):
                slot = (row, column)
                if slot in occupied:
                    return True
                occupied.add(slot)
    return False


def _to_cells(cells: Sequence[dict[str, Any]]) -> tuple[int, int, list[Cell]]:
    converted = [
        Cell(
            text=str(item.get("text", "")).strip(),
            row_index=max(0, int(item["row_start"]) - 1),
            col_index=max(0, int(item["col_start"]) - 1),
            rowspan=max(1, int(item.get("rowspan", 1))),
            colspan=max(1, int(item.get("colspan", 1))),
            bbox=BBox(*item["bbox"]),
        )
        for item in cells
        if item.get("bbox")
    ]
    converted.sort(key=lambda cell: (cell.row_index, cell.col_index))
    row_count = max(
        (cell.row_index + max(1, cell.rowspan) for cell in converted),
        default=0,
    )
    column_count = max(
        (cell.col_index + max(1, cell.colspan) for cell in converted),
        default=0,
    )
    return row_count, column_count, converted


def recover_hybrid_body_cells(
    page: fitz.Page,
    region_bbox: BBox,
    column_edges: Sequence[float],
) -> tuple[int, int, list[Cell]]:
    """Recover rows inside a trusted wired body using native spans only.

    The wired table supplies the x topology.  This path deliberately skips
    wireless header inference because a numbered first body row can otherwise
    be mistaken for a header and split one wired column into pseudo-columns.
    """
    bands = _column_bands(column_edges)
    if not bands:
        return 0, 0, []

    try:
        native_spans = collect_native_spans(page, allowed_regions=[region_bbox])
        spans = region_spans(native_spans, region_bbox)
        output_mode = infer_output_order_mode(spans)
        atoms = build_text_runs(spans, output_mode=output_mode)
        if not atoms:
            return 0, 0, []

        for atom in atoms:
            column_span = _assign_fixed_column_span(atom, bands)
            if column_span is None:
                continue
            atom["column_id"] = column_span[0]
            atom["column_start"] = column_span[0]
            atom["column_end"] = column_span[1]

        candidates = merge_column_continuations(atoms, bands)
        if not candidates:
            return 0, 0, []
        physical_rows, columns, grid_cells, _issues = build_grid(candidates, bands)
        if not grid_cells:
            return 0, 0, []

        cells = merge_same_slot_fragments(grid_cells, header_cutoff=None)
        cells = merge_multiline_cells(
            cells, header_cutoff=None, output_mode=output_mode
        )
        if _has_occupancy_conflict(cells):
            return 0, 0, []

        logical_rows, logical_columns, logical_cells = build_logical_grid(
            physical_rows, columns, cells
        )
        if _has_occupancy_conflict(logical_cells):
            return 0, 0, []

        logical_cells = materialize_empty_cells(
            logical_rows,
            physical_rows,
            logical_columns,
            logical_cells,
            region_bbox,
        )
        if _has_occupancy_conflict(logical_cells):
            return 0, 0, []
        row_count, col_count, cells = _to_cells(logical_cells)
        if not _has_hybrid_structure_support(cells, row_count, col_count):
            return 0, 0, []
        return row_count, col_count, cells
    except Exception:
        return 0, 0, []


def _has_hybrid_structure_support(
    cells: Sequence[Cell], row_count: int, col_count: int
) -> bool:
    """Validate that recovered cells have true multi-row structural support.

    A genuine multi-row body in a multi-column table (col_count >= 2) must have
    synchronized multi-column alignment across rows or multiple distinct data rows
    supported by peer columns. A single column's multiline paragraph must not be
    fractured into pseudo-rows with empty peer cells.
    """
    if row_count < 2 or col_count < 2:
        return True

    non_empty_cells = [c for c in cells if c.text and c.text.strip()]
    if not non_empty_cells:
        return False

    multi_support_rows = 0
    for r in range(row_count):
        row_cells = [c for c in non_empty_cells if c.row_index == r]
        col_indices = {c.col_index for c in row_cells}
        has_colspan = any(c.colspan >= 2 for c in row_cells)
        if len(col_indices) >= 2 or has_colspan:
            multi_support_rows += 1

    cols_with_multiple_rows = sum(
        1
        for col_idx in range(col_count)
        if sum(1 for c in non_empty_cells if c.col_index == col_idx) >= 2
    )

    if multi_support_rows >= 2:
        return True
    if multi_support_rows >= 1 and cols_with_multiple_rows >= 2:
        return True

    return False
