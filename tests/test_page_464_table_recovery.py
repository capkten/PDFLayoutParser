# -*- coding: utf-8 -*-
from pathlib import Path
import pytest
import fitz

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.table_extractor import TableExtractor
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region


def test_page_464_top_table_recovery_integration():
    """集成测试：Page 464 顶部表格必须成功恢复出完整的 4x7 无线表格。"""
    pdf_path = Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Page 464 integration fixture is local-only and was not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    page = doc[464]

    class NoWordsPage:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def get_text(self, kind, *args, **kwargs):
            if kind == "words":
                raise AssertionError("native-span recovery must not read page words")
            return self._wrapped.get_text(kind, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    top_bbox = BBox(85.1, 97.9, 538.6, 218.3)

    rows, cols, cells = recover_cells_from_region(NoWordsPage(page), top_bbox)
    assert rows == 4, f"Expected 4 rows, got {rows}"
    assert cols == 7, f"Expected 7 cols, got {cols}"
    assert len(cells) == 28, f"Expected 28 cells, got {len(cells)}"

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

    # 验证表头 7 列分立
    assert "种类" in cell_map[(0, 0)].text
    assert "期初余额" in cell_map[(0, 1)].text
    assert "本期新增补" in cell_map[(0, 2)].text
    assert "入损益的金" in cell_map[(0, 3)].text
    assert "其他" in cell_map[(0, 4)].text
    assert "变动" in cell_map[(0, 4)].text
    assert "期末余额" in cell_map[(0, 5)].text
    assert "损益的列报项" in cell_map[(0, 6)].text

    # 验证合计行第 5 列（其他变动占位符）与第 6 列（期末余额）完全分离
    assert "合计" in cell_map[(3, 0)].text
    assert cell_map[(3, 1)].text == "84,756,954.96"
    assert cell_map[(3, 2)].text == "2,514,100.00"
    assert cell_map[(3, 3)].text == "12,314,982.25"
    assert cell_map[(3, 4)].text == "--"
    assert cell_map[(3, 5)].text == "74,956,072.71"
    assert cell_map[(3, 6)].text == "--"


def test_page_464_table_extractor_finds_both_tables():
    """页面级测试：TableExtractor 在 Page 464 必须成功提取全部 2 张表格。"""
    pdf_path = Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Page 464 integration fixture is local-only and was not found: {pdf_path}")

    model_path = Path(__file__).resolve().parents[1] / "src" / "hexai_pdf_parser" / "ml" / "table_detector_model" / "best.onnx"
    doc = fitz.open(str(pdf_path))
    page = doc[464]

    extractor = TableExtractor(ml_model_path=str(model_path))
    tables = extractor.extract(page)

    assert len(tables) == 2, f"Expected 2 tables on page 464, got {len(tables)}"
    t0, t1 = tables[0], tables[1]
    assert t0.rows == 4 and t0.cols == 7
    assert t1.rows == 26 and t1.cols == 4
