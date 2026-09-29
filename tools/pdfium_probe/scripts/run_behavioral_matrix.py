#!/usr/bin/env python3
"""Run behavioral shadow matrix across PDFium and PyMuPDF extractions."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import fitz

from hexai_pdf_parser.core.models import Table
from hexai_pdf_parser.debug.table_visualizer import render_table_visualization
from pdfium_shadow_runner import run_shadow_page


def compute_file_sha256(path: Path) -> Optional[str]:
    """Compute SHA-256 hex digest of a file, returning None if file does not exist."""
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def to_canonical_obj(obj: Any) -> Any:
    """Recursively convert object to canonical representation with sorted keys and rounded floats."""
    if isinstance(obj, float):
        rounded = round(obj, 4)
        return 0.0 if rounded == 0.0 else rounded
    elif isinstance(obj, (dict, Mapping)):
        return {k: to_canonical_obj(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, (list, tuple)):
        return [to_canonical_obj(item) for item in obj]
    else:
        return obj


def canonical_json_bytes(data: Any) -> bytes:
    """Serialize data to compact canonical UTF-8 JSON bytes."""
    canonical_obj = to_canonical_obj(data)
    return json.dumps(
        canonical_obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(data: Any) -> str:
    """Compute SHA-256 of canonical JSON serialization."""
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


def detect_platform_key() -> str:
    """Detect current platform key matching manifest.json."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows" and machine in ("amd64", "x86_64"):
        return "win-x64"
    elif system == "linux" and machine in ("x86_64", "amd64"):
        return "linux-x64"
    elif system == "darwin":
        if "arm" in machine or machine == "aarch64":
            return "mac-arm64"
        else:
            return "mac-x64"
    return "win-x64"


def get_probe_root() -> Path:
    """Return root directory of pdfium_probe."""
    return Path(__file__).resolve().parents[1]


def get_repo_root() -> Path:
    """Return root directory of the main repository."""
    if "REPO_ROOT" in os.environ:
        return Path(os.environ["REPO_ROOT"])
    probe_root = get_probe_root()
    direct = probe_root.parents[1]
    if (direct / "test.pdf").exists():
        return direct
    worktree_parent = direct.parents[1]
    if (worktree_parent / "test.pdf").exists():
        return worktree_parent
    return direct


