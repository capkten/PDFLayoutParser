"""Unit tests for designated table region extraction (extract_table_in_region).

Covers:
1. Wired table extraction within specified region without running ML detector.
2. Wireless table structure extraction within specified region without running ML detector.
3. Empty/invalid region returning None.
4. Top-level convenience function extract_table_from_region with various bbox formats.
5. PDFParser.extract_table_in_region integration.
"""

from pathlib import Path
import fitz
import pytest

from hexai_pdf_parser.core.models import BBox, Table
from hexai_pdf_parser.core.pdf_parser import PDFParser
from hexai_pdf_parser.tables.table_extractor import TableExtractor, extract_table_from_region


def _create_wired_table_pdf(path: Path) -> BBox:
    """Create a PDF with a 3x3 wired table."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=400)
    # Draw table bounding box and grid lines
    # Table box: (50, 50, 350, 170)
    y_lines = [50.0, 90.0, 130.0, 170.0]
    x_lines = [50.0, 150.0, 250.0, 350.0]
    for y in y_lines:
        page.draw_line((x_lines[0], y), (x_lines[-1], y))
    for x in x_lines:
        page.draw_line((x, y_lines[0]), (x, y_lines[-1]))

    # Insert cell texts
    texts = [
        ["名称", "数量", "单价"],
        ["商品A", "10", "100.0"],
        ["商品B", "5", "200.0"],
    ]
    for r_idx, row in enumerate(texts):
        for c_idx, val in enumerate(row):
            page.insert_text(
                (x_lines[c_idx] + 10, y_lines[r_idx] + 25),
                val,
                fontsize=11,
            )

    doc.save(str(path))
    doc.close()
    return BBox(50.0, 50.0, 350.0, 170.0)


def _create_wireless_table_pdf(path: Path) -> BBox:
    """Create a PDF with a borderless Chinese table."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=400)
    # No vector lines drawn!
    x_coords = [60.0, 180.0, 300.0]
    y_coords = [80.0, 115.0, 150.0]
    rows = [
        ["项目名称", "期末余额", "年初余额"],
        ["应收账款", "12,345.00", "10,000.00"],
        ["存货", "6,789.00", "5,500.00"],
    ]
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            page.insert_text(
                (x_coords[c_idx], y_coords[r_idx]),
                val,
                fontsize=10,
                fontname="china-s",
            )

    doc.save(str(path))
    doc.close()
    return BBox(50.0, 60.0, 420.0, 170.0)


def test_extract_table_in_region_wired(tmp_path: Path):
    pdf_path = tmp_path / "wired.pdf"
    table_bbox = _create_wired_table_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    page = doc[0]

    extractor = TableExtractor(use_ml_table_detector=False)
    table = extractor.extract_table_in_region(page, table_bbox)

    assert table is not None
    assert isinstance(table, Table)
    assert table.source == "line_projection"
    assert table.rows == 3
    assert table.cols == 3
    assert len(table.cells) == 9

    doc.close()


def test_extract_table_in_region_wireless(tmp_path: Path):
    pdf_path = tmp_path / "wireless.pdf"
    table_bbox = _create_wireless_table_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    page = doc[0]

    extractor = TableExtractor(use_ml_table_detector=False)
    table = extractor.extract_table_in_region(page, table_bbox)

    assert table is not None
    assert isinstance(table, Table)
    assert table.source == "wireless_span_recovery"
    assert table.rows >= 2
    assert table.cols == 3
    assert len(table.cells) > 0

    doc.close()


def test_extract_table_in_region_empty(tmp_path: Path):
    pdf_path = tmp_path / "empty.pdf"
    _create_wired_table_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    page = doc[0]

    extractor = TableExtractor(use_ml_table_detector=False)
    # Query a blank corner of the page
    table = extractor.extract_table_in_region(page, BBox(400, 300, 490, 390))
    assert table is None

    doc.close()


