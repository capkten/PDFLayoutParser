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
    summarize_migration_timings,
    write_benchmark_run,
)
from hexai_pdf_parser.debug.benchmark_utils import summarize_timings_with_percentiles
from hexai_pdf_parser.benchmark_utils import summarize_timings as public_summarize_timings
from scripts import benchmark_rust_migration
from scripts import compare_rust_migration
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
    summary = summarize_migration_timings([1.0, 2.0, 3.0, 4.0])

    assert summary["p50"] == 2.5
    assert summary["p95"] == 3.85
    assert summary["p99"] == 3.97


def test_parse_worker_output_accepts_one_json_record_after_diagnostics():
    output = "fitz warning: deprecated API\n{\"pid\": 123, \"samples\": []}\n"

    result = benchmark_rust_migration._parse_worker_output(output, "")

    assert result == {"pid": 123, "samples": []}


def test_parse_worker_output_rejects_multiple_json_records():
    output = '{"pid": 1}\n{"pid": 2}\n'

    with pytest.raises(ValueError, match="exactly one JSON worker record"):
        benchmark_rust_migration._parse_worker_output(output, "")


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
            {"text": "", "row_index": 1, "col_index": 0,
             "bbox": [0.0, 10.0, 5.0, 20.0], "rowspan": 2, "colspan": 1},
            {"text": "first", "row_index": 0, "col_index": 1,
             "bbox": [5.0, 1.0, 10.0, 10.0], "rowspan": 1, "colspan": 1},
        ],
    }]


def test_compare_canonical_tables_reports_field_level_text_difference():
    python_tables = [{"cells": [{"text": "python", "row_index": 0, "col_index": 0}]}]
    rust_tables = [{"cells": [{"text": "rust", "row_index": 0, "col_index": 0}]}]

    result = compare_canonical_tables(python_tables, rust_tables)

    assert result["equal"] is False
    assert result["differences"] == [{
        "path": "tables[0].cells[0].text",
        "field": "text",
        "python_value": "python",
        "rust_value": "rust",
        "difference_kind": "text",
        "classification": "defect",
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


def test_canonicalize_tables_preserves_table_and_cell_input_order():
    tables = [
        {
            "source": "first",
            "cells": [
                {"text": "b", "row_index": 0, "col_index": 1},
                {"text": "a", "row_index": 0, "col_index": 0},
            ],
        },
        {"source": "second", "cells": []},
    ]

    canonical = canonicalize_tables(tables)

    assert [table["source"] for table in canonical] == ["first", "second"]
    assert [cell["text"] for cell in canonical[0]["cells"]] == ["b", "a"]


@pytest.mark.parametrize(
    ("python_value", "rust_value", "difference_kind", "field"),
    [
        ({"text": "x"}, {}, "missing_key", "text"),
        ({}, {"text": "x"}, "extra_key", "text"),
        ({"cells": [1]}, {"cells": []}, "list_length", "cells"),
        ({"text": "python"}, {"text": "rust"}, "text", "text"),
        ({"bbox": [0.0, 0.0, 1.0, 1.0]}, {"bbox": [0.0, 0.0, 2.0, 1.0]}, "bbox", "bbox"),
        ({"rowspan": 1}, {"rowspan": 2}, "span", "rowspan"),
        ({"source": "python"}, {"source": "rust"}, "value", "source"),
    ],
)
def test_compare_tables_reports_explicit_difference_kind_and_defect(
    python_value, rust_value, difference_kind, field
):
    differences = compare_canonical_tables([python_value], [rust_value])["differences"]

    matching = [item for item in differences if item["difference_kind"] == difference_kind]
    assert matching
    assert matching[0]["field"] == field
    assert matching[0]["classification"] == "defect"
    assert "python_value" in matching[0]
    assert "rust_value" in matching[0]


def test_compare_tables_reports_order_without_sorting_inputs():
    python_tables = [{"source": "a"}, {"source": "b"}]
    rust_tables = [{"source": "b"}, {"source": "a"}]

    result = compare_canonical_tables(python_tables, rust_tables)

    assert result["equal"] is False
    assert any(item["difference_kind"] == "order" for item in result["differences"])


def test_canonicalize_tables_preserves_empty_slots_and_floats():
    canonical = canonicalize_tables(
        [{
            "bbox": {"x0": 0, "y0": 1, "x1": 2, "y1": 3},
            "empty_slots": [{"row": 0, "col": 1}],
            "cells": [{
                "text": "value", "row_index": 0, "col_index": 0,
                "bbox": {"x0": 0, "y0": 1, "x1": 1, "y1": 3},
                "rowspan": 1, "colspan": 1,
            }],
        }]
    )

    assert canonical[0]["bbox"] == [0.0, 1.0, 2.0, 3.0]
    assert canonical[0]["cells"][0]["bbox"] == [0.0, 1.0, 1.0, 3.0]
    assert canonical[0]["empty_slots"] == [{"row": 0, "col": 1}]


def test_run_suite_emits_stage_percentiles_rss_manifest_and_fresh_workers(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"pages": [{"tables": []}]}), encoding="utf-8")

    result = run_suite(
        "python", "fixture", str(fixture), [], 0, 3, str(tmp_path / "out"),
        source_root=str(Path(__file__).parents[1]), baseline_id="test-baseline",
    )

    assert result["commit"]
    assert result["baseline_id"] == "test-baseline"
    assert set(result["segment_samples"]) == {
        "extract", "dto", "ffi", "algorithm", "adapt", "total",
    }
    assert all(len(samples) == 3 for samples in result["segment_samples"].values())
    assert all(
        set(result["segments"][stage]) == {"count", "p50", "p95", "p99"}
        for stage in result["segments"]
    )
    assert len(result["memory"]["peak_rss_samples_bytes"]) == 3
    assert len(set(result["diagnostics"]["worker_pids"])) == 3
    assert result["output_manifest"]["pages"] == 1
    assert (tmp_path / "out" / "fixture-python.json").exists()


