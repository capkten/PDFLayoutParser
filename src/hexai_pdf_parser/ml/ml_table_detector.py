"""YOLO-based table region detector.

This module wraps the bundled ``layoutanalysis.onnx`` model and extracts
only the ``Table`` class regions.  The pipeline invokes it on pages that
the recall-oriented rule pass identifies as table candidates.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple, Union

import fitz
import numpy as np

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.ml.yolo_layout_utils import (
    YOLO_LAYOUT_LABELS,
    postprocess_yolo_layout,
    preprocess_yolo_image,
)


def _require_onnxruntime():
    """Import and return onnxruntime, or raise a clear error."""
    try:
        import onnxruntime as ort

        return ort
    except ImportError:
        raise ImportError(
            "onnxruntime is required for ML table detection. "
            "Install it with: pip install hexai_pdf_parser[ml]"
        )


def _resolve_default_model_path() -> Path:
    """Return the path to the bundled YOLO table detector ONNX model."""
    candidates = [
        Path(__file__).resolve().parent / "table_detector_model" / "best.onnx",
        Path(__file__).resolve().parents[1] / "table_detector_model" / "best.onnx",
        Path(__file__).resolve().parents[2] / "models" / "table_detector" / "best.onnx",
        Path(__file__).resolve().parents[3] / "models" / "table_detector" / "best.onnx",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Fallback for packaged distributions that ship the model as package data.
    try:
        import importlib.resources

        data_ref = importlib.resources.files("hexai_pdf_parser") / "models" / "table_detector"
        packaged_model = Path(str(data_ref)) / "best.onnx"
        if packaged_model.exists():
            return packaged_model
    except Exception:
        pass

    raise FileNotFoundError(
        "Table detector model (best.onnx) not found in standard locations. "
        "Provide a custom path via model_path parameter."
    )


class MLTableDetector:
    """Detect table regions using the bundled YOLO layout-analysis model.

    Parameters
    ----------
    model_path:
        Path to an ONNX model file.  When ``None``, uses the bundled
        ``layoutanalysis.onnx`` model from the repository.
    confidence_threshold:
        Minimum confidence score to keep a detection.
    table_class_ids:
        Set of class IDs that represent tables in the model output.
        Default is ``{4}`` (YOLO class ``Table``).
    input_size:
        Model input image size (height == width).  Default ``640``.
    render_dpi:
        DPI used to rasterize the PDF page.  Higher values give better
        accuracy but use more memory and CPU time.  Default ``200``.
    """

    def __init__(
        self,
        model_path: Optional[Union[str, Path]] = None,
        confidence_threshold: float = 0.70,
        iou_threshold: float = 0.50,
        table_class_ids: Optional[set[int]] = None,
        input_size: int = 640,
        render_dpi: int = 200,
    ) -> None:
        self._model_path = (
            Path(model_path) if model_path else _resolve_default_model_path()
        )
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.table_class_ids = table_class_ids or {0, 4}
        self.input_size = input_size
        self.render_dpi = render_dpi
        self._session = None  # Lazy-loaded

    def __enter__(self) -> MLTableDetector:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Release underlying ONNX Runtime session resources."""
        self._session = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, page: fitz.Page) -> List[BBox]:
        """Return table bounding boxes detected on *page*."""
        return [b for b, _ in self.detect_with_scores(page)]

    def detect_with_scores(self, page: fitz.Page) -> List[Tuple[BBox, float]]:
        """Return table bounding boxes and model confidence scores detected on *page*."""
        tensor, pix_width, pix_height, scale_x, scale_y = self._preprocess_page(page)
        output = self._run_inference(tensor)
        results = self._postprocess_with_scores(output, pix_width, pix_height, scale_x, scale_y)

        # Filter detections that cover almost the entire page with low confidence —
        # these are typically false positives on pages without real tables.
        page_area = page.rect.width * page.rect.height
        results = [
            (bbox, score) for bbox, score in results
            if not (
                (bbox.x1 - bbox.x0) * (bbox.y1 - bbox.y0) > page_area * 0.85
                and score < 0.50
            )
        ]

        # Expand each detected table bbox to encompass any touching/intersecting text words
        try:
            all_words = page.get_text("words")
            if all_words:
                results = [
                    (self._expand_bbox_to_touching_words(bbox, all_words, page=page), score)
                    for bbox, score in results
                ]
        except Exception:
            pass

        return results

    @staticmethod
    def _expand_bbox_to_touching_words(
        bbox: BBox,
        words: List[Tuple[float, float, float, float, str]],
        margin: float = 3.0,
        page: Optional[fitz.Page] = None,
    ) -> BBox:
        """Expand table bbox outward if boundary overlaps or cuts into text words."""
        if not words:
            return bbox

        x0, y0, x1, y1 = bbox.x0, bbox.y0, bbox.x1, bbox.y1

        if page is not None:
            try:
                drawings = page.get_drawings()
                for d in drawings:
                    r = d.get("rect")
                    if r:
                        ix0 = max(x0, r.x0)
                        iy0 = max(y0, r.y0)
                        ix1 = min(x1, r.x1)
                        iy1 = min(y1, r.y1)
                        if ix1 > ix0 and iy1 > iy0:
                            x0 = min(x0, r.x0)
                            y0 = min(y0, r.y0)
                            x1 = max(x1, r.x1)
                            y1 = max(y1, r.y1)
            except Exception:
                pass

        expanded = True
        while expanded:
            expanded = False
            for w in words:
                wx0, wy0, wx1, wy1 = w[0], w[1], w[2], w[3]
                # Direct intersection/overlap
                if wx1 > x0 and wx0 < x1 and wy1 > y0 and wy0 < y1:
                    new_x0 = min(x0, wx0)
                    new_y0 = min(y0, wy0)
                    new_x1 = max(x1, wx1)
                    new_y1 = max(y1, wy1)
                    if new_x0 < x0 or new_y0 < y0 or new_x1 > x1 or new_y1 > y1:
                        x0, y0, x1, y1 = new_x0, new_y0, new_x1, new_y1
                        expanded = True
                # Word on same row line just outside left/right boundary
                elif (wy0 + wy1) / 2.0 >= y0 and (wy0 + wy1) / 2.0 <= y1:
                    if 0.0 <= x0 - wx1 <= 20.0:
                        x0 = min(x0, wx0)
                        expanded = True
                    elif 0.0 <= wx0 - x1 <= 15.0:
                        x1 = max(x1, wx1)
                        expanded = True

        return BBox(x0=round(x0, 1), y0=round(y0, 1), x1=round(x1, 1), y1=round(y1, 1))

    # ------------------------------------------------------------------
    # ONNX session
    # ------------------------------------------------------------------

    def _load_session(self):
        """Lazy-load the ONNX Runtime inference session."""
        if self._session is not None:
            return self._session

        ort = _require_onnxruntime()
        self._session = ort.InferenceSession(
            str(self._model_path),
            providers=["CPUExecutionProvider"],
        )
        return self._session

    def _run_inference(self, tensor: np.ndarray) -> np.ndarray:
        """Run ONNX inference and return the primary detection output."""
        session = self._load_session()
        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: tensor})
        return outputs[0]

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess_page(
        self, page: fitz.Page
    ) -> Tuple[np.ndarray, int, int, float, float]:
        """Render page to RGB image and prepare a YOLO tensor."""
        target = self.input_size
        factor = self.render_dpi / 72.0
        mat = fitz.Matrix(factor, factor)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3
        )

        scale_x = page.rect.width / pix.width
        scale_y = page.rect.height / pix.height

        tensor = preprocess_yolo_image(img, (target, target))
        return tensor, pix.width, pix.height, scale_x, scale_y

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _postprocess_with_scores(
        self,
        output: np.ndarray,
        pix_width: int,
        pix_height: int,
        scale_x: float,
        scale_y: float,
    ) -> List[Tuple[BBox, float]]:
        """Filter detections by class and confidence, then map to page coords."""

        detections = postprocess_yolo_layout(
            output,
            orig_size=(pix_width, pix_height),
            label_list=YOLO_LAYOUT_LABELS,
            confidence_threshold=self.confidence_threshold,
            iou_threshold=self.iou_threshold,
            input_size=self.input_size,
        )

        results: List[Tuple[BBox, float]] = []
        for det in detections:
            if det["class_id"] not in self.table_class_ids:
                continue
            x0, y0, x1, y1 = det["bbox"]
            score = float(det.get("score", 0.85))
            bbox = BBox(
                x0=float(x0 * scale_x),
                y0=float(y0 * scale_y),
                x1=float(x1 * scale_x),
                y1=float(y1 * scale_y),
            )
            results.append((bbox, score))
        return results

    # ------------------------------------------------------------------
    # NMS
    # ------------------------------------------------------------------

    @staticmethod
    def _nms(
        boxes: np.ndarray, scores: np.ndarray, iou_threshold: float
    ) -> List[int]:
        """Pure-NumPy Non-Maximum Suppression."""
        if len(boxes) == 0:
            return []

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        order = scores.argsort()[::-1]

        keep: List[int] = []
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
