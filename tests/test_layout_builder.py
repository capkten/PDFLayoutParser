"""Tests for the layout builder."""

import pytest

from pdflayoutparser.layout_builder import LayoutBuilder
from pdflayoutparser.models import BBox, Image, LayoutElement, Table


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
