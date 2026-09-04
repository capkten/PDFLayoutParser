from hexai_pdf_parser.tables.wireless_structure.grid import build_grid
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure import logical_grid
from hexai_pdf_parser.tables.wireless_structure.logical_grid import build_logical_grid
from hexai_pdf_parser.tables.wireless_structure.recoverer import _has_occupancy_conflict


def _candidate(text, x0, y0, column_id, flow):
    return {
        "cell_id": f"T{flow}",
        "text": text,
        "bbox": [x0, y0, x0 + 20, y0 + 10],
        "column_id": column_id,
        "flow_start": flow,
        "flow_end": flow,
    }


def _logical_cell(cell_id, text, row, col_start, col_end=None, *, y=10):
    col_end = col_start if col_end is None else col_end
    return {
        "cell_id": cell_id,
        "text": text,
        "bbox": [col_start * 20, y, (col_end + 1) * 20, y + 8],
        "row_start": row,
        "row_end": row,
        "col_start": col_start,
        "col_end": col_end,
        "rowspan": 1,
        "colspan": col_end - col_start + 1,
    }


def test_build_grid_assigns_tall_text_by_vertical_center():
    candidates = [_candidate("项目", 10, 10, 1, 1), _candidate("金额", 100, 45, 2, 2)]
    candidates[0]["bbox"] = [10, 10, 30, 40]
    bands = [{"id": 1, "x0": 10, "x1": 30}, {"id": 2, "x0": 100, "x1": 120}]

    rows, columns, cells, issues = build_grid(candidates, bands)

    assert not issues
    assert len(rows) == 2
    assert [cell["col_start"] for cell in cells] == [1, 2]


def test_build_grid_reports_duplicate_occupancy():
    candidates = [_candidate("甲", 10, 10, 1, 1), _candidate("乙", 10, 10, 1, 2)]
    bands = [{"id": 1, "x0": 10, "x1": 30}]

    _, _, _, issues = build_grid(candidates, bands)

    assert issues == ["R1C1 conflict: T1/T2"]


def test_build_logical_grid_compresses_rows_covered_by_rowspan():
    physical_rows = [{"id": 1, "y": 10}, {"id": 2, "y": 20}, {"id": 3, "y": 30}]
    columns = [{"id": 1, "x0": 10, "x1": 30}]
    cells = [
        {"cell_id": "T1", "text": "合并", "bbox": [10, 10, 30, 25], "row_start": 1, "row_end": 2, "col_start": 1, "col_end": 1, "rowspan": 2, "colspan": 1},
        {"cell_id": "T2", "text": "末行", "bbox": [10, 30, 30, 40], "row_start": 3, "row_end": 3, "col_start": 1, "col_end": 1, "rowspan": 1, "colspan": 1},
    ]

    rows, _, logical_cells = build_logical_grid(physical_rows, columns, cells)

    assert [row["source_rows"] for row in rows] == [[1, 2], [3]]
    assert logical_cells[0]["source_row_start"] == 1
    assert logical_cells[0]["source_row_end"] == 2
    assert logical_cells[0]["row_start"] == 1
    assert logical_cells[0]["row_end"] == 1
    assert logical_cells[0]["rowspan"] == 1


def test_build_logical_grid_groups_rows_inside_a_multiline_first_column_record():
    physical_rows = [{"id": row, "y": row * 10} for row in range(1, 6)]
    columns = [{"id": column, "x0": column * 20, "x1": column * 20 + 10} for column in range(1, 4)]
    cells = [
        _logical_cell("HEADER", "表头", 1, 1, 3, y=10),
        {
            **_logical_cell("NAME", "FRASERS PROPERTY\nTHAILAND INDUSTRIAL\nFREEHOLD", 2, 1, y=20),
            "row_end": 4,
            "rowspan": 3,
        },
        _logical_cell("TYPE", "押金及保证金", 3, 2, y=30),
        _logical_cell("AMOUNT", "1,637,322.45", 4, 3, y=40),
        _logical_cell("NEXT", "下一单位", 5, 1, y=50),
    ]

    rows, _, logical_cells = build_logical_grid(physical_rows, columns, cells)

    assert [row["source_rows"] for row in rows] == [[1], [2, 3, 4], [5]]
    name = next(cell for cell in logical_cells if cell["cell_id"] == "NAME")
    assert (name["row_start"], name["row_end"], name["rowspan"]) == (2, 2, 1)


