"""Normalize PDF page rotation before coordinate-based processing."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import fitz


@contextmanager
def isolated_page(page: fitz.Page) -> Iterator[fitz.Page]:
    """Yield an in-memory page copy so mutating helpers cannot alter its source."""
    source_document = getattr(page, "parent", None)
    page_number = getattr(page, "number", None)
    if source_document is None or page_number is None or not hasattr(source_document, "insert_pdf"):
        yield page
        return

    document = fitz.open()
    try:
        document.insert_pdf(source_document, from_page=page_number, to_page=page_number)
        yield document[0]
    finally:
        document.close()


def normalize_page_rotation(page: fitz.Page) -> None:
    """Remove PDF page rotation and sanitize graphics state in memory so all page coordinates agree."""
    if getattr(page, "rotation", 0):
        try:
            page.set_rotation(0)
        except Exception:
            pass
    try:
        page.clean_contents()
    except Exception:
        pass
