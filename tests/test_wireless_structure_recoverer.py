from pathlib import Path

import fitz
import pytest

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan
from hexai_pdf_parser.tables.wireless_structure import recoverer
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region
from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs


PAGE_437_FIXTURE = Path(__file__).parent / "fixtures" / "page_437_wireless.pdf"


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


def test_page_437_fixture_bottom_table_preserves_first_column_and_record_rows():
    document = fitz.open(str(PAGE_437_FIXTURE))
    try:
        rows, columns, cells = recover_cells_from_region(
            document[0],
            BBox(67.6, 646.8, 522.5, 766.1),
        )
    finally:
        document.close()

    assert (rows, columns) == (3, 6)
    first_record = [cell for cell in cells if cell.row_index == 1]
    assert any(
        "FRASERS" in cell.text
        and "PROPERTY" in cell.text
        and "THAILAND" in cell.text
        and "INDUSTRIAL" in cell.text
        for cell in first_record
    )
    assert any("1,637,322.45" in cell.text for cell in first_record)
    assert any("196,478.69" in cell.text for cell in first_record)


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


def test_recover_cells_rebuilds_after_exact_slot_conflict_merge(monkeypatch):
    region = BBox(100, 260, 505, 385)
    build_grid_calls = 0
    real_build_grid = recoverer.build_grid

    def counting_build_grid(candidates, bands):
        nonlocal build_grid_calls
        build_grid_calls += 1
        return real_build_grid(candidates, bands)

    def candidate(text, flow, x0, x1, y0, column, source_line, source_span=0):
        return {
            "candidate_label": f"T{flow}",
            "cell_id": f"T{flow}",
            "text": text,
            "bbox": [x0, y0, x1, y0 + 10.5],
            "flow_start": flow,
            "flow_end": flow,
            "span_refs": [f"S{flow}"],
            "source_blocks": [14],
            "source_line_start": source_line,
            "source_line_end": source_line,
            "source_position_known": True,
            "font_size": 10.5,
            "bold": False,
            "script": "cjk" if not text.replace(".", "").isdigit() else "numeric",
            "column_id": column,
            "column_start": column,
            "column_end": column,
            "source_position": [14, source_line, source_span],
        }

    atoms = [
        candidate("项目", 1, 110, 150, 275, 1, 0),
        candidate("账面价值", 2, 250, 310, 275, 2, 1),
        candidate("评估价值", 3, 400, 460, 275, 3, 2),
        candidate("清远市新城B30号开发用土地", 4, 110, 230, 315, 1, 3),
        candidate("100.00", 5, 250, 300, 315, 2, 4),
        candidate("120.00", 6, 400, 450, 315, 3, 5),
        candidate("合", 7, 176.0415, 186.5415, 363.869, 1, 6, 0),
        candidate("计", 8, 212.8219, 223.3219, 363.869, 1, 6, 1),
        candidate("100.00", 9, 250, 300, 363.869, 2, 7),
        candidate("120.00", 10, 400, 450, 363.869, 3, 8),
    ]
    bands = [
        {"id": 1, "x0": 105, "x1": 230, "support": 3, "y_support": 3},
        {"id": 2, "x0": 240, "x1": 320, "support": 3, "y_support": 3},
        {"id": 3, "x0": 390, "x1": 470, "support": 3, "y_support": 3},
    ]

    monkeypatch.setattr(
        recoverer,
        "collect_native_spans",
        lambda page, allowed_regions: [object()],
    )
    monkeypatch.setattr(recoverer, "region_spans", lambda spans, bbox: [object()])
    monkeypatch.setattr(
        recoverer, "infer_output_order_mode", lambda spans: "row_interleaved"
    )
    monkeypatch.setattr(
        recoverer, "build_text_runs", lambda spans, output_mode: atoms
    )
    monkeypatch.setattr(recoverer, "infer_column_bands", lambda items, bbox: bands)
    monkeypatch.setattr(
        recoverer, "prune_paired_cjk_artifact_bands", lambda items, value: value
    )
    monkeypatch.setattr(
        recoverer,
        "prune_sparse_alignment_artifact_bands",
        lambda items, value: value,
    )
    monkeypatch.setattr(
        recoverer, "merge_same_band_native_line_runs", lambda items, value: items
    )
    monkeypatch.setattr(
        recoverer, "refine_leaf_bands", lambda items, value: (value, None)
    )
    monkeypatch.setattr(
        recoverer,
        "rescue_sparse_body_bands",
        lambda items, value, cutoff: value,
    )
    monkeypatch.setattr(
        recoverer,
        "rescue_header_only_note_bands",
        lambda items, value, cutoff: value,
    )
    monkeypatch.setattr(
        recoverer,
        "rescue_header_only_leaf_bands",
        lambda items, value, cutoff: value,
    )
    monkeypatch.setattr(
        recoverer,
        "annotate_columns",
        lambda items, value, cutoff, bbox: None,
    )
    monkeypatch.setattr(
        recoverer, "merge_column_continuations", lambda items, value: items
    )
    monkeypatch.setattr(recoverer, "build_grid", counting_build_grid)

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns) == (3, 3)
    assert build_grid_calls == 2
    assert any(cell.text == "合计" for cell in cells)
    occupied = set()
    for cell in cells:
        for row in range(cell.row_index, cell.row_index + cell.rowspan):
            for column in range(cell.col_index, cell.col_index + cell.colspan):
                assert (row, column) not in occupied
                occupied.add((row, column))
    assert len(occupied) == rows * columns


