import json
import hashlib
import inspect
import os
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from collections import Counter

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.recoverer import _native_atom_core
from hexai_pdf_parser.tables.wireless_structure.span_chain import region_spans
from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan


FIXTURE = Path(__file__).parent / "fixtures/rust_migration/wireless/native_span_differential.json"
FIELDS = (
    "presence",
    "value",
    "ordering",
    "grouping",
    "text",
    "bbox",
    "flow/order",
    "font/script",
    "span/run refs",
    "source continuity",
    "errors",
)
SEMANTIC_FIELDS = {"presence", "value", "ordering", "grouping", "text", "bbox"}
SEMANTIC_GAP_CLASSIFICATION = {
    "packed_numeric_split": "requires_adaptation",
    "superscript_inline_gap": "requires_adaptation",
    "vertical_wrapped_witness": "requires_adaptation",
    "alignment_corridor_veto": "defect",
}
REQUIRED_FIXTURES = {
    "packed_numeric_split",
    "empty_whitespace_and_separator",
    "cjk_whitelist_spacing",
    "cjk_non_whitelist_spacing",
    "superscript_inline_gap",
    "vertical_wrapped_witness",
    "source_block_line_noncontinuous",
    "alignment_corridor_veto",
    "independent_fields_counterexample",
    "single_field_control",
}
EXPECTED_LEDGER_SHA256 = "cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81"
EXPECTED_FIXTURE_COUNTS = {
    "alignment_corridor_veto": 40,
    "cjk_non_whitelist_spacing": 10,
    "cjk_whitelist_spacing": 5,
    "empty_whitespace_and_separator": 6,
    "independent_fields_counterexample": 10,
    "packed_numeric_split": 10,
    "single_field_control": 5,
    "source_block_line_noncontinuous": 10,
    "superscript_inline_gap": 5,
    "vertical_wrapped_witness": 10,
}
EXPECTED_FIELD_COUNTS = {
    "flow/order": 23,
    "font/script": 22,
    "source continuity": 22,
    "span/run refs": 44,
}
EXPECTED_CLASS_COUNTS = {
    "defect": 8,
    "requires_adaptation": 15,
    "unsupported": 88,
}
EXPLICIT_AUDIT = {
    (
        "empty_whitespace_and_separator",
        "text_runs",
        "flow/order",
    ): {
        "classification": "requires_adaptation",
        "reason": "Rust text run omits flow metadata for the separator survivor; Python retains source flow 2.",
    },
    (
        "empty_whitespace_and_separator",
        "atoms",
        "flow/order",
    ): {
        "classification": "requires_adaptation",
        "reason": "Rust atom exposes filtered local flow/order 1 while Python retains source order 2 after separator filtering.",
    },
}


def _load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _python_runs(vector, region):
    spans = [
        NativeSpan(
            item["text"],
            BBox(*item["bbox"]),
            item["font"],
            item["size"],
            item["order"],
            [(char["text"], BBox(*char["bbox"])) for char in item["char_boxes"]],
            tuple(item["source_position"]),
        )
        for item in vector["spans"]
    ]
    normalized = region_spans(spans, BBox(region["x0"], region["y0"], region["x1"], region["y1"]))
    return build_text_runs(normalized)


def _rust_runs(vector, region):
    spans = [
        {
            "schema_version": 1,
            "text": item["text"],
            "rect": {
                "schema_version": 1,
                "x0": item["bbox"][0],
                "y0": item["bbox"][1],
                "x1": item["bbox"][2],
                "y1": item["bbox"][3],
            },
            "font": item["font"],
            "size": item["size"],
            "flags": 0,
            "order": item["order"],
            "characters": [
                {
                    "schema_version": 1,
                    "text": char["text"],
                    "rect": {
                        "schema_version": 1,
                        "x0": char["bbox"][0],
                        "y0": char["bbox"][1],
                        "x1": char["bbox"][2],
                        "y1": char["bbox"][3],
                    },
                    "order": index,
                }
                for index, char in enumerate(item["char_boxes"])
            ],
            "source_position": {
                "schema_version": 1,
                "block": item["source_position"][0],
                "line": item["source_position"][1],
            },
            "block": item["source_position"][0],
            "line": item["source_position"][1],
        }
        for item in vector["spans"]
    ]
    return rust_adapter.build_text_runs(spans, {"schema_version": 1, **region})


def _canonical_ref(order):
    return f"S{order}"


def _source_continuity(span_refs, source_by_ref):
    positions = [source_by_ref[ref.split(".", 1)[0]] for ref in span_refs]
    return {
        "known": True,
        "blocks": sorted({position[0] for position in positions}),
        "line_start": min(position[1] for position in positions),
        "line_end": max(position[1] for position in positions),
    }


def _source_orders(span_refs):
    return [int(ref.split(".", 1)[0][1:]) for ref in span_refs]


