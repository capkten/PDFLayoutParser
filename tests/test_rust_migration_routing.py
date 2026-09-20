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
                "raw_source_position": (0, 0, 2),
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
                "raw_source_position": (0,),
                "source_order": 0,
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
    assert expected == "f6181446f0cdb04b9b26d463bb9609a534673747417688801a206eca050835dc"
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
    digest = rust_adapter.page_snapshot_digest(snapshot_dto)
    stage = rust_adapter.recover_native_text_input(
        {**snapshot_dto, "input_snapshot_digest": digest},
        region=snapshot_dto["allowed_regions"][0],
    )

    assert stage["stage"] == "recover_native_text_input"
    assert stage["input_snapshot_digest"] == digest
    assert stage["spans"] == snapshot_dto["spans"]


def test_page_snapshot_adapter_rejects_missing_and_wrong_typed_nested_fields():
    cases = []

    missing_block_lines = _snapshot_fixture()
    missing_block = dict(missing_block_lines["text_blocks"][0])
    missing_block.pop("lines")
    missing_block_lines["text_blocks"] = (missing_block,)
    cases.append(missing_block_lines)

    wrong_span_chars = _snapshot_fixture()
    wrong_span_chars["spans"] = (dict(wrong_span_chars["spans"][0]),)
    wrong_span_chars["spans"][0]["chars"] = "not-a-sequence"
    cases.append(wrong_span_chars)

    missing_word_text = _snapshot_fixture()
    missing_word_text["words"] = (dict(missing_word_text["words"][0]),)
    missing_word_text["words"][0].pop("text")
    cases.append(missing_word_text)

    wrong_drawing_items = _snapshot_fixture()
    wrong_drawing_items["drawings"] = (dict(wrong_drawing_items["drawings"][0]),)
    wrong_drawing_items["drawings"][0]["items"] = "not-a-sequence"
    cases.append(wrong_drawing_items)

    wrong_region = _snapshot_fixture()
    wrong_region["allowed_regions"] = (None,)
    cases.append(wrong_region)

    wrong_options = _snapshot_fixture()
    wrong_options["extraction_options"] = []
    cases.append(wrong_options)

    for fixture in cases:
        snapshot = type("Snapshot", (), {})()
        for key, value in fixture.items():
            setattr(snapshot, key, value)
        with pytest.raises(ValueError):
            rust_adapter.page_snapshot_to_rust_input(snapshot)


def test_page_snapshot_adapter_rejects_nonfinite_nested_values_without_coercion():
    fixture = _snapshot_fixture()
    fixture["text_blocks"] = (dict(fixture["text_blocks"][0]),)
    fixture["text_blocks"][0]["lines"] = (dict(fixture["text_blocks"][0]["lines"][0]),)
    fixture["text_blocks"][0]["lines"][0]["spans"] = (
        dict(fixture["text_blocks"][0]["lines"][0]["spans"][0]),
    )
    fixture["text_blocks"][0]["lines"][0]["spans"][0]["size"] = float("inf")
    snapshot = type("Snapshot", (), {})()
    for key, value in fixture.items():
        setattr(snapshot, key, value)

    with pytest.raises(ValueError):
        rust_adapter.page_snapshot_to_rust_input(snapshot)


def test_page_snapshot_adapter_preserves_raw_positions_and_structured_drawing_lines():
    dto = rust_adapter.page_snapshot_to_rust_input(_snapshot_object())

    assert dto["text_blocks"][0]["source_position"] == [0]
    assert dto["text_blocks"][0]["lines"][0]["source_position"] == [0, 0]
    assert dto["text_blocks"][0]["lines"][0]["spans"][0]["raw_source_position"] == [
        0,
        0,
        0,
    ]
    assert dto["spans"][0]["raw_source_position"] == [0, 0, 0]
    assert len(dto["drawings"][0]["lines"]) == 2
    assert dto["drawings"][0]["lines"][0]["rect"] == {
        "schema_version": 1,
        "x0": 0.0,
        "y0": 0.0,
        "x1": 120.0,
        "y1": 0.0,
    }


def test_page_snapshot_preserves_full_character_word_and_drawing_positions_and_digest():
    fixture = _snapshot_fixture()
    fixture["text_blocks"][0]["lines"][0]["spans"][0]["chars"][0][
        "raw_source_position"
    ] = (7, 8, 9, 10, 11)
    fixture["words"][0]["raw_source_position"] = (4, 5, 6, 7, 8)
    fixture["drawings"][0]["raw_source_position"] = (12, 13, 14, 15)
    snapshot = type("Snapshot", (), {})()
    for key, value in fixture.items():
        setattr(snapshot, key, value)

    dto = rust_adapter.page_snapshot_to_rust_input(snapshot)
    character = dto["text_blocks"][0]["lines"][0]["spans"][0]["characters"][0]
    assert character["raw_source_position"] == [7, 8, 9, 10, 11]
    assert dto["spans"][0]["characters"][0]["raw_source_position"] == [0, 0, 0, 0]
    assert dto["words"][0]["raw_source_position"] == [4, 5, 6, 7, 8]
    assert dto["drawings"][0]["raw_source_position"] == [12, 13, 14, 15]

    roundtripped = rust_adapter.roundtrip_dto("page_snapshot", dto)
    assert roundtripped == dto

    changed_fixture = copy.deepcopy(fixture)
    changed_fixture["words"][0]["raw_source_position"] = (4, 5, 6, 7, 99)
    changed_snapshot = type("Snapshot", (), {})()
    for key, value in changed_fixture.items():
        setattr(changed_snapshot, key, value)
    assert rust_adapter.page_snapshot_digest(dto) != rust_adapter.page_snapshot_digest(
        rust_adapter.page_snapshot_to_rust_input(changed_snapshot)
    )


