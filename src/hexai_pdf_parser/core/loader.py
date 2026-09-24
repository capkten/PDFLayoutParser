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
            if target_indices is None:
                for idx, page in enumerate(pdf):
                    rect = page.rect
                    page_type = classify_page_type(page)
                    pages.append(
                        Page(
                            index=idx,
                            size={"width": rect.width, "height": rect.height},
                            rotation=page.rotation,
                            page_type=page_type,
                        )
                    )
            else:
                for idx in range(page_count):
                    if idx in target_indices:
                        page = pdf[idx]
                        rect = page.rect
                        page_type = classify_page_type(page)
                        pages.append(
                            Page(
                                index=idx,
                                size={"width": rect.width, "height": rect.height},
                                rotation=page.rotation,
                                page_type=page_type,
                            )
                        )
                    else:
                        pages.append(
                            Page(
                                index=idx,
                                size={"width": 0.0, "height": 0.0},
                                rotation=0,
                                page_type="vector",
                            )
                        )

        return Document(file_name=file_name, page_count=page_count, pages=pages)
