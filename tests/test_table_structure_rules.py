"""Tests for the parameter-based table structure rule engine."""

import pytest

from hexai_pdf_parser.models import BBox, Cell, Table
from hexai_pdf_parser.table_config import StructureRuleSet
from hexai_pdf_parser.table_structure_rules import (
    TableStructureCandidate,
    _identify_header_rows,
    _select_main_columns,
    _trim_trailing_summary_rows,
    apply_structure_rules,
)


def _make_table(rows: int, cols: int, cell_texts: list[str] | None = None) -> Table:
    cells = []
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            text = cell_texts[idx] if cell_texts and idx < len(cell_texts) else ""
            cells.append(
                Cell(
                    text=text,
                    row_index=r,
                    col_index=c,
                    bbox=BBox(c * 50, r * 20, c * 50 + 45, r * 20 + 18),
                )
            )
    return Table(
        bbox=BBox(0, 0, cols * 50, rows * 20),
        rows=rows,
        cols=cols,
        cells=cells,
        confidence=1.0,
        source="line_projection",
    )


class TestIdentifyHeaderRows:
    def test_marks_header_rows(self):
        candidate = TableStructureCandidate(rows=5, cols=3, cells=[])
        result = _identify_header_rows(candidate, header_row_count=2)
        assert result.header_rows == 2
        assert result.diagnostics["header_rows"] == 2

    def test_clamps_to_total_rows(self):
        candidate = TableStructureCandidate(rows=1, cols=3, cells=[])
        result = _identify_header_rows(candidate, header_row_count=5)
        assert result.header_rows == 1

    def test_zero_header_rows(self):
        candidate = TableStructureCandidate(rows=5, cols=3, cells=[])
        result = _identify_header_rows(candidate, header_row_count=0)
        assert result.header_rows == 0


class TestSelectMainColumns:
    def test_selects_valid_columns(self):
        candidate = TableStructureCandidate(rows=5, cols=4, cells=[])
        result = _select_main_columns(candidate, [0, 2])
        assert result.main_columns == [0, 2]

    def test_filters_out_of_range(self):
        candidate = TableStructureCandidate(rows=5, cols=3, cells=[])
        result = _select_main_columns(candidate, [0, 5, -1])
        assert result.main_columns == [0]

    def test_empty_selection_passthrough(self):
        candidate = TableStructureCandidate(rows=5, cols=3, cells=[])
        result = _select_main_columns(candidate, [])
        assert result.main_columns == []


class TestTrimTrailingSummaryRows:
    def test_trims_summary_row(self):
        table = _make_table(3, 2, ["A", "B", "1", "2", "合计", "100"])
        candidate = TableStructureCandidate(
            rows=3, cols=2, cells=list(table.cells)
        )
        result = _trim_trailing_summary_rows(candidate)
        assert result.rows == 2
        assert result.diagnostics.get("trimmed_trailing") is True

    def test_no_trim_without_summary(self):
        table = _make_table(3, 2, ["A", "B", "1", "2", "3", "4"])
        candidate = TableStructureCandidate(
            rows=3, cols=2, cells=list(table.cells)
        )
        result = _trim_trailing_summary_rows(candidate)
        assert result.rows == 3

    def test_single_row_no_trim(self):
        candidate = TableStructureCandidate(rows=1, cols=2, cells=[])
        result = _trim_trailing_summary_rows(candidate)
        assert result.rows == 1


class TestApplyStructureRules:
    def test_disabled_rules_return_original(self):
        table = _make_table(3, 2)
        rules = StructureRuleSet(enabled=False)
        result = apply_structure_rules(rules, table)
        assert result is table

    def test_trim_trailing_summary(self):
        table = _make_table(4, 2, ["H1", "H2", "A", "1", "B", "2", "合计", "3"])
        rules = StructureRuleSet(trim_trailing_summary=True)
        result = apply_structure_rules(rules, table)
        assert result.rows == 3

    def test_no_op_when_rules_dont_change_shape(self):
        table = _make_table(3, 2, ["A", "B", "1", "2", "3", "4"])
        rules = StructureRuleSet(header_rows=1)
        result = apply_structure_rules(rules, table)
        # header_rows alone doesn't change the Table shape
        assert result is table

    def test_combined_header_and_trim(self):
        table = _make_table(4, 2, ["H1", "H2", "A", "1", "B", "2", "总计", "3"])
        rules = StructureRuleSet(header_rows=1, trim_trailing_summary=True)
        result = apply_structure_rules(rules, table)
        assert result.rows == 3
