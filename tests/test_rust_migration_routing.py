# -*- coding: utf-8 -*-
"""Sprint 011: Test suite for differential routing, fallbacks, and feature gates."""

from __future__ import annotations

import os
import copy
import hashlib
import json
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


def test_run_python_or_rust_routes_sentinel_without_changing_shadow_result():
    """Rust mode returns the Rust sentinel while shadow mode keeps Python output."""
    python_result = {"sentinel": False}
    rust_result = {"sentinel": True}

    assert rust_adapter.run_python_or_rust(
        mode="rust",
        python_fn=lambda: python_result,
        rust_fn=lambda: rust_result,
        path="sentinel",
    ) == rust_result

    rust_adapter.clear_diagnostics()
    assert rust_adapter.run_python_or_rust(
        mode="shadow",
        python_fn=lambda: python_result,
        rust_fn=lambda: rust_result,
        path="sentinel",
    ) == python_result

    diagnostics = rust_adapter.get_diagnostics()
    assert len(diagnostics) == 1
    assert diagnostics[0]["status"] == "rust_output_mismatch"
    assert {"schema_version", "status", "path"} <= diagnostics[0].keys()


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


def test_diagnostic_path_is_normalized_and_has_common_fields():
    """Diagnostics use unknown for blank paths and always expose the common fields."""
    rust_adapter.run_python_or_rust(
        mode="shadow",
        python_fn=lambda: "python",
        rust_fn=lambda: "rust",
        path="   ",
    )

    diagnostics = rust_adapter.get_diagnostics()
    assert len(diagnostics) == 1
    assert diagnostics[0]["path"] == "unknown"
    assert {"schema_version", "status", "path"} <= diagnostics[0].keys()


def test_run_python_or_rust_rejects_non_string_mode():
    """Invalid mode values fail through the routing contract with ValueError."""
    with pytest.raises(ValueError, match="Invalid mode"):
        rust_adapter.run_python_or_rust(
            mode=None,
            python_fn=lambda: "python",
            rust_fn=lambda: "rust",
        )


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


def _snapshot_fixture():
    return {
        "schema_version": 1,
        "version": 1,
        "page_index": 4,
        "geometry": {
            "rect": (0.0, 0.0, 120.0, 80.0),
            "x0": 0.0,
            "y0": 0.0,
            "x1": 120.0,
            "y1": 80.0,
            "width": 120.0,
            "height": 80.0,
            "rotation": 90,
        },
        "text_blocks": (
            {
                "bbox": (1.0, 2.0, 30.0, 14.0),
                "raw_source_position": (0,),
                "source_order": 0,
                "lines": (
                    {
                        "bbox": (1.0, 2.0, 30.0, 14.0),
                        "raw_source_position": (0, 0),
                        "source_order": 0,
                        "spans": (
                            {
                                "bbox": (1.0, 2.0, 30.0, 14.0),
                                "raw_source_position": (0, 0, 0),
                                "source_order": 0,
                                "text": "甲",
                                "font": "Noto",
                                "size": 12.0,
                                "flags": 3,
                                "chars": (
                                    {
                                        "c": "甲",
                                        "bbox": (1.0, 2.0, 8.0, 14.0),
                                        "raw_source_position": (0, 0, 0, 0),
                                        "source_order": 0,
                                    },
                                ),
                            },
                        ),
                    },
                ),
            },
        ),
        "spans": (
            {
                "bbox": (1.0, 2.0, 30.0, 14.0),
                "raw_source_position": (0, 0, 0),
                "source_order": 0,
                "text": "甲",
                "font": "Noto",
                "size": 12.0,
                "flags": 3,
                "chars": (
                    {
                        "c": "甲",
                        "bbox": (1.0, 2.0, 8.0, 14.0),
                        "raw_source_position": (0, 0, 0, 0),
                        "source_order": 0,
                    },
                ),
            },
        ),
        "words": (
            {
                "bbox": (1.0, 2.0, 30.0, 14.0),
                "text": "甲",
                "block_index": 0,
                "line_index": 0,
                "word_index": 2,
                "source_order": 7,
            },
        ),
        "drawings": (
            {
                "type": "fs",
                "rect": (0.0, 0.0, 120.0, 20.0),
                "color": (0.0, 0.0, 0.0),
                "fill": (0.8, 0.8, 0.8),
                "opacity": 0.5,
                "fill_opacity": 0.4,
                "width": 1.25,
                "items": (
                    ("l", (0.0, 0.0), (120.0, 0.0)),
                    ("re", (0.0, 0.0, 120.0, 20.0), 1),
                ),
                "seqno": 9,
                "level": 2,
            },
        ),
        "allowed_regions": ({"x0": 0.0, "y0": 0.0, "x1": 60.0, "y1": 40.0},),
        "excluded_regions": ({"x0": 50.0, "y0": 10.0, "x1": 55.0, "y1": 20.0},),
        "extraction_options": {
            "rawdict": {
                "selected": {"status": "ok", "kwargs": {"flags": 2}},
                "variants": {"default": {"status": "ok"}},
            },
            "words": {"selected": {"status": "ok"}},
        },
    }


