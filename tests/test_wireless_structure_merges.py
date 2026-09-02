from hexai_pdf_parser.tables.wireless_structure.continuations import merge_column_continuations
from hexai_pdf_parser.tables.wireless_structure.merged_cells import (
    merge_multiline_cells,
    merge_same_slot_fragments,
)


def _cell(text, *, flow, row, col=1, x0=10, y0=10, x1=40, y1=20, source_line=1):
    return {
        "candidate_label": f"T{flow}",
        "cell_id": f"T{flow}",
        "text": text,
        "bbox": [x0, y0, x1, y1],
        "flow_start": flow,
        "flow_end": flow,
        "span_refs": [f"S{flow}"],
        "source_blocks": [1],
        "source_line_start": source_line,
        "source_line_end": source_line,
        "source_position_known": True,
        "font_size": 10,
        "bold": False,
        "script": "cjk",
        "row_start": row,
        "row_end": row,
        "col_start": col,
        "col_end": col,
        "column_id": col,
        "rowspan": 1,
        "colspan": 1,
    }


def test_merge_column_continuations_materializes_only_assigned_atoms_in_flow_order():
    atoms = [_cell("项目", flow=2, row=1), _cell("金额", flow=1, row=1, col=2)]

    result = merge_column_continuations(atoms, [{"id": 1}, {"id": 2}])

    assert [item["cell_id"] for item in result] == ["T1", "T2"]
    assert [item["candidate_label"] for item in result] == ["T1", "T2"]


