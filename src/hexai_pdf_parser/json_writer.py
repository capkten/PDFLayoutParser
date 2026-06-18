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
    TextChar,
    TextBlock,
    CellStructure,
    TableStructure,
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
        page_to_dict = self._page_to_dict
        return {
            "document": {
                "file_name": document.file_name,
                "page_count": document.page_count,
            },
            "pages": [page_to_dict(p) for p in document.pages],
        }

    def _page_to_dict(self, page: Page) -> Dict[str, Any]:
        block_to_dict = self._block_to_dict
        table_to_dict = self._table_to_dict
        image_to_dict = self._image_to_dict
        seal_to_dict = self._seal_to_dict
        layout_element_to_dict = self._layout_element_to_dict
        return {
            "index": page.index,
            "size": page.size,
            "rotation": page.rotation,
            "blocks": [block_to_dict(b) for b in page.blocks],
            "tables": [table_to_dict(t) for t in page.tables],
            "images": [image_to_dict(i) for i in page.images],
            "seals": [seal_to_dict(s) for s in page.seals],
            "render": self._render_info_to_dict(page.render),
            "layout_elements": [
                layout_element_to_dict(le) for le in page.layout_elements
            ],
        }

    def _char_to_dict(self, char: Char) -> Dict[str, Any]:
        cb = char.bbox
        return {
            "text": char.text,
            "bbox": {"x0": cb.x0, "y0": cb.y0, "x1": cb.x1, "y1": cb.y1},
            "font": char.font,
            "size": char.size,
            "color": char.color,
            "flags": char.flags,
        }

    def _word_to_dict(self, word: Word) -> Dict[str, Any]:
        wb = word.bbox
        char_to_dict = self._char_to_dict
        return {
            "text": word.text,
            "bbox": {"x0": wb.x0, "y0": wb.y0, "x1": wb.x1, "y1": wb.y1},
            "chars": [char_to_dict(c) for c in word.chars],
        }

    def _line_to_dict(self, line: Line) -> Dict[str, Any]:
        lb = line.bbox
        word_to_dict = self._word_to_dict
        return {
            "text": line.text,
            "bbox": {"x0": lb.x0, "y0": lb.y0, "x1": lb.x1, "y1": lb.y1},
            "words": [word_to_dict(w) for w in line.words],
        }

    def _block_to_dict(self, block: Block) -> Dict[str, Any]:
        bb = block.bbox
        line_to_dict = self._line_to_dict
        return {
            "text": block.text,
            "bbox": {"x0": bb.x0, "y0": bb.y0, "x1": bb.x1, "y1": bb.y1},
            "lines": [line_to_dict(ln) for ln in block.lines],
        }

    def _span_to_dict(self, span: Span) -> Dict[str, Any]:
        sb = span.bbox
        return {
            "text": span.text,
            "bbox": {"x0": sb.x0, "y0": sb.y0, "x1": sb.x1, "y1": sb.y1},
            "font": span.font,
            "size": span.size,
        }

    def _cell_to_dict(self, cell: Cell) -> Dict[str, Any]:
        cb = cell.bbox
        return {
            "text": cell.text,
            "row_index": cell.row_index,
            "col_index": cell.col_index,
            "bbox": {"x0": cb.x0, "y0": cb.y0, "x1": cb.x1, "y1": cb.y1},
            "rowspan": cell.rowspan,
            "colspan": cell.colspan,
        }

    def _table_to_dict(self, table: Table) -> Dict[str, Any]:
        tb = table.bbox
        cell_to_dict = self._cell_to_dict
        return {
            "bbox": {"x0": tb.x0, "y0": tb.y0, "x1": tb.x1, "y1": tb.y1},
            "rows": table.rows,
            "cols": table.cols,
            "cells": [cell_to_dict(c) for c in table.cells],
            "confidence": table.confidence,
            "source": table.source,
        }

    def _image_to_dict(self, image: Image) -> Dict[str, Any]:
        ib = image.bbox
        return {
            "bbox": {"x0": ib.x0, "y0": ib.y0, "x1": ib.x1, "y1": ib.y1},
            "page_index": image.page_index,
            "resource_index": image.resource_index,
            "width": image.width,
            "height": image.height,
            "path": image.path,
            "ext": image.ext,
        }

    def _seal_to_dict(self, seal: Seal) -> Dict[str, Any]:
        sb = seal.bbox
        return {
            "bbox": {"x0": sb.x0, "y0": sb.y0, "x1": sb.x1, "y1": sb.y1},
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
        eb = element.bbox
        result: Dict[str, Any] = {
            "type": element.type,
            "bbox": {"x0": eb.x0, "y0": eb.y0, "x1": eb.x1, "y1": eb.y1},
            "order": element.order,
            "content": self._content_to_dict(element.content),
        }
        # Include nested text structures when present
        if element.spans:
            span_to_dict = self._span_to_dict
            result["spans"] = [span_to_dict(s) for s in element.spans]
        if element.lines:
            line_to_dict = self._line_to_dict
            result["lines"] = [line_to_dict(ln) for ln in element.lines]
        if element.words:
            word_to_dict = self._word_to_dict
            result["words"] = [word_to_dict(w) for w in element.words]
        if element.chars:
            char_to_dict = self._char_to_dict
            result["chars"] = [char_to_dict(c) for c in element.chars]
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

    def table_structures_to_dict(
        self, structures: List[TableStructure]
    ) -> List[Dict[str, Any]]:
        """Convert a list of TableStructure to serializable dicts."""
        return [self._table_structure_to_dict(s) for s in structures]

    def _text_char_to_dict(self, tc: TextChar) -> Dict[str, Any]:
        cb = tc.bbox
        result: Dict[str, Any] = {
            "text": tc.text,
            "bbox": {"x0": cb.x0, "y0": cb.y0, "x1": cb.x1, "y1": cb.y1},
        }
        if tc.confidence is not None:
            result["confidence"] = tc.confidence
        return result

    def _text_block_to_dict(self, tb: TextBlock) -> Dict[str, Any]:
        bb = tb.bbox
        return {
            "text": tb.text,
            "bbox": {"x0": bb.x0, "y0": bb.y0, "x1": bb.x1, "y1": bb.y1},
            "chars": [self._text_char_to_dict(c) for c in tb.chars],
        }

    def _cell_structure_to_dict(self, cs: CellStructure) -> Dict[str, Any]:
        cb = cs.bbox
        result: Dict[str, Any] = {
            "text": cs.text,
            "row_index": cs.row_index,
            "col_index": cs.col_index,
            "cell_coord": [
                {"x": p[0], "y": p[1]} for p in cs.cell_coord
            ],
            "bbox": {"x0": cb.x0, "y0": cb.y0, "x1": cb.x1, "y1": cb.y1},
            "tl_row": cs.tl_row,
            "tl_col": cs.tl_col,
            "br_row": cs.br_row,
            "br_col": cs.br_col,
        }
        if cs.text_block is not None:
            result["text_block"] = self._text_block_to_dict(cs.text_block)
        return result

    def _table_structure_to_dict(self, ts: TableStructure) -> Dict[str, Any]:
        tb = ts.bbox
        result: Dict[str, Any] = {
            "bbox": {"x0": tb.x0, "y0": tb.y0, "x1": tb.x1, "y1": tb.y1},
            "rows": ts.rows,
            "cols": ts.cols,
            "cells": [self._cell_structure_to_dict(c) for c in ts.cells],
        }
        if ts.confidence is not None:
            result["confidence"] = ts.confidence
        if ts.source is not None:
            result["source"] = ts.source
        return result

