"""Render engine module.

Renders PDF pages to raster images (PNG) using PyMuPDF.
"""

import os
from typing import Optional

import fitz
from hexai_pdf_parser.page_normalizer import normalize_page_rotation

from hexai_pdf_parser.core.models import RenderInfo
from hexai_pdf_parser.page_normalizer import normalize_page_rotation
from hexai_pdf_parser.page_type_label import draw_page_type_label


class RenderEngine:
    """Render a PDF page to a PNG image.

    Example::

        engine = RenderEngine(output_dir="/tmp/renders", dpi=200)
        info = engine.render("doc.pdf", page_index=0)
    """

    def __init__(self, output_dir: str, dpi: int = 200):
        """Create *output_dir* if it does not exist."""
        self.output_dir = output_dir
        self.dpi = dpi
        os.makedirs(output_dir, exist_ok=True)

    def render(
        self,
        file_path: str,
        page_index: int,
        page_type: Optional[str] = None,
    ) -> RenderInfo:
        """Render *page_index* of *file_path* to a PNG and return :class:`RenderInfo`."""
        doc = fitz.open(file_path)
        try:
            page = doc[page_index]
            normalize_page_rotation(page)
            draw_page_type_label(page, page_type)
            mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            pix = page.get_pixmap(matrix=mat)

            file_name = f"page-{page_index:03d}.png"
            path = os.path.join(self.output_dir, file_name)
            pix.save(path)

            return RenderInfo(
                path=path,
                width=pix.width,
                height=pix.height,
                dpi=self.dpi,
            )
        finally:
            doc.close()
