from __future__ import annotations

from types import SimpleNamespace

import fitz
import pytest

from hexai_pdf_parser.core.models import BBox, Cell
from hexai_pdf_parser.tables.extractors.wired_table_extractor import WiredTableExtractor


def test_extract_lines_ignores_white_fill_only_page_border():
    extractor = WiredTableExtractor()
    page = SimpleNamespace(
        get_drawings=lambda: [
            {"color": None, "fill": (1.0, 1.0, 1.0), "items": [("re", SimpleNamespace(x0=24.0, y0=24.0, x1=571.0, y1=24.5))]},
            {"color": None, "fill": (1.0, 1.0, 1.0), "items": [("re", SimpleNamespace(x0=24.0, y0=817.5, x1=571.0, y1=818.0))]},
            {"color": None, "fill": (1.0, 1.0, 1.0), "items": [("re", SimpleNamespace(x0=24.0, y0=24.0, x1=24.5, y1=818.0))]},
            {"color": None, "fill": (1.0, 1.0, 1.0), "items": [("re", SimpleNamespace(x0=571.0, y0=24.0, x1=571.5, y1=818.0))]},
        ]
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == []
    assert v_lines == []


def test_extract_lines_accepts_visible_fill_only_rules():
    extractor = WiredTableExtractor()
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "items": [
                    ("re", SimpleNamespace(x0=10.0, y0=20.0, x1=110.0, y1=20.5))
                ],
            },
            {
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "items": [
                    ("re", SimpleNamespace(x0=10.0, y0=20.0, x1=10.5, y1=80.0))
                ],
            },
        ]
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == [(10.0, 20.25, 110.0, 20.25)]
    assert v_lines == [(10.25, 20.0, 10.25, 80.0)]


def test_extract_lines_ignores_non_narrow_filled_path_outline():
    extractor = WiredTableExtractor()
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "type": "f",
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "rect": fitz.Rect(10.0, 20.0, 110.0, 80.0),
                "items": [
                    ("l", fitz.Point(10.0, 20.0), fitz.Point(110.0, 20.0)),
                    ("l", fitz.Point(110.0, 20.0), fitz.Point(110.0, 80.0)),
                    ("l", fitz.Point(110.0, 80.0), fitz.Point(10.0, 80.0)),
                    ("l", fitz.Point(10.0, 80.0), fitz.Point(10.0, 20.0)),
                ],
            }
        ]
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == []
    assert v_lines == []


def test_extract_lines_keeps_re_rule_in_non_narrow_fill_path():
    extractor = WiredTableExtractor()
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "type": "f",
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "rect": fitz.Rect(10.0, 20.0, 110.0, 80.0),
                "items": [("re", fitz.Rect(10.0, 20.0, 110.0, 20.5))],
            }
        ]
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == [(10.0, 20.25, 110.0, 20.25)]
    assert v_lines == []


