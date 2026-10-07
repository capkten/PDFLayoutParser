import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = CURRENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest
import pymupdf as fitz
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor

@pytest.mark.parametrize("method_name", ["extract_zebra", "extract_general_wireless", "extract"])
def test_page_347_table_structure(method_name):
    pdf_path = Path("src/hexai_pdf_parser/data/en_all_pages/problem/en_all_table_pages_page_347.pdf")
    if not pdf_path.exists():
        pdf_path = Path(r"c:\Users\92410\Desktop\git\hexai_pdf_parser\src\hexai_pdf_parser\data\en_all_pages\problem\en_all_table_pages_page_347.pdf")
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    table_bbox = BBox(x0=30.5, y0=104.7, x1=576.6, y1=213.8)

    extractor = EnglishTableExtractor()
    if method_name == "extract_zebra":
        tables = extractor.extract_zebra(page, table_bbox)
    elif method_name == "extract_general_wireless":
        tables = extractor.extract_general_wireless(page, table_bbox)
    else:
        tables = extractor.extract(page, table_bbox=table_bbox)
    assert len(tables) == 1
    table = tables[0]

    rows = {}
    for c in table.cells:
        rows.setdefault(c.row_index, []).append(c)

    # 1. 验证首列表头跨行合并：Row 0 Col 0 必须为 rowspan=2, colspan=1，Row 1 不应再出现独立的空槽位
    row0_col0 = next((c for c in rows[0] if c.col_index == 0), None)
    assert row0_col0 is not None
    assert row0_col0.rowspan == 2, f"Row 0 Col 0 应具有 rowspan=2，实际为 {row0_col0.rowspan}"
    row1_col0 = next((c for c in rows[1] if c.col_index == 0), None)
    assert row1_col0 is None, "Row 1 Col 0 已被 Row 0 占用，不应生成独立的 1x1 空槽位"

    # 2. 验证 Common Stock 双子列划分与金额 $ 归位
    common_stock = next((c for c in rows[0] if "Common Stock" in c.text), None)
    assert common_stock is not None
    assert common_stock.colspan == 2, f"Common Stock 应为 colspan=2，实际为 {common_stock.colspan}"
    common_col = common_stock.col_index

    # 检查 Row 1 的两列子标题：Shares 和 $
    shares_sub = next((c for c in rows[1] if c.col_index == common_col), None)
    dollar_sub = next((c for c in rows[1] if c.col_index == common_col + 1), None)
    assert shares_sub is not None and "Shares" in shares_sub.text
    assert dollar_sub is not None and "$" in dollar_sub.text

    # 检查数据行 June 30, 2024 (Row 2): 股票数不含 $，金额包含 $76
    row2_shares = next((c for c in rows[2] if c.col_index == common_col), None)
    row2_amount = next((c for c in rows[2] if c.col_index == common_col + 1), None)
    assert row2_shares is not None
    assert row2_shares.text.strip() == "75,968", f"股票数应为 '75,968'，实际为 '{row2_shares.text}'"
    assert row2_amount is not None
    assert row2_amount.text.strip() == "$76", f"金额应为 '$76'，实际为 '{row2_amount.text}'"

    # 3. 验证 Treasury Stock 严格为 colspan=2，不吞并 APIC
    treasury_stock = next((c for c in rows[0] if "Treasury Stock" in c.text), None)
    assert treasury_stock is not None
    assert treasury_stock.colspan == 2, f"Treasury Stock 应为 colspan=2，实际为 {treasury_stock.colspan}"

    # 4. 验证 APIC 为独立单列表头且向上合并为 rowspan=2
    apic_cell = next((c for c in table.cells if "APIC" in c.text), None)
    assert apic_cell is not None
    assert apic_cell.colspan == 1
    assert apic_cell.rowspan == 2, f"APIC 应向上合并具有 rowspan=2，实际为 {apic_cell.rowspan}"
    assert apic_cell.row_index == 0, f"APIC 向上合并后起始行应为 Row 0，实际为 Row {apic_cell.row_index}"

    # 5. 验证后续数据行两列无粘连
    # PHOT share issuance (Row 6): shares=813, amount=1
    phot_row = next((r for r in rows.values() if any("PHOT" in c.text for c in r)), None)
    assert phot_row is not None
    phot_shares = next((c for c in phot_row if c.col_index == common_col), None)
    phot_amount = next((c for c in phot_row if c.col_index == common_col + 1), None)
    assert phot_shares is not None and phot_shares.text.strip() == "813"
    assert phot_amount is not None and phot_amount.text.strip() == "1"

    # September 30, 2024 (Row 13): shares=77,092, amount=77 (禁止粘连为 77,09277)
    sep_row = next((r for r in rows.values() if any("September 30" in c.text for c in r)), None)
    assert sep_row is not None
    sep_shares = next((c for c in sep_row if c.col_index == common_col), None)
    sep_amount = next((c for c in sep_row if c.col_index == common_col + 1), None)
    assert sep_shares is not None and sep_shares.text.strip() == "77,092"
    assert sep_amount is not None and sep_amount.text.strip() == "77"
