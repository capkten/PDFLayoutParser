"""Tests for lazy page classification in Loader and PDFParser."""

from pathlib import Path
import fitz
import pytest

from hexai_pdf_parser.core.loader import Loader
from hexai_pdf_parser import PDFParser
from tests.conftest import make_multi_page_pdf


def test_loader_skips_unrequested_page_classification(tmp_path, monkeypatch):
    pdf_path = tmp_path / "three_pages.pdf"
    make_multi_page_pdf(pdf_path, texts=["Page 0", "Page 1", "Page 2"])

    classified_pages = []

    def mock_classify(page):
        classified_pages.append(page.number)
        return "vector"

    monkeypatch.setattr("hexai_pdf_parser.core.loader.classify_page_type", mock_classify)

    # 仅请求第 1 页
    loader = Loader(str(pdf_path))
    doc = loader.load(page_indices=[1])

    assert doc.page_count == 3
    assert len(doc.pages) == 3
    # 验证 classify_page_type 只对 page 1 调用，不扫描 page 0 和 page 2
    assert classified_pages == [1]


def test_pdf_parser_extract_tables_passes_page_indices_to_loader(tmp_path, monkeypatch):
    pdf_path = tmp_path / "three_pages.pdf"
    make_multi_page_pdf(pdf_path, texts=["Page 0", "Page 1", "Page 2"])

    classified_pages = []

    def mock_classify(page):
        classified_pages.append(page.number)
        return "vector"

    monkeypatch.setattr("hexai_pdf_parser.core.loader.classify_page_type", mock_classify)
    monkeypatch.setattr("hexai_pdf_parser.tables.table_extractor.TableExtractor.extract", lambda self, page: [])

    parser = PDFParser(str(pdf_path))
    res = parser.extract_tables(page_indices=[1])

    assert res.code in (0, 1)
    # 验证全流程中 classify_page_type 只针对 page 1
    assert classified_pages == [1]
