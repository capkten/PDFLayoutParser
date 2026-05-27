"""Public API for PDFLayoutParser.

Provides the :class:`PDFParser` class that wraps the internal pipeline
and individual extractors behind a unified interface.
"""

from __future__ import annotations

import os
from typing import List, Optional

from hexai_pdf_parser.models import Block, Document, Image, RenderInfo, Table


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

        from hexai_pdf_parser.pipeline import Pipeline

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
        from hexai_pdf_parser.loader import Loader
        from hexai_pdf_parser.text_extractor import TextExtractor

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
        from hexai_pdf_parser.loader import Loader
        from hexai_pdf_parser.table_extractor import TableExtractor

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

    def extract_images(
        self,
        output_dir: str,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> List[Image]:
        """Extract embedded images from the PDF, writing to *output_dir*."""
        from hexai_pdf_parser.loader import Loader
        from hexai_pdf_parser.image_extractor import ImageExtractor

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

    def render_pages(
        self,
        output_dir: str,
        *,
        dpi: Optional[int] = None,
        page_indices: Optional[List[int]] = None,
    ) -> List[RenderInfo]:
        """Render PDF pages as PNG files into *output_dir*."""
        from hexai_pdf_parser.loader import Loader
        from hexai_pdf_parser.render_engine import RenderEngine

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

    def to_json(
        self,
        document: Optional[Document] = None,
    ) -> str:
        """Serialize a Document to a JSON string (in-memory, no file I/O).

        If *document* is None, uses the cached parse result (calls :meth:`parse`
        if not yet parsed).
        """
        import json
        from hexai_pdf_parser.json_writer import JSONWriter

        doc = document if document is not None else self.parse()
        data = JSONWriter().to_dict(doc)
        return json.dumps(data, ensure_ascii=False)

    def to_markdown(
        self,
        document: Optional[Document] = None,
    ) -> str:
        """Serialize a Document to a Markdown string (in-memory, no file I/O).

        If *document* is None, uses the cached parse result (calls :meth:`parse`
        if not yet parsed).
        """
        from hexai_pdf_parser.markdown_writer import MarkdownWriter

        doc = document if document is not None else self.parse()
        return MarkdownWriter().to_string(doc)

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
    ) -> List[Block]:
        """Extract text blocks that intersect with the given region(s).

        Region coordinates are normalized 0~1 relative to page size.
        """
        page_sizes = self._get_page_sizes()
        regions = self._normalize_regions(region, page_sizes)

        # Ensure text is extracted
        if self._document is None:
            self.extract_text()

        blocks: List[Block] = []
        for r in regions:
            page_idx = r["page_index"]
            target_page = None
            for p in self._document.pages:
                if p.index == page_idx:
                    target_page = p
                    break
            if target_page is None:
                continue
            for block in target_page.blocks:
                if self._bbox_intersects(block.bbox, r):
                    blocks.append(block)
        return blocks

    def extract_table_in_region(
        self,
        region: dict | list[dict],
    ) -> Table | list[Table] | None:
        """Extract table(s) from specified region(s).

        Region coordinates are normalized 0~1 relative to page size.
        Returns Table for single region (or None), list[Table] for multiple.
        """
        import fitz as _fitz
        from hexai_pdf_parser.loader import Loader
        from hexai_pdf_parser.table_extractor import TableExtractor

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
                use_ml=self._use_ml,
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

    def extract_image_in_region(
        self,
        region: dict | list[dict],
        output_dir: str,
    ) -> Image | list[Image] | None:
        """Extract images that intersect with the given region(s).

        Region coordinates are normalized 0~1 relative to page size.
        """
        is_single = isinstance(region, dict)
        page_sizes = self._get_page_sizes()
        regions = self._normalize_regions(region, page_sizes)

        # Get all images first
        all_page_indices = list({r["page_index"] for r in regions})
        all_images = self.extract_images(
            output_dir, page_indices=all_page_indices
        )

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

    def render_region(
        self,
        region: dict | list[dict],
        output_dir: str,
        dpi: Optional[int] = None,
    ) -> RenderInfo | list[RenderInfo]:
        """Render region(s) of the PDF as PNG files.

        Region coordinates are normalized 0~1 relative to page size.
        """
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