def _rust_span_refs(run):
    raw_refs = list(run["span_refs"])
    evidence = run.get("evidence") or {}
    indices = evidence.get("source_fragment_indices")
    counts = evidence.get("source_fragment_counts")
    if (indices is None) != (counts is None):
        raise AssertionError("Rust fragment evidence fields must be provided together")
    if indices is None:
        return [_canonical_ref(order) for order in raw_refs]
    if len(indices) != len(raw_refs) or len(counts) != len(raw_refs):
        raise AssertionError("Rust fragment evidence must align with span_refs")
    refs = []
    for order, index, count in zip(raw_refs, indices, counts):
        base = _canonical_ref(order)
        refs.append(f"{base}.{index + 1}" if count > 1 else base)
    return refs


def _python_normalized_runs(runs, vector):
    source_by_ref = {
        _canonical_ref(item["order"]): item["source_position"]
        for item in vector["spans"]
    }
    normalized = []
    for index, run in enumerate(runs):
        refs = list(run["span_refs"])
        normalized.append(
            {
                "presence": True,
                "value": run["text"],
                "ordering": index,
                "grouping": refs,
                "text": run["text"],
                "bbox": list(run["bbox"]),
                "flow/order": {
                    "flow_start": run["flow_start"],
                    "flow_end": run["flow_end"],
                    "order": index,
                    "source_start": min(_source_orders(refs)),
                    "source_end": max(_source_orders(refs)),
                },
                "font/script": {"font": run["font"], "script": run["script"]},
                "span/run refs": {
                    "span_refs": refs,
                    "raw_span_refs": list(run["span_refs"]),
                    "run_refs": None,
                    "raw_run_refs": None,
                },
                "source continuity": _source_continuity(refs, source_by_ref),
                "errors": [],
            }
        )
    return normalized


def _rust_normalized_runs(runs, vector):
    normalized = []
    for index, run in enumerate(runs):
        refs = _rust_span_refs(run)
        normalized.append(
            {
                "presence": True,
                "value": run["text"],
                "ordering": index,
                "grouping": refs,
                "text": run["text"],
                "bbox": [
                    run["rect"]["x0"],
                    run["rect"]["y0"],
                    run["rect"]["x1"],
                    run["rect"]["y1"],
                ],
                "flow/order": {
                    "flow_start": None,
                    "flow_end": None,
                    "order": run["order"],
                    "source_start": run["source_start"],
                    "source_end": run["source_end"],
                },
                "font/script": None,
                "span/run refs": {
                    "span_refs": refs,
                    "raw_span_refs": list(run["span_refs"]),
                    "run_refs": None,
                    "raw_run_refs": None,
                },
                "source continuity": None,
                "errors": [],
            }
        )
    return normalized


def _python_atoms(vector, region):
    runs = _python_runs(vector, region)
    valid_span_orders = {item["order"] for item in vector["spans"]}
    atoms = []
    for index, run in enumerate(runs):
        atom_input = dict(run)
        atom_input["bbox"] = list(run["bbox"])
        atoms.append(_native_atom_core(atom_input, index, valid_span_orders))
    return atoms, runs


def _rust_atoms(vector, region):
    runs = _rust_runs(vector, region)
    atoms = rust_adapter.build_atoms(runs, {"schema_version": 1, **region})
    return atoms, runs


def _atom_rect(atom):
    return [
        atom["rect"]["x0"],
        atom["rect"]["y0"],
        atom["rect"]["x1"],
        atom["rect"]["y1"],
    ]


def _normalized_atoms(atoms, runs, vector, side):
    source_by_ref = {
        _canonical_ref(item["order"]): item["source_position"]
        for item in vector["spans"]
    }
    normalized = []
    for index, (atom, run) in enumerate(zip(atoms, runs)):
        if side == "python":
            span_refs = list(run["span_refs"])
            raw_span_refs = list(run["span_refs"])
            flow_start = atom["flow_start"]
            flow_end = atom["flow_end"]
            source_continuity = _source_continuity(span_refs, source_by_ref)
        else:
            span_refs = _rust_span_refs(run)
            raw_span_refs = list(run["span_refs"])
            flow_start = atom.get("flow_start")
            flow_end = atom.get("flow_end")
            source_start = run["source_start"]
            source_end = run["source_end"]
            if {
                "source_blocks",
                "source_line_start",
                "source_line_end",
                "source_position_known",
            } <= atom.keys():
                source_continuity = {
                    "known": atom["source_position_known"],
                    "blocks": list(atom["source_blocks"]),
                    "line_start": atom["source_line_start"],
                    "line_end": atom["source_line_end"],
                }
            else:
                source_continuity = None
        normalized.append(
            {
                "presence": True,
                "value": atom["text"],
                "ordering": index,
                "grouping": span_refs,
                "text": atom["text"],
                "bbox": _atom_rect(atom),
                "flow/order": {
                    "flow_start": flow_start,
                    "flow_end": flow_end,
                    "order": atom["order"],
                    "source_start": (
                        min(_source_orders(span_refs))
                        if side == "python"
                        else source_start
                    ),
                    "source_end": (
                        max(_source_orders(span_refs))
                        if side == "python"
                        else source_end
                    ),
                },
                "font/script": None,
                "span/run refs": {
                    "span_refs": span_refs,
                    "raw_span_refs": raw_span_refs,
                    "run_refs": list(atom["run_refs"]),
                    "raw_run_refs": list(atom["run_refs"]),
                },
                "source continuity": source_continuity,
                "errors": [],
            }
        )
    return normalized


