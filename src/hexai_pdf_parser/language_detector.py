"""Language detector for PDF pages.

Detects whether a page is primarily Chinese, English, or mixed,
based on character analysis.
"""

from __future__ import annotations

import re
from typing import Literal

import fitz


def detect_page_language(page: fitz.Page) -> Literal["zh", "en", "mixed"]:
    """Detect the primary language of a PDF page.

    Returns:
        "zh" if Chinese characters > 30%
        "en" if Chinese characters < 5%
        "mixed" otherwise
    """
    try:
        text = page.get_text("text")
    except Exception:
        return "en"

    if not text or not text.strip():
        return "en"

    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(text.strip())

    if total_chars == 0:
        return "en"

    ratio = chinese_chars / total_chars

    if ratio > 0.3:
        return "zh"
    elif ratio < 0.05:
        return "en"
    return "mixed"


def detect_document_language(pdf_path: str, sample_pages: int = 3) -> Literal["zh", "en", "mixed"]:
    """Detect the primary language of a PDF document.

    Samples the first few pages to determine the overall language.

    Args:
        pdf_path: Path to the PDF file
        sample_pages: Number of pages to sample (default 3)

    Returns:
        "zh", "en", or "mixed"
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return "en"

    total_chinese = 0
    total_chars = 0

    for i in range(min(sample_pages, len(doc))):
        try:
            text = doc[i].get_text("text")
            if text:
                total_chinese += len(re.findall(r'[\u4e00-\u9fff]', text))
                total_chars += len(text.strip())
        except Exception:
            continue

    doc.close()

    if total_chars == 0:
        return "en"

    ratio = total_chinese / total_chars

    if ratio > 0.3:
        return "zh"
    elif ratio < 0.05:
        return "en"
    return "mixed"
