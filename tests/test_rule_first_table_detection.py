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
        lambda page, table_bbox=None, confidence=None, **kwargs: [model_table]
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


def test_native_page_signal_gates_model_without_becoming_final_table(monkeypatch):
    extractor = TableExtractor()
    model_table = _table("model", 200)
    calls = []

    extractor._wireless_extractor.extract_zebra = lambda page: []
    extractor._wired_extractor.extract = lambda page: []

    def signal_alignment(page, excluded_regions=None):
        extractor._last_wireless_recovery = {
            "page_signal": {
                "matched": True,
                "bbox": {"x0": 20.0, "y0": 40.0, "x1": 380.0, "y1": 180.0},
            }
        }
        return []

    extractor._extract_via_text_alignment = signal_alignment

    class FakeDetector:
        def detect_with_scores(self, page):
            calls.append(page)
            return [(model_table.bbox, 0.91)]

    extractor._ml_detector = FakeDetector()
    extractor._wireless_extractor.extract = (
        lambda page, table_bbox=None, confidence=None, **kwargs: [model_table]
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.extractors.language_detector.detect_page_language",
        lambda page: "mixed",
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    result = extractor.extract(_page())

    assert len(calls) == 1
    assert result == [model_table]
    assert all(table.source != "wireless_page_signal" for table in result)


def test_native_page_signal_does_not_leak_when_model_returns_no_tables(monkeypatch):
    extractor = TableExtractor()
    extractor._wireless_extractor.extract_zebra = lambda page: []
    extractor._wired_extractor.extract = lambda page: []

    def signal_alignment(page, excluded_regions=None):
        extractor._last_wireless_recovery = {
            "page_signal": {
                "matched": True,
                "bbox": {"x0": 20.0, "y0": 40.0, "x1": 380.0, "y1": 180.0},
            }
        }
        return []

    extractor._extract_via_text_alignment = signal_alignment

    class EmptyDetector:
        def detect_with_scores(self, page):
            return []

    extractor._ml_detector = EmptyDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.extractors.language_detector.detect_page_language",
        lambda page: "mixed",
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == []


def test_model_failure_does_not_fall_back_to_rule_tables(monkeypatch):
    extractor = TableExtractor()
    rule_table = _table("line_projection", 10)
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

    assert extractor.extract(_page()) == [rule_table]


def test_empty_model_result_keeps_all_wired_tables(monkeypatch):
    extractor = TableExtractor()
    wired_tables = [_table("line_projection", 10), _table("line_projection", 200)]
    _configure_rule_candidates(extractor, wired_tables)

    class EmptyDetector:
        def detect_with_scores(self, page):
            return []

    extractor._ml_detector = EmptyDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == wired_tables


def test_model_only_result_is_augmented_with_unmatched_wired_tables(monkeypatch):
    extractor = TableExtractor()
    matched = _table("line_projection", 10)
    unmatched = _table("line_projection", 200)
    _configure_rule_candidates(extractor, [matched, unmatched])
    extractor._wireless_extractor.extract_zebra = lambda *args, **kwargs: []

    class PartialDetector:
        def detect_with_scores(self, page):
            return [(matched.bbox, 0.91)]

    extractor._ml_detector = PartialDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == [matched, unmatched]


def test_overlapping_model_region_prefers_rule_wired_table(monkeypatch):
    extractor = TableExtractor()
    wired_table = _table("line_projection", 10)
    model_table = _table("model", 20)
    detector_calls = []
    structure_calls = []

    extractor._wireless_extractor.extract_zebra = lambda page: []

    def extract_wired(page, table_bbox=None, confidence=None):
        if table_bbox is None:
            return [wired_table]
        structure_calls.append((table_bbox, confidence))
        return [model_table]

    extractor._wired_extractor.extract = extract_wired
    extractor._extract_via_text_alignment = lambda page, excluded_regions=None: []

    class FakeDetector:
        def detect_with_scores(self, page):
            detector_calls.append(page)
            return [(model_table.bbox, 0.91)]

    extractor._ml_detector = FakeDetector()
    extractor._wireless_extractor.extract = (
        lambda page, table_bbox=None, confidence=None, **kwargs: (_ for _ in ()).throw(
            AssertionError("overlapping wired table must take precedence")
        )
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    result = extractor.extract(_page())

    assert detector_calls
    assert result == [wired_table]
    assert structure_calls == []
