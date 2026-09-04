# -*- coding: utf-8 -*-
from pathlib import Path
import pytest
import fitz

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region


def test_page_1014_table_recovery_integration():
    """集成测试：Page 1014 必须成功恢复出包含多级表头的 10 列无线大表。"""
    pdf_path = Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Page 1014 integration fixture is local-only and was not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    page = doc[1014]

    class NoWordsPage:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def get_text(self, kind, *args, **kwargs):
            if kind == "words":
                raise AssertionError("native-span recovery must not read page words")
            return self._wrapped.get_text(kind, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    bbox = BBox(83.6, 90.3, 754.2, 507.5)

    rows, cols, cells = recover_cells_from_region(NoWordsPage(page), bbox)
    assert rows >= 10, f"Expected at least 10 rows, got {rows}"
    assert cols >= 9, f"Expected at least 9 cols, got {cols}"

    # 验证没有槽位冲突，所有槽位唯一覆盖
    slot_counts = {}
    for cell in cells:
        assert 0 <= cell.row_index < rows
        assert 0 <= cell.col_index < cols
        assert cell.row_index + cell.rowspan <= rows
        assert cell.col_index + cell.colspan <= cols
        for row in range(cell.row_index, cell.row_index + cell.rowspan):
            for col in range(cell.col_index, cell.col_index + cell.colspan):
                slot_counts[(row, col)] = slot_counts.get((row, col), 0) + 1

    expected_slots = {(row, col) for row in range(rows) for col in range(cols)}
    assert set(slot_counts) == expected_slots
    assert set(slot_counts.values()) == {1}, "每个槽位必须恰好被 1 个单元格占用，不得有任何重叠冲突"

    cell_map = {(c.row_index, c.col_index): c for c in cells}

    # 验证左侧两端表头跨行 (rowspan=2)
    assert "被投资单位" in cell_map[(0, 0)].text
    assert cell_map[(0, 0)].rowspan == 2

    assert "期初余额" in cell_map[(0, 1)].text
    assert cell_map[(0, 1)].rowspan == 2

    # 验证本期增减变动位于 Row 0
    change_headers = [c for c in cells if c.row_index == 0 and "增减变动" in c.text]
    assert len(change_headers) == 1
    change_header = change_headers[0]
    assert change_header.rowspan == 1
    assert change_header.colspan >= 2

    # 验证其子表头位于 Row 1
    child_headers = [c for c in cells if c.row_index == 1 and ("投资" in c.text or "减值" in c.text)]
    assert len(child_headers) >= 2, f"子表头必须位于 Row 1, got {[c.text for c in cells if c.row_index == 1]}"