def _classification(fixture, field):
    if field in {"font/script", "source continuity"}:
        return "unsupported"
    return SEMANTIC_GAP_CLASSIFICATION.get(fixture, "requires_adaptation")


def _values_equal(field, python_value, rust_value):
    if python_value is None or rust_value is None:
        return python_value is rust_value
    if field == "bbox":
        if len(python_value) != len(rust_value):
            return False
        return all(abs(left - right) <= 0.01 for left, right in zip(python_value, rust_value))
    return python_value == rust_value


def _record_mismatch(ledger, fixture, layer, run_identity, field, python_value, rust_value):
    explicit_audit = EXPLICIT_AUDIT.get((fixture, layer, field))
    if explicit_audit is not None:
        classification = explicit_audit["classification"]
        reason = explicit_audit["reason"]
    elif field == "span/run refs":
        python_refs = python_value.get("span_refs") if isinstance(python_value, dict) else None
        rust_refs = rust_value.get("span_refs") if isinstance(rust_value, dict) else None
        if python_refs == rust_refs:
            classification = "unsupported"
        else:
            classification = _classification(fixture, field)
        reason = {
            "unsupported": "Raw span/run reference representation is not comparable in this bounded slice.",
            "requires_adaptation": "Rust and Python differ at a known adaptation boundary for this fixture.",
            "defect": "Rust differs from Python in a semantic field covered by the migrated contract.",
        }[classification]
    else:
        classification = _classification(fixture, field)
        reason = {
            "unsupported": "Field comparison is outside this bounded slice.",
            "requires_adaptation": "Rust and Python differ at a known adaptation boundary for this fixture.",
            "defect": "Rust differs from Python in a semantic field covered by the migrated contract.",
        }[classification]
    ledger.append(
        {
            "fixture": fixture,
            "layer": layer,
            "run_identity": run_identity,
            "field": field,
            "python_value": python_value,
            "rust_value": rust_value,
            "classification": classification,
            "reason": reason,
        }
    )


def _item_identity(item):
    grouping = tuple(item.get("grouping", ()))
    if not grouping:
        return "__empty_grouping__"
    return "|".join(grouping)


def _compare_layer(ledger, fixture, layer, python_items, rust_items):
    layer_key = "span_chain" if layer == "text_runs" and fixture == "packed_numeric_split" else layer
    if len(python_items) != len(rust_items):
        _record_mismatch(
            ledger,
            fixture,
            layer_key,
            "__count__",
            "presence",
            len(python_items),
            len(rust_items),
        )
    python_by_identity = {}
    rust_by_identity = {}
    for item in python_items:
        python_by_identity.setdefault(_item_identity(item), []).append(item)
    for item in rust_items:
        rust_by_identity.setdefault(_item_identity(item), []).append(item)

    for identity in sorted(set(python_by_identity) | set(rust_by_identity)):
        python_group = python_by_identity.get(identity, [])
        rust_group = rust_by_identity.get(identity, [])
        if len(python_group) > 1 or len(rust_group) > 1:
            _record_mismatch(
                ledger,
                fixture,
                layer_key,
                f"duplicate:{identity}",
                "errors",
                {"duplicate_identity": identity, "count": len(python_group)},
                {"duplicate_identity": identity, "count": len(rust_group)},
            )
        for index in range(max(len(python_group), len(rust_group))):
            python_item = python_group[index] if index < len(python_group) else None
            rust_item = rust_group[index] if index < len(rust_group) else None
            if python_item is not None and rust_item is not None:
                run_identity = identity
            elif python_item is not None:
                run_identity = f"python:{identity}"
            else:
                run_identity = f"rust:{identity}"
            if python_item is None or rust_item is None:
                _record_mismatch(
                    ledger,
                    fixture,
                    layer_key,
                    run_identity,
                    "presence",
                    python_item is not None,
                    rust_item is not None,
                )
            for field in FIELDS:
                if field == "presence":
                    continue
                python_value = python_item[field] if python_item is not None else None
                rust_value = rust_item[field] if rust_item is not None else None
                if (
                    python_item is None
                    or rust_item is None
                    or not _values_equal(field, python_value, rust_value)
                ):
                    _record_mismatch(
                        ledger,
                        fixture,
                        layer_key,
                        run_identity,
                        field,
                        python_value,
                        rust_value,
                    )


def _stable_ledger_key(item):
    return (
        item["fixture"],
        item["layer"],
        item["run_identity"],
        item["field"],
        item["classification"],
    )


