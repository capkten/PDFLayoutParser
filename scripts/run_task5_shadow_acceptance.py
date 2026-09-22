"""Run Task 5 Python/shadow/Rust acceptance on representative PDF pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable

import fitz

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.debug.rust_task5_acceptance import (
    compare_normalized,
    normalize_recovery,
    normalize_region_result,
)
from hexai_pdf_parser.extractors.language_detector import detect_page_language
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region
from hexai_pdf_parser.tables.wireless_table_recovery import (
    WirelessRecovery,
    export_wireless_debug,
    recover_wireless_tables,
)


MODES = ("python", "shadow", "rust")


def clear_mode_overrides(mode: str) -> None:
    """Ensure both wireless entrances use exactly one requested global mode."""

    for key in list(os.environ):
        if key.startswith("PDF_RUST_MODE_"):
            os.environ.pop(key, None)
    os.environ["PDF_RUST_MODE"] = mode
    rust_adapter.clear_diagnostics()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _bbox_from_values(values: Iterable[float]) -> BBox:
    x0, y0, x1, y1 = [float(value) for value in values]
    return BBox(x0, y0, x1, y1)


def _table_regions(recovery: WirelessRecovery) -> list[BBox]:
    return [table.bbox for table in recovery.tables]


def build_page_payload(
    *,
    recovery: WirelessRecovery,
    page_index: int,
    mode: str,
    pdf_path: str,
    input_sha256: str,
    language: str,
    artifacts: dict[str, str],
    region_results: list[dict[str, Any]],
    routing_diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the stable per-page manifest payload used by tests and CLI."""

    payload = normalize_recovery(recovery, page_index=page_index, mode=mode)
    payload.update(
        {
            "pdf_path": pdf_path,
            "input_sha256": input_sha256,
            "language": language,
            "artifacts": artifacts,
            "regions": region_results,
            "routing_diagnostics": routing_diagnostics,
        }
    )
    return payload


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _run_mode(
    *,
    page: fitz.Page,
    page_index: int,
    mode: str,
    pdf_path: Path,
    input_sha256: str,
    language: str,
    regions: list[BBox],
    mode_dir: Path,
    dpi: int,
) -> dict[str, Any]:
    clear_mode_overrides(mode)
    recovery = recover_wireless_tables(page)
    page_diagnostics = rust_adapter.get_diagnostics()

    debug_paths = export_wireless_debug(page, recovery, str(mode_dir), dpi=dpi)
    page_json_path = mode_dir / f"page-{page_index}.json"
    image_path = Path(debug_paths["image"]).resolve()

    region_results: list[dict[str, Any]] = []
    region_diagnostics: list[dict[str, Any]] = []
    for region in regions:
        rust_adapter.clear_diagnostics()
        result = recover_cells_from_region(page, region)
        region_results.append(
            normalize_region_result(
                result,
                region,
                page_index=page_index,
                mode=mode,
            )
        )
        region_diagnostics.extend(rust_adapter.get_diagnostics())

    payload = build_page_payload(
        recovery=recovery,
        page_index=page_index,
        mode=mode,
        pdf_path=str(pdf_path),
        input_sha256=input_sha256,
        language=language,
        artifacts={
            "json": str(page_json_path.resolve()),
            "png": str(image_path),
            "debug_json": str(Path(debug_paths["json"]).resolve()),
            "html": str(Path(debug_paths["html"]).resolve()),
        },
        region_results=region_results,
        routing_diagnostics=page_diagnostics + region_diagnostics,
    )
    _write_json(page_json_path, payload)
    return payload


def _comparison_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in ("page_index", "language", "table_count", "tables", "regions")
        if key in payload
    }


