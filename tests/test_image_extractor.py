"""Tests for the image extractor."""

from pathlib import Path

import pytest

from pdflayoutparser.image_extractor import ImageExtractor
from tests.conftest import make_pdf_with_image


class TestImageExtractor:
    def test_extract_images(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "with_image.pdf"
        make_pdf_with_image(pdf_path)

        output_dir = Path(tmp_dir) / "images"
        extractor = ImageExtractor(str(output_dir))
        images = extractor.extract(str(pdf_path), page_index=0)

        assert len(images) >= 1
        image = images[0]
        assert image.page_index == 0
        assert image.bbox is not None
        assert image.path is not None
        assert Path(image.path).exists()
