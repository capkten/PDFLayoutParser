from __future__ import annotations

import fitz
import pytest

from hexai_pdf_parser.extractors.personal_credit_report import (
    _join_query_items,
    _make_query_table,
    _make_query_tables,
)


def test_join_query_items():
    items = [
        (10.0, 20.0, 30.0, 40.0, "招商"),
        (30.0, 20.0, 50.0, 40.0, "银行"),
    ]
    result = _join_query_items(items)
    assert result == "招商银行"


def test_make_query_tables_with_synthetic_page():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Header row
    page.insert_text((50, 100), "编号", fontsize=10, fontname="china-s")
    page.insert_text((150, 100), "查询日期", fontsize=10, fontname="china-s")
    page.insert_text((260, 100), "查询机构", fontsize=10, fontname="china-s")
    page.insert_text((420, 100), "查询原因", fontsize=10, fontname="china-s")
    # Row 1
    page.insert_text((50, 120), "1", fontsize=10, fontname="china-s")
    page.insert_text((150, 120), "2023年01月01日", fontsize=10, fontname="china-s")
    page.insert_text((260, 120), "测试银行", fontsize=10, fontname="china-s")
    page.insert_text((420, 120), "信用卡审批", fontsize=10, fontname="china-s")
    # Row 2
    page.insert_text((50, 140), "2", fontsize=10, fontname="china-s")
    page.insert_text((150, 140), "2023年02月01日", fontsize=10, fontname="china-s")
    page.insert_text((260, 140), "某某银行", fontsize=10, fontname="china-s")
    page.insert_text((420, 140), "贷后管理", fontsize=10, fontname="china-s")

    tables = _make_query_tables(page)
    assert len(tables) == 1
    assert tables[0].rows == 3
    assert tables[0].cols == 4
    doc.close()


def test_is_numbered_prose_candidate_rejects_two_column_split_prose():
    """Verify that _is_numbered_prose_candidate detects paragraphs even when split into 2 columns with each cell < 50 chars."""
    from hexai_pdf_parser.core.models import BBox, Cell, Table
    from hexai_pdf_parser.extractors.personal_credit_report import (
        PersonalCreditReportTableExtractor,
    )

    box = BBox(36.0, 400.0, 550.0, 500.0)
    # Row 0: Lead title
    # Row 1: Item 1 split into 2 columns, each < 50 chars (e.g. 44 and 43), total = 87
    # Row 2: Item 2 split into 2 columns, each < 50 chars (e.g. 39 and 42), total = 81
    cells = [
        Cell("信用卡", 0, 0, BBox(36, 411, 72, 423)),
        Cell("从未逾期过的贷记卡及透支未超过60天的准贷记卡账户明细如下：", 1, 0, BBox(36, 428, 341, 439), colspan=2),
        Cell("1. 2017年03月11日交通银行股份有限公司\n54,000，已使用额度20,932。", 2, 0, BBox(36, 443, 201, 465)),
        Cell("上海市分行发放的贷记卡（卡片尾号：2344），2026年07月到期，信用额度", 2, 1, BBox(201, 443, 547, 452)),
        Cell("2. 2017年03月11日交通银行股份有限公司\n14,000，已使用额度0。", 3, 0, BBox(36, 470, 201, 492)),
        Cell("上海市分行发放的贷记卡（美元账户，卡片尾号：5244），2026年07月到期，信用额度折合人民币", 3, 1, BBox(201, 470, 538, 479)),
    ]
    table = Table(bbox=box, rows=4, cols=2, cells=cells, source="wireless_span_recovery")

    assert PersonalCreditReportTableExtractor._is_numbered_prose_candidate(table) is True


def test_pdfsam_merge_numbered_prose_not_extracted_as_table():
    """Verify that on PDFsam_merge1.pdf, the numbered credit card prose is not extracted as a table."""
    import os
    from hexai_pdf_parser.extractors.personal_credit_report import (
        PersonalCreditReportTableExtractor,
    )

    pdf_path = os.path.join(
        "D:\\codes\\PDFLayoutParser",
        "个人信用报告",
        "PDFsam_merge1.pdf",
    )
    assert os.path.exists(pdf_path)

    doc = fitz.open(pdf_path)
    page = doc[0]

    extractor = PersonalCreditReportTableExtractor(use_ml_table_detector=False)
    tables = extractor.extract(page)

    # 验证不包含“从未逾期过的贷记卡...”表格
    prose_tables = [
        t for t in tables
        if any("从未逾期过的贷记卡" in cell.text for cell in t.cells)
    ]
    assert len(prose_tables) == 0, f"Expected 0 prose tables, got {len(prose_tables)}"