def build_differential_ledger(fixture):
    ledger = []
    for vector in fixture["vectors"]:
        name = vector["fixture"]
        try:
            python_runs = _python_normalized_runs(
                _python_runs(vector, fixture["region"]), vector
            )
            python_error = None
        except Exception as exc:  # pragma: no cover - recorded as a field mismatch
            python_runs = []
            python_error = {"type": type(exc).__name__, "message": str(exc)}
        try:
            rust_runs = _rust_normalized_runs(
                _rust_runs(vector, fixture["region"]), vector
            )
            rust_error = None
        except Exception as exc:  # pragma: no cover - recorded as a field mismatch
            rust_runs = []
            rust_error = {"type": type(exc).__name__, "message": str(exc)}

        if python_error or rust_error:
            if python_error != rust_error:
                _record_mismatch(
                    ledger,
                    name,
                    "text_runs",
                    "__error__",
                    "errors",
                    python_error,
                    rust_error,
                )
            continue
        _compare_layer(ledger, name, "text_runs", python_runs, rust_runs)

        try:
            python_atoms_raw, python_atom_runs = _python_atoms(vector, fixture["region"])
            python_atoms = _normalized_atoms(
                python_atoms_raw, python_atom_runs, vector, "python"
            )
            python_atom_error = None
        except Exception as exc:  # pragma: no cover - recorded as a field mismatch
            python_atoms = []
            python_atom_error = {"type": type(exc).__name__, "message": str(exc)}
        try:
            rust_atoms_raw, rust_atom_runs = _rust_atoms(vector, fixture["region"])
            rust_atoms = _normalized_atoms(
                rust_atoms_raw, rust_atom_runs, vector, "rust"
            )
            rust_atom_error = None
        except Exception as exc:  # pragma: no cover - recorded as a field mismatch
            rust_atoms = []
            rust_atom_error = {"type": type(exc).__name__, "message": str(exc)}
        if python_atom_error or rust_atom_error:
            if python_atom_error != rust_atom_error:
                _record_mismatch(
                    ledger,
                    name,
                    "atoms",
                    "__error__",
                    "errors",
                    python_atom_error,
                    rust_atom_error,
                )
        else:
            _compare_layer(ledger, name, "atoms", python_atoms, rust_atoms)
    return sorted(ledger, key=_stable_ledger_key)


def test_differential_ledger_is_field_level_repeatable_and_explicit():
    fixture = _load_fixture()
    assert {vector["fixture"] for vector in fixture["vectors"]} == REQUIRED_FIXTURES
    first = build_differential_ledger(fixture)
    second = build_differential_ledger(fixture)

    assert first == second
    assert first
    assert {item["field"] for item in first} <= set(FIELDS)
    assert all(
        set(item)
        == {
            "fixture",
            "layer",
            "run_identity",
            "field",
            "python_value",
            "rust_value",
            "classification",
            "reason",
        }
        for item in first
    )
    assert {item["classification"] for item in first} <= {
        "requires_adaptation",
        "defect",
        "unsupported",
    }
    by_fixture = {name: {item["field"] for item in first if item["fixture"] == name} for name in {item["fixture"] for item in first}}
    assert not {
        item["field"]
        for item in first
        if item["fixture"] == "packed_numeric_split"
        and item["field"] in SEMANTIC_FIELDS
    }
    assert not {
        item["field"]
        for item in first
        if item["fixture"] == "superscript_inline_gap"
        and item["field"] in SEMANTIC_FIELDS
    }
    assert not any(
        item["fixture"] == "alignment_corridor_veto"
        and item["classification"] == "defect"
        and item["field"] in SEMANTIC_FIELDS
        for item in first
    )

    semantic_mismatches = {
        control: {
            item["field"]
            for item in first
            if item["fixture"] == control and item["field"] in SEMANTIC_FIELDS
        }
        for control in {item["fixture"] for item in first}
    }
    assert not semantic_mismatches.get("vertical_wrapped_witness", set())
    for control in {
        "empty_whitespace_and_separator",
        "cjk_whitelist_spacing",
        "cjk_non_whitelist_spacing",
        "source_block_line_noncontinuous",
        "independent_fields_counterexample",
        "single_field_control",
    }:
        assert not semantic_mismatches.get(control, set())

    expected_python_text = {
        "empty_whitespace_and_separator": ["-"],
        "cjk_whitelist_spacing": ["合计"],
        "cjk_non_whitelist_spacing": ["男", "女"],
        "source_block_line_noncontinuous": ["甲", "乙"],
        "independent_fields_counterexample": ["金额", "比例"],
        "single_field_control": ["正常字段"],
    }
    for vector in fixture["vectors"]:
        if vector["fixture"] in expected_python_text:
            assert [
                run["text"] for run in _python_runs(vector, fixture["region"])
            ] == expected_python_text[vector["fixture"]]
    wrapped = next(v for v in fixture["vectors"] if v["fixture"] == "vertical_wrapped_witness")
    assert any("\n" in run["text"] for run in _python_runs(wrapped, fixture["region"]))


def test_separator_flow_order_mismatches_have_explicit_audit_reasons():
    ledger = build_differential_ledger(_load_fixture())

    mismatches = [
        item
        for item in ledger
        if item["fixture"] == "empty_whitespace_and_separator"
        and item["field"] == "flow/order"
    ]

    assert [
        (item["layer"], item["classification"], item["reason"])
        for item in mismatches
    ] == [
        (
            "atoms",
            "requires_adaptation",
            "Rust atom exposes filtered local flow/order 1 while Python retains source order 2 after separator filtering.",
        ),
        (
            "text_runs",
            "requires_adaptation",
            "Rust text run omits flow metadata for the separator survivor; Python retains source flow 2.",
        ),
    ]


