import json
import inspect
from pathlib import Path

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.span_chain import region_spans
from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan


FIXTURE = Path(__file__).parent / "fixtures/rust_migration/wireless/native_span_differential.json"
FIELDS = {
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
}
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
                },
                "font/script": {"font": run["font"], "script": run["script"]},
                "span/run refs": {"span_refs": refs, "run_refs": None},
                "source continuity": _source_continuity(refs, source_by_ref),
                "errors": [],
            }
        )
    return normalized


def _rust_normalized_runs(runs, vector):
    normalized = []
    for index, run in enumerate(runs):
        refs = [_canonical_ref(order) for order in run["span_refs"]]
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
                },
                "font/script": None,
                "span/run refs": {"span_refs": refs, "run_refs": None},
                "source continuity": None,
                "errors": [],
            }
        )
    return normalized


def _classification(fixture, field):
    if field in {"font/script", "source continuity"}:
        return "unsupported"
    return SEMANTIC_GAP_CLASSIFICATION.get(fixture, "requires_adaptation")


def _values_equal(field, python_value, rust_value):
    if field == "bbox":
        return all(abs(left - right) <= 0.01 for left, right in zip(python_value, rust_value))
    return python_value == rust_value


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
                ledger.append(
                    {
                        "fixture": name,
                        "layer": "text_runs",
                        "field": "errors",
                        "python_value": python_error,
                        "rust_value": rust_error,
                        "classification": "unsupported",
                    }
                )
            continue

        common_count = min(len(python_runs), len(rust_runs))
        if len(python_runs) != len(rust_runs):
            ledger.append(
                {
                    "fixture": name,
                    "layer": "span_chain" if name == "packed_numeric_split" else "text_runs",
                    "field": "presence",
                    "python_value": len(python_runs),
                    "rust_value": len(rust_runs),
                    "classification": _classification(name, "presence"),
                }
            )
        for index in range(common_count):
            python_run = python_runs[index]
            rust_run = rust_runs[index]
            for field in FIELDS - {"presence"}:
                python_value = python_run[field]
                rust_value = rust_run[field]
                if not _values_equal(field, python_value, rust_value):
                    ledger.append(
                        {
                            "fixture": name,
                            "layer": "span_chain" if name == "packed_numeric_split" else "text_runs",
                            "field": field,
                            "python_value": python_value,
                            "rust_value": rust_value,
                            "classification": _classification(name, field),
                        }
                    )
    return ledger


def test_differential_ledger_is_field_level_repeatable_and_explicit():
    fixture = _load_fixture()
    assert {vector["fixture"] for vector in fixture["vectors"]} == REQUIRED_FIXTURES
    first = build_differential_ledger(fixture)
    second = build_differential_ledger(fixture)

    assert first == second
    assert first
    assert {item["field"] for item in first} <= FIELDS
    assert all(
        set(item) == {"fixture", "layer", "field", "python_value", "rust_value", "classification"}
        for item in first
    )
    assert {item["classification"] for item in first} <= {
        "requires_adaptation",
        "defect",
        "unsupported",
    }

    by_fixture = {name: {item["field"] for item in first if item["fixture"] == name} for name in {item["fixture"] for item in first}}
    assert {"presence", "grouping", "text"} <= by_fixture["packed_numeric_split"]
    assert {"grouping", "text"} <= by_fixture["superscript_inline_gap"]
    assert {"grouping", "text"} <= by_fixture["vertical_wrapped_witness"]
    assert any(
        item["fixture"] == "alignment_corridor_veto"
        and item["classification"] == "defect"
        and item["field"] in {"grouping", "text"}
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
