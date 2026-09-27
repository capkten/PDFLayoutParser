"""Compare benchmark runs and page manifests across Python, Rust, and Shadow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hexai_pdf_parser.debug.rust_migration_benchmark import compare_canonical_tables


def _read_json(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def compare_runs(
    baseline_run: str,
    migration_python_run: str,
    rust_run: str,
    shadow_run: Optional[str] = None,
) -> Dict[str, Any]:
    baseline_payload = _read_json(baseline_run)
    python_payload = _read_json(migration_python_run)
    rust_payload = _read_json(rust_run)
    shadow_payload = _read_json(shadow_run) if shadow_run else None

    table_comparison = compare_canonical_tables(
        python_payload.get("tables", []), rust_payload.get("tables", [])
    )

    baseline_segments = baseline_payload.get("segments", {})
    rust_segments = rust_payload.get("segments", {})

    b_alg = baseline_segments.get("algorithm", {}).get("p95")
    r_alg = rust_segments.get("algorithm", {}).get("p95")
    alg_speedup = (b_alg / r_alg) if (b_alg is not None and r_alg is not None and r_alg > 0) else None

    b_tot = baseline_segments.get("total", {}).get("p95")
    r_tot = rust_segments.get("total", {}).get("p95")
    tot_speedup = (b_tot / r_tot) if (b_tot is not None and r_tot is not None and r_tot > 0) else None

    result = {
        "equal": table_comparison.get("equal", True),
        "differences": table_comparison.get("differences", []),
        "speedup": {
            "algorithm_p95": alg_speedup,
            "total_p95": tot_speedup,
        },
        "baseline": baseline_payload,
        "python": python_payload,
        "rust": rust_payload,
    }
    if shadow_payload is not None:
        result["shadow"] = shadow_payload
    return result


def compare_manifests(
    migration_python_manifest: str,
    rust_manifest: str,
    shadow_manifest: Optional[str] = None,
) -> Dict[str, Any]:
    py_man = _read_json(migration_python_manifest)
    rust_man = _read_json(rust_manifest)
    shadow_man = _read_json(shadow_manifest) if shadow_manifest else None

    differences: List[Dict[str, Any]] = []

    py_pages = py_man.get("pages", [])
    rust_pages = rust_man.get("pages", [])

    if len(py_pages) != len(rust_pages):
        differences.append({
            "path": "pages",
            "field": "pages",
            "difference_kind": "list_length",
            "python_value": len(py_pages),
            "rust_value": len(rust_pages),
            "classification": "defect",
        })
    else:
        for idx, (p_page, r_page) in enumerate(zip(py_pages, rust_pages)):
            if isinstance(p_page, Mapping) and isinstance(r_page, Mapping):
                for key in sorted(set(p_page) | set(r_page)):
                    if p_page.get(key) != r_page.get(key):
                        differences.append({
                            "path": f"pages[{idx}].{key}",
                            "field": str(key),
                            "difference_kind": "value",
                            "python_value": p_page.get(key),
                            "rust_value": r_page.get(key),
                            "classification": "defect",
                        })

    return {
        "equal": len(differences) == 0,
        "differences": differences,
        "python_manifest": py_man,
        "rust_manifest": rust_man,
        "shadow_manifest": shadow_man,
    }


def main():
    parser = argparse.ArgumentParser(description="Compare Rust migration benchmark runs or manifests.")
    parser.add_argument("--baseline", help="Path to feature-dev baseline JSON")
    parser.add_argument("--python", help="Path to migration Python JSON")
    parser.add_argument("--rust", help="Path to migration Rust JSON")
    parser.add_argument("--shadow", help="Optional path to migration Shadow JSON")
    parser.add_argument("--manifests", nargs="+", help="Paths to manifests: <python> <rust> [<shadow>]")
    parser.add_argument("--report", help="Output markdown report path")

    args = parser.parse_args()

    if args.manifests:
        if len(args.manifests) < 2:
            parser.error("--manifests requires at least two manifest paths: python rust [shadow]")
        py_path = args.manifests[0]
        rust_path = args.manifests[1]
        shadow_path = args.manifests[2] if len(args.manifests) > 2 else None
        result = compare_manifests(py_path, rust_path, shadow_path)
    elif args.baseline and args.python and args.rust:
        result = compare_runs(args.baseline, args.python, args.rust, args.shadow)
    else:
        parser.error("Either provide --manifests <py> <rust> or --baseline, --python, --rust")

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_lines = [
            "# Rust Migration Comparison Report",
            "",
            f"- **Equal**: {result.get('equal')}",
            f"- **Differences Count**: {len(result.get('differences', []))}",
        ]
        if "speedup" in result:
            report_lines.extend([
                f"- **Algorithm P95 Speedup**: {result['speedup'].get('algorithm_p95')}",
                f"- **Total P95 Speedup**: {result['speedup'].get('total_p95')}",
            ])
        if result.get("differences"):
            report_lines.append("\n## Differences\n")
            report_lines.append("```json")
            report_lines.append(json.dumps(result["differences"][:20], indent=2, ensure_ascii=False))
            report_lines.append("```")
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        print(f"Report written to: {report_path}")

    print(json.dumps({
        "equal": result.get("equal"),
        "differences_count": len(result.get("differences", [])),
        "speedup": result.get("speedup"),
    }))


if __name__ == "__main__":
    main()
