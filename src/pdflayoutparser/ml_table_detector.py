"""YOLO-based table region detector.

This module wraps the bundled ``layoutanalysis.onnx`` model and extracts
only the ``Table`` class regions.  It is used as the optional ML backend
for table-region detection when the line-based extractor cannot find a
table structure on its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import fitz
import numpy as np

from pdflayoutparser.models import BBox
from pdflayoutparser.yolo_layout_utils import (
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
            "Install it with: pip install pdflayoutparser[ml]"
        )


def _resolve_default_model_path() -> Path:
    """Return the path to the bundled YOLO layout model file."""
    repo_model = (
        Path(__file__).resolve().parents[1]
        / "models"
        / "layoutanalysis"
        / "layoutanalysis.onnx"
    )
    if repo_model.exists():
        return repo_model

    # Fallback for packaged distributions that ship the model as package data.
    try:
        import importlib.resources

        data_ref = importlib.resources.files("pdflayoutparser") / "data" / "models"
        packaged_model = Path(str(data_ref)) / "layoutanalysis.onnx"
        if packaged_model.exists():
            return packaged_model
    except Exception:
        pass

    raise FileNotFoundError(
        f"Bundled model not found at {repo_model}. "
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
        model_path: str | None = None,
        confidence_threshold: float = 0.25,
        table_class_ids: set[int] | None = None,
        input_size: int = 640,
        render_dpi: int = 200,
    ):
        self._model_path = (
            Path(model_path) if model_path else _resolve_default_model_path()
        )
        self.confidence_threshold = confidence_threshold
        self.table_class_ids = table_class_ids or {4}
        self.input_size = input_size
        self.render_dpi = render_dpi
        self._session = None  # Lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, page: fitz.Page) -> List[BBox]:
        """Return table bounding boxes detected on *page*."""
        tensor, pix_width, pix_height, scale_x, scale_y = self._preprocess_page(page)
        output = self._run_inference(tensor)
        return self._postprocess(output, pix_width, pix_height, scale_x, scale_y)

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

    def _postprocess(
        self,
        output: np.ndarray,
        pix_width: int,
        pix_height: int,
        scale_x: float,
        scale_y: float,
    ) -> List[BBox]:
        """Filter detections by class and confidence, then map to page coords."""

        detections = postprocess_yolo_layout(
            output,
            orig_size=(pix_width, pix_height),
            label_list=YOLO_LAYOUT_LABELS,
            confidence_threshold=self.confidence_threshold,
            input_size=self.input_size,
        )

        bboxes: List[BBox] = []
        for det in detections:
            if det["class_id"] not in self.table_class_ids:
                continue
            x0, y0, x1, y1 = det["bbox"]
            bboxes.append(
                BBox(
                    x0=float(x0 * scale_x),
                    y0=float(y0 * scale_y),
                    x1=float(x1 * scale_x),
                    y1=float(y1 * scale_y),
                )
            )
        return bboxes

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