def test_page_snapshot_adapter_requires_source_order_instead_of_fallback_indices():
    fixture = _snapshot_fixture()
    fixture["words"] = (dict(fixture["words"][0]),)
    fixture["words"][0].pop("source_order")
    snapshot = type("Snapshot", (), {})()
    for key, value in fixture.items():
        setattr(snapshot, key, value)

    with pytest.raises(ValueError):
        rust_adapter.page_snapshot_to_rust_input(snapshot)


def test_recover_native_text_input_requires_matching_snapshot_digest():
    snapshot_dto = rust_adapter.page_snapshot_to_rust_input(_snapshot_object())
    digest = rust_adapter.page_snapshot_digest(snapshot_dto)
    validated_input = {**snapshot_dto, "input_snapshot_digest": digest}

    with pytest.raises(ValueError, match="input_snapshot_digest"):
        rust_adapter.recover_native_text_input(snapshot_dto)
    with pytest.raises(ValueError, match="input_snapshot_digest"):
        rust_adapter.recover_native_text_input(
            {**validated_input, "input_snapshot_digest": "0" * 64}
        )

    stage = rust_adapter.recover_native_text_input(
        validated_input, region=snapshot_dto["allowed_regions"][0]
    )
    assert stage["stage"] == "recover_native_text_input"
    assert stage["input_snapshot_digest"] == digest


def test_stage_input_digest_wrapper_uses_direct_rust_binding(monkeypatch):
    observed = {}

    def fake_stage_digest(data):
        observed["data"] = data
        return "rust-stage-digest"

    monkeypatch.setattr(rust_adapter._pdf_fast, "stage_input_digest", fake_stage_digest)

    assert rust_adapter.stage_input_digest({"unicode": "甲✨"}) == "rust-stage-digest"
    assert observed["data"] == {"unicode": "甲✨"}


def test_direct_rust_stage_digest_matches_python_wrapper_for_fixed_unicode_fixture():
    stage_input = {
        "stage": "recover_native_text_input",
        "unicode": "甲✨",
        "nested": {"z": [3, 2, 1], "a": {"β": "值"}},
    }
    reordered = {
        "nested": {"a": {"β": "值"}, "z": [3, 2, 1]},
        "unicode": "甲✨",
        "stage": "recover_native_text_input",
    }

    direct = rust_adapter._pdf_fast.stage_input_digest(stage_input)
    assert direct == rust_adapter._pdf_fast.stage_input_digest(reordered)
    assert rust_adapter.stage_input_digest(reordered) == direct
    assert direct == "53e4488a7f0d3a4af575f9bbddda272af8d6bba4f60b2578c47c0031a65a0364"

    with pytest.raises(ValueError):
        rust_adapter.stage_input_digest({"bad": float("nan")})


def test_page_snapshot_adapter_and_stage_output_are_recursively_unaliased():
    snapshot = _snapshot_object()
    dto = rust_adapter.page_snapshot_to_rust_input(snapshot)
    digest = rust_adapter.page_snapshot_digest(dto)
    snapshot_before = copy.deepcopy(snapshot.__dict__)
    dto_before = copy.deepcopy(dto)

    dto["text_blocks"][0]["lines"][0]["spans"][0]["characters"][0]["text"] = "changed"
    dto["drawings"][0]["items"][0][1][0] = 999.0
    dto["extraction_options"]["options"]["rawdict"]["selected"]["kwargs"]["flags"] = 99

    assert snapshot.text_blocks[0]["lines"][0]["spans"][0]["chars"][0]["c"] == "甲"
    assert snapshot.drawings[0]["items"][0][1][0] == 0.0
    assert snapshot.extraction_options["rawdict"]["selected"]["kwargs"]["flags"] == 2

    stage = rust_adapter.recover_native_text_input(
        {**dto_before, "input_snapshot_digest": digest},
        region=dto_before["allowed_regions"][0],
    )
    stage["spans"][0]["characters"][0]["text"] = "stage-mutated"
    stage["spans"][0]["characters"][0]["raw_source_position"].append(99)
    stage["region"]["x0"] = 99.0
    stage["input_snapshot_digest"] = "mutated"

    assert snapshot.__dict__ == snapshot_before
    assert dto_before == rust_adapter.page_snapshot_to_rust_input(snapshot)
