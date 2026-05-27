"""Serialize Document and its nested models to a unified JSON file."""

import json
from typing import Any, Dict, List

from hexai_pdf_parser.models import (
    BBox,
    Block,
    Cell,
    Char,
    Document,
    Image,
    LayoutElement,
    Line,
    Page,
    RenderInfo,
    Seal,
    Span,
    Table,
    Word,
)


class JSONWriter:
    """Writes a :class:`Document` tree to a JSON file.

    The output follows the unified schema described in the design spec:
    top-level keys are ``document`` (metadata) and ``pages`` (list of pages).
    """

    def to_dict(self, document: Document) -> Dict[str, Any]:
        """Convert *document* to a dict without writing to disk."""
        return self._document_to_dict(document)

    def write(self, document: Document, output_path: str) -> None:
        """Convert *document* to dict and write it to *output_path*."""
        data = self._document_to_dict(document)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def write_page(self, page: Page, output_path: str) -> None:
        """Convert a single *page* to dict and write it to *output_path*."""
        data = self._page_to_dict(page)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    # --------------------------------------------------------------------- #
    # Recursive converters – one per model type
    # --------------------------------------------------------------------- #

    def _document_to_dict(self, document: Document) -> Dict[str, Any]:
        return {
            "document": {
                "file_name": document.file_name,
                "page_count": document.page_count,
            },
            "pages": [self._page_to_dict(p) for p in document.pages],
        }

    def _page_to_dict(self, page: Page) -> Dict[str, Any]:
        return {
            "index": page.index,
            "size": page.size,
            "rotation": page.rotation,
            "blocks": [self._block_to_dict(b) for b in page.blocks],
            "tables": [self._table_to_dict(t) for t in page.tables],
            "images": [self._image_to_dict(i) for i in page.images],
            "seals": [self._seal_to_dict(s) for s in page.seals],
            "render": self._render_info_to_dict(page.render),
            "layout_elements": [
                self._layout_element_to_dict(le) for le in page.layout_elements
            ],
        }

    def _char_to_dict(self, char: Char) -> Dict[str, Any]:
        return {
            "text": char.text,
            "bbox": {"x0": char.bbox.x0, "y0": char.bbox.y0, "x1": char.bbox.x1, "y1": char.bbox.y1},
            "font": char.font,
            "size": char.size,
            "color": char.color,
            "flags": char.flags,
        }

    def _word_to_dict(self, word: Word) -> Dict[str, Any]:
        return {
            "text": word.text,
            "bbox": {"x0": word.bbox.x0, "y0": word.bbox.y0, "x1": word.bbox.x1, "y1": word.bbox.y1},
            "chars": [self._char_to_dict(c) for c in word.chars],
        }

    def _line_to_dict(self, line: Line) -> Dict[str, Any]:
        return {
            "text": line.text,
            "bbox": {"x0": line.bbox.x0, "y0": line.bbox.y0, "x1": line.bbox.x1, "y1": line.bbox.y1},
            "words": [self._word_to_dict(w) for w in line.words],
        }

    def _block_to_dict(self, block: Block) -> Dict[str, Any]:
        return {
            "text": block.text,
            "bbox": {"x0": block.bbox.x0, "y0": block.bbox.y0, "x1": block.bbox.x1, "y1": block.bbox.y1},
            "lines": [self._line_to_dict(ln) for ln in block.lines],
        }

    def _span_to_dict(self, span: Span) -> Dict[str, Any]:
        return {
            "text": span.text,
            "bbox": {"x0": span.bbox.x0, "y0": span.bbox.y0, "x1": span.bbox.x1, "y1": span.bbox.y1},
            "font": span.font,
            "size": span.size,
        }

    def _cell_to_dict(self, cell: Cell) -> Dict[str, Any]:
        return {
            "text": cell.text,
            "row_index": cell.row_index,
            "col_index": cell.col_index,
            "bbox": {"x0": cell.bbox.x0, "y0": cell.bbox.y0, "x1": cell.bbox.x1, "y1": cell.bbox.y1},
            "rowspan": cell.rowspan,
            "colspan": cell.colspan,
        }

    def _table_to_dict(self, table: Table) -> Dict[str, Any]:
        return {
            "bbox": {"x0": table.bbox.x0, "y0": table.bbox.y0, "x1": table.bbox.x1, "y1": table.bbox.y1},
            "rows": table.rows,
            "cols": table.cols,
            "cells": [self._cell_to_dict(c) for c in table.cells],
            "confidence": table.confidence,
            "source": table.source,
        }

    def _image_to_dict(self, image: Image) -> Dict[str, Any]:
        return {
            "bbox": {"x0": image.bbox.x0, "y0": image.bbox.y0, "x1": image.bbox.x1, "y1": image.bbox.y1},
            "page_index": image.page_index,
            "resource_index": image.resource_index,
            "width": image.width,
            "height": image.height,
            "path": image.path,
            "ext": image.ext,
        }

    def _seal_to_dict(self, seal: Seal) -> Dict[str, Any]:
        return {
            "bbox": {"x0": seal.bbox.x0, "y0": seal.bbox.y0, "x1": seal.bbox.x1, "y1": seal.bbox.y1},
            "page_index": seal.page_index,
            "path": seal.path,
        }

    def _render_info_to_dict(self, render: RenderInfo) -> Dict[str, Any]:
        return {
            "path": render.path,
            "width": render.width,
            "height": render.height,
            "dpi": render.dpi,
        }

    def _layout_element_to_dict(self, element: LayoutElement) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": element.type,
            "bbox": {"x0": element.bbox.x0, "y0": element.bbox.y0, "x1": element.bbox.x1, "y1": element.bbox.y1},
            "order": element.order,
            "content": self._content_to_dict(element.content),
        }
        # Include nested text structures when present
        if element.spans:
            result["spans"] = [self._span_to_dict(s) for s in element.spans]
        if element.lines:
            result["lines"] = [self._line_to_dict(ln) for ln in element.lines]
        if element.words:
            result["words"] = [self._word_to_dict(w) for w in element.words]
        if element.chars:
            result["chars"] = [self._char_to_dict(c) for c in element.chars]
        return result

    def _content_to_dict(self, content: Any) -> Any:
        """Dispatch content to the correct converter based on its type."""
        if content is None:
            return None
        if isinstance(content, Table):
            return self._table_to_dict(content)
        if isinstance(content, Image):
            return self._image_to_dict(content)
        if isinstance(content, Seal):
            return self._seal_to_dict(content)
        if isinstance(content, Block):
            return self._block_to_dict(content)
        # Fallback for plain values (strings, numbers, etc.)
        return content
