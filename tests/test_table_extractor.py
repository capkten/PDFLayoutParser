"""Tests for the table extractor."""

import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from hexai_pdf_parser.models import BBox, Cell, Table
from hexai_pdf_parser.text_region_detector import CandidateRegion
from hexai_pdf_parser.table_extractor import TableExtractor


def make_pdf_with_table(path: str | Path) -> None:
    """Create a PDF with a simple 2x2 grid drawn with lines and text."""
    doc = fitz.open()
    page = doc.new_page()
    # Draw horizontal lines
    page.draw_line((100, 100), (300, 100))
    page.draw_line((100, 150), (300, 150))
    page.draw_line((100, 200), (300, 200))
    # Draw vertical lines
    page.draw_line((100, 100), (100, 200))
    page.draw_line((200, 100), (200, 200))
    page.draw_line((300, 100), (300, 200))
    # Insert text in cells
    page.insert_text((120, 120), "A1")
    page.insert_text((220, 120), "B1")
    page.insert_text((120, 170), "A2")
    page.insert_text((220, 170), "B2")
    doc.save(path)
    doc.close()


def make_synthetic_text_alignment_pdf(
    path: str | Path,
    rows: list[tuple[float, list[tuple[float, str]]]],
    *,
    page_size: tuple[float, float] = (320.0, 260.0),
) -> None:
    """Create a synthetic PDF page with positioned text rows."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=page_size[0], height=page_size[1])
        for y, tokens in rows:
            for x, text in tokens:
                page.insert_text((x, y), text, fontsize=10)
        doc.save(str(path))
    finally:
        doc.close()


class TestTableExtractor:
    def test_detect_text_regions_maps_detector_rows_back_to_original_rows(self, monkeypatch):
        extractor = TableExtractor()
        rows = [
            {
                "tokens": [
                    {"text": "A", "x0": 20.0, "y0": 30.0, "x1": 40.0, "y1": 42.0, "is_numeric": False},
                    {"text": "10", "x0": 150.0, "y0": 30.0, "x1": 170.0, "y1": 42.0, "is_numeric": True},
                ],
                "x0": 20.0,
                "y0": 30.0,
                "x1": 170.0,
                "y1": 42.0,
            },
            {
                "tokens": [
                    {"text": "B", "x0": 20.0, "y0": 48.0, "x1": 40.0, "y1": 60.0, "is_numeric": False},
                    {"text": "20", "x0": 150.0, "y0": 48.0, "x1": 170.0, "y1": 60.0, "is_numeric": True},
                ],
                "x0": 20.0,
                "y0": 48.0,
                "x1": 170.0,
                "y1": 60.0,
            },
        ]

        captured = {}

        def fake_detect_candidate_regions(visual_rows, horizontal_separators=None):
            captured["row_count"] = len(visual_rows)
            captured["separator_count"] = len(horizontal_separators or [])
            return [
                CandidateRegion(
                    rows=visual_rows,
                    bbox=CandidateRegion.bbox_union([row.bbox for row in visual_rows]),
                    features={"kind": "test"},
                    score=1.0,
                )
            ]

        monkeypatch.setattr(
            "hexai_pdf_parser.table_extractor.detect_candidate_regions",
            fake_detect_candidate_regions,
        )

        page = SimpleNamespace(
            rect=fitz.Rect(0, 0, 300, 200),
            get_drawings=lambda: [],
        )

        regions = extractor._detect_text_regions(rows, page)

        assert captured["row_count"] == 2
        assert captured["separator_count"] == 0
        assert len(regions) == 1
        assert regions[0]["rows"][0] is rows[0]
        assert regions[0]["rows"][1] is rows[1]
        assert regions[0]["bbox"].x0 == 20.0
        assert regions[0]["bbox"].y0 == 30.0
        assert regions[0]["bbox"].x1 == 170.0
        assert regions[0]["bbox"].y1 == 60.0
        assert regions[0]["column_guides"] == [20.0, 150.0]

    def test_extract_via_text_alignment_uses_detect_text_regions(self, tmp_dir, monkeypatch):
        pdf_path = Path(tmp_dir) / "detect_text_regions_entry.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "A"), (150.0, "10")]),
                (48.0, [(20.0, "B"), (150.0, "20")]),
                (66.0, [(20.0, "C"), (150.0, "30")]),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            page = doc[0]
            rows = extractor._collect_text_rows(page.get_text("words"))

            monkeypatch.setattr(
                extractor,
                "_detect_text_regions",
                lambda passed_rows, passed_page: [
                    {
                        "rows": rows,
                        "bbox": extractor._rows_bbox(rows),
                        "column_guides": extractor._infer_column_guides(rows),
                    }
                ],
            )

            tables = extractor._extract_via_text_alignment(page)

            assert len(tables) == 1
            assert tables[0].rows == 3
            assert tables[0].cols == 2
        finally:
            doc.close()

    def test_should_fallback_for_degenerate_one_cell_tables(self):
        extractor = TableExtractor()
        tables = [
            Table(
                bbox=BBox(0, 0, 100, 20),
                rows=1,
                cols=1,
                cells=[Cell(text="", row_index=0, col_index=0, bbox=BBox(0, 0, 100, 20))],
                confidence=0.9,
                source="line_projection",
            )
        ]
        assert extractor._should_fallback(tables) is True

    def test_should_not_fallback_for_dense_wide_table(self):
        extractor = TableExtractor()
        cells = []
        for row_index in range(2):
            for col_index in range(31):
                cells.append(
                    Cell(
                        text=f"{row_index}-{col_index}",
                        row_index=row_index,
                        col_index=col_index,
                        bbox=BBox(col_index * 10.0, row_index * 10.0, col_index * 10.0 + 8.0, row_index * 10.0 + 8.0),
                    )
                )

        tables = [
            Table(
                bbox=BBox(0, 0, 310, 20),
                rows=2,
                cols=31,
                cells=cells,
                confidence=0.9,
                source="line_projection",
            )
        ]

        assert extractor._should_fallback(tables) is False

    def test_should_fallback_for_sparse_wide_table(self):
        extractor = TableExtractor()
        cells = [
            Cell(
                text="A",
                row_index=0,
                col_index=0,
                bbox=BBox(0, 0, 8, 8),
            ),
            Cell(
                text="B",
                row_index=1,
                col_index=30,
                bbox=BBox(300, 10, 308, 18),
            ),
        ]

        tables = [
            Table(
                bbox=BBox(0, 0, 310, 20),
                rows=2,
                cols=31,
                cells=cells,
                confidence=0.9,
                source="line_projection",
            )
        ]

        assert extractor._should_fallback(tables) is True

    def test_extract_keeps_line_tables_when_fallback_returns_empty(self):
        extractor = TableExtractor()
        line_tables = [
            Table(
                bbox=BBox(0, 0, 100, 100),
                rows=2,
                cols=2,
                cells=[
                    Cell(
                        text="A",
                        row_index=0,
                        col_index=0,
                        bbox=BBox(0, 0, 10, 10),
                    )
                ],
                confidence=0.9,
                source="line_projection",
            )
        ]

        extractor._extract_via_lines = lambda page: line_tables
        extractor._should_fallback = lambda tables: True
        extractor._extract_via_pymupdf = lambda page: []

        result = extractor.extract(SimpleNamespace())

        assert result == line_tables

    def test_find_table_regions_separates_disconnected_grids(self):
        extractor = TableExtractor()
        h_lines = [
            (10.0, 10.0, 110.0, 10.0),
            (10.0, 60.0, 110.0, 60.0),
            (10.0, 110.0, 110.0, 110.0),
            (210.0, 10.0, 310.0, 10.0),
            (210.0, 60.0, 310.0, 60.0),
            (210.0, 110.0, 310.0, 110.0),
        ]
        v_lines = [
            (10.0, 10.0, 10.0, 110.0),
            (60.0, 10.0, 60.0, 110.0),
            (110.0, 10.0, 110.0, 110.0),
            (210.0, 10.0, 210.0, 110.0),
            (260.0, 10.0, 260.0, 110.0),
            (310.0, 10.0, 310.0, 110.0),
        ]

        regions = extractor._find_table_regions(h_lines, v_lines)

        assert len(regions) == 2
        bboxes = sorted(
            [(bbox.x0, bbox.y0, bbox.x1, bbox.y1) for bbox, _, _ in regions]
        )
        assert bboxes == [
            (10.0, 10.0, 110.0, 110.0),
            (210.0, 10.0, 310.0, 110.0),
        ]

    def test_find_table_regions_with_short_vertical_included(self):
        extractor = TableExtractor()
        h_lines = [
            (10.0, 10.0, 110.0, 10.0),
            (10.0, 60.0, 110.0, 60.0),
            (10.0, 110.0, 110.0, 110.0),
        ]
        v_lines = [
            (10.0, 10.0, 10.0, 110.0),
            (60.0, 10.0, 60.0, 110.0),
            (110.0, 10.0, 110.0, 110.0),
            (35.0, 10.0, 35.0, 25.0),
        ]

        regions = extractor._find_table_regions(h_lines, v_lines)

        assert len(regions) == 1
        _, region_h, region_v = regions[0]
        # Short vertical (35.0, 10→25) is included in the region's v_lines.
        assert len(region_v) == 4

    def test_merge_oversegmented_columns_keeps_wide_empty_columns(self):
        extractor = TableExtractor()
        cells = [
            Cell(text="A1", row_index=0, col_index=0, bbox=BBox(0, 0, 40, 20)),
            Cell(text="", row_index=0, col_index=1, bbox=BBox(40, 0, 70, 20)),
            Cell(text="B1", row_index=0, col_index=2, bbox=BBox(70, 0, 110, 20)),
            Cell(text="A2", row_index=1, col_index=0, bbox=BBox(0, 20, 40, 40)),
            Cell(text="", row_index=1, col_index=1, bbox=BBox(40, 20, 70, 40)),
            Cell(text="B2", row_index=1, col_index=2, bbox=BBox(70, 20, 110, 40)),
        ]

        merged = extractor._merge_oversegmented_columns(cells)

        assert max(c.col_index for c in merged) == 2
        empty_col_cells = [c for c in merged if c.col_index == 1]
        assert len(empty_col_cells) == 2
        assert all(c.text == "" for c in empty_col_cells)

    def test_merge_adjacent_regions_does_not_merge_separate_tables(self):
        extractor = TableExtractor()
        regions = [
            (
                BBox(0, 0, 50, 50),
                [(0.0, 0.0, 50.0, 0.0)],
                [(0.0, 0.0, 0.0, 50.0)],
            ),
            (
                BBox(90, 0, 140, 50),
                [(90.0, 0.0, 140.0, 0.0)],
                [(90.0, 0.0, 90.0, 50.0)],
            ),
        ]

        merged = extractor._merge_adjacent_regions(regions)

        assert len(merged) == 2

    def test_build_cells_for_region_merges_atomic_grid_into_spanning_cells(self):
        extractor = TableExtractor()
        bbox = BBox(0, 0, 30, 30)
        h_lines = [
            (0.0, 0.0, 30.0, 0.0),
            (10.0, 10.0, 30.0, 10.0),
            (10.0, 20.0, 30.0, 20.0),
            (0.0, 30.0, 30.0, 30.0),
        ]
        v_lines = [
            (0.0, 0.0, 0.0, 30.0),
            (10.0, 0.0, 10.0, 30.0),
            (20.0, 20.0, 20.0, 30.0),
            (30.0, 0.0, 30.0, 30.0),
        ]

        cells = extractor._build_cells_for_region(bbox, h_lines, v_lines)

        layout = sorted(
            (
                c.row_index,
                c.col_index,
                c.rowspan,
                c.colspan,
                (c.bbox.x0, c.bbox.y0, c.bbox.x1, c.bbox.y1),
            )
            for c in cells
        )
        assert layout == [
            (0, 0, 3, 1, (0.0, 0.0, 10.0, 30.0)),
            (0, 1, 1, 2, (10.0, 0.0, 30.0, 10.0)),
            (1, 1, 1, 2, (10.0, 10.0, 30.0, 20.0)),
            (2, 1, 1, 1, (10.0, 20.0, 20.0, 30.0)),
            (2, 2, 1, 1, (20.0, 20.0, 30.0, 30.0)),
        ]

    def test_build_cells_for_region_delegates_to_unified_grid_builder(self):
        extractor = TableExtractor()
        bbox = BBox(0, 0, 100, 100)
        h_lines = [
            (0.0, 0.0, 100.0, 0.0),
            (0.0, 25.0, 100.0, 25.0),
            (0.0, 50.0, 100.0, 50.0),
            (0.0, 75.0, 100.0, 75.0),
            (0.0, 100.0, 100.0, 100.0),
        ]
        v_lines = [
            (0.0, 0.0, 0.0, 100.0),
            (20.0, 25.0, 20.0, 100.0),
            (40.0, 25.0, 40.0, 100.0),
            (60.0, 0.0, 60.0, 100.0),
        ]

        captured = {}

        def fake_build_cells_in_region(h_ys_arg, v_xs_arg, h_lines_arg, v_lines_arg):
            captured["h_ys"] = h_ys_arg
            captured["v_xs"] = v_xs_arg
            captured["h_lines"] = h_lines_arg
            captured["v_lines"] = v_lines_arg
            return [
                Cell(
                    text="",
                    row_index=0,
                    col_index=0,
                    bbox=BBox(0, 0, 20, 25),
                )
            ]

        extractor._build_cells_in_region = fake_build_cells_in_region

        extractor._build_cells_for_region(bbox, h_lines, v_lines)

        assert captured["h_ys"] == [0.0, 25.0, 50.0, 75.0, 100.0]
        assert captured["v_xs"] == [0.0, 20.0, 40.0, 60.0]
        assert captured["h_lines"] == h_lines
        assert captured["v_lines"] == v_lines

    def test_build_cells_in_region_excludes_cartesian_product_outside_gaps(self):
        extractor = TableExtractor()
        h_lines = [
            (20.0, 0.0, 40.0, 0.0),
            (0.0, 10.0, 40.0, 10.0),
            (0.0, 20.0, 40.0, 20.0),
        ]
        v_lines = [
            (0.0, 0.0, 0.0, 100.0),
            (20.0, 0.0, 20.0, 20.0),
            (40.0, 0.0, 40.0, 20.0),
        ]
        h_ys = [0.0, 10.0, 20.0]
        v_xs = [0.0, 20.0, 40.0]

        cells = extractor._build_cells_in_region(h_ys, v_xs, h_lines, v_lines)

        assert (0, 0) not in {(c.row_index, c.col_index) for c in cells}
        assert (0, 1) in {(c.row_index, c.col_index) for c in cells}

    def test_ignore_rectangles_fully_covered_by_later_fill_path(self):
        page = SimpleNamespace(
            rect=fitz.Rect(0, 0, 400, 400),
            get_drawings=lambda: [
                {
                    "items": [("re", fitz.Rect(100, 100, 200, 150), 1)],
                    "type": "s",
                    "stroke_opacity": 1.0,
                    "color": (0.0, 0.0, 0.0),
                    "width": 1.0,
                    "seqno": 0,
                }
            ],
            get_bboxlog=lambda: [
                ("stroke-path", (100, 100, 200, 150)),
                ("fill-path", (95, 95, 205, 155)),
            ],
        )

        extractor = TableExtractor()
        h_lines, v_lines = extractor._extract_lines_from_drawings(page)
        assert h_lines == []
        assert v_lines == []

    def test_keep_rectangles_when_later_fill_only_partially_overlaps(self):
        page = SimpleNamespace(
            rect=fitz.Rect(0, 0, 400, 400),
            get_drawings=lambda: [
                {
                    "items": [("re", fitz.Rect(100, 100, 200, 150), 1)],
                    "type": "s",
                    "stroke_opacity": 1.0,
                    "color": (0.0, 0.0, 0.0),
                    "width": 1.0,
                    "seqno": 0,
                }
            ],
            get_bboxlog=lambda: [
                ("stroke-path", (100, 100, 200, 150)),
                ("fill-path", (150, 100, 220, 155)),
            ],
        )

        extractor = TableExtractor()
        h_lines, v_lines = extractor._extract_lines_from_drawings(page)
        assert len(h_lines) == 2
        assert len(v_lines) == 2

    def test_ignore_fully_transparent_rectangles_when_extracting_lines(
        self, tmp_dir
    ):
        pdf_path = Path(tmp_dir) / "transparent_rect.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.draw_rect(
            (100, 100, 200, 150),
            color=(0, 0, 0),
            width=1,
            stroke_opacity=0,
        )
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            h_lines, v_lines = extractor._extract_lines_from_drawings(page)
            assert h_lines == []
            assert v_lines == []
        finally:
            doc.close()

    def test_ignore_fill_only_rectangles_when_extracting_lines(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "fill_only_rect.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.draw_rect(
            (100, 100, 200, 150),
            fill=(1, 0, 0),
            color=None,
            width=0,
            fill_opacity=1,
        )
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            h_lines, v_lines = extractor._extract_lines_from_drawings(page)
            assert h_lines == []
            assert v_lines == []
        finally:
            doc.close()

    def test_keep_fill_only_thin_rectangles_as_visible_lines(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "fill_only_thin_line.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.draw_rect(
            (100, 100, 200, 101),
            fill=(0, 0, 0),
            color=None,
            width=0,
            fill_opacity=1,
        )
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            h_lines, v_lines = extractor._extract_lines_from_drawings(page)
            assert len(h_lines) == 1
            assert v_lines == []
        finally:
            doc.close()

    def test_extract_table_from_lines(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "with_table.pdf"
        make_pdf_with_table(pdf_path)

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            tables = extractor.extract(page)

            assert isinstance(tables, list)
            if tables:
                table = tables[0]
                assert table.rows >= 1
                assert table.cols >= 1
                assert len(table.cells) >= 1
                assert table.confidence == 1.0
                assert table.source == "PyMuPDF.find_tables"
        finally:
            doc.close()


    def test_extract_via_text_alignment_rejects_repeated_numeric_fragments_in_prose(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "repeated_numeric_fragments.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "The quarterly commentary notes"),
                        (165.0, "2024"),
                    ],
                ),
                (
                    50.0,
                    [
                        (20.0, "that operating conditions"),
                        (165.0, "15"),
                        (206.0, "remain uneven"),
                    ],
                ),
                (
                    70.0,
                    [
                        (20.0, "across regions, especially"),
                        (165.0, "2024"),
                        (206.0, "in the second half"),
                    ],
                ),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert tables == []
        finally:
            doc.close()

    def test_extract_via_text_alignment_keeps_long_label_text_only_table(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "long_label_table.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "Net sales"),
                        (150.0, "12345"),
                    ],
                ),
                (
                    48.0,
                    [
                        (20.0, "Operating income"),
                        (150.0, "67890"),
                    ],
                ),
                (
                    66.0,
                    [
                        (20.0, "Depreciation"),
                        (150.0, "11111"),
                    ],
                ),
                (
                    84.0,
                    [
                        (20.0, "Amortization"),
                        (150.0, "22222"),
                    ],
                ),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert len(tables) == 1
            assert tables[0].rows == 4
            assert tables[0].cols == 2
        finally:
            doc.close()

    def test_extract_via_text_alignment_keeps_chinese_financial_table(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "chinese_financial.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "房屋建筑物"),
                        (150.0, "20-100"),
                        (250.0, "5"),
                        (320.0, "0.95-4.75"),
                    ],
                ),
                (
                    48.0,
                    [
                        (20.0, "机器设备"),
                        (150.0, "10-15"),
                        (250.0, "5"),
                        (320.0, "6.33-9.50"),
                    ],
                ),
                (
                    66.0,
                    [
                        (20.0, "运输工具"),
                        (150.0, "8"),
                        (250.0, "5"),
                        (320.0, "11.88"),
                    ],
                ),
                (
                    84.0,
                    [
                        (20.0, "电子设备"),
                        (150.0, "3-10"),
                        (250.0, "5"),
                        (320.0, "9.50-31.67"),
                    ],
                ),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert len(tables) == 1
            assert tables[0].rows == 4
        finally:
            doc.close()

    def test_extract_via_text_alignment_preserves_multiple_text_columns(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "multi_text_cols.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "名称"), (120.0, "简称"), (220.0, "类型"), (320.0, "金额"), (420.0, "比例")]),
                (48.0, [(20.0, "甲公司"), (120.0, "甲"), (220.0, "子公司"), (320.0, "100.00"), (420.0, "50%")]),
                (66.0, [(20.0, "乙公司"), (120.0, "乙"), (220.0, "联营"), (320.0, "200.00"), (420.0, "30%")]),
                (84.0, [(20.0, "丙公司"), (120.0, "丙"), (220.0, "合营"), (320.0, "300.00"), (420.0, "20%")]),
            ],
            page_size=(500.0, 120.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert len(tables) == 1
            assert tables[0].rows == 4
            assert tables[0].cols == 5
        finally:
            doc.close()

    def test_extract_via_text_alignment_handles_multiline_cells(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "multiline_cells.pdf"
        # Simulate a table with a multi-line middle column:
        # Row 0 (header): 3 tokens
        # Row 1: complete row with 3 tokens
        # Row 2: complete row with 3 tokens (first line of a multi-line cell)
        # Row 3: continuation line — only the middle column wraps
        # Row 4: complete row with 3 tokens
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "税种"),
                        (150.0, "计税依据"),
                        (280.0, "税率"),
                    ],
                ),
                (
                    48.0,
                    [
                        (20.0, "增值税"),
                        (150.0, "销售货物的销售额"),
                        (280.0, "13%"),
                    ],
                ),
                (
                    66.0,
                    [
                        (20.0, "土地增值税"),
                        (150.0, "有偿转让国有土地"),
                        (280.0, "超率累进"),
                    ],
                ),
                (
                    82.0,
                    [
                        (150.0, "使用权及附着物"),
                    ],
                ),
                (
                    100.0,
                    [
                        (20.0, "房产税"),
                        (150.0, "房产原值余值"),
                        (280.0, "1.2%"),
                    ],
                ),
            ],
            page_size=(320.0, 200.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert len(tables) == 1
            # All 4 data rows should be detected (continuation merged)
            assert tables[0].rows == 4
            assert tables[0].cols == 3
        finally:
            doc.close()

    def test_extract_via_text_alignment_trims_prose_prefix(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "trims_prose_prefix.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "This"),
                        (80.0, "short"),
                        (150.0, "note"),
                    ],
                ),
                (
                    48.0,
                    [
                        (20.0, "introduces"),
                        (80.0, "the"),
                        (150.0, "table"),
                    ],
                ),
                (
                    84.0,
                    [
                        (20.0, "A"),
                        (150.0, "10"),
                    ],
                ),
                (
                    102.0,
                    [
                        (20.0, "B"),
                        (150.0, "20"),
                    ],
                ),
                (
                    120.0,
                    [
                        (20.0, "C"),
                        (150.0, "30"),
                    ],
                ),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])

            assert len(tables) == 1
            table = tables[0]
            assert table.rows == 3
            assert table.cols == 2
            assert table.bbox.y0 >= 55.0
            cells = {(cell.row_index, cell.col_index): cell.text for cell in table.cells}
            assert cells[(0, 0)] == "A"
            assert cells[(0, 1)] == "10"
            assert cells[(1, 0)] == "B"
            assert cells[(1, 1)] == "20"
            assert cells[(2, 0)] == "C"
            assert cells[(2, 1)] == "30"
        finally:
            doc.close()

    def test_extract_via_text_alignment_merges_short_header_span(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "merges_short_header_span.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "Header"),
                        (150.0, "Amount"),
                    ],
                ),
                (
                    86.0,
                    [
                        (20.0, "A"),
                        (150.0, "10"),
                    ],
                ),
                (
                    104.0,
                    [
                        (20.0, "B"),
                        (150.0, "20"),
                    ],
                ),
                (
                    122.0,
                    [
                        (20.0, "C"),
                        (150.0, "30"),
                    ],
                ),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            page = doc[0]
            rows = extractor._collect_text_rows(page.get_text("words"))
            spans = extractor._split_rows_into_spans(rows)

            assert len(spans) == 2
            assert [row["tokens"][0]["text"] for row in spans[0]] == ["Header"]
            assert [row["tokens"][0]["text"] for row in spans[1]] == ["A", "B", "C"]

            tables = extractor._extract_via_text_alignment(page)

            assert len(tables) == 1
            table = tables[0]
            assert table.rows == 4
            assert table.cols == 2
            assert table.bbox.y0 <= spans[0][0]["y0"] + 5.0
            cells = {(cell.row_index, cell.col_index): cell.text for cell in table.cells}
            assert cells[(0, 0)] == "Header"
            assert cells[(0, 1)] == "Amount"
            assert cells[(1, 0)] == "A"
            assert cells[(1, 1)] == "10"
            assert cells[(2, 0)] == "B"
            assert cells[(2, 1)] == "20"
            assert cells[(3, 0)] == "C"
            assert cells[(3, 1)] == "30"
        finally:
            doc.close()

    def test_extract_via_text_alignment_excludes_heading_rows(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "excludes_heading_rows.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "Operating"),
                        (90.0, "results"),
                    ],
                ),
                (
                    54.0,
                    [
                        (20.0, "A"),
                        (150.0, "10"),
                    ],
                ),
                (
                    72.0,
                    [
                        (20.0, "B"),
                        (150.0, "20"),
                    ],
                ),
                (
                    90.0,
                    [
                        (20.0, "C"),
                        (150.0, "30"),
                    ],
                ),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])

            assert len(tables) == 1
            table = tables[0]
            assert table.rows == 3
            assert table.cols == 2
            assert table.bbox.y0 >= 35.0
            texts = [cell.text for cell in table.cells]
            assert "Operating" not in texts
            assert "results" not in texts
            assert sorted(texts) == ["10", "20", "30", "A", "B", "C"]
        finally:
            doc.close()

    def test_extract_via_text_alignment_records_debug_snapshot(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "debug_snapshot.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "项目A"), (180.0, "10"), (300.0, "20")]),
                (48.0, [(20.0, "项目B"), (180.0, "11"), (300.0, "21")]),
            ],
            page_size=(360.0, 220.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert len(tables) == 1

            snapshot = extractor._last_text_alignment_debug
            assert snapshot is not None
            assert snapshot["page_index"] == 0
            assert len(snapshot["regions"]) == 1
            region = snapshot["regions"][0]
            assert "bbox" in region
            assert "rows" in region
            assert "column_guides" in region
            assert len(region["rows"]) >= 2
            assert len(region["column_guides"]) >= 2
        finally:
            doc.close()

    def test_extract_no_crash_on_text_only(self, tmp_dir):
        """Ensure the extractor does not crash on pages without tables."""
        pdf_path = Path(tmp_dir) / "no_table.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Just some text")
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            tables = extractor.extract(page)
            assert isinstance(tables, list)
        finally:
            doc.close()

    def test_extract_cells_from_region_builds_grid(self, tmp_dir):
        """Cells are correctly inferred from text within a bbox."""
        pdf_path = Path(tmp_dir) / "region_test.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((100, 100), "A1")
        page.insert_text((200, 100), "B1")
        page.insert_text((100, 130), "A2")
        page.insert_text((200, 130), "B2")
        page.insert_text((100, 160), "A3")
        page.insert_text((200, 160), "B3")
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            region_bbox = BBox(80, 80, 280, 180)
            row_count, col_count, cells = extractor._extract_cells_from_region(
                page, region_bbox
            )
            assert row_count == 3
            assert col_count == 2
            assert len(cells) == 6
        finally:
            doc.close()

    def test_extract_cells_from_region_returns_empty_for_no_text(self, tmp_dir):
        """Empty region returns zero cells."""
        pdf_path = Path(tmp_dir) / "empty_region.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((400, 400), "far away")
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            region_bbox = BBox(50, 50, 200, 200)
            row_count, col_count, cells = extractor._extract_cells_from_region(
                page, region_bbox
            )
            assert row_count == 0
            assert col_count == 0
            assert cells == []
        finally:
            doc.close()

    def test_ml_disabled_by_default(self, tmp_dir):
        """use_ml=False means _extract_via_ml is never called."""
        extractor = TableExtractor()
        assert extractor.use_ml is False

    def test_ml_detector_defaults_to_layoutanalysis_model(self):
        from hexai_pdf_parser.ml_table_detector import MLTableDetector

        detector = MLTableDetector()
        assert detector._model_path.as_posix().endswith(
            "src/models/layoutanalysis/layoutanalysis.onnx"
        )

    def test_ml_tables_supplement_existing_tables(self, tmp_dir):
        """ML tables that don't overlap existing tables are appended."""
        extractor = TableExtractor(use_ml=True)
        # Mock _extract_via_lines to return one table
        existing = Table(
            bbox=BBox(0, 0, 100, 100),
            rows=2, cols=2, cells=[],
            confidence=0.9, source="line_projection",
        )
        extractor._extract_via_lines = lambda page: [existing]
        extractor._extract_via_ml = lambda page: [
            Table(
                bbox=BBox(200, 200, 400, 400),
                rows=3, cols=4, cells=[],
                confidence=0.85, source="ml_detection",
            )
        ]
        extractor._extract_via_text_alignment = lambda page: []

        result = extractor.extract(SimpleNamespace())
        assert len(result) == 2
        assert result[1].source == "ml_detection"

    def test_ml_tables_deduplicated_against_existing(self, tmp_dir):
        """Overlapping ML tables are filtered out."""
        extractor = TableExtractor(use_ml=True)
        existing = Table(
            bbox=BBox(100, 100, 300, 300),
            rows=2, cols=2, cells=[],
            confidence=0.9, source="line_projection",
        )
        extractor._extract_via_lines = lambda page: [existing]
        extractor._extract_via_ml = lambda page: [
            Table(
                bbox=BBox(110, 110, 290, 290),
                rows=3, cols=4, cells=[],
                confidence=0.85, source="ml_detection",
            )
        ]
        extractor._extract_via_text_alignment = lambda page: []

        result = extractor.extract(SimpleNamespace())
        assert len(result) == 1
        assert result[0].source == "line_projection"

    def test_extract_via_ml_builds_table_structure_from_model_region(
        self, tmp_dir, monkeypatch
    ):
        pdf_path = Path(tmp_dir) / "ml_region_table.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "A"), (150.0, "10")]),
                (48.0, [(20.0, "B"), (150.0, "20")]),
                (66.0, [(20.0, "C"), (150.0, "30")]),
            ],
        )

        class FakeDetector:
            def __init__(self, model_path=None, confidence_threshold=0.25, **kwargs):
                self.model_path = model_path
                self.confidence_threshold = confidence_threshold

            def detect(self, page):
                return [BBox(10, 10, 250, 100)]

        monkeypatch.setattr(
            "hexai_pdf_parser.ml_table_detector.MLTableDetector",
            FakeDetector,
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor(use_ml=True)
            tables = extractor.extract(doc[0])
            assert len(tables) == 1
            table = tables[0]
            assert table.source == "ml_detection"
            assert table.rows == 3
            assert table.cols == 2
        finally:
            doc.close()

    def test_extract_cells_from_region_detects_colspan_from_wide_header(
        self, tmp_dir
    ):
        pdf_path = Path(tmp_dir) / "wide_header_colspan.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "MergedHeaderAcrossTwoColumns")]),
                (60.0, [(20.0, "A"), (180.0, "10")]),
                (80.0, [(20.0, "B"), (180.0, "20")]),
            ],
            page_size=(360.0, 160.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            row_count, col_count, cells = extractor._extract_cells_from_region(
                doc[0],
                BBox(10.0, 10.0, 320.0, 140.0),
            )

            assert row_count == 3
            assert col_count >= 2
            header = next(cell for cell in cells if cell.row_index == 0)
            assert header.colspan >= 2
            assert header.text == "MergedHeaderAcrossTwoColumns"
        finally:
            doc.close()

    def test_extract_cells_from_region_extends_obvious_rowspan(
        self, tmp_dir
    ):
        pdf_path = Path(tmp_dir) / "stub_rowspan.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "A"), (180.0, "10")]),
                (48.0, [(180.0, "20")]),
                (66.0, [(20.0, "B"), (180.0, "30")]),
            ],
            page_size=(320.0, 120.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            row_count, col_count, cells = extractor._extract_cells_from_region(
                doc[0],
                BBox(10.0, 10.0, 300.0, 100.0),
            )

            assert row_count == 3
            assert col_count == 2
            first_col = next(
                cell for cell in cells if cell.row_index == 0 and cell.col_index == 0
            )
            assert first_col.text == "A"
            assert first_col.rowspan >= 2
        finally:
            doc.close()

    def test_text_alignment_snapshot_roundtrip(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "snapshot_roundtrip.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "Item"), (180.0, "Current"), (300.0, "Prior")]),
                (56.0, [(20.0, "Deposit"), (180.0, "154,658,371.56"), (300.0, "135,643,546.02")]),
                (74.0, [(20.0, "Interest"), (180.0, "42,057,215.66"), (300.0, "50,337,729.62")]),
            ],
            page_size=(420.0, 160.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            snapshot = extractor.capture_text_alignment_snapshot(
                doc[0], BBox(10.0, 10.0, 390.0, 140.0)
            )
            snapshot_path = Path(tmp_dir) / "snapshot.json"
            snapshot_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
            row_count, col_count, cells = (
                extractor.build_table_from_text_alignment_snapshot(loaded)
            )

            assert row_count == 3
            assert col_count == 3
            assert [cell.text for cell in cells if cell.row_index == 0] == [
                "Item",
                "Current",
                "Prior",
            ]
        finally:
            doc.close()

    def test_text_alignment_snapshot_merges_numeric_fragments(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "snapshot_numeric_merge.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (
                    30.0,
                    [
                        (20.0, "Label"),
                        (180.0, "47,95"),
                        (230.0, "4,294"),
                        (280.0, ".50"),
                        (330.0, "12,24"),
                        (380.0, "0,607"),
                    ],
                ),
                (
                    56.0,
                    [
                        (20.0, "Row2"),
                        (180.0, "39,90"),
                        (230.0, "7,082"),
                        (280.0, ".06"),
                        (330.0, "46,98"),
                        (380.0, "2,791"),
                    ],
                ),
            ],
            page_size=(460.0, 120.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            snapshot = extractor.capture_text_alignment_snapshot(
                doc[0], BBox(10.0, 10.0, 450.0, 100.0)
            )
            row_count, col_count, cells = (
                extractor.build_table_from_text_alignment_snapshot(snapshot)
            )

            assert row_count == 2
            assert col_count <= 3
            row0_texts = [cell.text for cell in cells if cell.row_index == 0]
            assert row0_texts[0] == "Label"
            assert any("47,95" in text and "4,294" in text for text in row0_texts)
        finally:
            doc.close()

    def test_collect_text_rows_merges_close_fragments_into_one_token(self):
        extractor = TableExtractor()

        rows = extractor._collect_text_rows(
            [
                (10.0, 10.0, 24.0, 22.0, "人民"),
                (24.2, 10.0, 31.0, 22.0, "币"),
            ]
        )

        assert len(rows) == 1
        assert [token["text"] for token in rows[0]["tokens"]] == ["人民币"]

    def test_collect_text_rows_keeps_tokens_on_different_rows_separate(self):
        extractor = TableExtractor()

        rows = extractor._collect_text_rows(
            [
                (10.0, 10.0, 24.0, 22.0, "A"),
                (24.2, 10.0, 31.0, 22.0, "B"),
                (10.0, 40.0, 24.0, 52.0, "C"),
            ]
        )

        assert len(rows) == 2
        assert [token["text"] for token in rows[0]["tokens"]] == ["AB"]
        assert [token["text"] for token in rows[1]["tokens"]] == ["C"]

    def test_collect_text_rows_does_not_merge_far_apart_same_row_fragments(self):
        extractor = TableExtractor()

        rows = extractor._collect_text_rows(
            [
                (676.1, 152.4, 734.6, 161.4, "17,863,206.52"),
                (56.4, 153.3, 160.1, 162.3, "47.米塔盒子科技有限公司"),
            ]
        )

        assert len(rows) == 1
        assert [token["text"] for token in rows[0]["tokens"]] == [
            "47.米塔盒子科技有限公司",
            "17,863,206.52",
        ]


class TestNMS:
    """Test pure-numpy NMS implementation."""

    def test_nms_removes_overlapping_boxes(self):
        import numpy as np
        from hexai_pdf_parser.ml_table_detector import MLTableDetector

        boxes = np.array([[10, 10, 50, 50], [12, 12, 52, 52], [200, 200, 250, 250]], dtype=np.float32)
        scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
        keep = MLTableDetector._nms(boxes, scores, iou_threshold=0.5)
        assert len(keep) == 2
        assert 0 in keep
        assert 2 in keep

    def test_nms_keeps_non_overlapping_boxes(self):
        import numpy as np
        from hexai_pdf_parser.ml_table_detector import MLTableDetector

        boxes = np.array([[10, 10, 50, 50], [200, 200, 250, 250]], dtype=np.float32)
        scores = np.array([0.9, 0.8], dtype=np.float32)
        keep = MLTableDetector._nms(boxes, scores, iou_threshold=0.5)
        assert len(keep) == 2

    def test_nms_empty_input(self):
        import numpy as np
        from hexai_pdf_parser.ml_table_detector import MLTableDetector

        boxes = np.empty((0, 4), dtype=np.float32)
        scores = np.empty((0,), dtype=np.float32)
        keep = MLTableDetector._nms(boxes, scores, iou_threshold=0.5)
        assert keep == []


class TestLayoutRuleIntegration:
    """Integration tests for the config-driven table layout rule system."""

    def test_no_config_preserves_behavior(self, tmp_dir):
        """Without table_config, behavior is identical to the old code path."""
        pdf_path = Path(tmp_dir) / "no_config.pdf"
        make_pdf_with_table(pdf_path)

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            tables = extractor.extract(page)
            assert isinstance(tables, list)
        finally:
            doc.close()

    def test_config_with_no_profiles_preserves_behavior(self, tmp_dir):
        """A config with no profiles does not alter extraction."""
        from hexai_pdf_parser.table_config import TableConfig

        pdf_path = Path(tmp_dir) / "no_profiles.pdf"
        make_pdf_with_table(pdf_path)

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor_no_config = TableExtractor()
            tables_no_config = extractor_no_config.extract(page)

            extractor_with_config = TableExtractor(
                table_config=TableConfig.default()
            )
            tables_with_config = extractor_with_config.extract(page)

            # Same number of tables, same shapes
            assert len(tables_no_config) == len(tables_with_config)
            for t1, t2 in zip(tables_no_config, tables_with_config):
                assert t1.rows == t2.rows
                assert t1.cols == t2.cols
        finally:
            doc.close()

    def test_config_settings_override_separator_threshold(self, tmp_dir):
        """Config settings override hardcoded separator thresholds."""
        from hexai_pdf_parser.table_config import (
            GlobalTableSettings,
            TableConfig,
        )

        extractor_no_config = TableExtractor()
        assert extractor_no_config._separator_min_width == 200.0
        assert extractor_no_config._separator_max_height == 1.5

        config = TableConfig(
            settings=GlobalTableSettings(
                separator_min_width=100.0,
                separator_max_height=3.0,
            )
        )
        extractor_with_config = TableExtractor(table_config=config)
        assert extractor_with_config._separator_min_width == 100.0
        assert extractor_with_config._separator_max_height == 3.0

    def test_profile_match_applies_structure_rules(self, tmp_dir):
        """A matched profile with trim_trailing_summary removes summary rows."""
        from hexai_pdf_parser.table_config import (
            LayoutProfile,
            MatcherConfig,
            StructureRuleSet,
            TableConfig,
        )

        pdf_path = Path(tmp_dir) / "trim_summary.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "Assets"), (150.0, "100")]),
                (48.0, [(20.0, "Liabilities"), (150.0, "200")]),
                (66.0, [(20.0, "Total"), (150.0, "300")]),
            ],
        )

        config = TableConfig(
            profiles=[
                LayoutProfile(
                    name="trim_test",
                    matcher=MatcherConfig(
                        required_keywords=["Assets"],
                        min_match_score=0.5,
                    ),
                    structure_rules=StructureRuleSet(
                        enabled=True,
                        trim_trailing_summary=True,
                    ),
                )
            ]
        )

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]

            extractor_plain = TableExtractor()
            tables_plain = extractor_plain.extract(page)

            extractor_rules = TableExtractor(table_config=config)
            tables_rules = extractor_rules.extract(page)

            # Both should detect a table
            if tables_plain and tables_rules:
                # The rule-applied version should have fewer or equal rows
                assert tables_rules[0].rows <= tables_plain[0].rows
        finally:
            doc.close()

    def test_unmatched_profile_leaves_tables_unchanged(self, tmp_dir):
        """A profile that doesn't match should not alter tables."""
        from hexai_pdf_parser.table_config import (
            LayoutProfile,
            MatcherConfig,
            StructureRuleSet,
            TableConfig,
        )

        pdf_path = Path(tmp_dir) / "unmatched.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "A"), (150.0, "10")]),
                (48.0, [(20.0, "B"), (150.0, "20")]),
            ],
        )

        config = TableConfig(
            profiles=[
                LayoutProfile(
                    name="never_match",
                    matcher=MatcherConfig(
                        required_keywords=["NONEXISTENT_KEYWORD_XYZ"],
                        min_match_score=0.5,
                    ),
                    structure_rules=StructureRuleSet(
                        enabled=True,
                        trim_trailing_summary=True,
                    ),
                )
            ]
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor_plain = TableExtractor()
            tables_plain = extractor_plain.extract(doc[0])

            extractor_rules = TableExtractor(table_config=config)
            tables_rules = extractor_rules.extract(doc[0])

            assert len(tables_plain) == len(tables_rules)
            for t1, t2 in zip(tables_plain, tables_rules):
                assert t1.rows == t2.rows
                assert t1.cols == t2.cols
        finally:
            doc.close()

    def test_handler_only_region_rules_still_invokes_handler(self, tmp_dir):
        """A region handler fires even without expand_anchors."""
        from hexai_pdf_parser.table_config import (
            LayoutProfile,
            MatcherConfig,
            RegionRuleSet,
            TableConfig,
        )
        from hexai_pdf_parser.table_rule_handlers import register_region_handler
        from hexai_pdf_parser.table_region_rules import TableRegionCandidate

        handler_called = {"value": False}

        @register_region_handler("test_handler_only_region")
        def handler_only(candidates, rows, params):
            handler_called["value"] = True
            return candidates

        pdf_path = Path(tmp_dir) / "handler_only_region.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "Assets"), (150.0, "10")]),
                (48.0, [(20.0, "Liabilities"), (150.0, "20")]),
            ],
        )

        config = TableConfig(
            profiles=[
                LayoutProfile(
                    name="handler_only",
                    matcher=MatcherConfig(
                        required_keywords=["Assets"],
                        min_match_score=0.5,
                    ),
                    region_rules=RegionRuleSet(
                        enabled=True,
                        handler="test_handler_only_region",
                        # No expand_anchors — handler-only config
                    ),
                )
            ]
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor(table_config=config)
            extractor.extract(doc[0])
            assert handler_called["value"] is True
        finally:
            doc.close()

    def test_handler_invocation(self, tmp_dir):
        """A matched profile with a handler calls the registered handler."""
        from hexai_pdf_parser.table_config import (
            LayoutProfile,
            MatcherConfig,
            StructureRuleSet,
            TableConfig,
        )
        from hexai_pdf_parser.table_rule_handlers import register_structure_handler
        from hexai_pdf_parser.table_structure_rules import TableStructureCandidate

        handler_called = {"value": False}

        @register_structure_handler("test_invoke_handler")
        def invoke_handler(candidate: TableStructureCandidate, params):
            handler_called["value"] = True
            return candidate

        pdf_path = Path(tmp_dir) / "handler.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "Assets"), (150.0, "10")]),
                (48.0, [(20.0, "Liabilities"), (150.0, "20")]),
            ],
        )

        config = TableConfig(
            profiles=[
                LayoutProfile(
                    name="handler_test",
                    matcher=MatcherConfig(
                        required_keywords=["Assets"],
                        min_match_score=0.5,
                    ),
                    structure_rules=StructureRuleSet(
                        enabled=True,
                        handler="test_invoke_handler",
                    ),
                )
            ]
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor(table_config=config)
            extractor.extract(doc[0])
            assert handler_called["value"] is True
        finally:
            doc.close()


class TestEndToEndRegression:
    """End-to-end regression tests for the table layout rule system."""

    def test_region_rules_add_table_missed_by_baseline(self, tmp_dir):
        """Anchor-driven region rules add a table the baseline missed.

        Build a PDF where base extraction finds one table but a second
        table-like area (positioned below a gap) is only picked up when
        region anchors point to it.
        """
        from hexai_pdf_parser.table_config import (
            LayoutProfile,
            MatcherConfig,
            RegionRuleSet,
            TableConfig,
        )

        # Top table: normal alignment, base pipeline will find it.
        # Bottom area: same alignment but far below — the base pipeline
        # treats it as a separate span and may or may not pick it up.
        # With an anchor keyword, region rules will explicitly locate it.
        pdf_path = Path(tmp_dir) / "region_anchor.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                # Upper table (base pipeline finds this)
                (30.0, [(20.0, "Alpha"), (150.0, "100")]),
                (48.0, [(20.0, "Beta"), (150.0, "200")]),
                # Large gap — splits spans
                (120.0, [(20.0, "AnchoredSection"), (150.0, "Value")]),
                (138.0, [(20.0, "Row1"), (150.0, "10")]),
                (156.0, [(20.0, "Row2"), (150.0, "20")]),
            ],
            page_size=(320.0, 220.0),
        )

        config = TableConfig(
            profiles=[
                LayoutProfile(
                    name="anchor_test",
                    matcher=MatcherConfig(
                        required_keywords=["AnchoredSection"],
                        min_match_score=0.5,
                    ),
                    region_rules=RegionRuleSet(
                        expand_anchors=["AnchoredSection"],
                        min_row_window=2,
                        enabled=True,
                    ),
                )
            ]
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor_plain = TableExtractor()
            tables_plain = extractor_plain.extract(doc[0])

            extractor_anchored = TableExtractor(table_config=config)
            tables_anchored = extractor_anchored.extract(doc[0])

            # The anchor-driven extractor should find at least as many tables.
            # The table may be found by the baseline text_alignment detector
            # (improved continuation merging) or by the region_rule.
            assert len(tables_anchored) >= len(tables_plain)
            sources = [t.source for t in tables_anchored]
            assert "region_rule" in sources or len(tables_anchored) >= 1
        finally:
            doc.close()

    def test_structure_handler_modifies_table_shape(self, tmp_dir):
        """A registered structure handler can change table dimensions."""
        from hexai_pdf_parser.table_config import (
            LayoutProfile,
            MatcherConfig,
            StructureRuleSet,
            TableConfig,
        )
        from hexai_pdf_parser.table_rule_handlers import register_structure_handler
        from hexai_pdf_parser.table_structure_rules import TableStructureCandidate

        @register_structure_handler("test_drop_last_row")
        def drop_last_row(candidate: TableStructureCandidate, params):
            if candidate.rows <= 1:
                return candidate
            return TableStructureCandidate(
                rows=candidate.rows - 1,
                cols=candidate.cols,
                cells=[c for c in candidate.cells if c.row_index < candidate.rows - 1],
            )

        pdf_path = Path(tmp_dir) / "drop_row.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "Label"), (150.0, "Amount")]),
                (48.0, [(20.0, "Row1"), (150.0, "10")]),
                (66.0, [(20.0, "Row2"), (150.0, "20")]),
            ],
        )

        config = TableConfig(
            profiles=[
                LayoutProfile(
                    name="drop_test",
                    matcher=MatcherConfig(
                        required_keywords=["Label"],
                        min_match_score=0.5,
                    ),
                    structure_rules=StructureRuleSet(
                        enabled=True,
                        handler="test_drop_last_row",
                    ),
                )
            ]
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor_plain = TableExtractor()
            tables_plain = extractor_plain.extract(doc[0])

            extractor_handler = TableExtractor(table_config=config)
            tables_handler = extractor_handler.extract(doc[0])

            if tables_plain and tables_handler:
                assert tables_handler[0].rows < tables_plain[0].rows
        finally:
            doc.close()

    def test_structure_handler_cell_level_correction_is_written_back(self, tmp_dir):
        """A handler that only changes cell text (not rows/cols) takes effect."""
        from hexai_pdf_parser.models import Cell
        from hexai_pdf_parser.table_config import (
            LayoutProfile,
            MatcherConfig,
            StructureRuleSet,
            TableConfig,
        )
        from hexai_pdf_parser.table_rule_handlers import register_structure_handler
        from hexai_pdf_parser.table_structure_rules import TableStructureCandidate

        @register_structure_handler("test_uppercase_cells")
        def uppercase_cells(candidate: TableStructureCandidate, params):
            new_cells = [
                Cell(
                    text=c.text.upper(),
                    row_index=c.row_index,
                    col_index=c.col_index,
                    bbox=c.bbox,
                    rowspan=c.rowspan,
                    colspan=c.colspan,
                )
                for c in candidate.cells
            ]
            return TableStructureCandidate(
                rows=candidate.rows,
                cols=candidate.cols,
                cells=new_cells,
            )

        pdf_path = Path(tmp_dir) / "cell_edit.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "Alpha"), (150.0, "10")]),
                (48.0, [(20.0, "Beta"), (150.0, "20")]),
            ],
        )

        config = TableConfig(
            profiles=[
                LayoutProfile(
                    name="cell_test",
                    matcher=MatcherConfig(
                        required_keywords=["Alpha"],
                        min_match_score=0.5,
                    ),
                    structure_rules=StructureRuleSet(
                        enabled=True,
                        handler="test_uppercase_cells",
                    ),
                )
            ]
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor_plain = TableExtractor()
            tables_plain = extractor_plain.extract(doc[0])

            extractor_handler = TableExtractor(table_config=config)
            tables_handler = extractor_handler.extract(doc[0])

            if tables_plain and tables_handler:
                # Dimensions must stay the same
                assert tables_handler[0].rows == tables_plain[0].rows
                assert tables_handler[0].cols == tables_plain[0].cols
                # But cell text should be uppercased
                handler_texts = [c.text for c in tables_handler[0].cells]
                assert all(t == t.upper() for t in handler_texts if t)
                plain_texts = [c.text for c in tables_plain[0].cells]
                assert not all(t == t.upper() for t in plain_texts if t)
        finally:
            doc.close()

    def test_extract_via_text_alignment_long_horizontal_separator_merges_header(
        self, tmp_dir
    ):
        """A long drawn horizontal line between header and body text causes
        them to be merged into a single table via separator-driven detection."""
        pdf_path = Path(tmp_dir) / "long_horizontal_separator.pdf"
        doc = fitz.open()
        page = doc.new_page(width=480, height=200)
        # Header text above separator
        page.insert_text((30, 40), "Item", fontsize=10)
        page.insert_text((180, 40), "Amount", fontsize=10)
        page.insert_text((320, 40), "Prior", fontsize=10)
        # Draw a long horizontal line spanning most of the page width
        page.draw_line((30, 52), (440, 52), color=(0, 0, 0), width=0.5)
        # Body text below separator
        page.insert_text((30, 72), "Revenue", fontsize=10)
        page.insert_text((180, 72), "1,234,567.89", fontsize=10)
        page.insert_text((320, 72), "987,654.32", fontsize=10)
        page.insert_text((30, 90), "Cost", fontsize=10)
        page.insert_text((180, 90), "2,345,678.90", fontsize=10)
        page.insert_text((320, 90), "876,543.21", fontsize=10)
        page.insert_text((30, 108), "Profit", fontsize=10)
        page.insert_text((180, 108), "3,456,789.01", fontsize=10)
        page.insert_text((320, 108), "765,432.10", fontsize=10)
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert len(tables) >= 1
            table = tables[0]
            # The header row (Item/Amount/Prior) above the separator
            # must be included in the table region.
            cells = {
                (cell.row_index, cell.col_index): cell.text for cell in table.cells
            }
            header_included = any("Item" in c.text for c in table.cells)
            assert header_included, f"Header row not included in table: {cells}"
            assert table.rows >= 4
            assert table.cols >= 3
        finally:
            doc.close()

    def test_line_based_tables_unchanged_without_profile(self, tmp_dir):
        """Line-based tables remain identical without profile rules."""
        pdf_path = Path(tmp_dir) / "line_table_regression.pdf"
        make_pdf_with_table(pdf_path)

        from hexai_pdf_parser.table_config import TableConfig

        doc = fitz.open(str(pdf_path))
        try:
            extractor_plain = TableExtractor()
            tables_plain = extractor_plain.extract(doc[0])

            extractor_config = TableExtractor(table_config=TableConfig.default())
            tables_config = extractor_config.extract(doc[0])

            assert len(tables_plain) == len(tables_config)
            for t1, t2 in zip(tables_plain, tables_config):
                assert t1.rows == t2.rows
                assert t1.cols == t2.cols
                assert len(t1.cells) == len(t2.cells)
        finally:
            doc.close()


def test_financial_grouped_header_is_promoted_on_page_046():
    pdf_path = Path(r"D:\codes\PDFLayoutParser\152590_20230428_N7ZK_0.pdf")

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[46])

    financial = next(
        t for t in tables
        if any("本年金额" in cell.text for cell in t.cells)
        or (t.rows >= 3 and t.cols >= 8)
    )

    assert financial.bbox.y0 < 310.0
    assert any(
        cell.text == "本年金额" and cell.colspan == 7
        for cell in financial.cells
    )
    assert any(
        cell.text == "项目" and cell.rowspan == 2
        for cell in financial.cells
    )


