from types import SimpleNamespace

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.normalizers.financial_header_handler import (
    normalize_complex_financial_header,
)
from hexai_pdf_parser.tables.normalizers.table_header_normalizer import (
    normalize_table_headers,
)


def test_line_projection_preserves_wire_grid_header_spans():
    table = Table(
        bbox=BBox(0, 0, 400, 60),
        rows=2,
        cols=4,
        cells=[
            Cell("项目", 0, 0, BBox(0, 0, 100, 30), rowspan=2),
            Cell("本年金额", 0, 1, BBox(100, 0, 300, 30), colspan=2),
            Cell("上年金额", 0, 3, BBox(300, 0, 400, 30)),
            Cell("年初", 1, 1, BBox(100, 30, 200, 60)),
            Cell("年末", 1, 2, BBox(200, 30, 300, 60)),
            Cell("年末", 1, 3, BBox(300, 30, 400, 60)),
        ],
        source="line_projection",
    )

    result = normalize_table_headers(table, SimpleNamespace())
    result = normalize_complex_financial_header(result, SimpleNamespace())

    group = next(cell for cell in result.cells if cell.text == "本年金额")
    assert group.colspan == 2
    assert next(cell for cell in result.cells if cell.text == "上年金额").colspan == 1
    assert next(cell for cell in result.cells if cell.text == "项目").rowspan == 2


def test_line_projection_keeps_parallel_group_labels_as_separate_cells():
    table = Table(
        bbox=BBox(0, 0, 300, 40),
        rows=2,
        cols=3,
        cells=[
            Cell("项目", 0, 0, BBox(0, 0, 100, 20)),
            Cell("本期发生额", 0, 1, BBox(100, 0, 200, 20)),
            Cell("上期发生额", 0, 2, BBox(200, 0, 300, 20)),
            Cell("工资", 1, 0, BBox(0, 20, 100, 40)),
            Cell("100", 1, 1, BBox(100, 20, 200, 40)),
            Cell("90", 1, 2, BBox(200, 20, 300, 40)),
        ],
        source="line_projection",
    )

    result = normalize_table_headers(table, SimpleNamespace())

    assert [
        (cell.text, cell.row_index, cell.col_index, cell.rowspan, cell.colspan)
        for cell in result.cells[:3]
    ] == [
        ("项目", 0, 0, 1, 1),
        ("本期发生额", 0, 1, 1, 1),
        ("上期发生额", 0, 2, 1, 1),
    ]


def test_native_span_table_skips_legacy_grouped_header_promotion():
    table = Table(
        bbox=BBox(100, 100, 460, 300),
        rows=3,
        cols=3,
        cells=[
            Cell("\u9879\u76ee", 0, 0, BBox(100, 100, 200, 120)),
            Cell("\u672c\u5e74\u91d1\u989d", 0, 1, BBox(300, 100, 360, 120)),
            Cell("\u4e0a\u5e74\u91d1\u989d", 0, 2, BBox(400, 100, 460, 120)),
            Cell("\u804c\u5de5\u85aa\u916c", 1, 0, BBox(100, 140, 180, 160)),
            Cell("100", 1, 1, BBox(320, 140, 360, 160)),
            Cell("90", 1, 2, BBox(420, 140, 460, 160)),
        ],
        source="wireless_span_recovery",
    )
    page = SimpleNamespace(
        get_text=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("native-span tables must not reread page words")
        )
    )

    result = normalize_complex_financial_header(table, page)

    assert result is table
    assert [(cell.rowspan, cell.colspan) for cell in result.cells[:3]] == [
        (1, 1),
        (1, 1),
        (1, 1),
    ]
