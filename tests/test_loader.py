"""Tests for the PDF loader."""

from pathlib import Path

import fitz
import pytest

from hexai_pdf_parser.loader import Loader
from tests.conftest import make_multi_page_pdf, make_text_pdf


class TestLoader:
    def test_load_single_page_pdf(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "single.pdf"
        make_text_pdf(pdf_path, text="Hello World")

        loader = Loader(str(pdf_path))
        doc = loader.load()

        assert doc.file_name == "single.pdf"
        assert doc.page_count == 1
        assert len(doc.pages) == 1

        page = doc.pages[0]
        assert page.index == 0
        assert page.size["width"] == pytest.approx(595.0, rel=1e-3)
        assert page.size["height"] == pytest.approx(842.0, rel=1e-3)
        assert page.rotation == 0
        assert page.page_type == "vector"

    def test_load_classifies_garbled_page_as_scanned(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "garbled.pdf"
        pdf = fitz.open()
        page = pdf.new_page(width=595, height=842)
        page.insert_text((50, 100), "\x00" * 20, fontsize=12)
        pdf.save(str(pdf_path))
        pdf.close()

        doc = Loader(str(pdf_path)).load()

        assert doc.pages[0].page_type == "scanned"

    def test_load_multi_page_pdf(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "multi.pdf"
        make_multi_page_pdf(pdf_path, texts=["Page 1", "Page 2"])

        loader = Loader(str(pdf_path))
        doc = loader.load()

        assert doc.file_name == "multi.pdf"
        assert doc.page_count == 2
        assert len(doc.pages) == 2

        assert doc.pages[0].index == 0
        assert doc.pages[1].index == 1

        for page in doc.pages:
            assert page.size["width"] == pytest.approx(595.0, rel=1e-3)
            assert page.size["height"] == pytest.approx(842.0, rel=1e-3)
            assert page.rotation == 0
