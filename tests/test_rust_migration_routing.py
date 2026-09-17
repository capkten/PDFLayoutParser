# -*- coding: utf-8 -*-
"""Sprint 011: Test suite for differential routing, fallbacks, and feature gates."""

from __future__ import annotations

import os
import pytest
from hexai_pdf_parser import rust_adapter


def setup_function():
    rust_adapter.clear_diagnostics()
    for key in list(os.environ.keys()):
        if key.startswith("PDF_RUST_MODE"):
            del os.environ[key]


def test_default_mode_is_python():
    """Default mode must be 'python' when no environment variable is set."""
    assert rust_adapter.get_rust_mode() == "python"


def test_valid_modes():
    """Modes 'python', 'shadow', 'rust' must be parsed case-insensitively."""
    for mode in ["python", "shadow", "rust", "PYTHON", "Shadow", "RUST"]:
        os.environ["PDF_RUST_MODE"] = mode
        assert rust_adapter.get_rust_mode() == mode.lower()


def test_invalid_mode_raises():
    """Invalid modes like 'both', 'fast' must raise ValueError."""
    for bad in ["both", "fast", "unknown", "123"]:
        os.environ["PDF_RUST_MODE"] = bad
        with pytest.raises(ValueError, match="Invalid PDF_RUST_MODE"):
            rust_adapter.get_rust_mode()


def test_path_specific_feature_gate():
    """Specific paths can be overridden via PDF_RUST_MODE_<PATH>."""
    os.environ["PDF_RUST_MODE"] = "python"
    os.environ["PDF_RUST_MODE_WIRED"] = "rust"
    os.environ["PDF_RUST_MODE_ENGLISH_WIRELESS"] = "shadow"

    assert rust_adapter.get_rust_mode() == "python"
    assert rust_adapter.get_rust_mode("wired") == "rust"
    assert rust_adapter.get_rust_mode("english-wireless") == "shadow"
    assert rust_adapter.get_rust_mode("chinese-wireless") == "python"


def test_run_python_or_rust_python_mode():
    """In python mode, only python_fn is called."""
    rust_called = []
    py_called = []

    res = rust_adapter.run_python_or_rust(
        mode="python",
        python_fn=lambda: (py_called.append(True), "py_val")[1],
        rust_fn=lambda inp: (rust_called.append(True), "rust_val")[1],
        input_dto={"test": 1},
    )
    assert res == "py_val"
    assert py_called == [True]
    assert rust_called == []
    assert len(rust_adapter.get_diagnostics()) == 0


def test_run_python_or_rust_rust_mode_success():
    """In rust mode on success, rust_fn is called and its result returned."""
    rust_called = []
    py_called = []

    res = rust_adapter.run_python_or_rust(
        mode="rust",
        python_fn=lambda: (py_called.append(True), "py_val")[1],
        rust_fn=lambda inp: (rust_called.append(inp), "rust_val")[1],
        input_dto={"test": 42},
    )
    assert res == "rust_val"
    assert rust_called == [{"test": 42}]
    assert py_called == []
    assert len(rust_adapter.get_diagnostics()) == 0


def test_run_python_or_rust_rust_mode_fallback():
    """In rust mode, if rust_fn raises an exception, fallback to python_fn and record diagnostic."""
    def bad_rust(inp):
        raise RuntimeError("Rust crash simulation")

    res = rust_adapter.run_python_or_rust(
        mode="rust",
        python_fn=lambda: "fallback_py",
        rust_fn=bad_rust,
        input_dto={"test": 1},
        path="test/fallback_path",
    )
    assert res == "fallback_py"
    diags = rust_adapter.get_diagnostics()
    assert len(diags) == 1
    assert diags[0]["status"] == "rust_fallback"
    assert diags[0]["path"] == "test/fallback_path"
    assert diags[0]["error_type"] == "RuntimeError"


def test_run_python_or_rust_shadow_mode():
    """In shadow mode, always return python_val, and record mismatch diagnostic if outputs differ."""
    # 1. Matching case
    res1 = rust_adapter.run_python_or_rust(
        mode="shadow",
        python_fn=lambda: "match",
        rust_fn=lambda inp: "match",
        input_dto={"test": 1},
    )
    assert res1 == "match"
    assert len(rust_adapter.get_diagnostics()) == 0

    # 2. Mismatch case
    res2 = rust_adapter.run_python_or_rust(
        mode="shadow",
        python_fn=lambda: "py_result",
        rust_fn=lambda inp: "rust_result",
        input_dto={"test": 1},
        path="test/shadow_path",
    )
    assert res2 == "py_result"
    diags = rust_adapter.get_diagnostics()
    assert len(diags) == 1
    assert diags[0]["status"] == "rust_output_mismatch"
    assert diags[0]["path"] == "test/shadow_path"
    assert diags[0]["classification"] == "defect"


def test_assert_equivalent():
    """assert_equivalent verifies equality and raises AssertionError on mismatch."""
    rust_adapter.assert_equivalent("path/ok", 123, 123)

    with pytest.raises(AssertionError, match="Output mismatch on path 'path/diff'"):
        rust_adapter.assert_equivalent("path/diff", "a", "b")

    diags = rust_adapter.get_diagnostics()
    assert len(diags) == 1
    assert diags[0]["status"] == "rust_output_mismatch"
