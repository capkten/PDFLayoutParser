"""Public API for PDFLayoutParser.

Provides the :class:`PDFParser` class that wraps the internal pipeline
and individual extractors behind a unified interface.
"""

from __future__ import annotations

from typing import List, Optional

from hexai_pdf_parser.core.models import ApiResult, Document
from hexai_pdf_parser import pdfium_api
from hexai_pdf_parser.page_normalizer import normalize_page_rotation


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
        source,
        *,
        render_dpi: int = 72,
        ml_render_dpi: Optional[int] = None,
        seal_coords: Optional[List[dict]] = None,
        ml_model_path: Optional[str] = None,
        ml_confidence: float = 0.40,
        num_workers: Optional[int] = None,
        backend: str = "thread",
        debug_pipeline: bool = False,
        visualize_tables: bool = False,
    ) -> None:
        if isinstance(source, Document):
            self._pdf_path = None
            self._document = source
        else:
            self._pdf_path = source
            self._document = None
        self._pdf_doc = None

        self._text_ready = self._document is not None
        self._document_complete = self._document is not None

        self._render_dpi = render_dpi
        self._ml_render_dpi = ml_render_dpi
        self._seal_coords = seal_coords or []
        self._ml_model_path = ml_model_path
        self._ml_confidence = ml_confidence
        self._num_workers = num_workers
        self._backend = backend
        self._debug_pipeline = debug_pipeline
        self._visualize_tables = visualize_tables

    def __enter__(self) -> PDFParser:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get_pdf_doc(self):
        if self._pdf_path is None:
            raise ValueError("PDF file path required")
        if self._pdf_doc is None or self._pdf_doc.is_closed:
            import fitz
            self._pdf_doc = fitz.open(self._pdf_path)
        return self._pdf_doc

    def close(self) -> None:
        if self._pdf_doc is not None:
            self._pdf_doc.close()
            self._pdf_doc = None

    def warmup(self) -> None:
        """Preload and warm up models before parsing to eliminate cold-start overhead."""
        from hexai_pdf_parser.ml.ml_table_detector import (
            MLTableDetector,
            _resolve_default_model_path,
        )

        model_path = self._ml_model_path or _resolve_default_model_path()
        detector = MLTableDetector(
            model_path=model_path,
            confidence_threshold=self._ml_confidence,
            render_dpi=self._render_dpi,
        )
        detector.warmup()

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_content(data) -> bool:
        if data is None:
            return False
        if isinstance(data, str):
            return bool(data.strip())
        if isinstance(data, (list, tuple, dict, set)):
            return len(data) > 0
        if isinstance(data, Document):
            return any(
                page.page_type == "scanned"
                or page.blocks
                or page.tables
                or page.images
                or page.layout_elements
                for page in data.pages
            )
        return True

    @staticmethod
    def _build_result(data, success_message: str, empty_message: str) -> ApiResult:
        if PDFParser._has_content(data):
            return ApiResult(code=1, message=success_message, data=data)
        return ApiResult(code=0, message=empty_message, data=data)

    @staticmethod
    def _execute_result(action, success_message: str, empty_message: str) -> ApiResult:
        try:
            data = action()
            return PDFParser._build_result(data, success_message, empty_message)
        except Exception as exc:
            return ApiResult(code=-1, message=str(exc), data=None)

    def parse(
        self,
        *,
        page_indices: Optional[List[int]] = None,
        output_dir: Optional[str] = None,
        visualize_tables: Optional[bool] = None,
    ) -> ApiResult:
        """Run the full parsing pipeline and return an ApiResult wrapping a Document.

        Results are cached — subsequent calls return the same object.
        Pass *output_dir* to also write JSON, Markdown, images, and renders.
        """
        def _do_parse():
            if self._document is not None and self._document_complete:
                return self._document

            from hexai_pdf_parser.core.pipeline import Pipeline

            eff_visualize_tables = (
                visualize_tables
                if visualize_tables is not None
                else self._visualize_tables
            )

            pipeline = Pipeline(
                pdf_path=self._pdf_path,
                output_dir=output_dir,
                render_dpi=self._render_dpi,
                ml_render_dpi=self._ml_render_dpi,
                seal_coords=self._seal_coords,
                page_indices=page_indices,
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
                num_workers=self._num_workers,
                backend=self._backend,
                debug_pipeline=self._debug_pipeline,
                visualize_tables=eff_visualize_tables,
            )
            self._document = pipeline.run()
            self._text_ready = True
            self._document_complete = True
            return self._document

        return self._execute_result(_do_parse, "document parsed", "document parsed but empty")

    def extract_text(
        self,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> ApiResult:
        """Extract text blocks from the PDF, returning an ApiResult wrapping List[Block].

        If a cached Document exists, returns its blocks directly.
        Otherwise loads the PDF, detects table regions, and rebuilds the
        final line-ordered text blocks.
        """
        def _do():
            if self._document is not None and self._text_ready:
                return self._collect_from_document(
                    lambda p: p.blocks, page_indices
                )

            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.tables.table_extractor import TableExtractor
            from hexai_pdf_parser.extractors.text_extractor import TextExtractor

            pdf_doc = self._get_pdf_doc()
            document = Loader(self._pdf_path).load(pdf_doc, page_indices=page_indices)
            table_extractor = TableExtractor(
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
            )
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                page_handle = pdf_doc[page.index]
                original_rotation = page_handle.rotation
                try:
                    normalize_page_rotation(page_handle)
                    page.blocks = TextExtractor().extract_blocks(page_handle)
                    page.tables = table_extractor.extract(page_handle)
                    page.blocks = TextExtractor().extract_layout_blocks(
                        page_handle,
                        page.tables,
                    )
                finally:
                    if page_handle.rotation != original_rotation:
                        page_handle.set_rotation(original_rotation)
            self._document = document
            self._text_ready = True
            self._document_complete = False
            return self._collect_from_document(lambda p: p.blocks, page_indices)

        return self._execute_result(_do, "text extracted", "no text extracted")

    def extract_tables(
        self,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> ApiResult:
        """Extract tables from the PDF, returning an ApiResult wrapping List[Table].

        If a cached Document exists, returns its tables directly.
        Otherwise loads the PDF and runs only the table detection stage.
        """
        def _do():
            if self._document is not None:
                return self._collect_from_document(
                    lambda p: p.tables, page_indices
                )

            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.tables.table_extractor import TableExtractor

            pdf_doc = self._get_pdf_doc()
            document = Loader(self._pdf_path).load(pdf_doc, page_indices=page_indices)
            extractor = TableExtractor(
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
            )
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                page_handle = pdf_doc[page.index]
                original_rotation = page_handle.rotation
                try:
                    normalize_page_rotation(page_handle)
                    page.tables = extractor.extract(page_handle)
                finally:
                    if page_handle.rotation != original_rotation:
                        page_handle.set_rotation(original_rotation)
            self._document = document
            self._text_ready = False
            self._document_complete = False
            return self._collect_from_document(lambda p: p.tables, page_indices)

        return self._execute_result(_do, "tables extracted", "no tables extracted")

    def extract_images(
        self,
        output_dir: str,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> ApiResult:
        """Extract embedded images from the PDF, writing to *output_dir*."""
        def _do():
            if self._pdf_path is None:
                raise ValueError("extract_images requires a PDF file path, not a Document")
            data = pdfium_api._run({
                "operation": "extract_images", "pdf_path": str(self._pdf_path),
                "output_dir": output_dir, "page_indices": page_indices,
            })["data"]
            return [pdfium_api.image(item) for item in data]

        return self._execute_result(_do, "images extracted", "no images extracted")

    def render_pages(
        self,
        output_dir: str,
        *,
        dpi: Optional[int] = None,
        page_indices: Optional[List[int]] = None,
    ) -> ApiResult:
        """Render PDF pages as PNG files into *output_dir*."""
        def _do():
            if self._pdf_path is None:
                raise ValueError("render_pages requires a PDF file path, not a Document")
            effective_dpi = dpi if dpi is not None else self._render_dpi
            data = pdfium_api._run({
                "operation": "render_pages", "pdf_path": str(self._pdf_path),
                "output_dir": output_dir, "dpi": effective_dpi,
                "page_indices": page_indices,
            })["data"]
            return [pdfium_api.render(item) for item in data]

        return self._execute_result(_do, "pages rendered", "no pages rendered")

    def classify_page(
        self,
        page_index: int = 0,
    ) -> ApiResult:
        """Classify whether a page is 'vector' or 'scanned'.

        A parser constructed from a Document uses its cached page_type.
        A path source is always classified by Rust.
        """
        def _do() -> str:
            if self._pdf_path is None and self._document is not None:
                for page in self._document.pages:
                    if page.index == page_index:
                        return page.page_type
                raise IndexError(f"page_index {page_index} out of range")

            if self._pdf_path is None:
                raise ValueError("classify_page requires a PDF file path")
            return pdfium_api._run({
                "operation": "classify_page", "pdf_path": str(self._pdf_path),
                "page_index": page_index,
            })["data"]

        return self._execute_result(_do, "page classified", "page classified but empty")

    def to_json(
        self,
        document: Optional[Document] = None,
    ) -> ApiResult:
        """Serialize a Document to a JSON string (in-memory, no file I/O).

        If *document* is None, uses the cached parse result (calls :meth:`parse`
        if not yet parsed).
        """
        try:
            if document is not None:
                doc = document
            else:
                parse_result = self.parse()
                if parse_result.code == -1:
                    return parse_result
                doc = parse_result.data

            import json
            from hexai_pdf_parser.writers.json_writer import JSONWriter

            data = JSONWriter().to_dict(doc)
            result_str = json.dumps(data, ensure_ascii=False)
            if self._has_content(doc):
                return ApiResult(code=1, message="json generated", data=result_str)
            return ApiResult(code=0, message="json generated but empty", data=result_str)
        except Exception as exc:
            return ApiResult(code=-1, message=str(exc), data=None)

    def to_markdown(
        self,
        document: Optional[Document] = None,
    ) -> ApiResult:
        """Serialize a Document to a Markdown string (in-memory, no file I/O).

        If *document* is None, uses the cached parse result (calls :meth:`parse`
        if not yet parsed).
        """
        try:
            if document is not None:
                doc = document
            else:
                parse_result = self.parse()
                if parse_result.code == -1:
                    return parse_result
                doc = parse_result.data

            from hexai_pdf_parser.writers.markdown_writer import MarkdownWriter

            md = MarkdownWriter().to_string(doc)
            if self._has_content(doc):
                return ApiResult(code=1, message="markdown generated", data=md)
            return ApiResult(code=0, message="markdown generated but empty", data=md)
        except Exception as exc:
            return ApiResult(code=-1, message=str(exc), data=None)

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

    @staticmethod
    def _normalize_regions(region: dict | list[dict]) -> list[dict]:
        """Preserve normalized coordinates for Rust's page-size conversion."""
        return [dict(item) for item in (region if isinstance(region, list) else [region])]

    def extract_text_in_region(
        self,
        region: dict | list[dict],
    ) -> ApiResult:
        """Extract text from normalized 0~1 region coordinates."""
        def _do():
            if self._pdf_path is None:
                raise ValueError("extract_text_in_region requires a PDF file path")
            data = pdfium_api._run({
                "operation": "extract_text_in_region", "pdf_path": str(self._pdf_path),
                "regions": self._normalize_regions(region),
            })["data"]
            return [pdfium_api.block(item) for item in data]

        return self._execute_result(_do, "region text extracted", "no text found in region")

    def extract_table_in_region(
        self,
        region: dict | list[dict],
    ) -> ApiResult:
        """Extract table(s) from specified region(s).

        Region coordinates are normalized 0~1 relative to page size.
        Returns ApiResult wrapping Table for single region (or None), list[Table] for multiple.
        """
        def _do():
            if self._pdf_path is None:
                raise ValueError("PDF file path required")
            single = isinstance(region, dict)
            data = pdfium_api._run({
                "operation": "extract_table_in_region", "pdf_path": str(self._pdf_path),
                "regions": self._normalize_regions(region), "single": single,
            })["data"]
            return pdfium_api.table(data) if single and data is not None else (
                None if single else [pdfium_api.table(item) for item in data]
            )

        return self._execute_result(_do, "region table extracted", "no table found in region")

    def extract_table_structure(
        self,
        *,
        page_indices: Optional[List[int]] = None,
        region: Optional[dict | list[dict]] = None,
    ) -> ApiResult:
        """Extract tables with cell coordinates and char-level text.

        Returns ApiResult wrapping List[TableStructure].
        Supports two modes:
        - page_indices: extract from specified pages
        - region: extract from normalized 0~1 region(s)
        """
        def _do():
            if self._pdf_path is None:
                raise ValueError("extract_table_structure requires a PDF file path")
            data = pdfium_api._run({
                "operation": "extract_table_structure", "pdf_path": str(self._pdf_path),
                "page_indices": page_indices,
                "regions": self._normalize_regions(region) if region is not None else None,
                "ml_model_path": self._ml_model_path,
                "ml_confidence": self._ml_confidence,
            })["data"]
            return [pdfium_api.table_structure(item) for item in data]

        return self._execute_result(_do, "table structure extracted", "no table structure extracted")

    def extract_image_in_region(
        self,
        region: dict | list[dict],
        output_dir: str,
    ) -> ApiResult:
        """Extract images that intersect with the given region(s).

        Region coordinates are normalized 0~1 relative to page size.
        """
        def _do():
            if self._pdf_path is None:
                raise ValueError("extract_images requires a PDF file path, not a Document")
            single = isinstance(region, dict)
            data = pdfium_api._run({
                "operation": "extract_image_in_region", "pdf_path": str(self._pdf_path),
                "regions": self._normalize_regions(region),
                "output_dir": output_dir, "single": single,
            })["data"]
            return pdfium_api.image(data) if single and data is not None else (
                None if single else [pdfium_api.image(item) for item in data]
            )

        return self._execute_result(_do, "region image extracted", "no image found in region")

    def render_region(
        self,
        region: dict | list[dict],
        output_dir: str,
        dpi: Optional[int] = None,
    ) -> ApiResult:
        """Render region(s) of the PDF as PNG files.

        Region coordinates are normalized 0~1 relative to page size.
        """
        def _do():
            if self._pdf_path is None:
                raise ValueError("render_region requires a PDF file path")
            single = isinstance(region, dict)
            data = pdfium_api._run({
                "operation": "render_region", "pdf_path": str(self._pdf_path),
                "regions": self._normalize_regions(region), "output_dir": output_dir,
                "dpi": dpi if dpi is not None else self._render_dpi, "single": single,
            })["data"]
            return pdfium_api.render(data) if single and data is not None else (
                None if single else [pdfium_api.render(item) for item in data]
            )

        return self._execute_result(_do, "region rendered", "region rendered but empty")
