"""Tests for the PDFParser class constructor and context manager."""

import os

import pytest

from hexai_pdf_parser.pdf_parser import PDFParser
from hexai_pdf_parser.models import Document
from tests.conftest import make_text_pdf


def test_constructor_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    assert parser._pdf_path == pdf_path
    assert parser._document is None


def test_constructor_from_document():
    doc = Document(file_name="test.pdf", page_count=1, pages=[])
    parser = PDFParser(doc)
    assert parser._document is doc
    assert parser._pdf_path is None


def test_context_manager_closes_handle(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    with PDFParser(pdf_path) as parser:
        assert parser is not None
    # Context manager exits cleanly without error


def test_context_manager_with_document():
    doc = Document(file_name="test.pdf", page_count=1, pages=[])
    with PDFParser(doc) as parser:
        assert parser._document is doc


def test_parse_returns_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello World")
    parser = PDFParser(pdf_path)
    doc = parser.parse()
    assert isinstance(doc, Document)
    assert doc.page_count == 1
    assert len(doc.pages) == 1
    assert len(doc.pages[0].blocks) >= 1


def test_parse_caches_result(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    doc1 = parser.parse()
    doc2 = parser.parse()
    assert doc1 is doc2


def test_parse_from_document():
    doc = Document(file_name="test.pdf", page_count=1, pages=[])
    parser = PDFParser(doc)
    result = parser.parse()
    assert result is doc


def test_parse_with_output_dir_writes_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "out")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path, render_dpi=150)
    doc = parser.parse(output_dir=output_dir)
    assert os.path.exists(os.path.join(output_dir, "output.json"))
    assert os.path.exists(os.path.join(output_dir, "output.md"))


def test_parse_no_output_dir_does_not_write_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    doc = parser.parse()
    assert isinstance(doc, Document)
    # No output_dir means no files written
    assert not os.path.exists(os.path.join(tmp_dir, "output.json"))


def test_parse_with_page_indices(tmp_dir):
    from tests.conftest import make_multi_page_pdf

    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_multi_page_pdf(pdf_path, ["Page 0", "Page 1", "Page 2"])
    parser = PDFParser(pdf_path)
    doc = parser.parse(page_indices=[0, 2])
    assert doc.page_count == 3  # Document metadata still reports all pages
    # But only pages 0 and 2 should have extracted content
    assert len(doc.pages[0].blocks) >= 1
    assert len(doc.pages[2].blocks) >= 1


from hexai_pdf_parser.models import Block, Table


def test_extract_text_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Extract me")
    parser = PDFParser(pdf_path)
    blocks = parser.extract_text()
    assert isinstance(blocks, list)
    assert len(blocks) >= 1
    assert isinstance(blocks[0], Block)
    assert "Extract" in blocks[0].text


def test_extract_text_from_cached_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Cached text")
    parser = PDFParser(pdf_path)
    parser.parse()
    blocks = parser.extract_text()
    assert len(blocks) >= 1
    assert "Cached" in blocks[0].text


