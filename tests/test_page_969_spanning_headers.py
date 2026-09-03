import fitz
import pytest

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.page_normalizer import normalize_page_rotation
from hexai_pdf_parser.tables.wireless_structure.recoverer import (
    recover_cells_from_region,
)
from hexai_pdf_parser.tables.wireless_structure.columns import (
    is_spanning_header,
)


@pytest.fixture
def page_969():
    doc = fitz.open(r"fix/zh_all_table_pages.pdf")
    page = doc[969]
    normalize_page_rotation(page)
    yield page
    doc.close()


def test_table2_parent_span_recovery(page_969):
    """Page 969 Table 2 (资产负债表中归属于母公司的其他综合收益) should recover 5 columns with colspan=2 for '本期发生额'."""
    region = BBox(x0=84.0, y0=274.2, x1=505.7, y1=448.6)
    rows, cols, cells = recover_cells_from_region(page_969, region)

    assert rows >= 5, f"Expected at least 5 rows, got {rows}"
    assert cols == 5, f"Expected 5 columns, got {cols}"
    assert len(cells) > 0

    # Verify no occupancy conflict
    occupied = set()
    for c in cells:
        for r in range(c.row_index, c.row_index + c.rowspan):
            for col in range(c.col_index, c.col_index + c.colspan):
                slot = (r, col)
                assert slot not in occupied, f"Duplicate occupancy at {slot} by '{c.text}'"
                occupied.add(slot)

    # Verify '本期发生额' parent header
    parent_cells = [c for c in cells if "本期发生额" in c.text.replace("\n", "")]
    assert len(parent_cells) == 1, "Expected exactly one '本期发生额' cell"
    parent = parent_cells[0]
    assert parent.colspan == 2, f"Expected '本期发生额' to have colspan=2, got {parent.colspan}"
    assert parent.col_index == 2, f"Expected '本期发生额' col_index=2, got {parent.col_index}"

    # Verify leaf child columns
    leaf1_cells = [c for c in cells if "税后归属于母公司" in c.text.replace("\n", "")]
    assert len(leaf1_cells) >= 1
    assert leaf1_cells[0].col_index == 2
    assert leaf1_cells[0].colspan == 1

    leaf2_cells = [c for c in cells if "转入留存收益" in c.text.replace("\n", "")]
    assert len(leaf2_cells) >= 1
    assert leaf2_cells[0].col_index == 3
    assert leaf2_cells[0].colspan == 1

    # Verify body row with numeric values
    row_reclass = [c for c in cells if "将重分类进损益" in c.text.replace("\n", "")]
    assert len(row_reclass) == 1
    body_row_idx = row_reclass[0].row_index
    body_row = {c.col_index: c.text.strip() for c in cells if c.row_index == body_row_idx}
    assert body_row[1] == "-1,651,421.74"
    assert body_row[2] == "1,038,531.60"
    assert body_row[3] == "-"
    assert body_row[4] == "-612,890.14"


def test_table3_six_column_recovery(page_969):
    """Page 969 Table 3 (利润表中归属于母公司的其他综合收益) should recover 6 columns without column collapse."""
    region = BBox(x0=84.5, y0=479.5, x1=506.0, y1=694.7)
    rows, cols, cells = recover_cells_from_region(page_969, region)

    assert rows >= 5, f"Expected at least 5 rows, got {rows}"
    assert cols == 6, f"Expected 6 columns, got {cols}"
    assert len(cells) > 0

    # Verify no occupancy conflict
    occupied = set()
    for c in cells:
        for r in range(c.row_index, c.row_index + c.rowspan):
            for col in range(c.col_index, c.col_index + c.colspan):
                slot = (r, col)
                assert slot not in occupied, f"Duplicate occupancy at {slot} by '{c.text}'"
                occupied.add(slot)

    # Verify body row has values in all columns (no merged '--')
    row_reclass = [c for c in cells if "将重分类进损益" in c.text.replace("\n", "")]
    assert len(row_reclass) == 1
    body_row_idx = row_reclass[0].row_index
    body_row = {c.col_index: c.text.strip() for c in cells if c.row_index == body_row_idx}
    assert body_row[1] == "1,038,531.60"
    assert body_row[2] == "-"
    assert body_row[3] == "-"
    assert body_row[4] == "-"
    assert body_row[5] == "1,038,531.60"


def test_is_spanning_header_negative_cases():
    """Negative tests: leaf headers or single items should not be flagged as spanning headers."""
    region = BBox(0.0, 0.0, 500.0, 400.0)

    # Case 1: Simple leaf header with single column below
    atom_leaf = {"text": "金额", "bbox": [100.0, 20.0, 150.0, 32.0]}
    atoms = [
        atom_leaf,
        {"text": "100.00", "bbox": [105.0, 50.0, 145.0, 62.0]},
        {"text": "200.00", "bbox": [105.0, 70.0, 145.0, 82.0]},
    ]
    assert not is_spanning_header(atom_leaf, atoms, region)

    # Case 2: Lower row (in body, y > 0.45 of region)
    atom_body = {"text": "小计", "bbox": [100.0, 250.0, 200.0, 262.0]}
    atoms_with_body = [
        atom_body,
        {"text": "10.0", "bbox": [105.0, 280.0, 145.0, 292.0]},
        {"text": "20.0", "bbox": [155.0, 280.0, 195.0, 292.0]},
    ]
    assert not is_spanning_header(atom_body, atoms_with_body, region)

    # Case 3: Spanning header positive case
    atom_parent = {"text": "本期发生额", "bbox": [100.0, 20.0, 200.0, 32.0]}
    atoms_parent = [
        atom_parent,
        {"text": "税前", "bbox": [105.0, 40.0, 145.0, 52.0]},
        {"text": "税后", "bbox": [155.0, 40.0, 195.0, 52.0]},
    ]
    assert is_spanning_header(atom_parent, atoms_parent, region)
