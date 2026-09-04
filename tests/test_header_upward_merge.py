import os
from pathlib import Path
import pytest
import pymupdf as fitz
from hexai_pdf_parser.core.models import Cell, BBox
from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor


def test_normalize_headers_upward_merge_without_parent_with_grandparent():
    """测试多层表头场景（存在祖父级大标题 Row 0）：
    Row 0: 大标题跨全列 (colspan=4)
    Row 1: Col 0~1 有母表头 (colspan=2)
    Row 2: Col 0 是 2023，Col 1 是 2024（有母表头）
           Col 2 (Less FX Effect) 和 Col 3 (As Reported) 在 Row 1 无母表头且无横线，
           必须向上合并至 Row 1 并获得 rowspan=2。
    """
    extractor = EnglishTableExtractor()
    columns = [
        (100.0, 200.0),  # Col 0
        (200.0, 300.0),  # Col 1
        (300.0, 400.0),  # Col 2: Less FX Effect
        (400.0, 500.0),  # Col 3: As Reported
    ]

    # Row 0: 祖父大标题跨全列
    c_grand = Cell(text="Grand Header", row_index=0, col_index=0, bbox=BBox(100, 0, 500, 15), colspan=4, rowspan=1)
    # Row 1: Col 0~1 的母表头
    c_parent = Cell(text="Three Months Ended", row_index=1, col_index=0, bbox=BBox(100, 20, 300, 35), colspan=2, rowspan=1)
    # Row 2: 子表头与单列表头
    c_child1 = Cell(text="2023", row_index=2, col_index=0, bbox=BBox(100, 40, 200, 55), colspan=1, rowspan=1)
    c_child2 = Cell(text="2024", row_index=2, col_index=1, bbox=BBox(200, 40, 300, 55), colspan=1, rowspan=1)
    c_leaf1 = Cell(text="Less FX Effect", row_index=2, col_index=2, bbox=BBox(300, 40, 400, 55), colspan=1, rowspan=1)
    c_leaf2 = Cell(text="As Reported", row_index=2, col_index=3, bbox=BBox(400, 40, 500, 55), colspan=1, rowspan=1)

    raw_cells = [c_grand, c_parent, c_child1, c_child2, c_leaf1, c_leaf2]
    norm_cells, num_rows = extractor._normalize_headers(raw_cells, columns, page=None)

    assert num_rows == 3

    # Row 0 祖父大标题
    grand_res = next(c for c in norm_cells if c.text == "Grand Header")
    assert grand_res.row_index == 0
    assert grand_res.colspan == 4

    # Row 1 母表头
    parent_res = next(c for c in norm_cells if c.text == "Three Months Ended")
    assert parent_res.row_index == 1
    assert parent_res.col_index == 0
    assert parent_res.colspan == 2
    assert parent_res.rowspan == 1

    # Row 2 子表头
    child1_res = next(c for c in norm_cells if c.text == "2023")
    assert child1_res.row_index == 2 and child1_res.rowspan == 1
    child2_res = next(c for c in norm_cells if c.text == "2024")
    assert child2_res.row_index == 2 and child2_res.rowspan == 1

    # Col 2 & Col 3 在 Row 1 无母表头，应向上合并至 Row 1 并获得 rowspan=2
    leaf1_res = next(c for c in norm_cells if c.text == "Less FX Effect")
    assert leaf1_res.row_index == 1, f"Expected leaf1 in row 1, got row {leaf1_res.row_index}"
    assert leaf1_res.col_index == 2
    assert leaf1_res.rowspan == 2, f"Expected leaf1 rowspan=2, got {leaf1_res.rowspan}"

    leaf2_res = next(c for c in norm_cells if c.text == "As Reported")
    assert leaf2_res.row_index == 1, f"Expected leaf2 in row 1, got row {leaf2_res.row_index}"
    assert leaf2_res.col_index == 3
    assert leaf2_res.rowspan == 2, f"Expected leaf2 rowspan=2, got {leaf2_res.rowspan}"