def test_merge_same_slot_fragments_joins_native_inline_chinese_fragments():
    left = _cell("金额", flow=1, row=1, x0=10, x1=25)
    right = _cell("合计", flow=2, row=1, x0=25, x1=40, source_line=1)

    result = merge_same_slot_fragments([left, right], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "金额合计"
    assert result[0]["span_refs"] == ["S1", "S2"]


def test_merge_same_slot_fragments_joins_same_visual_line_from_split_native_lines():
    left = _cell("FRASERS", flow=1, row=1, x0=10, x1=25, source_line=0)
    right = _cell("PROPERTY", flow=2, row=1, x0=25, x1=40, source_line=1)

    result = merge_same_slot_fragments([left, right], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "FRASERSPROPERTY"


def test_merge_same_slot_fragments_joins_right_side_numbered_prefix():
    marker = _cell(
        "2.", flow=1, row=1, x0=10, y0=20, x1=15, y1=30, source_line=0
    )
    body = _cell(
        "权益法下的其他综合收益",
        flow=2,
        row=1,
        x0=18,
        y0=16,
        x1=90,
        y1=26,
        source_line=0,
    )
    marker["font_size"] = body["font_size"] = 6.72

    result = merge_same_slot_fragments([marker, body], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "2.权益法下的其他综合收益"
    assert result[0]["merge_kind"] == "same_slot_horizontal_prefix"


def test_merge_same_slot_fragments_keeps_right_side_prefix_in_different_column():
    marker = _cell(
        "2.", flow=1, row=1, col=1, x0=10, y0=20, x1=15, y1=30, source_line=0
    )
    body = _cell(
        "金额",
        flow=2,
        row=1,
        col=2,
        x0=18,
        y0=16,
        x1=40,
        y1=26,
        source_line=0,
    )

    result = merge_same_slot_fragments([marker, body], header_cutoff=None)

    assert [item["text"] for item in result] == ["2.", "金额"]


def test_merge_same_slot_fragments_joins_numbered_marker_with_right_ellipsis():
    marker = _cell(
        "3.", flow=1, row=1, x0=10, y0=20, x1=15, y1=30, source_line=0
    )
    ellipsis = _cell(
        "……",
        flow=2,
        row=1,
        x0=18,
        y0=20,
        x1=30,
        y1=30,
        source_line=0,
    )
    marker["font_size"] = ellipsis["font_size"] = 6.72

    result = merge_same_slot_fragments([marker, ellipsis], header_cutoff=None)

    assert [item["text"] for item in result] == ["3.……"]


def test_merge_multiline_cells_requires_continuous_same_column_evidence():
    first = _cell("项目", flow=1, row=1, y0=10, y1=20, source_line=1)
    second = _cell("续写", flow=2, row=2, y0=22, y1=32, source_line=2)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "项目\n续写"
    assert result[0]["row_end"] == 2
    assert result[0]["rowspan"] == 2


def test_merge_multiline_cells_columnar_keeps_different_native_blocks_separate():
    first = _cell("项目一", flow=1, row=1, y0=10, y1=20, source_line=1)
    second = _cell("项目二", flow=2, row=2, y0=22, y1=32, source_line=2)
    second["source_blocks"] = [2]

    result = merge_multiline_cells(
        [first, second], header_cutoff=None, output_mode="columnar"
    )

    assert [item["text"] for item in result] == ["项目一", "项目二"]


def test_merge_multiline_cells_columnar_accepts_adjacent_lines_from_one_block():
    first = _cell("项目", flow=1, row=1, y0=10, y1=20, source_line=1)
    second = _cell("续写", flow=2, row=2, y0=22, y1=32, source_line=2)

    result = merge_multiline_cells(
        [first, second], header_cutoff=None, output_mode="columnar"
    )

    assert len(result) == 1
    assert result[0]["text"] == "项目\n续写"


def test_merge_multiline_cells_accepts_vertical_fragments_in_same_physical_row():
    first = _cell("坏账准备", flow=1, row=1, y0=10, y1=20)
    second = _cell("期末余额", flow=2, row=1, y0=21, y1=31)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "坏账准备\n期末余额"
    assert result[0]["row_start"] == result[0]["row_end"] == 1
    assert result[0]["rowspan"] == 1


def test_merge_multiline_cells_accepts_left_shifted_single_cjk_continuation():
    first = _cell(
        "一年内到期的非流动资",
        flow=1,
        row=1,
        x0=18,
        y0=10,
        x1=90,
        y1=20,
        source_line=1,
    )
    second = _cell(
        "产",
        flow=2,
        row=1,
        x0=10,
        y0=22,
        x1=20,
        y1=32,
        source_line=2,
    )

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "一年内到期的非流动资\n产"


def test_merge_multiline_cells_accepts_multi_char_left_shifted_continuation():
    first = _cell(
        "长期应收款-融资租赁",
        flow=1,
        row=1,
        x0=30,
        y0=10,
        x1=90,
        y1=20,
        source_line=1,
    )
    second = _cell(
        "保证金",
        flow=2,
        row=2,
        x0=15,
        y0=22,
        x1=28,
        y1=32,
        source_line=2,
    )

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "长期应收款-融资租赁\n保证金"


def test_merge_multiline_cells_keeps_left_shifted_independent_label_separate():
    first = _cell("项目明细", flow=1, row=1, x0=40, y0=10, x1=70, y1=20)
    second = _cell("金额", flow=2, row=1, x0=10, y0=22, x1=30, y1=32, source_line=2)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert [item["text"] for item in result] == ["项目明细", "金额"]


def test_merge_multiline_cells_requires_candidate_to_be_below_previous_fragment():
    first = _cell("上方片段", flow=1, row=1, y0=21, y1=31)
    second = _cell("下方片段", flow=2, row=1, y0=10, y1=20)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert [item["text"] for item in result] == ["上方片段", "下方片段"]


def test_merge_multiline_cells_keeps_next_numbered_item_separate():
    first = _cell("2.权益法下的其他综合收益", flow=1, row=1, y0=10, y1=20)
    second = _cell("3.……", flow=2, row=2, y0=22, y1=32)
    second["script"] = "numeric"

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert [item["text"] for item in result] == [
        "2.权益法下的其他综合收益",
        "3.……",
    ]


def test_merge_multiline_cells_keeps_independent_project_rows_separate():
    first = _cell("项目一", flow=1, row=1, y0=10, y1=20)
    second = _cell("项目二", flow=3, row=2, y0=22, y1=32)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert [item["text"] for item in result] == ["项目一", "项目二"]


def test_merge_multiline_cells_accepts_one_font_size_vertical_gap():
    first = _cell("单项金额不重大但按", flow=1, row=1, y0=10, y1=20, source_line=1)
    second = _cell("信用风险特征组合后", flow=2, row=2, y0=29.48, y1=39.48, source_line=2)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "单项金额不重大但按\n信用风险特征组合后"


def test_merge_same_slot_fragments_joins_wide_spaced_single_cjk_pair():
    left = _cell("合", flow=1, row=1, x0=10, x1=20)
    right = _cell("计", flow=2, row=1, x0=41, x1=51, source_line=1)

    result = merge_same_slot_fragments([left, right], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "合计"


def test_merge_same_slot_fragments_does_not_join_wide_multi_character_labels():
    left = _cell("比例", flow=1, row=1, x0=10, x1=20)
    right = _cell("坏账准备", flow=2, row=1, x0=41, x1=71, source_line=1)

    result = merge_same_slot_fragments([left, right], header_cutoff=None)

    assert [item["text"] for item in result] == ["比例", "坏账准备"]


def test_merge_same_slot_fragments_joins_two_character_spread_cjk_pair():
    left = _cell("目", flow=1, row=1, x0=250.7, x1=264.7)
    right = _cell("录", flow=2, row=1, x0=299.8, x1=313.8, source_line=1)
    left["font_size"] = right["font_size"] = 14.05

    result = merge_same_slot_fragments([left, right], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "目录"

