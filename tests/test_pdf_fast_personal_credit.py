from __future__ import annotations

import math

import fitz
import pytest

from hexai_pdf_parser import _pdf_fast
from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot
from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.rust_adapter import page_snapshot_to_rust_input
from hexai_pdf_parser.extractors.personal_credit_report import _make_query_tables


def _empty_personal_credit_input(*, tolerance: float = 2.2) -> dict:
    document = fitz.open()
    try:
        page = document.new_page(width=595, height=842)
        snapshot = capture_page_snapshot(page, page_index=0)
        return {
            "schema_version": 1,
            "snapshot": page_snapshot_to_rust_input(snapshot),
            "wired_line_tolerance": tolerance,
        }
    finally:
        document.close()


def _query_fixture(
    *,
    include_header: bool = True,
    include_record: bool = True,
    include_title: bool = True,
    include_lead_record: bool = False,
    record_count: int | None = None,
):
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    if include_lead_record:
        page.insert_text((50, 45), "44", fontsize=10, fontname="china-s")
        page.insert_text((150, 45), "2024年09月02日", fontsize=10, fontname="china-s")
        page.insert_text((260, 45), "江南农村商业银行", fontsize=10, fontname="china-s")
        page.insert_text((420, 45), "贷后管理", fontsize=10, fontname="china-s")
    if include_title:
        page.insert_text((260, 80), "本人查询记录明细", fontsize=10, fontname="china-s")
    if include_header:
        page.insert_text((50, 100), "编号", fontsize=10, fontname="china-s")
        page.insert_text((150, 100), "查询日期", fontsize=10, fontname="china-s")
        page.insert_text((260, 100), "查询机构", fontsize=10, fontname="china-s")
        page.insert_text((420, 100), "查询原因", fontsize=10, fontname="china-s")
    count = (1 if include_header else 2) if include_record else 0
    if record_count is not None:
        count = record_count
    for row in range(count):
        record_y = (120 if include_header else 100) + row * 20
        page.insert_text((50, record_y), str(row + 1), fontsize=10, fontname="china-s")
        page.insert_text((150, record_y), f"2023年0{row + 1}月01日", fontsize=10, fontname="china-s")
        page.insert_text((260, record_y), f"测试银行{row + 1}", fontsize=10, fontname="china-s")
        page.insert_text((420, record_y), "信用卡审批", fontsize=10, fontname="china-s")

    snapshot = capture_page_snapshot(page, page_index=0)
    input_dto = {
        "schema_version": 1,
        "snapshot": page_snapshot_to_rust_input(snapshot),
        "wired_line_tolerance": 2.2,
    }
    expected = [_table_to_candidate(table) for table in _make_query_tables(page)]
    return document, input_dto, expected


def _wired_fixture():
    from hexai_pdf_parser.extractors.personal_credit_report import (
        PersonalCreditReportTableExtractor,
    )

    document = fitz.open()
    page = document.new_page(width=300, height=160)
    for y in (40, 62, 84):
        page.draw_line((40, y), (240, y), color=(0, 0, 0), width=0.5)
    for x in (40, 140, 240):
        page.draw_line((x, 40), (x, 84), color=(0, 0, 0), width=0.5)
    page.insert_text((50, 56), "Field", fontsize=10)
    page.insert_text((150, 56), "Value", fontsize=10)
    page.insert_text((50, 78), "Name", fontsize=10)
    page.insert_text((150, 78), "Alice", fontsize=10)

    snapshot = capture_page_snapshot(page, page_index=0)
    input_dto = {
        "schema_version": 1,
        "snapshot": page_snapshot_to_rust_input(snapshot),
        "wired_line_tolerance": 2.2,
    }
    tables = PersonalCreditReportTableExtractor(use_ml_table_detector=False).extract(page)
    return document, input_dto, [_table_to_candidate(table) for table in tables]


def _table_to_candidate(table) -> dict:
    def rect(box):
        return {
            "schema_version": 1,
            "x0": float(box.x0),
            "y0": float(box.y0),
            "x1": float(box.x1),
            "y1": float(box.y1),
        }

    return {
        "schema_version": 1,
        "rect": rect(table.bbox),
        "source": table.source,
        "confidence": table.confidence,
        "rows": table.rows,
        "cols": table.cols,
        "cells": [
            {
                "schema_version": 1,
                "text": cell.text,
                "row": cell.row_index,
                "col": cell.col_index,
                "rect": rect(cell.bbox),
                "rowspan": cell.rowspan,
                "colspan": cell.colspan,
                "source": None,
            }
            for cell in table.cells
        ],
    }


def _run_candidate_tables(candidates):
    input_dto = _empty_personal_credit_input()
    input_dto["candidate_tables"] = [_table_to_candidate(table) for table in candidates]
    return rust_adapter.recover_personal_credit_tables(input_dto)


def test_personal_credit_binding_is_registered():
    assert callable(getattr(_pdf_fast, "recover_personal_credit_tables", None))


def test_personal_credit_binding_rejects_missing_snapshot():
    recover = getattr(_pdf_fast, "recover_personal_credit_tables", None)
    assert callable(recover)

    with pytest.raises((TypeError, ValueError), match="snapshot"):
        recover({"schema_version": 1})


