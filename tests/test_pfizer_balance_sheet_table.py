import sys
from pathlib import Path
import pytest
import pymupdf as fitz
from hexai_pdf_parser.core.models import BBox, Cell
from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor

PFIZER_PDF = Path(r"c:\Users\23662\xwechat_files\wxid_gi29mv53wwtn22_e71e\msg\file\2026-10\0000078003_10-K_20250227.pdf")

@pytest.mark.skipif(not PFIZER_PDF.exists(), reason="Pfizer test PDF not found")
def test_column_shading_rejected_as_zebra():
    """验证当表格底色为单一数据列高亮（如 2024 列），而不是行交替斑马纹时，extract_zebra 必须拒绝并返回空，不得误当斑马表。"""
    doc = fitz.open(str(PFIZER_PDF))
    page = doc[64]
    table_bbox = BBox(30.9, 89.9, 571.3, 600.5)

    extractor = EnglishTableExtractor()
    # 纯列底色不应被识别为行斑马纹
    zebra_tables = extractor.extract_zebra(page, table_bbox=table_bbox)
    assert len(zebra_tables) == 0, f"列底色表格不应被 extract_zebra 识别，但识别出 {len(zebra_tables)} 个表格"

@pytest.mark.skipif(not PFIZER_PDF.exists(), reason="Pfizer test PDF not found")
def test_pfizer_page_65_balance_sheet_structure():
    """验证 Pfizer 10-K 第 65 页（index 64）资产负债表的完整结构：
    1. 不发生 NameError 崩溃；
    2. 表头 As of December 31, 正确跨 2 列 (colspan=2)；
    3. 行数 >= 40 行，明细行不被压缩到单行中；
    4. Assets 为独立行，Cash and cash equivalents 与其数值对应正确。
    """
    doc = fitz.open(str(PFIZER_PDF))
    page = doc[64]
    table_bbox = BBox(30.9, 89.9, 571.3, 600.5)

    extractor = EnglishTableExtractor()
    tables = extractor.extract(page, table_bbox=table_bbox, page_language="en")
    assert len(tables) == 1
    t = tables[0]

    # 行数必须在 40~45 行之间，严禁坍塌为 7 行
    assert t.rows >= 40, f"表格行数预期 >= 40，实际仅为 {t.rows}"
    assert t.cols == 3, f"表格列数预期为 3，实际为 {t.cols}"

    # 表头第一行应包含 As of December 31, 且跨 2 列
    as_of = next((c for c in t.cells if "as of december 31" in c.text.lower()), None)
    assert as_of is not None, "未找到 'As of December 31,' 表头单元格"
    assert as_of.row_index == 0, f"'As of December 31,' 起始行应为 0，实际为 {as_of.row_index}"
    assert as_of.colspan == 2, f"'As of December 31,' 应跨 2 列 (colspan=2)，实际为 {as_of.colspan}"

    # Cash and cash equivalents 单元格验证
    cash_cell = next((c for c in t.cells if "cash and cash equivalents" in c.text.lower()), None)
    assert cash_cell is not None, "未找到 'Cash and cash equivalents' 单元格"
    cash_row = cash_cell.row_index
    # 同一行的 2024 年和 2023 年数值单元格
    c1 = next((c for c in t.cells if c.row_index == cash_row and c.col_index == 1), None)
    c2 = next((c for c in t.cells if c.row_index == cash_row and c.col_index == 2), None)
    assert c1 is not None and "1,043" in c1.text, f"2024 年现金及等价物预期包含 1,043，实际为 {getattr(c1, 'text', None)}"
    assert c2 is not None and "2,853" in c2.text, f"2023 年现金及等价物预期包含 2,853，实际为 {getattr(c2, 'text', None)}"