def test_build_logical_grid_redivides_chained_multiline_header_rows():
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 30},
        {"id": 4, "y": 40},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 7)
    ]
    cells = [
        _logical_cell("TITLE", "期末余额", 1, 1, 6, y=10),
        _logical_cell("P2", "账面余额", 2, 2, y=20),
        _logical_cell("L2", "金额", 3, 2, y=30),
        _logical_cell("P4", "坏账准备", 2, 4, y=20),
        _logical_cell("L4", "金额", 3, 4, y=30),
        {
            **_logical_cell("V6", "账面\n价值", 2, 6, y=20),
            "row_end": 3,
            "rowspan": 2,
        },
        {
            **_logical_cell("R5", "预期信用损失\n率(%)", 3, 5, y=30),
            "row_end": 4,
            "rowspan": 2,
        },
    ]

    rows, _, logical_cells = build_logical_grid(physical_rows, columns, cells)

    assert [row["source_rows"] for row in rows] == [[1], [2], [3, 4]]
    assert _has_occupancy_conflict(logical_cells) is False
    book_value = next(cell for cell in logical_cells if cell["cell_id"] == "V6")
    loss_rate = next(cell for cell in logical_cells if cell["cell_id"] == "R5")
    assert (book_value["row_start"], book_value["row_end"], book_value["rowspan"]) == (2, 3, 2)
    assert (loss_rate["row_start"], loss_rate["row_end"], loss_rate["rowspan"]) == (3, 3, 1)


def test_build_logical_grid_collapses_wrapped_leaf_header_row():
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 30},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 6)
    ]
    cells = [
        {
            **_logical_cell(
                "H3",
                "未来12个月\n内的预期信用损失率(%)",
                1,
                3,
                y=10,
            ),
            "row_end": 2,
            "rowspan": 2,
            "merge_kind": "multiline_cell",
        },
        _logical_cell("H1", "类别", 2, 1, y=20),
        _logical_cell("H2", "账面余额", 2, 2, y=20),
        _logical_cell("H4", "坏账准备", 2, 4, y=20),
        _logical_cell("H5", "账面价值", 2, 5, y=20),
        *[_logical_cell(f"B{column}", f"正文{column}", 3, column, y=30) for column in range(1, 6)],
    ]

    rows, _, logical_cells = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=25,
    )

    assert [row["source_rows"] for row in rows] == [[1, 2], [3]]
    header = [cell for cell in logical_cells if cell["text"].startswith(("类别", "账面余额", "未来", "坏账准备", "账面价值"))]
    assert all((cell["row_start"], cell["row_end"], cell["rowspan"]) == (1, 1, 1) for cell in header)

    materialized = logical_grid.materialize_empty_cells(
        rows,
        physical_rows,
        columns,
        logical_cells,
        BBox(0, 0, 120, 40),
    )
    assert not any(cell.get("merge_kind") == "empty_slot" and cell["row_start"] == 1 for cell in materialized)


