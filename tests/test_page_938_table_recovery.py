# -*- coding: utf-8 -*-
from pathlib import Path

import fitz
import pytest

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.recoverer import (
    recover_cells_from_region,
)


PDF_PATH = Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf"


class NoWordsPage:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def get_text(self, kind, *args, **kwargs):
        if kind == "words":
            raise AssertionError("native-span recovery must not read page words")
        return self._wrapped.get_text(kind, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


@pytest.mark.skipif(not PDF_PATH.exists(), reason="local PDF fixture is unavailable")
def test_page_938_development_cost_table_recovers_wrapped_date():
    document = fitz.open(str(PDF_PATH))
    try:
        rows, columns, cells = recover_cells_from_region(
            NoWordsPage(document[938]),
            BBox(83.4, 117.1, 753.5, 425.4),
        )
    finally:
        document.close()

    assert (rows, columns) == (7, 7)

    occupied = []
    for cell in cells:
        occupied.extend(
            (row, column)
            for row in range(cell.row_index, cell.row_index + cell.rowspan)
            for column in range(cell.col_index, cell.col_index + cell.colspan)
        )
    assert len(occupied) == len(set(occupied)) == rows * columns

    cell_map = {(cell.row_index, cell.col_index): cell for cell in cells}
    assert "2022年6\n月开始陆续完工" in cell_map[(4, 2)].text
    assert cell_map[(6, 0)].text == "合计"
