"""Tests for Rust wired table geometry and region detection kernels."""

import pytest
from hexai_pdf_parser.rust_adapter import (
    merge_h_lines,
    merge_v_lines,
    merge_region_line_coordinates,
    lines_intersect,
    find_table_regions,
    snap_coordinates,
    snap_grid_coordinates,
    complete_partial_outer_boundaries,
)


def test_merge_h_lines_normal():
    lines = [(0.0, 10.0, 10.0, 10.0), (10.5, 10.2, 20.0, 10.2)]
    merged = merge_h_lines(lines, merge_group_tol=0.3)
    assert len(merged) == 1
    assert merged[0] == pytest.approx((0.0, 10.1, 20.0, 10.1))


def test_merge_h_lines_gap_not_connected():
    lines = [
        (10.0, 20.0, 50.0, 20.0),
        (53.5, 20.0, 90.0, 20.0),
    ]
    merged = merge_h_lines(lines, merge_group_tol=0.3)
    assert len(merged) == 2
    assert merged[0] == (10.0, 20.0, 50.0, 20.0)
    assert merged[1] == (53.5, 20.0, 90.0, 20.0)


def test_merge_v_lines_normal():
    v_lines = [
        (28.0, 10.0, 28.0, 50.0),
        (28.1, 51.5, 28.1, 90.0),
    ]
    merged = merge_v_lines(v_lines, h_lines=[], line_tolerance=2.3)
    assert len(merged) == 1
    assert merged[0][0] == pytest.approx(28.05)
    assert merged[0][1] == pytest.approx(10.0)
    assert merged[0][3] == pytest.approx(90.0)


def test_merge_v_lines_gap_not_connected():
    v_lines = [
        (28.0, 10.0, 28.0, 50.0),
        (28.0, 52.5, 28.0, 90.0),
    ]
    merged = merge_v_lines(v_lines, h_lines=[], line_tolerance=2.3)
    assert len(merged) == 2
    assert merged[0] == (28.0, 10.0, 28.0, 50.0)
    assert merged[1] == (28.0, 52.5, 28.0, 90.0)


def test_region_line_merge_horizontal():
    h_lines = [
        (20.0, 50.0, 80.0, 50.0),
        (80.4, 50.6, 120.0, 50.6),
    ]
    merged = merge_region_line_coordinates(h_lines, horizontal=True, tolerance=2.3)
    assert len(merged) == 1
    assert merged[0][1] == pytest.approx(50.3)
    assert merged[0][0] == pytest.approx(20.0)
    assert merged[0][2] == pytest.approx(120.0)


def test_region_line_merge_vertical():
    v_lines = [
        (99.00, 87.24, 99.00, 414.60),
        (98.40, 415.08, 98.40, 705.96),
    ]
    merged = merge_region_line_coordinates(v_lines, horizontal=False, tolerance=2.3)
    assert len(merged) == 1
    assert merged[0][0] == pytest.approx(98.70)
    assert merged[0][1] == pytest.approx(87.24)
    assert merged[0][3] == pytest.approx(705.96)


def test_lines_intersect():
    h_line = (10.0, 20.0, 100.0, 20.0)
    v_touch = (50.0, 0.0, 50.0, 40.0)
    v_miss = (120.0, 0.0, 120.0, 40.0)
    assert lines_intersect(h_line, v_touch, tolerance=2.3) is True
    assert lines_intersect(h_line, v_miss, tolerance=2.3) is False


def test_find_table_regions_disconnected():
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
    regions = find_table_regions(h_lines, v_lines, tolerance=2.3)
    assert len(regions) == 2
    bboxes = [(r[0]["x0"], r[0]["y0"], r[0]["x1"], r[0]["y1"]) for r in regions]
    assert bboxes == [
        (10.0, 10.0, 110.0, 110.0),
        (200.0, 200.0, 300.0, 300.0),
    ]


def test_find_table_regions_ignores_unintersected_h_lines():
    h_lines = [
        (20.0, 0.0, 100.0, 0.0),
        (10.0, 10.0, 110.0, 10.0),
        (10.0, 60.0, 110.0, 60.0),
        (10.0, 110.0, 110.0, 110.0),
        (10.0, 130.0, 110.0, 130.0),
    ]
    v_lines = [
        (10.0, 10.0, 10.0, 110.0),
        (60.0, 10.0, 60.0, 110.0),
        (110.0, 10.0, 110.0, 110.0),
    ]
    regions = find_table_regions(h_lines, v_lines, tolerance=2.3)
    assert len(regions) == 1
    bbox, reg_h, reg_v = regions[0]
    assert (bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]) == pytest.approx(
        (10.0, 10.0, 110.0, 110.0)
    )
    assert [line[1] for line in reg_h] == pytest.approx([10.0, 60.0, 110.0])
    assert len(reg_v) == 3


def test_snap_coordinates():
    coords = [10.2, 10.8, 25.1, 50.0]
    anchors = [10.0, 25.0, 50.5]
    snapped = snap_coordinates(coords, anchors, tol=1.5)
    assert snapped == [10.0, 25.0, 50.5]


def test_snap_grid_coordinates():
    lines = [
        (10.0, 20.0, 100.0, 20.0),
        (10.0, 50.0, 100.0, 50.0),
        (10.0, 80.0, 100.0, 80.0),
    ]
    coords = snap_grid_coordinates(
        start=20.0,
        end=80.0,
        orthogonal_start=10.0,
        orthogonal_end=100.0,
        lines=lines,
        horizontal=True,
        tolerance=2.3,
    )
    assert coords == pytest.approx([20.0, 50.0, 80.0])


def test_complete_partial_outer_boundaries():
    bbox = {"x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 100.0}
    h_lines = [
        (0.0, 0.0, 50.0, 0.0),
        (0.0, 50.0, 100.0, 50.0),
        (0.0, 100.0, 100.0, 100.0),
    ]
    v_lines = [
        (0.0, 0.0, 0.0, 100.0),
        (50.0, 0.0, 50.0, 100.0),
        (100.0, 0.0, 100.0, 100.0),
    ]
    h_ys = [0.0, 50.0, 100.0]
    v_xs = [0.0, 50.0, 100.0]
    eff_h, eff_v = complete_partial_outer_boundaries(
        bbox=bbox,
        h_lines=h_lines,
        v_lines=v_lines,
        h_ys=h_ys,
        v_xs=v_xs,
        tolerance=2.3,
    )
    assert len(eff_h) >= len(h_lines)
    assert len(eff_v) >= len(v_lines)