def test_build_logical_grid_collapses_wrapped_leaf_header_spanning_three_physical_rows():
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 30},
        {"id": 4, "y": 50},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 6)
    ]
    cells = [
        {
            **_logical_cell(
                "H3",
                "第一行\n第二行\n第三行",
                1,
                3,
                y=10,
            ),
            "row_end": 3,
            "rowspan": 3,
            "merge_kind": "multiline_cell",
            "bbox": [50, 10, 70, 38],
        },
        _logical_cell("H1", "类别", 3, 1, y=30),
        _logical_cell("H2", "账面余额", 3, 2, y=30),
        _logical_cell("H4", "坏账准备", 3, 4, y=30),
        _logical_cell("H5", "账面价值", 3, 5, y=30),
        *[_logical_cell(f"B{column}", f"正文{column}", 4, column, y=50) for column in range(1, 6)],
    ]

    rows, _, logical_cells = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=40,
    )

    assert [row["source_rows"] for row in rows] == [[1, 2, 3], [4]]
    header = [
        cell
        for cell in logical_cells
        if cell["cell_id"].startswith("H")
    ]
    assert all(
        (cell["row_start"], cell["row_end"], cell["rowspan"]) == (1, 1, 1)
        for cell in header
    )

    materialized = logical_grid.materialize_empty_cells(
        rows,
        physical_rows,
        columns,
        logical_cells,
        BBox(0, 0, 120, 60),
    )
    assert not any(
        cell.get("merge_kind") == "empty_slot" and cell["row_start"] == 1
        for cell in materialized
    )


def test_build_logical_grid_keeps_wrapped_leaf_below_a_real_parent_header():
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 30},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 5)
    ]
    cells = [
        {
            **_logical_cell("H1", "账面\n价值", 1, 1, y=10),
            "row_end": 2,
            "rowspan": 2,
            "merge_kind": "multiline_cell",
        },
        _logical_cell("P", "年度", 1, 2, 4, y=10),
        _logical_cell("L2", "金额", 2, 2, y=20),
        _logical_cell("L3", "坏账准备", 2, 3, y=20),
        _logical_cell("L4", "账面余额", 2, 4, y=20),
        *[_logical_cell(f"B{column}", f"正文{column}", 3, column, y=30) for column in range(1, 5)],
    ]

    rows, _, logical_cells = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=25,
    )

    assert [row["source_rows"] for row in rows] == [[1], [2], [3]]
    header = next(cell for cell in logical_cells if cell["cell_id"] == "H1")
    assert (header["row_start"], header["row_end"], header["rowspan"]) == (1, 2, 2)


def test_build_logical_grid_collapses_mixed_leaf_headers_under_proven_two_column_parent():
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 30},
        {"id": 4, "y": 40},
        {"id": 5, "y": 50},
        {"id": 6, "y": 70},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 8)
    ]
    cells = [
        _logical_cell("PARENT", "分组表头", 1, 5, 6, y=10),
        {
            **_logical_cell("LAST", "末列表头", 1, 7, y=10),
            "row_end": 5,
            "rowspan": 5,
            "merge_kind": "multiline_cell",
        },
        *[
            _logical_cell(f"STUB{column}", f"独立表头{column}", 3, column, y=30)
            for column in range(1, 5)
        ],
        _logical_cell("DIRECT", "叶标题甲", 4, 5, y=40),
        {
            **_logical_cell("INDIRECT", "叶\n标题乙", 3, 6, y=30),
            "row_end": 4,
            "rowspan": 2,
            "merge_kind": "multiline_cell",
        },
        *[
            _logical_cell(f"BODY{column}", f"正文{column}", 6, column, y=70)
            for column in range(1, 8)
        ],
    ]

    rows, _, logical_cells = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=55,
    )

    assert [row["source_rows"] for row in rows] == [[1, 2], [3, 4, 5], [6]]

    spanned = logical_grid.merge_header_spans(logical_cells, header_cutoff=55)
    cell_map = {cell["cell_id"]: cell for cell in spanned}
    assert (cell_map["PARENT"]["row_start"], cell_map["PARENT"]["colspan"]) == (1, 2)
    assert cell_map["DIRECT"]["row_start"] == cell_map["INDIRECT"]["row_start"] == 2
    for cell_id in ["STUB1", "STUB2", "STUB3", "STUB4", "LAST"]:
        assert (
            cell_map[cell_id]["row_start"],
            cell_map[cell_id]["row_end"],
            cell_map[cell_id]["rowspan"],
        ) == (1, 2, 2)

    materialized = logical_grid.materialize_empty_cells(
        rows,
        physical_rows,
        columns,
        spanned,
        BBox(0, 0, 180, 80),
    )
    assert not any(
        cell.get("merge_kind") == "empty_slot" and cell["row_start"] <= 2
        for cell in materialized
    )
    assert _has_occupancy_conflict(materialized) is False


