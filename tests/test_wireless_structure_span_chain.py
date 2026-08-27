from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan
from hexai_pdf_parser.tables.wireless_structure.span_chain import region_spans


def _span(text, bbox, order, *, source_position=None):
    span = NativeSpan(text, bbox, "SimSun", 10, order)
    if source_position is not None:
        span.source_position = source_position
    return span


def test_region_spans_preserves_native_source_metadata_and_filters_by_center():
    inside = _span("项目", BBox(10, 10, 30, 20), 4, source_position=(2, 3, 1))
    outside = _span("页眉", BBox(10, 100, 30, 110), 5, source_position=(0, 0, 0))

    result = region_spans([outside, inside], BBox(0, 0, 50, 50))

    assert [item["text"] for item in result] == ["项目"]
    assert result[0]["source_position"] == [2, 3, 1]
    assert result[0]["flow"] == 1
    assert result[0]["span_ref"] == "S4"


def test_region_spans_splits_packed_numeric_fields_using_character_gap():
    text = "100   200"
    chars = []
    x = 10.0
    for char in text:
        if char == "2":
            x += 8.0
        width = 4.0 if not char.isspace() else 8.0
        chars.append((char, BBox(x, 10, x + width, 20)))
        x += width
    span = NativeSpan(text, BBox(10, 10, x, 20), "SimSun", 10, 7, chars)
    span.source_position = (1, 2, 0)

    result = region_spans([span], BBox(0, 0, 100, 50))

    assert [item["text"] for item in result] == ["100", "200"]
    assert [item["span_ref"] for item in result] == ["S7.1", "S7.2"]
    assert [item["source_position"] for item in result] == [[1, 2, 0], [1, 2, 2]]
