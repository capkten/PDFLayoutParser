"""Text extractor module.

Extracts a hierarchical text structure (blocks -> lines -> words -> chars)
from a PyMuPDF ``fitz.Page``.
"""

from typing import List

import fitz

from pdflayoutparser.models import Block, BBox, Char, Line, Word


class TextExtractor:
    """Extract text hierarchy from a PDF page.

    Example::

        extractor = TextExtractor()
        blocks = extractor.extract_blocks(page)
    """

    def extract_blocks(self, page: fitz.Page) -> List[Block]:
        """Return a list of :class:`Block` objects for the given *page*."""
        page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks: List[Block] = []

        for block_dict in page_dict.get("blocks", []):
            if block_dict.get("type") != 0:
                continue

            block_bbox = BBox(*block_dict["bbox"])
            lines: List[Line] = []

            for line_dict in block_dict.get("lines", []):
                line_bbox = BBox(*line_dict["bbox"])
                words: List[Word] = []

                for span_dict in line_dict.get("spans", []):
                    span_text = span_dict.get("text", "")
                    span_bbox = BBox(*span_dict["bbox"])
                    span_font = span_dict.get("font")
                    span_size = span_dict.get("size")

                    chars: List[Char] = []
                    raw_chars = span_dict.get("chars")
                    if raw_chars:
                        for char_dict in raw_chars:
                            char_text = char_dict.get("c", "")
                            char_bbox = BBox(*char_dict["bbox"])
                            char_font = char_dict.get("font", span_font)
                            char_size = char_dict.get("size", span_size)
                            chars.append(
                                Char(
                                    text=char_text,
                                    bbox=char_bbox,
                                    font=char_font,
                                    size=char_size,
                                )
                            )
                    else:
                        # Synthesise chars when PyMuPDF does not provide them.
                        span_width = span_bbox.x1 - span_bbox.x0
                        char_count = len(span_text)
                        if char_count > 0:
                            char_width = span_width / char_count
                            for idx, ch in enumerate(span_text):
                                char_bbox = BBox(
                                    span_bbox.x0 + idx * char_width,
                                    span_bbox.y0,
                                    span_bbox.x0 + (idx + 1) * char_width,
                                    span_bbox.y1,
                                )
                                chars.append(
                                    Char(
                                        text=ch,
                                        bbox=char_bbox,
                                        font=span_font,
                                        size=span_size,
                                    )
                                )

                    words.append(
                        Word(
                            text=span_text,
                            bbox=span_bbox,
                            chars=chars,
                        )
                    )

                line_text = "".join(w.text for w in words)
                lines.append(
                    Line(
                        text=line_text,
                        bbox=line_bbox,
                        words=words,
                    )
                )

            block_text = "\n".join(l.text for l in lines)
            blocks.append(
                Block(
                    text=block_text,
                    bbox=block_bbox,
                    lines=lines,
                )
            )

        return blocks
