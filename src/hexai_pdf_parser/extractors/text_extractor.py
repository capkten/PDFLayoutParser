"""Text extractor module.

Extracts a hierarchical text structure (blocks -> lines -> words -> chars)
from a PyMuPDF ``fitz.Page``.
"""

from typing import Dict, List, Tuple

import fitz

from hexai_pdf_parser.core.models import Block, BBox, Char, Line, Table, Word


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

                line_text = self._join_words(words)
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

    def extract_layout_blocks(
        self,
        page: fitz.Page,
        tables: List[Table],
    ) -> List[Block]:
        """Extract line-sized blocks for final page layout ordering.

        The raw block structure is retained for wireless-table detection, but
        it can combine unrelated visual lines.  Final layout text is rebuilt
        from individual PDF lines and excludes words assigned to tables.
        """
        page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks: List[Block] = []

        for block_dict in page_dict.get("blocks", []):
            if block_dict.get("type") != 0:
                continue

            for line_dict in block_dict.get("lines", []):
                words = self._words_from_spans(line_dict.get("spans", []))
                if not words:
                    continue

                outside_words: List[Word] = []
                for word in words:
                    if self._word_inside_any_table(word, tables):
                        if outside_words:
                            blocks.append(self._block_from_words(outside_words))
                            outside_words = []
                        continue
                    outside_words.append(word)

                if outside_words:
                    blocks.append(self._block_from_words(outside_words))

        return sorted(
            blocks,
            key=lambda block: (
                block.bbox.y0,
                block.bbox.x0,
                block.bbox.y1,
                block.bbox.x1,
            ),
        )

    def _words_from_spans(self, spans: List[dict]) -> List[Word]:
        words: List[Word] = []
        for span_dict in spans:
            span_text = span_dict.get("text", "")
            if not span_text.strip():
                continue

            span_bbox = BBox(*span_dict["bbox"])
            span_font = span_dict.get("font")
            span_size = span_dict.get("size")
            chars: List[Char] = []
            raw_chars = span_dict.get("chars")
            if raw_chars:
                for char_dict in raw_chars:
                    chars.append(
                        Char(
                            text=char_dict.get("c", ""),
                            bbox=BBox(*char_dict["bbox"]),
                            font=char_dict.get("font", span_font),
                            size=char_dict.get("size", span_size),
                        )
                    )
            else:
                span_width = span_bbox.x1 - span_bbox.x0
                char_count = len(span_text)
                if char_count > 0:
                    char_width = span_width / char_count
                    for index, char in enumerate(span_text):
                        chars.append(
                            Char(
                                text=char,
                                bbox=BBox(
                                    span_bbox.x0 + index * char_width,
                                    span_bbox.y0,
                                    span_bbox.x0 + (index + 1) * char_width,
                                    span_bbox.y1,
                                ),
                                font=span_font,
                                size=span_size,
                            )
                        )

            words.append(Word(text=span_text, bbox=span_bbox, chars=chars))
        return words

    def _block_from_words(self, words: List[Word]) -> Block:
        line = Line(
            text=self._join_words(words),
            bbox=BBox(
                min(word.bbox.x0 for word in words),
                min(word.bbox.y0 for word in words),
                max(word.bbox.x1 for word in words),
                max(word.bbox.y1 for word in words),
            ),
            words=words,
        )
        return Block(text=line.text, bbox=line.bbox, lines=[line])

    @staticmethod
    def _word_inside_any_table(word: Word, tables: List[Table]) -> bool:
        center_x = (word.bbox.x0 + word.bbox.x1) / 2.0
        center_y = (word.bbox.y0 + word.bbox.y1) / 2.0
        return any(
            table.bbox.x0 <= center_x <= table.bbox.x1
            and table.bbox.y0 <= center_y <= table.bbox.y1
            for table in tables
        )

    def _join_words(self, words: List[Word]) -> str:
        """Join words while preserving visible gaps between spans."""
        if not words:
            return ""

        parts = [words[0].text]
        for prev_word, word in zip(words, words[1:]):
            prev_text = prev_word.text or ""
            curr_text = word.text or ""
            if prev_text.endswith(" ") or curr_text.startswith(" "):
                parts.append(curr_text)
                continue

            gap = word.bbox.x0 - prev_word.bbox.x1
            if gap > 1.0:
                parts.append(" " + curr_text)
            else:
                parts.append(curr_text)

        return "".join(parts)

    def refine_blocks_for_tables(
        self,
        page: fitz.Page,
        blocks: List[Block],
        tables: List[Table],
    ) -> List[Block]:
        """Split only native text blocks that cross table boundaries.

        PyMuPDF can place text from a table and a neighboring note box in one
        native block. Keep the normal ``dict`` extraction as the default, and
        use word coordinates only for those crossing blocks.
        """
        if not blocks or not tables:
            return blocks

        crossing_indexes = [
            index
            for index, block in enumerate(blocks)
            if self._block_crosses_table(block.bbox, tables)
        ]
        if not crossing_indexes:
            return blocks

        try:
            words = page.get_text("words")
        except Exception:
            return blocks

        refined: List[Block] = []
        crossing_index_set = set(crossing_indexes)
        for index, block in enumerate(blocks):
            if index not in crossing_index_set:
                refined.append(block)
                continue

            split_blocks = self._split_block_by_table_words(
                block.bbox,
                words,
                tables,
            )
            refined.extend(split_blocks or [block])

        return refined

    def _block_crosses_table(self, bbox: BBox, tables: List[Table]) -> bool:
        for table in tables:
            table_bbox = table.bbox
            intersects = (
                bbox.x0 < table_bbox.x1
                and bbox.x1 > table_bbox.x0
                and bbox.y0 < table_bbox.y1
                and bbox.y1 > table_bbox.y0
            )
            if not intersects:
                continue

            fully_inside = (
                bbox.x0 >= table_bbox.x0
                and bbox.y0 >= table_bbox.y0
                and bbox.x1 <= table_bbox.x1
                and bbox.y1 <= table_bbox.y1
            )
            if not fully_inside:
                return True
        return False

    def _split_block_by_table_words(
        self,
        bbox: BBox,
        words: List[Tuple],
        tables: List[Table],
    ) -> List[Block]:
        selected = []
        for word in words:
            word_bbox = BBox(*word[:4])
            center_x = (word_bbox.x0 + word_bbox.x1) / 2.0
            center_y = (word_bbox.y0 + word_bbox.y1) / 2.0
            if not (
                bbox.x0 <= center_x <= bbox.x1
                and bbox.y0 <= center_y <= bbox.y1
            ):
                continue
            selected.append(word)

        if not selected:
            return []

        selected.sort(key=lambda word: (word[5], word[6], word[7], word[0]))
        line_groups: Dict[Tuple[int, int], List[Tuple]] = {}
        for word in selected:
            line_groups.setdefault((word[5], word[6]), []).append(word)

        segments: List[Tuple[object, List[Tuple]]] = []
        for line_words in line_groups.values():
            line_words.sort(key=lambda word: (word[7], word[0]))
            current_region = None
            current_words: List[Tuple] = []
            for word in line_words:
                region = self._word_table_index(word, tables)
                if current_words and region != current_region:
                    segments.append((current_region, current_words))
                    current_words = []
                current_region = region
                current_words.append(word)
            if current_words:
                segments.append((current_region, current_words))

        grouped: List[Tuple[object, List[List[Tuple]]]] = []
        for region, line_words in segments:
            if not grouped or grouped[-1][0] != region:
                grouped.append((region, []))
            grouped[-1][1].append(line_words)

        result = []
        for _, grouped_lines in grouped:
            lines: List[Line] = []
            for line_words in grouped_lines:
                word_objects = [
                    Word(text=word[4], bbox=BBox(*word[:4]))
                    for word in line_words
                ]
                line_bbox = BBox(
                    min(word.bbox.x0 for word in word_objects),
                    min(word.bbox.y0 for word in word_objects),
                    max(word.bbox.x1 for word in word_objects),
                    max(word.bbox.y1 for word in word_objects),
                )
                lines.append(
                    Line(
                        text=self._join_words(word_objects),
                        bbox=line_bbox,
                        words=word_objects,
                    )
                )

            result.append(
                Block(
                    text="\n".join(line.text for line in lines),
                    bbox=BBox(
                        min(line.bbox.x0 for line in lines),
                        min(line.bbox.y0 for line in lines),
                        max(line.bbox.x1 for line in lines),
                        max(line.bbox.y1 for line in lines),
                    ),
                    lines=lines,
                )
            )
        return result

    @staticmethod
    def _word_table_index(word: tuple, tables: List[Table]) -> object:
        center_x = (word[0] + word[2]) / 2.0
        center_y = (word[1] + word[3]) / 2.0
        for index, table in enumerate(tables):
            bbox = table.bbox
            if bbox.x0 <= center_x <= bbox.x1 and bbox.y0 <= center_y <= bbox.y1:
                return index
        return None
