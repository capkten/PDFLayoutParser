"""Tests for the layout builder."""

import pytest

from hexai_pdf_parser.layout_builder import LayoutBuilder
from hexai_pdf_parser.models import BBox, Image, LayoutElement, Table


class TestLayoutBuilder:
    def test_build_page_layout_orders_elements(self):
        """Text LayoutElements are preserved with their original order."""
        element_a = LayoutElement(
            type="text",
            bbox=BBox(x0=0, y0=0, x1=10, y1=10),
            order=0,
            content="Hello",
        )
        element_b = LayoutElement(
            type="text",
            bbox=BBox(x0=10, y0=10, x1=20, y1=20),
            order=1,
            content="World",
        )

        builder = LayoutBuilder()
        result = builder.build([element_a, element_b], [], [])

        assert len(result) == 2
        assert result[0].type == "text"
        assert result[0].order == 0
        assert result[0].content == "Hello"
        assert result[1].type == "text"
        assert result[1].order == 1
        assert result[1].content == "World"

    def test_build_includes_tables_and_images(self):
        """Tables and images are appended after text elements."""
        text_element = LayoutElement(
            type="text",
            bbox=BBox(x0=0, y0=0, x1=10, y1=10),
            order=0,
            content="Text",
        )
        table = Table(
            bbox=BBox(x0=20, y0=20, x1=50, y1=50),
            rows=2,
            cols=2,
        )
        image = Image(
            bbox=BBox(x0=60, y0=60, x1=90, y1=90),
            page_index=0,
            resource_index=0,
            width=30,
            height=30,
        )

        builder = LayoutBuilder()
        result = builder.build([text_element], [table], [image])

        assert len(result) == 3
        assert result[0].type == "text"
        assert result[0].order == 0
        assert result[1].type == "table"
        assert result[1].order == 1
        assert result[1].content == table
        assert result[2].type == "image"
        assert result[2].order == 2
        assert result[2].content == image

    def test_build_keeps_text_with_small_table_overlap(self):
        """Small bbox overlap should not remove the text element."""
        overlapping_text = LayoutElement(
            type="text",
            bbox=BBox(x0=90, y0=10, x1=120, y1=30),
            order=0,
            content="Overlap",
        )
        table = Table(
            bbox=BBox(x0=0, y0=0, x1=100, y1=100),
            rows=2,
            cols=2,
        )

        builder = LayoutBuilder()
        result = builder.build([overlapping_text], [table], [])

        assert [element.type for element in result] == ["table", "text"]

    def test_build_filters_text_fully_inside_a_table(self):
        text_element = LayoutElement(
            type="text",
            bbox=BBox(x0=10, y0=10, x1=20, y1=20),
            order=0,
            content="Cell text",
        )
        table = Table(
            bbox=BBox(x0=0, y0=0, x1=100, y1=100),
            rows=2,
            cols=2,
        )

        result = LayoutBuilder().build([text_element], [table], [])

        assert [element.type for element in result] == ["table"]

    def test_build_filters_text_when_iou_exceeds_half(self):
        """Text should be filtered when bbox IoU with a table exceeds 0.5."""
        text_element = LayoutElement(
            type="text",
            bbox=BBox(x0=0, y0=0, x1=80, y1=80),
            order=0,
            content="Covered",
        )
        table = Table(
            bbox=BBox(x0=0, y0=0, x1=100, y1=100),
            rows=2,
            cols=2,
        )

        result = LayoutBuilder().build([text_element], [table], [])

        assert [element.type for element in result] == ["table"]

    def test_build_keeps_text_when_iou_equals_half(self):
        """An IoU of exactly 0.5 should not meet the strict threshold."""
        text_element = LayoutElement(
            type="text",
            bbox=BBox(x0=0, y0=0, x1=100, y1=50),
            order=0,
            content="Boundary",
        )
        table = Table(
            bbox=BBox(x0=0, y0=0, x1=100, y1=100),
            rows=2,
            cols=2,
        )

        result = LayoutBuilder().build([text_element], [table], [])

        assert [element.type for element in result] == ["table", "text"]

    def test_build_sorts_elements_by_page_position(self):
        """Layout elements should follow page order, top-to-bottom then left-to-right."""
        bottom_text = LayoutElement(
            type="text",
            bbox=BBox(x0=0, y0=180, x1=20, y1=190),
            order=0,
            content="Bottom",
        )
        top_text = LayoutElement(
            type="text",
            bbox=BBox(x0=0, y0=10, x1=20, y1=20),
            order=1,
            content="Top",
        )
        middle_table = Table(
            bbox=BBox(x0=0, y0=50, x1=40, y1=90),
            rows=2,
            cols=2,
        )
        bottom_image = Image(
            bbox=BBox(x0=0, y0=120, x1=30, y1=150),
            page_index=0,
            resource_index=0,
            width=30,
            height=30,
        )

        builder = LayoutBuilder()
        result = builder.build([bottom_text, top_text], [middle_table], [bottom_image])

        assert [element.type for element in result] == [
            "text",
            "table",
            "image",
            "text",
        ]
        assert [element.order for element in result] == [0, 1, 2, 3]
        assert [element.content for element in result if element.type == "text"] == [
            "Top",
            "Bottom",
        ]