def test_personal_credit_binding_returns_versioned_empty_output():
    result = rust_adapter.recover_personal_credit_tables(
        _empty_personal_credit_input()
    )

    assert result == {"schema_version": 1, "tables": [], "diagnostics": []}


def test_rust_personal_credit_recovers_query_table_like_python():
    document, input_dto, expected = _query_fixture()
    try:
        result = rust_adapter.recover_personal_credit_tables(input_dto)
    finally:
        document.close()

    assert result["tables"] == expected


def test_rust_personal_credit_recovers_wired_table_like_python():
    document, input_dto, expected = _wired_fixture()
    try:
        result = rust_adapter.recover_personal_credit_tables(input_dto)
    finally:
        document.close()

    assert len(expected) == 1
    assert result["tables"] == expected


def test_rust_personal_credit_supplements_missing_wireless_candidates():
    from hexai_pdf_parser.extractors.personal_credit_report import (
        PersonalCreditReportTableExtractor,
    )

    document = fitz.open()
    page = document.new_page(width=420, height=180)
    page.insert_text((40, 45), "项目", fontsize=10, fontname="china-s")
    page.insert_text((260, 45), "金额", fontsize=10, fontname="china-s")
    for y, label, value in [(72, "收入", "1200"), (99, "支出", "800"), (126, "结余", "400")]:
        page.insert_text((40, y), label, fontsize=10, fontname="china-s")
        page.insert_text((260, y), value, fontsize=10, fontname="china-s")
    snapshot = capture_page_snapshot(page, page_index=0)
    expected = [
        _table_to_candidate(table)
        for table in PersonalCreditReportTableExtractor(
            use_ml_table_detector=False
        ).extract(page)
    ]
    input_dto = {
        "schema_version": 1,
        "snapshot": page_snapshot_to_rust_input(snapshot),
        "wired_line_tolerance": 2.2,
        "candidate_tables": [],
        "supplement_rust_candidates": True,
    }
    try:
        result = rust_adapter.recover_personal_credit_tables(input_dto)
    finally:
        document.close()

    assert len(expected) == 1
    assert result["tables"] == expected


def test_personal_credit_skips_rust_fullpage_supplement_when_disabled():
    document = fitz.open()
    page = document.new_page(width=420, height=180)
    page.insert_text((40, 45), "项目", fontsize=10, fontname="china-s")
    page.insert_text((260, 45), "金额", fontsize=10, fontname="china-s")
    for y, label, value in [(72, "收入", "1200"), (99, "支出", "800"), (126, "结余", "400")]:
        page.insert_text((40, y), label, fontsize=10, fontname="china-s")
        page.insert_text((260, y), value, fontsize=10, fontname="china-s")
    snapshot = capture_page_snapshot(page, page_index=0)
    input_dto = {
        "schema_version": 1,
        "snapshot": page_snapshot_to_rust_input(snapshot),
        "wired_line_tolerance": 2.2,
        "candidate_tables": [],
        "supplement_rust_candidates": False,
    }
    document.close()

    result = rust_adapter.recover_personal_credit_tables(input_dto)

    assert result["tables"] == []


def test_personal_credit_rust_entry_accepts_upstream_table_candidates():
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    candidate = Table(
        bbox=BBox(20.0, 20.0, 180.0, 60.0),
        rows=2,
        cols=2,
        cells=[
            Cell("Field", 0, 0, BBox(20.0, 20.0, 80.0, 40.0)),
            Cell("Value", 0, 1, BBox(80.0, 20.0, 180.0, 40.0)),
            Cell("Name", 1, 0, BBox(20.0, 40.0, 80.0, 60.0)),
            Cell("Alice", 1, 1, BBox(80.0, 40.0, 180.0, 60.0)),
        ],
        confidence=0.9,
        source="wireless_span_recovery",
    )
    input_dto = _empty_personal_credit_input()
    expected = _table_to_candidate(candidate)
    input_dto["candidate_tables"] = [expected]

    result = rust_adapter.recover_personal_credit_tables(input_dto)

    assert result["tables"] == [expected]


def test_personal_credit_adapter_roundtrips_table_candidates():
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    table = Table(
        bbox=BBox(20.0, 20.0, 180.0, 60.0),
        rows=2,
        cols=2,
        cells=[Cell("A", 0, 0, BBox(20.0, 20.0, 80.0, 40.0))],
        confidence=0.9,
        source="line_projection",
    )
    expected = _table_to_candidate(table)

    restored = rust_adapter.personal_credit_tables_to_project(
        {"schema_version": 1, "tables": [expected], "diagnostics": []}
    )

    assert [_table_to_candidate(item) for item in restored] == [expected]


