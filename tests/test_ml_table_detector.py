from types import SimpleNamespace

import fitz

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.ml.ml_table_detector import MLTableDetector


def test_expand_bbox_includes_directly_intersecting_words_once():
    result = MLTableDetector._expand_bbox_to_touching_words(
        BBox(10, 10, 20, 20),
        [(8, 12, 15, 18, "direct")],
    )

    assert result == BBox(8, 10, 20, 20)


def test_expand_bbox_does_not_chain_through_newly_expanded_words():
    result = MLTableDetector._expand_bbox_to_touching_words(
        BBox(10, 10, 20, 20),
        [(9, 12, 15, 18, "direct"), (4, 12, 9.5, 18, "chained")],
    )

    assert result == BBox(9, 10, 20, 20)


def test_expand_bbox_ignores_page_background_drawing():
    page = SimpleNamespace(
        rect=fitz.Rect(0, 0, 100, 100),
        get_drawings=lambda: [{"rect": fitz.Rect(0, 0, 100, 100)}],
    )

    result = MLTableDetector._expand_bbox_to_touching_words(
        BBox(10, 10, 20, 20),
        [(12, 12, 15, 18, "direct")],
        page=page,
    )

    assert result == BBox(10, 10, 20, 20)
