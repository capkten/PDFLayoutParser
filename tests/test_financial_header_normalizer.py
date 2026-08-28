from types import SimpleNamespace

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.normalizers.financial_header_handler import (
    normalize_complex_financial_header,
)


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