def test_build_logical_grid_keeps_mixed_leaf_rows_when_two_column_parent_is_incomplete():
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 30},
        {"id": 4, "y": 40},
        {"id": 5, "y": 50},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 7)
    ]
    cells = [
        _logical_cell("PARENT", "分组表头", 1, 5, 6, y=10),
        _logical_cell("STUB_START", "独立表头", 3, 1, y=30),
        {
            **_logical_cell("WRAPPED", "叶\n标题", 3, 6, y=30),
            "row_end": 4,
            "rowspan": 2,
            "merge_kind": "multiline_cell",
        },
        _logical_cell("STUB_END", "另一层标题", 4, 2, y=40),
        _logical_cell("BODY", "正文", 5, 1, y=50),
    ]

    rows, _, _ = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=45,
    )

    assert [row["source_rows"] for row in rows] == [[1, 2], [3], [4], [5]]


def test_materialize_empty_cells_fills_every_unoccupied_logical_slot():
    logical_rows = [{"id": 1, "source_rows": [1]}, {"id": 2, "source_rows": [2]}]
    physical_rows = [{"id": 1, "y": 10}, {"id": 2, "y": 30}]
    columns = [
        {"id": 1, "x0": 10, "x1": 20},
        {"id": 2, "x0": 40, "x1": 50},
        {"id": 3, "x0": 70, "x1": 80},
    ]
    cells = [
        {
            "cell_id": "T1",
            "text": "金额",
            "bbox": [40, 5, 50, 15],
            "row_start": 1,
            "row_end": 1,
            "col_start": 2,
            "col_end": 2,
            "rowspan": 1,
            "colspan": 1,
        }
    ]

    result = logical_grid.materialize_empty_cells(
        logical_rows, physical_rows, columns, cells, BBox(0, 0, 90, 40)
    )

    assert len(result) == 6
    assert {(cell["row_start"], cell["col_start"]) for cell in result} == {
        (1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)
    }
    empty = next(cell for cell in result if cell["row_start"] == 1 and cell["col_start"] == 1)
    assert empty["text"] == ""
    assert empty["rowspan"] == empty["colspan"] == 1
    assert empty["bbox"] == [0, 0, 30, 20]


def test_materialize_empty_cells_does_not_fill_existing_colspan_coverage():
    logical_rows = [{"id": 1, "source_rows": [1]}]
    physical_rows = [{"id": 1, "y": 10}]
    columns = [
        {"id": 1, "x0": 10, "x1": 20},
        {"id": 2, "x0": 40, "x1": 50},
        {"id": 3, "x0": 70, "x1": 80},
    ]
    cells = [
        {
            "cell_id": "T1",
            "text": "分组",
            "bbox": [10, 5, 50, 15],
            "row_start": 1,
            "row_end": 1,
            "col_start": 1,
            "col_end": 2,
            "rowspan": 1,
            "colspan": 2,
        }
    ]

    result = logical_grid.materialize_empty_cells(
        logical_rows, physical_rows, columns, cells, BBox(0, 0, 90, 20)
    )

    assert len(result) == 2
    assert [(cell["col_start"], cell["colspan"], cell["text"]) for cell in result] == [
        (1, 2, "分组"),
        (3, 1, ""),
    ]


