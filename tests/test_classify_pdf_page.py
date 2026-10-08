"""Tests for classify_pdf_page and PDFParser.classify_page."""

from pathlib import Path
import fitz
import pytest

from hexai_pdf_parser.core.pdf_parser import PDFParser
from hexai_pdf_parser.extractors.page_classifier import classify_pdf_page
from hexai_pdf_parser import pdfium_api
from hexai_pdf_parser.models import Document, Page


def _make_vector_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 50), "This is normal digital vector text for testing.", fontsize=12)
    doc.save(str(path))
    doc.close()


def _make_scanned_pdf(path: Path) -> None:
    doc = fitz.open()
    # Empty page with no text is classified as scanned
    doc.new_page(width=400, height=300)
    doc.save(str(path))
    doc.close()


def test_classify_pdf_page_vector(tmp_path: Path):
    pdf_path = tmp_path / "vector.pdf"
    _make_vector_pdf(pdf_path)

    res = classify_pdf_page(str(pdf_path), page_index=0)
    assert res.code == 1
    assert res.message == "page classified"
    assert res.data == "vector"


def test_classify_pdf_page_scanned(tmp_path: Path):
    pdf_path = tmp_path / "scanned.pdf"
    _make_scanned_pdf(pdf_path)

    res = classify_pdf_page(str(pdf_path), page_index=0)
    assert res.code == 1
    assert res.message == "page classified"
    assert res.data == "scanned"


def test_classify_pdf_page_with_page_and_document(tmp_path: Path):
    pdf_path = tmp_path / "vector.pdf"
    _make_vector_pdf(pdf_path)

    doc = fitz.open(str(pdf_path))
    try:
        # Pass fitz.Document
        res_doc = classify_pdf_page(doc, page_index=0)
        assert res_doc.code == 1
        assert res_doc.data == "vector"

        # Pass fitz.Page
        res_page = classify_pdf_page(doc[0])
        assert res_page.code == 1
        assert res_page.data == "vector"
    finally:
        doc.close()


def test_classify_pdf_page_errors(tmp_path: Path):
    # Non-existent file
    res1 = classify_pdf_page("non_existent_file_xyz.pdf", page_index=0)
    assert res1.code == -1
    assert res1.data is None
    assert res1.message

    # Page index out of range
    pdf_path = tmp_path / "vector.pdf"
    _make_vector_pdf(pdf_path)
    res2 = classify_pdf_page(str(pdf_path), page_index=99)
    assert res2.code == -1
    assert res2.data is None
    assert "out of range" in res2.message or "index" in res2.message.lower()


def test_pdf_parser_classify_page(tmp_path: Path):
    pdf_path = tmp_path / "vector.pdf"
    _make_vector_pdf(pdf_path)

    parser = PDFParser(str(pdf_path))
    res = parser.classify_page(page_index=0)
    assert res.code == 1
    assert res.data == "vector"


def test_classify_inputs_dispatch_to_rust(monkeypatch, tmp_path):
    pdf_path = tmp_path / "vector.pdf"
    _make_vector_pdf(pdf_path)
    requests = []
    bytes_calls = []
    monkeypatch.setattr(pdfium_api, "_run", lambda request: requests.append(request) or {"data": "vector"})
    monkeypatch.setattr(pdfium_api, "classify_bytes", lambda data, index: bytes_calls.append((data, index)) or "vector")
    with fitz.open(pdf_path) as doc:
        assert classify_pdf_page(doc, 0).data == "vector"
        assert classify_pdf_page(doc[0]).data == "vector"
    assert len(bytes_calls) == 2
    assert all(data.startswith(b"%PDF-") and index == 0 for data, index in bytes_calls)
    monkeypatch.setattr(fitz, "open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("PyMuPDF opened path")))
    assert classify_pdf_page(pdf_path).data == "vector"
    assert requests == [{"operation": "classify_page", "pdf_path": str(pdf_path), "page_index": 0}]


def test_classify_cached_document_only_for_document_source(monkeypatch):
    document = Document(file_name="cached.pdf", page_count=1, pages=[
        Page(index=0, size={"width": 100, "height": 100}, rotation=0, page_type="scanned"),
    ])
    requests = []
    monkeypatch.setattr(pdfium_api, "_run", lambda request: requests.append(request) or {"data": "vector"})
    assert PDFParser(document).classify_page(0).data == "scanned"
    parser = PDFParser("cached.pdf")
    parser._document = document
    assert parser.classify_page(0).data == "vector"
    assert requests[0]["operation"] == "classify_page"
