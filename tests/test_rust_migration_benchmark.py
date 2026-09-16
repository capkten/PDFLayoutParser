import json
import os
import subprocess
from pathlib import Path

import pytest

from hexai_pdf_parser import BBox, Cell, Table
import hexai_pdf_parser.debug.rust_migration_benchmark as migration_benchmark
from hexai_pdf_parser.debug.rust_migration_benchmark import (
    canonicalize_tables,
    compare_canonical_tables,
    summarize_timings_with_percentiles,
    write_benchmark_run,
)
from hexai_pdf_parser.debug.benchmark_utils import summarize_timings_with_percentiles
from hexai_pdf_parser.benchmark_utils import summarize_timings as public_summarize_timings
from scripts import benchmark_rust_migration
from scripts.benchmark_rust_migration import run_suite


@pytest.mark.parametrize(
    ("values", "count", "total", "mean", "minimum", "maximum"),
    [([], 0, 0.0, 0.0, 0.0, 0.0), ([2.5], 1, 2.5, 2.5, 2.5, 2.5),
     ([1.0, 3.0], 2, 4.0, 2.0, 1.0, 3.0), ([4.0, 1.0, 3.0], 3, 8.0, 8 / 3, 1.0, 4.0)],
)
def test_summarize_timings_handles_empty_singleton_even_and_odd(
    values, count, total, mean, minimum, maximum
):
    summary = summarize_timings_with_percentiles(values)

    assert summary["count"] == count
    assert summary["total"] == total
    assert summary["mean"] == mean
    assert summary["min"] == minimum
    assert summary["max"] == maximum


def test_benchmark_summary_includes_percentiles():
    summary = summarize_timings_with_percentiles([1.0, 2.0, 3.0, 4.0])

    assert summary["p50"] == 2.5
    assert summary["p95"] == 3.85
    assert summary["p99"] == 3.97


def test_public_debug_summarize_timings_remains_legacy_five_key_api():
    summary = public_summarize_timings([1.0, 2.0, 3.0, 4.0])

    assert summary == {
        "count": 4,
        "total": 10.0,
        "mean": 2.5,
        "min": 1.0,
        "max": 4.0,
    }


def test_migration_module_does_not_expose_legacy_summary_alias():
    assert not hasattr(migration_benchmark, "summarize_timings")


def test_migration_summary_is_percentile_aware():
    summary = summarize_timings_with_percentiles([1.0, 2.0, 3.0, 4.0])

    assert summary["p50"] == 2.5
    assert summary["p95"] == 3.85
    assert summary["p99"] == 3.97


def test_run_suite_calls_explicit_percentile_api(monkeypatch, tmp_path):
    calls = []

    def summarize(values):
        calls.append(list(values))
        return {"count": len(values), "p50": 0.0, "p95": 0.0, "p99": 0.0}

    monkeypatch.setattr(
        benchmark_rust_migration,
        "summarize_timings_with_percentiles",
        summarize,
    )
    monkeypatch.setattr(benchmark_rust_migration, "_extract_python", lambda *_: [])

    run_suite("python", "fixture", "tests/fixtures/page_000_vector.pdf", [0], 0, 1, str(tmp_path))

    assert calls and len(calls[0]) == 1


def test_run_suite_commit_is_resolved_from_script_repository(monkeypatch, tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "page_000_vector.pdf"
    expected_commit = subprocess.check_output(
        ["git", "-C", str(Path(__file__).parents[1]), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    monkeypatch.setattr(benchmark_rust_migration, "_extract_python", lambda *_: [])

    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = run_suite("python", "fixture", str(fixture), [0], 0, 1, str(tmp_path / "out"))
    finally:
        os.chdir(original_cwd)

    assert result["commit"] == expected_commit


def test_canonicalize_tables_preserves_metadata_and_stable_cell_order():
    table = Table(
        bbox=BBox(0, 1, 10, 20), rows=2, cols=2, source="python",
        confidence=0.875,
        cells=[
            Cell("", 1, 0, BBox(0, 10, 5, 20), rowspan=2, colspan=1),
            Cell("first", 0, 1, BBox(5, 1, 10, 10), rowspan=1, colspan=1),
        ],
    )

    canonical = canonicalize_tables([table])

    assert canonical == [{
        "bbox": [0.0, 1.0, 10.0, 20.0],
        "cols": 2,
        "confidence": 0.875,
        "rows": 2,
        "source": "python",
        "cells": [
            {"text": "first", "row_index": 0, "col_index": 1,
             "bbox": [5.0, 1.0, 10.0, 10.0], "rowspan": 1, "colspan": 1},
            {"text": "", "row_index": 1, "col_index": 0,
             "bbox": [0.0, 10.0, 5.0, 20.0], "rowspan": 2, "colspan": 1},
        ],
    }]


def test_compare_canonical_tables_reports_field_level_text_difference():
    python_tables = [{"cells": [{"text": "python", "row_index": 0, "col_index": 0}]}]
    rust_tables = [{"cells": [{"text": "rust", "row_index": 0, "col_index": 0}]}]

    result = compare_canonical_tables(python_tables, rust_tables)

    assert result["equal"] is False
    assert result["differences"] == [{
        "path": "tables[0].cells[0].text",
        "python_value": "python",
        "rust_value": "rust",
        "classification": "text_mismatch",
    }]


def test_unknown_mode_is_rejected_and_default_is_python(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="unknown mode"):
        run_suite("invalid", "fixture", "tests/fixtures/page_000_vector.pdf", [0], 0, 1, str(tmp_path))

    monkeypatch.delenv("PDF_RUST_MODE", raising=False)
    result = run_suite("", "fixture", "tests/fixtures/page_000_vector.pdf", [0], 0, 1, str(tmp_path))
    assert result["mode"] == "python"


def test_write_benchmark_run_is_sorted_json_and_serializable(tmp_path):
    path = tmp_path / "run.json"
    write_benchmark_run(path, {"z": 1, "a": ["ok"], "nested": {"b": 2, "a": 1}})

    raw = path.read_text(encoding="utf-8")
    assert raw == '{\n  "a": [\n    "ok"\n  ],\n  "nested": {\n    "a": 1,\n    "b": 2\n  },\n  "z": 1\n}\n'
    assert json.loads(raw) == {"z": 1, "a": ["ok"], "nested": {"b": 2, "a": 1}}
