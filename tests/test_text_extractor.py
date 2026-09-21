"""Tests for the text extractor."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import fitz

from hexai_pdf_parser.models import BBox, Block, Table
from hexai_pdf_parser.text_extractor import TextExtractor
from tests.conftest import make_text_pdf


def _raw_char(char, x, y0, y1, origin_y, *, font="SourceHanSerifCN-Regular", size=9, flags=0):
    return {
        "c": char,
        "bbox": (x, y0, x + 8, y1),
        "origin": (x, origin_y),
        "font": font,
        "size": size,
        "flags": flags,
    }


def _rawdict_page(blocks):
    def get_text(mode, *args, **kwargs):
        assert mode == "rawdict"
        assert kwargs["flags"] == fitz.TEXT_PRESERVE_WHITESPACE
        return {"blocks": blocks}

    return SimpleNamespace(
        get_text=get_text,
    )


class TestTextExtractor:
    def test_native_character_layout_bbox_rejects_anomalous_height_for_order(self):
        font = "SourceHanSerifCN-Regular"
        normal_chars = [
            _raw_char(
                chr(ord("a") + index),
                10 + index * 8,
                0,
                10,
                10,
                font=font,
            )
            for index in range(12)
        ]
        anomalous_char = _raw_char(
            "M",
            106,
            -3,
            25,
            10,
            font=font,
        )
        next_line_chars = [
            _raw_char("2", 10, 15, 25, 25, font=font),
            _raw_char(".", 18, 15, 25, 25, font=font),
        ]
        page = _rawdict_page(
            [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "bbox": (10, -3, 114, 25),
                                    "font": font,
                                    "size": 9,
                                    "flags": 0,
                                    "chars": normal_chars + [anomalous_char],
                                }
                            ]
                        },
                        {
                            "spans": [
                                {
                                    "bbox": (10, 15, 26, 25),
                                    "font": font,
                                    "size": 9,
                                    "flags": 0,
                                    "chars": next_line_chars,
                                }
                            ]
                        },
                    ],
                }
            ]
        )

        blocks = TextExtractor().extract_layout_blocks(page, [])

        assert [block.text for block in blocks] == ["abcdefghijklM", "2."]
        word = blocks[0].lines[0].words[0]
        assert word.chars[-1].bbox.y0 == -3
        assert word.chars[-1].bbox.y1 == 25
        assert word.bbox.y0 == 0
        assert word.bbox.y1 == 10
        assert blocks[0].lines[0].bbox.y0 == 0
        assert blocks[0].lines[0].bbox.y1 == 10
        assert blocks[0].bbox.y0 == 0
        assert blocks[0].bbox.y1 == 10

    def test_native_character_layout_bbox_preserves_real_larger_font_height(self):
        page = _rawdict_page(
            [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "bbox": (10, 0, 26, 9),
                                    "font": "SourceHanSerifCN-Regular",
                                    "size": 9,
                                    "flags": 0,
                                    "chars": [
                                        _raw_char("a", 10, 0, 9, 9, size=9),
                                        _raw_char("b", 18, 0, 9, 9, size=9),
                                    ],
                                },
                                {
                                    "bbox": (40, -5, 56, 14),
                                    "font": "SourceHanSerifCN-Regular",
                                    "size": 14,
                                    "flags": 0,
                                    "chars": [
                                        _raw_char("X", 40, -5, 14, 9, size=14),
                                        _raw_char("Y", 48, -5, 14, 9, size=14),
                                    ],
                                },
                            ]
                        }
                    ],
                }
            ]
        )

        blocks = TextExtractor().extract_layout_blocks(page, [])

        assert len(blocks) == 1
        assert [word.text for word in blocks[0].lines[0].words] == ["ab", "XY"]
        assert blocks[0].lines[0].words[1].bbox.y1 - blocks[0].lines[0].words[1].bbox.y0 == 19

    def test_native_character_layout_falls_back_to_span_text_without_chars(self):
        page = _rawdict_page(
            [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {
                                    "text": "fallback",
                                    "bbox": (10, 0, 74, 9),
                                    "font": "SourceHanSerifCN-Regular",
                                    "size": 9,
                                    "flags": 0,
                                }
                            ]
                        }
                    ],
                }
            ]
        )

        blocks = TextExtractor().extract_layout_blocks(page, [])

        word = blocks[0].lines[0].words[0]
        assert word.text == "fallback"
        assert len(word.chars) == len(word.text)
        assert word.bbox.y0 == 0
        assert word.bbox.y1 == 9

    def test_extract_layout_blocks_orders_lines_and_excludes_tables(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "layout-lines.pdf"

        import fitz

        doc = fitz.open()
        page = doc.new_page(width=300, height=300)
        page.insert_text((20, 100), "1.")
        page.insert_text((40, 100), "First body line")
        page.insert_text((20, 115), "2.")
        page.insert_text((40, 115), "Second body line")
        page.insert_text((40, 160), "TABLE TEXT")
        doc.save(pdf_path)
        doc.close()

        table = Table(
            bbox=BBox(30, 145, 150, 175),
            rows=1,
            cols=1,
        )
        with fitz.open(pdf_path) as doc:
            blocks = TextExtractor().extract_layout_blocks(doc[0], [table])

        texts = [block.text for block in blocks]
        assert texts == ["1. First body line", "2. Second body line"]
        assert "TABLE TEXT" not in texts

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

    def test_joining_multiple_spans_keeps_word_boundaries(self):
        page = SimpleNamespace(
            get_text=lambda *args, **kwargs: {
                "blocks": [
                    {
                        "type": 0,
                        "bbox": (0, 0, 100, 20),
                        "lines": [
                            {
                                "bbox": (0, 0, 100, 20),
                                "spans": [
                                    {
                                        "text": "Hello",
                                        "bbox": (0, 0, 40, 20),
                                        "font": "Helvetica",
                                        "size": 11,
                                    },
                                    {
                                        "text": "World",
                                        "bbox": (45, 0, 90, 20),
                                        "font": "Helvetica",
                                        "size": 11,
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        )

        extractor = TextExtractor()
        blocks = extractor.extract_blocks(page)

        assert len(blocks) == 1
        assert blocks[0].lines[0].text == "Hello World"
        assert blocks[0].text == "Hello World"

    def test_refines_only_blocks_that_cross_table_boundary(self):
        block = Block(
            text="inside\noutside",
            bbox=BBox(0, 0, 150, 30),
        )
        table = Table(bbox=BBox(0, 0, 100, 30), rows=1, cols=1)
        page = SimpleNamespace(
            get_text=lambda mode: [
                (10, 10, 20, 20, "inside", 0, 0, 0),
                (110, 10, 120, 20, "outside", 0, 1, 0),
            ]
        )

        result = TextExtractor().refine_blocks_for_tables(
            page,
            [block],
            [table],
        )

        assert [item.text for item in result] == ["inside", "outside"]
        assert result[0].bbox.x1 == 20
        assert result[1].bbox.x0 == 110

    def test_does_not_request_words_without_a_crossing_block(self):
        block = Block(
            text="inside",
            bbox=BBox(10, 10, 20, 20),
        )
        table = Table(bbox=BBox(0, 0, 100, 30), rows=1, cols=1)

        def unexpected_words_call(mode):
            raise AssertionError("word extraction should not be requested")

        page = SimpleNamespace(get_text=unexpected_words_call)

        result = TextExtractor().refine_blocks_for_tables(
            page,
            [block],
            [table],
        )

        assert result == [block]
