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


def test_model_disabled_uses_wireless_candidates_without_detector(monkeypatch):
    extractor = TableExtractor(use_ml_table_detector=False)
    wireless = _table("wireless_span_recovery", 20)
    _configure_rule_candidates(extractor, [])
    extractor._extract_via_text_alignment = (
        lambda page, excluded_regions=None: [wireless]
    )

    class FailDetector:
        def detect_with_scores(self, page):
            raise AssertionError("ML detector must not run when disabled")

    extractor._ml_detector = FailDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == [wireless]


def test_model_disabled_drops_wireless_page_signal(monkeypatch):
    extractor = TableExtractor(use_ml_table_detector=False)
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

    class FailDetector:
        def detect_with_scores(self, page):
            raise AssertionError("ML detector must not run for signal-only page")

    extractor._ml_detector = FailDetector()
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


def test_model_disabled_prefers_wired_overlapping_wireless_candidate(monkeypatch):
    extractor = TableExtractor(use_ml_table_detector=False)
    wired = _table("line_projection", 10)
    wireless = _table("wireless_span_recovery", 20)
    extractor._wireless_extractor.extract_zebra = lambda page: []
    extractor._wired_extractor.extract = lambda page: [wired]
    extractor._extract_via_text_alignment = (
        lambda page, excluded_regions=None: [wireless]
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == [wired]


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


def test_contained_wired_fragments_recover_full_model_region():
    extractor = TableExtractor()
    left = _table("line_projection", 10)
    right = _table("line_projection", 130)
    full = _table("english_general_wireless", 0)
    full.bbox = BBox(0, 0, 250, 110)
    calls = []
    def recover(page, **kwargs):
        calls.append(kwargs["table_bbox"])
        return [full]
    extractor._wireless_extractor.extract = recover
    result = extractor._recover_tables_from_regions(
        _page(), [(full.bbox, 0.95)], [left, right], "en")
    assert result == [full]
    assert calls == [full.bbox]


def test_unassigned_native_span_recovers_larger_model_region():
    extractor = TableExtractor()
    wired = _table("line_projection", 10)
    full = _table("english_general_wireless", 0)
    full.bbox = BBox(0, 0, 250, 110)
    page = _page()
    page.get_text = lambda mode: {"blocks": [{"lines": [{"spans": [
        {"text": "2023", "bbox": (160, 25, 190, 35)}]}]}]}
    extractor._wireless_extractor.extract = lambda *args, **kwargs: [full]
    assert extractor._recover_tables_from_regions(
        page, [(full.bbox, 0.95)], [wired], "en") == [full]


def test_partial_overlap_does_not_replace_independent_wired_table():
    extractor = TableExtractor()
    wired = _table("line_projection", 10)
    extractor._wireless_extractor.extract = lambda *args, **kwargs: (
        (_ for _ in ()).throw(AssertionError("must retain wired")))
    assert extractor._recover_tables_from_regions(
        _page(), [(BBox(60, 0, 200, 110), 0.95)], [wired], "en") == [wired]


def test_failed_full_region_recovery_keeps_wired_fragments():
    extractor = TableExtractor()
    wired = [_table("line_projection", 10), _table("line_projection", 130)]
    extractor._wireless_extractor.extract = lambda *args, **kwargs: []
    assert extractor._recover_tables_from_regions(
        _page(), [(BBox(0, 0, 250, 110), 0.95)], wired, "en") == wired


def test_model_entry_recovers_contained_wired_fragments(monkeypatch):
    extractor = TableExtractor()
    wired = [_table("line_projection", 10), _table("line_projection", 130)]
    full = _table("english_general_wireless", 0)
    full.bbox = BBox(0, 0, 250, 110)
    _configure_rule_candidates(extractor, wired)
    extractor._ml_detector = SimpleNamespace(
        detect_with_scores=lambda page: [(full.bbox, 0.95)])
    extractor._wireless_extractor.extract = lambda *args, **kwargs: [full]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None)
    assert extractor.extract(_page()) == [full]


def test_region_recovery_may_preserve_two_independent_tables():
    extractor = TableExtractor()
    wired = [_table("line_projection", 10), _table("line_projection", 130)]
    extractor._wireless_extractor.extract = lambda *args, **kwargs: wired
    assert extractor._recover_tables_from_regions(
        _page(), [(BBox(0, 0, 250, 110), 0.95)], wired, "en") == wired


def test_span_inside_wired_or_outside_model_does_not_trigger_recovery():
    extractor = TableExtractor()
    wired = _table("line_projection", 10)
    page = _page()
    page.get_text = lambda mode: {"blocks": [{"lines": [{"spans": [
        {"text": "data", "bbox": (20, 25, 60, 35)},
        {"text": "footnote", "bbox": (20, 125, 60, 135)}]}]}]}
    extractor._wireless_extractor.extract = lambda *args, **kwargs: (
        (_ for _ in ()).throw(AssertionError("must retain wired")))
    assert extractor._recover_tables_from_regions(
        page, [(BBox(0, 0, 250, 110), 0.95)], [wired], "en") == [wired]


def test_model_disabled_retains_contained_wired_fragments():
    extractor = TableExtractor(use_ml_table_detector=False)
    wired = [_table("line_projection", 10), _table("line_projection", 130)]
    extractor._wireless_extractor.extract = lambda *args, **kwargs: (
        (_ for _ in ()).throw(AssertionError("must retain rule behavior")))
    assert extractor._recover_tables_from_regions(
        _page(), [(BBox(0, 0, 250, 110), 0.95)], wired, "en") == wired
