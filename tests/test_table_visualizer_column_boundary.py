import json
from pathlib import Path
import pytest
from hexai_pdf_parser.core.models import Table, Cell, BBox
from hexai_pdf_parser.debug.table_visualizer import _compute_cell_grid_rects

# Check both worktree-relative and main-repo-relative paths
_P52_CANDIDATES = [
    Path("D:/codes/PDFLayoutParser/output/needs_human_glossary_ec_see_fix_v2_20260917/pages/page-052.json"),
    Path(__file__).resolve().parent.parent / "output" / "needs_human_glossary_ec_see_fix_v2_20260917" / "pages" / "page-052.json",
]
GLOSSARY_PAGE_52_JSON = next((p for p in _P52_CANDIDATES if p.exists()), None)


def test_compute_cell_grid_rects_with_horizontal_overlap_does_not_cut_left_column():
    """When a right-column cell starts further left (e.g. 'see' cross-reference),
    the column boundary must not collapse and slice through long text in the left column.
    """
    tb = BBox(49.9, 47.9, 560.4, 691.8)
    cells = [
        # Row 0: short left, 'see' reference in right column
        Cell(text="ETN", row_index=0, col_index=0, bbox=BBox(56.6, 59.6, 84.0, 73.0)),
        Cell(text="see exchange traded note", row_index=0, col_index=1, bbox=BBox(269.9, 59.6, 438.5, 73.0)),
        # Row 1: long left text extending to 294.0, right text starting at 319.0
        Cell(
            text="Electronic Mailing Stock Information Service (EMSIS)",
            row_index=1,
            col_index=0,
            bbox=BBox(56.6, 458.8, 294.0, 485.9),
        ),
        Cell(text="電子傳遞證券資訊服務", row_index=1, col_index=1, bbox=BBox(319.0, 460.8, 439.0, 475.0)),
        # Row 2: standard row
        Cell(text="early buy-in", row_index=2, col_index=0, bbox=BBox(56.6, 114.4, 122.0, 127.8)),
        Cell(text="提早補購", row_index=2, col_index=1, bbox=BBox(319.0, 116.5, 367.0, 130.7)),
    ]
    table = Table(bbox=tb, rows=3, cols=2, cells=cells, source="wireless_span_recovery")

    rects = _compute_cell_grid_rects(table)
    assert len(rects) == 6

    # Verify that the column 0 grid width is at least wide enough to enclose 294.0
    col0_rects = [r for c, r in rects if c.col_index == 0]
    for r in col0_rects:
        assert r.x1 >= 294.0, f"Column 0 boundary collapsed to {r.x1}, cutting off text at 294.0!"

    # Verify that the boundary lies in the true safe corridor [294.0, 319.0]
    col1_rects = [r for c, r in rects if c.col_index == 1]
    for r0, r1 in zip(col0_rects, col1_rects):
        assert r0.x1 == r1.x0
        assert 294.0 <= r0.x1 <= 319.0, f"Boundary {r0.x1} not in safe corridor [294.0, 319.0]"


@pytest.mark.skipif(GLOSSARY_PAGE_52_JSON is None, reason="page-052.json not found")
def test_compute_cell_grid_rects_page_52_no_text_clipped():
    """On full page 52, no cell in column 0 should be clipped by the vertical divider."""
    data = json.loads(GLOSSARY_PAGE_52_JSON.read_text(encoding="utf-8"))
    t_data = data["tables"][0]
    cells = [
        Cell(
            text=c["text"],
            row_index=c["row_index"],
            col_index=c["col_index"],
            rowspan=c["rowspan"],
            colspan=c["colspan"],
            bbox=BBox(**c["bbox"]),
        )
        for c in t_data["cells"]
    ]
    table = Table(
        bbox=BBox(**t_data["bbox"]),
        rows=t_data["rows"],
        cols=t_data["cols"],
        cells=cells,
        source=t_data.get("source"),
    )

    rects = _compute_cell_grid_rects(table)
    for cell, grid_rect in rects:
        if cell.col_index == 0 and cell.text.strip():
            # Column 0 text must be fully enclosed by its grid rect (no clipping)
            assert cell.bbox.x1 <= grid_rect.x1 + 0.5, (
                f"Cell '{cell.text.splitlines()[0]}' with x1={cell.bbox.x1} is clipped by grid_rect.x1={grid_rect.x1}!"
            )
