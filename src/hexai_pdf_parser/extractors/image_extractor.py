"""Image extractor module.

Extracts embedded image resources from a PDF page using PyMuPDF.
"""

import os
from collections import defaultdict
from typing import List

import fitz

from hexai_pdf_parser.core.models import BBox, Image


class ImageExtractor:
    """Extract embedded images from a PDF page.

    Example::

        extractor = ImageExtractor(output_dir="/tmp/images")
        images = extractor.extract("doc.pdf", page_index=0)
    """

    def __init__(self, output_dir: str):
        """Create *output_dir* if it does not exist."""
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract(self, file_path: str, page_index: int) -> List[Image]:
        """Return a list of :class:`Image` objects for the given *page_index*."""
        doc = fitz.open(file_path)
        try:
            page = doc[page_index]
            image_list = page.get_images(full=True)
            image_infos = page.get_image_info(xrefs=True)
            bbox_by_xref = defaultdict(list)
            for info in image_infos:
                xref = info.get("xref")
                bbox = info.get("bbox")
                if xref is None or bbox is None:
                    continue
                bbox_by_xref[xref].append(BBox(*bbox))

            images: List[Image] = []

            for img_index, img in enumerate(image_list):
                xref = img[0]
                bbox = None
                if bbox_by_xref.get(xref):
                    bbox = bbox_by_xref[xref].pop(0)
                # A resource without a page placement cannot participate in
                # reading order and would create LayoutElement(bbox=None).
                # Keep only images that PyMuPDF can locate on this page.
                if bbox is None:
                    continue
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                ext = base_image["ext"]
                width = base_image["width"]
                height = base_image["height"]

                file_name = f"page-{page_index:03d}-img-{img_index:03d}.{ext}"
                path = os.path.join(self.output_dir, file_name)
                with open(path, "wb") as f:
                    f.write(image_bytes)

                images.append(
                    Image(
                        bbox=bbox,
                        page_index=page_index,
                        resource_index=img_index,
                        width=width,
                        height=height,
                        path=path,
                        ext=ext,
                    )
                )

            return images
        finally:
            doc.close()
