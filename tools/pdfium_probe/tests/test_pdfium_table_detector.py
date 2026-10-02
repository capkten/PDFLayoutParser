from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, List, Optional, Tuple

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.ml.ml_table_detector import MLTableDetector
from pdfium_table_detector_adapter import (
    _find_pdfium_probe_bin,
    detect_tables_with_rust_probe,
)


def _get_repo_root() -> Path:
    probe_root = _TEST_DIR.parent
    fallback_repo = (
        probe_root.parents[1]
        if len(probe_root.parents) > 1
        else probe_root.parent.parent
    )
    return Path(os.environ.get("REPO_ROOT", str(fallback_repo)))


def _resolve_test_pdf() -> Path:
    repo_root = _get_repo_root()
    cand1 = repo_root / "test.pdf"
    if cand1.is_file():
        return cand1
    cand2 = Path("D:/codes/PDFLayoutParser/test.pdf")
    if cand2.is_file():
        return cand2
    cand3 = _TEST_DIR / "fixtures" / "test.pdf"
    if cand3.is_file():
        return cand3
    pytest.skip("test.pdf not found in repo or fixtures")


def _calculate_iou(b1: BBox, b2: BBox) -> float:
    ix0 = max(b1.x0, b2.x0)
    iy0 = max(b1.y0, b2.y0)
    ix1 = min(b1.x1, b2.x1)
    iy1 = min(b1.y1, b2.y1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area1 = (b1.x1 - b1.x0) * (b1.y1 - b1.y0)
    area2 = (b2.x1 - b2.x0) * (b2.y1 - b2.y0)
    union = area1 + area2 - intersection
    return intersection / union if union > 0 else 0.0


def test_rust_probe_binary_exists() -> None:
    bin_path = _find_pdfium_probe_bin()
    assert bin_path is not None, "pdfium_probe binary not found"
    assert Path(bin_path).is_file(), f"Binary path is not a file: {bin_path}"


def test_detect_tables_with_rust_probe_finds_tables() -> None:
    pdf_path = _resolve_test_pdf()
    results = detect_tables_with_rust_probe(str(pdf_path), page_index=27)

    assert len(results) >= 1, "Expected at least 1 table detected on page 27"
    for bbox, score in results:
        assert isinstance(bbox, BBox)
        assert isinstance(score, float)
        assert score >= 0.40
        assert bbox.x1 > bbox.x0
        assert bbox.y1 > bbox.y0
        assert bbox.x0 >= 0.0
        assert bbox.y0 >= 0.0


def test_detect_tables_rust_and_python_parity() -> None:
    import fitz

    pdf_path = _resolve_test_pdf()
    page_index = 27

    # 1. Rust probe detection
    rust_detections = detect_tables_with_rust_probe(str(pdf_path), page_index=page_index)

    # 2. Python MLTableDetector detection
    doc = fitz.open(str(pdf_path))
    try:
        py_page = doc[page_index]
        py_detector = MLTableDetector()
        py_detections = py_detector.detect_with_scores(py_page)
    finally:
        doc.close()

    # 3. Assert counts match
    assert len(rust_detections) == len(py_detections), (
        f"Detected table count mismatch: Rust={len(rust_detections)} vs Python={len(py_detections)}"
    )

    # 4. Compare bbox IoU, coordinate deltas (< 1.0 pt), and confidence score delta (< 0.05)
    for (r_box, r_score), (p_box, p_score) in zip(rust_detections, py_detections):
        iou = _calculate_iou(r_box, p_box)
        assert iou >= 0.95, f"IoU too low: {iou:.4f} < 0.95 for boxes {r_box} and {p_box}"

        assert abs(r_box.x0 - p_box.x0) < 1.0, f"x0 delta too large: {abs(r_box.x0 - p_box.x0)}"
        assert abs(r_box.y0 - p_box.y0) < 1.0, f"y0 delta too large: {abs(r_box.y0 - p_box.y0)}"
        assert abs(r_box.x1 - p_box.x1) < 1.0, f"x1 delta too large: {abs(r_box.x1 - p_box.x1)}"
        assert abs(r_box.y1 - p_box.y1) < 1.0, f"y1 delta too large: {abs(r_box.y1 - p_box.y1)}"

        assert abs(r_score - p_score) < 0.05, f"Score delta too large: {abs(r_score - p_score)}"


def test_detect_tables_blank_or_no_table_page() -> None:
    pdf_path = _resolve_test_pdf()
    # Page 0 has no tables
    results = detect_tables_with_rust_probe(str(pdf_path), page_index=0)
    assert results == [], f"Expected no tables on page 0, got {results}"


def test_detect_tables_fallback_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdfium_table_detector_adapter

    monkeypatch.setattr(pdfium_table_detector_adapter, "_find_pdfium_probe_bin", lambda: None)

    pdf_path = _resolve_test_pdf()
    results = detect_tables_with_rust_probe(str(pdf_path), page_index=27)
    assert len(results) >= 1
    bbox, score = results[0]
    assert isinstance(bbox, BBox)
    assert isinstance(score, float)
    assert score >= 0.40


def test_detect_tables_confidence_threshold_filtering() -> None:
    pdf_path = _resolve_test_pdf()
    # Setting threshold higher than 0.99 should filter out tables on page 27
    results = detect_tables_with_rust_probe(
        str(pdf_path), page_index=27, confidence_threshold=0.999
    )
    assert results == [], f"Expected all tables filtered at threshold 0.999, got {results}"