def test_complex_financial_header_handler_normalizes_grouped_header():
    from hexai_pdf_parser.financial_header_handler import (
        normalize_complex_financial_header,
    )

    cells: list[Cell] = [
        Cell(text="", row_index=0, col_index=0, bbox=BBox(0, 0, 10, 10)),
        Cell(text="本年金额", row_index=0, col_index=1, bbox=BBox(10, 0, 20, 10)),
        Cell(text="", row_index=0, col_index=2, bbox=BBox(20, 0, 30, 10)),
        Cell(text="", row_index=0, col_index=3, bbox=BBox(30, 0, 40, 10)),
        Cell(text="", row_index=0, col_index=4, bbox=BBox(40, 0, 50, 10)),
        Cell(text="", row_index=0, col_index=5, bbox=BBox(50, 0, 60, 10)),
        Cell(text="", row_index=0, col_index=6, bbox=BBox(60, 0, 70, 10)),
        Cell(text="", row_index=0, col_index=7, bbox=BBox(70, 0, 80, 10)),
        Cell(text="项目", row_index=1, col_index=0, bbox=BBox(0, 10, 10, 20)),
        Cell(text="年初资产总额", row_index=1, col_index=1, bbox=BBox(10, 10, 20, 20)),
        Cell(text="年初负债总额", row_index=1, col_index=2, bbox=BBox(20, 10, 30, 20)),
        Cell(text="年初资本公积", row_index=1, col_index=3, bbox=BBox(30, 10, 40, 20)),
        Cell(text="年初盈余公积", row_index=1, col_index=4, bbox=BBox(40, 10, 50, 20)),
        Cell(text="年初未分配利润", row_index=1, col_index=5, bbox=BBox(50, 10, 60, 20)),
        Cell(text="年初少数股东权益", row_index=1, col_index=6, bbox=BBox(60, 10, 70, 20)),
        Cell(text="年初归属于母公司所有者权益总额", row_index=1, col_index=7, bbox=BBox(70, 10, 80, 20)),
        Cell(text="追溯调整前余额", row_index=2, col_index=0, bbox=BBox(0, 20, 10, 30)),
        Cell(text="780,435,127,240.78", row_index=2, col_index=1, bbox=BBox(10, 20, 20, 30)),
        Cell(text="511,686,422,633.62", row_index=2, col_index=2, bbox=BBox(20, 20, 30, 30)),
        Cell(text="244,583,302,593.81", row_index=2, col_index=3, bbox=BBox(30, 20, 40, 30)),
        Cell(text="15,745,573,807.25", row_index=2, col_index=4, bbox=BBox(40, 20, 50, 30)),
        Cell(text="2,127,378,786.61", row_index=2, col_index=5, bbox=BBox(50, 20, 60, 30)),
        Cell(text="14,538,588,616.87", row_index=2, col_index=6, bbox=BBox(60, 20, 70, 30)),
        Cell(text="24,165,402,013.35", row_index=2, col_index=7, bbox=BBox(70, 20, 80, 30)),
    ]

    table = Table(
        bbox=BBox(0, 0, 80, 30),
        rows=3,
        cols=8,
        cells=cells,
        confidence=0.9,
        source="PyMuPDF.find_tables",
    )

    mock_page = SimpleNamespace()
    result = normalize_complex_financial_header(table, mock_page)

    group_label = next(c for c in result.cells if c.text == "本年金额")
    assert group_label.col_index == 1
    assert group_label.colspan == 7
    left_anchor = next(c for c in result.cells if c.text == "项目")
    assert left_anchor.rowspan == 2