def test_extract_lines_recovers_rules_tiled_as_tiny_images():
    extractor = WiredTableExtractor()
    page = SimpleNamespace(
        get_drawings=lambda: [],
        get_image_info=lambda **_kwargs: [
            {"bbox": (x, 20.0, x + 1.0, 21.0), "width": 1, "height": 1}
            for x in range(10, 111)
        ] + [
            {"bbox": (60.0, y, 61.0, y + 1.0), "width": 1, "height": 1}
            for y in range(20, 81)
        ] + [
            {"bbox": (200.0, 200.0, 202.0, 202.0), "width": 2, "height": 2}
        ],
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == [(10.0, 20.5, 111.0, 20.5)]
    assert v_lines == [(60.5, 20.0, 60.5, 81.0)]


def test_extract_lines_compares_fill_only_rules_with_page_background():
    extractor = WiredTableExtractor()
    gray_samples = bytes([128, 128, 128] * 100)
    page = SimpleNamespace(
        get_pixmap=lambda **_kwargs: SimpleNamespace(
            width=10,
            height=10,
            n=3,
            samples=gray_samples,
        ),
        get_drawings=lambda: [
            {
                "color": None,
                "fill": (128 / 255, 128 / 255, 128 / 255),
                "items": [
                    ("re", SimpleNamespace(x0=10.0, y0=20.0, x1=110.0, y1=20.5))
                ],
            },
            {
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "items": [
                    ("re", SimpleNamespace(x0=10.0, y0=20.0, x1=10.5, y1=80.0))
                ],
            },
        ],
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == []
    assert v_lines == [(10.25, 20.0, 10.25, 80.0)]


def test_extract_lines_ignores_invisible_or_background_colored_dashed_rules():
    extractor = WiredTableExtractor()
    page = SimpleNamespace(
        get_pixmap=lambda **_kwargs: SimpleNamespace(
            width=10, height=10, n=3, samples=bytes([255, 255, 255] * 100)
        ),
        get_drawings=lambda: [
            {
                "color": (1.0, 1.0, 1.0),
                "fill": None,
                "opacity": 1.0,
                "dashes": "[1 1] 0",
                "items": [("l", SimpleNamespace(x=10.0, y=20.0), SimpleNamespace(x=110.0, y=20.0))],
            },
            {
                "color": (0.0, 0.0, 0.0),
                "fill": None,
                "opacity": 0.0,
                "dashes": "[1 1] 0",
                "items": [("l", SimpleNamespace(x=10.0, y=30.0), SimpleNamespace(x=110.0, y=30.0))],
            },
        ],
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == []
    assert v_lines == []


def test_extract_lines_keeps_visible_black_dashed_rules():
    extractor = WiredTableExtractor()
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "color": (0.0, 0.0, 0.0),
                "fill": None,
                "opacity": 1.0,
                "dashes": "[1 1] 0",
                "items": [("l", SimpleNamespace(x=10.0, y=20.0), SimpleNamespace(x=110.0, y=20.0))],
            }
        ],
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == [(10.0, 20.0, 110.0, 20.0)]
    assert v_lines == []


def test_extract_lines_ignores_type3_glyph_drawings_but_keeps_table_rules():
    extractor = WiredTableExtractor()
    glyph_drawing = {
        "rect": fitz.Rect(10.5, 10.5, 19.5, 20.5),
        "color": None,
        "fill": (0.0, 0.0, 0.0),
        "items": [
            ("l", fitz.Point(11.0, 12.0), fitz.Point(19.0, 12.0)),
            ("l", fitz.Point(15.0, 11.0), fitz.Point(15.0, 20.0)),
        ],
    }
    table_drawing = {
        "rect": fitz.Rect(0.0, 40.0, 100.0, 100.0),
        "color": (0.0, 0.0, 0.0),
        "fill": None,
        "items": [
            ("l", fitz.Point(0.0, 40.0), fitz.Point(100.0, 40.0)),
            ("l", fitz.Point(0.0, 70.0), fitz.Point(100.0, 70.0)),
            ("l", fitz.Point(0.0, 100.0), fitz.Point(100.0, 100.0)),
            ("l", fitz.Point(0.0, 40.0), fitz.Point(0.0, 100.0)),
            ("l", fitz.Point(100.0, 40.0), fitz.Point(100.0, 100.0)),
        ],
    }
    page = SimpleNamespace(
        get_fonts=lambda **_kwargs: [(1, "n/a", "Type3", "T54", "T54", "", 0)],
        get_text=lambda _kind: {
            "blocks": [
                {
                    "lines": [
                        {
                            "dir": (1.0, 0.0),
                            "spans": [
                                {
                                    "font": "T54",
                                    "size": 10.0,
                                    "chars": [
                                        {
                                            "c": "A",
                                            "origin": (10.0, 20.0),
                                            "bbox": (10.0, -80.0, 20.0, 120.0),
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        },
        get_drawings=lambda: [glyph_drawing, table_drawing],
    )

    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert h_lines == [
        (0.0, 40.0, 100.0, 40.0),
        (0.0, 70.0, 100.0, 70.0),
        (0.0, 100.0, 100.0, 100.0),
    ]
    assert v_lines == [
        (0.0, 40.0, 0.0, 100.0),
        (100.0, 40.0, 100.0, 100.0),
    ]


def test_find_table_regions_ignores_horizontal_lines_without_vertical_intersections():
    extractor = WiredTableExtractor()
    h_lines = [
        (20.0, 0.0, 100.0, 0.0),  # unrelated page/header line
        (10.0, 10.0, 110.0, 10.0),
        (10.0, 60.0, 110.0, 60.0),
        (10.0, 110.0, 110.0, 110.0),
        (10.0, 130.0, 110.0, 130.0),  # below the table, no vertical contact
    ]
    v_lines = [
        (10.0, 10.0, 10.0, 110.0),
        (60.0, 10.0, 60.0, 110.0),
        (110.0, 10.0, 110.0, 110.0),
    ]

    regions = extractor._find_table_regions(h_lines, v_lines)

    assert len(regions) == 1
    bbox, region_h, region_v = regions[0]
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == pytest.approx(
        (10.0, 10.0, 110.0, 110.0)
    )
    assert [line[1] for line in region_h] == pytest.approx([10.0, 60.0, 110.0])
    assert len(region_v) == 3


def test_find_table_regions_splits_disconnected_line_components():
    extractor = WiredTableExtractor()
    h_lines = [
        (10.0, 10.0, 110.0, 10.0),
        (10.0, 60.0, 110.0, 60.0),
        (10.0, 110.0, 110.0, 110.0),
        (200.0, 200.0, 300.0, 200.0),
        (200.0, 250.0, 300.0, 250.0),
        (200.0, 300.0, 300.0, 300.0),
    ]
    v_lines = [
        (10.0, 10.0, 10.0, 110.0),
        (60.0, 10.0, 60.0, 110.0),
        (110.0, 10.0, 110.0, 110.0),
        (200.0, 200.0, 200.0, 300.0),
        (250.0, 200.0, 250.0, 300.0),
        (300.0, 200.0, 300.0, 300.0),
    ]

    regions = extractor._find_table_regions(h_lines, v_lines)

    assert len(regions) == 2
    bboxes = sorted(
        (bbox.x0, bbox.y0, bbox.x1, bbox.y1) for bbox, _, _ in regions
    )
    assert bboxes == [
        (10.0, 10.0, 110.0, 110.0),
        (200.0, 200.0, 300.0, 300.0),
    ]


def test_build_cells_for_three_line_table_uses_horizontal_bounds_as_columns():
    extractor = WiredTableExtractor()
    cells = extractor._build_cells_for_region(
        bbox=BBox(0.0, 0.0, 100.0, 20.0),
        h_lines=[
            (0.0, 0.0, 100.0, 0.0),
            (0.0, 10.0, 100.0, 10.0),
            (0.0, 20.0, 100.0, 20.0),
        ],
        v_lines=[
            (40.0, 0.0, 40.0, 20.0),
            (60.0, 0.0, 60.0, 20.0),
        ],
    )

    assert len(cells) == 6
    assert sorted({cell.bbox.x0 for cell in cells}) == [0.0, 40.0, 60.0]
    assert sorted({cell.bbox.x1 for cell in cells}) == [40.0, 60.0, 100.0]


def test_find_table_regions_accepts_one_internal_vertical_line():
    extractor = WiredTableExtractor()
    h_lines = [
        (0.0, 0.0, 100.0, 0.0),
        (0.0, 10.0, 100.0, 10.0),
        (0.0, 20.0, 100.0, 20.0),
    ]
    v_lines = [(40.0, 0.0, 40.0, 20.0)]

    regions = extractor._find_table_regions(h_lines, v_lines)

    assert len(regions) == 1
    bbox, _, region_v = regions[0]
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == pytest.approx(
        (0.0, 0.0, 100.0, 20.0)
    )
    assert len(region_v) == 1


def test_extract_rejects_single_cell_wire_frame():
    rectangle = fitz.Rect(10.0, 20.0, 110.0, 50.0)
    left_edge = 10.4
    right_edge = 109.6
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "color": (0.0, 0.0, 0.0),
                "fill": None,
                "items": [
                    ("l", fitz.Point(rectangle.x0, rectangle.y0), fitz.Point(rectangle.x1, rectangle.y0)),
                    ("l", fitz.Point(rectangle.x0, rectangle.y1), fitz.Point(rectangle.x1, rectangle.y1)),
                    ("l", fitz.Point(left_edge, rectangle.y0), fitz.Point(left_edge, rectangle.y1)),
                    ("l", fitz.Point(right_edge, rectangle.y0), fitz.Point(right_edge, rectangle.y1)),
                ],
            }
        ],
        get_fonts=lambda **_kwargs: [],
        get_image_info=lambda **_kwargs: [],
        get_text=lambda kind: (
            [(25.0, 28.0, 45.0, 38.0, "value", 0, 0, 0)]
            if kind == "words"
            else {"blocks": []}
        ),
    )

    assert WiredTableExtractor().extract(page) == []


def test_extract_collapses_filled_path_edges_before_single_cell_filter():
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "type": "f",
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "rect": fitz.Rect(10.0, 20.0, 110.0, 20.48),
                "items": [
                    ("l", fitz.Point(10.0, 20.0), fitz.Point(110.0, 20.0)),
                    ("l", fitz.Point(110.0, 20.48), fitz.Point(10.0, 20.48)),
                ],
            },
            {
                "type": "f",
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "rect": fitz.Rect(10.0, 50.0, 110.0, 50.48),
                "items": [
                    ("l", fitz.Point(10.0, 50.0), fitz.Point(110.0, 50.0)),
                    ("l", fitz.Point(110.0, 50.48), fitz.Point(10.0, 50.48)),
                ],
            },
            {
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "items": [("re", fitz.Rect(10.0, 20.48, 10.48, 50.0))],
            },
            {
                "color": None,
                "fill": (0.0, 0.0, 0.0),
                "items": [("re", fitz.Rect(109.52, 20.48, 110.0, 50.0))],
            },
        ],
        get_fonts=lambda **_kwargs: [],
        get_image_info=lambda **_kwargs: [],
        get_text=lambda kind: (
            [(25.0, 28.0, 45.0, 38.0, "value", 0, 0, 0)]
            if kind == "words"
            else {"blocks": []}
        ),
    )

    extractor = WiredTableExtractor()
    h_lines, v_lines = extractor._extract_lines_from_drawings(page)

    assert len(h_lines) == 2
    for line, expected_y in zip(h_lines, (20.24, 50.24)):
        assert line[0] == pytest.approx(10.0)
        assert line[1] == pytest.approx(expected_y)
        assert line[2] == pytest.approx(110.0)
        assert line[3] == pytest.approx(expected_y)

    assert len(v_lines) == 2
    for line, expected_x in zip(v_lines, (10.24, 109.76)):
        assert line[0] == pytest.approx(expected_x)
        assert line[1] == pytest.approx(20.48)
        assert line[2] == pytest.approx(expected_x)
        assert line[3] == pytest.approx(50.0)
    assert extractor.extract(page) == []


def test_extract_keeps_multi_cell_wire_table():
    rectangle = fitz.Rect(10.0, 20.0, 110.0, 50.0)
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "color": (0.0, 0.0, 0.0),
                "fill": None,
                "items": [
                    ("l", fitz.Point(rectangle.x0, rectangle.y0), fitz.Point(rectangle.x1, rectangle.y0)),
                    ("l", fitz.Point(rectangle.x0, rectangle.y1), fitz.Point(rectangle.x1, rectangle.y1)),
                    ("l", fitz.Point(rectangle.x0, rectangle.y0), fitz.Point(rectangle.x0, rectangle.y1)),
                    ("l", fitz.Point(rectangle.x1, rectangle.y0), fitz.Point(rectangle.x1, rectangle.y1)),
                    ("l", fitz.Point(60.0, 20.0), fitz.Point(60.0, 50.0)),
                ],
            }
        ],
        get_fonts=lambda **_kwargs: [],
        get_image_info=lambda **_kwargs: [],
        get_text=lambda kind: (
            [
                (20.0, 28.0, 35.0, 38.0, "left", 0, 0, 0),
                (75.0, 28.0, 90.0, 38.0, "right", 0, 0, 0),
            ]
            if kind == "words"
            else {"blocks": []}
        ),
    )

    tables = WiredTableExtractor().extract(page)

    assert len(tables) == 1
    assert (tables[0].rows, tables[0].cols) == (1, 2)