def test_extract_table_from_region_top_level_various_formats(tmp_path: Path):
    pdf_path = tmp_path / "wired.pdf"
    table_bbox = _create_wired_table_pdf(pdf_path)

    # 1. Using pdf_path + BBox
    table1 = extract_table_from_region(str(pdf_path), table_bbox)
    assert table1 is not None
    assert table1.rows == 3

    # 2. Using tuple (x0, y0, x1, y1)
    bbox_tuple = (table_bbox.x0, table_bbox.y0, table_bbox.x1, table_bbox.y1)
    table2 = extract_table_from_region(str(pdf_path), bbox_tuple)
    assert table2 is not None
    assert table2.rows == 3

    # 3. Using normalized dict (0~1)
    # Page size is 500x400
    norm_dict = {
        "x0": table_bbox.x0 / 500.0,
        "y0": table_bbox.y0 / 400.0,
        "x1": table_bbox.x1 / 500.0,
        "y1": table_bbox.y1 / 400.0,
    }
    table3 = extract_table_from_region(str(pdf_path), norm_dict)
    assert table3 is not None
    assert table3.rows == 3

    # 4. Using fitz.Page directly
    doc = fitz.open(str(pdf_path))
    table4 = extract_table_from_region(doc[0], table_bbox)
    assert table4 is not None
    assert table4.rows == 3
    doc.close()


def test_pdf_parser_extract_table_in_region_integration(tmp_path: Path):
    pdf_path = tmp_path / "wireless.pdf"
    table_bbox = _create_wireless_table_pdf(pdf_path)

    parser = PDFParser(str(pdf_path))
    region_dict = {
        "page_index": 0,
        "x0": table_bbox.x0 / 500.0,
        "y0": table_bbox.y0 / 400.0,
        "x1": table_bbox.x1 / 500.0,
        "y1": table_bbox.y1 / 400.0,
    }
    res = parser.extract_table_in_region(region_dict)
    assert res.code == 1
    table = res.data
    assert table is not None
    assert isinstance(table, Table)
    assert table.source == "wireless_span_recovery"


def test_extract_table_in_region_english(tmp_path: Path):
    """Test English wireless table in designated region."""
    pdf_path = tmp_path / "english.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=400)
    for x, text in [(60, "Item"), (180, "Price"), (300, "Quantity")]:
        page.insert_text((x, 80), text, fontsize=10)
    for y, item, price, qty in [(115, "Product A", "12.50", "100"), (150, "Product B", "34.00", "50")]:
        page.insert_text((60, y), item, fontsize=10)
        page.insert_text((180, y), price, fontsize=10)
        page.insert_text((300, y), qty, fontsize=10)
    doc.save(str(pdf_path))
    doc.close()

    table = extract_table_from_region(
        str(pdf_path),
        (50, 60, 420, 180),
        confidence=0.95,
    )
    assert table is not None
    assert table.cols == 3
    assert table.rows >= 2
    assert table.confidence == 0.95


def test_pdf_parser_extract_table_in_region_multi(tmp_path: Path):
    """Test PDFParser.extract_table_in_region with a list of regions."""
    pdf_path = tmp_path / "multi.pdf"
    table_bbox = _create_wired_table_pdf(pdf_path)

    parser = PDFParser(str(pdf_path))
    regions = [
        {
            "page_index": 0,
            "x0": table_bbox.x0 / 500.0,
            "y0": table_bbox.y0 / 400.0,
            "x1": table_bbox.x1 / 500.0,
            "y1": table_bbox.y1 / 400.0,
        },
        {
            "page_index": 0,
            "x0": 0.8,
            "y0": 0.8,
            "x1": 0.95,
            "y1": 0.95,
        },
    ]
    res = parser.extract_table_in_region(regions)
    assert res.code == 1
    tables = res.data
    assert isinstance(tables, list)
    assert len(tables) == 1
    assert tables[0].source == "line_projection"

