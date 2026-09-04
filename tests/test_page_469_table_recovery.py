# -*- coding: utf-8 -*-
from pathlib import Path
import pytest
import pymupdf as fitz
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.table_extractor import TableExtractor
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region


PDF_PATH = Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf"
if not PDF_PATH.exists():
    PDF_PATH = Path("D:/codes/PDFLayoutParser/fix/zh_all_table_pages.pdf")

MODEL_PATH = Path(__file__).resolve().parents[1] / "src" / "hexai_pdf_parser" / "ml" / "table_detector_model" / "best.onnx"
if not MODEL_PATH.exists():
    MODEL_PATH = Path("D:/codes/PDFLayoutParser/src/hexai_pdf_parser/ml/table_detector_model/best.onnx")


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
def test_page_469_recovers_both_tables_without_words_readback():
    doc = fitz.open(str(PDF_PATH))
    try:
        page = NoWordsPage(doc[469])
        extractor = TableExtractor(ml_model_path=str(MODEL_PATH))
        tables = extractor.extract(page)
    finally:
        doc.close()

    # Must extract both Table 1 (top continuation table) and Table 2 (bottom table)
    assert len(tables) == 2, f"Expected 2 tables on page 469, but got {len(tables)}"

    top_table = tables[0]
    bottom_table = tables[1]

    # Top continuation table checks
    assert top_table.source == "wireless_span_recovery"
    assert top_table.rows == 3
    assert top_table.cols == 6

    # Verify cell structure of top table
    occupied_slots = set()
    for cell in top_table.cells:
        for r in range(cell.row_index, cell.row_index + cell.rowspan):
            for c in range(cell.col_index, cell.col_index + cell.colspan):
                slot = (r, c)
                assert slot not in occupied_slots, f"Occupancy conflict at slot {slot}"
                occupied_slots.add(slot)

    # Verify key cells in top table
    cells_by_pos = {(c.row_index, c.col_index): c for c in top_table.cells}
    assert (0, 0) in cells_by_pos
    assert "项目" in cells_by_pos[(0, 0)].text
    assert cells_by_pos[(0, 0)].rowspan == 2

    assert (0, 2) in cells_by_pos
    assert "上年年末余额" in cells_by_pos[(0, 2)].text
    assert cells_by_pos[(0, 2)].colspan == 2

    assert (2, 0) in cells_by_pos
    assert "金融负债和" in cells_by_pos[(2, 0)].text
    assert (2, 1) in cells_by_pos
    assert "17,927.57" in cells_by_pos[(2, 1)].text

    # Bottom table checks
    assert bottom_table.source == "wireless_span_recovery"
    assert bottom_table.rows == 5
    assert bottom_table.cols == 3
