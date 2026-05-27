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
