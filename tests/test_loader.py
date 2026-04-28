"""Tests for the PDF loader."""

from pathlib import Path

import pytest

from pdflayoutparser.loader import Loader
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
