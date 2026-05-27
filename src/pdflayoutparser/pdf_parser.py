"""Public API for PDFLayoutParser.

Provides the :class:`PDFParser` class that wraps the internal pipeline
and individual extractors behind a unified interface.
"""

from __future__ import annotations

import os
from typing import List, Optional

from pdflayoutparser.models import Block, Document, Table


class PDFParser:
    """High-level PDF parsing and extraction interface.

    Accepts either a file path or a pre-parsed :class:`Document`.

    Example::

        with PDFParser("report.pdf") as parser:
            doc = parser.parse()
            tables = parser.extract_tables()
    """

    def __init__(
        self,
        source: str | Document,
        *,
        render_dpi: int = 200,
        seal_coords: Optional[List[dict]] = None,
        use_ml: bool = False,
        ml_model_path: Optional[str] = None,
        ml_confidence: float = 0.25,
    ) -> None:
        if isinstance(source, Document):
            self._pdf_path: str | None = None
            self._document: Document | None = source
        else:
            self._pdf_path = source
            self._document = None

        self._render_dpi = render_dpi
        self._seal_coords = seal_coords or []
        self._use_ml = use_ml
        self._ml_model_path = ml_model_path
        self._ml_confidence = ml_confidence

    def __enter__(self) -> PDFParser:
        return self

    def __exit__(self, *exc) -> None:
        pass

    def parse(
        self,
        *,
        page_indices: Optional[List[int]] = None,
        output_dir: Optional[str] = None,
    ) -> Document:
        """Run the full parsing pipeline and return a Document.

        Results are cached — subsequent calls return the same object.
        Pass *output_dir* to also write JSON, Markdown, images, and renders.
        """
        if self._document is not None:
            return self._document

        from pdflayoutparser.pipeline import Pipeline

        pipeline = Pipeline(
            pdf_path=self._pdf_path,
            output_dir=output_dir,
            render_dpi=self._render_dpi,
            seal_coords=self._seal_coords,
            page_indices=page_indices,
            use_ml=self._use_ml,
            ml_model_path=self._ml_model_path,
            ml_confidence=self._ml_confidence,
        )
        self._document = pipeline.run()
        return self._document

    def extract_text(
        self,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> List[Block]:
        """Extract text blocks from the PDF.

        If a cached Document exists, returns its blocks directly.
        Otherwise loads the PDF and runs only the text extraction stage.
        """
        if self._document is not None:
            return self._collect_from_document(
                lambda p: p.blocks, page_indices
            )

        import fitz as _fitz
        from pdflayoutparser.loader import Loader
        from pdflayoutparser.text_extractor import TextExtractor

        document = Loader(self._pdf_path).load()
        pdf_doc = _fitz.open(self._pdf_path)
        try:
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                page.blocks = TextExtractor().extract_blocks(pdf_doc[page.index])
        finally:
            pdf_doc.close()
        self._document = document
        return self._collect_from_document(lambda p: p.blocks, page_indices)

    def extract_tables(
        self,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> List[Table]:
        """Extract tables from the PDF.

        If a cached Document exists, returns its tables directly.
        Otherwise loads the PDF and runs only the table detection stage.
        """
        if self._document is not None:
            return self._collect_from_document(
                lambda p: p.tables, page_indices
            )

        import fitz as _fitz
        from pdflayoutparser.loader import Loader
        from pdflayoutparser.table_extractor import TableExtractor

        document = Loader(self._pdf_path).load()
        pdf_doc = _fitz.open(self._pdf_path)
        try:
            extractor = TableExtractor(
                use_ml=self._use_ml,
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
            )
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                page.tables = extractor.extract(pdf_doc[page.index])
        finally:
            pdf_doc.close()
        self._document = document
        return self._collect_from_document(lambda p: p.tables, page_indices)

    def _collect_from_document(
        self,
        getter,
        page_indices: Optional[List[int]],
    ) -> list:
        """Collect items from all pages of the cached document."""
        items = []
        for page in self._document.pages:
            if page_indices is not None and page.index not in page_indices:
                continue
            items.extend(getter(page))
        return items
