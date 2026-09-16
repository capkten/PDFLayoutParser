"""Compare two benchmark run JSON files."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hexai_pdf_parser.debug.rust_migration_benchmark import compare_canonical_tables


def compare_runs(python_run: str, rust_run: str):
    with Path(python_run).open(encoding="utf-8") as stream:
        python_payload = json.load(stream)
    with Path(rust_run).open(encoding="utf-8") as stream:
        rust_payload = json.load(stream)
    return compare_canonical_tables(
        python_payload.get("tables", []), rust_payload.get("tables", [])
    )
