import json
import math
from pathlib import Path

import pytest

from hexai_pdf_parser import rust_adapter


FIXTURE = Path(__file__).parent / "fixtures/rust_migration/wireless/native_span_differential.json"


def _load_vector(name):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return next(vector for vector in fixture["vectors"] if vector["fixture"] == name), fixture["region"]


def _native_spans(vector):
    spans = []
    for item in vector["spans"]:
        block, line, _ = item["source_position"]
        spans.append(
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
                    "block": block,
                    "line": line,
                },
                "block": block,
                "line": line,
            }
        )
    return spans


def _text_run_with_evidence(evidence):
    return {
        "schema_version": 1,
        "text": "合计",
        "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 50.0, "y1": 20.0},
        "span_refs": [0, 1],
        "source_start": 0,
        "source_end": 1,
        "order": 0,
        "evidence": evidence,
    }


def test_build_text_runs_transmits_owned_source_font_size_and_flags_evidence():
    vector, region = _load_vector("cjk_whitelist_spacing")
    spans = _native_spans(vector)
    spans[0]["font"] = None
    spans[0]["size"] = None
    spans[0]["flags"] = None
    spans[1]["flags"] = 7

    runs = rust_adapter.build_text_runs(spans, {"schema_version": 1, **region})

    assert len(runs) == 1
    assert runs[0]["text"] == "合计"
    evidence = runs[0]["evidence"]
    assert evidence["schema_version"] == 1
    assert evidence["source_positions"] == [span["source_position"] for span in spans]
    assert evidence["fonts"] == [None, "SimSun"]
    assert evidence["sizes"] == [None, 10.0]
    assert evidence["flags"] == [None, 7]


def test_text_run_evidence_roundtrip_preserves_owned_lists():
    evidence = {
        "schema_version": 1,
        "source_positions": [
            {"schema_version": 1, "block": 3, "line": 4},
            {"schema_version": 1, "block": 3, "line": 5},
        ],
        "fonts": [None, "SimSun"],
        "sizes": [None, 10.0],
        "flags": [None, 4],
    }

    assert rust_adapter.roundtrip_dto("text_run", _text_run_with_evidence(evidence))["evidence"] == evidence


def test_text_run_dto_legacy_shape_unchanged_without_evidence():
    data = {
        "schema_version": 1,
        "text": "合计",
        "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 50.0, "y1": 20.0},
        "span_refs": [0, 1],
        "source_start": 0,
        "source_end": 1,
        "order": 0,
    }

    assert rust_adapter.roundtrip_dto("text_run", data) == data


def test_text_run_rejects_evidence_cardinality_mismatch():
    evidence = {
        "schema_version": 1,
        "source_positions": [{"schema_version": 1, "block": 0, "line": 0}],
        "fonts": ["SimSun"],
        "sizes": [10.0],
        "flags": [0],
    }

    with pytest.raises(ValueError, match=r"span_refs|evidence"):
        rust_adapter.roundtrip_dto("text_run", _text_run_with_evidence(evidence))


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (
            {
                "schema_version": 1,
                "source_positions": [{"schema_version": 1, "block": 0, "line": 0}],
                "fonts": [],
                "sizes": [10.0],
                "flags": [0],
            },
            "fonts",
        ),
        (
            {
                "schema_version": 1,
                "source_positions": [{"schema_version": 1, "block": 0, "line": 0}],
                "fonts": [123],
                "sizes": [10.0],
                "flags": [0],
            },
            "fonts",
        ),
        (
            {
                "schema_version": 1,
                "source_positions": [{"schema_version": 1, "block": 0, "line": 0}],
                "fonts": ["SimSun"],
                "sizes": [math.inf],
                "flags": [0],
            },
            "sizes",
        ),
        (
            {
                "schema_version": 1,
                "source_positions": [{"schema_version": 1, "block": 0, "line": 0}],
                "fonts": ["SimSun"],
                "sizes": [math.nan],
                "flags": [0],
            },
            "sizes",
        ),
        (
            {
                "schema_version": 1,
                "source_positions": [{"schema_version": 1, "block": 0, "line": 0}],
                "fonts": ["SimSun"],
                "sizes": [10.0],
                "flags": ["bad"],
            },
            "flags",
        ),
    ],
)
def test_text_run_rejects_invalid_evidence(evidence, message):
    with pytest.raises(ValueError, match=message):
        rust_adapter.roundtrip_dto("text_run", _text_run_with_evidence(evidence))
