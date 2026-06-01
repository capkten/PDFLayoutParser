"""Specialized financial header normalization helpers.

This module keeps the complex grouped-financial-header handling behind a
dedicated entrypoint so the generic table header normalizer can remain
lightweight.  The implementation deliberately reuses the existing grouped
header promotion helpers from :mod:`hexai_pdf_parser.table_header_normalizer`
to avoid duplicating the promotion logic.
"""

from __future__ import annotations

import fitz

from hexai_pdf_parser.models import Table


def normalize_complex_financial_header(table: Table, page: fitz.Page) -> Table:
    """Normalize a complex financial header when the pattern is recognized.

    The detection and promotion logic stay in the existing grouped-header
    helpers.  This function is a narrow wrapper that gives the specialized
    path its own module boundary.
    """
    from hexai_pdf_parser.table_header_normalizer import (
        _looks_like_grouped_financial_header,
        _promote_grouped_header,
    )

    if not _looks_like_grouped_financial_header(table, page):
        return table
    return _promote_grouped_header(table, page)
