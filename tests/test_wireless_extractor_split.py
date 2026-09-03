from types import SimpleNamespace

import fitz

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.extractors.wireless_table_extractor import (
    WirelessTableExtractor,
)


def _page():
    return SimpleNamespace(
        rect=fitz.Rect(0, 0, 200, 200),
        get_text=lambda kind, **kwargs: [],
        get_drawings=lambda: [],
    )


def _table(source):
    bbox = BBox(0, 0, 20, 20)
    return Table(
        bbox=bbox,
        rows=1,
        cols=1,
        cells=[Cell(source, 0, 0, bbox)],
        source=source,
    )


def test_english_and_chinese_strategies_are_separate_modules():
    from hexai_pdf_parser.tables.extractors.chinese_table_extractor import (
        ChineseTableExtractor,
    )
    from hexai_pdf_parser.tables.extractors.english_table_extractor import (
        EnglishTableExtractor,
    )

    assert EnglishTableExtractor.__module__.endswith("english_table_extractor")
    assert ChineseTableExtractor.__module__.endswith("chinese_table_extractor")


def test_top_level_strategy_aliases_are_importable():
    from hexai_pdf_parser.chinese_table_extractor import ChineseTableExtractor
    from hexai_pdf_parser.english_table_extractor import EnglishTableExtractor

    assert EnglishTableExtractor.__name__ == "EnglishTableExtractor"
    assert ChineseTableExtractor.__name__ == "ChineseTableExtractor"


def test_wireless_facade_routes_en_and_zh_to_different_strategies(monkeypatch):
    extractor = WirelessTableExtractor()
    english = _table("english")
    chinese = _table("chinese")
    monkeypatch.setattr(
        extractor._english_extractor,
        "extract",
        lambda page, table_bbox=None, confidence=None: [english],
    )
    monkeypatch.setattr(
        extractor._chinese_extractor,
        "extract",
        lambda page, table_bbox=None, confidence=None, page_language=None: [chinese],
    )

    assert extractor.extract(_page(), page_language="en") == [english]
    assert extractor.extract(_page(), page_language="zh") == [chinese]


def test_legacy_recover_cells_monkeypatch_path_still_controls_chinese_region(
    monkeypatch,
):
    bbox = BBox(0, 0, 100, 100)
    expected = [Cell("中文", 0, 0, bbox)]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.extractors.wireless_table_extractor.recover_cells_from_region",
        lambda page, region: (1, 1, expected),
    )

    tables = WirelessTableExtractor().extract(
        _page(), table_bbox=bbox, page_language="mixed"
    )

    assert tables[0].source == "wireless_span_recovery"
    assert tables[0].cells == expected


def test_table_extractor_keeps_legacy_text_alignment_method_surface():
    from hexai_pdf_parser.tables.table_extractor import TableExtractor

    extractor = TableExtractor()
    rows = extractor._collect_text_rows(
        [(10.0, 10.0, 20.0, 20.0, "A", 0, 0, 0)]
    )

    assert rows[0]["tokens"][0]["text"] == "A"
    assert callable(extractor._extract_via_text_alignment)


def test_table_extractor_routes_text_alignment_to_language_strategy(monkeypatch):
    from hexai_pdf_parser.tables.table_extractor import TableExtractor

    extractor = TableExtractor()
    page = _page()
    expected = _table("chinese")
    calls = []
    monkeypatch.setattr(
        "hexai_pdf_parser.extractors.language_detector.detect_page_language",
        lambda page: "zh",
    )

    def recover(page, excluded_regions=None, allowed_regions=None):
        calls.append((page, excluded_regions, allowed_regions))
        return [expected]

    monkeypatch.setattr(
        extractor._wireless_extractor._chinese_extractor,
        "extract_text_alignment_candidates",
        recover,
    )

    assert extractor._extract_via_text_alignment(page) == [expected]
    assert calls == [(page, None, None)]


def test_chinese_page_candidates_do_not_request_words(monkeypatch):
    from hexai_pdf_parser.tables.extractors.chinese_table_extractor import (
        ChineseTableExtractor,
    )

    requested = []
    page = SimpleNamespace(
        get_text=lambda kind, **kwargs: requested.append(kind) or [],
    )

    assert ChineseTableExtractor().extract_text_alignment_candidates(page) == []
    assert "words" not in requested
