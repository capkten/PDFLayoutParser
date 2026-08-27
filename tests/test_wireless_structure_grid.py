from hexai_pdf_parser.tables.wireless_structure.grid import build_grid
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure import logical_grid
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
    assert logical_cells[0]["row_end"] == 1
    assert logical_cells[0]["rowspan"] == 1


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
