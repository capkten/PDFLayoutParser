from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from hexai_pdf_parser.extractors.page_classifier import (
    classify_page_type,
    is_scanned_page,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SCANNED_PAGE_FIXTURE = FIXTURE_DIR / "page_705_scanned.pdf"
VECTOR_PAGE_FIXTURE = FIXTURE_DIR / "page_000_vector.pdf"


class _FakeParent:
    def __init__(self, objects):
        self.objects = objects

    def xref_object(self, xref):
        return self.objects[xref]


class _FakePage:
    rect = SimpleNamespace(width=595.0, height=842.0)

    def __init__(self, text, fonts=(), objects=None):
        self.text = text
        self.fonts = list(fonts)
        self.parent = _FakeParent(objects or {})

    def get_text(self, mode):
        if mode == "text":
            return self.text
        if mode == "blocks":
            return [(0.0, 0.0, 100.0, 12.0, self.text, 0, 0)]
        raise AssertionError(mode)

    def get_fonts(self, full=True):
        return self.fonts

    def get_drawings(self):
        return []

    def get_images(self):
        return []


def test_empty_page_classified_as_scanned():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    assert is_scanned_page(page) is True
    assert classify_page_type(page) == "scanned"
    doc.close()


def test_normal_digital_text_page_classified_as_vector():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Insert normal Chinese and English digital text
    page.insert_text((50, 100), "烟台美年大健康体检管理有限公司 审计报告 2025年", fontsize=12)
    page.insert_text((50, 130), "合并资产负债表 财务报表附注 第1页", fontsize=10)
    page.insert_text((50, 160), "This is a normal born-digital PDF page with extractable text.", fontsize=10)
    assert is_scanned_page(page) is False
    assert classify_page_type(page) == "vector"
    doc.close()


def test_garbled_control_characters_classified_as_scanned():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Insert garbled string with non-printable control characters
    garbled_text = "\x00\x00 \x00 \x00\x03\x04\x03\x05 \x04\x03\x04\x06\x03\x07\x04 \x00\x08\t\n\x0b\n\x0c\r\x0e\x0f"
    page.insert_text((50, 100), garbled_text, fontsize=12)
    assert is_scanned_page(page) is True
    assert classify_page_type(page) == "scanned"
    doc.close()


def test_single_unextractable_character_classified_as_scanned():
    page = _FakePage("A" * 100 + "\x00")

    assert is_scanned_page(page) is True


def test_single_replacement_character_classified_as_scanned():
    page = _FakePage("normal text\ufffd")

    assert is_scanned_page(page) is True


def test_mixed_type3_without_tounicode_classified_as_scanned():
    type3_font = (1, "n/a", "Type3", "T1", "T1", "", 0)
    true_type_font = (2, "n/a", "TrueType", "Arial", "F1", "WinAnsiEncoding", 0)
    page = _FakePage(
        "normal text",
        fonts=[type3_font, true_type_font],
        objects={1: "<< /Type /Font /Subtype /Type3 >>"},
    )

    assert is_scanned_page(page) is True


def test_type3_with_tounicode_remains_vector():
    type3_font = (1, "n/a", "Type3", "T1", "T1", "", 0)
    page = _FakePage(
        "normal text",
        fonts=[type3_font],
        objects={1: "<< /Type /Font /Subtype /Type3 /ToUnicode 3 0 R >>"},
    )

    assert is_scanned_page(page) is False


def test_vector_outlined_drawings_classified_as_scanned():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Insert almost no text
    page.insert_text((50, 100), "1", fontsize=10)
    # Draw many character-sized vector shapes (simulating vector-outlined text)
    shape = page.new_shape()
    for i in range(40):
        x = 50 + (i % 10) * 20
        y = 150 + (i // 10) * 25
        shape.draw_rect(fitz.Rect(x, y, x + 15, y + 15))
    shape.finish(fill=(0, 0, 0), color=(0, 0, 0))
    shape.commit()

    assert is_scanned_page(page) is True
    assert classify_page_type(page) == "scanned"
    doc.close()


def test_page_705_fixture_classified_as_scanned():
    doc = fitz.open(str(SCANNED_PAGE_FIXTURE))
    page = doc[0]
    assert is_scanned_page(page) is True
    assert classify_page_type(page) == "scanned"
    doc.close()


def test_vector_page_fixture_classified_as_vector():
    doc = fitz.open(str(VECTOR_PAGE_FIXTURE))
    page = doc[0]
    assert is_scanned_page(page) is False
    assert classify_page_type(page) == "vector"
    doc.close()
