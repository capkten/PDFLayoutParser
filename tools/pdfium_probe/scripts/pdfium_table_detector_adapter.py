"""PDFium Rust YOLO Table Detector adapter.

Provides Python integration for invoking the compiled `pdfium_probe detect-tables`
CLI subcommand, detecting table regions and confidence scores using the pure Rust
ONNX Runtime YOLO inference pipeline with fallback to Python `MLTableDetector`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

from hexai_pdf_parser.core.models import BBox

__all__ = ["detect_tables_with_rust_probe"]


def _find_pdfium_probe_bin() -> Optional[str]:
    """Locate compiled pdfium_probe binary (debug or release)."""
    env_bin = os.environ.get("PDFIUM_PROBE_BIN")
    if env_bin:
        cand = Path(env_bin)
        if cand.is_file():
            return str(cand.resolve())

    probe_root = Path(__file__).resolve().parents[1]
    fallback_repo = (
        probe_root.parents[1]
        if len(probe_root.parents) > 1
        else probe_root.parent.parent
    )
    repo_root = Path(os.environ.get("REPO_ROOT", str(fallback_repo)))
    bin_names = (
        ["pdfium_probe.exe", "pdfium_probe"]
        if os.name == "nt"
        else ["pdfium_probe", "pdfium_probe.exe"]
    )

    candidate_dirs: List[Path] = []
    cargo_target_dir = os.environ.get("CARGO_TARGET_DIR")
    if cargo_target_dir:
        c_target = Path(cargo_target_dir)
        candidate_dirs.extend([
            c_target / "release",
            c_target / "debug",
        ])

    candidate_dirs.extend([
        probe_root / "target" / "release",
        probe_root / "target" / "debug",
        fallback_repo / "tools" / "pdfium_probe" / "target" / "release",
        fallback_repo / "tools" / "pdfium_probe" / "target" / "debug",
        repo_root / "tools" / "pdfium_probe" / "target" / "release",
        repo_root / "tools" / "pdfium_probe" / "target" / "debug",
    ])

    for cdir in candidate_dirs:
        for bname in bin_names:
            cand = cdir / bname
            if cand.is_file():
                return str(cand.resolve())

    for bname in bin_names:
        which_path = shutil.which(bname)
        if which_path:
            p = Path(which_path)
            if p.is_file():
                return str(p.resolve())

    return None


def _resolve_target_pdf(pdf_path: Union[str, Path]) -> Optional[Path]:
    """Resolve input PDF path with fallback search locations."""
    target_pdf = Path(pdf_path)
    if target_pdf.is_file():
        return target_pdf

    probe_root = Path(__file__).resolve().parents[1]
    fallback_synth = probe_root / "test_data" / "synthetic" / target_pdf.name
    if fallback_synth.is_file():
        return fallback_synth

    repo_root = Path(os.environ.get("REPO_ROOT", str(probe_root.parents[1])))
    fallback_repo = repo_root / target_pdf.name
    if fallback_repo.is_file():
        return fallback_repo

    fallback_d = Path("D:/codes/PDFLayoutParser") / target_pdf.name
    if fallback_d.is_file():
        return fallback_d

    return None


def _resolve_model_arg(model_path: Optional[str] = None) -> str:
    """Resolve model path argument to an existing file path or 'auto'."""
    if model_path and model_path not in ("auto", "default"):
        p = Path(model_path)
        if p.is_file():
            return str(p.resolve())
        return str(model_path)

    env_model = os.environ.get("YOLO_TABLE_DETECTOR_MODEL")
    if env_model and Path(env_model).is_file():
        return str(Path(env_model).resolve())

    try:
        from hexai_pdf_parser.ml.ml_table_detector import _resolve_default_model_path
        resolved = _resolve_default_model_path()
        if resolved and Path(resolved).is_file():
            return str(Path(resolved).resolve())
    except Exception:
        pass

    return "auto"


def _python_fallback_detect(
    pdf_path: Path,
    page_index: int = 0,
    model_path: Optional[str] = None,
    confidence_threshold: float = 0.40,
) -> List[Tuple[BBox, float]]:
    """Fallback table detection using Python MLTableDetector pipeline."""
    try:
        import fitz
        from hexai_pdf_parser.ml.ml_table_detector import MLTableDetector

        doc = fitz.open(str(pdf_path))
        try:
            if page_index < 0 or page_index >= len(doc):
                return []
            page = doc[page_index]
            detector = MLTableDetector(
                model_path=model_path,
                confidence_threshold=confidence_threshold,
            )
            return detector.detect_with_scores(page)
        finally:
            doc.close()
    except Exception:
        return []


def detect_tables_with_rust_probe(
    pdf_path: str,
    page_index: int = 0,
    model_path: Optional[str] = None,
    confidence_threshold: float = 0.40,
) -> List[Tuple[BBox, float]]:
    """Execute `pdfium_probe detect-tables` CLI and return detected table bboxes and scores.

    Args:
        pdf_path: Path to target PDF document.
        page_index: 0-based page index.
        model_path: Optional path to ONNX model file. If None, resolves automatically.
        confidence_threshold: Minimum confidence score to retain detection (default: 0.40).

    Returns:
        List of (BBox, confidence_score) tuples for detected tables on the page.
    """
    target_pdf = _resolve_target_pdf(pdf_path)
    if target_pdf is None:
        return _python_fallback_detect(
            Path(pdf_path), page_index, model_path, confidence_threshold
        )

    probe_bin_str = _find_pdfium_probe_bin()
    if probe_bin_str is None:
        return _python_fallback_detect(
            target_pdf, page_index, model_path, confidence_threshold
        )

    probe_bin = Path(probe_bin_str)
    if not probe_bin.is_file():
        return _python_fallback_detect(
            target_pdf, page_index, model_path, confidence_threshold
        )

    out_tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_tmp_path = Path(out_tmp.name)
    out_tmp.close()

    model_arg = _resolve_model_arg(model_path)

    try:
        cmd = [
            str(probe_bin),
            "detect-tables",
            str(target_pdf.resolve()),
            str(page_index),
            model_arg,
            str(out_tmp_path.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            return _python_fallback_detect(
                target_pdf, page_index, model_path, confidence_threshold
            )

        if not out_tmp_path.is_file():
            return _python_fallback_detect(
                target_pdf, page_index, model_path, confidence_threshold
            )

        content = out_tmp_path.read_text(encoding="utf-8")
        raw_list = json.loads(content)

        results: List[Tuple[BBox, float]] = []
        for item in raw_list:
            score = float(item.get("score", 0.0))
            if score < confidence_threshold:
                continue
            x0 = round(float(item.get("x0", 0.0)), 1)
            y0 = round(float(item.get("y0", 0.0)), 1)
            x1 = round(float(item.get("x1", 0.0)), 1)
            y1 = round(float(item.get("y1", 0.0)), 1)
            results.append((BBox(x0=x0, y0=y0, x1=x1, y1=y1), score))

        return results

    except Exception:
        return _python_fallback_detect(
            target_pdf, page_index, model_path, confidence_threshold
        )

    finally:
        if out_tmp_path.is_file():
            try:
                out_tmp_path.unlink()
            except OSError:
                pass
