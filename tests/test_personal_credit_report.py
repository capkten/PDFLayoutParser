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


def test_make_query_tables_keeps_header_only_cross_page_continuation():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((260, 80), "机构查询记录明细", fontsize=10, fontname="china-s")
    page.insert_text((50, 100), "编号", fontsize=10, fontname="china-s")
    page.insert_text((150, 100), "查询日期", fontsize=10, fontname="china-s")
    page.insert_text((260, 100), "查询机构", fontsize=10, fontname="china-s")
    page.insert_text((420, 100), "查询原因", fontsize=10, fontname="china-s")

    tables = _make_query_tables(page)

    assert len(tables) == 1
    assert tables[0].rows == 1
    assert tables[0].cols == 4
    assert [cell.text for cell in tables[0].cells] == [
        "编号",
        "查询日期",
        "查询机构",
        "查询原因",
    ]
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


def test_trim_query_table_with_merged_header_cells():
    """Verify that _trim_query_table drops section title row even when headers are merged into fewer cells."""
    from hexai_pdf_parser.core.models import BBox, Cell, Table
    from hexai_pdf_parser.extractors.personal_credit_report import _trim_query_table

    box = BBox(52.3, 564.0, 542.2, 635.9)
    # Row 0: Section title
    # Row 1: Merged headers ("查询机构查询原因" merged into 1 cell)
    # Row 2: Data row
    cells = [
        Cell("本人查询记录明细", 0, 0, BBox(52.3, 564.0, 542.2, 573.0), colspan=4),
        Cell("编号", 1, 0, BBox(52.3, 580.1, 72.0, 589.1)),
        Cell("查询日期", 1, 1, BBox(120.0, 580.1, 180.0, 589.1)),
        Cell("查询机构查询原因", 1, 2, BBox(243.0, 580.1, 450.0, 589.1), colspan=2),
        Cell("1", 2, 0, BBox(52.3, 595.0, 72.0, 604.0)),
        Cell("2025年05月13日", 2, 1, BBox(120.0, 595.0, 180.0, 604.0)),
        Cell("本人", 2, 2, BBox(243.0, 595.0, 300.0, 604.0)),
        Cell("本人查询", 2, 3, BBox(350.0, 595.0, 450.0, 604.0)),
    ]
    table = Table(bbox=box, rows=3, cols=4, cells=cells, source="wireless_span_recovery")
    trimmed = _trim_query_table(table)

    assert trimmed.rows == 2
    assert trimmed.bbox.y0 >= 580.0
    row0_texts = [c.text for c in trimmed.cells if c.row_index == 0]
    assert "本人查询记录明细" not in row0_texts
    assert "编号" in row0_texts


def test_page_003_query_tables_do_not_contain_titles():
    """Verify that on page 3 of 个人征信报告（简版）(1).pdf, both query tables do not include titles as rows."""
    import os
    from hexai_pdf_parser.extractors.personal_credit_report import (
        PersonalCreditReportTableExtractor,
    )

    pdf_path = os.path.join(
        "D:\\codes\\PDFLayoutParser",
        "个人信用报告",
        "个人征信报告（简版）(1).pdf",
    )
    assert os.path.exists(pdf_path)

    doc = fitz.open(pdf_path)
    page = doc[3]

    extractor = PersonalCreditReportTableExtractor(use_ml_table_detector=False)
    tables = extractor.extract(page)

    # 找到机构查询明细和本人查询明细表格
    query_tables = [
        t for t in tables
        if any("查询原因" in c.text or "查询机构" in c.text for c in t.cells)
    ]
    assert len(query_tables) >= 2, f"Expected at least 2 query tables, got {len(query_tables)}"

    for qt in query_tables:
        row0_cells = [c for c in qt.cells if c.row_index == 0]
        row0_text = "".join(c.text for c in row0_cells)
        assert "明细" not in row0_text, f"Row 0 should not contain section title, but got: {row0_text}"
        assert "编号" in row0_text
        assert "查询日期" in row0_text
        assert qt.rows > 1, f"Query table should contain detail rows, but got rows={qt.rows}"