def test_header_span_conflict_keeps_conflict_free_base_grid(monkeypatch):
    base = [
        {"cell_id": "A", "row_start": 1, "row_end": 1, "col_start": 1, "col_end": 1},
        {"cell_id": "B", "row_start": 1, "row_end": 1, "col_start": 2, "col_end": 2},
    ]
    conflicting = [dict(item) for item in base]
    conflicting[0].update(col_end=2, colspan=2)
    monkeypatch.setattr(recoverer, "merge_header_spans", lambda cells, cutoff: conflicting)

    result = recoverer._commit_header_spans_or_keep_base(base, header_cutoff=20)

    assert result == base
    assert recoverer._has_occupancy_conflict(result) is False


def test_header_span_without_conflict_commits_proposed_grid(monkeypatch):
    base = [
        {"cell_id": "A", "row_start": 1, "row_end": 1, "col_start": 1, "col_end": 1},
        {"cell_id": "B", "row_start": 1, "row_end": 1, "col_start": 2, "col_end": 2},
    ]
    proposed = [dict(item) for item in base]
    proposed[0]["rowspan"] = 2
    proposed[0]["row_end"] = 2
    monkeypatch.setattr(recoverer, "merge_header_spans", lambda cells, cutoff: proposed)

    result = recoverer._commit_header_spans_or_keep_base(base, header_cutoff=20)

    assert result == proposed


def test_recoverer_materializes_complete_grid_after_header_span_conflict(monkeypatch):
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
        recoverer,
        "collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    def conflicting_spans(cells, cutoff):
        proposed = [dict(cell) for cell in cells]
        proposed[0].update(col_end=2, colspan=2)
        return proposed

    monkeypatch.setattr(recoverer, "merge_header_spans", conflicting_spans)

    rows, columns, cells = recover_cells_from_region(object(), region)

    occupied = [
        (row, column)
        for cell in cells
        for row in range(cell.row_index, cell.row_index + cell.rowspan)
        for column in range(cell.col_index, cell.col_index + cell.colspan)
    ]
    assert (rows, columns, len(cells)) == (3, 2, 6)
    assert len(occupied) == len(set(occupied)) == rows * columns
    assert next(cell for cell in cells if cell.row_index == 2 and cell.col_index == 1).text == ""


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