def test_run_suite_rejects_measurement_path_overwrite(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"pages": [{"tables": []}]}), encoding="utf-8")
    output_dir = tmp_path / "out"

    run_suite("python", "fixture", str(fixture), [], 0, 1, str(output_dir))

    with pytest.raises(FileExistsError):
        run_suite("python", "fixture", str(fixture), [], 0, 1, str(output_dir))


def test_run_suite_rejects_both_mode():
    with pytest.raises(ValueError, match="unknown mode"):
        run_suite("both", "fixture", "tests/fixtures/page_000_vector.pdf", [0], 0, 1, "out")


def test_runner_parser_requires_exactly_one_pdf_or_fixture():
    parser = benchmark_rust_migration.build_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--suite", "fixture", "--pages", "0", "--output-dir", "out"])
    with pytest.raises(SystemExit):
        parser.parse_args([
            "--suite", "fixture", "--pdf", "a.pdf", "--fixture", "b.json",
            "--output-dir", "out",
        ])


def test_runner_pages_all_expands_pdf_and_preserves_explicit_order(monkeypatch):
    monkeypatch.setattr(benchmark_rust_migration, "_input_page_count", lambda _: 4)

    assert benchmark_rust_migration._parse_pages("all", "document.pdf") == [0, 1, 2, 3]
    assert benchmark_rust_migration._parse_pages("3,1,3", "document.pdf") == [3, 1, 3]


def test_compare_runs_and_manifests_preserve_structure_and_timing_inputs(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    baseline = write("baseline.json", {"segments": {"algorithm": {"p95": 4}, "total": {"p95": 8}}})
    python = write("python.json", {"tables": [{"cells": [{"text": "a"}]}], "output_manifest": {"pages": 1}})
    rust = write("rust.json", {"tables": [{"cells": [{"text": "b"}]}], "output_manifest": {"pages": 1}})
    shadow = write("shadow.json", {"tables": [{"cells": [{"text": "a"}]}], "output_manifest": {"pages": 1}})

    result = compare_rust_migration.compare_runs(baseline, python, rust, shadow)

    assert result["differences"][0]["difference_kind"] == "text"
    assert result["speedup"]["algorithm_p95"] == 4 / 0 if False else result["speedup"]["algorithm_p95"] is None

    python_manifest = write("python-manifest.json", {"pages": [{"page_index": 0, "tables": 1}]})
    rust_manifest = write("rust-manifest.json", {"pages": [{"page_index": 0, "tables": 2}]})
    manifest_result = compare_rust_migration.compare_manifests(python_manifest, rust_manifest)
    assert manifest_result["equal"] is False
    assert manifest_result["differences"][0]["field"] == "tables"


def test_runner_parser_defaults_python_and_accepts_fixture_without_pages():
    parser = benchmark_rust_migration.build_argument_parser()

    args = parser.parse_args(["--suite", "fixture", "--fixture", "input.json", "--output-dir", "out"])

    assert args.mode == "python"
    assert args.pages is None
    assert args.fixture == "input.json"


def test_run_suite_records_source_root_provenance_and_stage_contract(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"pages": [{"tables": []}]}), encoding="utf-8")

    result = run_suite(
        "python", "fixture", str(fixture), [], 0, 1, str(tmp_path / "out"),
        source_root=str(Path(__file__).parents[1]), baseline_id="feature-dev-test",
    )

    assert result["source_provenance"]["source_root"] == str(Path(__file__).parents[1].resolve())
    assert result["baseline_id"] == "feature-dev-test"
    assert result["memory"]["peak_rss_samples_bytes"][0] > 0
    assert result["environment"]["cold_start"] is True
    assert result["segments"]["algorithm"]["count"] == 1
