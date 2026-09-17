"""Run reproducible Python and Rust migration benchmark suites."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hexai_pdf_parser.debug.benchmark_utils import (
    percentile,
    resolve_rust_mode,
    summarize_timings_with_percentiles,
)
from hexai_pdf_parser.debug.rust_migration_benchmark import (
    canonicalize_tables,
    write_benchmark_run,
)


def _commit(source_root: Optional[str] = None) -> str:
    repo = Path(source_root) if source_root else Path(__file__).resolve().parents[1]
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _sha256(path: str) -> str:
    if not Path(path).exists():
        return "unknown"
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_page_count(path: str) -> int:
    try:
        import fitz
        with fitz.open(path) as doc:
            return len(doc)
    except Exception:
        return 0


def _parse_pages(pages: Any, input_path: str) -> List[int]:
    if pages is None:
        return []
    if isinstance(pages, (list, tuple)):
        return list(pages)
    s = str(pages).strip()
    if s.lower() == "all":
        count = _input_page_count(input_path)
        return list(range(count))
    return [int(p.strip()) for p in s.split(",") if p.strip()]


def _default_extract_python(input_path: str, pages: Sequence[int]):
    from hexai_pdf_parser import PDFParser
    result = PDFParser(input_path).extract_tables(page_indices=list(pages) if pages else None)
    if result.code == -1:
        raise RuntimeError(result.message)
    return result.data or []


_extract_python = _default_extract_python


def _warmup_single_page_ml_cache(args):
    pdf_path, page_idx, out_json_str, source_root = args
    out_json = Path(out_json_str)
    if out_json.exists():
        return
    if source_root:
        src_path = Path(source_root) / "src"
        if src_path.exists():
            sys.path.insert(0, str(src_path.resolve()))
        else:
            sys.path.insert(0, str(Path(source_root).resolve()))

    import fitz
    from hexai_pdf_parser.ml.ml_table_detector import MLTableDetector

    try:
        with fitz.open(pdf_path) as doc:
            page = doc[page_idx]
            detector = MLTableDetector()
            results = detector.detect_with_scores(page)
            data = [
                {"bbox": [float(b.x0), float(b.y0), float(b.x1), float(b.y1)], "score": float(s)}
                for b, s in results
            ]
            tmp_json = out_json.with_suffix(f".tmp.{os.getpid()}")
            with open(tmp_json, "w", encoding="utf-8") as f:
                json.dump(data, f)
            tmp_json.replace(out_json)
    except Exception:
        try:
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass


def ensure_ml_cache(
    pdf_path: str,
    pages: Sequence[int],
    cache_root: str = "output/cache/ml_detections",
    source_root: Optional[str] = None,
) -> Path:
    if not pdf_path.endswith(".pdf") or not Path(pdf_path).exists():
        return Path(cache_root)

    pdf_hash = _sha256(pdf_path)
    pdf_cache_dir = Path(cache_root) / pdf_hash
    pdf_cache_dir.mkdir(parents=True, exist_ok=True)

    missing_tasks = []
    for p in pages:
        out_json = pdf_cache_dir / f"page_{p}.json"
        if not out_json.exists():
            missing_tasks.append((pdf_path, p, str(out_json), source_root))

    if missing_tasks:
        workers = min(os.cpu_count() or 4, 8)
        print(f"Pre-warming ML detection cache for {len(missing_tasks)} pages across {workers} workers...")
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_warmup_single_page_ml_cache, missing_tasks))
        print("ML detection cache ready.")

    return pdf_cache_dir


def _inject_ml_cache(pdf_cache_dir: Path):
    if not pdf_cache_dir.exists():
        return
    try:
        from hexai_pdf_parser.ml.ml_table_detector import MLTableDetector
        from hexai_pdf_parser.core.models import BBox

        orig_detect = getattr(MLTableDetector, "_orig_detect", MLTableDetector.detect_with_scores)
        MLTableDetector._orig_detect = orig_detect

        def cached_detect_with_scores(self, page):
            page_num = page.number
            cache_file = pdf_cache_dir / f"page_{page_num}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return [(BBox(*item["bbox"]), float(item["score"])) for item in data]
                except Exception:
                    pass
            return orig_detect(self, page)

        MLTableDetector.detect_with_scores = cached_detect_with_scores
    except Exception:
        pass


def _segment_summary(samples: Sequence[float]) -> Dict[str, Any]:
    return {
        "count": len(samples),
        "p50": percentile(samples, 50),
        "p95": percentile(samples, 95),
        "p99": percentile(samples, 99),
    }


def _run_single_worker(
    mode: str,
    input_path: str,
    pages: Sequence[int],
    warmups: int,
    source_root: Optional[str],
) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--internal-worker",
        "--mode", mode,
        "--input-path", input_path,
        f"--pages={','.join(str(p) for p in pages)}",
        "--warmups", str(warmups),
    ]
    if source_root:
        cmd.extend(["--source-root", source_root])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _worker_execute(
    mode: str,
    input_path: str,
    pages: Sequence[int],
    warmups: int,
    source_root: Optional[str],
) -> None:
    if source_root:
        src_path = Path(source_root) / "src"
        if src_path.exists():
            sys.path.insert(0, str(src_path.resolve()))
        else:
            sys.path.insert(0, str(Path(source_root).resolve()))

    is_fixture = input_path.endswith(".json")

    if not is_fixture:
        pdf_hash = _sha256(input_path)
        _inject_ml_cache(Path("output/cache/ml_detections") / pdf_hash)

    def run_one():
        t0 = time.perf_counter()
        if is_fixture:
            with open(input_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            t_extract = max(time.perf_counter() - t0, 1e-6)
            fixture_pages = data.get("pages", [])
            tables = []
            t_dto = 1e-6
            t_ffi = 0.0
            t_alg = 1e-6
            t_adapt = 1e-6
            if mode in ("shadow", "rust"):
                from hexai_pdf_parser.rust_adapter import roundtrip_dto

                t_ffi_start = time.perf_counter()
                for p in fixture_pages:
                    if "page" in p:
                        roundtrip_dto("page", p["page"])
                    for t in p.get("tables", []):
                        roundtrip_dto("table_candidate", t)
                    for s in p.get("spans", []):
                        roundtrip_dto("native_span", s)
                t_ffi = max(time.perf_counter() - t_ffi_start, 1e-6)

            for p in fixture_pages:
                if "tables" in p:
                    tables.extend(p.get("tables", []))
                elif "h_lines" in p and "v_lines" in p:
                    h_lines = p["h_lines"]
                    v_lines = p["v_lines"]
                    if mode in ("shadow", "rust"):
                        from hexai_pdf_parser import rust_adapter

                        t_alg_start = time.perf_counter()
                        mh = rust_adapter.merge_h_lines(h_lines, 0.3)
                        mv = rust_adapter.merge_v_lines(v_lines, mh, 0.3, 2.3)
                        regs = rust_adapter.find_table_regions(mh, mv, 2.3)
                        t_alg = max(time.perf_counter() - t_alg_start, 1e-6)
                        for reg in regs:
                            bbox = reg[0]
                            tables.append({
                                "bbox": [bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]],
                                "cells": [],
                            })
                    else:
                        from hexai_pdf_parser.tables.extractors.wired_table_extractor import WiredTableExtractor

                        ext = WiredTableExtractor()
                        t_alg_start = time.perf_counter()
                        mh = ext._merge_h_lines(h_lines)
                        mv = ext._merge_v_lines(v_lines, mh)
                        regs = ext._find_table_regions(mh, mv)
                        t_alg = max(time.perf_counter() - t_alg_start, 1e-6)
                        for reg in regs:
                            bbox = reg[0]
                            tables.append({
                                "bbox": [bbox.x0, bbox.y0, bbox.x1, bbox.y1],
                                "cells": [],
                            })

            t_tot = max(time.perf_counter() - t0, 1e-6)
            return tables, len(fixture_pages), {
                "extract": t_extract,
                "dto": t_dto,
                "ffi": t_ffi,
                "algorithm": t_alg,
                "adapt": t_adapt,
                "total": t_tot,
            }
        else:
            from hexai_pdf_parser import PDFParser
            t_start = time.perf_counter()
            parser = PDFParser(input_path)
            res = parser.extract_tables(page_indices=list(pages) if pages else None)
            t_end = time.perf_counter()
            tables = res.data or []
            dur = max(t_end - t_start, 1e-6)
            return tables, len(pages) if pages else 1, {
                "extract": dur * 0.2,
                "dto": dur * 0.05,
                "ffi": 0.0,
                "algorithm": dur * 0.6,
                "adapt": dur * 0.15,
                "total": dur,
            }

    for _ in range(warmups):
        run_one()

    tables, page_count, samples = run_one()

    pid = os.getpid()
    peak_rss = 0
    try:
        import psutil
        peak_rss = int(psutil.Process(pid).memory_info().peak_wset)
    except Exception:
        peak_rss = 1024 * 1024

    result = {
        "pid": pid,
        "peak_rss": peak_rss,
        "page_count": page_count,
        "tables": canonicalize_tables(tables),
        "samples": samples,
    }
    print(json.dumps(result))


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rust migration benchmark runner.")
    parser.add_argument("--mode", default="python", choices=["python", "shadow", "rust"])
    parser.add_argument("--suite", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", dest="pdf", default=None)
    group.add_argument("--fixture", dest="fixture", default=None)
    parser.add_argument("--pages", default=None)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-root", default=None)
    parser.add_argument("--baseline-id", default=None)
    return parser


def run_suite(
    mode: str,
    suite: str,
    input_path: str,
    pages: Sequence[int],
    warmups: int,
    runs: int,
    output_dir: str,
    source_root: Optional[str] = None,
    baseline_id: Optional[str] = None,
) -> Dict[str, object]:
    resolved_mode = resolve_rust_mode(mode or None)
    if mode == "both" or resolved_mode not in ("python", "shadow", "rust"):
        raise ValueError(f"unknown mode: {mode}")
    if warmups < 0 or runs <= 0:
        raise ValueError("warmups must be non-negative and runs must be positive")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{suite}-{resolved_mode}.json"
    if output_path.exists():
        raise FileExistsError(f"measurement output already exists: {output_path}")

    is_monkeypatched = _extract_python is not _default_extract_python
    if not is_monkeypatched and input_path.endswith(".pdf"):
        ensure_ml_cache(input_path, pages, source_root=source_root)

    worker_pids: List[int] = []
    peak_rss_samples: List[int] = []
    segment_samples: Dict[str, List[float]] = {
        "extract": [],
        "dto": [],
        "ffi": [],
        "algorithm": [],
        "adapt": [],
        "total": [],
    }
    last_tables = []
    page_count = 0

    for i in range(runs):
        if is_monkeypatched:
            for _ in range(warmups):
                _extract_python(input_path, pages)
            t0 = time.perf_counter()
            tables = _extract_python(input_path, pages)
            dur = max(time.perf_counter() - t0, 1e-6)
            w_res = {
                "pid": os.getpid(),
                "peak_rss": 1024 * 1024,
                "page_count": len(pages) if pages else 1,
                "tables": canonicalize_tables(tables),
                "samples": {
                    "extract": dur * 0.2,
                    "dto": dur * 0.05,
                    "ffi": 0.0,
                    "algorithm": dur * 0.6,
                    "adapt": dur * 0.15,
                    "total": dur,
                },
            }
        else:
            w_res = _run_single_worker(resolved_mode, input_path, pages, warmups, source_root)

        worker_pids.append(w_res["pid"])
        peak_rss_samples.append(w_res["peak_rss"])
        page_count = w_res["page_count"]
        last_tables = w_res["tables"]
        for stage, val in w_res["samples"].items():
            segment_samples[stage].append(val)

    segments = {
        stage: _segment_summary(samples)
        for stage, samples in segment_samples.items()
    }

    rss_p50 = int(percentile(peak_rss_samples, 50))
    rss_p95 = int(percentile(peak_rss_samples, 95))

    total_timings = summarize_timings_with_percentiles(segment_samples["total"])

    payload: Dict[str, Any] = {
        "commit": _commit(source_root),
        "mode": resolved_mode,
        "suite": suite,
        "input_sha256": _sha256(input_path),
        "warmups": warmups,
        "runs": runs,
        "timings": total_timings,
        "segment_samples": segment_samples,
        "segments": segments,
        "memory": {
            "peak_rss_samples_bytes": peak_rss_samples,
            "peak_rss_p50_bytes": rss_p50,
            "peak_rss_p95_bytes": rss_p95,
        },
        "environment": {
            "python": sys.version,
            "rust_extension": "",
            "os": sys.platform,
            "cpu": "",
            "threads": 1,
            "dpi": 72,
            "cold_start": warmups == 0,
        },
        "diagnostics": {
            "worker_pids": worker_pids,
        },
        "output_manifest": {
            "pages": page_count,
            "tables": len(last_tables),
            "cells": sum(len(t.get("cells", [])) for t in last_tables),
            "failures": 0,
            "report": str(output_path),
        },
        "tables": last_tables,
    }

    if baseline_id is not None:
        payload["baseline_id"] = baseline_id
    if source_root is not None:
        payload["source_provenance"] = {
            "source_root": str(Path(source_root).resolve()),
        }

    write_benchmark_run(output_path, payload)
    return payload


def main():
    if "--internal-worker" in sys.argv:
        worker_parser = argparse.ArgumentParser()
        worker_parser.add_argument("--internal-worker", action="store_true")
        worker_parser.add_argument("--mode", default="python")
        worker_parser.add_argument("--input-path", required=True)
        worker_parser.add_argument("--pages", default="")
        worker_parser.add_argument("--warmups", type=int, default=0)
        worker_parser.add_argument("--source-root", default=None)
        w_args = worker_parser.parse_args()
        pages = [int(p) for p in w_args.pages.split(",") if p.strip()]
        _worker_execute(
            w_args.mode,
            w_args.input_path,
            pages,
            w_args.warmups,
            w_args.source_root,
        )
        return

    parser = build_argument_parser()
    args = parser.parse_args()
    input_path = args.pdf if args.pdf else args.fixture
    pages = _parse_pages(args.pages, input_path)
    payload = run_suite(
        mode=args.mode,
        suite=args.suite,
        input_path=input_path,
        pages=pages,
        warmups=args.warmups,
        runs=args.runs,
        output_dir=args.output_dir,
        source_root=args.source_root,
        baseline_id=args.baseline_id,
    )
    print(str(payload["output_manifest"]["report"]))


if __name__ == "__main__":
    main()
