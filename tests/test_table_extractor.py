"""Tests for the table extractor."""

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from pdflayoutparser.models import BBox, Cell, Table
from pdflayoutparser.table_extractor import TableExtractor


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


class TestTableExtractor:
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
