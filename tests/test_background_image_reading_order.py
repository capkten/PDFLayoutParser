"""Tests for LayoutBuilder reading order in the presence of background/watermark images."""

from hexai_pdf_parser.core.models import BBox, Image, LayoutElement
from hexai_pdf_parser.extractors.layout_builder import LayoutBuilder


def test_hanging_indent_list_with_background_image():
    """A full-height background image must not cause all list numbers to sort before text bodies."""
    # List items: number on the left (x: 36..44), body on the right (x: 50..450)
    item1_num = LayoutElement(type="text", bbox=BBox(36.0, 50.0, 44.0, 60.0), order=0, content="1.")
    item1_txt = LayoutElement(type="text", bbox=BBox(50.0, 50.0, 450.0, 60.0), order=1, content="Item 1 detail text")

    item2_num = LayoutElement(type="text", bbox=BBox(36.0, 70.0, 44.0, 80.0), order=2, content="2.")
    item2_txt = LayoutElement(type="text", bbox=BBox(50.0, 70.0, 450.0, 80.0), order=3, content="Item 2 detail text")

    item3_num = LayoutElement(type="text", bbox=BBox(36.0, 90.0, 44.0, 100.0), order=4, content="3.")
    item3_txt = LayoutElement(type="text", bbox=BBox(50.0, 90.0, 450.0, 100.0), order=5, content="Item 3 detail text")

    text_elements = [item1_num, item1_txt, item2_num, item2_txt, item3_num, item3_txt]

    # Large background / watermark image spanning across y=40 to 800
    bg_image = Image(
        bbox=BBox(1.0, 40.0, 400.0, 800.0),
        page_index=0,
        resource_index=0,
        width=400,
        height=760,
    )

    builder = LayoutBuilder()
    result = builder.build(text_elements, [], [bg_image])

    # Extract text elements in their sorted order
    text_contents = [e.content for e in result if e.type == "text"]

    expected_order = [
        "1.",
        "Item 1 detail text",
        "2.",
        "Item 2 detail text",
        "3.",
        "Item 3 detail text",
    ]
    assert text_contents == expected_order, (
        f"Reading order was corrupted by background image! Got: {text_contents}"
    )