def _diagnostic_summary(diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Keep routing evidence useful without embedding large repr snapshots."""

    keys = (
        "schema_version",
        "status",
        "path",
        "field",
        "classification",
        "error_type",
        "message",
    )
    return {key: diagnostic[key] for key in keys if key in diagnostic}


def _compare_page_modes(
    python_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    mode: str,
) -> list[dict[str, Any]]:
    mismatches = compare_normalized(
        _comparison_payload(python_payload),
        _comparison_payload(candidate_payload),
        entry=f"{mode}:page-{python_payload['page_index']}",
    )
    for mismatch in mismatches:
        mismatch["classification"] = "defect"
    routing = candidate_payload.get("routing_diagnostics", [])
    for diagnostic in routing:
        mismatches.append(
            {
                "entry": f"{mode}:page-{python_payload['page_index']}",
                "layer": "routing_diagnostics",
                "field": diagnostic.get("status", "unknown"),
                "python_value": [],
                "rust_value": _diagnostic_summary(diagnostic),
                "classification": diagnostic.get("classification", "defect"),
            }
        )
    return mismatches


def run_acceptance(pdf_path: Path, pages: list[int], output_dir: Path, dpi: int) -> dict[str, Any]:
    pdf_path = pdf_path.resolve()
    output_dir = output_dir.resolve()
    input_sha256 = _sha256(pdf_path)
    commit = _git_commit()
    output_dir.mkdir(parents=True, exist_ok=True)
    mode_payloads: dict[str, dict[int, dict[str, Any]]] = {mode: {} for mode in MODES}
    mismatches: list[dict[str, Any]] = []

    with fitz.open(str(pdf_path)) as document:
        for page_index in pages:
            if page_index < 0 or page_index >= document.page_count:
                raise ValueError(f"page index {page_index} out of range for {document.page_count} pages")
            page = document.load_page(page_index)
            language = detect_page_language(page)

            clear_mode_overrides("python")
            baseline = recover_wireless_tables(page)
            regions = _table_regions(baseline)

            for mode in MODES:
                payload = _run_mode(
                    page=page,
                    page_index=page_index,
                    mode=mode,
                    pdf_path=pdf_path,
                    input_sha256=input_sha256,
                    language=language,
                    regions=regions,
                    mode_dir=output_dir / mode,
                    dpi=dpi,
                )
                mode_payloads[mode][page_index] = payload

            python_payload = mode_payloads["python"][page_index]
            for mode in ("shadow", "rust"):
                mismatches.extend(
                    _compare_page_modes(
                        python_payload,
                        mode_payloads[mode][page_index],
                        mode,
                    )
                )

    for mode in MODES:
        _write_json(
            output_dir / mode / "manifest.json",
            {
                "schema_version": 1,
                "mode": mode,
                "commit": commit,
                "pdf_path": str(pdf_path),
                "input_sha256": input_sha256,
                "pages": [mode_payloads[mode][page] for page in pages],
            },
        )

    comparison = {
        "schema_version": 1,
        "commit": commit,
        "pdf_path": str(pdf_path),
        "input_sha256": input_sha256,
        "pages": pages,
        "mismatches": mismatches,
        "summary": {
            "mismatch_count": len(mismatches),
            "unclassified_count": len(mismatches),
            "by_classification": {
                classification: sum(
                    1
                    for item in mismatches
                    if item.get("classification") == classification
                )
                for classification in sorted(
                    {item.get("classification", "unclassified") for item in mismatches}
                )
            },
            "by_mode": {
                mode: sum(1 for item in mismatches if item["entry"].startswith(f"{mode}:"))
                for mode in ("shadow", "rust")
            },
        },
    }
    comparison["summary"]["unclassified_count"] = sum(
        1 for item in mismatches if not item.get("classification")
    )
    _write_json(output_dir / "comparison" / "comparison.json", comparison)
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pages", required=True, help="comma-separated 0-based page indices")
    parser.add_argument("--output", required=True)
    parser.add_argument("--dpi", type=int, default=160)
    args = parser.parse_args()
    pages = [int(item.strip()) for item in args.pages.split(",") if item.strip()]
    comparison = run_acceptance(Path(args.pdf), pages, Path(args.output), args.dpi)
    print(json.dumps(comparison["summary"], ensure_ascii=False, sort_keys=True))
    return 2 if comparison["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