def test_normalize_headers_rejects_upward_merge_with_horizontal_line():
    """反例测试：若两层之间在当前列存在物理横线阻断，严格禁止跨线向上合并。"""
    extractor = EnglishTableExtractor()
    columns = [
        (100.0, 200.0),
        (200.0, 300.0),
        (300.0, 400.0),
    ]

    c_parent = Cell(text="Three Months Ended", row_index=0, col_index=0, bbox=BBox(100, 10, 300, 25), colspan=2, rowspan=1)
    c_child1 = Cell(text="2023", row_index=1, col_index=0, bbox=BBox(100, 30, 200, 45), colspan=1, rowspan=1)
    c_child2 = Cell(text="2024", row_index=1, col_index=1, bbox=BBox(200, 30, 300, 45), colspan=1, rowspan=1)
    c_leaf = Cell(text="Standalone Underlined", row_index=1, col_index=2, bbox=BBox(300, 30, 400, 45), colspan=1, rowspan=1)

    class MockPage:
        def get_drawings(self):
            return [{
                "items": [("l", fitz.Point(300, 27), fitz.Point(400, 27))],
                "color": (0, 0, 0),
                "fill": None
            }]
    page = MockPage()

    raw_cells = [c_parent, c_child1, c_child2, c_leaf]
    norm_cells, num_rows = extractor._normalize_headers(raw_cells, columns, page=page)

    leaf_res = next(c for c in norm_cells if c.text == "Standalone Underlined")
    assert leaf_res.row_index == 1
    assert leaf_res.rowspan == 1


def test_page_075_table_headers_upward_merge():
    """集成测试：Page 075 Table 1 和 Table 2 中的单列表头应整齐向上合并，消除空白槽位。"""
    pdf_path = r"C:\Users\92410\Desktop\git\hexai_pdf_parser\src\hexai_pdf_parser\data\en_all_pages\problem\en_all_table_pages_page_075.pdf"
    doc = fitz.open(pdf_path)
    page = doc[0]
    extractor = EnglishTableExtractor()
    tables = extractor.extract(page)

    assert len(tables) >= 2

    for t_idx, t in enumerate(tables[:2]):
        occupied = set()
        for c in t.cells:
            for r in range(c.row_index, c.row_index + c.rowspan):
                for col in range(c.col_index, c.col_index + c.colspan):
                    slot = (r, col)
                    assert slot not in occupied, f"Table {t_idx+1}: duplicate occupancy at {slot} by '{c.text}'"
                    occupied.add(slot)

        rows = {}
        for c in t.cells:
            rows.setdefault(c.row_index, []).append(c)

        # 检查 Table 1 / Table 2 的表头结构：
        # Col 3 (Less FX Effect) 和 Col 4 (Constant Currency Revenues) 在 Row 1 向上合并，且 rowspan=3
        row1_cells = {c.col_index: c for c in rows[1]}
        assert 3 in row1_cells, f"Table {t_idx+1}: Col 3 should be in Row 1"
        assert row1_cells[3].rowspan == 3, f"Table {t_idx+1}: Col 3 rowspan should be 3, got {row1_cells[3].rowspan}"
        assert "Less FX Effect" in row1_cells[3].text

        # Col 5 (As Reported) 在 Row 2（隶属于 % Change from Prior Period），且 rowspan=2
        row2_cells = {c.col_index: c for c in rows[2]}
        assert 5 in row2_cells, f"Table {t_idx+1}: Col 5 should be in Row 2"
        assert row2_cells[5].rowspan == 2, f"Table {t_idx+1}: Col 5 rowspan should be 2, got {row2_cells[5].rowspan}"
        assert "As Reported" in row2_cells[5].text


        row3_cells = {c.col_index: c for c in rows[3]}
        assert 1 in row3_cells and "2023" in row3_cells[1].text and row3_cells[1].rowspan == 1
        assert 2 in row3_cells and "2024" in row3_cells[2].text and row3_cells[2].rowspan == 1