def test_merge_header_spans_extends_group_parents_and_the_single_stub_column():
    cells = [
        _logical_cell("P1", "年末数", 1, 2, 3, y=10),
        _logical_cell("P2", "年初数", 1, 4, 5, y=10),
        _logical_cell("S1", "项目", 2, 1, y=20),
        _logical_cell("L2", "金额", 3, 2, y=30),
        _logical_cell("L3", "坏账准备", 3, 3, y=30),
        _logical_cell("L4", "金额", 3, 4, y=30),
        _logical_cell("L5", "坏账准备", 3, 5, y=30),
        _logical_cell("B1", "正文", 4, 1, y=50),
    ]

    result = logical_grid.merge_header_spans(cells, header_cutoff=40)

    first_parent = next(cell for cell in result if cell["cell_id"] == "P1")
    stub = next(cell for cell in result if cell["cell_id"] == "S1")
    assert (first_parent["row_start"], first_parent["row_end"], first_parent["rowspan"]) == (1, 2, 2)
    assert (stub["row_start"], stub["row_end"], stub["rowspan"]) == (1, 3, 3)
    assert _has_occupancy_conflict(result) is False


def test_merge_header_spans_keeps_parent_short_when_intermediate_slot_has_text():
    cells = [
        _logical_cell("P1", "父标题", 1, 2, 3, y=10),
        _logical_cell("M2", "中间标题", 2, 2, y=20),
        _logical_cell("L2", "叶一", 3, 2, y=30),
        _logical_cell("L3", "叶二", 3, 3, y=30),
    ]

    result = logical_grid.merge_header_spans(cells, header_cutoff=40)

    parent = next(cell for cell in result if cell["cell_id"] == "P1")
    assert (parent["row_start"], parent["row_end"], parent["rowspan"]) == (1, 1, 1)


def test_merge_header_spans_keeps_stub_short_when_its_column_has_another_header():
    cells = [
        _logical_cell("C1", "上层标题", 1, 1, y=10),
        _logical_cell("P1", "父标题", 1, 2, 3, y=10),
        _logical_cell("S1", "首列表头", 2, 1, y=20),
        _logical_cell("L2", "叶一", 3, 2, y=30),
        _logical_cell("L3", "叶二", 3, 3, y=30),
    ]

    result = logical_grid.merge_header_spans(cells, header_cutoff=40)

    stub = next(cell for cell in result if cell["cell_id"] == "S1")
    assert (stub["row_start"], stub["row_end"], stub["rowspan"]) == (2, 2, 1)


def test_build_grid_separates_column_overlapping_vertical_tiers():
    """存在列重叠且纵向一上一下的候选项，严禁被贪心单链吸附进同一个物理行。"""
    bands = [
        {"id": 1, "x0": 10, "x1": 30},
        {"id": 2, "x0": 40, "x1": 60},
        {"id": 3, "x0": 70, "x1": 90},
    ]
    # PARENT (center=15) -> STUB (center=20, diff=5) -> CHILD (center=25, diff=5)
    # 当 tolerance >= 6 时，无同列冲突防护将链式合并为同一行，产生 R1C2/R1C3 冲突
    candidates = [
        {
            "cell_id": "PARENT",
            "text": "本期增减变动",
            "bbox": [40, 10, 90, 20],
            "column_id": 2,
            "column_start": 2,
            "column_end": 3,
            "colspan": 2,
        },
        {
            "cell_id": "STUB",
            "text": "项目名称",
            "bbox": [10, 11, 30, 29],
            "column_id": 1,
            "column_start": 1,
            "column_end": 1,
            "colspan": 1,
        },
        {
            "cell_id": "CHILD1",
            "text": "追加投资",
            "bbox": [40, 20, 60, 30],
            "column_id": 2,
            "column_start": 2,
            "column_end": 2,
            "colspan": 1,
        },
        {
            "cell_id": "CHILD2",
            "text": "减少投资",
            "bbox": [70, 20, 90, 30],
            "column_id": 3,
            "column_start": 3,
            "column_end": 3,
            "colspan": 1,
        },
    ]

    rows, columns, cells, issues = build_grid(candidates, bands)
    assert not issues, f"Expected no issues, got {issues}"
    cell_map = {c["cell_id"]: c for c in cells}
    assert cell_map["PARENT"]["row_start"] < cell_map["CHILD1"]["row_start"]
    assert cell_map["CHILD1"]["row_start"] == cell_map["CHILD2"]["row_start"]


