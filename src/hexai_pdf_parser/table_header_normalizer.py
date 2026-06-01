"""Table header normalizer.

Post-processes extracted :class:`Table` objects to normalize grouped
financial headers.  Many Chinese financial reports use a two-row header
where the first row contains a group label (e.g. "本年金额") spanning
several detail columns, and the first column acts as a left anchor
(e.g. "项目") spanning both header rows.

PyMuPDF's ``find_tables`` sometimes misinterprets this layout, assigning
colspan=1 to the group label and rowspan=1 to the left anchor.  This
module detects that pattern and corrects the spans.
"""

from __future__ import annotations

import fitz

from hexai_pdf_parser.models import BBox, Cell, Table

# Phrases that typically appear as grouped financial header labels.
_GROUP_LABEL_PATTERNS: list[str] = [
    "本年金额",
    "本期金额",
    "上年金额",
    "上期金额",
    "本年发生额",
    "本期发生额",
    "上年发生额",
    "上期发生额",
]


def normalize_table_headers(table: Table, page: fitz.Page) -> Table:
    """Post-process a table to normalize grouped financial headers.

    Applies generic normalisation first, then detects and promotes
    grouped financial headers when the pattern is recognised.
    *page* is reserved for future page-text-based detection.
    """
    table = _normalize_generic_table(table)
    if _looks_like_grouped_financial_header(table, page):
        return _promote_grouped_header(table, page)
    return table


def _normalize_generic_table(table: Table) -> Table:
    """Apply generic header normalisation rules.

    Currently this is a pass-through that preserves existing
    rowspan/colspan values.  It exists as a hook for future
    normalisation logic that applies to all tables regardless of
    financial header structure.
    """
    return table


def _looks_like_grouped_financial_header(table: Table, page: fitz.Page) -> bool:
    """Return *True* if *table* has a grouped financial header pattern.

    Detection criteria:
    1. A cell whose text matches a known group-label phrase (e.g. "本年金额")
       is present in the table.
    2. A cell in column 0 whose text equals "项目" acts as a left anchor.
    3. The table has at least 3 columns (group label + at least 2 detail).
    """
    if table.cols < 3:
        return False

    has_group_label = False
    has_left_anchor = False

    for cell in table.cells:
        text = cell.text.strip()
        if text == "项目" and cell.col_index == 0:
            has_left_anchor = True
        if cell.row_index == 0:
            for pattern in _GROUP_LABEL_PATTERNS:
                if pattern in text:
                    has_group_label = True
                    break

    return has_group_label and has_left_anchor


def _promote_grouped_header(table: Table, page: fitz.Page) -> Table:
    """Promote a detected grouped financial header.

    Adjustments made:
    - The group-label cell's colspan is set to ``table.cols - 1``
      (spanning all columns except the left anchor).
    - The left-anchor cell ("项目") in column 0 has its rowspan set to 2.
    - All body cells are left unchanged.
    """
    promoted_cells: list[Cell] = []

    for cell in table.cells:
        text = cell.text.strip()

        # Promote group label: extend colspan to cover all non-anchor columns.
        is_group_label = any(pattern in text for pattern in _GROUP_LABEL_PATTERNS)
        if is_group_label:
            promoted_cells.append(
                Cell(
                    text=cell.text,
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                    bbox=cell.bbox,
                    rowspan=cell.rowspan,
                    colspan=table.cols - 1,
                )
            )
            continue

        # Promote left anchor: extend rowspan to cover both header rows.
        if text == "项目" and cell.col_index == 0:
            promoted_cells.append(
                Cell(
                    text=cell.text,
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                    bbox=cell.bbox,
                    rowspan=2,
                    colspan=cell.colspan,
                )
            )
            continue

        promoted_cells.append(cell)

    return Table(
        bbox=table.bbox,
        rows=table.rows,
        cols=table.cols,
        cells=promoted_cells,
        confidence=table.confidence,
        source=table.source,
    )