def test_alignment_corridor_veto_matches_python_and_keeps_two_row_join():
    fixture = _load_fixture()
    vector = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "alignment_corridor_veto"
    )

    python_runs = _python_runs(vector, fixture["region"])
    rust_runs = _rust_runs(vector, fixture["region"])
    expected = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛"]

    assert [run["text"] for run in python_runs] == expected
    assert [run["text"] for run in rust_runs] == expected
    assert rust_runs[0]["span_refs"] == [0]
    assert rust_runs[1]["span_refs"] == [1]
    assert rust_runs[0]["rect"] == {
        "schema_version": 1,
        "x0": 10.0,
        "y0": 10.0,
        "x1": 30.0,
        "y1": 20.0,
    }

    two_row_control = deepcopy(vector)
    two_row_control["spans"] = two_row_control["spans"][:4]
    python_control = _python_runs(two_row_control, fixture["region"])
    rust_control = _rust_runs(two_row_control, fixture["region"])
    assert [run["text"] for run in python_control] == ["甲乙", "丙丁"]
    assert [run["text"] for run in rust_control] == ["甲乙", "丙丁"]


def test_superscript_inline_gap_matches_python_and_rust_helpers():
    fixture = _load_fixture()
    vector = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "superscript_inline_gap"
    )

    python_runs = _python_runs(vector, fixture["region"])
    rust_runs = _rust_runs(vector, fixture["region"])

    assert [run["text"] for run in python_runs] == ["基2"]
    assert [run["text"] for run in rust_runs] == ["基2"]
    assert rust_runs[0]["span_refs"] == [0, 1]
    assert rust_runs[0]["source_start"] == 0
    assert rust_runs[0]["source_end"] == 1
    assert rust_runs[0]["rect"] == {
        "schema_version": 1,
        "x0": 10.0,
        "y0": 70.0,
        "x1": 40.0,
        "y1": 80.0,
    }
    assert rust_runs[0]["evidence"]["sizes"] == [10.0, 7.0]


def test_superscript_inline_gap_rejects_threshold_and_corridor_variants():
    fixture = _load_fixture()
    base = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "superscript_inline_gap"
    )

    for size, x0 in ((8.2, 34.0), (7.0, 35.0)):
        vector = deepcopy(base)
        candidate = vector["spans"][1]
        candidate["size"] = size
        candidate["bbox"] = [x0, 71.0, x0 + 6.0, 79.0]
        candidate["char_boxes"][0]["bbox"] = list(candidate["bbox"])

        python_runs = _python_runs(vector, fixture["region"])
        rust_runs = _rust_runs(vector, fixture["region"])

        assert [run["text"] for run in python_runs] == ["基", "2"]
        assert [run["text"] for run in rust_runs] == ["基", "2"]


def test_superscript_inline_gap_respects_placeholder_and_numeric_vetoes():
    fixture = _load_fixture()
    base = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "superscript_inline_gap"
    )

    cases = (("numeric_pair", "1", "2"), ("placeholder_candidate", "基", "-"))
    for _, previous_text, candidate_text in cases:
        vector = deepcopy(base)
        previous = vector["spans"][0]
        candidate = vector["spans"][1]
        previous["text"] = previous_text
        previous["char_boxes"][0]["text"] = previous_text
        candidate["text"] = candidate_text
        candidate["char_boxes"][0]["text"] = candidate_text

        python_runs = _python_runs(vector, fixture["region"])
        rust_runs = _rust_runs(vector, fixture["region"])

        assert [run["text"] for run in python_runs] == [
            previous_text,
            candidate_text,
        ]
        assert [run["text"] for run in rust_runs] == [
            previous_text,
            candidate_text,
        ]


def test_wrapped_field_merge_matches_python_and_preserves_owned_evidence():
    fixture = _load_fixture()
    vector = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "vertical_wrapped_witness"
    )

    python_runs = _python_runs(vector, fixture["region"])
    rust_runs = _rust_runs(vector, fixture["region"])

    expected_text = ["第一行\n第二行\n第三行", "右侧字段"]
    assert [run["text"] for run in python_runs] == expected_text
    assert [run["text"] for run in rust_runs] == expected_text
    assert [run["order"] for run in rust_runs] == [0, 2]

    merged = rust_runs[0]
    assert merged["rect"] == {
        "schema_version": 1,
        "x0": 100.0,
        "y0": 10.0,
        "x1": 160.0,
        "y1": 48.0,
    }
    assert merged["span_refs"] == [0, 1, 2]
    assert merged["source_start"] == 0
    assert merged["source_end"] == 2
    assert merged["evidence"] == {
        "schema_version": 1,
        "source_positions": [
            {"schema_version": 1, "block": 0, "line": 0},
            {"schema_version": 1, "block": 0, "line": 1},
            {"schema_version": 1, "block": 0, "line": 2},
        ],
        "fonts": ["SimSun", "SimSun", "SimSun"],
        "sizes": [10.0, 10.0, 10.0],
        "flags": [0, 0, 0],
    }


