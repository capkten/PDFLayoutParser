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
def test_page_987_mixed_leaf_headers_share_one_logical_header_row():
    document = fitz.open(str(PDF_PATH))
    try:
        rows, columns, cells = recover_cells_from_region(
            NoWordsPage(document[987]),
            BBox(84.2, 91.1, 506.2, 362.5),
        )
    finally:
        document.close()

    assert (rows, columns) == (6, 7)
    assert len(cells) == 36

    occupied = []
    for cell in cells:
        occupied.extend(
            (row, column)
            for row in range(cell.row_index, cell.row_index + cell.rowspan)
            for column in range(cell.col_index, cell.col_index + cell.colspan)
        )
    assert len(occupied) == len(set(occupied)) == rows * columns == 42

    cell_map = {(cell.row_index, cell.col_index): cell for cell in cells}
    assert cell_map[(0, 4)].colspan == 2
    assert all(cell_map[(0, column)].rowspan == 2 for column in range(4))
    assert cell_map[(0, 6)].rowspan == 2

    direct = next(cell for cell in cells if cell.text == "直接")
    indirect = next(cell for cell in cells if cell.text.replace("\n", "") == "间接")
    assert direct.row_index == indirect.row_index == 1
    assert not any(
        cell.row_index < 2 and not cell.text.strip()
        for cell in cells
    )
