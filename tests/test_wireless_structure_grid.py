from hexai_pdf_parser.tables.wireless_structure.grid import build_grid
from hexai_pdf_parser.tables.wireless_structure.logical_grid import build_logical_grid


def _candidate(text, x0, y0, column_id, flow):
    return {
        "cell_id": f"T{flow}",
        "text": text,
        "bbox": [x0, y0, x0 + 20, y0 + 10],
        "column_id": column_id,
        "flow_start": flow,
        "flow_end": flow,
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