def test_wrapped_field_merge_ignores_filtered_source_gap():
    fixture = _load_fixture()
    base = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "vertical_wrapped_witness"
    )
    vector = deepcopy(base)
    for span in vector["spans"][1:]:
        span["order"] += 1
    vector["spans"].insert(
        1,
        {
            "text": "区域外来源间隔",
            "bbox": [400.0, 24.0, 460.0, 34.0],
            "font": "SimSun",
            "size": 10.0,
            "order": 1,
            "source_position": [9, 9, 0],
            "char_boxes": [
                {
                    "text": char,
                    "bbox": [400.0 + index * 10.0, 24.0, 410.0 + index * 10.0, 34.0],
                }
                for index, char in enumerate("区域外来源间隔")
            ],
        },
    )

    python_runs = _python_runs(vector, fixture["region"])
    rust_runs = _rust_runs(vector, fixture["region"])

    assert [run["text"] for run in python_runs] == [
        "第一行\n第二行\n第三行",
        "右侧字段",
    ]
    assert [run["text"] for run in rust_runs] == [run["text"] for run in python_runs]
    assert [run["order"] for run in rust_runs] == [0, 2]

    merged = rust_runs[0]
    assert merged["rect"] == {
        "schema_version": 1,
        "x0": 100.0,
        "y0": 10.0,
        "x1": 160.0,
        "y1": 48.0,
    }
    assert merged["span_refs"] == [0, 2, 3]
    assert merged["source_start"] == 0
    assert merged["source_end"] == 3
    assert merged["evidence"] == {
        "schema_version": 1,
        "source_positions": [
            {"schema_version": 1, "block": 0, "line": 0},
            {"schema_version": 1, "block": 0, "line": 1},
            {"schema_version": 1, "block": 0, "line": 2},
        ],
        "fonts": ["SimSun", "SimSun", "SimSun"],
        "sizes": [10.0, 10.0, 10.0],
        "flags": [0, 0, 0],
    }


def test_wrapped_field_merge_requires_witness_and_oracle_geometry():
    fixture = _load_fixture()
    base = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "vertical_wrapped_witness"
    )

    variants = []
    without_witness = deepcopy(base)
    without_witness["spans"] = without_witness["spans"][:3]
    variants.append(without_witness)

    incompatible_font = deepcopy(base)
    incompatible_font["spans"][1]["font"] = "SimSun-Bold"
    variants.append(incompatible_font)

    excessive_gap = deepcopy(base)
    excessive_gap["spans"][1]["bbox"] = [100.0, 34.1, 160.0, 44.1]
    for char in excessive_gap["spans"][1]["char_boxes"]:
        char["bbox"][1] += 10.1
        char["bbox"][3] += 10.1
    variants.append(excessive_gap)

    insufficient_overlap = deepcopy(base)
    insufficient_overlap["spans"][1]["bbox"] = [170.0, 24.0, 230.0, 34.0]
    for char in insufficient_overlap["spans"][1]["char_boxes"]:
        char["bbox"][0] += 70.0
        char["bbox"][2] += 70.0
    variants.append(insufficient_overlap)

    for vector in variants:
        python_runs = _python_runs(vector, fixture["region"])
        rust_runs = _rust_runs(vector, fixture["region"])
        assert [run["text"] for run in rust_runs] == [
            run["text"] for run in python_runs
        ]
        assert all("\n" not in run["text"] for run in python_runs)


def test_wrapped_field_merge_rejects_noncontinuous_source_control():
    fixture = _load_fixture()
    vector = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "source_block_line_noncontinuous"
    )

    python_runs = _python_runs(vector, fixture["region"])
    rust_runs = _rust_runs(vector, fixture["region"])

    assert [run["text"] for run in python_runs] == ["甲", "乙"]
    assert [run["text"] for run in rust_runs] == ["甲", "乙"]


def test_wrapped_field_merge_rejects_noncontinuous_source_in_fallback_pair():
    fixture = _load_fixture()
    base_spans = [
        {
            "text": "右侧字段",
            "bbox": [240.0, 0.0, 300.0, 40.0],
            "font": "SimSun",
            "size": 10.0,
            "order": 0,
            "source_position": [1, 0, 0],
            "char_boxes": [
                {"text": char, "bbox": [240.0 + index * 15.0, 0.0, 255.0 + index * 15.0, 40.0]}
                for index, char in enumerate("右侧字段")
            ],
        },
        {
            "text": "其",
            "bbox": [100.0, 10.0, 110.0, 20.0],
            "font": "SimSun",
            "size": 10.0,
            "order": 1,
            "source_position": [22, 0, 0],
            "char_boxes": [{"text": "其", "bbox": [100.0, 10.0, 110.0, 20.0]}],
        },
        {
            "text": "他",
            "bbox": [100.0, 24.0, 110.0, 34.0],
            "font": "SimSun",
            "size": 10.0,
            "order": 2,
            "source_position": [22, 1, 0],
            "char_boxes": [{"text": "他", "bbox": [100.0, 24.0, 110.0, 34.0]}],
        },
    ]
    for position in ([22, 2, 0], [23, 1, 0]):
        vector = {
            "fixture": "fallback_source_control",
            "spans": deepcopy(base_spans),
        }
        vector["spans"][2]["source_position"] = list(position)
        python_runs = _python_runs(vector, fixture["region"])
        rust_runs = _rust_runs(vector, fixture["region"])
        assert [run["text"] for run in rust_runs] == [
            run["text"] for run in python_runs
        ]
        assert "其\n他" not in {run["text"] for run in python_runs}