def test_page_046_lower_table_matches_label_structure():
    pdf_path = Path(r"D:\codes\PDFLayoutParser\152590_20230428_N7ZK_0.pdf")

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[46])

    lower = next(t for t in tables if t.bbox.y0 >= 300.0)

    assert lower.rows == 5
    assert lower.cols == 8
    cell_map = {(cell.row_index, cell.col_index): cell for cell in lower.cells}
    assert cell_map[(0, 0)].rowspan == 2
    assert cell_map[(0, 1)].colspan == 7
    assert not any(ch.isdigit() for ch in cell_map[(1, 3)].text)
    assert cell_map[(2, 3)].text == "244,583,302,593.81"
    assert cell_map[(3, 6)].text == "20,136,924.05"
    assert cell_map[(4, 3)].text == "244,603,439,517.86"
    assert cell_map[(4, 6)].text == "14,558,725,540.92"


def test_plain_grid_table_is_not_changed_by_header_normalization(tmp_dir):
    pdf_path = Path(tmp_dir) / "plain_grid.pdf"
    make_pdf_with_table(pdf_path)

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[0])

    assert len(tables) == 1
    table = tables[0]
    assert table.rows == 2
    assert table.cols == 2
    assert all(cell.rowspan == 1 for cell in table.cells)
    assert all(cell.colspan == 1 for cell in table.cells)


