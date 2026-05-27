"""Utilities for YOLO-style layout detection models."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import cv2
import numpy as np


YOLO_LAYOUT_LABELS = [
    "Text",
    "Title",
    "Figure",
    "Figure caption",
    "Table",
    "Table caption",
    "Header",
    "Footer",
    "Circular seal",
    "Square seal",
    "Elliptical seal",
    "Riding seal",
    "Catalogue",
    "Handwriting",
    "QR code",
    "Bar code",
    "Equation",
    "Annotation",
]


def preprocess_yolo_image(
    image: np.ndarray,
    target_size: tuple[int, int] = (640, 640),
) -> np.ndarray:
    """Resize and normalize an image for an Ultralytics YOLO ONNX model."""

    target_w, target_h = target_size
    resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    tensor = resized.astype(np.float32) / 255.0
    tensor = np.transpose(tensor, (2, 0, 1))[np.newaxis, ...]
    return tensor.astype(np.float32)


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Pure-NumPy Non-Maximum Suppression."""

    if len(boxes) == 0:
        return []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return keep


def postprocess_yolo_layout(
    output: np.ndarray,
    orig_size: tuple[int, int],
    label_list: list[str] | None = None,
    confidence_threshold: float = 0.25,
    iou_threshold: float = 0.5,
    input_size: int = 640,
) -> list[dict[str, Any]]:
    """Convert YOLO detect output into drawable detections.

    The exported model returns ``(1, 4 + nc, N)`` where the first 4 values
    are center-format box coordinates in the input image space.
    """

    if output.ndim == 3:
        raw = output[0].T
    else:
        raw = output

    if raw.size == 0 or raw.shape[1] < 5:
        return []

    class_scores = raw[:, 4:]
    if class_scores.size == 0:
        return []

    best_class = class_scores.argmax(axis=1).astype(int)
    best_score = class_scores.max(axis=1)

    mask = best_score >= confidence_threshold
    if not np.any(mask):
        return []

    raw = raw[mask]
    best_class = best_class[mask]
    best_score = best_score[mask]

    cx, cy, w, h = raw[:, 0], raw[:, 1], raw[:, 2], raw[:, 3]
    boxes = np.stack([cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0], axis=1)

    orig_w, orig_h = orig_size
    scale_x = float(orig_w) / float(input_size)
    scale_y = float(orig_h) / float(input_size)

    detections: list[dict[str, Any]] = []
    unique_classes = sorted(set(best_class.tolist()))
    for cls_id in unique_classes:
        idxs = np.where(best_class == cls_id)[0]
        keep = _nms(boxes[idxs], best_score[idxs], iou_threshold)
        for keep_idx in keep:
            det_idx = idxs[keep_idx]
            x0, y0, x1, y1 = boxes[det_idx]
            x0 = float(np.clip(x0 * scale_x, 0.0, float(orig_w)))
            y0 = float(np.clip(y0 * scale_y, 0.0, float(orig_h)))
            x1 = float(np.clip(x1 * scale_x, 0.0, float(orig_w)))
            y1 = float(np.clip(y1 * scale_y, 0.0, float(orig_h)))
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
            label = (
                label_list[cls_id]
                if label_list is not None and cls_id < len(label_list)
                else f"class_{cls_id}"
            )
            detections.append(
                {
                    "class_id": int(cls_id),
                    "label": label,
                    "score": float(best_score[det_idx]),
                    "bbox": [x0, y0, x1, y1],
                }
            )

    detections.sort(key=lambda item: item["score"], reverse=True)
    return detections
