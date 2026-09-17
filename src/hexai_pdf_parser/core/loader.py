"""PDF loader module.

Opens a PDF file with PyMuPDF (``fitz``) and builds a :class:`Document`
containing per-page metadata (size, rotation, etc.).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from typing import Optional, Sequence

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

    def load(self, page_indices: Optional[Sequence[int]] = None) -> Document:
        """Open the PDF and return a :class:`Document`."""
        file_name = Path(self.file_path).name
        target_indices = set(page_indices) if page_indices is not None else None

        with fitz.open(self.file_path) as pdf:
            page_count = len(pdf)
            pages: list[Page] = []

            for idx, page in enumerate(pdf):
                rect = page.rect
                should_classify = target_indices is None or idx in target_indices
                page_type = classify_page_type(page) if should_classify else "vector"
                pages.append(
                    Page(
                        index=idx,
                        size={"width": rect.width, "height": rect.height},
                        rotation=page.rotation,
                        page_type=page_type,
                    )
                )

        return Document(file_name=file_name, page_count=page_count, pages=pages)