def test_build_cells_respects_partial_line_segments_and_merges_missing_edges():
    extractor = WiredTableExtractor()
    cells = extractor._build_cells_for_region(
        bbox=BBox(0.0, 0.0, 100.0, 20.0),
        h_lines=[
            (0.0, 0.0, 100.0, 0.0),
            (0.0, 10.0, 100.0, 10.0),
            (0.0, 20.0, 100.0, 20.0),
        ],
        v_lines=[
            (0.0, 0.0, 0.0, 20.0),
            (50.0, 10.0, 50.0, 20.0),
            (100.0, 0.0, 100.0, 20.0),
        ],
    )

    assert len(cells) == 3
    merged = [cell for cell in cells if cell.colspan == 2]
    assert len(merged) == 1
    assert merged[0].bbox == BBox(0.0, 0.0, 100.0, 10.0)
    assert merged[0].colspan == 2


def test_build_cells_synthesizes_missing_top_and_bottom_edges():
    extractor = WiredTableExtractor()
    cells = extractor._build_cells_for_region(
        bbox=BBox(0.0, 0.0, 100.0, 30.0),
        h_lines=[
            (0.0, 10.0, 100.0, 10.0),
            (0.0, 20.0, 100.0, 20.0),
        ],
        v_lines=[
            (25.0, 0.0, 25.0, 30.0),
            (50.0, 0.0, 50.0, 30.0),
            (75.0, 0.0, 75.0, 30.0),
        ],
    )

    assert len(cells) == 12
    assert sorted({cell.bbox.y0 for cell in cells}) == [0.0, 10.0, 20.0]
    assert sorted({cell.bbox.y1 for cell in cells}) == [10.0, 20.0, 30.0]


