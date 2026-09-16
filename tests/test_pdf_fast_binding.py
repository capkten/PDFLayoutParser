from hexai_pdf_parser.rust_adapter import merge_h_lines


def test_merge_h_lines_groups_nearby_lines_and_merges_segments():
    assert merge_h_lines(
        [(0, 10, 10, 10), (10.5, 10.2, 20, 10.2)], 0.3
    ) == [(0, 10.1, 20, 10.1)]


def test_merge_h_lines_keeps_segments_separated_by_more_than_three_points():
    assert merge_h_lines(
        [(0, 10, 10, 10), (14, 10, 20, 10)], 0.3
    ) == [(0, 10, 10, 10), (14, 10, 20, 10)]


def test_merge_h_lines_returns_empty_for_empty_input():
    assert merge_h_lines([], 0.3) == []


def test_merge_h_lines_uses_python_decimal_rounding_for_sort_keys():
    assert merge_h_lines(
        [(10, 1.15, 11, 1.15), (0, 1.2, 1, 1.2)], 0.0
    ) == [(10, 1.15, 11, 1.15), (0, 1.2, 1, 1.2)]


def test_merge_h_lines_preserves_python_half_value_sort_order():
    assert round(2.25, 1) == 2.2
    assert merge_h_lines(
        [(10.0, 2.25, 11.0, 2.25), (0.0, 2.3, 1.0, 2.3)], 0.0
    ) == [(10.0, 2.25, 11.0, 2.25), (0.0, 2.3, 1.0, 2.3)]


def test_merge_h_lines_preserves_input_order_when_rounded_y_is_nan():
    import math

    output = merge_h_lines(
        [(10.0, float("nan"), 11.0, float("nan")), (0.0, 1.2, 1.0, 1.2)],
        0.0,
    )

    assert len(output) == 2
    assert output[0][0] == 10.0
    assert math.isnan(output[0][1])
    assert output[1][0] == 0.0
    assert output[1][1] == 1.2
