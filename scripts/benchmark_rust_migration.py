"""Run the Python baseline benchmark used by the Rust migration sprints."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hexai_pdf_parser import PDFParser
from hexai_pdf_parser.debug.benchmark_utils import resolve_rust_mode
from hexai_pdf_parser.debug.benchmark_utils import summarize_timings_with_percentiles
from hexai_pdf_parser.debug.rust_migration_benchmark import (
    canonicalize_tables,
    write_benchmark_run,
)


def _commit():
    repository = Path(__file__).resolve().parents[1]
    try:
        return subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            "cannot resolve repository commit for {}".format(repository)
        ) from error


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_python(input_path, pages):
    result = PDFParser(input_path).extract_tables(page_indices=list(pages))
    if result.code == -1:
        raise RuntimeError(result.message)
    return result.data or []


def run_suite(mode: str, suite: str, input_path: str, pages: Sequence[int],
              warmups: int, runs: int, output_dir: str) -> Dict[str, object]:
    """Run a deterministic suite; Sprint 001 records non-routing baseline runs."""

    resolved_mode = resolve_rust_mode(mode or None)
    if warmups < 0 or runs <= 0:
        raise ValueError("warmups must be non-negative and runs must be positive")

    for _ in range(warmups):
        _extract_python(input_path, pages)
    timings = []
    tables = []
    for _ in range(runs):
        started = time.perf_counter()
        tables = _extract_python(input_path, pages)
        timings.append(time.perf_counter() - started)

    payload = {
        "commit": _commit(),
        "mode": resolved_mode,
        "suite": suite,
        "input_sha256": _sha256(input_path),
        "warmups": warmups,
        "runs": runs,
        "timings": summarize_timings_with_percentiles(timings),
        "output_manifest": {
            "tables": len(tables),
            "pages": list(pages),
            "route": "python_baseline",
        },
        "tables": canonicalize_tables(tables),
    }
    output_path = Path(output_dir) / (suite + "-" + resolved_mode + ".json")
    write_benchmark_run(output_path, payload)
    payload["output_manifest"] = dict(payload["output_manifest"], report=str(output_path))
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=None, choices=None)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--pdf", dest="input_path", required=True)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    pages = [int(page) for page in args.pages.split(",") if page.strip()]
    payload = run_suite(args.mode or "", args.suite, args.input_path, pages,
                        args.warmups, args.runs, args.output_dir)
    print(str(payload["output_manifest"]["report"]))


if __name__ == "__main__":
    main()
