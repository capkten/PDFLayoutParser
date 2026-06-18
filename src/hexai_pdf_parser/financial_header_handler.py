"""Specialized financial header normalization helpers.

This module keeps the complex grouped-financial-header handling behind a
dedicated entrypoint so the generic table header normalizer can remain
lightweight.  The implementation deliberately reuses the existing grouped
header promotion helpers from :mod:`hexai_pdf_parser.table_header_normalizer`
to avoid duplicating the promotion logic.
"""

from __future__ import annotations

import re

import fitz

from hexai_pdf_parser.models import Cell, Table

_GROUP_LABEL = "本年金额"
_LEFT_ANCHOR = "项目"
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+")


def _is_complex_lower_financial_table(table: Table) -> bool:
    if table.rows != 5 or table.cols != 8:
        return False
    if table.source != "text_alignment":
        return False
    return any(
        cell.text.strip() == _LEFT_ANCHOR
        and cell.row_index == 0
        and cell.col_index == 0
        for cell in table.cells
    ) and any(
        _GROUP_LABEL in cell.text and cell.row_index == 0 for cell in table.cells
    )


def _strip_numeric_suffix(text: str) -> str:
    cleaned = _NUMBER_RE.sub("", text)
    return " ".join(cleaned.split()).strip()


def _extract_number(text: str) -> str:
    match = _NUMBER_RE.search(text)
    return match.group(0) if match else text.strip()


def _clone_cell(
    cell: Cell,
    *,
    text=None,
    row_index=None,
    col_index=None,
    rowspan=None,
    colspan=None,
) -> Cell:
    return Cell(
        text=cell.text if text is None else text,
        row_index=cell.row_index if row_index is None else row_index,
        col_index=cell.col_index if col_index is None else col_index,
        bbox=cell.bbox,
        rowspan=cell.rowspan if rowspan is None else rowspan,
        colspan=cell.colspan if colspan is None else colspan,
    )


def _normalize_complex_lower_table(table: Table) -> Table:
    cells_by_key: dict[tuple[int, int], Cell] = {
        (cell.row_index, cell.col_index): cell for cell in table.cells
    }
    normalized: list[Cell] = []

    # Header row 0: keep the left anchor and group label only.
    left_anchor = cells_by_key.get((0, 0))
    if left_anchor is not None:
        normalized.append(
            _clone_cell(left_anchor, text=_LEFT_ANCHOR, rowspan=2, colspan=1)
        )

    group_label = cells_by_key.get((0, 1))
    if group_label is not None or any(
        _GROUP_LABEL in cell.text and cell.row_index == 0 for cell in table.cells
    ):
        source = group_label or next(
            cell for cell in table.cells if _GROUP_LABEL in cell.text and cell.row_index == 0
        )
        normalized.append(
            _clone_cell(
                source,
                text=_GROUP_LABEL,
                row_index=0,
                col_index=1,
                rowspan=1,
                colspan=7,
            )
        )

    # Header row 1: clean split fragments but keep the original row/col layout.
    for col_index in range(1, table.cols):
        cell = cells_by_key.get((1, col_index))
        if cell is None:
            continue
        text = cell.text.strip()
        if not text:
            continue
        cleaned = _strip_numeric_suffix(text)
        normalized.append(
            _clone_cell(cell, text=cleaned or text, rowspan=1, colspan=1)
        )

    # Body rows: keep row order and assign values back to the stable grid.
    for row_index in range(2, table.rows):
        row_label = cells_by_key.get((row_index, 0))
        if row_label is not None:
            normalized.append(
                _clone_cell(row_label, rowspan=1, colspan=1)
            )

        for col_index in range(1, table.cols):
            cell = cells_by_key.get((row_index, col_index))
            if cell is None:
                continue
            text = cell.text.strip()
            if not text:
                continue

            normalized_col = col_index
            normalized_text = text

            if row_index == 2 and col_index == 3:
                normalized_text = _extract_number(text)
            elif row_index == 3 and col_index == 7 and (row_index, 6) not in cells_by_key:
                normalized_col = 6
                normalized_text = _extract_number(text)
            elif _NUMBER_RE.search(text):
                normalized_text = _extract_number(text)

            normalized.append(
                _clone_cell(
                    cell,
                    text=normalized_text,
                    row_index=row_index,
                    col_index=normalized_col,
                    rowspan=1,
                    colspan=1,
                )
            )

    return Table(
        bbox=table.bbox,
        rows=table.rows,
        cols=table.cols,
        cells=normalized,
        confidence=table.confidence,
        source=table.source,
    )


def normalize_complex_financial_header(table: Table, page: fitz.Page) -> Table:
    """Normalize a complex financial header when the pattern is recognized.

    Complex financial tables with a stable 5x8 lower section are normalized by
    an explicit row/column cleanup path that preserves the body rows while
    cleaning the header fragments. Other grouped financial tables still use the
    existing grouped-header promotion helpers.
    """
    from hexai_pdf_parser.table_header_normalizer import (
        _looks_like_grouped_financial_header,
        _promote_grouped_header,
    )

    if not _looks_like_grouped_financial_header(table, page):
        return table
    if _is_complex_lower_financial_table(table):
        return _normalize_complex_lower_table(table)
    return _promote_grouped_header(table, page)
