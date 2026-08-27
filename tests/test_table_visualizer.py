from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.debug.table_visualizer import _compute_cell_grid_rects


def test_complete_wireless_recovery_table_still_uses_inferred_grid_rects():
    table = Table(
        bbox=BBox(0, 0, 100, 40),
        rows=2,
        cols=2,
        source="wireless_span_recovery",
        cells=[
            Cell("项目", 0, 0, BBox(10, 5, 20, 10)),
            Cell("", 0, 1, BBox(50, 0, 100, 20)),
            Cell("甲", 1, 0, BBox(10, 25, 20, 30)),
            Cell("10", 1, 1, BBox(60, 25, 70, 30)),
        ],
    )

    rects = _compute_cell_grid_rects(table)

    first = rects[0][1]
    assert (first.x0, first.y0) == (0, 0)
    assert first.x1 > table.cells[0].bbox.x1
