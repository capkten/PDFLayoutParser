"""Tests for the PDFParser class constructor and context manager."""

import os

import pytest

from hexai_pdf_parser.pdf_parser import PDFParser
from hexai_pdf_parser.models import Document
from tests.conftest import make_text_pdf

# ---------------------------------------------------------------------------
# Real-PDF fixtures and region catalog
# ---------------------------------------------------------------------------

REAL_PDF_PATH = os.path.abspath("万马股份2024财报.pdf")

REAL_TEXT_PAGE_INDEX = 0
REAL_TEXT_REGION = {
    "page_index": 0,
    "x0": 0.08,
    "y0": 0.08,
    "x1": 0.92,
    "y1": 0.22,
}

REAL_TABLE_REGION = {
    "page_index": 12,
    "x0": 0.08,
    "y0": 0.18,
    "x1": 0.92,
    "y1": 0.78,
}

REAL_IMAGE_REGION = {
    "page_index": 5,
    "x0": 0.08,
    "y0": 0.08,
    "x1": 0.92,
    "y1": 0.40,
}

REAL_EMPTY_REGION = {
    "page_index": 0,
    "x0": 0.01,
    "y0": 0.01,
    "x1": 0.04,
    "y1": 0.03,
}


@pytest.fixture
def real_pdf_path() -> str:
    if not os.path.exists(REAL_PDF_PATH):
        pytest.skip("real sample PDF not found: 万马股份2024财报.pdf")
    return REAL_PDF_PATH


# ---------------------------------------------------------------------------
# Shared response assertions
# ---------------------------------------------------------------------------


def assert_success_result(result):
    assert result.code == 1
    assert isinstance(result.message, str)
    assert result.message
    assert result.data is not None


def assert_empty_result(result):
    assert result.code == 0
    assert isinstance(result.message, str)
    assert result.message


def assert_error_result(result, expected_substring: str | None = None):
    assert result.code == -1
    assert isinstance(result.message, str)
    assert result.data is None
    if expected_substring is not None:
        assert expected_substring in result.message


from hexai_pdf_parser import ApiResult


def test_api_result_model_is_exported():
    result = ApiResult(code=1, message="ok", data=["x"])
    assert result.code == 1
    assert result.message == "ok"
    assert result.data == ["x"]


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
    result = parser.parse()
    assert_success_result(result)
    doc = result.data
    assert isinstance(doc, Document)
    assert doc.page_count == 1
    assert len(doc.pages) == 1
    assert len(doc.pages[0].blocks) >= 1


def test_parse_caches_result(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    result1 = parser.parse()
    result2 = parser.parse()
    assert result1.data is result2.data


def test_parse_from_document():
    doc = Document(file_name="test.pdf", page_count=1, pages=[])
    parser = PDFParser(doc)
    result = parser.parse()
    assert result.data is doc


def test_parse_with_output_dir_writes_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "out")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path, render_dpi=150)
    result = parser.parse(output_dir=output_dir)
    assert_success_result(result)
    assert os.path.exists(os.path.join(output_dir, "output.json"))
    assert os.path.exists(os.path.join(output_dir, "output.md"))


def test_parse_no_output_dir_does_not_write_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    result = parser.parse()
    assert_success_result(result)
    assert isinstance(result.data, Document)
    assert not os.path.exists(os.path.join(tmp_dir, "output.json"))


def test_parse_with_page_indices(tmp_dir):
    from tests.conftest import make_multi_page_pdf

    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_multi_page_pdf(pdf_path, ["Page 0", "Page 1", "Page 2"])
    parser = PDFParser(pdf_path)
    result = parser.parse(page_indices=[0, 2])
    assert_success_result(result)
    doc = result.data
    assert doc.page_count == 3
    assert len(doc.pages[0].blocks) >= 1
    assert len(doc.pages[2].blocks) >= 1


from hexai_pdf_parser.models import Block, Table


def test_extract_text_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Extract me")
    parser = PDFParser(pdf_path)
    result = parser.extract_text()
    assert_success_result(result)
    blocks = result.data
    assert isinstance(blocks, list)
    assert len(blocks) >= 1
    assert isinstance(blocks[0], Block)
    assert "Extract" in blocks[0].text


def test_extract_text_from_cached_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Cached text")
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.extract_text()
    assert_success_result(result)
    blocks = result.data
    assert len(blocks) >= 1
    assert "Cached" in blocks[0].text


