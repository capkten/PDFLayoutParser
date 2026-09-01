"""PDF loader module.

Opens a PDF file with PyMuPDF (``fitz``) and builds a :class:`Document`
containing per-page metadata (size, rotation, etc.).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from hexai_pdf_parser.core.models import Document, Page
from hexai_pdf_parser.extractors.page_classifier import classify_page_type


class Loader:
    """Load a PDF file and extract high-level page metadata.

    Example::

        loader = Loader("document.pdf")
        doc = loader.load()
    """

    def __init__(self, file_path: str):
        self.file_path = file_path

    def load(self) -> Document:
        """Open the PDF and return a :class:`Document`."""
        file_name = Path(self.file_path).name

        with fitz.open(self.file_path) as pdf:
            page_count = len(pdf)
            pages: list[Page] = []

            for idx, page in enumerate(pdf):
                rect = page.rect
                pages.append(
                    Page(
                        index=idx,
                        size={"width": rect.width, "height": rect.height},
                        rotation=page.rotation,
                        page_type=classify_page_type(page),
                    )
                )

        return Document(file_name=file_name, page_count=page_count, pages=pages)
