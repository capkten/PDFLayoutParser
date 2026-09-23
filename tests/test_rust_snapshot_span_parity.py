from typing import Sequence
import fitz
import pytest

from hexai_pdf_parser.models import BBox
from hexai_pdf_parser.pdf_snapshot import PageSnapshot, capture_page_snapshot
from hexai_pdf_parser.tables.wireless_table_recovery import (
    NativeSpan,
    collect_native_spans_from_snapshot as python_collect_native_spans,
)
from hexai_pdf_parser import rust_adapter


class StrictSpyPage:
    """A proxy over fitz.Page that raises if any read methods are called while locked."""

    def __init__(self, page: fitz.Page) -> None:
        self._page = page
        self.locked = False

    def __getattr__(self, name: str):
        if self.locked:
            forbidden_prefixes = ("get_text", "get_drawings", "get_pixmap", "get_images", "get_bboxlog")
            if any(name.startswith(p) for p in forbidden_prefixes):
                raise AssertionError(f"StrictSpyPage violation: forbidden method {name} called after snapshot capture!")
        return getattr(self._page, name)


def _assert_spans_equal(actual_spans: Sequence[NativeSpan], expected_spans: Sequence[NativeSpan]):
    assert len(actual_spans) == len(expected_spans), (
        f"Span count mismatch: got {len(actual_spans)}, expected {len(expected_spans)}"
    )
    for idx, (actual, expected) in enumerate(zip(actual_spans, expected_spans)):
        assert actual.text == expected.text, f"Span {idx} text mismatch: {actual.text!r} vs {expected.text!r}"
        assert actual.order == expected.order, f"Span {idx} order mismatch: {actual.order} vs {expected.order}"
        assert actual.bbox.x0 == pytest.approx(expected.bbox.x0, abs=1e-3), f"Span {idx} bbox.x0 mismatch"
        assert actual.bbox.y0 == pytest.approx(expected.bbox.y0, abs=1e-3), f"Span {idx} bbox.y0 mismatch"
        assert actual.bbox.x1 == pytest.approx(expected.bbox.x1, abs=1e-3), f"Span {idx} bbox.x1 mismatch"
        assert actual.bbox.y1 == pytest.approx(expected.bbox.y1, abs=1e-3), f"Span {idx} bbox.y1 mismatch"
        assert actual.font == expected.font, f"Span {idx} font mismatch: {actual.font!r} vs {expected.font!r}"
        if expected.size is not None and actual.size is not None:
            assert actual.size == pytest.approx(expected.size, abs=1e-3), f"Span {idx} size mismatch"
        assert actual.source_position == expected.source_position, (
            f"Span {idx} source_position mismatch: {actual.source_position} vs {expected.source_position}"
        )
        assert len(actual.characters) == len(expected.characters), (
            f"Span {idx} characters count mismatch: {len(actual.characters)} vs {len(expected.characters)}"
        )
        for c_idx, ((ac_char, ac_box), (ex_char, ex_box)) in enumerate(
            zip(actual.characters, expected.characters)
        ):
            assert ac_char == ex_char, f"Span {idx} char {c_idx} mismatch: {ac_char!r} vs {ex_char!r}"
            assert ac_box.x0 == pytest.approx(ex_box.x0, abs=1e-3)
            assert ac_box.y0 == pytest.approx(ex_box.y0, abs=1e-3)
            assert ac_box.x1 == pytest.approx(ex_box.x1, abs=1e-3)
            assert ac_box.y1 == pytest.approx(ex_box.y1, abs=1e-3)


def test_real_pdf_collect_native_spans_parity():
    """Verify parity on a real Chinese financial report PDF page."""
    doc = fitz.open("tests/fixtures/page_437_wireless.pdf")
    try:
        page = doc[0]
        snapshot = capture_page_snapshot(page, page_index=0)

        # 1. Full page parity
        expected = python_collect_native_spans(snapshot)
        actual = rust_adapter.collect_native_spans_from_snapshot(snapshot)
        assert len(actual) > 50
        _assert_spans_equal(actual, expected)

        # 2. Allowed regions parity
        allowed = [BBox(50, 100, 500, 400)]
        expected_allowed = python_collect_native_spans(snapshot, allowed_regions=allowed)
        actual_allowed = rust_adapter.collect_native_spans_from_snapshot(snapshot, allowed_regions=allowed)
        assert len(actual_allowed) > 0
        _assert_spans_equal(actual_allowed, expected_allowed)

        # 3. Excluded regions parity
        excluded = [BBox(50, 100, 500, 200)]
        expected_excluded = python_collect_native_spans(
            snapshot, allowed_regions=allowed, excluded_regions=excluded
        )
        actual_excluded = rust_adapter.collect_native_spans_from_snapshot(
            snapshot, allowed_regions=allowed, excluded_regions=excluded
        )
        assert len(actual_excluded) > 0
        _assert_spans_equal(actual_excluded, expected_excluded)
    finally:
        doc.close()


def _make_char(c: str, x0: float, y0: float, x1: float, y1: float, pos: tuple[int, int, int, int]):
    return {
        "c": c,
        "bbox": (x0, y0, x1, y1),
        "raw_source_position": pos,
        "source_order": pos[3],
    }