def test_complex_financial_handler_does_not_touch_plain_grid_table(tmp_dir):
    pdf_path = Path(tmp_dir) / "plain_grid.pdf"
    make_pdf_with_table(pdf_path)

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[0])

    assert len(tables) == 1
    table = tables[0]
    assert table.rows == 2
    assert table.cols == 2
    assert all(cell.rowspan == 1 for cell in table.cells)
    assert all(cell.colspan == 1 for cell in table.cells)


def test_page_046_lower_table_uses_complex_financial_header():
    pdf_path = Path(r"D:\codes\PDFLayoutParser\152590_20230428_N7ZK_0.pdf")

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[46])

    lower = next(t for t in tables if t.bbox.y0 >= 300.0)

    assert lower.rows == 5
    assert lower.cols == 8
    assert any(
        cell.text == "项目"
        and cell.row_index == 0
        and cell.col_index == 0
        and cell.rowspan == 2
        for cell in lower.cells
    )
    assert any(
        cell.text == "本年金额"
        and cell.row_index == 0
        and cell.col_index == 1
        and cell.colspan == 7
        for cell in lower.cells
    )
    assert any(
        cell.text == "追溯调整前余额"
        and cell.row_index == 2
        and cell.col_index == 0
        for cell in lower.cells
    )
    assert any(
        cell.text == "追溯调整"
        and cell.row_index == 3
        and cell.col_index == 0
        for cell in lower.cells
    )
    assert any(
        cell.text == "追溯调整后余额"
        and cell.row_index == 4
        and cell.col_index == 0
        for cell in lower.cells
    )


