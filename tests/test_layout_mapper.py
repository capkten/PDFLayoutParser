"""Tests for the layout mapper."""

import pytest

from hexai_pdf_parser.layout_mapper import LayoutMapper
from hexai_pdf_parser.models import BBox, Block, Char, Line, Word


class TestLayoutMapper:
    def test_map_text_block_to_layout_element(self):
        """A single Block with 1 Line, 1 Word, 1 Char produces a correct LayoutElement."""
        char = Char(text="A", bbox=BBox(x0=0, y0=0, x1=10, y1=10))
        word = Word(text="A", bbox=BBox(x0=0, y0=0, x1=10, y1=10), chars=[char])
        line = Line(text="A", bbox=BBox(x0=0, y0=0, x1=10, y1=10), words=[word])
        block = Block(text="A", bbox=BBox(x0=0, y0=0, x1=10, y1=10), lines=[line])

        mapper = LayoutMapper()
        result = mapper.map_blocks([block])

        assert len(result) == 1
        element = result[0]
        assert element.type == "text"
        assert element.bbox == block.bbox
        assert element.order == 0
        assert element.content == "A"
        assert element.lines == [line]
        assert element.words == [word]
        assert element.chars == [char]

    def test_map_multiple_blocks(self):
        """Two Blocks produce two LayoutElements with sequential order values."""
        char_a = Char(text="A", bbox=BBox(x0=0, y0=0, x1=5, y1=5))
        word_a = Word(text="A", bbox=BBox(x0=0, y0=0, x1=5, y1=5), chars=[char_a])
        line_a = Line(text="A", bbox=BBox(x0=0, y0=0, x1=5, y1=5), words=[word_a])
        block_a = Block(text="A", bbox=BBox(x0=0, y0=0, x1=5, y1=5), lines=[line_a])

        char_b = Char(text="B", bbox=BBox(x0=10, y0=10, x1=15, y1=15))
        word_b = Word(text="B", bbox=BBox(x0=10, y0=10, x1=15, y1=15), chars=[char_b])
        line_b = Line(text="B", bbox=BBox(x0=10, y0=10, x1=15, y1=15), words=[word_b])
        block_b = Block(text="B", bbox=BBox(x0=10, y0=10, x1=15, y1=15), lines=[line_b])

        mapper = LayoutMapper()
        result = mapper.map_blocks([block_a, block_b])

        assert len(result) == 2
        assert result[0].order == 0
        assert result[0].content == "A"
        assert result[1].order == 1
        assert result[1].content == "B"