def _make_span(text: str, bbox: tuple[float, float, float, float], pos: tuple[int, int, int]):
    chars = [
        _make_char(ch, bbox[0] + i * 10, bbox[1], bbox[0] + (i + 1) * 10, bbox[3], (*pos, i))
        for i, ch in enumerate(text)
    ]
    return {
        "text": text,
        "bbox": bbox,
        "font": "SimSun",
        "size": 10.0,
        "flags": 0,
        "chars": tuple(chars),
        "raw_source_position": pos,
        "source_order": pos[2],
    }


def _make_synthetic_snapshot():
    """Create a synthetic PageSnapshot with diverse span scenarios."""
    blocks = [
        # Block 0: Table Header & Row
        {
            "type": 0,
            "bbox": (50.0, 100.0, 350.0, 150.0),
            "raw_source_position": (0,),
            "source_order": 0,
            "lines": [
                {
                    "bbox": (50.0, 100.0, 350.0, 120.0),
                    "raw_source_position": (0, 0),
                    "source_order": 0,
                    "spans": [
                        _make_span("项目", (50.0, 100.0, 90.0, 120.0), (0, 0, 0)),
                        _make_span("金额", (150.0, 100.0, 190.0, 120.0), (0, 0, 1)),
                        _make_span("比例", (250.0, 100.0, 290.0, 120.0), (0, 0, 2)),
                    ],
                },
                {
                    "bbox": (50.0, 130.0, 350.0, 150.0),
                    "raw_source_position": (0, 1),
                    "source_order": 1,
                    "spans": [
                        _make_span("流动资产", (50.0, 130.0, 110.0, 150.0), (0, 1, 0)),
                        # Empty whitespace span (should be filtered)
                        _make_span("   ", (120.0, 130.0, 140.0, 150.0), (0, 1, 1)),
                        _make_span("1,000.00", (150.0, 130.0, 210.0, 150.0), (0, 1, 2)),
                    ],
                },
            ],
        },
        # Block 1: Body text mentioning page number (should NOT be filtered as footer)
        {
            "type": 0,
            "bbox": (50.0, 300.0, 450.0, 320.0),
            "raw_source_position": (1,),
            "source_order": 1,
            "lines": [
                {
                    "bbox": (50.0, 300.0, 450.0, 320.0),
                    "raw_source_position": (1, 0),
                    "source_order": 2,
                    "spans": [
                        _make_span(
                            "正文说明：第 1 页 / 共 5 页 见附注",
                            (50.0, 300.0, 350.0, 320.0),
                            (1, 0, 0),
                        ),
                    ],
                }
            ],
        },
        # Block 2: Bottom footer line matching regex (should be strictly filtered)
        {
            "type": 0,
            "bbox": (200.0, 750.0, 350.0, 770.0),
            "raw_source_position": (2,),
            "source_order": 2,
            "lines": [
                {
                    "bbox": (200.0, 750.0, 350.0, 770.0),
                    "raw_source_position": (2, 0),
                    "source_order": 3,
                    "spans": [
                        _make_span("第 1 页 / 共 5 页", (200.0, 750.0, 350.0, 770.0), (2, 0, 0)),
                    ],
                }
            ],
        },
    ]

    all_spans = []
    for b in blocks:
        for l in b["lines"]:
            all_spans.extend(l["spans"])

    snapshot = PageSnapshot(
        schema_version=1,
        version=1,
        page_index=0,
        geometry={
            "rect": (0.0, 0.0, 600.0, 800.0),
            "x0": 0.0,
            "y0": 0.0,
            "x1": 600.0,
            "y1": 800.0,
            "width": 600.0,
            "height": 800.0,
            "rotation": 0,
        },
        text_blocks=tuple(blocks),
        spans=tuple(all_spans),
        characters=(),
        words=(),
        drawings=(),
        allowed_regions=(),
        excluded_regions=(),
        extraction_options={},
        summary={},
    )
    return snapshot


def test_synthetic_snapshot_parity_and_footer_filtering():
    """Verify footer filtering, whitespace filtering, and span order parity."""
    snapshot = _make_synthetic_snapshot()

    expected = python_collect_native_spans(snapshot)
    actual = rust_adapter.collect_native_spans_from_snapshot(snapshot)

    # 1. Parity check
    _assert_spans_equal(actual, expected)

    # 2. Bottom footer filtered check
    footer_spans = [s for s in actual if "第 1 页 / 共 5 页" in s.text and s.bbox.y0 >= 680]
    assert len(footer_spans) == 0, "Footer page number at page bottom must be filtered"

    # 3. Body text retained check
    body_spans = [s for s in actual if "正文说明" in s.text]
    assert len(body_spans) == 1, "Body text mentioning page number should be retained"

    # 4. Whitespace span filtered check
    empty_spans = [s for s in actual if not s.text.strip()]
    assert len(empty_spans) == 0, "Empty or whitespace-only spans must be filtered"

    # 5. Continuous order numbering
    orders = [s.order for s in actual]
    assert orders == list(range(len(actual))), "Order should increment monotonically without gaps"


def test_strict_spy_page_zero_read():
    """Verify strictly 0 PyMuPDF read calls happen during span extraction."""
    doc = fitz.open("tests/fixtures/page_437_wireless.pdf")
    try:
        page = doc[0]
        spy_page = StrictSpyPage(page)
        snapshot = capture_page_snapshot(spy_page, page_index=0)
        spy_page.locked = True

        # After snapshot capture, reading is forbidden
        spans = rust_adapter.collect_native_spans_from_snapshot(snapshot)
        assert len(spans) > 50
    finally:
        doc.close()
