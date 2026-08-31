"""Normalize PDF page rotation before coordinate-based processing."""

from __future__ import annotations

import fitz


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
