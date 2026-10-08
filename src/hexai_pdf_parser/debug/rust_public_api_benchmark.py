"""Compare the saved Python migration baseline with current Rust public APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import fitz
from hexai_pdf_parser.core.pdf_parser import PDFParser


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
FULL_PAGE = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return value.name
    return value


def _invoke(parser: PDFParser, api: str, out: Path) -> Any:
    if api == "text_region":
        return parser.extract_text_in_region(FULL_PAGE)
    if api == "table_region":
        return parser.extract_table_in_region(FULL_PAGE)
    if api == "table_structure":
        return parser.extract_table_structure(page_indices=[0])
    if api == "images":
        return parser.extract_images(str(out / "images"), page_indices=[0])
    if api == "image_region":
        return parser.extract_image_in_region(FULL_PAGE, str(out / "region-images"))
    if api == "render_pages":
        return parser.render_pages(str(out / "pages"), page_indices=[0])
    if api == "render_region":
        return parser.render_region(FULL_PAGE, str(out / "regions"))
    if api == "classify_page":
        return parser.classify_page(0)
    raise ValueError("unknown API: {}".format(api))


def _create_generated_image_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pixmap.set_rect(pixmap.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(100, 100, 200, 200), pixmap=pixmap)
    document.save(path)
    document.close()


def _public_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (Path(item).name if key == "path" and isinstance(item, str) else _public_data(item))
                for key, item in value.items() if key not in ("file", "decoded", "sha256")}
    if isinstance(value, list):
        return [_public_data(item) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 6)
    return value


def _sha256(value: Any) -> str:
    encoded = json.dumps(_public_data(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_summary(result: Any) -> Dict[str, Any]:
    data = _plain(result.data)
    if isinstance(data, list):
        count = len(data)
        first = data[0] if data else None
    else:
        count = int(data is not None)
        first = data
    summary: Dict[str, Any] = {"code": result.code, "message": result.message,
                               "data_type": type(data).__name__, "item_count": count,
                               "public_data_sha256": _sha256(data)}
    if isinstance(first, dict):
        summary["first_item_keys"] = sorted(key for key in first if key != "file")
        for key in ("bbox", "rows", "cols", "source", "width", "height", "page_type", "ext", "page_index", "resource_index"):
            if key in first:
                summary["first_item_{}".format(key)] = first[key]
        if isinstance(first.get("text"), str):
            summary["first_item_text_length"] = len(first["text"])
            summary["first_item_text_sha256"] = hashlib.sha256(first["text"].encode("utf-8")).hexdigest()
        cells = first.get("cells")
        if isinstance(cells, list):
            summary["first_item_cell_count"] = len(cells)
            summary["first_item_spans"] = [[c.get("rowspan", 1), c.get("colspan", 1)] for c in cells]
            summary["first_item_cell_text_sha256"] = hashlib.sha256("\n".join(
                str(cell.get("text", "")) for cell in cells).encode("utf-8")).hexdigest()
    if isinstance(data, list) and data and all(isinstance(item, dict) and "text" in item for item in data):
        summary["all_text_sha256"] = hashlib.sha256("\n".join(str(item["text"]) for item in data).encode("utf-8")).hexdigest()
    elif isinstance(first, str):
        summary["data"] = first
    return summary


def _baseline_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    data = result.get("data")
    summary: Dict[str, Any] = {"code": result.get("code"), "message": result.get("message"),
                               "data_type": type(data).__name__,
                               "item_count": len(data) if isinstance(data, list) else int(data is not None),
                               "public_data_sha256": _sha256(data)}
    first = data[0] if isinstance(data, list) and data else data
    if isinstance(first, dict):
        summary["first_item_keys"] = sorted(key for key in first if key != "file")
        for key in ("bbox", "rows", "cols", "source", "width", "height", "page_type", "ext", "page_index", "resource_index"):
            if key in first:
                summary["first_item_{}".format(key)] = first[key]
        if isinstance(first.get("text"), str):
            summary["first_item_text_length"] = len(first["text"])
            summary["first_item_text_sha256"] = hashlib.sha256(first["text"].encode("utf-8")).hexdigest()
        if isinstance(first.get("cells"), list):
            summary["first_item_cell_count"] = len(first["cells"])
            summary["first_item_spans"] = [[c.get("rowspan", 1), c.get("colspan", 1)] for c in first["cells"]]
            summary["first_item_cell_text_sha256"] = hashlib.sha256("\n".join(
                str(cell.get("text", "")) for cell in first["cells"]).encode("utf-8")).hexdigest()
    if isinstance(data, list) and data and all(isinstance(item, dict) and "text" in item for item in data):
        summary["all_text_sha256"] = hashlib.sha256("\n".join(str(item["text"]) for item in data).encode("utf-8")).hexdigest()
    elif isinstance(first, str):
        summary["data"] = first
    return summary


def _differences(baseline: Dict[str, Any], current: Dict[str, Any]) -> list:
    differences = []
    for key in sorted(set(baseline) | set(current)):
        if baseline.get(key) != current.get(key):
            differences.append({"field": key, "python_baseline": baseline.get(key),
                                "rust_current": current.get(key)})
    return differences


def _probe_table_structure(pdf: Path) -> Optional[str]:
    """Probe the Rust-loaded ORT runtime in isolation; return only a confirmed version error."""
    probe = r'''import sys
from hexai_pdf_parser.core.pdf_parser import PDFParser
try:
    result = PDFParser(sys.argv[1]).extract_table_structure(page_indices=[0])
    if result.code < 0:
        raise RuntimeError(result.message)
except BaseException as error:
    print("{}: {}".format(type(error).__name__, error), file=sys.stderr)
    raise SystemExit(2)
'''
    env = os.environ.copy()
    source_path = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_path, env.get("PYTHONPATH", "")) if part
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe, str(pdf)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("isolated Rust table_structure probe failed: {}".format(error)) from error
    if result.returncode == 0:
        return None
    detail = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if "BadVersion" in detail and "version_str" in detail:
        return detail
    raise RuntimeError("isolated Rust table_structure probe failed: {}".format(detail))


def run(baseline_path: Path, runs: int, output: Path, fixture_names: list) -> Dict[str, Any]:
    if runs < 5:
        raise ValueError("--runs must be at least 5")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    selected = fixture_names or list(baseline["cases"])
    reports = []
    api_names = list(next(iter(baseline["cases"].values()))["apis"])
    with tempfile.TemporaryDirectory(prefix="rust-public-api-bench-") as temp:
        temp_root = Path(temp)
        for fixture_name in selected:
            if fixture_name not in baseline["cases"]:
                raise ValueError("fixture missing from baseline: {}".format(fixture_name))
            pdf = FIXTURES / fixture_name
            if fixture_name == "generated_image.pdf" and not pdf.is_file():
                pdf = temp_root / "fixtures" / fixture_name
                pdf.parent.mkdir(parents=True, exist_ok=True)
                _create_generated_image_pdf(pdf)
            if not pdf.is_file():
                raise FileNotFoundError(pdf)
            for api in api_names:
                saved = baseline["cases"][fixture_name]["apis"][api]
                py_samples = saved["timing_ms"]["samples"]
                py_median = float(saved["timing_ms"].get("median", statistics.median(py_samples)))
                case_dir = temp_root / fixture_name / api
                case_dir.mkdir(parents=True)
                if api == "table_structure":
                    runtime_failure = _probe_table_structure(pdf)
                    if runtime_failure is not None:
                        reports.append({"fixture": fixture_name, "api": api, "status": "skipped",
                                        "reason": "isolated Rust API probe reported an ONNX Runtime version mismatch",
                                        "runtime_probe": runtime_failure,
                                        "python_median_ms": py_median, "rust_median_ms": None, "speedup": None,
                                        "difference_summary": [{"field": "runtime_probe", "python_baseline": None,
                                                                "rust_current": runtime_failure}]})
                        continue
                parser = PDFParser(str(pdf))
                # A current-code warmup precedes the measured Rust samples.
                warmup = _invoke(parser, api, case_dir / "warmup")
                if warmup.code < 0:
                    raise RuntimeError("warmup failed for {} / {}: {}".format(fixture_name, api, warmup.message))
                samples = []
                current = warmup
                for sample_index in range(runs):
                    sample_dir = case_dir / str(sample_index)
                    sample_dir.mkdir(parents=True)
                    start = time.perf_counter()
                    current = _invoke(parser, api, sample_dir)
                    samples.append((time.perf_counter() - start) * 1000.0)
                    if current.code < 0:
                        raise RuntimeError("run failed for {} / {}: {}".format(fixture_name, api, current.message))
                rust_median = statistics.median(samples)
                py_summary = _baseline_summary(saved["result"])
                rust_summary = _result_summary(current)
                reports.append({
                    "fixture": fixture_name,
                    "api": api,
                    "status": "measured",
                    "python_median_ms": py_median,
                    "rust_median_ms": rust_median,
                    "speedup": (py_median / rust_median) if rust_median else None,
                    "python_samples_ms": list(py_samples),
                    "rust_samples_ms": samples,
                    "difference_summary": _differences(py_summary, rust_summary),
                    "python_result_summary": py_summary,
                    "rust_result_summary": rust_summary,
                })
    payload = {"schema_version": 1, "baseline": str(baseline_path), "runs": runs,
               "warmups_per_side": 1, "timing_source": "saved Python baseline samples and current Rust calls",
               "results": reports}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", action="append", default=[])
    args = parser.parse_args()
    payload = run(args.baseline, args.runs, args.output, args.fixture)
    for item in payload["results"]:
        if item["status"] == "skipped":
            print("{fixture} {api}: skipped ({reason})".format(**item))
            continue
        print("{fixture} {api}: python={python_median_ms:.3f} ms rust={rust_median_ms:.3f} ms speedup={speedup:.3f}x differences={count}".format(
            count=len(item["difference_summary"]), **item))
    print("Wrote {} API/case measurements to {}".format(len(payload["results"]), args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
