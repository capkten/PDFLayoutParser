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