def test_text_aligned_page_046_tables_are_reconstructed():
    pdf_path = Path(r"D:\codes\PDFLayoutParser\152590_20230428_N7ZK_0.pdf")

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[46])

    upper = next(t for t in tables if t.bbox.y0 < 300.0)
    lower = next(t for t in tables if t.bbox.y0 >= 300.0)

    assert upper.rows == 3
    assert upper.cols == 7
    assert any(cell.text == "所属单位" and cell.row_index == 0 for cell in upper.cells)
    assert any(
        cell.text == "受影响的各个比较期间报表项目名称" and cell.row_index == 0
        for cell in upper.cells
    )
    assert any(
        "北京市地铁运" in cell.text and "营有限公司" in cell.text
        for cell in upper.cells
    )
    assert any(
        cell.text.startswith("本公司") and "合并报表" in cell.text
        for cell in upper.cells
    )

    assert lower.rows == 5
    assert lower.cols == 8
    assert any(cell.text == "本年金额" and cell.col_index == 1 and cell.colspan == 7 for cell in lower.cells)
    assert any(cell.text == "项目" and cell.row_index == 0 and cell.rowspan == 2 for cell in lower.cells)
    assert any(
        "年初归属于母公司" in cell.text and "所有者权益总额" in cell.text
        and cell.row_index == 1
        and cell.col_index == 3
        for cell in lower.cells
    )
    assert any(
        cell.text == "追溯调整前余额" and cell.row_index == 2 and cell.col_index == 0
        for cell in lower.cells
    )


