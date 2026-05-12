"""Tests for the image extractor."""

from pathlib import Path
from types import SimpleNamespace

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

    def test_extract_images_uses_xref_to_match_bbox(self, tmp_dir, monkeypatch):
        class FakeDoc:
            def __init__(self):
                self.page = SimpleNamespace(
                    get_images=lambda full=True: [
                        (101, 0, 10, 10, 8, "ICCBased", "", "fzImg0", "", 0),
                        (202, 0, 10, 10, 8, "ICCBased", "", "fzImg1", "", 0),
                    ],
                    get_image_info=lambda xrefs=True: [
                        {"xref": 202, "bbox": (200.0, 200.0, 260.0, 260.0)},
                        {"xref": 101, "bbox": (10.0, 20.0, 30.0, 40.0)},
                    ],
                )

            def __getitem__(self, index):
                assert index == 0
                return self.page

            def extract_image(self, xref):
                return {
                    "image": b"fake-image-bytes",
                    "ext": "png",
                    "width": 10,
                    "height": 10,
                }

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.close()

        monkeypatch.setattr("fitz.open", lambda *args, **kwargs: FakeDoc())

        output_dir = Path(tmp_dir) / "images"
        extractor = ImageExtractor(str(output_dir))
        images = extractor.extract("dummy.pdf", page_index=0)

        assert [img.resource_index for img in images] == [0, 1]
        assert images[0].bbox.x0 == 10.0
        assert images[0].bbox.y0 == 20.0
        assert images[1].bbox.x0 == 200.0
        assert images[1].bbox.y0 == 200.0
