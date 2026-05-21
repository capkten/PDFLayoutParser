from __future__ import annotations

import numpy as np
import pytest

from pdflayoutparser.yolo_layout_utils import (
    YOLO_LAYOUT_LABELS,
    postprocess_yolo_layout,
    preprocess_yolo_image,
)


def test_preprocess_yolo_image_returns_nchw_float32():
    img = np.full((12, 16, 3), 255, dtype=np.uint8)

    tensor = preprocess_yolo_image(img, (640, 640))

    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert float(tensor.max()) == 1.0
    assert float(tensor.min()) == 1.0


def test_postprocess_yolo_layout_scales_boxes_and_applies_nms():
    output = np.zeros((1, 22, 2), dtype=np.float32)
    # Two overlapping table candidates; only the higher-confidence one should remain.
    output[0, 0, 0] = 100.0
    output[0, 1, 0] = 120.0
    output[0, 2, 0] = 40.0
    output[0, 3, 0] = 20.0
    output[0, 4 + 4, 0] = 0.90

    output[0, 0, 1] = 102.0
    output[0, 1, 1] = 121.0
    output[0, 2, 1] = 42.0
    output[0, 3, 1] = 22.0
    output[0, 4 + 4, 1] = 0.80

    detections = postprocess_yolo_layout(
        output,
        orig_size=(1280, 960),
        label_list=YOLO_LAYOUT_LABELS,
        confidence_threshold=0.5,
        iou_threshold=0.5,
        input_size=640,
    )

    assert len(detections) == 1
    det = detections[0]
    assert det["class_id"] == 4
    assert det["label"] == "Table"
    assert det["score"] == pytest.approx(0.90)
    x0, y0, x1, y1 = det["bbox"]
    assert round(x0, 1) == 160.0
    assert round(y0, 1) == 165.0
    assert round(x1, 1) == 240.0
    assert round(y1, 1) == 195.0
