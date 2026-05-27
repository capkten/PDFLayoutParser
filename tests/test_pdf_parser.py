"""Tests for the PDFParser class constructor and context manager."""

import os

import pytest

from pdflayoutparser.pdf_parser import PDFParser
from pdflayoutparser.models import Document
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


from pdflayoutparser.models import Block, Table


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
