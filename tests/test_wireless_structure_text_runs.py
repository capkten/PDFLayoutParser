from hexai_pdf_parser.tables.wireless_structure.text_runs import (
    build_text_runs,
    merge_same_band_native_line_runs,
)


def _atom(
    text,
    x0,
    x1,
    order,
    source_position=(1, 1, 0),
    *,
    font_size=10,
    y=10,
):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 10],
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


def test_build_text_runs_merges_native_continuous_wrapped_fields_before_grid():
    atoms = [
        _atom("企业名称", 100, 142, 0, (0, 0, 80), y=18.5),
        _atom("注册", 168, 189, 1, (0, 0, 81), y=10),
        _atom("地址", 168, 189, 2, (0, 0, 82), y=27),
        _atom("主营业务", 220, 262, 3, (0, 0, 83), y=18.5),
        _atom("与本公司", 289, 331, 4, (0, 0, 84), y=10),
        _atom("关系", 299.5, 320.5, 5, (0, 0, 85), y=27),
        _atom("业务", 339, 360, 6, (0, 0, 86), y=10),
        _atom("性质", 339, 360, 7, (0, 0, 87), y=27),
        _atom("法定", 379, 400, 8, (0, 0, 88), y=10),
        _atom("代表人", 374, 405.5, 9, (0, 0, 89), y=27),
        _atom("组织机构代码", 422, 485, 10, (0, 0, 90), y=18.5),
        _atom("杨志茂", 92, 124, 11, (0, 0, 91), y=70),
        _atom("本公司实", 289, 331, 12, (0, 0, 92), y=61.5),
        _atom("际控制人", 289, 331, 13, (0, 0, 93), y=78.5),
        _atom("---", 382, 403, 14, (0, 0, 94), y=70),
    ]

    result = build_text_runs(atoms)
    by_text = {item["text"]: item for item in result}

    assert {
        "注册\n地址",
        "与本公司\n关系",
        "业务\n性质",
        "法定\n代表人",
        "本公司实\n际控制人",
    } <= set(by_text)
    assert by_text["注册\n地址"]["bbox"] == [168, 10, 189, 37]
    assert by_text["注册\n地址"]["flow_start"] == 2
    assert by_text["注册\n地址"]["flow_end"] == 3
    assert by_text["注册\n地址"]["span_refs"] == ["S1", "S2"]
    assert by_text["注册\n地址"]["merge_kind"] == "wrapped_field"