def test_build_cells_recovers_repeated_horizontal_start_as_missing_leading_boundary():
    extractor = WiredTableExtractor()
    cells = extractor._build_cells_for_region(
        bbox=BBox(88.0, 0.0, 500.0, 100.0),
        h_lines=[
            (88.0, 0.0, 500.0, 0.0),
            (120.0, 1.0, 500.0, 1.0),
            (250.0, 20.0, 500.0, 20.0),
            (120.0, 40.0, 500.0, 40.0),
            (120.0, 60.0, 500.0, 60.0),
            (120.0, 80.0, 500.0, 80.0),
            (120.0, 100.0, 500.0, 100.0),
        ],
        v_lines=[
            (250.0, 1.0, 250.0, 100.0),
            (350.0, 1.0, 350.0, 100.0),
            (430.0, 1.0, 430.0, 100.0),
        ],
    )

    assert any(cell.bbox.x0 == 120.0 and cell.bbox.x1 == 250.0 for cell in cells)


def test_build_cells_accepts_visually_touching_lines_with_small_coordinate_gap():
    extractor = WiredTableExtractor(line_tolerance=2.0)
    cells = extractor._build_cells_for_region(
        bbox=BBox(0.0, 0.0, 100.0, 20.0),
        h_lines=[
            (0.0, 0.0, 100.0, 0.0),
            (0.0, 10.0, 100.0, 10.0),
            (0.0, 20.0, 100.0, 20.0),
        ],
        v_lines=[
            (0.0, 0.0, 0.0, 20.0),
            (50.5, 10.5, 50.5, 20.0),
            (100.0, 0.0, 100.0, 20.0),
        ],
    )

    assert len(cells) == 3
    assert any(cell.colspan == 2 for cell in cells)
    assert extractor._lines_intersect(
        h_line=(0.0, 10.0, 100.0, 10.0),
        v_line=(50.5, 10.5, 50.5, 20.0),
    )


