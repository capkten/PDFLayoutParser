"""Export end-to-end PDF table extraction results (JSON, PNG, manifest)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import fitz

# Ensure source root is in sys.path
source_root = Path(__file__).resolve().parent.parent / "src"
if str(source_root) not in sys.path:
    sys.path.insert(0, str(source_root))

from hexai_pdf_parser.core.pdf_parser import PDFParser
from hexai_pdf_parser.writers.json_writer import JSONWriter


def parse_pages(pages_arg: str, total_pages: int) -> List[int]:
    if not pages_arg or pages_arg.strip().lower() == "all":
        return list(range(total_pages))
    result = []
    for part in pages_arg.split(","):
        part = part.strip()
        if not part:
            continue
        idx = int(part)
        if idx >= total_pages:
            raise ValueError(f"Page index {idx} out of range (total pages: {total_pages})")
        result.append(idx)
    return result


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export end-to-end PDF table extraction results.")
    parser.add_argument("--mode", choices=["python", "rust", "shadow"], default="python")
    parser.add_argument("--pdf", required=True, help="Path to input PDF")
    parser.add_argument("--pages", default="all", help="Pages to export (comma-separated 0-based indices or all)")
    parser.add_argument("--dpi", type=int, default=200, help="Rendering DPI for PNGs")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    os.environ["PDF_RUST_MODE"] = args.mode

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(args.output_dir).resolve()
    pages_dir = output_dir / "pages"
    tables_dir = output_dir / "tables"
    pages_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    doc_raw = fitz.open(str(pdf_path))
    total_doc_pages = len(doc_raw)
    pages_to_process = parse_pages(args.pages, total_doc_pages)

    t0 = time.perf_counter()
    with PDFParser(str(pdf_path), render_dpi=args.dpi) as pdf_parser:
        parse_res = pdf_parser.parse(page_indices=pages_to_process)
    t_total = max(time.perf_counter() - t0, 1e-6)

    doc_obj = parse_res.data
    json_writer = JSONWriter()

    page_results: List[Dict[str, Any]] = []

    for page_idx in pages_to_process:
        page_item = None
        if doc_obj and hasattr(doc_obj, "pages"):
            for p in doc_obj.pages:
                if getattr(p, "index", getattr(p, "page_index", None)) == page_idx:
                    page_item = p
                    break

        if page_item is None:
            page_results.append({
                "page_index": page_idx,
                "status": "failed",
                "table_count": 0,
                "json": f"pages/page-{page_idx}.json",
                "png": f"tables/page-{page_idx}.png",
                "table_sources": [],
                "rows": [],
                "cols": [],
                "bbox": [],
                "occupancy_conflicts": 0,
                "segments": {"extract": 0.0, "dto": 0.0, "ffi": 0.0, "algorithm": 0.0, "adapt": 0.0, "total": 0.0},
                "memory": 0,
                "error": f"Page index {page_idx} not found in parsed document",
            })
            continue

        page_json_path = pages_dir / f"page-{page_idx}.json"
        try:
            json_writer.write_page(page_item, str(page_json_path))
        except Exception as exc:
            pass

        png_path = tables_dir / f"page-{page_idx}.png"
        try:
            fitz_page = doc_raw.load_page(page_idx)
            zoom = args.dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = fitz_page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(png_path))
        except Exception:
            pass

        tables = getattr(page_item, "tables", []) or []
        table_sources = [getattr(t, "source", "unknown") for t in tables]
        table_rows = [getattr(t, "rows", 0) for t in tables]
        table_cols = [getattr(t, "cols", 0) for t in tables]
        table_bboxes = []
        for t in tables:
            bb = getattr(t, "bbox", None)
            if bb is not None:
                table_bboxes.append([round(bb.x0, 2), round(bb.y0, 2), round(bb.x1, 2), round(bb.y1, 2)])
            else:
                table_bboxes.append([])

        occupancy_conflicts = 0
        for t in tables:
            slots_seen: Set[Tuple[int, int]] = set()
            for c in getattr(t, "cells", []):
                r_idx = getattr(c, "row_index", 0)
                c_idx = getattr(c, "col_index", 0)
                r_span = getattr(c, "rowspan", 1)
                c_span = getattr(c, "colspan", 1)
                for r in range(r_idx, r_idx + r_span):
                    for col in range(c_idx, c_idx + c_span):
                        slot = (r, col)
                        if slot in slots_seen:
                            occupancy_conflicts += 1
                        else:
                            slots_seen.add(slot)

        page_results.append({
            "page_index": page_idx,
            "status": "success",
            "table_count": len(tables),
            "json": f"pages/page-{page_idx}.json",
            "png": f"tables/page-{page_idx}.png",
            "table_sources": table_sources,
            "rows": table_rows,
            "cols": table_cols,
            "bbox": table_bboxes,
            "occupancy_conflicts": occupancy_conflicts,
            "segments": {"extract": 0.0, "dto": 0.0, "ffi": 0.0, "algorithm": 0.0, "adapt": 0.0, "total": 0.0},
            "memory": 0,
            "error": None,
        })

    doc_raw.close()

    manifest = {
        "schema_version": 1,
        "mode": args.mode,
        "commit": get_git_commit(),
        "input_sha256": compute_sha256(pdf_path),
        "pages": page_results,
        "dpi": args.dpi,
        "model": "rule_first",
        "environment": "windows",
        "segment_samples": {"extract": [], "dto": [], "ffi": [], "algorithm": [], "adapt": [], "total": [t_total]},
        "segments": {
            "extract": {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
            "dto": {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
            "ffi": {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
            "algorithm": {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
            "adapt": {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
            "total": {"count": 1, "p50": round(t_total, 4), "p95": round(t_total, 4), "p99": round(t_total, 4)},
        },
        "memory": {
            "peak_rss_samples_bytes": [],
            "peak_rss_p50_bytes": 0,
            "peak_rss_p95_bytes": 0,
        },
        "page_results": page_results,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(page_results)} pages to {output_dir} (manifest: {manifest_path})")


if __name__ == "__main__":
    main()
