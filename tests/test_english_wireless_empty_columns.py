from pathlib import Path
import pytest
import pymupdf as fitz
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor

PDF_PATH = Path("C:/Users/92410/Desktop/git/hexai_pdf_parser/simple_test_50/needs_human_report_2026-09-17/pdfs/0000708781_10-Q_20240806.pdf")

@pytest.mark.skipif(not PDF_PATH.exists(), reason="Test PDF not found")
def test_p030_no_phantom_empty_columns():
    doc = fitz.open(str(PDF_PATH))
    page = doc[29]
    bbox = BBox(31.8, 78.3, 580.1, 537.4)
    extractor = EnglishTableExtractor()
    tables = extractor.extract_zebra(page, bbox)
    assert len(tables) == 1
    table = tables[0]
    num_cols = max(c.col_index + max(1, c.colspan) for c in table.cells)
    # The table should be 7 columns, not 9 columns
    assert num_cols == 7
    # Check that Col 1 to 6 in row 1 are the expected headers
    r1_cells = {c.col_index: c.text.strip() for c in table.cells if c.row_index == 1}
    assert r1_cells.get(1) == "Average Balance"
    assert r1_cells.get(2) == "Interest Income/ Expense"
    assert r1_cells.get(3) == "Yield/ Rate"
    assert r1_cells.get(4) == "Average Balance"
    assert r1_cells.get(5) == "Interest Income/ Expense"
    assert r1_cells.get(6) == "Yield/ Rate"

@pytest.mark.skipif(not PDF_PATH.exists(), reason="Test PDF not found")
def test_p023_data_column_bbox_matches_actual_text():
    doc = fitz.open(str(PDF_PATH))
    page = doc[22]
    bbox = BBox(31.5, 161.9, 572.6, 314.7)
    extractor = EnglishTableExtractor()
    tables = extractor.extract_zebra(page, bbox)
    assert len(tables) == 1
    table = tables[0]
    num_cols = max(c.col_index + max(1, c.colspan) for c in table.cells)
    assert num_cols == 2
    # Check that col 1 bbox covers the actual text (which is at x >= 480, up to x=568.3, table bbox x1=572.6)
    # It must NOT stop at 400.2!
    col1_cells = [c for c in table.cells if c.col_index == 1]
    assert col1_cells
    for c in col1_cells:
        assert c.bbox.x1 >= 560.0, f"Cell {c} bbox.x1 should extend to right edge of table, got {c.bbox.x1}"