def test_merge_oversegmented_line_columns_recomputes_colspan_after_pruning():
    extractor = WiredTableExtractor()
    cells = [
        Cell("merged", 0, 1, BBox(10.0, 0.0, 40.0, 10.0), colspan=3),
        Cell("", 0, 2, BBox(20.0, 0.0, 30.0, 10.0)),
        Cell("", 0, 3, BBox(30.0, 0.0, 40.0, 10.0)),
        Cell("next", 0, 4, BBox(40.0, 0.0, 50.0, 10.0)),
    ]

    result = extractor._merge_oversegmented_line_columns(cells)

    assert [(cell.text, cell.col_index, cell.colspan) for cell in result] == [
        ("merged", 0, 1),
        ("next", 1, 1),
    ]


def test_merge_oversegmented_line_columns_preserves_independent_empty_column():
    extractor = WiredTableExtractor()
    cells = [
        Cell("left", 0, 0, BBox(0.0, 0.0, 20.0, 10.0)),
        Cell("", 0, 1, BBox(20.0, 0.0, 29.4, 10.0)),
        Cell("right", 0, 2, BBox(29.4, 0.0, 60.0, 10.0)),
        Cell("left", 1, 0, BBox(0.0, 10.0, 20.0, 20.0)),
        Cell("", 1, 1, BBox(20.0, 10.0, 29.4, 20.0)),
        Cell("right", 1, 2, BBox(29.4, 10.0, 60.0, 20.0)),
    ]

    result = extractor._merge_oversegmented_line_columns(cells)

    assert [(cell.text, cell.col_index, cell.colspan) for cell in result] == [
        ("left", 0, 1),
        ("", 1, 1),
        ("right", 2, 1),
        ("left", 0, 1),
        ("", 1, 1),
        ("right", 2, 1),
    ]


def test_assign_text_to_line_cells_splits_word_at_physical_column_boundary():
    extractor = WiredTableExtractor()
    cells = [
        Cell("", 0, 0, BBox(220.11, 138.13, 233.28, 149.86)),
        Cell("", 0, 1, BBox(233.28, 138.13, 242.72, 149.86)),
    ]
    word = (223.976, 142.236, 241.712, 145.953, "减：专项", 0, 0, 0)
    raw_chars = [
        {"c": "减", "bbox": (223.976, 142.236, 227.694, 145.953)},
        {"c": "：", "bbox": (227.694, 142.236, 231.412, 145.953)},
        {"c": "专", "bbox": (234.277, 142.236, 237.995, 145.953)},
        {"c": "项", "bbox": (237.995, 142.236, 241.712, 145.953)},
    ]
    page = SimpleNamespace(
        get_text=lambda kind: (
            [word]
            if kind == "words"
            else {"blocks": [{"lines": [{"spans": [{"chars": raw_chars}]}]}]}
        )
    )

    result = extractor._assign_text_to_line_cells(cells, page)

    assert [cell.text for cell in result] == ["减：", "专项"]
