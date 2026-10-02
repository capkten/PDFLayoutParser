"""PDFium Rust native pipeline adapter.

Provides Python integration for invoking the compiled `pdfium_probe parse`
CLI subcommand, executing the pure Rust end-to-end PDF processing pipeline
with fallback to Python `Pipeline`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Union

__all__ = ["parse_pdf_with_rust_probe"]


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


def _python_fallback_pipeline(
    pdf_path: str,
    output_dir: str,
    page_indices: Optional[List[int]] = None,
    render_dpi: float = 72.0,
    model_path: Optional[str] = None,
    confidence_threshold: float = 0.40,
    export_renders: bool = True,
    export_pages: bool = True,
) -> Dict[str, Any]:
    """Fallback execution using Python Pipeline."""
    from hexai_pdf_parser.core.pipeline import Pipeline
    from hexai_pdf_parser.writers.json_writer import JSONWriter

    pipeline = Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=int(round(render_dpi)),
        page_indices=page_indices,
        ml_model_path=model_path,
        ml_confidence=confidence_threshold,
    )
    document = pipeline.run()
    out_json_path = os.path.join(output_dir, "output.json")
    if os.path.isfile(out_json_path):
        with open(out_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return JSONWriter().to_dict(document)


def parse_pdf_with_rust_probe(
    pdf_path: str,
    output_dir: str,
    page_indices: Optional[List[int]] = None,
    render_dpi: float = 72.0,
    model_path: Optional[str] = None,
    confidence_threshold: float = 0.40,
    export_renders: bool = True,
    export_pages: bool = True,
) -> Dict[str, Any]:
    """Execute pure Rust end-to-end `parse` pipeline with fallback to Python `Pipeline`.

    Args:
        pdf_path: Path to target PDF document.
        output_dir: Output directory path where output.json, output.md, pages/, renders/ are written.
        page_indices: Optional list of 0-based page indices to process.
        render_dpi: Rasterization DPI for page renders (default: 72.0).
        model_path: Optional path to table detection ONNX model.
        confidence_threshold: Confidence score threshold for table detection (default: 0.40).
        export_renders: Whether to render and export page PNG images (default: True).
        export_pages: Whether to export per-page markdown and json files (default: True).

    Returns:
        JSON dictionary loaded from output.json.
    """
    target_pdf = _resolve_target_pdf(pdf_path)
    actual_pdf_path = str(target_pdf.resolve()) if target_pdf is not None else str(pdf_path)

    bin_path = _find_pdfium_probe_bin()
    if bin_path is None or not Path(bin_path).is_file():
        return _python_fallback_pipeline(
            pdf_path=actual_pdf_path,
            output_dir=output_dir,
            page_indices=page_indices,
            render_dpi=render_dpi,
            model_path=model_path,
            confidence_threshold=confidence_threshold,
            export_renders=export_renders,
            export_pages=export_pages,
        )

    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        bin_path,
        "parse",
        actual_pdf_path,
        "--output",
        str(output_dir),
        "--dpi",
        str(render_dpi),
    ]

    if page_indices is not None and len(page_indices) > 0:
        cmd.extend(["--pages", ",".join(str(p) for p in page_indices)])

    if model_path is not None:
        cmd.extend(["--model", str(model_path)])

    if confidence_threshold is not None:
        cmd.extend(["--confidence", str(confidence_threshold)])

    if not export_renders:
        cmd.append("--no-renders")

    if not export_pages:
        cmd.append("--no-pages")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            return _python_fallback_pipeline(
                pdf_path=actual_pdf_path,
                output_dir=output_dir,
                page_indices=page_indices,
                render_dpi=render_dpi,
                model_path=model_path,
                confidence_threshold=confidence_threshold,
                export_renders=export_renders,
                export_pages=export_pages,
            )

        out_json_path = os.path.join(output_dir, "output.json")
        if not os.path.isfile(out_json_path):
            return _python_fallback_pipeline(
                pdf_path=actual_pdf_path,
                output_dir=output_dir,
                page_indices=page_indices,
                render_dpi=render_dpi,
                model_path=model_path,
                confidence_threshold=confidence_threshold,
                export_renders=export_renders,
                export_pages=export_pages,
            )

        with open(out_json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return _python_fallback_pipeline(
            pdf_path=actual_pdf_path,
            output_dir=output_dir,
            page_indices=page_indices,
            render_dpi=render_dpi,
            model_path=model_path,
            confidence_threshold=confidence_threshold,
            export_renders=export_renders,
            export_pages=export_pages,
        )