def test_complete_ledger_is_locked_by_count_summary_and_digest():
    ledger = build_differential_ledger(_load_fixture())
    serialized = json.dumps(
        ledger, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert len(ledger) == 111
    assert dict(Counter(item["fixture"] for item in ledger)) == EXPECTED_FIXTURE_COUNTS
    assert dict(Counter(item["field"] for item in ledger)) == EXPECTED_FIELD_COUNTS
    assert dict(Counter(item["classification"] for item in ledger)) == EXPECTED_CLASS_COUNTS
    assert hashlib.sha256(serialized).hexdigest() == EXPECTED_LEDGER_SHA256


def test_harness_does_not_use_page_or_word_reads_and_keeps_routes(monkeypatch):
    source = Path(__file__).read_text(encoding="utf-8")
    assert "fitz." + "Page" not in source
    assert "get_text(" + '"words")' not in source
    assert "get_text(" + "'words')" not in source
    assert "str(" + "python_runs)" not in inspect.getsource(build_differential_ledger)

    monkeypatch.delenv("PDF_RUST_MODE", raising=False)
    monkeypatch.delenv("PDF_RUST_MODE_WIRELESS_TABLE_RECOVERY", raising=False)
    assert rust_adapter.get_rust_mode("wireless_table_recovery") == "python"

    python_value = {"source": "python"}
    result = rust_adapter.run_python_or_rust(
        "shadow",
        lambda: python_value,
        lambda _input: {"source": "rust"},
        input_dto={},
        path="task-3a",
    )
    assert result is python_value


def test_ledger_field_order_and_sort_are_hash_seed_stable():
    fixture = _load_fixture()
    assert isinstance(FIELDS, tuple)
    ledger = build_differential_ledger(fixture)
    assert ledger == sorted(
        ledger,
        key=lambda item: (
            item["fixture"],
            item["layer"],
            item.get("run_identity", ""),
            item["field"],
        ),
    )


def test_ledger_json_is_identical_across_hash_seeds():
    module_path = str(Path(__file__).resolve())
    script = """
import importlib.util
import json
import sys
spec = importlib.util.spec_from_file_location('task_3a_diff', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.build_differential_ledger(module._load_fixture()), ensure_ascii=False, sort_keys=True, separators=(',', ':')))
"""
    outputs = []
    for seed in ("1", "2"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
        env["PYTHONIOENCODING"] = "utf-8"
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", script, module_path],
                env=env,
                text=True,
                encoding="utf-8",
            )
        )
    assert outputs[0] == outputs[1]


def test_packed_numeric_fragment_evidence_aligns_python_identities():
    fixture = _load_fixture()
    vector = next(
        vector
        for vector in fixture["vectors"]
        if vector["fixture"] == "packed_numeric_split"
    )

    normalized = _rust_normalized_runs(
        _rust_runs(vector, fixture["region"]), vector
    )

    assert [item["grouping"] for item in normalized] == [["S0.1"], ["S0.2"]]


def test_raw_refs_and_source_bounds_are_not_discarded():
    fixture = _load_fixture()
    vector = next(v for v in fixture["vectors"] if v["fixture"] == "packed_numeric_split")
    rust_run = _rust_normalized_runs(_rust_runs(vector, fixture["region"]), vector)[0]
    assert rust_run["span/run refs"]["raw_span_refs"] == [0]
    assert rust_run["span/run refs"]["run_refs"] is None
    assert rust_run["flow/order"]["source_start"] == 0
    assert rust_run["flow/order"]["source_end"] == 0
    rust_atoms, rust_runs = _rust_atoms(vector, fixture["region"])
    rust_atom = _normalized_atoms(rust_atoms, rust_runs, vector, "rust")[0]
    assert rust_atom["span/run refs"]["run_refs"] == [0]
    assert rust_atom["flow/order"] == {
        "flow_start": 1,
        "flow_end": 1,
        "order": 1,
        "source_start": 0,
        "source_end": 0,
    }
    assert rust_atom["source continuity"] == {
        "known": True,
        "blocks": [0],
        "line_start": 0,
        "line_end": 0,
    }


def test_build_atoms_uses_source_span_refs_not_visual_run_order():
    run = {
        "schema_version": 1,
        "text": "source-owned",
        "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 80.0, "y1": 20.0},
        "span_refs": [7, 9],
        "source_start": 7,
        "source_end": 9,
        "order": 41,
        "flow_start": 20,
        "flow_end": 22,
        "evidence": {
            "schema_version": 1,
            "source_positions": [
                {"schema_version": 1, "block": 6, "line": 3},
                {"schema_version": 1, "block": 6, "line": 4},
            ],
            "fonts": ["SimSun", "SimSun"],
            "sizes": [10.0, 10.0],
            "flags": [0, 0],
        },
    }

    atom = rust_adapter.build_atoms([run])[0]

    assert atom["run_refs"] == [7, 9]


