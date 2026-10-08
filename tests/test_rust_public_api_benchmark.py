"""Focused contracts for Rust public API benchmark comparisons."""

import importlib.util
import sys
import types
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "src/hexai_pdf_parser/debug/rust_public_api_benchmark.py"


def load_benchmark(monkeypatch):
    package = types.ModuleType("hexai_pdf_parser")
    package.__path__ = []
    core = types.ModuleType("hexai_pdf_parser.core")
    core.__path__ = []
    parser_module = types.ModuleType("hexai_pdf_parser.core.pdf_parser")
    parser_module.PDFParser = object
    monkeypatch.setitem(sys.modules, "hexai_pdf_parser", package)
    monkeypatch.setitem(sys.modules, "hexai_pdf_parser.core", core)
    monkeypatch.setitem(sys.modules, "hexai_pdf_parser.core.pdf_parser", parser_module)
    spec = importlib.util.spec_from_file_location("rust_public_api_benchmark_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_data_strips_baseline_diagnostics_and_normalizes_paths(monkeypatch):
    benchmark = load_benchmark(monkeypatch)
    value = {
        "path": "C:/baseline/run/page-000.png",
        "file": {"name": "page-000.png", "sha256": "diagnostic"},
        "decoded": True,
        "sha256": "diagnostic",
        "bbox": {"x0": 1, "x1": 2},
        "ext": "png",
    }

    assert benchmark._public_data(value) == {
        "path": "page-000.png",
        "bbox": {"x0": 1, "x1": 2},
        "ext": "png",
    }


def test_result_summaries_expose_text_and_cell_text_differences(monkeypatch):
    benchmark = load_benchmark(monkeypatch)

    baseline = benchmark._baseline_summary({
        "code": 1, "message": "ok", "data": [{"text": "before", "cells": [{"text": "cell-a"}]}]
    })
    current = benchmark._result_summary(types.SimpleNamespace(
        code=1, message="ok", data=[{"text": "after", "cells": [{"text": "cell-b"}]}]
    ))
    differences = {item["field"] for item in benchmark._differences(baseline, current)}

    assert "public_data_sha256" in differences
    assert "first_item_text_sha256" in differences
    assert "first_item_cell_text_sha256" in differences


def test_runtime_skip_requires_a_specific_failed_rust_probe(monkeypatch):
    benchmark = load_benchmark(monkeypatch)

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(
        returncode=1, stdout="", stderr="PanicException: BadVersion { version_str: '1.17.1' }"
    ))
    assert "BadVersion" in benchmark._probe_table_structure(Path("fixture.pdf"))

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(
        returncode=1, stdout="", stderr="AssertionError: expected cell text"
    ))
    try:
        benchmark._probe_table_structure(Path("fixture.pdf"))
    except RuntimeError as error:
        assert "AssertionError" in str(error)
    else:
        raise AssertionError("non-runtime Rust failures must not be reported as skips")

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(
        returncode=1, stdout="", stderr="BadVersion: unrelated failure"
    ))
    try:
        benchmark._probe_table_structure(Path("fixture.pdf"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("a generic version-like message must not be reported as an ORT skip")

    monkeypatch.setattr(benchmark.subprocess, "run", lambda *args, **kwargs: types.SimpleNamespace(
        returncode=0, stdout="", stderr=""
    ))
    assert benchmark._probe_table_structure(Path("fixture.pdf")) is None


def test_run_records_skip_only_for_the_isolated_rust_runtime_probe(monkeypatch, tmp_path):
    benchmark = load_benchmark(monkeypatch)
    monkeypatch.setattr(benchmark, "PDFParser", lambda *_args: object())
    monkeypatch.setattr(benchmark, "_probe_table_structure", lambda _pdf: "BadVersion version_str=1.17.1")
    monkeypatch.setattr(benchmark, "_invoke", lambda *_args: types.SimpleNamespace(
        code=1, message="ok", data=[]
    ))

    payload = benchmark.run(
        benchmark.ROOT / "tests/fixtures/rust_public_api/python_baseline.json",
        5,
        tmp_path / "result.json",
        ["page_000_vector.pdf"],
    )

    table = next(item for item in payload["results"] if item["api"] == "table_structure")
    assert table["status"] == "skipped"
    assert table["reason"] == "isolated Rust API probe reported an ONNX Runtime version mismatch"
    assert table["runtime_probe"] == "BadVersion version_str=1.17.1"