def test_build_grid_separates_partially_overlapping_column_tiers():
    """部分 y 重叠的跨列父子表头也不能被桥接到同一物理行。"""
    bands = [
        {"id": 1, "x0": 10, "x1": 30},
        {"id": 2, "x0": 40, "x1": 60},
        {"id": 3, "x0": 70, "x1": 90},
    ]
    candidates = [
        {
            "cell_id": "PARENT",
            "text": "本期增减变动",
            "bbox": [40, 10, 90, 22],
            "column_id": 2,
            "column_start": 2,
            "column_end": 3,
            "colspan": 2,
        },
        {
            "cell_id": "STUB",
            "text": "项目名称",
            "bbox": [10, 11, 30, 29],
            "column_id": 1,
            "column_start": 1,
            "column_end": 1,
            "colspan": 1,
        },
        {
            "cell_id": "CHILD1",
            "text": "追加投资",
            "bbox": [40, 18, 60, 30],
            "column_id": 2,
            "column_start": 2,
            "column_end": 2,
            "colspan": 1,
        },
        {
            "cell_id": "CHILD2",
            "text": "减少投资",
            "bbox": [70, 18, 90, 30],
            "column_id": 3,
            "column_start": 3,
            "column_end": 3,
            "colspan": 1,
        },
    ]

    rows, columns, cells, issues = build_grid(candidates, bands)

    assert not issues, f"Expected no issues, got {issues}"
    cell_map = {c["cell_id"]: c for c in cells}
    assert cell_map["PARENT"]["row_start"] < cell_map["CHILD1"]["row_start"]
    assert cell_map["CHILD1"]["row_start"] == cell_map["CHILD2"]["row_start"]


def test_build_grid_keeps_partially_overlapping_boxes_in_one_row_across_columns():
    """不同列的文本框只部分重叠时，仍应识别为同一物理行。"""
    bands = [
        {"id": 1, "x0": 10, "x1": 30},
        {"id": 2, "x0": 40, "x1": 60},
    ]
    candidates = [
        {
            **_candidate("左列", 10, 10, 1, 1),
            "bbox": [10, 10, 30, 22],
        },
        {
            **_candidate("右列", 40, 18, 2, 2),
            "bbox": [40, 18, 60, 30],
        },
    ]

    rows, _, cells, issues = build_grid(candidates, bands)

    assert not issues
    assert len(rows) == 1
    assert {cell["row_start"] for cell in cells} == {1}


def test_build_grid_separates_partially_overlapping_boxes_in_one_column():
    """同列上下两行的文本框部分重叠时，不得仅凭中心距离合并。"""
    bands = [{"id": 1, "x0": 10, "x1": 30}]
    candidates = [
        {
            **_candidate("上一行", 10, 10, 1, 1),
            "bbox": [10, 10, 30, 22],
        },
        {
            **_candidate("下一行", 10, 18, 1, 2),
            "bbox": [10, 18, 30, 30],
        },
    ]

    rows, _, cells, issues = build_grid(candidates, bands)

    assert not issues
    assert len(rows) == 2
    assert [cell["row_start"] for cell in cells] == [1, 2]


def test_build_grid_requires_reciprocal_y_overlap_for_asymmetric_boxes():
    """异常偏高的上框不能因下框被其局部包含而合并到同一行。"""
    bands = [{"id": 1, "x0": 10, "x1": 30}]
    candidates = [
        {
            **_candidate("上方文本块", 10, 10, 1, 1),
            "bbox": [10, 10, 30, 36],
        },
        {
            **_candidate("下方文本块", 10, 30, 1, 2),
            "bbox": [10, 30, 30, 42],
        },
    ]

    rows, _, cells, issues = build_grid(candidates, bands)

    assert not issues
    assert len(rows) == 2
    assert [cell["row_start"] for cell in cells] == [1, 2]
