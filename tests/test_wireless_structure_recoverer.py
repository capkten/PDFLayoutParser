from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan
from hexai_pdf_parser.tables.wireless_structure import recoverer
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region
from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs


def test_recover_cells_from_region_converts_new_pipeline_to_project_cells(monkeypatch):
    region = BBox(0, 0, 160, 70)
    spans = [
        NativeSpan(text, BBox(x0, y, x0 + 20, y + 10), "SimSun", 10, order)
        for order, (y, x0, text) in enumerate(
            [
                (10, 10, "项目"),
                (10, 100, "金额"),
                (30, 10, "甲"),
                (30, 100, "10"),
                (50, 10, "乙"),
                (50, 100, "20"),
            ]
        )
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns) == (3, 2)
    assert {(cell.row_index, cell.col_index, cell.text) for cell in cells} == {
        (0, 0, "项目"),
        (0, 1, "金额"),
        (1, 0, "甲"),
        (1, 1, "10"),
        (2, 0, "乙"),
        (2, 1, "20"),
    }


def test_table_header_gap_above_normal_gap_is_not_joined():
    def atom(text, x0, x1, order, line):
        return {
            "text": text,
            "bbox": [x0, line * 20, x1, line * 20 + 10],
            "order": order,
            "flow": order + 1,
            "source_position": [line, 0, order],
            "font": "SimSun",
            "font_size": 10,
            "bold": False,
            "span_ref": f"S{order}",
            "char_boxes": [],
        }

    atoms = [
        atom("a", 10, 14, 1, 0),
        atom("b", 22.5, 26.5, 2, 0),
        atom("c", 35, 39, 3, 0),
        atom("d", 47.5, 51.5, 4, 0),
        atom("比例", 10, 20, 5, 1),
        atom("坏账准备", 32, 52, 6, 1),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result[-2:]] == ["比例", "坏账准备"]


def test_final_occupancy_rejects_unresolved_duplicate_slot():
    duplicate_cells = [
        {"cell_id": "T1", "row_start": 1, "row_end": 1, "col_start": 1, "col_end": 1},
        {"cell_id": "T2", "row_start": 1, "row_end": 1, "col_start": 1, "col_end": 1},
    ]

    assert recoverer._has_occupancy_conflict(duplicate_cells) is True


def test_recover_cells_from_region_materializes_missing_empty_slot(monkeypatch):
    region = BBox(0, 0, 160, 70)
    spans = [
        NativeSpan(text, BBox(x0, y, x0 + 20, y + 10), "SimSun", 10, order)
        for order, (y, x0, text) in enumerate(
            [
                (10, 10, "项目"),
                (10, 100, "金额"),
                (30, 10, "甲"),
                (30, 100, "10"),
                (50, 10, "乙"),
            ]
        )
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns, len(cells)) == (3, 2, 6)
    empty = next(cell for cell in cells if cell.row_index == 2 and cell.col_index == 1)
    assert empty.text == ""
    assert empty.rowspan == empty.colspan == 1