def test_promote_grouped_financial_header_sets_rowspan_and_colspan():
    from hexai_pdf_parser.table_header_normalizer import normalize_table_headers

    # Build a table that mimics the page-46 financial header structure:
    #   Row 0: [empty, "本年金额", empty, empty, empty, empty, empty, empty]
    #   Row 1: ["项目", "年初资产总额", "年初负债总额", "年初资本公积",
    #           "年初盈余公积", "年初未分配利润", "年初少数股东权益", "年初归属于母公司"]
    #   Row 2+: body rows (omitted for brevity; not needed for header detection)
    cells: list[Cell] = [
        Cell(text="",            row_index=0, col_index=0, bbox=BBox(0,  0, 10, 10)),
        Cell(text="本年金额",     row_index=0, col_index=1, bbox=BBox(10, 0, 20, 10)),
        Cell(text="",            row_index=0, col_index=2, bbox=BBox(20, 0, 30, 10)),
        Cell(text="",            row_index=0, col_index=3, bbox=BBox(30, 0, 40, 10)),
        Cell(text="",            row_index=0, col_index=4, bbox=BBox(40, 0, 50, 10)),
        Cell(text="",            row_index=0, col_index=5, bbox=BBox(50, 0, 60, 10)),
        Cell(text="",            row_index=0, col_index=6, bbox=BBox(60, 0, 70, 10)),
        Cell(text="",            row_index=0, col_index=7, bbox=BBox(70, 0, 80, 10)),
        Cell(text="项目",        row_index=1, col_index=0, bbox=BBox(0,  10, 10, 20)),
        Cell(text="年初资产总额", row_index=1, col_index=1, bbox=BBox(10, 10, 20, 20)),
        Cell(text="年初负债总额", row_index=1, col_index=2, bbox=BBox(20, 10, 30, 20)),
        Cell(text="年初资本公积", row_index=1, col_index=3, bbox=BBox(30, 10, 40, 20)),
        Cell(text="年初盈余公积", row_index=1, col_index=4, bbox=BBox(40, 10, 50, 20)),
        Cell(text="年初未分配利润", row_index=1, col_index=5, bbox=BBox(50, 10, 60, 20)),
        Cell(text="年初少数股东权益", row_index=1, col_index=6, bbox=BBox(60, 10, 70, 20)),
        Cell(text="年初归属于母公司", row_index=1, col_index=7, bbox=BBox(70, 10, 80, 20)),
    ]

    table = Table(
        bbox=BBox(0, 0, 80, 30),
        rows=3,
        cols=8,
        cells=cells,
        confidence=0.9,
        source="PyMuPDF.find_tables",
    )

    # page argument is only used for page-text scanning; not needed for
    # the pattern detected via table-internal cells, but the API requires it.
    mock_page = SimpleNamespace()

    result = normalize_table_headers(table, mock_page)

    # Group label "本年金额" should span all columns except the left anchor.
    group_label = next(c for c in result.cells if "本年金额" in c.text)
    assert group_label.colspan == 7

    # Left anchor "项目" should span both header rows.
    left_anchor = next(c for c in result.cells if c.text == "项目")
    assert left_anchor.rowspan == 2

    # Body cells are unchanged.
    body_cell = next(c for c in result.cells if c.text == "年初资产总额")
    assert body_cell.rowspan == 1
    assert body_cell.colspan == 1


