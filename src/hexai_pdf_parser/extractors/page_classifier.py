"""Page type classifier module.

Classifies PDF pages into either 'vector' (digitally extractable born-digital text)
or 'scanned' (raster scanned images, vector-outlined text, or Type 3 fonts lacking
ToUnicode mapping that require OCR processing).
"""

from __future__ import annotations

from typing_extensions import Literal

import fitz


def classify_page_type(page: fitz.Page) -> Literal["vector", "scanned"]:
    """Classify a PDF page as either 'vector' or 'scanned'.

    Returns:
        "scanned": if the page text is empty, contains garbled/control characters,
                   uses Type 3 fonts without ToUnicode, has distorted BBoxes, or
                   consists of vector-outlined drawing paths.
        "vector":  if the page contains normal, extractable digital text.
    """
    if is_scanned_page(page):
        return "scanned"
    return "vector"


def is_scanned_page(page: fitz.Page) -> bool:
    """Return True if the page should be treated as a scanned page (requires OCR)."""
    try:
        text = page.get_text("text")
    except Exception:
        return True

    clean_text = text.strip() if text else ""

    # 1. Empty or virtually empty text
    if not clean_text:
        return True

    # 2. Garbled / non-printable control characters or replacement characters
    if _check_garbled_control_characters(text):
        return True

    # 3. Type 3 font without /ToUnicode CMap mapping
    if _check_type3_missing_tounicode(page):
        return True

    # 4. Text Bounding Box severe distortion (e.g. height bloated or negative y0)
    if _check_bbox_distortion(page):
        return True

    # 5. Vector-outlined text drawings (文字转曲)
    if _check_vector_outlined_drawings(page, clean_text):
        return True

    # 6. Very short text dominated by large background raster image
    if len(clean_text) <= 10 and _has_fullpage_raster_image(page):
        return True

    return False


def _check_garbled_control_characters(text: str) -> bool:
    """Return whether any extracted character cannot represent normal text."""
    if not text:
        return False

    invalid_count = sum(
        1 for c in text
        if (ord(c) < 32 and c not in ("\n", "\r", "\t")) or c == "\ufffd" or ord(c) == 0
    )
    return invalid_count > 0


def _check_type3_missing_tounicode(page: fitz.Page) -> bool:
    """Return whether any Type 3 font on the page lacks a ToUnicode map."""
    try:
        fonts = page.get_fonts(full=True)
    except Exception:
        return False

    for font in fonts:
        font_type = font[2]
        if font_type == "Type3":
            xref = font[0]
            # get_fonts()[5] is the font encoding, not the ToUnicode resource.
            if xref <= 0 or not page.parent:
                return True
            try:
                obj = page.parent.xref_object(xref)
            except Exception:
                return True
            if "/ToUnicode" not in obj:
                return True

    return False


def _check_bbox_distortion(page: fitz.Page) -> bool:
    """Check if text blocks have severe bounding box distortion."""
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return False

    page_height = float(page.rect.height) if getattr(page, "rect", None) else 842.0

    for block in blocks:
        if len(block) >= 5:
            x0, y0, x1, y1, text = block[:5]
            h = y1 - y0
            # Negative start coordinate exceeding margin
            if y0 < -10:
                return True
            # Single line/short text with abnormal height spanning > 25% of page
            text_lines = str(text or "").strip().splitlines()
            if len(text_lines) <= 2 and h > page_height * 0.25 and len(str(text or "").strip()) < 50:
                return True

    return False


def _check_vector_outlined_drawings(page: fitz.Page, clean_text: str) -> bool:
    """Check if text has been outlined into vector path drawings."""
    # If text is already rich (> 50 valid characters), unlikely to be pure outlined page
    if len(clean_text) > 50:
        return False

    try:
        drawings = page.get_drawings()
    except Exception:
        return False

    if not drawings:
        return False

    total_drawing_count = len(drawings)
    total_path_items = sum(len(d.get("items", [])) for d in drawings)

    # 1. Multiple discrete small drawings (e.g. 10+ separate glyph paths)
    small_glyph_drawings = 0
    for d in drawings:
        rect = d.get("rect")
        if rect:
            w = rect.width
            h = rect.height
            if 4 <= w <= 80 and 4 <= h <= 80:
                small_glyph_drawings += 1

    if small_glyph_drawings >= 10:
        return True

    # 2. Or many path segments/items with very little text (< 15 chars)
    if total_path_items >= 30 and len(clean_text) < 15:
        return True

    # 3. Many drawings with low text
    if total_drawing_count >= 20 and len(clean_text) < 20:
        return True

    return False


def _has_fullpage_raster_image(page: fitz.Page) -> bool:
    """Check if the page has a raster image covering a major portion of the page."""
    try:
        images = page.get_images()
        if not images:
            return False
        page_area = float(page.rect.width * page.rect.height)
        for img in images:
            xref = img[0]
            for rect in page.get_image_rects(xref):
                if (rect.width * rect.height) >= page_area * 0.60:
                    return True
    except Exception:
        pass
    return False
