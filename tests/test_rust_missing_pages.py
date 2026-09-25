from pathlib import Path
import fitz
import pytest

from hexai_pdf_parser.table_extractor import TableExtractor
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region

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


@pytest.mark.parametrize(
    "page_index, bbox, expected",
    [
        (454, BBox(61.5, 183.1, 561.7, 327.8), (9, 9, 72)),
        (462, BBox(83.9, 367.8, 539.9, 767.9), (11, 7, 77)),
        (932, BBox(85.0, 142.1, 505.9, 247.9), (7, 5, 32)),
        (590, BBox(54.5, 119.6, 785.9, 507.6), (29, 11, 309)),
        (591, BBox(56.2, 119.8, 787.3, 507.6), (29, 11, 309)),
    ],
)
def test_rust_region_recovery_matches_python_reference_pages(
    monkeypatch, page_index, bbox, expected
):
    """Rust region recovery must match the Python stage oracle on remaining pages."""
    if not pdf_path.exists():
        pytest.skip("Local test PDF not found")
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_index]
        monkeypatch.setenv("PDF_RUST_MODE", "python")
        python_result = recover_cells_from_region(page, bbox)
        monkeypatch.setenv("PDF_RUST_MODE", "rust")
        rust_result = recover_cells_from_region(page, bbox)

    assert (python_result[0], python_result[1], len(python_result[2])) == expected
    assert (rust_result[0], rust_result[1], len(rust_result[2])) == expected