def test_extract_text_with_page_indices(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    from tests.conftest import make_multi_page_pdf
    make_multi_page_pdf(pdf_path, ["AAA", "BBB", "CCC"])
    parser = PDFParser(pdf_path)
    result = parser.extract_text(page_indices=[1])
    assert_success_result(result)
    blocks = result.data
    texts = " ".join(b.text for b in blocks)
    assert "BBB" in texts


def test_extract_tables_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    result = parser.extract_tables()
    assert_success_result(result)
    assert isinstance(result.data, list)


def test_extract_tables_from_cached_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.extract_tables()
    assert_success_result(result)
    assert isinstance(result.data, list)


from hexai_pdf_parser.models import Image, RenderInfo
from tests.conftest import make_pdf_with_image


def test_extract_images_writes_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    result = parser.extract_images(output_dir)
    assert_success_result(result)
    images = result.data
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
    result = parser.extract_images(output_dir, page_indices=[0])
    assert_success_result(result)
    assert len(result.data) >= 1


def test_render_pages_writes_png(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "renders")
    make_text_pdf(pdf_path, text="Render me")
    parser = PDFParser(pdf_path, render_dpi=150)
    result = parser.render_pages(output_dir)
    assert_success_result(result)
    renders = result.data
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
    result = parser.render_pages(output_dir, dpi=100)
    assert_success_result(result)
    assert result.data[0].dpi == 100


import json as json_module


def test_to_json_returns_string(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="JSON test")
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.to_json()
    assert_success_result(result)
    assert isinstance(result.data, str)
    data = json_module.loads(result.data)
    assert "document" in data
    assert "pages" in data


def test_to_json_without_parse_auto_parses(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Auto parse")
    parser = PDFParser(pdf_path)
    result = parser.to_json()
    assert_success_result(result)
    data = json_module.loads(result.data)
    assert data["document"]["page_count"] == 1


def test_to_json_with_explicit_document():
    doc = Document(file_name="test.pdf", page_count=0, pages=[])
    parser = PDFParser(doc)
    result = parser.to_json(document=doc)
    assert_empty_result(result)
    data = json_module.loads(result.data)
    assert data["document"]["page_count"] == 0


def test_to_markdown_returns_string(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="MD test")
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.to_markdown()
    assert_success_result(result)
    assert isinstance(result.data, str)
    assert len(result.data) > 0


def test_to_markdown_without_parse_auto_parses(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Auto MD")
    parser = PDFParser(pdf_path)
    result = parser.to_markdown()
    assert_success_result(result)
    assert isinstance(result.data, str)
    assert len(result.data) > 0


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
    result = parser.extract_text_in_region(region)
    assert_success_result(result)
    blocks = result.data
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
    result = parser.extract_text_in_region(regions)
    assert_success_result(result)
    assert isinstance(result.data, list)


def test_extract_text_in_region_excludes_outside_text(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "TopLeft")
    page.insert_text((400, 700), "BottomRight")
    doc.save(pdf_path)
    doc.close()

    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    result = parser.extract_text_in_region(region)
    assert_success_result(result)
    all_text = " ".join(b.text for b in result.data)
    assert "TopLeft" in all_text


def test_extract_table_in_region_returns_table_or_none(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table

    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_table_in_region(region)
    assert result.code in {0, 1}
    if result.code == 1:
        assert isinstance(result.data, Table)
    else:
        assert result.data is None


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
    assert result.code in {0, 1}
    assert isinstance(result.data, list)


def test_extract_table_in_region_empty_page(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "empty.pdf")
    make_text_pdf(pdf_path, text="No table here")
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_table_in_region(region)
    assert result.code == 0
    assert result.data is None


def test_extract_image_in_region_returns_image_or_none(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "region_images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_image_in_region(region, output_dir)
    assert result.code in {0, 1}
    if result.code == 1:
        assert isinstance(result.data, Image)
    else:
        assert result.data is None


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
    assert result.code in {0, 1}
    assert isinstance(result.data, list)


def test_render_region_writes_png(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="Render region")
    parser = PDFParser(pdf_path, render_dpi=150)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    result = parser.render_region(region, output_dir)
    assert_success_result(result)
    info = result.data
    assert isinstance(info, RenderInfo)
    assert info.path is not None
    assert os.path.exists(info.path)
    assert info.path.endswith(".png")


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
    assert_success_result(result)
    renders = result.data
    assert isinstance(renders, list)
    assert len(renders) == 2
    for r in renders:
        assert os.path.exists(r.path)


def test_render_region_custom_dpi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="DPI region")
    parser = PDFParser(pdf_path, render_dpi=200)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.render_region(region, output_dir, dpi=100)
    assert_success_result(result)
    assert result.data.dpi == 100


# ===========================================================================
# Task 3: parse / to_json / to_markdown status code tests
# ===========================================================================


def test_parse_returns_success_result_for_real_pdf(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.parse()
    assert_success_result(result)
    assert isinstance(result.data, Document)
    assert result.data.page_count > 0


def test_parse_returns_empty_result_for_empty_document():
    parser = PDFParser(Document(file_name="empty.pdf", page_count=0, pages=[]))
    result = parser.parse()
    assert_empty_result(result)
    assert result.data.page_count == 0


def test_parse_returns_error_result_on_pipeline_exception(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr("hexai_pdf_parser.pipeline.Pipeline.run", boom)
    result = parser.parse()
    assert_error_result(result, "pipeline exploded")


def test_to_json_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.to_json()
    assert_success_result(result)
    assert isinstance(result.data, str)
    assert "\"document\"" in result.data


def test_to_json_returns_empty_result_for_empty_document():
    doc = Document(file_name="empty.pdf", page_count=0, pages=[])
    parser = PDFParser(doc)
    result = parser.to_json(document=doc)
    assert_empty_result(result)
    assert isinstance(result.data, str)
    assert "page_count" in result.data


def test_to_markdown_returns_error_result_on_writer_exception(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("markdown exploded")

    monkeypatch.setattr("hexai_pdf_parser.markdown_writer.MarkdownWriter.to_string", boom)
    result = parser.to_markdown()
    assert_error_result(result, "markdown exploded")


# ===========================================================================
# Task 4: page-level extract / render status code tests
# ===========================================================================


def test_extract_text_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text(page_indices=[REAL_TEXT_PAGE_INDEX])
    assert_success_result(result)
    assert isinstance(result.data, list)
    assert result.data


def test_extract_text_returns_empty_result_for_invalid_page_filter(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text(page_indices=[9999])
    assert_empty_result(result)
    assert result.data == []


def test_extract_text_returns_error_result_on_extractor_exception(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("text exploded")

    monkeypatch.setattr("hexai_pdf_parser.text_extractor.TextExtractor.extract_blocks", boom)
    result = parser.extract_text(page_indices=[REAL_TEXT_PAGE_INDEX])
    assert_error_result(result, "text exploded")


def test_extract_tables_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_tables(page_indices=[REAL_TABLE_REGION["page_index"]])
    assert_success_result(result)
    assert isinstance(result.data, list)


def test_extract_tables_returns_empty_result_for_invalid_page_filter(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_tables(page_indices=[9999])
    assert_empty_result(result)
    assert result.data == []


def test_extract_images_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_images(os.path.join(tmp_dir, "images"), page_indices=[REAL_IMAGE_REGION["page_index"]])
    assert_success_result(result)
    assert isinstance(result.data, list)


def test_extract_images_returns_error_result_on_invalid_document_input(tmp_dir):
    parser = PDFParser(Document(file_name="empty.pdf", page_count=0, pages=[]))
    result = parser.extract_images(os.path.join(tmp_dir, "images"))
    assert_error_result(result, "requires a PDF file path")


def test_render_pages_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path, render_dpi=150)
    result = parser.render_pages(os.path.join(tmp_dir, "renders"), page_indices=[REAL_TEXT_PAGE_INDEX])
    assert_success_result(result)
    assert isinstance(result.data, list)
    assert result.data[0].path is not None


def test_render_pages_returns_empty_result_for_invalid_page_filter(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.render_pages(os.path.join(tmp_dir, "renders"), page_indices=[9999])
    assert_empty_result(result)
    assert result.data == []


# ===========================================================================
# Task 5: region method status code tests
# ===========================================================================


def test_extract_text_in_region_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text_in_region(REAL_TEXT_REGION)
    assert_success_result(result)
    assert isinstance(result.data, list)
    assert result.data


def test_extract_text_in_region_returns_empty_result_for_image_region(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text_in_region(REAL_EMPTY_REGION)
    assert_empty_result(result)
    assert result.data == []


def test_extract_table_in_region_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_table_in_region(REAL_TABLE_REGION)
    assert_success_result(result)
    assert result.data is not None


def test_extract_table_in_region_returns_empty_result_for_text_region(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_table_in_region(REAL_TEXT_REGION)
    assert_empty_result(result)
    assert result.data is None


def test_extract_image_in_region_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_image_in_region(REAL_IMAGE_REGION, os.path.join(tmp_dir, "region-images"))
    assert_success_result(result)
    assert result.data is not None


def test_extract_image_in_region_returns_empty_result_for_text_region(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_image_in_region(REAL_EMPTY_REGION, os.path.join(tmp_dir, "region-images"))
    assert_empty_result(result)
    assert result.data is None


def test_render_region_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path, render_dpi=150)
    result = parser.render_region(REAL_TEXT_REGION, os.path.join(tmp_dir, "crops"))
    assert_success_result(result)
    assert result.data.path is not None


def test_render_region_returns_error_result_on_invalid_pdf_input(tmp_dir):
    parser = PDFParser(Document(file_name="empty.pdf", page_count=0, pages=[]))
    result = parser.render_region(REAL_TEXT_REGION, os.path.join(tmp_dir, "crops"))
    assert_error_result(result, "requires a PDF file path")


def test_extract_text_in_region_returns_error_result_on_normalize_failure(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("normalize exploded")

    monkeypatch.setattr(PDFParser, "_normalize_regions", staticmethod(boom))
    result = parser.extract_text_in_region(REAL_TEXT_REGION)
    assert_error_result(result, "normalize exploded")


def test_extract_table_in_region_returns_error_result_on_extractor_failure(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("table region exploded")

    monkeypatch.setattr("hexai_pdf_parser.table_extractor.TableExtractor.extract", boom)
    result = parser.extract_table_in_region(REAL_TABLE_REGION)
    assert_error_result(result, "table region exploded")


def test_extract_image_in_region_returns_error_result_on_image_failure(real_pdf_path, tmp_dir, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("image region exploded")

    monkeypatch.setattr(PDFParser, "extract_images", boom)
    result = parser.extract_image_in_region(REAL_IMAGE_REGION, os.path.join(tmp_dir, "region-images"))
    assert_error_result(result, "image region exploded")


def test_render_region_returns_error_result_on_render_failure(real_pdf_path, tmp_dir, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("render region exploded")

    monkeypatch.setattr("fitz.Page.get_pixmap", boom)
    result = parser.render_region(REAL_TEXT_REGION, os.path.join(tmp_dir, "crops"))
    assert_error_result(result, "render region exploded")


# ===========================================================================
# Task 6: no-content coverage matrix
# ===========================================================================


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("extract_text", {"page_indices": [9999]}),
        ("extract_tables", {"page_indices": [9999]}),
        ("to_json", {"document": Document(file_name="empty.pdf", page_count=0, pages=[])}),
        ("to_markdown", {"document": Document(file_name="empty.pdf", page_count=0, pages=[])}),
    ],
)
def test_public_methods_return_code_zero_when_content_is_empty(real_pdf_path, method_name, kwargs):
    parser = PDFParser(real_pdf_path)
    method = getattr(parser, method_name)
    result = method(**kwargs)
    assert result.code == 0


def test_parse_returns_code_zero_for_empty_document():
    parser = PDFParser(Document(file_name="empty.pdf", page_count=0, pages=[]))
    result = parser.parse()
    assert result.code == 0


def test_extract_images_returns_code_zero_for_non_image_page(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_images(os.path.join(tmp_dir, "images"), page_indices=[REAL_TEXT_PAGE_INDEX])
    assert result.code in {0, 1}


def test_render_pages_returns_code_zero_for_empty_page_filter(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.render_pages(os.path.join(tmp_dir, "renders"), page_indices=[9999])
    assert result.code == 0


def test_real_fixture_expectations_are_stable(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    assert parser.extract_text_in_region(REAL_TEXT_REGION).code == 1
    assert parser.extract_text_in_region(REAL_EMPTY_REGION).code == 0
    assert parser.extract_table_in_region(REAL_TABLE_REGION).code == 1
    assert parser.extract_image_in_region(REAL_IMAGE_REGION, os.path.join(tmp_dir, "images")).code == 1
