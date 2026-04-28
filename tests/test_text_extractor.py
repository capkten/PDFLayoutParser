"""Tests for the text extractor."""

from pathlib import Path

import pytest

from pdflayoutparser.text_extractor import TextExtractor
from tests.conftest import make_text_pdf


class TestTextExtractor:
    def test_extract_blocks_and_lines(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "hello.pdf"
        make_text_pdf(pdf_path, text="Hello World")

        import fitz

        with fitz.open(pdf_path) as doc:
            page = doc[0]
            extractor = TextExtractor()
            blocks = extractor.extract_blocks(page)

        assert len(blocks) >= 1
        block = blocks[0]
        assert block.text == "Hello World"
        assert len(block.lines) >= 1
        line = block.lines[0]
        assert line.text == "Hello World"

    def test_extract_chars_when_available(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "ab.pdf"
        make_text_pdf(pdf_path, text="AB")

        import fitz

        with fitz.open(pdf_path) as doc:
            page = doc[0]
            extractor = TextExtractor()
            blocks = extractor.extract_blocks(page)

        assert len(blocks) == 1
        block = blocks[0]
        assert len(block.lines) == 1
        line = block.lines[0]
        assert len(line.words) == 1
        word = line.words[0]
        assert len(word.chars) == 2
        assert word.chars[0].text == "A"
        assert word.chars[1].text == "B"
        for char in word.chars:
            assert char.bbox is not None
            assert char.bbox.x0 < char.bbox.x1
            assert char.bbox.y0 < char.bbox.y1
