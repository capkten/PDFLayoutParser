"""Unit tests for natural reading order sorting."""

import pytest
from hexai_pdf_parser.core.models import BBox, LayoutElement, Table, Image
from hexai_pdf_parser.extractors.layout_builder import LayoutBuilder
from hexai_pdf_parser.extractors.reading_order import sort_by_reading_order


class TestReadingOrder:
    def test_single_column_top_to_bottom(self):
        """Single column elements should sort naturally from top to bottom."""
        b1 = LayoutElement(type="text", bbox=BBox(50, 10, 300, 30), order=0, content="Line 1")
        b2 = LayoutElement(type="text", bbox=BBox(50, 40, 300, 60), order=1, content="Line 2")
        b3 = LayoutElement(type="text", bbox=BBox(50, 70, 300, 90), order=2, content="Line 3")

        # Pass in shuffled order
        sorted_elements = sort_by_reading_order([b3, b1, b2])
        contents = [e.content for e in sorted_elements]
        assert contents == ["Line 1", "Line 2", "Line 3"]

    def test_two_column_left_then_right(self):
        """Two-column layout should read entire left column before right column."""
        # Left column (x: 50..200)
        l1 = LayoutElement(type="text", bbox=BBox(50, 50, 200, 70), order=0, content="L1")
        l2 = LayoutElement(type="text", bbox=BBox(50, 90, 200, 110), order=1, content="L2")
        l3 = LayoutElement(type="text", bbox=BBox(50, 130, 200, 150), order=2, content="L3")

        # Right column (x: 250..400)
        r1 = LayoutElement(type="text", bbox=BBox(250, 40, 400, 80), order=3, content="R1")
        r2 = LayoutElement(type="text", bbox=BBox(250, 100, 400, 140), order=4, content="R2")

        # Pass in interleaved / arbitrary order
        sorted_elements = sort_by_reading_order([r1, l2, r2, l1, l3])
        contents = [e.content for e in sorted_elements]
        assert contents == ["L1", "L2", "L3", "R1", "R2"]

    def test_mixed_header_twocolumn_footer(self):
        """Full-width header -> Left column -> Right column -> Full-width footer."""
        header = LayoutElement(type="text", bbox=BBox(50, 10, 400, 30), order=0, content="Header")

        # Left column
        l1 = LayoutElement(type="text", bbox=BBox(50, 50, 200, 80), order=1, content="L1")
        l2 = LayoutElement(type="text", bbox=BBox(50, 90, 200, 120), order=2, content="L2")

        # Right column (with a table)
        r_table = Table(bbox=BBox(250, 50, 400, 90), rows=2, cols=2)
        r1 = LayoutElement(type="table", bbox=r_table.bbox, order=3, content=r_table)
        r2 = LayoutElement(type="text", bbox=BBox(250, 100, 400, 120), order=4, content="R2")

        footer = LayoutElement(type="text", bbox=BBox(50, 150, 400, 170), order=5, content="Footer")

        shuffled = [r2, footer, l1, header, r1, l2]
        sorted_elements = sort_by_reading_order(shuffled)

        expected = [header, l1, l2, r1, r2, footer]
        assert sorted_elements == expected

    def test_layout_builder_integrates_reading_order(self):
        """LayoutBuilder.build() should produce layout elements ordered by reading order."""
        header = LayoutElement(type="text", bbox=BBox(50, 10, 400, 30), order=0, content="Header")
        l1 = LayoutElement(type="text", bbox=BBox(50, 50, 200, 80), order=1, content="Left Body")
        r_text = LayoutElement(type="text", bbox=BBox(250, 100, 400, 130), order=2, content="Right Body")

        table = Table(bbox=BBox(250, 50, 400, 90), rows=2, cols=2)

        builder = LayoutBuilder()
        result = builder.build([r_text, header, l1], [table], [])

        assert len(result) == 4
        assert [e.order for e in result] == [0, 1, 2, 3]
        assert result[0].content == "Header"
        assert result[1].content == "Left Body"
        assert result[2].type == "table"
        assert result[3].content == "Right Body"

    def test_same_line_minor_y_jitter_orders_left_to_right(self):
        """When right fragment has slightly smaller y0 due to font differences, order must be left-to-right."""
        line_prev = LayoutElement(
            type="text",
            bbox=BBox(125.5, 329.0, 505.8, 340.7),
            order=0,
            content="Line Prev",
        )
        # Left fragment (starts lower at y0=349.4)
        left_frag = LayoutElement(
            type="text",
            bbox=BBox(125.5, 349.4, 372.7, 360.0),
            order=1,
            content="Left Fragment",
        )
        # Right fragment (due to English/brackets, y0=349.1 is 0.3pt higher than left)
        right_frag = LayoutElement(
            type="text",
            bbox=BBox(362.3, 349.1, 505.8, 360.8),
            order=2,
            content="Right Fragment",
        )
        line_next = LayoutElement(
            type="text",
            bbox=BBox(125.5, 369.0, 505.8, 380.7),
            order=3,
            content="Line Next",
        )

        # Shuffle and sort
        sorted_elements = sort_by_reading_order([right_frag, line_next, left_frag, line_prev])
        contents = [e.content for e in sorted_elements]
        assert contents == ["Line Prev", "Left Fragment", "Right Fragment", "Line Next"]

    def test_two_column_never_interleaves_horizontally(self):
        """Two columns with identical y-ranges must be fully read column-by-column, never interleaved."""
        l1 = LayoutElement(type="text", bbox=BBox(50, 50, 200, 70), order=0, content="Left 1")
        l2 = LayoutElement(type="text", bbox=BBox(50, 80, 200, 100), order=1, content="Left 2")
        l3 = LayoutElement(type="text", bbox=BBox(50, 110, 200, 130), order=2, content="Left 3")

        r1 = LayoutElement(type="text", bbox=BBox(250, 50, 400, 70), order=3, content="Right 1")
        r2 = LayoutElement(type="text", bbox=BBox(250, 80, 400, 100), order=4, content="Right 2")
        r3 = LayoutElement(type="text", bbox=BBox(250, 110, 400, 130), order=5, content="Right 3")

        # Shuffled
        sorted_elements = sort_by_reading_order([r2, l1, r1, l3, r3, l2])
        contents = [e.content for e in sorted_elements]
        assert contents == ["Left 1", "Left 2", "Left 3", "Right 1", "Right 2", "Right 3"]

    def test_numbered_bullet_with_tall_prose_not_absorbed_by_prev_line(self):
        """Numbered bullet and its tall body text should not be absorbed into prev line or inverted."""
        prev_line = LayoutElement(
            type="text",
            bbox=BBox(46.10, 605.33, 300.0, 614.33),
            order=0,
            content="7_prev_line",
        )
        bullet_8 = LayoutElement(
            type="text",
            bbox=BBox(36.0, 618.8310546875, 43.785003662109375, 627.8310546875),
            order=1,
            content="8.",
        )
        prose_8 = LayoutElement(
            type="text",
            bbox=BBox(46.09999084472656, 610.7689819335938, 555.2149658203125, 636.490966796875),
            order=2,
            content="2017年07月05日招商银行...",
        )
        tail_8 = LayoutElement(
            type="text",
            bbox=BBox(46.0999755859375, 638.0, 100.0, 647.0),
            order=3,
            content="度0。",
        )

        # Shuffle and sort
        sorted_elements = sort_by_reading_order([prose_8, tail_8, bullet_8, prev_line])
        contents = [e.content for e in sorted_elements]
        assert contents == ["7_prev_line", "8.", "2017年07月05日招商银行...", "度0。"]

    def test_sub_threshold_vertical_overlap_does_not_merge_lines(self):
        """Small vertical overlap (e.g. 2.5pt < 40% of line height) must NOT merge distinct lines."""
        line1 = LayoutElement(
            type="text",
            bbox=BBox(50.0, 100.0, 200.0, 110.0),
            order=0,
            content="Line 1",
        )
        # Line 2 overlaps line 1 by 2.0pt (108.0 to 110.0), height 10.0, overlap ratio 20%
        line2 = LayoutElement(
            type="text",
            bbox=BBox(50.0, 108.0, 200.0, 118.0),
            order=1,
            content="Line 2",
        )
        sorted_elements = sort_by_reading_order([line2, line1])
        assert [e.content for e in sorted_elements] == ["Line 1", "Line 2"]

    def test_same_line_pixel_jitter_merges_and_sorts_left_to_right(self):
        """Elements on same line with 2-3px jitter but >=45% overlap should merge and sort left-to-right."""
        label = LayoutElement(
            type="text",
            bbox=BBox(30.0, 200.0, 60.0, 212.0),
            order=0,
            content="Label:",
        )
        # Value has slightly different font metrics (y: 202..214, 2px lower, 10px overlap / 12px min_h = 83%)
        val = LayoutElement(
            type="text",
            bbox=BBox(65.0, 202.0, 150.0, 214.0),
            order=1,
            content="Value 123",
        )
        sorted_elements = sort_by_reading_order([val, label])
        assert [e.content for e in sorted_elements] == ["Label:", "Value 123"]
