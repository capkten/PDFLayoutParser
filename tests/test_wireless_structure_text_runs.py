from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs


def _atom(text, x0, x1, order, source_position=(1, 1, 0), *, font_size=10):
    return {
        "text": text,
        "bbox": [x0, 10, x1, 20],
        "order": order,
        "flow": order + 1,
        "source_position": list(source_position),
        "font": "SimSun",
        "font_size": font_size,
        "bold": False,
        "span_ref": f"S{order}",
        "char_boxes": [],
    }


def test_build_text_runs_merges_adjacent_chinese_fragments_on_one_native_line():
    atoms = [_atom("1", 10, 14, 1, (2, 3, 0)), _atom("\u5e74\u4ee5\u5185", 14, 38, 2, (2, 3, 1))]
    result = build_text_runs(atoms)
    assert len(result) == 1
    assert result[0]["text"] == "1\u5e74\u4ee5\u5185"
    assert result[0]["flow_start"] == 2
    assert result[0]["flow_end"] == 3
    assert result[0]["merge_kind"] == "same_line"


def test_build_text_runs_keeps_chinese_label_and_numeric_field_separate():
    atoms = [
        _atom("广东锦龙发展股份有限公司", 95.8, 221.8, 9, (2, 3, 0)),
        _atom("304,623,048.00", 221.8, 314.7, 10, (2, 3, 1)),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == [
        "广东锦龙发展股份有限公司",
        "304,623,048.00",
    ]


def test_build_text_runs_keeps_currency_and_adjacent_numeric_fields_separate():
    atoms = [_atom("$", 10, 16, 1, (2, 3, 0)), _atom("100", 17, 34, 2, (2, 3, 1)), _atom("200", 36, 53, 3, (2, 3, 2))]
    result = build_text_runs(atoms)
    assert [item["text"] for item in result] == ["$", "100", "200"]


def test_build_text_runs_attaches_small_superscript():
    atoms = [_atom("金额", 10, 24, 1, (2, 3, 0)), _atom("1", 24, 27, 2, (2, 3, 1), font_size=7)]
    atoms[1]["bbox"] = [23, 12, 27, 19]
    result = build_text_runs(atoms)
    assert len(result) == 1
    assert result[0]["text"] == "金额1"


def test_build_text_runs_filters_a_wide_separator_line():
    atoms = [_atom("——", 10, 30, 1), _atom("——", 31, 51, 2), _atom("——", 52, 72, 3), _atom("——", 73, 93, 4)]
    result = build_text_runs(atoms)
    assert result == []


def test_build_text_runs_keeps_a_single_dash_body_value():
    result = build_text_runs([_atom("—", 10, 16, 1)])
    assert [item["text"] for item in result] == ["—"]


def test_build_text_runs_filters_separator_text_with_internal_spaces():
    result = build_text_runs([_atom("----  ---------", 10, 90, 1)])

    assert result == []


def test_build_text_runs_filters_long_ascii_equals_rule():
    result = build_text_runs([_atom("=========", 10, 70, 1)])

    assert result == []


def test_build_text_runs_keeps_multiple_short_dash_placeholders():
    atoms = [
        _atom("---", 10, 25, 1, (2, 3, 0)),
        _atom("---", 45, 60, 2, (2, 3, 1)),
        _atom("---", 80, 95, 3, (2, 3, 2)),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["---", "---", "---"]


def test_build_text_runs_does_not_join_placeholder_to_positive_gap_neighbor():
    atoms = [
        _atom("项目", 10, 25, 1, (2, 3, 0)),
        _atom("---", 26, 41, 2, (2, 3, 1)),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["项目", "---"]


def test_build_text_runs_caps_measured_gap_before_separate_headers():
    atoms = []
    for line in range(3):
        atoms.extend(
            [
                _atom("a", 10, 14, line * 2, (line, 0, 0)),
                _atom("b", 26, 30, line * 2 + 1, (line, 0, 1)),
            ]
        )
    atoms.extend(
        [
            _atom("比例", 100, 120, 10, (4, 0, 0)),
            _atom("坏账准备", 131.2, 171.2, 11, (4, 0, 1)),
        ]
    )

    result = build_text_runs(atoms)

    assert [item["text"] for item in result[-2:]] == ["比例", "坏账准备"]
