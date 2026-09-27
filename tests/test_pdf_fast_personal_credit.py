from __future__ import annotations

import math

import fitz
import pytest

from hexai_pdf_parser import _pdf_fast
from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot
from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.rust_adapter import page_snapshot_to_rust_input


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


@pytest.mark.parametrize("tolerance", [math.nan, math.inf, -1.0])
def test_personal_credit_binding_rejects_invalid_wired_tolerance(tolerance):
    recover = getattr(_pdf_fast, "recover_personal_credit_tables", None)
    assert callable(recover)

    with pytest.raises((TypeError, ValueError), match="wired_line_tolerance"):
        recover(_empty_personal_credit_input(tolerance=tolerance))