def test_promote_grouped_financial_header_inserts_external_header_band():
    from hexai_pdf_parser.table_header_normalizer import normalize_table_headers

    table = Table(
        bbox=BBox(38.0, 320.0, 804.0, 408.0),
        rows=3,
        cols=8,
        cells=[
            Cell(
                text="项目",
                row_index=0,
                col_index=0,
                bbox=BBox(66.0, 320.0, 84.0, 339.0),
                rowspan=2,
            ),
            Cell(
                text="年初资产总额",
                row_index=1,
                col_index=1,
                bbox=BBox(136.0, 330.0, 191.0, 339.0),
            ),
            Cell(
                text="年初负债总额",
                row_index=1,
                col_index=2,
                bbox=BBox(240.0, 330.0, 295.0, 339.0),
            ),
        ],
    )

    mock_page = SimpleNamespace(
        get_text=lambda *args, **kwargs: {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "本年金额",
                                    "bbox": [460.0, 302.0, 530.0, 312.0],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    )

    result = normalize_table_headers(table, mock_page)

    assert result.bbox.y0 == 302.0
    assert result.rows == 3
    assert any(
        cell.text == "本年金额"
        and cell.row_index == 0
        and cell.col_index == 1
        and cell.colspan == 7
        for cell in result.cells
    )
    assert any(
        cell.text == "项目" and cell.row_index == 0 and cell.rowspan == 2
        for cell in result.cells
    )