def test_personal_credit_snapshot_adapter_includes_candidate_tables():
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    document = fitz.open()
    try:
        page = document.new_page(width=300, height=160)
        snapshot = capture_page_snapshot(page, page_index=0)
    finally:
        document.close()
    table = Table(
        bbox=BBox(20.0, 20.0, 180.0, 60.0),
        rows=1,
        cols=1,
        cells=[Cell("A", 0, 0, BBox(20.0, 20.0, 180.0, 60.0))],
        source="wireless_span_recovery",
    )

    result = rust_adapter.personal_credit_snapshot_to_rust_input(
        snapshot, 2.2, [table]
    )

    assert result["candidate_tables"] == [_table_to_candidate(table)]


def test_rust_personal_credit_filters_numbered_prose_candidate():
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    table = Table(
        bbox=BBox(36.0, 400.0, 550.0, 500.0),
        rows=2,
        cols=2,
        source="wireless_span_recovery",
        cells=[
            Cell("信用卡", 0, 0, BBox(36.0, 410.0, 80.0, 422.0)),
            Cell("账户明细如下", 0, 1, BBox(80.0, 410.0, 220.0, 422.0)),
            Cell("1. 2017年03月11日交通银行股份有限公司发放的贷记卡及透支账户", 1, 0, BBox(36.0, 430.0, 290.0, 442.0)),
            Cell("卡片尾号2344，2026年07月到期，信用额度54,000元", 1, 1, BBox(290.0, 430.0, 550.0, 442.0)),
        ],
    )

    result = _run_candidate_tables([table])

    assert result["tables"] == []


def test_rust_personal_credit_filters_report_metadata_candidate():
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    table = Table(
        bbox=BBox(30.0, 30.0, 260.0, 60.0),
        rows=2,
        cols=2,
        source="wireless_span_recovery",
        cells=[
            Cell("报告编号", 0, 0, BBox(30.0, 30.0, 100.0, 45.0)),
            Cell("12345", 0, 1, BBox(100.0, 30.0, 160.0, 45.0)),
            Cell("证件号码", 1, 0, BBox(30.0, 45.0, 100.0, 60.0)),
            Cell("4401", 1, 1, BBox(100.0, 45.0, 160.0, 60.0)),
        ],
    )

    result = _run_candidate_tables([table])

    assert result["tables"] == []


def test_rust_personal_credit_splits_repeated_record_candidate_like_python():
    from hexai_pdf_parser.core.models import BBox, Cell, Table
    from hexai_pdf_parser.extractors.personal_credit_report import (
        PersonalCreditReportTableExtractor,
    )

    table = Table(
        bbox=BBox(30.0, 30.0, 260.0, 90.0),
        rows=4,
        cols=1,
        source="wireless_span_recovery",
        cells=[
            Cell("处罚机构甲", 0, 0, BBox(30.0, 30.0, 200.0, 45.0)),
            Cell("处罚内容", 1, 0, BBox(30.0, 45.0, 200.0, 60.0)),
            Cell("立案法院乙", 2, 0, BBox(30.0, 60.0, 200.0, 75.0)),
            Cell("执行情况", 3, 0, BBox(30.0, 75.0, 200.0, 90.0)),
        ],
    )
    expected = [
        _table_to_candidate(item)
        for item in PersonalCreditReportTableExtractor._split_repeated_record_table(table)
    ]

    result = _run_candidate_tables([table])

    assert result["tables"] == expected


@pytest.mark.parametrize(
    "fixture_options",
    [
        {
            "include_header": False,
            "include_record": True,
            "include_title": False,
            "record_count": 2,
        },
        {"include_header": True, "include_record": False},
    ],
    ids=["headerless-continuation", "header-only-continuation"],
)
def test_rust_personal_credit_matches_query_continuation_like_python(fixture_options):
    document, input_dto, expected = _query_fixture(**fixture_options)
    try:
        result = rust_adapter.recover_personal_credit_tables(input_dto)
    finally:
        document.close()

    assert result["tables"] == expected


def test_rust_personal_credit_recovers_lead_continuation_before_query_header():
    document, input_dto, expected = _query_fixture(include_lead_record=True)
    try:
        result = rust_adapter.recover_personal_credit_tables(input_dto)
    finally:
        document.close()

    assert len(expected) == 2
    assert result["tables"] == expected


def test_rust_personal_credit_keeps_upstream_order_before_query_tables():
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    document, input_dto, query_tables = _query_fixture()
    candidate = Table(
        bbox=BBox(20.0, 300.0, 180.0, 340.0),
        rows=1,
        cols=1,
        cells=[Cell("Earlier candidate", 0, 0, BBox(20.0, 300.0, 180.0, 340.0))],
        source="wireless_span_recovery",
    )
    input_dto["candidate_tables"] = [_table_to_candidate(candidate)]
    try:
        result = rust_adapter.recover_personal_credit_tables(input_dto)
    finally:
        document.close()

    assert result["tables"] == [_table_to_candidate(candidate), *query_tables]


@pytest.mark.parametrize("tolerance", [math.nan, math.inf, -1.0])
def test_personal_credit_binding_rejects_invalid_wired_tolerance(tolerance):
    recover = getattr(_pdf_fast, "recover_personal_credit_tables", None)
    assert callable(recover)

    with pytest.raises((TypeError, ValueError), match="wired_line_tolerance"):
        recover(_empty_personal_credit_input(tolerance=tolerance))