def _snapshot_object():
    class Snapshot:
        pass

    snapshot = Snapshot()
    for key, value in _snapshot_fixture().items():
        setattr(snapshot, key, value)
    return snapshot


def test_page_snapshot_to_rust_input_normalizes_owned_contract_without_mutation():
    snapshot = _snapshot_object()
    before = copy.deepcopy(snapshot.__dict__)

    dto = rust_adapter.page_snapshot_to_rust_input(snapshot)

    assert snapshot.__dict__ == before
    assert set(dto) == {
        "schema_version",
        "page_index",
        "page",
        "text_blocks",
        "spans",
        "words",
        "drawings",
        "allowed_regions",
        "excluded_regions",
        "extraction_options",
    }
    assert dto["page"] == {
        "schema_version": 1,
        "width": 120.0,
        "height": 80.0,
        "rotation": 90,
    }
    assert dto["spans"][0]["order"] == 0
    assert dto["words"][0]["order"] == 7
    assert dto["drawings"][0]["source_order"] == 0
    assert dto["drawings"][0]["opacity"] == 0.5
    assert dto["drawings"][0]["items"][1][0] == "re"
    assert dto["allowed_regions"][0]["allowed"] is True
    assert dto["excluded_regions"][0]["allowed"] is False
    assert dto["allowed_regions"][0]["source_order"] == 0
    assert dto["excluded_regions"][0]["source_order"] == 0


def test_page_snapshot_contract_roundtrips_and_rust_digest_matches_python():
    dto = rust_adapter.page_snapshot_to_rust_input(_snapshot_object())
    roundtripped = rust_adapter.roundtrip_dto("page_snapshot", dto)

    assert roundtripped == dto
    canonical = json.dumps(
        dto, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    assert expected == "a05f7956e7e0e9b6c00e66ec81be00e43636beaac436248bef2f623a96b60e16"
    assert rust_adapter.stage_input_digest(dto) == expected
    assert rust_adapter.page_snapshot_digest(dto) == expected


@pytest.mark.parametrize(
    "mutate",
    [
        lambda dto: dto.pop("page"),
        lambda dto: dto.update(schema_version=2),
        lambda dto: dto["page"].update(width=float("nan")),
        lambda dto: dto["words"].append({}),
        lambda dto: dto.__setitem__("extraction_options", []),
    ],
)
def test_page_snapshot_contract_rejects_missing_schema_type_and_nonfinite_values(mutate):
    dto = rust_adapter.page_snapshot_to_rust_input(_snapshot_object())
    mutate(dto)

    with pytest.raises(ValueError):
        rust_adapter.roundtrip_dto("page_snapshot", dto)


def test_stage_dto_declares_stage_and_snapshot_digest():
    snapshot_dto = rust_adapter.page_snapshot_to_rust_input(_snapshot_object())
    stage = rust_adapter.recover_native_text_input(
        snapshot_dto, region=snapshot_dto["allowed_regions"][0]
    )

    assert stage["stage"] == "recover_native_text_input"
    assert stage["input_snapshot_digest"] == rust_adapter.stage_input_digest(snapshot_dto)
    assert stage["spans"] == snapshot_dto["spans"]
