from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan
from hexai_pdf_parser.tables.wireless_structure import hybrid_body
from hexai_pdf_parser.tables.wireless_structure.hybrid_body import (
    recover_hybrid_body_cells,
)


def _span(text, x0, y0, x1, order):
    return NativeSpan(
        text=text,
        bbox=BBox(x0, y0, x1, y0 + 10),
        font="SimSun",
        size=10,
        order=order,
    )


def test_hybrid_body_uses_wired_columns_and_materializes_missing_slots(monkeypatch):
    region = BBox(100, 100, 340, 190)
    spans = [
        _span("一、", 110, 110, 130, 1),
        _span("2012 年度利润总额", 132, 110, 230, 2),
        _span("48,811,123.02", 285, 110, 335, 3),
        _span("业务招待费超支", 110, 140, 190, 4),
        _span("5,008,704.46", 285, 140, 335, 5),
        _span("研发费用", 110, 170, 155, 6),
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_hybrid_body_cells(
        object(), region, [100, 260, 340]
    )

    assert (rows, columns, len(cells)) == (3, 2, 6)
    assert [cell.text for cell in cells if cell.col_index == 0 and cell.text] == [
        "一、2012 年度利润总额",
        "业务招待费超支",
        "研发费用",
    ]
    assert [cell.text for cell in cells if cell.col_index == 1 and cell.text] == [
        "48,811,123.02",
        "5,008,704.46",
    ]
    empty = next(cell for cell in cells if cell.row_index == 2 and cell.col_index == 1)
    assert empty.text == ""
    assert empty.rowspan == empty.colspan == 1


def test_hybrid_body_preserves_a_geometry_proven_colspan(monkeypatch):
    region = BBox(0, 0, 200, 40)
    spans = [_span("跨列项目", 20, 10, 180, 1)]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_hybrid_body_cells(
        object(), region, [0, 100, 200]
    )

    assert (rows, columns, len(cells)) == (1, 2, 1)
    assert cells[0].text == "跨列项目"
    assert (cells[0].col_index, cells[0].colspan) == (0, 2)


def test_hybrid_body_merges_left_shifted_same_column_continuation(monkeypatch):
    region = BBox(0, 0, 200, 60)
    spans = [
        _span("一年内到期的非流动资", 20, 10, 95, 1),
        _span("产", 0, 18, 10, 2),
        _span("100", 120, 16.3, 150, 3),
        _span("其他项目", 20, 40, 55, 4),
        _span("200", 120, 40, 150, 5),
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_hybrid_body_cells(
        object(), region, [0, 100, 200]
    )

    assert (rows, columns) == (2, 2)
    assert [cell.text for cell in cells if cell.col_index == 0 and cell.text] == [
        "一年内到期的非流动资\n产",
        "其他项目",
    ]


def test_hybrid_body_rejects_independent_same_slot_fields(monkeypatch):
    region = BBox(0, 0, 200, 40)
    build_grid_calls = 0
    real_build_grid = hybrid_body.build_grid

    def counting_build_grid(candidates, bands):
        nonlocal build_grid_calls
        build_grid_calls += 1
        return real_build_grid(candidates, bands)

    spans = [
        _span("字段一", 10, 10, 35, 1),
        _span("字段二", 70, 10, 95, 2),
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )
    monkeypatch.setattr(hybrid_body, "build_grid", counting_build_grid)

    assert recover_hybrid_body_cells(object(), region, [0, 100, 200]) == (0, 0, [])
    assert build_grid_calls == 1


def test_hybrid_body_resolves_wide_spaced_single_cjk_exact_slot(monkeypatch):
    region = BBox(0, 0, 200, 60)
    build_grid_calls = 0
    real_build_grid = hybrid_body.build_grid

    def counting_build_grid(candidates, bands):
        nonlocal build_grid_calls
        build_grid_calls += 1
        return real_build_grid(candidates, bands)

    spans = [
        NativeSpan(
            "项目",
            BBox(10, 10, 40, 20),
            "SimSun",
            10.5,
            1,
            source_position=(1, 0, 0),
        ),
        NativeSpan(
            "金额",
            BBox(120, 10, 150, 20),
            "SimSun",
            10.5,
            2,
            source_position=(2, 0, 0),
        ),
        NativeSpan(
            "合",
            BBox(10, 40, 20, 50),
            "SimSun",
            10.5,
            3,
            source_position=(3, 0, 0),
        ),
        NativeSpan(
            "计",
            BBox(46.28, 40, 56.28, 50),
            "SimSun",
            10.5,
            4,
            source_position=(3, 0, 1),
        ),
        NativeSpan(
            "30",
            BBox(120, 40, 140, 50),
            "SimSun",
            10.5,
            5,
            source_position=(4, 0, 0),
        ),
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )
    monkeypatch.setattr(hybrid_body, "build_grid", counting_build_grid)

    rows, columns, cells = recover_hybrid_body_cells(
        object(), region, [0, 100, 200]
    )

    assert (rows, columns) == (2, 2)
    assert build_grid_calls == 2
    assert next(
        cell for cell in cells if cell.row_index == 1 and cell.col_index == 0
    ).text == "合计"


def test_hybrid_body_rebuilds_after_same_slot_native_continuation(monkeypatch):
    region = BBox(0, 0, 200, 60)
    build_grid_calls = 0
    real_build_grid = hybrid_body.build_grid

    def counting_build_grid(candidates, bands):
        nonlocal build_grid_calls
        build_grid_calls += 1
        return real_build_grid(candidates, bands)

    spans = [
        NativeSpan(
            "以摊余成本计量的金融资产终止确",
            BBox(18, 10, 90, 20),
            "SimSun",
            10,
            1,
            source_position=(1, 0, 0),
        ),
        NativeSpan(
            "认收益（损失以\"-\"号填列）",
            BBox(0, 21, 17, 31),
            "SimSun",
            10,
            2,
            source_position=(1, 1, 0),
        ),
        NativeSpan(
            "-",
            BBox(120, 16, 130, 26),
            "SimSun",
            10,
            3,
            source_position=(2, 1, 0),
        ),
        NativeSpan(
            "后续项目",
            BBox(20, 40, 60, 50),
            "SimSun",
            10,
            4,
            source_position=(3, 2, 0),
        ),
        NativeSpan(
            "200",
            BBox(120, 40, 140, 50),
            "SimSun",
            10,
            5,
            source_position=(4, 2, 0),
        ),
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )
    monkeypatch.setattr(hybrid_body, "build_grid", counting_build_grid)

    rows, columns, cells = recover_hybrid_body_cells(
        object(), region, [0, 100, 200]
    )

    assert (rows, columns) == (2, 2)
    assert build_grid_calls == 2
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 0).text == (
        "以摊余成本计量的金融资产终止确\n认收益（损失以\"-\"号填列）"
    )


def test_hybrid_body_rejects_overlapping_span_occupancy(monkeypatch):
    region = BBox(0, 0, 200, 40)
    spans = [
        _span("跨列项目", 20, 10, 180, 1),
        _span("独立金额", 120, 10, 150, 2),
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    assert recover_hybrid_body_cells(object(), region, [0, 100, 200]) == (0, 0, [])


def test_hybrid_body_rejects_single_column_multiline_paragraphs_without_peer_support(
    monkeypatch,
):
    region = BBox(0, 0, 200, 100)
    spans = [
        _span("确定方法标题", 10, 45, 90, 1),
        _span("定价第一段说明文字", 110, 10, 190, 2),
        _span("定价第二段说明文字", 110, 40, 190, 3),
        _span("定价第三段说明文字", 110, 75, 190, 4),
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.hybrid_body.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    assert recover_hybrid_body_cells(object(), region, [0, 100, 200]) == (0, 0, [])
