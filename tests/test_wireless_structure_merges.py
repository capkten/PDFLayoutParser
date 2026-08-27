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


def test_merge_multiline_cells_requires_continuous_same_column_evidence():
    first = _cell("项目", flow=1, row=1, y0=10, y1=20, source_line=1)
    second = _cell("续写", flow=2, row=2, y0=22, y1=32, source_line=2)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert len(result) == 1
    assert result[0]["text"] == "项目\n续写"
    assert result[0]["row_end"] == 2
    assert result[0]["rowspan"] == 2


def test_merge_multiline_cells_keeps_independent_project_rows_separate():
    first = _cell("项目一", flow=1, row=1, y0=10, y1=20)
    second = _cell("项目二", flow=3, row=2, y0=22, y1=32)

    result = merge_multiline_cells([first, second], header_cutoff=None)

    assert [item["text"] for item in result] == ["项目一", "项目二"]
