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
    build_cells_for_region,
    trim_ghost_edge_rows,
    merge_oversegmented_line_columns,
    assign_text_to_line_cells,
    extract_wired_region,
)
from hexai_pdf_parser.tables.extractors.wired_table_extractor import WiredTableExtractor


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


def test_build_cells_for_region_normal():
    bbox = {"x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 100.0}
    h_lines = [
        (0.0, 0.0, 100.0, 0.0),
        (0.0, 50.0, 100.0, 50.0),
        (0.0, 100.0, 100.0, 100.0),
    ]
    v_lines = [
        (0.0, 0.0, 0.0, 100.0),
        (50.0, 0.0, 50.0, 100.0),
        (100.0, 0.0, 100.0, 100.0),
    ]
    cells = build_cells_for_region(
        bbox=bbox,
        h_lines=h_lines,
        v_lines=v_lines,
        tolerance=2.3,
    )
    assert len(cells) == 4
    assert cells[0]["row"] == 0 and cells[0]["col"] == 0
    assert cells[1]["row"] == 0 and cells[1]["col"] == 1
    assert cells[2]["row"] == 1 and cells[2]["col"] == 0
    assert cells[3]["row"] == 1 and cells[3]["col"] == 1
    for c in cells:
        assert c["rowspan"] == 1
        assert c["colspan"] == 1


def test_build_cells_for_region_with_rowspan_and_colspan():
    # 2x2 网格，但是第 0 行中间竖线缺失 -> colspan=2
    # 第 1 行有两个单独单元格
    bbox = {"x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 100.0}
    h_lines = [
        (0.0, 0.0, 100.0, 0.0),
        (0.0, 50.0, 100.0, 50.0),
        (0.0, 100.0, 100.0, 100.0),
    ]
    v_lines = [
        (0.0, 0.0, 0.0, 100.0),
        (50.0, 50.0, 50.0, 100.0),  # 中间竖线只在第 1 行
        (100.0, 0.0, 100.0, 100.0),
    ]
    cells = build_cells_for_region(
        bbox=bbox,
        h_lines=h_lines,
        v_lines=v_lines,
        tolerance=2.3,
    )
    assert len(cells) == 3
    # 第一行合并为 colspan=2
    c0 = cells[0]
    assert c0["row"] == 0 and c0["col"] == 0
    assert c0["colspan"] == 2
    assert c0["rowspan"] == 1


def test_trim_ghost_edge_rows_removes_unsupported_and_thin_rows():
    h_lines = [(0.0, 50.0, 100.0, 50.0), (0.0, 100.0, 100.0, 100.0)]
    cells = [
        # 行 0：超薄缝隙行 (y0=49.0, y1=49.5, height=0.5 <= tol)，且无文字
        {"text": "", "row": 0, "col": 0, "rect": {"schema_version": 1, "x0": 0.0, "y0": 49.0, "x1": 100.0, "y1": 49.5}, "rowspan": 1, "colspan": 1},
        # 行 1：真实文字行
        {"text": "Data", "row": 1, "col": 0, "rect": {"schema_version": 1, "x0": 0.0, "y0": 50.0, "x1": 100.0, "y1": 100.0}, "rowspan": 1, "colspan": 1},
    ]
    trimmed = trim_ghost_edge_rows(cells, h_lines, tol=2.0)
    assert len(trimmed) == 1
    assert trimmed[0]["text"] == "Data"
    assert trimmed[0]["row"] == 0


def test_trim_ghost_edge_rows_preserves_legitimate_empty_row():
    h_lines = [
        (0.0, 10.0, 100.0, 10.0),
        (0.0, 30.0, 100.0, 30.0),
        (0.0, 50.0, 100.0, 50.0),
    ]
    cells = [
        # 行 0：空行，但高度为 20.0，且上下均有真实物理横线支撑
        {"text": "", "row": 0, "col": 0, "rect": {"schema_version": 1, "x0": 0.0, "y0": 10.0, "x1": 100.0, "y1": 30.0}, "rowspan": 1, "colspan": 1},
        # 行 1：文字行
        {"text": "Data", "row": 1, "col": 0, "rect": {"schema_version": 1, "x0": 0.0, "y0": 30.0, "x1": 100.0, "y1": 50.0}, "rowspan": 1, "colspan": 1},
    ]
    trimmed = trim_ghost_edge_rows(cells, h_lines, tol=2.0)
    assert len(trimmed) == 2
    assert trimmed[0]["row"] == 0
    assert trimmed[1]["row"] == 1


def test_merge_oversegmented_line_columns_removes_thin_or_covered_columns():
    cells = [
        # col 0: 正常列，有文字
        {"text": "Item", "row": 0, "col": 0, "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 30.0}, "rowspan": 1, "colspan": 1},
        # col 1: 超薄空列 (宽度 0.5 < tol=2.3)
        {"text": "", "row": 0, "col": 1, "rect": {"schema_version": 1, "x0": 50.0, "y0": 0.0, "x1": 50.5, "y1": 30.0}, "rowspan": 1, "colspan": 1},
        # col 2: 正常文字列
        {"text": "100", "row": 0, "col": 2, "rect": {"schema_version": 1, "x0": 50.5, "y0": 0.0, "x1": 100.0, "y1": 30.0}, "rowspan": 1, "colspan": 1},
    ]
    merged = merge_oversegmented_line_columns(cells, tolerance=2.3)
    assert len(merged) == 2
    assert merged[0]["col"] == 0 and merged[0]["text"] == "Item"
    assert merged[1]["col"] == 1 and merged[1]["text"] == "100"


def test_assign_text_to_line_cells_basic_and_split():
    cells = [
        {"text": "", "row": 0, "col": 0, "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 30.0}, "rowspan": 1, "colspan": 1},
        {"text": "", "row": 0, "col": 1, "rect": {"schema_version": 1, "x0": 50.0, "y0": 0.0, "x1": 100.0, "y1": 30.0}, "rowspan": 1, "colspan": 1},
    ]
    # 两个普通 word 分别落在两个单元格中
    words = [
        {"schema_version": 1, "text": "Left", "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 30.0, "y1": 20.0}, "order": 0, "block": 0, "line": 0},
        {"schema_version": 1, "text": "Right", "rect": {"schema_version": 1, "x0": 60.0, "y0": 10.0, "x1": 80.0, "y1": 20.0}, "order": 1, "block": 0, "line": 0},
    ]
    assigned = assign_text_to_line_cells(cells, words, chars=[], tolerance=2.3)
    assert assigned[0]["text"] == "Left"
    assert assigned[1]["text"] == "Right"


def test_assign_text_to_line_cells_split_word_crossing_boundary():
    cells = [
        {"text": "", "row": 0, "col": 0, "rect": {"schema_version": 1, "x0": 220.11, "y0": 138.13, "x1": 233.28, "y1": 149.86}, "rowspan": 1, "colspan": 1},
        {"text": "", "row": 0, "col": 1, "rect": {"schema_version": 1, "x0": 233.28, "y0": 138.13, "x1": 242.72, "y1": 149.86}, "rowspan": 1, "colspan": 1},
    ]
    word = {
        "schema_version": 1,
        "text": "减：专项",
        "rect": {"schema_version": 1, "x0": 223.976, "y0": 142.236, "x1": 241.712, "y1": 145.953},
        "order": 0,
        "block": 0,
        "line": 0,
    }
    raw_chars = [
        {"schema_version": 1, "text": "减", "rect": {"schema_version": 1, "x0": 223.976, "y0": 142.236, "x1": 227.694, "y1": 145.953}, "order": 0},
        {"schema_version": 1, "text": "：", "rect": {"schema_version": 1, "x0": 227.694, "y0": 142.236, "x1": 231.412, "y1": 145.953}, "order": 1},
        {"schema_version": 1, "text": "专", "rect": {"schema_version": 1, "x0": 234.277, "y0": 142.236, "x1": 237.995, "y1": 145.953}, "order": 2},
        {"schema_version": 1, "text": "项", "rect": {"schema_version": 1, "x0": 237.995, "y0": 142.236, "x1": 241.712, "y1": 145.953}, "order": 3},
    ]
    assigned = assign_text_to_line_cells(cells, [word], chars=raw_chars, tolerance=2.3)
    assert [c["text"] for c in assigned] == ["减：", "专项"]


def test_assign_text_to_line_cells_matches_python_row_boundary_tolerance():
    cells = [
        {
            "text": "",
            "row": 0,
            "col": 0,
            "rect": {
                "schema_version": 1,
                "x0": 70.6,
                "y0": 450.2,
                "x1": 260.3,
                "y1": 464.0,
            },
            "rowspan": 1,
            "colspan": 1,
        },
        {
            "text": "",
            "row": 1,
            "col": 0,
            "rect": {
                "schema_version": 1,
                "x0": 70.6,
                "y0": 464.0,
                "x1": 260.3,
                "y1": 477.8,
            },
            "rowspan": 1,
            "colspan": 1,
        },
    ]
    word = {
        "schema_version": 1,
        "text": "boundary-word",
        "rect": {
            "schema_version": 1,
            "x0": 76.93,
            "y0": 461.54,
            "x1": 252.37,
            "y1": 470.54,
        },
        "order": 0,
        "block": 0,
        "line": 0,
    }

    assigned = assign_text_to_line_cells(cells, [word], chars=[], tolerance=2.3)

    # Python's wired text path uses a fixed 2.0pt text-row tolerance even
    # though the geometric line tolerance is 2.3pt. The word center is just
    # outside the upper row under that contract.
    assert [c["text"] for c in assigned] == ["", "boundary-word"]


def test_wired_extractor_words_called_only_once_page_spy():
    class PageSpy:
        def __init__(self):
            import fitz
            self.call_counts = {"words": 0, "drawings": 0, "rawdict": 0}
            self.rect = fitz.Rect(0.0, 0.0, 600.0, 800.0)

        def get_drawings(self, extended=False):
            import fitz
            self.call_counts["drawings"] += 1
            # 两个独立的 2x2 表格区域
            return [
                # 表格 1
                {"items": [("l", fitz.Point(10.0, 10.0), fitz.Point(110.0, 10.0))], "rect": fitz.Rect(10.0, 10.0, 110.0, 10.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(10.0, 60.0), fitz.Point(110.0, 60.0))], "rect": fitz.Rect(10.0, 60.0, 110.0, 60.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(10.0, 110.0), fitz.Point(110.0, 110.0))], "rect": fitz.Rect(10.0, 110.0, 110.0, 110.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(10.0, 10.0), fitz.Point(10.0, 110.0))], "rect": fitz.Rect(10.0, 10.0, 10.0, 110.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(60.0, 10.0), fitz.Point(60.0, 110.0))], "rect": fitz.Rect(60.0, 10.0, 60.0, 110.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(110.0, 10.0), fitz.Point(110.0, 110.0))], "rect": fitz.Rect(110.0, 10.0, 110.0, 110.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                # 表格 2
                {"items": [("l", fitz.Point(200.0, 200.0), fitz.Point(300.0, 200.0))], "rect": fitz.Rect(200.0, 200.0, 300.0, 200.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(200.0, 250.0), fitz.Point(300.0, 250.0))], "rect": fitz.Rect(200.0, 250.0, 300.0, 250.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(200.0, 300.0), fitz.Point(300.0, 300.0))], "rect": fitz.Rect(200.0, 300.0, 300.0, 300.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(200.0, 200.0), fitz.Point(200.0, 300.0))], "rect": fitz.Rect(200.0, 200.0, 200.0, 300.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(250.0, 200.0), fitz.Point(250.0, 300.0))], "rect": fitz.Rect(250.0, 200.0, 250.0, 300.0), "type": "s", "color": (0.0, 0.0, 0.0)},
                {"items": [("l", fitz.Point(300.0, 200.0), fitz.Point(300.0, 300.0))], "rect": fitz.Rect(300.0, 200.0, 300.0, 300.0), "type": "s", "color": (0.0, 0.0, 0.0)},
            ]

        def get_text(self, kind):
            if kind == "words":
                self.call_counts["words"] += 1
                return [
                    (20.0, 20.0, 40.0, 30.0, "T1A", 0, 0, 0),
                    (70.0, 20.0, 90.0, 30.0, "T1B", 1, 0, 0),
                    (210.0, 210.0, 230.0, 220.0, "T2A", 2, 0, 0),
                    (260.0, 210.0, 280.0, 220.0, "T2B", 3, 0, 0),
                ]
            elif kind == "rawdict":
                self.call_counts["rawdict"] += 1
                return {"blocks": []}
            return []

    page = PageSpy()
    extractor = WiredTableExtractor()
    tables = extractor.extract(page)
    assert len(tables) == 2
    # 验证 words 获取被集中在页面级只执行一次，而不是每个 region 重复调用
    assert page.call_counts["words"] == 1
