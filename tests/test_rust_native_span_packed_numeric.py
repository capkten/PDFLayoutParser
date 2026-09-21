import pytest

from hexai_pdf_parser import rust_adapter


def _span(text, boxes, *, size=10.0):
    x0 = boxes[0][1]
    x1 = boxes[-1][2]
    return {
        "schema_version": 1,
        "text": text,
        "rect": {"schema_version": 1, "x0": x0, "y0": 10.0, "x1": x1, "y1": 20.0},
        "font": "SimSun",
        "size": size,
        "flags": 0,
        "order": 0,
        "characters": [
            {
                "schema_version": 1,
                "text": char,
                "rect": {"schema_version": 1, "x0": x0, "y0": 10.0, "x1": x1, "y1": 20.0},
                "order": index,
            }
            for index, (char, x0, x1) in enumerate(boxes)
        ],
        "source_position": {"schema_version": 1, "block": 0, "line": 0},
        "block": 0,
        "line": 0,
    }


def test_rust_native_span_splits_packed_numeric_fields_with_owned_fragment_evidence():
    spans = [
        _span(
            "100   200",
            [
                ("1", 20.0, 26.0),
                ("0", 26.0, 32.0),
                ("0", 32.0, 38.0),
                (" ", 38.0, 42.0),
                (" ", 42.0, 46.0),
                (" ", 46.0, 50.0),
                ("2", 50.0, 56.0),
                ("0", 56.0, 62.0),
                ("0", 62.0, 68.0),
            ],
        )
    ]
    region = {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 50.0}

    runs = rust_adapter.build_text_runs(spans, region)

    assert [run["text"] for run in runs] == ["100", "200"]
    assert [
        [run["rect"][key] for key in ("x0", "y0", "x1", "y1")]
        for run in runs
    ] == [[20.0, 10.0, 38.0, 20.0], [50.0, 10.0, 68.0, 20.0]]
    assert [run["span_refs"] for run in runs] == [[0], [0]]
    assert [run["evidence"]["source_fragment_indices"] for run in runs] == [[0], [1]]
    assert [run["evidence"]["source_fragment_counts"] for run in runs] == [[2], [2]]


def _packed_span(text):
    boxes = []
    x = 10.0
    after_space = False
    for char in text:
        if after_space and not char.isspace():
            x += 4.0
        width = 2.0 if char.isspace() else 4.0
        boxes.append((char, x, x + width))
        x += width
        after_space = char.isspace()
    return _span(text, boxes)


def _run_texts(text, boxes=None, *, size=10.0):
    span = _packed_span(text) if boxes is None else _span(text, boxes, size=size)
    region = {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 300.0, "y1": 50.0}
    return rust_adapter.build_text_runs([span], region)


def test_rust_native_span_splits_placeholder_and_multiple_numeric_fragments():
    placeholder_runs = _run_texts("- 1,6")
    multiple_runs = _run_texts("---  5,100,000.00  51%")

    assert [run["text"] for run in placeholder_runs] == ["-", "1,6"]
    assert [run["text"] for run in multiple_runs] == ["---", "5,100,000.00", "51%"]
    assert [run["evidence"]["source_fragment_indices"] for run in multiple_runs] == [
        [0],
        [1],
        [2],
    ]
    assert [run["evidence"]["source_fragment_counts"] for run in multiple_runs] == [
        [3],
        [3],
        [3],
    ]


def test_rust_native_span_refuses_single_tight_or_malformed_candidates():
    single = _run_texts("100")
    tight = _run_texts(
        "1 2",
        [("1", 10.0, 15.0), (" ", 15.0, 15.8), ("2", 16.0, 21.0)],
        size=5.0,
    )
    cjk = _run_texts("未来12个月")
    malformed = _run_texts(
        "100 200",
        [("1", 20.0, 26.0), ("0", 26.0, 32.0), (" ", 32.0, 38.0)],
    )

    assert [run["text"] for run in single] == ["100"]
    assert [run["text"] for run in tight] == ["1 2"]
    assert [run["text"] for run in cjk] == ["未来12个月"]
    assert [run["text"] for run in malformed] == ["100 200"]


def _text_run(evidence):
    return {
        "schema_version": 1,
        "text": "100",
        "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 30.0, "y1": 20.0},
        "span_refs": [0],
        "source_start": 0,
        "source_end": 0,
        "order": 0,
        "evidence": evidence,
    }


def _valid_fragment_evidence():
    return {
        "schema_version": 1,
        "source_positions": [{"schema_version": 1, "block": 0, "line": 0}],
        "fonts": ["SimSun"],
        "sizes": [10.0],
        "flags": [0],
        "source_fragment_indices": [0],
        "source_fragment_counts": [2],
    }


def test_text_run_fragment_evidence_roundtrip_is_owned_and_aligned():
    evidence = _valid_fragment_evidence()

    assert rust_adapter.roundtrip_dto("text_run", _text_run(evidence))["evidence"] == evidence


@pytest.mark.parametrize(
    "mutate",
    [
        lambda evidence: evidence.pop("source_fragment_counts"),
        lambda evidence: evidence.update(source_fragment_indices=["bad"]),
        lambda evidence: evidence.update(source_fragment_indices=[-1]),
        lambda evidence: evidence.update(source_fragment_indices=[2]),
        lambda evidence: evidence.update(source_fragment_counts=[-1]),
        lambda evidence: evidence.update(source_fragment_indices=[0, 1]),
    ],
)
def test_text_run_rejects_invalid_fragment_evidence(mutate):
    evidence = _valid_fragment_evidence()
    mutate(evidence)

    with pytest.raises(ValueError, match=r"fragment|evidence"):
        rust_adapter.roundtrip_dto("text_run", _text_run(evidence))
