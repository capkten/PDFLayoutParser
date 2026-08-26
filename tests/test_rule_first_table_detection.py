from types import SimpleNamespace

import fitz

from hexai_pdf_parser.models import BBox, Cell, Table
from hexai_pdf_parser.tables.table_extractor import TableExtractor


def _page():
    return SimpleNamespace(
        number=0,
        rect=fitz.Rect(0, 0, 400, 400),
        get_drawings=lambda: [],
        get_text=lambda mode: [],
    )


def _table(source: str, x0: float) -> Table:
    bbox = BBox(x0, 10, x0 + 100, 100)
    return Table(
        bbox=bbox,
        rows=1,
        cols=1,
        cells=[Cell(text=source, row_index=0, col_index=0, bbox=bbox)],
        source=source,
    )


def _configure_rule_candidates(extractor, candidates):
    extractor._wireless_extractor.extract_zebra = lambda page: []
    extractor._wired_extractor.extract = lambda page: candidates
    extractor._extract_via_text_alignment = lambda page, excluded_regions=None: []


def test_rule_hit_calls_model_and_only_model_tables_are_final(monkeypatch):
    extractor = TableExtractor()
    rule_table = _table("rule", 10)
    model_table = _table("model", 200)
    _configure_rule_candidates(extractor, [rule_table])

    calls = []

    class FakeDetector:
        def detect_with_scores(self, page):
            calls.append(page)
            return [(model_table.bbox, 0.91)]

    extractor._ml_detector = FakeDetector()
    extractor._wireless_extractor.extract = (
        lambda page, table_bbox=None, confidence=None: [model_table]
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    result = extractor.extract(_page())

    assert calls
    assert result == [model_table]
    assert rule_table not in result


def test_rule_miss_does_not_call_model(monkeypatch):
    extractor = TableExtractor()
    _configure_rule_candidates(extractor, [])

    class FailDetector:
        def detect_with_scores(self, page):
            raise AssertionError("model must not run for a rule-miss page")

    extractor._ml_detector = FailDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == []


def test_model_failure_does_not_fall_back_to_rule_tables(monkeypatch):
    extractor = TableExtractor()
    rule_table = _table("rule", 10)
    _configure_rule_candidates(extractor, [rule_table])

    class FailingDetector:
        def detect_with_scores(self, page):
            raise RuntimeError("model unavailable")

    extractor._ml_detector = FailingDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == []
