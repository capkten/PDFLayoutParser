"""Utilities for annotating rendered pages with their classified type."""

from __future__ import annotations

import fitz


_LABEL_FILL = (0.08, 0.08, 0.08)
_LABEL_TEXT = (1.0, 1.0, 1.0)


def draw_page_type_label(page: fitz.Page, page_type: str | None) -> None:
    """Draw a compact high-contrast page type label in the top-left corner."""
    if not page_type:
        return

    label = f"page_type: {page_type}"
    font_size = 8.0
    padding_x = 5.0
    badge_height = 14.0
    badge_width = min(
        max(96.0, len(label) * 4.8 + padding_x * 2),
        max(0.0, page.rect.width - 12.0),
    )
    if badge_width <= 0.0 or page.rect.height < badge_height + 12.0:
        return

    badge = fitz.Rect(
        page.rect.x0 + 6.0,
        page.rect.y0 + 6.0,
        page.rect.x0 + 6.0 + badge_width,
        page.rect.y0 + 6.0 + badge_height,
    )
    shape = page.new_shape()
    shape.draw_rect(badge)
    shape.finish(fill=_LABEL_FILL, color=_LABEL_FILL)
    shape.insert_text(
        fitz.Point(badge.x0 + padding_x, badge.y1 - 4.0),
        label,
        fontsize=font_size,
        color=_LABEL_TEXT,
    )
    shape.commit()
