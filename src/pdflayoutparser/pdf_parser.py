"""Public API for PDFLayoutParser.

Provides the :class:`PDFParser` class that wraps the internal pipeline
and individual extractors behind a unified interface.
"""

from __future__ import annotations

from typing import List, Optional

from pdflayoutparser.models import Document


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
