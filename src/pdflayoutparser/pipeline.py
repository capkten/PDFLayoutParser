"""Pipeline: orchestrates the full PDF processing flow.

This module ties together all individual modules (loader, text_extractor,
layout_mapper, image_extractor, table_extractor, layout_builder,
json_writer, markdown_writer, render_engine) into a single end-to-end
processing pipeline.
"""

import os
from typing import List, Optional

import fitz

from pdflayoutparser.image_extractor import ImageExtractor
from pdflayoutparser.json_writer import JSONWriter
from pdflayoutparser.layout_builder import LayoutBuilder
from pdflayoutparser.layout_mapper import LayoutMapper
from pdflayoutparser.loader import Loader
from pdflayoutparser.markdown_writer import MarkdownWriter
from pdflayoutparser.models import BBox, Document, LayoutElement, Seal
from pdflayoutparser.render_engine import RenderEngine
from pdflayoutparser.table_extractor import TableExtractor
from pdflayoutparser.text_extractor import TextExtractor


class Pipeline:
    """Orchestrate the full PDF processing flow.

    Example::

        pipeline = Pipeline("doc.pdf", output_dir="/tmp/out", render_dpi=200)
        document = pipeline.run()
    """

    def __init__(
        self,
        pdf_path: str,
        output_dir: str,
        render_dpi: int = 200,
        seal_coords: Optional[List[dict]] = None,
    ):
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.render_dpi = render_dpi
        self.seal_coords = seal_coords or []

    def run(self) -> Document:
        """Run the full processing pipeline and return the Document."""
        # 1. Load PDF
        document = Loader(self.pdf_path).load()

        # Prepare output directories
        images_dir = os.path.join(self.output_dir, "images")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)

        # 2. Per-page processing
        pdf_doc = fitz.open(self.pdf_path)
        try:
            for page in document.pages:
                page_handle = pdf_doc[page.index]

                # a. Text extraction
                page.blocks = TextExtractor().extract_blocks(page_handle)

                # b. Layout mapping (text -> LayoutElements)
                text_elements = LayoutMapper().map_blocks(page.blocks)

                # c. Table extraction
                page.tables = TableExtractor().extract(page_handle)

                # d. Image extraction
                page.images = ImageExtractor(images_dir).extract(
                    self.pdf_path, page.index
                )

                # e. Seals
                seals: List[Seal] = []
                for coord in self.seal_coords:
                    if coord.get("page_index") == page.index:
                        seal = Seal(
                            bbox=BBox(
                                coord["x0"],
                                coord["y0"],
                                coord["x1"],
                                coord["y1"],
                            ),
                            page_index=page.index,
                        )
                        seals.append(seal)
                page.seals = seals

                # f. Layout building
                layout_elements = LayoutBuilder().build(
                    text_elements, page.tables, page.images
                )

                # g. Append seal layout elements
                for seal in seals:
                    layout_elements.append(
                        LayoutElement(
                            type="seal",
                            bbox=seal.bbox,
                            order=len(layout_elements),
                            content=seal,
                        )
                    )

                # h. Set layout_elements on the page
                page.layout_elements = layout_elements

                # i. Render
                page.render = RenderEngine(
                    self.output_dir, self.render_dpi
                ).render(self.pdf_path, page.index)
        finally:
            pdf_doc.close()

        # 3. Output writers
        JSONWriter().write(
            document, os.path.join(self.output_dir, "output.json")
        )
        MarkdownWriter().write(
            document, os.path.join(self.output_dir, "output.md")
        )

        return document