def test_build_text_runs_keeps_close_native_continuous_rows_without_interleaving_evidence():
    atoms = [
        _atom("第一条", 100, 142, 0, (0, 0, 10), y=10),
        _atom("第二条", 100, 142, 1, (0, 0, 11), y=27),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["第一条", "第二条"]


def test_build_text_runs_keeps_vertically_overlapping_fields_separate():
    atoms = [
        _atom("字段甲", 100, 142, 0, (0, 0, 10), y=10),
        _atom("字段乙", 100, 142, 1, (0, 0, 11), y=14),
        _atom("中间列", 220, 262, 2, (0, 0, 12), y=12),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["字段甲", "字段乙", "中间列"]


def test_build_text_runs_merges_consecutive_vertical_blocks_with_right_witness():
    atoms = [
        _atom("上半字段", 100, 160, 0, (1, 2, 0), y=10),
        _atom("下半字段", 100, 160, 1, (2, 0, 0), y=24),
        _atom("右侧字段", 240, 300, 2, (3, 0, 0), y=17),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == [
        "上半字段\n下半字段",
        "右侧字段",
    ]
    assert result[0]["flow_start"] == 1
    assert result[0]["flow_end"] == 2
    assert result[0]["span_refs"] == ["S0", "S1"]
    assert result[0]["source_blocks"] == [1, 2]
    assert result[0]["merge_kind"] == "wrapped_field"


def test_build_text_runs_merges_three_line_flow_chain_with_right_witness():
    atoms = [
        _atom("第一行", 100, 160, 0, (1, 0, 0), y=10),
        _atom("第二行", 100, 160, 1, (2, 0, 0), y=24),
        _atom("第三行", 120, 160, 2, (3, 0, 0), y=38),
        _atom("右侧字段", 240, 300, 3, (4, 0, 0), y=24),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == [
        "第一行\n第二行\n第三行",
        "右侧字段",
    ]
    assert result[0]["flow_start"] == 1
    assert result[0]["flow_end"] == 3
    assert result[0]["span_refs"] == ["S0", "S1", "S2"]


def test_build_text_runs_keeps_consecutive_amount_rows_separate_with_right_witness():
    atoms = [
        _atom("100.00", 100, 150, 0, (1, 0, 0), y=10),
        _atom("200.00", 100, 150, 1, (2, 0, 0), y=24),
        _atom("右侧", 240, 280, 2, (3, 0, 0), y=17),
    ]

    assert [item["text"] for item in build_text_runs(atoms)] == [
        "100.00",
        "200.00",
        "右侧",
    ]


def test_build_text_runs_requires_strict_flow_continuity_for_wrapped_blocks():
    atoms = [
        _atom("上半字段", 100, 160, 0, (1, 0, 0), y=10),
        _atom("跳过字段", 20, 70, 1, (2, 0, 0), y=50),
        _atom("下半字段", 100, 160, 2, (3, 0, 0), y=24),
        _atom("右侧字段", 240, 300, 3, (4, 0, 0), y=17),
    ]

    assert "上半字段\n下半字段" not in {
        item["text"] for item in build_text_runs(atoms)
    }


def test_build_text_runs_keeps_two_rows_when_right_side_has_independent_peers():
    atoms = [
        _atom("左一", 100, 140, 0, (1, 0, 0), y=10),
        _atom("右一", 240, 280, 1, (2, 0, 0), y=10),
        _atom("左二", 100, 140, 2, (3, 0, 0), y=24),
        _atom("右二", 240, 280, 3, (4, 0, 0), y=24),
    ]

    assert [item["text"] for item in build_text_runs(atoms)] == [
        "左一",
        "右一",
        "左二",
        "右二",
    ]


def test_build_text_runs_merges_spaced_single_cjk_on_one_native_line():
    atoms = [
        _atom("项", 71.1, 81.6, 0, (1, 0, 0), y=10),
        _atom("目", 92.2, 102.7, 1, (1, 0, 1), y=10),
        _atom("中间列", 220, 280, 2, (2, 0, 0), y=10),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["项目", "中间列"]
    assert result[0]["span_refs"] == ["S0", "S1"]


def test_build_text_runs_keeps_widely_spaced_single_cjk_fields_separate():
    atoms = [
        _atom("年", 10, 20, 0, (1, 0, 0), y=10),
        _atom("月", 39, 49, 1, (1, 0, 1), y=10),
        _atom("金额", 100, 130, 2, (2, 0, 0), y=10),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["年", "月", "金额"]


def test_merge_same_band_native_line_runs_joins_wide_spaced_latin_fragments():
    atoms = build_text_runs(
        [
            _atom("FRASERS", 10, 50, 0, (1, 1, 0), font_size=10),
            _atom("PROPERTY", 84, 140, 1, (1, 1, 1), font_size=10),
        ]
    )

    result = merge_same_band_native_line_runs(
        atoms,
        [{"id": 1, "x0": 0, "x1": 150}],
    )

    assert [item["text"] for item in result] == ["FRASERS PROPERTY"]
    assert result[0]["merge_kind"] == "same_band_native_line"


def test_merge_same_band_native_line_runs_keeps_fragments_in_distinct_bands():
    atoms = build_text_runs(
        [
            _atom("FRASERS", 10, 50, 0, (1, 1, 0), font_size=10),
            _atom("PROPERTY", 84, 140, 1, (1, 1, 1), font_size=10),
        ]
    )

    result = merge_same_band_native_line_runs(
        atoms,
        [
            {"id": 1, "x0": 0, "x1": 70},
            {"id": 2, "x0": 70, "x1": 150},
        ],
    )

    assert [item["text"] for item in result] == ["FRASERS", "PROPERTY"]