def test_query_tables_detail_rows_extracted_on_personal_credit_report_samples():
    """Verify that query tables have detail rows extracted on both credit report samples."""
    import os
    from hexai_pdf_parser.extractors.personal_credit_report import (
        PersonalCreditReportTableExtractor,
    )

    pdf_files = [
        os.path.join("D:\\codes\\PDFLayoutParser", "个人信用报告", "个人信用报告(本人简版).pdf"),
        os.path.join("D:\\codes\\PDFLayoutParser", "个人信用报告", "个人征信报告（简版）(1).pdf"),
    ]
    for pdf_path in pdf_files:
        assert os.path.exists(pdf_path), f"File missing: {pdf_path}"
        doc = fitz.open(pdf_path)
        page = doc[3]  # Page 4 (0-indexed 3)
        extractor = PersonalCreditReportTableExtractor(use_ml_table_detector=False)
        tables = extractor.extract(page)
        query_tables = [
            t for t in tables
            if any("查询原因" in c.text or "查询机构" in c.text for c in t.cells)
        ]
        assert len(query_tables) == 2, f"Expected 2 query tables in {pdf_path}, got {len(query_tables)}"
        for qt in query_tables:
            assert qt.rows > 1, f"Expected table to contain detail rows in {pdf_path}, but got rows={qt.rows}"
            # Check row 1 has a number in col 0
            row1_col0 = [c for c in qt.cells if c.row_index == 1 and c.col_index == 0]
            assert len(row1_col0) == 1
            assert row1_col0[0].text.strip() == "1", f"Expected row 1 col 0 to be '1', got: {row1_col0[0].text}"



def test_document_result_preserves_layout_reading_order_over_raw_y0():
    """Verify that _document_result uses element.order instead of raw (y0, x0) sorting.

    When glyph bounding boxes cause the text top (y0=541.08) to be slightly higher than
    the number top (y0=541.58), raw (y0, x0) sort incorrectly places text before number.
    """
    from hexai_pdf_parser.core.models import BBox, Document, LayoutElement, Page
    from hexai_pdf_parser.extractors.personal_credit_report import _document_result

    # Order 0: "39." with y0=541.58
    elem_num = LayoutElement(
        type="text",
        bbox=BBox(36.0, 541.58, 48.64, 550.58),
        order=0,
        content="39.",
    )
    # Order 1: Text with y0=541.08 (< 541.58)
    elem_text = LayoutElement(
        type="text",
        bbox=BBox(50.95, 541.08, 479.05, 550.08),
        order=1,
        content="2020年12月18日南京银行股份有限公司常州分行发放的20,000元（人民币）其他贷款，2021年09月已结清。",
    )

    page = Page(index=0, size={"width": 595.0, "height": 842.0}, rotation=0)
    page.layout_elements = [elem_num, elem_text]
    doc = Document(file_name="test.pdf", page_count=1, pages=[page])

    result = _document_result(doc)
    blocks = result["pages"][0]["blocks"]

    assert len(blocks) == 2
    assert blocks[0]["content"] == "39.", f"Expected '39.' first, but got: {blocks[0]['content']}"
    assert "2020年12月18日" in blocks[1]["content"]


def test_parse_personal_credit_report_preserves_loan_numbering_order():
    """End-to-end test on the loan PDF sample to ensure no consecutive numbers and no number-after-text."""
    import os
    import re
    from hexai_pdf_parser.extractors.personal_credit_report import parse_personal_credit_report

    pdf_path = os.path.join(
        "D:\\codes\\PDFLayoutParser",
        "个人信用报告",
        "test",
        "test",
        "2_PDFsam_3e8ccb25-0108-449d-a8a4-04646b5d6b36-贷款38-45.pdf",
    )
    if not os.path.exists(pdf_path):
        pytest.skip(f"Test file not found: {pdf_path}")

    res = parse_personal_credit_report(pdf_path, use_ml_table_detector=False)
    blocks = res["pages"][0]["blocks"]

    prev_num = None
    for i, b in enumerate(blocks):
        txt = b["content"].strip()
        is_num = bool(re.match(r"^\d+\.$", txt))
        assert not (is_num and prev_num), f"Found consecutive numbers: '{prev_num}' and '{txt}' at block {i}"
        prev_num = txt if is_num else None

    # Check specifically around 38-45 that 39. comes before the loan text
    for i, b in enumerate(blocks):
        if b["content"].strip() == "39.":
            assert i + 1 < len(blocks)
            next_content = blocks[i + 1]["content"]
            assert "2020年12月18日" in next_content, f"Expected 2020年12月18日 after 39., got {next_content}"
            break
