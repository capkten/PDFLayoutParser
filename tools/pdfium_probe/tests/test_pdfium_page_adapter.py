import os
import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from typing import Any, Dict, List, Optional
import pytest

from fixtures_normalizer import make_raw_page, make_span
from pdfium_normalizer import NormalizedPage, normalize_raw_page
from pdfium_page_adapter import PageRect, PdfiumPageAdapter


def test_adapter_exposes_three_text_views():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("Hello world", 0, 10, 70, 20)]))
    )
    assert adapter.get_text("rawdict")["blocks"]
    assert adapter.get_text("dict")["blocks"]
    assert [item[4] for item in adapter.get_text("words")] == ["Hello", "world"]


def test_scanned_adapter_has_no_text():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("坏\ufffd字", 0, 10, 30, 20)]))
    )
    assert adapter.get_text("rawdict") == {"blocks": []}
    assert adapter.get_text("dict") == {"blocks": []}
    assert adapter.get_text("words") == []


def test_unknown_mode_fails_loudly():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("A", 0, 10, 10, 20)]))
    )
    with pytest.raises(ValueError, match="unsupported text mode"):
        adapter.get_text("html")


def test_adapter_number_and_rect():
    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    raw["page_index"] = 3
    raw["width"] = 250.0
    raw["height"] = 350.0
    adapter = PdfiumPageAdapter(normalize_raw_page(raw))

    assert adapter.number == 3
    assert isinstance(adapter.rect, tuple)
    assert adapter.rect == (0.0, 0.0, 250.0, 350.0)
    assert adapter.rect.x0 == 0.0
    assert adapter.rect.y0 == 0.0
    assert adapter.rect.x1 == 250.0
    assert adapter.rect.y1 == 350.0
    assert adapter.rect.width == 250.0
    assert adapter.rect.height == 350.0

    x0, y0, x1, y1 = adapter.rect
    assert (x0, y0, x1, y1) == (0.0, 0.0, 250.0, 350.0)

    try:
        import fitz
        f_rect = fitz.Rect(adapter.rect)
        assert f_rect.width == 250.0
        assert f_rect.height == 350.0
    except ImportError:
        pass


def test_adapter_drawings_and_snapshot_dto():
    drawing_item = {"drawing_index": 0, "rect": [10.0, 10.0, 50.0, 50.0]}
    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    norm_page = normalize_raw_page(raw)
    assert norm_page.page_snapshot is not None
    norm_page.page_snapshot["drawings"] = [drawing_item]

    adapter = PdfiumPageAdapter(norm_page)
    assert adapter.get_drawings() == [drawing_item]
    assert adapter.snapshot_dto() is norm_page.page_snapshot

    # Test drawings fallback from sidecar
    norm_page_sidecar = NormalizedPage(
        page_type="vector",
        page_snapshot={"page_index": 1, "page": {"width": 100, "height": 100}, "drawings": []},
        rawdict={"blocks": []},
        words=[],
        sidecar={"drawings": [drawing_item]},
        diagnostics={},
    )
    adapter_sidecar = PdfiumPageAdapter(norm_page_sidecar)
    assert adapter_sidecar.get_drawings() == [drawing_item]

    # Test scanned page drawings default
    scanned_norm = normalize_raw_page(make_raw_page([make_span("坏\ufffd字", 0, 10, 30, 20)]))
    scanned_adapter = PdfiumPageAdapter(scanned_norm)
    assert scanned_adapter.get_drawings() == []
    assert scanned_adapter.snapshot_dto() is None


def test_dict_view_preserves_characters_for_text_extractor():
    from hexai_pdf_parser.extractors.text_extractor import TextExtractor

    raw = make_raw_page([make_span("Hello world", 0, 10, 70, 20)])
    adapter = PdfiumPageAdapter(normalize_raw_page(raw))

    extractor = TextExtractor()
    blocks = extractor.extract_blocks(adapter)
    assert len(blocks) == 1
    assert len(blocks[0].lines) == 1
    assert blocks[0].lines[0].text == "Hello world"
    # Ensure characters were preserved in words rather than synthesized with equal spacing
    first_word = blocks[0].lines[0].words[0]
    assert len(first_word.chars) == len("Hello world")
    assert "".join(c.text for c in first_word.chars) == "Hello world"


def test_get_text_flags_and_kwargs_support():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("Hello", 0, 10, 50, 20)]))
    )
    rawdict_result = adapter.get_text("rawdict", flags=1)
    assert rawdict_result["blocks"]
    dict_result = adapter.get_text("dict", flags=1)
    assert dict_result["blocks"]
    words_result = adapter.get_text("words", flags=0)
    assert len(words_result) == 1
