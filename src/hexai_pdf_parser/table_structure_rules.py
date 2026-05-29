"""Parameter-based table structure rule engine.

Applies structure-level corrections to table candidates based on a matched
layout profile's :class:`StructureRuleSet`.  This module is independent from
page-level region candidate generation — it only adjusts the internal
structure (header rows, main columns, trailing rows) of already-identified
table regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hexai_pdf_parser.models import BBox, Cell, Table
from hexai_pdf_parser.table_config import StructureRuleSet


@dataclass
class TableStructureCandidate:
    """Intermediate structure representation during rule processing."""

    rows: int
    cols: int
    cells: List[Cell]
    header_rows: int = 0
    main_columns: List[int] = field(default_factory=list)
    guides: List[float] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def _identify_header_rows(
    candidate: TableStructureCandidate,
    header_row_count: int,
) -> TableStructureCandidate:
    """Mark the top *header_row_count* rows as header rows."""
    if header_row_count <= 0 or candidate.rows == 0:
        return candidate

    actual_header = min(header_row_count, candidate.rows)
    return TableStructureCandidate(
        rows=candidate.rows,
        cols=candidate.cols,
        cells=list(candidate.cells),
        header_rows=actual_header,
        main_columns=list(candidate.main_columns),
        guides=list(candidate.guides),
        diagnostics={**candidate.diagnostics, "header_rows": actual_header},
    )


def _select_main_columns(
    candidate: TableStructureCandidate,
    main_columns: List[int],
) -> TableStructureCandidate:
    """Select the specified main columns from the table."""
    if not main_columns:
        return candidate

    valid_columns = [c for c in main_columns if 0 <= c < candidate.cols]
    return TableStructureCandidate(
        rows=candidate.rows,
        cols=candidate.cols,
        cells=list(candidate.cells),
        header_rows=candidate.header_rows,
        main_columns=valid_columns,
        guides=list(candidate.guides),
        diagnostics={**candidate.diagnostics, "main_columns": valid_columns},
    )


def _trim_trailing_summary_rows(
    candidate: TableStructureCandidate,
) -> TableStructureCandidate:
    """Remove trailing rows that look like summary or page totals.

    A trailing row is considered a summary if its text matches common summary
    patterns (合计, 总计, 小计, etc.) and it is the last data row.
    """
    if candidate.rows <= 1 or not candidate.cells:
        return candidate

    cells_by_row: Dict[int, List[Cell]] = {}
    for cell in candidate.cells:
        cells_by_row.setdefault(cell.row_index, []).append(cell)

    last_row_idx = candidate.rows - 1
    last_cells = cells_by_row.get(last_row_idx, [])

    SUMMARY_PATTERNS = ("合计", "总计", "小计", "Total", "Sum", "Page")
    is_summary = any(
        any(pat in cell.text for pat in SUMMARY_PATTERNS)
        for cell in last_cells
    )

    if not is_summary:
        return candidate

    trimmed_rows = candidate.rows - 1
    trimmed_cells = [c for c in candidate.cells if c.row_index < trimmed_rows]

    return TableStructureCandidate(
        rows=trimmed_rows,
        cols=candidate.cols,
        cells=trimmed_cells,
        header_rows=candidate.header_rows,
        main_columns=list(candidate.main_columns),
        guides=list(candidate.guides),
        diagnostics={
            **candidate.diagnostics,
            "trimmed_trailing": True,
            "original_rows": candidate.rows,
        },
    )


def apply_structure_rules(
    rules: StructureRuleSet,
    table: Table,
) -> Table:
    """Apply structure rules to a table and return a corrected Table.

    If rules are disabled or have no corrections, returns the original table
    unchanged.
    """
    if not rules.enabled:
        return table

    candidate = TableStructureCandidate(
        rows=table.rows,
        cols=table.cols,
        cells=list(table.cells),
    )

    # 1. Identify header rows
    if rules.header_rows > 0:
        candidate = _identify_header_rows(candidate, rules.header_rows)

    # 2. Select main columns
    if rules.main_columns:
        candidate = _select_main_columns(candidate, rules.main_columns)

    # 3. Trim trailing summary rows
    if rules.trim_trailing_summary:
        candidate = _trim_trailing_summary_rows(candidate)

    # Build corrected table if rows changed
    if candidate.rows == table.rows and candidate.cols == table.cols:
        return table

    return Table(
        bbox=table.bbox,
        rows=candidate.rows,
        cols=candidate.cols,
        cells=candidate.cells,
        confidence=table.confidence,
        source=table.source,
    )
