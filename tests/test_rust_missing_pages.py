from pathlib import Path
import fitz
import pytest

from hexai_pdf_parser.table_extractor import TableExtractor

pdf_path = Path(r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf")


@pytest.mark.parametrize("page_index, expected", [(440, (1, 4, 13)), (923, (1, 6, 5))])
def test_rust_missing_page_uses_ml_after_empty_rule_candidates(monkeypatch, page_index, expected):
    """Page 440 and 923 have empty rule candidates in Rust, but ML detector recovers the wireless tables."""
    if not pdf_path.exists():
        pytest.skip("Local test PDF not found")
    monkeypatch.setenv("PDF_RUST_MODE", "rust")
    with fitz.open(str(pdf_path)) as doc:
        tables = TableExtractor().extract(doc[page_index])
    assert len(tables) == expected[0]
    assert (tables[0].rows, tables[0].cols) == expected[1:]
    assert tables[0].source == "wireless_span_recovery"

    occupied = []
    for cell in tables[0].cells:
        for row in range(cell.row_index, cell.row_index + cell.rowspan):
            for col in range(cell.col_index, cell.col_index + cell.colspan):
                occupied.append((row, col))
    assert len(occupied) == len(set(occupied)) == tables[0].rows * tables[0].cols


def test_rust_page_591_no_greedy_vertical_merge(monkeypatch):
    """Page 591 table was previously dropped due to greedy vertical merge of financial items."""
    if not pdf_path.exists():
        pytest.skip("Local test PDF not found")
    monkeypatch.setenv("PDF_RUST_MODE", "rust")
    with fitz.open(str(pdf_path)) as doc:
        tables = TableExtractor().extract(doc[590])
    assert len(tables) == 1
    assert tables[0].rows >= 20
    assert tables[0].cols == 11
    assert tables[0].source == "wireless_span_recovery"


def test_rust_page_936_and_960_wrapped_fragments_recovered(monkeypatch):
    """Pages 936 and 960 had wrapped cells in the same slot causing OccupancyConflict."""
    if not pdf_path.exists():
        pytest.skip("Local test PDF not found")
    monkeypatch.setenv("PDF_RUST_MODE", "rust")
    with fitz.open(str(pdf_path)) as doc:
        t_936 = TableExtractor().extract(doc[935])
        t_960 = TableExtractor().extract(doc[959])
    assert len(t_936) == 3, f"Expected 3 tables on page 936, got {len(t_936)}"
    assert len(t_960) == 2, f"Expected 2 tables on page 960, got {len(t_960)}"

