# -*- coding: utf-8 -*-
from pathlib import Path

import fitz
import pytest

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.recoverer import (
    recover_cells_from_region,
)


PDF_PATH = Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf"


def _assert_complete_occupancy(rows, columns, cells):
    occupied = []
    for cell in cells:
        assert 0 <= cell.row_index < rows
        assert 0 <= cell.col_index < columns
        assert cell.row_index + cell.rowspan <= rows
        assert cell.col_index + cell.colspan <= columns
        occupied.extend(
            (row, column)
            for row in range(cell.row_index, cell.row_index + cell.rowspan)
            for column in range(cell.col_index, cell.col_index + cell.colspan)
        )
    assert len(occupied) == len(set(occupied)) == rows * columns


@pytest.mark.skipif(not PDF_PATH.exists(), reason="local PDF fixture is unavailable")
def test_page_435_ageing_table_preserves_two_header_tiers():
    """435 页账龄表不能因松动 bbox 的行聚类冲突而整表丢失。"""
    document = fitz.open(str(PDF_PATH))
    try:
        rows, columns, cells = recover_cells_from_region(
            document[435],
            BBox(67.0, 597.7, 522.9, 722.5),
        )
    finally:
        document.close()

    assert (rows, columns) == (7, 5)
    _assert_complete_occupancy(rows, columns, cells)

    cell_map = {(cell.row_index, cell.col_index): cell for cell in cells}
    assert cell_map[(0, 0)].text == "账龄"
    assert cell_map[(0, 0)].rowspan == 2
    assert cell_map[(0, 1)].text == "期末余额"
    assert cell_map[(0, 1)].colspan == 2
    assert cell_map[(0, 3)].text == "上年年末余额"
    assert cell_map[(0, 3)].colspan == 2
    assert cell_map[(1, 1)].text == "金额"
    assert cell_map[(1, 2)].text == "比例（%）"
    assert cell_map[(1, 3)].text == "金额"
    assert cell_map[(1, 4)].text == "比例（%）"


@pytest.mark.skipif(not PDF_PATH.exists(), reason="local PDF fixture is unavailable")
def test_page_436_tables_keep_independent_shapes():
    """436 页相邻表格的已有结构不因行聚类改动而改变。"""
    document = fitz.open(str(PDF_PATH))
    try:
        regions = [
            BBox(67.3, 149.8, 523.0, 242.8),
            BBox(68.3, 272.8, 523.2, 447.9),
            BBox(69.7, 477.6, 522.3, 578.0),
            BBox(83.6, 635.0, 506.1, 771.6),
        ]
        shapes = [
            recover_cells_from_region(document[436], region)[:2]
            for region in regions
        ]
    finally:
        document.close()

    assert shapes == [(5, 3), (10, 3), (6, 7), (5, 5)]