def render_table_overlays(
    pdf_path: Path,
    page_index: int,
    pdfium_tables: Sequence[Table],
    pymupdf_tables: Sequence[Table],
    output_dir: Path,
) -> Dict[str, str]:
    """Render table detection overlays for both engines onto page rasterizations."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdfium_png = out_dir / "pdfium_overlay.png"
    pymupdf_png = out_dir / "pymupdf_overlay.png"

    render_table_visualization(
        source=str(pdf_path),
        tables=pdfium_tables,
        output_path=str(pdfium_png),
        page_index=page_index,
    )
    render_table_visualization(
        source=str(pdf_path),
        tables=pymupdf_tables,
        output_path=str(pymupdf_png),
        page_index=page_index,
    )

    return {
        "pdfium": str(pdfium_png),
        "pymupdf": str(pymupdf_png),
    }


def _load_manifest_supply_chain(manifest_path: Path) -> Dict[str, Any]:
    """Load supply chain information from manifest.json for current platform."""
    if not manifest_path.is_file():
        return {
            "release_tag": "unknown",
            "archive_sha256": "unknown",
            "library_relpath": "unknown",
            "expected_library_sha256": None,
        }
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        platform_key = detect_platform_key()
        plat_info = data.get("platforms", {}).get(platform_key, {})
        return {
            "release_tag": data.get("release_tag", "unknown"),
            "archive_sha256": plat_info.get("archive_sha256", "unknown"),
            "library_relpath": plat_info.get("library_relpath", "unknown"),
            "expected_library_sha256": plat_info.get("library_sha256"),
        }
    except Exception:
        return {
            "release_tag": "unknown",
            "archive_sha256": "unknown",
            "library_relpath": "unknown",
            "expected_library_sha256": None,
        }


def _execute_fixture(
    fixture: Mapping[str, Any],
    pdfium_root: Path,
    fixture_dir: Path,
    supply_chain_info: Mapping[str, Any],
) -> Dict[str, Any]:
    """Execute single behavioral fixture for one pdfium_root run."""
    start_time = time.time()
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_name = str(fixture.get("name", "unnamed"))
    page_index = int(fixture.get("page_index", 0))
    table_regions = list(fixture.get("table_regions", []))

    probe_root = get_probe_root()
    repo_root = get_repo_root()

    pdf_root_type = str(fixture.get("pdf_root", "probe")).lower()
    raw_pdf_path = str(fixture.get("pdf_path", ""))
    if pdf_root_type == "probe":
        pdf_path = probe_root / raw_pdf_path
    else:
        pdf_path = repo_root / raw_pdf_path

    raw_snapshot_rel = str(fixture.get("pdfium_raw_snapshot", ""))
    baseline_rel = str(fixture.get("pymupdf_baseline", ""))

    raw_json_path = pdfium_root / raw_snapshot_rel
    baseline_json_path = pdfium_root / baseline_rel

    blocked_reason: Optional[str] = None

    if not pdf_path.is_file():
        blocked_reason = f"Live PDF file not found: {pdf_path}"
    elif not raw_json_path.is_file():
        blocked_reason = f"PDFium raw snapshot file not found: {raw_json_path}"
    elif not baseline_json_path.is_file():
        blocked_reason = f"PyMuPDF baseline file not found: {baseline_json_path}"

    live_pdf_sha = compute_file_sha256(pdf_path) if pdf_path.is_file() else None
    raw_json_sha = compute_file_sha256(raw_json_path) if raw_json_path.is_file() else None
    baseline_json_sha = (
        compute_file_sha256(baseline_json_path) if baseline_json_path.is_file() else None
    )

    raw_data: Optional[Dict[str, Any]] = None
    baseline_data: Optional[Dict[str, Any]] = None

    if blocked_reason is None:
        try:
            raw_data = json.loads(raw_json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            blocked_reason = f"Failed to parse PDFium raw snapshot: {exc}"

    if blocked_reason is None:
        try:
            baseline_data = json.loads(baseline_json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            blocked_reason = f"Failed to parse PyMuPDF baseline: {exc}"

    # Verify source SHA matches live PDF
    if blocked_reason is None and raw_data is not None and baseline_data is not None:
        raw_source_sha = raw_data.get("source_file_sha256")
        baseline_source_sha = baseline_data.get("source_file_sha256")

        if (
            raw_source_sha is not None
            and live_pdf_sha is not None
            and raw_source_sha.lower() != live_pdf_sha.lower()
        ):
            blocked_reason = (
                f"Stale input: PDFium raw snapshot source SHA ({raw_source_sha}) "
                f"mismatches live PDF SHA ({live_pdf_sha})"
            )
        elif (
            baseline_source_sha is not None
            and live_pdf_sha is not None
            and baseline_source_sha.lower() != live_pdf_sha.lower()
        ):
            blocked_reason = (
                f"Stale input: PyMuPDF baseline source SHA ({baseline_source_sha}) "
                f"mismatches live PDF SHA ({live_pdf_sha})"
            )

    # Locate page in raw snapshot and check bounds
    raw_page: Optional[Dict[str, Any]] = None
    if blocked_reason is None and raw_data is not None:
        pages = raw_data.get("pages", [])
        for p in pages:
            if isinstance(p, Mapping) and p.get("page_index") == page_index:
                raw_page = p
                break
        if raw_page is None:
            if 0 <= page_index < len(pages):
                raw_page = pages[page_index]
            else:
                blocked_reason = (
                    f"Page index {page_index} out of bounds in raw snapshot (pages count: {len(pages)})"
                )

    # Verify live PDF page index bounds
    doc: Optional[fitz.Document] = None
    fitz_page: Optional[fitz.Page] = None
    if blocked_reason is None:
        try:
            doc = fitz.open(pdf_path)
            if page_index < 0 or page_index >= len(doc):
                blocked_reason = (
                    f"Page index {page_index} out of bounds in live PDF (pages count: {len(doc)})"
                )
            else:
                fitz_page = doc[page_index]
        except Exception as exc:
            blocked_reason = f"Failed to open live PDF: {exc}"

    # Handle blocked input
    if blocked_reason is not None:
        if doc is not None:
            doc.close()

        status = "blocked_input"
        diff = {
            "passed": False,
            "categories": ["blocked_input"],
            "unclassified": [],
            "diagnostics": {"blocked_reason": blocked_reason},
        }
        (fixture_dir / "pdfium.md").write_text("", encoding="utf-8")
        (fixture_dir / "pymupdf.md").write_text("", encoding="utf-8")
        (fixture_dir / "layout_signature.json").write_text(
            json.dumps({"pdfium": [], "pymupdf": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (fixture_dir / "table_signature.json").write_text(
            json.dumps({"pdfium": [], "pymupdf": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (fixture_dir / "diff.json").write_text(
            json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (fixture_dir / "diagnostics.json").write_text(
            json.dumps({"blocked_reason": blocked_reason}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (fixture_dir / "errors.json").write_text(
            json.dumps([blocked_reason], indent=2, ensure_ascii=False), encoding="utf-8"
        )

        canonical_data = {
            "blocked_reason": blocked_reason,
            "diff": diff,
            "fixture_name": fixture_name,
            "layout_signature": {"pdfium": [], "pymupdf": []},
            "page_index": page_index,
            "pdfium_markdown": "",
            "pdfium_page_type": "unknown",
            "pymupdf_markdown": "",
            "pymupdf_page_type": "unknown",
            "status": status,
            "table_signature": {"pdfium": [], "pymupdf": []},
        }
        can_sha = canonical_sha256(canonical_data)

        result_content = {
            "canonical_sha256": can_sha,
            "diff": diff,
            "fixture_name": fixture_name,
            "layout_signature": {"pdfium": [], "pymupdf": []},
            "overlays": {},
            "page_index": page_index,
            "pdfium_markdown": "",
            "pdfium_page_type": "unknown",
            "pymupdf_markdown": "",
            "pymupdf_page_type": "unknown",
            "status": status,
            "table_signature": {"pdfium": [], "pymupdf": []},
        }
        (fixture_dir / "result.json").write_text(
            json.dumps(result_content, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        ledger_content = {
            "canonical_sha256": can_sha,
            "classification_evidence": {},
            "digests": {},
            "fixture_name": fixture_name,
            "input_pdf_sha256": live_pdf_sha,
            "metadata": {
                "blocked_reason": blocked_reason,
                "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                "fixture_dir": str(fixture_dir),
                "pdf_path": str(pdf_path),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "pdfium_raw_sha256": raw_json_sha,
            "pymupdf_baseline_sha256": baseline_json_sha,
            "runtime_versions": {
                "mupdf_version": getattr(fitz, "VersionFitz", "unknown"),
                "pymupdf_version": fitz.__version__,
            },
            "supply_chain": {
                "archive_sha256": supply_chain_info.get("archive_sha256"),
                "library_relpath": supply_chain_info.get("library_relpath"),
                "manifest_library_sha256": supply_chain_info.get("expected_library_sha256"),
                "manifest_library_verification": "unavailable",
                "native_library_expected_sha256": None,
                "native_library_sha256": None,
                "native_library_verification": "unverified",
                "release_tag": supply_chain_info.get("release_tag"),
            },
        }
        (fixture_dir / "ledger.json").write_text(
            json.dumps(ledger_content, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return {
            "status": status,
            "canonical_sha256": can_sha,
            "fixture_name": fixture_name,
        }

    # Execute shadow page
    assert raw_page is not None
    assert fitz_page is not None

    shadow_result = run_shadow_page(
        pdfium_raw_page=raw_page,
        pymupdf_page=fitz_page,
        page_index=page_index,
        table_regions=table_regions,
        output_dir=fixture_dir,
    )

    pdfium_tables = shadow_result.get("tables", {}).get("pdfium", [])
    pymupdf_tables = shadow_result.get("tables", {}).get("pymupdf", [])

    overlays: Dict[str, str] = {}
    if table_regions:
        overlays = render_table_overlays(
            pdf_path=pdf_path,
            page_index=page_index,
            pdfium_tables=pdfium_tables,
            pymupdf_tables=pymupdf_tables,
            output_dir=fixture_dir,
        )

    if doc is not None:
        doc.close()

    # Determine final status
    p_type = shadow_result.get("pdfium_page_type", "unknown")
    m_type = shadow_result.get("pymupdf_page_type", "unknown")
    diff = shadow_result.get("diff", {})

    if p_type == "unclassified" or m_type == "unclassified":
        status = "unclassified"
    elif p_type == "scanned" and m_type == "scanned":
        status = "scanned"
    elif shadow_result.get("status") == "unsupported":
        status = "unsupported"
    elif diff.get("unclassified"):
        status = "unclassified"
    elif diff.get("passed", False):
        status = "passed"
    else:
        status = "failed"

    # Read back layout and table signatures written by run_shadow_page
    layout_sig: Dict[str, Any] = {"pdfium": [], "pymupdf": []}
    table_sig: Dict[str, Any] = {"pdfium": [], "pymupdf": []}
    diagnostics: Dict[str, Any] = {}

    layout_file = fixture_dir / "layout_signature.json"
    if layout_file.is_file():
        try:
            layout_sig = json.loads(layout_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    table_file = fixture_dir / "table_signature.json"
    if table_file.is_file():
        try:
            table_sig = json.loads(table_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    diag_file = fixture_dir / "diagnostics.json"
    if diag_file.is_file():
        try:
            diagnostics = json.loads(diag_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if overlays:
        diagnostics["overlays"] = overlays
        diag_file.write_text(
            json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Compute canonical result SHA-256
    canonical_data = {
        "diff": diff,
        "fixture_name": fixture_name,
        "layout_signature": layout_sig,
        "page_index": page_index,
        "pdfium_markdown": shadow_result.get("pdfium_markdown", ""),
        "pdfium_page_type": p_type,
        "pymupdf_markdown": shadow_result.get("pymupdf_markdown", ""),
        "pymupdf_page_type": m_type,
        "status": status,
        "table_signature": table_sig,
    }
    can_sha = canonical_sha256(canonical_data)

    # Write result.json
    result_content = {
        "canonical_sha256": can_sha,
        "diff": diff,
        "fixture_name": fixture_name,
        "layout_signature": layout_sig,
        "overlays": overlays,
        "page_index": page_index,
        "pdfium_markdown": shadow_result.get("pdfium_markdown", ""),
        "pdfium_page_type": p_type,
        "pymupdf_markdown": shadow_result.get("pymupdf_markdown", ""),
        "pymupdf_page_type": m_type,
        "status": status,
        "table_signature": table_sig,
    }
    (fixture_dir / "result.json").write_text(
        json.dumps(result_content, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Supply chain verification
    expected_lib_sha = supply_chain_info.get("expected_library_sha256")
    raw_native_sha = raw_data.get("native_library_sha256") if raw_data else None
    raw_native_expected = (
        raw_data.get("native_library_expected_sha256") if raw_data else None
    )

    if raw_native_sha and raw_native_expected and raw_native_sha == raw_native_expected:
        native_lib_verif = "verified"
    elif raw_native_sha or raw_native_expected:
        native_lib_verif = "mismatch"
    else:
        native_lib_verif = "unavailable"

    if expected_lib_sha is None:
        manifest_lib_verif = "unavailable"
    elif raw_native_sha and raw_native_sha.lower() == expected_lib_sha.lower():
        manifest_lib_verif = "verified"
    else:
        manifest_lib_verif = "mismatch"

    # Write ledger.json
    ledger_content = {
        "canonical_sha256": can_sha,
        "classification_evidence": diagnostics.get("page_classification", {}),
        "digests": diagnostics.get("digests", {}),
        "fixture_name": fixture_name,
        "input_pdf_sha256": live_pdf_sha,
        "metadata": {
            "elapsed_ms": round((time.time() - start_time) * 1000, 2),
            "fixture_dir": str(fixture_dir),
            "pdf_path": str(pdf_path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "pdfium_raw_sha256": raw_json_sha,
        "pymupdf_baseline_sha256": baseline_json_sha,
        "runtime_versions": {
            "mupdf_version": getattr(fitz, "VersionFitz", "unknown"),
            "pymupdf_version": fitz.__version__,
        },
        "supply_chain": {
            "archive_sha256": supply_chain_info.get("archive_sha256"),
            "library_relpath": supply_chain_info.get("library_relpath"),
            "manifest_library_sha256": expected_lib_sha,
            "manifest_library_verification": manifest_lib_verif,
            "native_library_expected_sha256": raw_native_expected,
            "native_library_sha256": raw_native_sha,
            "native_library_verification": native_lib_verif,
            "release_tag": supply_chain_info.get("release_tag"),
        },
    }
    (fixture_dir / "ledger.json").write_text(
        json.dumps(ledger_content, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "status": status,
        "canonical_sha256": can_sha,
        "fixture_name": fixture_name,
    }


def run_behavioral_matrix(
    *,
    fixture_manifest: Path,
    pdfium_roots: Sequence[Path],
    output_dir: Path,
) -> Dict[str, Any]:
    """Execute behavioral shadow matrix over multiple pdfium roots."""
    manifest_p = Path(fixture_manifest)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not manifest_p.is_file():
        raise FileNotFoundError(f"Fixture manifest not found: {manifest_p}")

    manifest_raw = json.loads(manifest_p.read_text(encoding="utf-8"))
    if isinstance(manifest_raw, list):
        fixtures = manifest_raw
    elif isinstance(manifest_raw, Mapping):
        fixtures = manifest_raw.get("fixtures", [])
    else:
        raise ValueError(f"Invalid manifest format: {manifest_p}")

    probe_root = get_probe_root()
    manifest_json_path = probe_root / "manifest.json"
    supply_chain_info = _load_manifest_supply_chain(manifest_json_path)

    runs_summary: Dict[str, Dict[str, Any]] = {}
    per_fixture_hashes: Dict[str, List[str]] = {}

    for fix in fixtures:
        per_fixture_hashes[str(fix.get("name", "unnamed"))] = []

    for run_idx, root_path in enumerate(pdfium_roots, start=1):
        run_name = f"run-{run_idx:02d}"
        run_dir = out_dir / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        run_results: Dict[str, Any] = {}

        for fix in fixtures:
            fix_name = str(fix.get("name", "unnamed"))
            fix_dir = run_dir / fix_name
            exec_res = _execute_fixture(
                fixture=fix,
                pdfium_root=Path(root_path),
                fixture_dir=fix_dir,
                supply_chain_info=supply_chain_info,
            )
            run_results[fix_name] = exec_res
            per_fixture_hashes[fix_name].append(exec_res["canonical_sha256"])

        runs_summary[run_name] = run_results

    # Check determinism across runs
    per_fixture_det: Dict[str, Any] = {}
    all_equal = True
    for fix_name, hashes in per_fixture_hashes.items():
        eq = len(set(hashes)) <= 1
        if not eq:
            all_equal = False
        per_fixture_det[fix_name] = {
            "all_equal": eq,
            "hashes": hashes,
        }

    # Status counts from the first run (canonical baseline)
    first_run_key = f"run-01"
    first_run = runs_summary.get(first_run_key, {})
    counts = {
        "passed": 0,
        "failed": 0,
        "scanned": 0,
        "unsupported": 0,
        "blocked_input": 0,
        "unclassified": 0,
    }
    for item in first_run.values():
        st = item.get("status", "failed")
        if st in counts:
            counts[st] += 1
        else:
            counts["failed"] += 1

    summary: Dict[str, Any] = {
        "fixture_count": len(fixtures),
        "run_count": len(pdfium_roots),
        "deterministic": {
            "all_equal": all_equal,
            "per_fixture": per_fixture_det,
        },
        "counts": counts,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "scanned": counts["scanned"],
        "unsupported": counts["unsupported"],
        "blocked_input": counts["blocked_input"],
        "unclassified": counts["unclassified"],
        "runs": runs_summary,
    }

    summary_file = out_dir / "summary.json"
    summary_file.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run PDFium shadow behavioral matrix against PyMuPDF baselines."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to behavioral fixture manifest JSON.",
    )
    parser.add_argument(
        "--pdfium-root",
        type=Path,
        action="append",
        required=True,
        help="Path to PDFium output root directory (can be specified multiple times).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for behavioral matrix results.",
    )

    args = parser.parse_args()

    summary = run_behavioral_matrix(
        fixture_manifest=args.manifest,
        pdfium_roots=args.pdfium_root,
        output_dir=args.output,
    )

    print("\n" + "=" * 70)
    print("           PDFium Shadow Behavioral Matrix Summary")
    print("=" * 70)
    print(f"Fixtures:      {summary['fixture_count']}")
    print(f"Runs:          {summary['run_count']}")
    print(f"Deterministic: {summary['deterministic']['all_equal']}")
    print("-" * 70)
    print(f"Passed:        {summary['passed']}")
    print(f"Failed:        {summary['failed']}")
    print(f"Scanned:       {summary['scanned']}")
    print(f"Unsupported:   {summary['unsupported']}")
    print(f"Blocked Input: {summary['blocked_input']}")
    print(f"Unclassified:  {summary['unclassified']}")
    print("=" * 70)
    print(f"Summary saved to: {args.output / 'summary.json'}\n")

    if (
        summary["blocked_input"] > 0
        or summary["failed"] > 0
        or summary["unclassified"] > 0
        or not summary["deterministic"]["all_equal"]
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
