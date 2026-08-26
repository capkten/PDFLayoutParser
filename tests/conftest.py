import sys
import tempfile
from pathlib import Path

try:
    import pymupdf as fitz
    sys.modules['fitz'] = fitz
except ImportError:
    import fitz

import pytest


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


def make_text_pdf(path, text="Hello World"):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def make_multi_page_pdf(path, texts):
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def make_pdf_with_image(path):
    doc = fitz.open()
    page = doc.new_page()
    # Create a red 10x10 RGB image
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(100, 100, 200, 200), pixmap=pix)
    doc.save(path)
    doc.close()
