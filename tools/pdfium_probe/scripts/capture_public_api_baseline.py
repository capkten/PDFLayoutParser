"""Capture replayable Python public-API results before the Rust migration."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import fitz

from hexai_pdf_parser.pdf_parser import PDFParser
from tests.conftest import make_pdf_with_image


FULL_PAGE = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
PDF_NAMES = (
    "page_000_vector.pdf",
    "page_437_wireless.pdf",
    "page_705_scanned.pdf",
)


def normalize(value):
    """Convert API dataclasses and output files to portable JSON values."""
    if is_dataclass(value):
        return normalize(asdict(value))
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        result = {key: normalize(item) for key, item in value.items()}
        path = value.get("path")
        if path:
            file_path = Path(path)
            if not file_path.is_file():
                raise RuntimeError(f"API returned a missing file: {file_path}")
            result["path"] = file_path.name
            if "resource_index" in value:
                pixmap = fitz.Pixmap(str(file_path))
                result["file"] = {
                    "name": file_path.name,
                    "ext": file_path.suffix.lower().lstrip("."),
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
                }
            elif "dpi" in value:
                if file_path.suffix.lower() != ".png":
                    raise RuntimeError(f"render is not PNG: {file_path}")
                pixmap = fitz.Pixmap(str(file_path))
                if (pixmap.width, pixmap.height) != (value["width"], value["height"]):
                    raise RuntimeError(f"render dimensions disagree: {file_path}")
                result["file"] = {
                    "name": file_path.name,
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "decoded": True,
                }
        return result
    return value


def _call_api(parser, api_name, output_dir):
    if api_name == "text_region":
        return parser.extract_text_in_region(FULL_PAGE)
    if api_name == "table_region":
        return parser.extract_table_in_region(FULL_PAGE)
    if api_name == "table_structure":
        return parser.extract_table_structure(page_indices=[0])
    if api_name == "images":
        return parser.extract_images(str(output_dir), page_indices=[0])
    if api_name == "image_region":
        return parser.extract_image_in_region(FULL_PAGE, str(output_dir))
    if api_name == "render_pages":
        return parser.render_pages(str(output_dir), dpi=72, page_indices=[0])
    if api_name == "render_region":
        return parser.render_region(FULL_PAGE, str(output_dir), dpi=72)
    if api_name == "classify_page":
        return parser.classify_page(0)
    raise ValueError(api_name)


API_NAMES = (
    "text_region", "table_region", "table_structure", "images",
    "image_region", "render_pages", "render_region", "classify_page",
)


def capture_api_snapshot(pdf_path, temp_dir):
    """Capture one result per public API using separate output directories."""
    snapshots = {}
    with PDFParser(str(pdf_path), render_dpi=72) as parser:
        for api_name in API_NAMES:
            output_dir = temp_dir / api_name
            result = _call_api(parser, api_name, output_dir)
            if result.code == -1:
                raise RuntimeError(f"{pdf_path.name} {api_name}: {result.message}")
            snapshots[api_name] = normalize(result)
    return snapshots


def capture_timings(pdf_path, temp_dir):
    timings = {}
    for api_name in API_NAMES:
        with PDFParser(str(pdf_path), render_dpi=72) as parser:
            samples = []
            for run_index in range(6):
                output_dir = temp_dir / api_name / str(run_index)
                start = perf_counter_ns()
                result = _call_api(parser, api_name, output_dir)
                elapsed_ms = (perf_counter_ns() - start) / 1_000_000
                if result.code == -1:
                    raise RuntimeError(f"{pdf_path.name} {api_name}: {result.message}")
                normalize(result)
                if run_index:
                    samples.append(round(elapsed_ms, 3))
            timings[api_name] = {
                "samples": samples,
                "median": round(statistics.median(samples), 3),
            }
    return timings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = {}
    with tempfile.TemporaryDirectory(prefix="public-api-baseline-") as temp_name:
        temp_dir = Path(temp_name)
        image_pdf = temp_dir / "generated_image.pdf"
        make_pdf_with_image(str(image_pdf))
        pdf_paths = [ROOT / "tests" / "fixtures" / name for name in PDF_NAMES]
        pdf_paths.append(image_pdf)
        for pdf_path in pdf_paths:
            if not pdf_path.is_file():
                raise FileNotFoundError(pdf_path)
            case_dir = temp_dir / pdf_path.stem
            snapshots = capture_api_snapshot(pdf_path, case_dir / "snapshot")
            timings = capture_timings(pdf_path, case_dir / "timings")
            cases[pdf_path.name] = {
                "apis": {
                    name: {"result": snapshots[name], "timing_ms": timings[name]}
                    for name in API_NAMES
                }
            }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"schema_version": 1, "cases": cases}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Captured {len(cases)} PDFs and {len(API_NAMES)} APIs: {args.output}")


if __name__ == "__main__":
    main()
