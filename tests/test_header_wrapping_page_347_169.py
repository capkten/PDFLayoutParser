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

def test_page_347_accumulated_deficit_merged():
    """验证 Page 347 表头中的 Accumulated 与 Deficit 垂直融合成单个完整单元格 'Accumulated Deficit'，禁止被拆分为两行。"""
    pdf_path = Path("src/hexai_pdf_parser/data/en_all_pages/problem/en_all_table_pages_page_347.pdf")
    if not pdf_path.exists():
        pdf_path = Path(r"c:\Users\92410\Desktop\git\hexai_pdf_parser\src\hexai_pdf_parser\data\en_all_pages\problem\en_all_table_pages_page_347.pdf")
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    table_bbox = BBox(x0=30.5, y0=104.7, x1=576.6, y1=213.8)

    extractor = EnglishTableExtractor()
    tables = extractor.extract(page, table_bbox=table_bbox)
    assert len(tables) == 1
    table = tables[0]

    # 验证是否存在融合后的 Accumulated Deficit 单元格
    acc_def = next((c for c in table.cells if "Accumulated Deficit" in c.text), None)
    assert acc_def is not None, f"未找到 'Accumulated Deficit' 单元格，当前所有包含 Accumulated 或 Deficit 的单元格为: {[c.text for c in table.cells if 'Accumulated' in c.text or 'Deficit' in c.text]}"
    assert acc_def.colspan == 1, f"'Accumulated Deficit' 应为单列 colspan=1，实际为 {acc_def.colspan}"
    assert acc_def.rowspan == 2, f"'Accumulated Deficit' 应为跨2行 rowspan=2，实际为 {acc_def.rowspan}"
    assert acc_def.row_index == 0, f"'Accumulated Deficit' 起始行应为 Row 0，实际为 Row {acc_def.row_index}"

    # 严禁残留孤立的单行 'Accumulated' 或单行 'Deficit'（Deficit Attributable to 除外）
    isolated_acc = next((c for c in table.cells if c.text.strip() == "Accumulated"), None)
    assert isolated_acc is None, "不应残留独立的 'Accumulated' 单元格"
    isolated_def = next((c for c in table.cells if c.text.strip() == "Deficit"), None)
    assert isolated_def is None, "不应残留独立的 'Deficit' 单元格"

def test_page_169_nine_months_ended_merged():
    """验证 Page 169 表头中的 Nine 与 Months Ended September 30, 垂直融合成单个单元格，禁止被拆分为两行。"""
    pdf_path = Path("src/hexai_pdf_parser/data/en_all_pages/problem/en_all_table_pages_page_169.pdf")
    if not pdf_path.exists():
        pdf_path = Path(r"c:\Users\92410\Desktop\git\hexai_pdf_parser\src\hexai_pdf_parser\data\en_all_pages\problem\en_all_table_pages_page_169.pdf")
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    table_bbox = BBox(x0=33.2, y0=317.7, x1=580.8, y1=375.4)

    extractor = EnglishTableExtractor()
    tables = extractor.extract(page, table_bbox=table_bbox)
    assert len(tables) == 1
    table = tables[0]

    # 1. 验证 Nine Months Ended September 30, 是否融合
    nine_months = next((c for c in table.cells if "Nine Months Ended" in c.text), None)
    assert nine_months is not None, f"未找到 'Nine Months Ended' 单元格，当前表头包含 Nine 或 Months 的单元格为: {[c.text for c in table.cells if 'Nine' in c.text or 'Months' in c.text]}"
    assert nine_months.colspan == 4, f"'Nine Months Ended' 应为 colspan=4，实际为 {nine_months.colspan}"
    assert nine_months.col_index == 5, f"'Nine Months Ended' 起始列应为 Col 5，实际为 Col {nine_months.col_index}"

    # 2. 验证 Three Months Ended September 30, 保持完好
    three_months = next((c for c in table.cells if "Three Months Ended" in c.text), None)
    assert three_months is not None
    assert three_months.colspan == 4
    assert three_months.col_index == 1

    # 3. 严禁出现孤立的 'Nine' 单元格
    isolated_nine = next((c for c in table.cells if c.text.strip() == "Nine"), None)
    assert isolated_nine is None, "不应残留独立的 'Nine' 单元格"