def test_recover_cells_restores_header_only_leaf_and_materializes_empty_body(monkeypatch):
    region = BBox(0, 0, 300, 140)
    raw = [
        (10, 10, "类别"),
        (10, 70, "使用寿命"),
        (10, 130, "确定依据"),
        (10, 190, "摊销方法"),
        (10, 250, "空列表头"),
    ]
    for row_index, label in enumerate(("甲", "乙", "丙", "丁", "戊"), 1):
        y = 20 + row_index * 20
        raw.extend(
            [
                (y, 10, label),
                (y, 70, str(row_index * 10)),
                (y, 130, f"依据{row_index}"),
                (y, 190, "直线法"),
            ]
        )
    spans = [
        NativeSpan(text, BBox(x0, y, x0 + 30, y + 10), "SimSun", 10, order)
        for order, (y, x0, text) in enumerate(raw)
    ]
    monkeypatch.setattr(
        recoverer,
        "collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns, len(cells)) == (6, 5, 30)
    assert next(
        cell for cell in cells if cell.row_index == 0 and cell.col_index == 4
    ).text == "空列表头"
    empty_body = [
        cell
        for cell in cells
        if cell.col_index == 4 and cell.row_index in range(1, 6)
    ]
    assert len(empty_body) == 5
    assert all(
        cell.text == "" and cell.rowspan == 1 and cell.colspan == 1
        for cell in empty_body
    )


def test_recover_cells_merges_wrapped_fields_before_physical_rows(monkeypatch):
    region = BBox(90, 0, 490, 120)
    raw = [
        (18.5, 103, 145, "企业名称"),
        (10, 168, 189, "注册"),
        (27, 168, 189, "地址"),
        (18.5, 220, 262, "主营业务"),
        (10, 289, 331, "与本公司"),
        (27, 299.5, 320.5, "关系"),
        (10, 339, 360, "业务"),
        (27, 339, 360, "性质"),
        (10, 379, 400, "法定"),
        (27, 374, 405.5, "代表人"),
        (18.5, 422, 485, "组织机构代码"),
        (70, 92, 124, "杨志茂"),
        (70, 160, 181, "---"),
        (70, 233, 254, "---"),
        (61.5, 289, 331, "本公司实"),
        (78.5, 289, 331, "际控制人"),
        (70, 342, 358, "---"),
        (70, 382, 403, "---"),
        (70, 446, 467, "---"),
        (100, 92, 157, "广东锦龙发展"),
        (100, 168, 189, "清远"),
        (100, 198, 285, "实业投资、房地产"),
        (100, 294, 326, "母公司"),
        (100, 339, 360, "上市"),
        (100, 379, 401, "杨志茂"),
        (100, 427, 485, "61797180-0"),
    ]
    spans = [
        NativeSpan(text, BBox(x0, y, x1, y + 10), "SimSun", 10.5, order)
        for order, (y, x0, x1, text) in enumerate(raw)
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns, len(cells)) == (3, 7, 21)
    occupied = {
        (row, column)
        for cell in cells
        for row in range(cell.row_index, cell.row_index + cell.rowspan)
        for column in range(cell.col_index, cell.col_index + cell.colspan)
    }
    assert len(occupied) == rows * columns
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 1).text == "注册\n地址"
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 3).text == "与本公司\n关系"
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 4).text == "业务\n性质"
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 5).text == "法定\n代表人"
    assert next(cell for cell in cells if cell.row_index == 1 and cell.col_index == 3).text == "本公司实\n际控制人"


