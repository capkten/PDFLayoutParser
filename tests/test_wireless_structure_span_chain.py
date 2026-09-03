from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan
from hexai_pdf_parser.tables.wireless_structure.span_chain import region_spans


def _span(text, bbox, order, *, source_position=None):
    span = NativeSpan(text, bbox, "SimSun", 10, order)
    if source_position is not None:
        span.source_position = source_position
    return span


def _packed_span(text, order=7, *, gap_before=None):
    characters = []
    x = 10.0
    after_space = False
    for index, char in enumerate(text):
        if gap_before is not None and index in gap_before:
            x += 6.0
        elif gap_before is None and after_space and not char.isspace():
            x += 6.0
        width = 2.0 if char.isspace() else 4.0
        characters.append((char, BBox(x, 10, x + width, 20)))
        x += width
        after_space = char.isspace()
    span = NativeSpan(text, BBox(10, 10, x, 20), "SimSun", 10, order, characters)
    span.source_position = (1, 2, 0)
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


def test_region_spans_splits_packed_amount_and_percentage_fields():
    result = region_spans(
        [_packed_span("5,100,000.00  51%")],
        BBox(0, 0, 200, 50),
    )

    assert [item["text"] for item in result] == ["5,100,000.00", "51%"]
    assert [item["span_ref"] for item in result] == ["S7.1", "S7.2"]


def test_region_spans_splits_placeholder_amount_and_percentage_fields():
    result = region_spans(
        [_packed_span("---  5,100,000.00  51%", gap_before={4, 19})],
        BBox(0, 0, 250, 50),
    )

    assert [item["text"] for item in result] == ["---", "5,100,000.00", "51%"]
    assert [item["span_ref"] for item in result] == ["S7.1", "S7.2", "S7.3"]
    assert [item["source_fragment_count"] for item in result] == [3, 3, 3]


def test_region_spans_does_not_split_mixed_chinese_numeric_text():
    span = _packed_span("1  年以内")

    result = region_spans([span], BBox(0, 0, 150, 50))

    assert [item["text"] for item in result] == ["1  年以内"]
    assert result[0]["span_ref"] == "S7"
