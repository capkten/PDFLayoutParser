from hexai_pdf_parser.tables.wireless_structure.span_chain import (
    _split_packed_numeric_fields,
)


def _make_span(text: str, char_specs: list[tuple[str, float, float]], font_size: float = 10.56):
    char_boxes = [
        {"text": c, "bbox": [x0, 100.0, x1, 112.0]}
        for c, x0, x1 in char_specs
    ]
    return {
        "text": text,
        "font_size": font_size,
        "source_position": [1, 0, 0],
        "bbox": [char_specs[0][1], 100.0, char_specs[-1][2], 112.0],
        "char_boxes": char_boxes,
    }


def test_split_adjacent_amounts_with_narrow_gap():
    # 模拟 Page 968 递延收益：'452,516,878.89 1,573,970,660.26'
    # '9' 右沿 360.66，' ' 360.55~362.96，'1' 左沿 366.31 (residual gap = 3.352pt, font_size = 10.56pt)
    specs = [
        ("4", 300.67, 305.49), ("5", 305.47, 310.29), ("2", 310.27, 315.09),
        (".", 348.65, 351.06), ("8", 351.05, 355.86), ("9", 355.85, 360.66),
        (" ", 360.55, 362.96),
        ("1", 366.31, 371.13), (",", 371.11, 373.52), ("5", 373.50, 378.32),
        (".", 421.49, 423.89), ("2", 423.88, 428.69), ("6", 428.68, 433.49),
    ]
    span = _make_span("452.89 1,5.26", specs, font_size=10.56)
    fragments = _split_packed_numeric_fields(span)
    assert len(fragments) == 2
    assert fragments[0]["text"] == "452.89"
    assert fragments[1]["text"] == "1,5.26"


def test_split_placeholder_and_amount():
    # 模拟 Page 968 股本表：'- 1,696,964,131.00'
    # '-' 右沿 429.34，' ' 429.34~431.75，'1' 左沿 435.10 (gap = 3.352pt)
    specs = [
        ("-", 426.46, 429.34),
        (" ", 429.34, 431.75),
        ("1", 435.10, 439.92), (",", 439.90, 442.31), ("6", 442.29, 447.11),
    ]
    span = _make_span("- 1,6", specs, font_size=10.56)
    fragments = _split_packed_numeric_fields(span)
    assert len(fragments) == 2
    assert fragments[0]["text"] == "-"
    assert fragments[1]["text"] == "1,6"


def test_keep_single_number_without_space_intact():
    specs = [
        ("1", 10.0, 15.0), ("0", 15.0, 20.0), ("0", 20.0, 25.0)
    ]
    span = _make_span("100", specs, font_size=10.56)
    fragments = _split_packed_numeric_fields(span)
    assert len(fragments) == 1
    assert fragments[0]["text"] == "100"


def test_packed_numeric_field_ignores_cjk_embedded_numbers():
    # 含有中文字符的，正则白名单直接跳过
    span = {
        "text": "未来12个月",
        "font_size": 10.56,
        "char_boxes": [],
        "bbox": [10.0, 10.0, 50.0, 20.0],
    }
    fragments = _split_packed_numeric_fields(span)
    assert len(fragments) == 1
    assert fragments[0]["text"] == "未来12个月"