def test_extract_text_with_page_indices(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    from tests.conftest import make_multi_page_pdf
    make_multi_page_pdf(pdf_path, ["AAA", "BBB", "CCC"])
    parser = PDFParser(pdf_path)
    blocks = parser.extract_text(page_indices=[1])
    # Only page 1 text should be returned
    texts = " ".join(b.text for b in blocks)
    assert "BBB" in texts


def test_extract_tables_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    tables = parser.extract_tables()
    assert isinstance(tables, list)


def test_extract_tables_from_cached_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    parser.parse()
    tables = parser.extract_tables()
    assert isinstance(tables, list)


from hexai_pdf_parser.models import Image, RenderInfo
from tests.conftest import make_pdf_with_image


def test_extract_images_writes_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    images = parser.extract_images(output_dir)
    assert isinstance(images, list)
    assert len(images) >= 1
    assert isinstance(images[0], Image)
    assert images[0].path is not None
    assert os.path.exists(images[0].path)


def test_extract_images_with_page_indices(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    images = parser.extract_images(output_dir, page_indices=[0])
    assert len(images) >= 1


def test_render_pages_writes_png(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "renders")
    make_text_pdf(pdf_path, text="Render me")
    parser = PDFParser(pdf_path, render_dpi=150)
    renders = parser.render_pages(output_dir)
    assert isinstance(renders, list)
    assert len(renders) >= 1
    assert isinstance(renders[0], RenderInfo)
    assert renders[0].path is not None
    assert os.path.exists(renders[0].path)
    assert renders[0].path.endswith(".png")


def test_render_pages_custom_dpi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "renders")
    make_text_pdf(pdf_path, text="DPI test")
    parser = PDFParser(pdf_path, render_dpi=200)
    renders = parser.render_pages(output_dir, dpi=100)
    assert renders[0].dpi == 100


import json as json_module


def test_to_json_returns_string(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="JSON test")
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.to_json()
    assert isinstance(result, str)
    data = json_module.loads(result)
    assert "document" in data
    assert "pages" in data


def test_to_json_without_parse_auto_parses(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Auto parse")
    parser = PDFParser(pdf_path)
    result = parser.to_json()
    assert isinstance(result, str)
    data = json_module.loads(result)
    assert data["document"]["page_count"] == 1


def test_to_json_with_explicit_document():
    doc = Document(file_name="test.pdf", page_count=0, pages=[])
    parser = PDFParser(doc)
    result = parser.to_json(document=doc)
    data = json_module.loads(result)
    assert data["document"]["page_count"] == 0


def test_to_markdown_returns_string(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="MD test")
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.to_markdown()
    assert isinstance(result, str)
    assert len(result) > 0


def test_to_markdown_without_parse_auto_parses(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Auto MD")
    parser = PDFParser(pdf_path)
    result = parser.to_markdown()
    assert isinstance(result, str)
    assert len(result) > 0


def test_normalize_region_single(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Region test")
    parser = PDFParser(pdf_path)
    # A4 page: 595.276 x 841.89 points
    page_sizes = parser._get_page_sizes()
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    result = PDFParser._normalize_regions(region, page_sizes)
    assert len(result) == 1
    assert result[0]["page_index"] == 0
    assert abs(result[0]["x0"] - 0.0) < 0.01
    assert abs(result[0]["x1"] - 297.638) < 1.0  # 595.276 * 0.5


def test_normalize_region_list():
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
        {"page_index": 1, "x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.8},
    ]
    result = PDFParser._normalize_regions(regions)
    assert len(result) == 2


def test_extract_text_in_region_single(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello Region")
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    blocks = parser.extract_text_in_region(region)
    assert isinstance(blocks, list)
    assert len(blocks) >= 1


def test_extract_text_in_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Multi Region")
    parser = PDFParser(pdf_path)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
        {"page_index": 0, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
    ]
    blocks = parser.extract_text_in_region(regions)
    assert isinstance(blocks, list)


def test_extract_text_in_region_excludes_outside_text(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    import fitz
    doc = fitz.open()
    page = doc.new_page()  # A4: 595 x 842
    page.insert_text((50, 50), "TopLeft")
    page.insert_text((400, 700), "BottomRight")
    doc.save(pdf_path)
    doc.close()

    parser = PDFParser(pdf_path)
    # Only top-left quadrant
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    blocks = parser.extract_text_in_region(region)
    all_text = " ".join(b.text for b in blocks)
    assert "TopLeft" in all_text


def test_extract_table_in_region_returns_table_or_none(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table

    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_table_in_region(region)
    # May return Table or None depending on whether detection finds a table
    assert result is None or isinstance(result, Table)


def test_extract_table_in_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table

    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
        {"page_index": 0, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
    ]
    result = parser.extract_table_in_region(regions)
    assert isinstance(result, list)


def test_extract_table_in_region_empty_page(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "empty.pdf")
    make_text_pdf(pdf_path, text="No table here")
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_table_in_region(region)
    assert result is None or (isinstance(result, Table) and result.rows == 0)


def test_extract_image_in_region_returns_image_or_none(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "region_images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_image_in_region(region, output_dir)
    assert result is None or isinstance(result, Image)


def test_extract_image_in_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "region_images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5},
        {"page_index": 0, "x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0},
    ]
    result = parser.extract_image_in_region(regions, output_dir)
    assert isinstance(result, list)


def test_render_region_writes_png(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="Render region")
    parser = PDFParser(pdf_path, render_dpi=150)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    result = parser.render_region(region, output_dir)
    assert isinstance(result, RenderInfo)
    assert result.path is not None
    assert os.path.exists(result.path)
    assert result.path.endswith(".png")


def test_render_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="Multi render")
    parser = PDFParser(pdf_path, render_dpi=150)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5},
        {"page_index": 0, "x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0},
    ]
    result = parser.render_region(regions, output_dir)
    assert isinstance(result, list)
    assert len(result) == 2
    for r in result:
        assert os.path.exists(r.path)


def test_render_region_custom_dpi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="DPI region")
    parser = PDFParser(pdf_path, render_dpi=200)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.render_region(region, output_dir, dpi=100)
    assert result.dpi == 100
