from pathlib import Path

from hexai_pdf_parser.layout_model_utils import (
    bbox_from_detection_row,
    save_image_with_fallback,
)


def test_bbox_from_detection_row_keeps_pixel_coordinates_and_clips_bounds():
    row = (11, 0.58, 1304.5384, 1178.5544, 2883.3748, 1399.1796)

    bbox = bbox_from_detection_row(row, image_size=(1654, 2339))

    assert bbox == (1304.5384, 1178.5544, 1654.0, 1399.1796)


def test_save_image_with_fallback_writes_bytes_when_imwrite_fails(tmp_dir):
    output_path = Path(tmp_dir) / "layout" / "page_001.jpg"
    image = object()

    def fake_imwrite(*_args, **_kwargs):
        return False

    def fake_imencode(ext, _image):
        assert ext == ".jpg"
        return True, b"fake-jpeg-bytes"

    save_image_with_fallback(output_path, image, fake_imwrite, fake_imencode)

    assert output_path.exists()
    assert output_path.read_bytes() == b"fake-jpeg-bytes"