def test_recover_cells_from_region_removes_paired_cjk_artifact_column(monkeypatch):
    region = BBox(90, 0, 470, 110)
    raw = [
        (10, 170, 180.5, "项"),
        (10, 191, 201.5, "目"),
        (10, 306, 348, "本年金额"),
        (10, 401, 443, "上年金额"),
        (30, 100, 142, "职工薪酬"),
        (30, 306, 370, "100"),
        (30, 401, 463, "90"),
        (50, 100, 174, "聘请中介机构费"),
        (50, 306, 370, "200"),
        (50, 401, 463, "180"),
        (70, 100, 121, "其他"),
        (70, 306, 370, "300"),
        (70, 401, 463, "270"),
        (90, 170, 180.5, "合"),
        (90, 191, 201.5, "计"),
        (90, 306, 370, "600"),
        (90, 401, 463, "540"),
    ]
    spans = [
        NativeSpan(text, BBox(x0, y, x1, y + 10), "SimSun", 10.5, order)
        for order, (y, x0, x1, text) in enumerate(raw)
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns, len(cells)) == (5, 3, 15)
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 0).text == "项目"
    assert next(cell for cell in cells if cell.row_index == 4 and cell.col_index == 0).text == "合计"


def test_recover_cells_from_region_removes_sparse_alignment_column(monkeypatch):
    region = BBox(90, 0, 470, 90)
    raw = [
        (10, 168, 189, "项目"),
        (10, 300, 340, "本年金额"),
        (10, 400, 440, "上年金额"),
        (30, 100, 142, "正文一"),
        (30, 300, 340, "100"),
        (30, 400, 440, "90"),
        (50, 100, 163, "正文二"),
        (50, 300, 340, "200"),
        (50, 400, 440, "180"),
        (70, 168, 189, "合计"),
        (70, 300, 340, "300"),
        (70, 400, 440, "270"),
    ]
    spans = [
        NativeSpan(text, BBox(x0, y, x1, y + 10), "SimSun", 10.5, order)
        for order, (y, x0, x1, text) in enumerate(raw)
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns, len(cells)) == (4, 3, 12)
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 0).text == "项目"
    assert next(cell for cell in cells if cell.row_index == 3 and cell.col_index == 0).text == "合计"


def test_recover_interleaved_vertical_cjk_columns(monkeypatch):
    region = BBox(0, 0, 200, 140)
    raw = [
        # Header row (y=10..40): "被投资单位" + "期初余额" + "期末余额"
        (10, 10, 20, "被"),
        (10, 30, 40, "投"),
        (25, 10, 20, "资"),
        (25, 30, 40, "单"),
        (40, 10, 20, "位"),
        (25, 60, 100, "期初余额"),
        (25, 120, 160, "期末余额"),
        # Row 1 (y=60..85): "河南泓淇" + 100.00 + 120.00
        (60, 10, 20, "河"),
        (60, 30, 40, "南"),
        (75, 10, 20, "泓"),
        (75, 30, 40, "淇"),
        (67.5, 60, 100, "100.00"),
        (67.5, 120, 160, "120.00"),
        # Row 2 (y=95..120): "光电产业" + 200.00 + 240.00
        (95, 10, 20, "光"),
        (95, 30, 40, "电"),
        (110, 10, 20, "产"),
        (110, 30, 40, "业"),
        (102.5, 60, 100, "200.00"),
        (102.5, 120, 160, "240.00"),
    ]
    spans = [
        NativeSpan(text, BBox(x0, y, x1, y + 10), "SimSun", 10.5, order)
        for order, (y, x0, x1, text) in enumerate(raw)
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns) == (3, 3)
    header_col0 = next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 0).text
    assert "被" in header_col0 and "投" in header_col0 and "资" in header_col0 and "单" in header_col0 and "位" in header_col0
    row1_col0 = next(cell for cell in cells if cell.row_index == 1 and cell.col_index == 0).text
    assert "河" in row1_col0 and "南" in row1_col0 and "泓" in row1_col0 and "淇" in row1_col0
    row2_col0 = next(cell for cell in cells if cell.row_index == 2 and cell.col_index == 0).text
    assert "光" in row2_col0 and "电" in row2_col0 and "产" in row2_col0 and "业" in row2_col0
    assert next(cell for cell in cells if cell.row_index == 1 and cell.col_index == 1).text == "100.00"
    assert next(cell for cell in cells if cell.row_index == 2 and cell.col_index == 2).text == "240.00"
