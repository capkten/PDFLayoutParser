"""Public API for PDFLayoutParser.

Provides the :class:`PDFParser` class that wraps the internal pipeline
and individual extractors behind a unified interface.
"""

from __future__ import annotations

import os
from typing import List, Optional

from hexai_pdf_parser.core.models import ApiResult, BBox, Block, Document, Image, Line, RenderInfo, Table
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
        render_dpi: int = 200,
        seal_coords: Optional[List[dict]] = None,
        ml_model_path: Optional[str] = None,
        ml_confidence: float = 0.70,
        num_workers: Optional[int] = None,
        backend: str = "thread",
        debug_pipeline: bool = False,
    ) -> None:
        if isinstance(source, Document):
            self._pdf_path = None
            self._document = source
        else:
            self._pdf_path = source
            self._document = None

        self._text_ready = self._document is not None
        self._document_complete = self._document is not None

        self._render_dpi = render_dpi
        self._seal_coords = seal_coords or []
        self._ml_model_path = ml_model_path
        self._ml_confidence = ml_confidence
        self._num_workers = num_workers
        self._backend = backend
        self._debug_pipeline = debug_pipeline

    def __enter__(self) -> PDFParser:
        return self

    def __exit__(self, *exc) -> None:
        pass

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
                page.blocks or page.tables or page.images or page.layout_elements
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
    ) -> ApiResult:
        """Run the full parsing pipeline and return an ApiResult wrapping a Document.

        Results are cached — subsequent calls return the same object.
        Pass *output_dir* to also write JSON, Markdown, images, and renders.
        """
        def _do_parse():
            if self._document is not None and self._document_complete:
                return self._document

            from hexai_pdf_parser.core.pipeline import Pipeline

            pipeline = Pipeline(
                pdf_path=self._pdf_path,
                output_dir=output_dir,
                render_dpi=self._render_dpi,
                seal_coords=self._seal_coords,
                page_indices=page_indices,
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
                num_workers=self._num_workers,
                backend=self._backend,
                debug_pipeline=self._debug_pipeline,
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

            import fitz as _fitz
            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.tables.table_extractor import TableExtractor
            from hexai_pdf_parser.extractors.text_extractor import TextExtractor

            document = Loader(self._pdf_path).load()
            pdf_doc = _fitz.open(self._pdf_path)
            try:
                table_extractor = TableExtractor(
                    ml_model_path=self._ml_model_path,
                    ml_confidence=self._ml_confidence,
                )
                for page in document.pages:
                    if page_indices is not None and page.index not in page_indices:
                        continue
                    page_handle = pdf_doc[page.index]
                    normalize_page_rotation(page_handle)
                    page.blocks = TextExtractor().extract_blocks(page_handle)
                    page.tables = table_extractor.extract(page_handle)
                    page.blocks = TextExtractor().extract_layout_blocks(
                        page_handle,
                        page.tables,
                    )
            finally:
                pdf_doc.close()
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

            import fitz as _fitz
            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.tables.table_extractor import TableExtractor

            document = Loader(self._pdf_path).load()
            pdf_doc = _fitz.open(self._pdf_path)
            try:
                extractor = TableExtractor(
                    ml_model_path=self._ml_model_path,
                    ml_confidence=self._ml_confidence,
                )
                for page in document.pages:
                    if page_indices is not None and page.index not in page_indices:
                        continue
                    page_handle = pdf_doc[page.index]
                    normalize_page_rotation(page_handle)
                    page.tables = extractor.extract(page_handle)
            finally:
                pdf_doc.close()
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
            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.extractors.image_extractor import ImageExtractor

            pdf_path = self._pdf_path
            if pdf_path is None:
                raise ValueError("extract_images requires a PDF file path, not a Document")
            document = Loader(pdf_path).load()
            extractor = ImageExtractor(output_dir)
            images: List[Image] = []
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                images.extend(extractor.extract(pdf_path, page.index))
            return images

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
            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.writers.render_engine import RenderEngine

            pdf_path = self._pdf_path
            if pdf_path is None:
                raise ValueError("render_pages requires a PDF file path, not a Document")
            effective_dpi = dpi if dpi is not None else self._render_dpi
            document = Loader(pdf_path).load()
            engine = RenderEngine(output_dir, effective_dpi)
            renders: List[RenderInfo] = []
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                renders.append(engine.render(pdf_path, page.index))
            return renders

        return self._execute_result(_do, "pages rendered", "no pages rendered")

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
    def _normalize_regions(
        region: dict | list[dict],
        page_sizes: dict[int, tuple[float, float]] | None = None,
    ) -> list[dict]:
        """Convert normalized 0~1 region coords to PDF point coords.

        If *page_sizes* is provided, multiplies normalized coords by page
        dimensions. Otherwise returns coords as-is.
        """
        regions = region if isinstance(region, list) else [region]
        result = []
        for r in regions:
            if page_sizes and r["page_index"] in page_sizes:
                w, h = page_sizes[r["page_index"]]
                result.append({
                    "page_index": r["page_index"],
                    "x0": r["x0"] * w,
                    "y0": r["y0"] * h,
                    "x1": r["x1"] * w,
                    "y1": r["y1"] * h,
                })
            else:
                result.append(dict(r))
        return result

    def _get_page_sizes(self) -> dict[int, tuple[float, float]]:
        """Return {page_index: (width, height)} from cached doc or PDF."""
        if self._document is not None:
            return {
                p.index: (p.size["width"], p.size["height"])
                for p in self._document.pages
            }
        import fitz as _fitz
        doc = _fitz.open(self._pdf_path)
        try:
            return {
                i: (doc[i].rect.width, doc[i].rect.height)
                for i in range(len(doc))
            }
        finally:
            doc.close()

    @staticmethod
    def _bbox_intersects(block_bbox, region_bbox: dict) -> bool:
        """Check if block_bbox overlaps with region_bbox."""
        return not (
            block_bbox.x1 < region_bbox["x0"]
            or block_bbox.x0 > region_bbox["x1"]
            or block_bbox.y1 < region_bbox["y0"]
            or block_bbox.y0 > region_bbox["y1"]
        )

    def extract_text_in_region(
        self,
        region: dict | list[dict],
    ) -> ApiResult:
        """Extract text from the given region(s) using word-level matching.

        Region coordinates are normalized 0~1 relative to page size.
        Uses PyMuPDF word-level extraction for precise region clipping.
        """
        def _do():
            import fitz as _fitz

            page_sizes = self._get_page_sizes()
            regions = self._normalize_regions(region, page_sizes)

            pdf_path = self._pdf_path
            if pdf_path is None:
                raise ValueError("extract_text_in_region requires a PDF file path")

            blocks: List[Block] = []
            pdf_doc = _fitz.open(pdf_path)
            try:
                for r in regions:
                    page_idx = r["page_index"]
                    page = pdf_doc[page_idx]
                    words = page.get_text("words")  # (x0, y0, x1, y1, text, block_no, line_no, word_no)

                    matched = [
                        w for w in words
                        if self._bbox_intersects(
                            BBox(w[0], w[1], w[2], w[3]), r
                        )
                    ]
                    if not matched:
                        continue

                    # Group by (block_no, line_no) to preserve line structure
                    from collections import OrderedDict
                    lines_map: dict[tuple[int, int], list] = OrderedDict()
                    for w in matched:
                        key = (w[5], w[6])
                        lines_map.setdefault(key, []).append(w)

                    lines: List[Line] = []
                    for words_in_line in lines_map.values():
                        words_in_line.sort(key=lambda w: w[0])  # sort by x
                        line_text = " ".join(w[4] for w in words_in_line)
                        lx0 = min(w[0] for w in words_in_line)
                        ly0 = min(w[1] for w in words_in_line)
                        lx1 = max(w[2] for w in words_in_line)
                        ly1 = max(w[3] for w in words_in_line)
                        lines.append(Line(
                            text=line_text,
                            bbox=BBox(lx0, ly0, lx1, ly1),
                        ))

                    block_text = "\n".join(l.text for l in lines)
                    bx0 = min(l.bbox.x0 for l in lines)
                    by0 = min(l.bbox.y0 for l in lines)
                    bx1 = max(l.bbox.x1 for l in lines)
                    by1 = max(l.bbox.y1 for l in lines)
                    blocks.append(Block(
                        text=block_text,
                        bbox=BBox(bx0, by0, bx1, by1),
                        lines=lines,
                    ))
            finally:
                pdf_doc.close()

            return blocks

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
            import fitz as _fitz
            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.tables.table_extractor import TableExtractor

            is_single = isinstance(region, dict)
            page_sizes = self._get_page_sizes()
            regions = self._normalize_regions(region, page_sizes)

            pdf_path = self._pdf_path
            if pdf_path is None:
                raise ValueError("extract_table_in_region requires a PDF file path")
            document = Loader(pdf_path).load()
            pdf_doc = _fitz.open(pdf_path)
            try:
                extractor = TableExtractor(
                    ml_model_path=self._ml_model_path,
                    ml_confidence=self._ml_confidence,
                )
                results: list[Table] = []
                for r in regions:
                    page_idx = r["page_index"]
                    page_handle = pdf_doc[page_idx]
                    tables = extractor.extract(page_handle)
                    # Filter tables that intersect with the region
                    matched = [
                        t for t in tables
                        if self._bbox_intersects(t.bbox, r)
                    ]
                    if is_single:
                        return matched[0] if matched else None
                    results.extend(matched)
                return results
            finally:
                pdf_doc.close()

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
            import fitz as _fitz
            from hexai_pdf_parser.core.loader import Loader
            from hexai_pdf_parser.tables.table_extractor import TableExtractor

            pdf_path = self._pdf_path
            if pdf_path is None:
                raise ValueError("extract_table_structure requires a PDF file path")

            extractor = TableExtractor(
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
            )

            if region is not None:
                page_sizes = self._get_page_sizes()
                regions = self._normalize_regions(region, page_sizes)
                pdf_doc = _fitz.open(pdf_path)
                try:
                    all_results = []
                    for r in regions:
                        page_idx = r["page_index"]
                        page_handle = pdf_doc[page_idx]
                        structures = extractor.extract_table_structure(page_handle)
                        for s in structures:
                            if self._bbox_intersects(s.bbox, r):
                                all_results.append(s)
                    return all_results
                finally:
                    pdf_doc.close()
            else:
                document = Loader(pdf_path).load()
                pdf_doc = _fitz.open(pdf_path)
                try:
                    all_results = []
                    for page in document.pages:
                        if page_indices is not None and page.index not in page_indices:
                            continue
                        page_handle = pdf_doc[page.index]
                        all_results.extend(
                            extractor.extract_table_structure(page_handle)
                        )
                    return all_results
                finally:
                    pdf_doc.close()

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
            is_single = isinstance(region, dict)
            page_sizes = self._get_page_sizes()
            regions = self._normalize_regions(region, page_sizes)

            # Get all images first
            all_page_indices = list({r["page_index"] for r in regions})
            images_result = self.extract_images(
                output_dir, page_indices=all_page_indices
            )
            if images_result.code == -1:
                raise RuntimeError(images_result.message)
            all_images = images_result.data or []

            results: list[Image] = []
            for r in regions:
                matched = [
                    img for img in all_images
                    if img.page_index == r["page_index"]
                    and img.bbox is not None
                    and self._bbox_intersects(img.bbox, r)
                ]
                if is_single:
                    return matched[0] if matched else None
                results.extend(matched)
            return results

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
            import fitz as _fitz

            is_single = isinstance(region, dict)
            effective_dpi = dpi if dpi is not None else self._render_dpi
            page_sizes = self._get_page_sizes()
            regions = self._normalize_regions(region, page_sizes)

            os.makedirs(output_dir, exist_ok=True)
            pdf_path = self._pdf_path
            if pdf_path is None:
                raise ValueError("render_region requires a PDF file path")
            pdf_doc = _fitz.open(pdf_path)
            try:
                results: list[RenderInfo] = []
                for idx, r in enumerate(regions):
                    page_handle = pdf_doc[r["page_index"]]
                    clip = _fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
                    mat = _fitz.Matrix(effective_dpi / 72, effective_dpi / 72)
                    pix = page_handle.get_pixmap(matrix=mat, clip=clip)

                    file_name = f"region-{r['page_index']:03d}-{idx:03d}.png"
                    path = os.path.join(output_dir, file_name)
                    pix.save(path)

                    info = RenderInfo(
                        path=path,
                        width=pix.width,
                        height=pix.height,
                        dpi=effective_dpi,
                    )
                    if is_single:
                        return info
                    results.append(info)
                return results
            finally:
                pdf_doc.close()

        return self._execute_result(_do, "region rendered", "region rendered but empty")