def test_build_atoms_preserves_flow_and_owned_source_evidence():
    fixture = _load_fixture()
    packed = next(item for item in fixture["vectors"] if item["fixture"] == "packed_numeric_split")

    atoms, _ = _rust_atoms(packed, fixture["region"])

    assert [(atom["flow_start"], atom["flow_end"], atom["order"], atom["run_refs"]) for atom in atoms] == [
        (1, 1, 1, [0]),
        (2, 2, 2, [0]),
    ]
    assert all(atom["source_blocks"] == [0] for atom in atoms)
    assert all(atom["source_line_start"] == 0 for atom in atoms)
    assert all(atom["source_line_end"] == 0 for atom in atoms)
    assert all(atom["source_position_known"] is True for atom in atoms)


def test_build_atoms_flow_covers_filtered_gap_and_wrapped_chain():
    fixture = _load_fixture()
    base = next(
        item for item in fixture["vectors"] if item["fixture"] == "vertical_wrapped_witness"
    )
    vector = deepcopy(base)
    for span in vector["spans"][1:]:
        span["order"] += 1
    vector["spans"].insert(
        1,
        {
            "text": "filtered source gap",
            "bbox": [400.0, 24.0, 460.0, 34.0],
            "font": "SimSun",
            "size": 10.0,
            "order": 1,
            "source_position": [9, 9, 0],
            "char_boxes": [
                {
                    "text": char,
                    "bbox": [400.0 + index * 10.0, 24.0, 410.0 + index * 10.0, 34.0],
                }
                for index, char in enumerate("filtered source gap")
            ],
        },
    )

    atoms, _ = _rust_atoms(vector, fixture["region"])

    assert atoms[0]["text"] == "第一行\n第二行\n第三行"
    assert atoms[0]["flow_start"] == 1
    assert atoms[0]["flow_end"] == 3
    assert atoms[0]["order"] == 1
    assert atoms[0]["run_refs"] == [0, 2, 3]
    assert atoms[0]["source_blocks"] == [0]
    assert atoms[0]["source_line_start"] == 0
    assert atoms[0]["source_line_end"] == 2
    assert atoms[0]["source_position_known"] is True


def test_build_atoms_keeps_legacy_no_evidence_shape():
    run = {
        "schema_version": 1,
        "text": "legacy",
        "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 40.0, "y1": 20.0},
        "span_refs": [3],
        "source_start": 3,
        "source_end": 3,
        "order": 8,
    }

    atom = rust_adapter.build_atoms([run])[0]

    assert set(atom) == {
        "schema_version",
        "text",
        "rect",
        "run_refs",
        "row_hint",
        "col_hint",
        "order",
    }


def test_build_atoms_keeps_legacy_evidence_only_shape_without_flow_bundle():
    run = {
        "schema_version": 1,
        "text": "legacy evidence",
        "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 80.0, "y1": 20.0},
        "span_refs": [3],
        "source_start": 3,
        "source_end": 3,
        "order": 8,
        "evidence": {
            "schema_version": 1,
            "source_positions": [{"schema_version": 1, "block": 4, "line": 6}],
            "fonts": ["SimSun"],
            "sizes": [10.0],
            "flags": [0],
        },
    }

    atom = rust_adapter.build_atoms([run])[0]

    assert set(atom) == {
        "schema_version",
        "text",
        "rect",
        "run_refs",
        "row_hint",
        "col_hint",
        "order",
    }


def test_atom_layer_is_present_and_uses_real_helpers():
    ledger = build_differential_ledger(_load_fixture())
    assert any(item["layer"] == "atoms" for item in ledger)


def test_bbox_comparison_rejects_length_mismatch():
    assert not _values_equal("bbox", [0.0, 0.0, 1.0, 1.0, 99.0], [0.0, 0.0, 1.0, 1.0])


def test_middle_missing_run_aligns_by_identity_not_position():
    def item(ref, text):
        return {
            "presence": True,
            "value": text,
            "ordering": 0,
            "grouping": [ref],
            "text": text,
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "flow/order": {"flow_start": 0, "flow_end": 0, "order": 0},
            "font/script": None,
            "span/run refs": {"span_refs": [ref], "run_refs": None},
            "source continuity": None,
            "errors": [],
        }

    ledger = []
    _compare_layer(
        ledger,
        "middle_missing",
        "text_runs",
        [item("S0", "zero"), item("S1", "one"), item("S2", "two")],
        [item("S0", "zero"), item("S2", "two")],
    )

    missing = [entry for entry in ledger if entry["run_identity"] == "python:S1"]
    assert {"presence", *FIELDS[1:]} <= {entry["field"] for entry in missing}
    assert not any("python:S1|rust:S2" == entry["run_identity"] for entry in ledger)


def test_duplicate_identity_is_recorded_as_error():
    item = {
        "presence": True,
        "value": "zero",
        "ordering": 0,
        "grouping": ["S0"],
        "text": "zero",
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "flow/order": {"flow_start": 0, "flow_end": 0, "order": 0},
        "font/script": None,
        "span/run refs": {"span_refs": ["S0"], "run_refs": None},
        "source continuity": None,
        "errors": [],
    }
    ledger = []
    _compare_layer(ledger, "duplicate_identity", "text_runs", [item, dict(item)], [item])
    assert any(
        entry["field"] == "errors"
        and entry["run_identity"] == "duplicate:S0"
        for entry in ledger
    )
