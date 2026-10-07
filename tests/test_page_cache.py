from __future__ import annotations

import fitz

from hexai_pdf_parser.core.page_cache import CachedPage
from hexai_pdf_parser.tables.table_extractor import TableExtractor


class CountingPage:
    def __init__(self) -> None:
        self.text_calls: list[tuple[tuple, dict]] = []
        self.drawing_calls: list[tuple[tuple, dict]] = []

    def get_text(self, *args, **kwargs):
        self.text_calls.append((args, kwargs))
        return {"mode": args[0] if args else None, "call": len(self.text_calls)}

    def get_drawings(self, *args, **kwargs):
        self.drawing_calls.append((args, kwargs))
        return [{"call": len(self.drawing_calls)}]


def test_cached_page_reuses_identical_text_and_drawing_reads():
    raw_page = CountingPage()
    page = CachedPage(raw_page)

    first_text = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    second_text = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    first_drawings = page.get_drawings(extended=True)
    second_drawings = page.get_drawings(extended=True)

    assert first_text is second_text
    assert first_drawings is second_drawings
    assert len(raw_page.text_calls) == 1
    assert len(raw_page.drawing_calls) == 1


def test_cached_page_keeps_different_read_arguments_separate():
    raw_page = CountingPage()
    page = CachedPage(raw_page)

    page.get_text("text")
    page.get_text("words")
    page.get_drawings()
    page.get_drawings(extended=True)

    assert len(raw_page.text_calls) == 2
    assert len(raw_page.drawing_calls) == 2


def test_table_extractor_can_skip_redundant_page_normalization(monkeypatch):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 40), "not a table")
    extractor = TableExtractor(use_ml_table_detector=False)
    monkeypatch.setattr(
        extractor,
        "_detect_rule_candidates",
        lambda _page, page_language=None: [],
    )
    normalize_calls = []
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda _page: normalize_calls.append(True),
    )

    try:
        assert extractor.extract(page, page_already_normalized=True) == []
    finally:
        doc.close()

    assert normalize_calls == []
