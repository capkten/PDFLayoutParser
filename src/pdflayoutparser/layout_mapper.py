"""Layout mapper: normalizes raw text blocks into LayoutElements.

This module bridges the text_extractor (raw text hierarchy) and the
layout_builder (unified layout) by converting Block objects into the
common LayoutElement model.
"""

from typing import List

from pdflayoutparser.models import Block, Char, LayoutElement, Line, Word


class LayoutMapper:
    """Maps a list of Blocks into LayoutElements."""

    def map_blocks(self, blocks: List[Block]) -> List[LayoutElement]:
        """Convert each Block into a LayoutElement.

        Args:
            blocks: Raw text blocks extracted from a PDF page.

        Returns:
            A list of LayoutElements with flattened words and chars.
        """
        elements: List[LayoutElement] = []
        for order, block in enumerate(blocks):
            words: List[Word] = []
            chars: List[Char] = []
            for line in block.lines:
                for word in line.words:
                    words.append(word)
                    chars.extend(word.chars)
            element = LayoutElement(
                type="text",
                bbox=block.bbox,
                order=order,
                content=block.text,
                lines=block.lines,
                words=words,
                chars=chars,
            )
            elements.append(element)
        return elements
