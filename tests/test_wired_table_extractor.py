from __future__ import annotations

import pytest

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.extractors.wired_table_extractor import WiredTableExtractor


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
