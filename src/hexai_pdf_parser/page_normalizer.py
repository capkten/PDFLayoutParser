"""Normalize PDF page rotation before coordinate-based processing."""

from __future__ import annotations

import fitz


def normalize_page_rotation(page: fitz.Page) -> None:
    """Remove PDF page rotation in memory so all page coordinates agree."""
    if getattr(page, "rotation", 0):
        page.remove_rotation()
