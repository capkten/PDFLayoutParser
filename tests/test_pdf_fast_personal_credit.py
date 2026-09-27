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
    record_count: int | None = None,
):
    document = fitz.open()
    page = document.new_page(width=595, height=842)
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


@pytest.mark.parametrize("tolerance", [math.nan, math.inf, -1.0])
def test_personal_credit_binding_rejects_invalid_wired_tolerance(tolerance):
    recover = getattr(_pdf_fast, "recover_personal_credit_tables", None)
    assert callable(recover)

    with pytest.raises((TypeError, ValueError), match="wired_line_tolerance"):
        recover(_empty_personal_credit_input(tolerance=tolerance))
