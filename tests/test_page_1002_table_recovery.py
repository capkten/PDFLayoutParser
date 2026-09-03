# -*- coding: utf-8 -*-
from pathlib import Path
import pytest
import fitz

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region
from hexai_pdf_parser.tables.table_extractor import TableExtractor


def test_page_1002_table_recovery_integration():
    """集成测试：Page 1002 必须成功恢复包含多级表头与首列空槽的 6 列无线大表。"""
    candidates = [
        Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf",
        Path(__file__).resolve().parents[2] / "fix" / "zh_all_table_pages.pdf",
        Path(r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf"),
    ]
    pdf_path = next((p for p in candidates if p.exists()), None)
    if not pdf_path:
        pytest.skip("Page 1002 integration fixture is local-only and was not found")

    doc = fitz.open(str(pdf_path))
    page = doc[1002]

    class NoWordsPage:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def get_text(self, kind, *args, **kwargs):
            if kind == "words":
                raise AssertionError("native-span recovery must not read page words")
            return self._wrapped.get_text(kind, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    bbox = BBox(82.5, 90.2, 505.9, 590.7)

    rows, cols, cells = recover_cells_from_region(NoWordsPage(page), bbox)
    assert rows == 25, f"Expected 25 rows, got {rows}"
    assert cols == 6, f"Expected 6 cols, got {cols}"

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

    # 验证表头多级与跨度结构
    assert "项目名称" in cell_map[(0, 0)].text
    assert cell_map[(0, 0)].colspan == 1
    assert cell_map[(0, 0)].rowspan == 3

    assert "关联方" in cell_map[(0, 1)].text
    assert cell_map[(0, 1)].colspan == 1
    assert cell_map[(0, 1)].rowspan == 3

    assert "期末余额" in cell_map[(0, 2)].text
    assert cell_map[(0, 2)].colspan == 2
    assert cell_map[(0, 2)].rowspan == 2

    assert "上年年末余额" in cell_map[(0, 4)].text
    assert cell_map[(0, 4)].colspan == 2
    assert cell_map[(0, 4)].rowspan == 2

    # 子表头
    assert "账面余额" in cell_map[(2, 2)].text
    assert "坏账准备" in cell_map[(2, 3)].text
    assert "账面余额" in cell_map[(2, 4)].text
    assert "坏账准备" in cell_map[(2, 5)].text

    # 正文首行数据与独立物化的首列空单元格
    assert cell_map[(3, 0)].text == ""
    assert "海农食品" in cell_map[(3, 1)].text
    assert "7,213,813.76" in cell_map[(3, 2)].text


def test_page_1002_full_page_extractor_finds_both_tables():
    """全页测试：TableExtractor 在 Page 1002 必须提取出 2 张表格。"""
    candidates = [
        Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf",
        Path(__file__).resolve().parents[2] / "fix" / "zh_all_table_pages.pdf",
        Path(r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf"),
    ]
    pdf_path = next((p for p in candidates if p.exists()), None)
    if not pdf_path:
        pytest.skip("Page 1002 integration fixture is local-only and was not found")

    doc = fitz.open(str(pdf_path))
    page = doc[1002]

    extractor = TableExtractor()
    tables = extractor.extract(page)

    assert len(tables) == 2, f"Expected 2 tables on Page 1002, got {len(tables)}"
    assert tables[0].rows == 25
    assert tables[0].cols == 6
    assert tables[0].source == "wireless_span_recovery"

    assert tables[1].rows == 7
    assert tables[1].cols == 4
