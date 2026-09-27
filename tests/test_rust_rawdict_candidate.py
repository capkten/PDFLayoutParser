import pytest
import pymupdf as fitz
from pathlib import Path

from hexai_pdf_parser import _pdf_fast, rust_adapter
from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot
from hexai_pdf_parser.tables.wireless_table_recovery import (
    collect_native_spans_from_snapshot,
    recover_wireless_tables,
    _wireless_recovery_from_rust,
)


@pytest.fixture
def sample_pdf_doc():
    doc_path = Path("tests/fixtures/page_437_wireless.pdf")
    if not doc_path.exists():
        pytest.skip(f"Test fixture not found: {doc_path}")
    doc = fitz.open(str(doc_path))
    yield doc
    doc.close()


def test_collect_native_spans_from_rawdict_matches_snapshot(sample_pdf_doc):
    """Verify that collecting native spans directly from rawdict matches snapshot extraction 100%."""
    page = sample_pdf_doc[0]
    rect = page.rect

    snapshot = capture_page_snapshot(page, page_index=0, lightweight=True)
    spans_snap = collect_native_spans_from_snapshot(snapshot)

    rawdict = page.get_text("rawdict")
    spans_raw = _pdf_fast.collect_native_spans_from_rawdict(rawdict, rect.height, rect.y0)

    assert len(spans_snap) == len(spans_raw)
    for idx, (s1, s2) in enumerate(zip(spans_snap, spans_raw)):
        assert s1.text == s2["text"]
        assert abs(s1.bbox.x0 - s2["rect"]["x0"]) < 1e-4
        assert abs(s1.bbox.y0 - s2["rect"]["y0"]) < 1e-4
        assert abs(s1.bbox.x1 - s2["rect"]["x1"]) < 1e-4
        assert abs(s1.bbox.y1 - s2["rect"]["y1"]) < 1e-4


def test_recover_wireless_tables_from_rawdict_matches_snapshot(sample_pdf_doc, monkeypatch):
    """Verify borderless table recovery directly from rawdict produces identical tables to snapshot."""
    monkeypatch.setenv("PDF_RUST_MODE", "rust")
    page = sample_pdf_doc[0]
    rect = page.rect

    snapshot = capture_page_snapshot(page, page_index=0, lightweight=True)
    res_snap = recover_wireless_tables(snapshot)

    rawdict = page.get_text("rawdict")
    raw_res_dict = rust_adapter.recover_wireless_tables_from_rawdict(
        rawdict=rawdict,
        page_width=rect.width,
        page_height=rect.height,
        rotation=getattr(page, "rotation", 0),
        page_y0=rect.y0,
    )
    res_raw = _wireless_recovery_from_rust(raw_res_dict)

    assert len(res_snap.tables) == len(res_raw.tables)
    for t1, t2 in zip(res_snap.tables, res_raw.tables):
        assert t1.rows == t2.rows
        assert t1.cols == t2.cols
        assert abs(t1.bbox.x0 - t2.bbox.x0) < 1e-3
        assert abs(t1.bbox.y0 - t2.bbox.y0) < 1e-3
        assert abs(t1.bbox.x1 - t2.bbox.x1) < 1e-3
        assert abs(t1.bbox.y1 - t2.bbox.y1) < 1e-3


def test_recover_wireless_tables_page_fast_path(sample_pdf_doc, monkeypatch):
    """Verify calling recover_wireless_tables(page) in rust mode directly uses rawdict fast path."""
    monkeypatch.setenv("PDF_RUST_MODE", "rust")
    page = sample_pdf_doc[0]

    # Ensure page has no cached snapshot
    if hasattr(page, "_cached_snapshot"):
        delattr(page, "_cached_snapshot")

    result = recover_wireless_tables(page)
    # Fast path should succeed and NOT populate _cached_snapshot
    assert not hasattr(page, "_cached_snapshot")
    assert result is not None
    assert result.diagnostics.get("source") == "rust"


def test_recover_wireless_tables_fallback_on_error(sample_pdf_doc, monkeypatch):
    """Verify graceful fallback to snapshot path when rawdict fast path raises an exception."""
    monkeypatch.setenv("PDF_RUST_MODE", "rust")
    page = sample_pdf_doc[0]

    # Mock recover_wireless_tables_from_rawdict to raise an error
    def _raise(*args, **kwargs):
        raise RuntimeError("Simulated Rust rawdict kernel failure")

    monkeypatch.setattr(rust_adapter, "recover_wireless_tables_from_rawdict", _raise)

    # Calling with page should not crash; it should catch the exception and fall back to snapshot
    result = recover_wireless_tables(page)
    assert result is not None
    assert hasattr(page, "_cached_snapshot")
