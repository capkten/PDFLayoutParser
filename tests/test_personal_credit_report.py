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
