from __future__ import annotations

from dataclasses import replace

import pytest

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.pdf_snapshot import PageSnapshot
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan
from hexai_pdf_parser.tables.wireless_structure import recoverer


def _snapshot_for_rows(rows):
    lines = []
    for row_index, values in enumerate(rows):
        y0 = 10.0 + row_index * 20.0
        spans = []
        spans.extend(
            {
                "bbox": (x0, y0, x0 + 30.0, y0 + 10.0),
                "font": "SimSun",
                "size": 10.0,
                "chars": tuple(
                    {
                        "c": character,
                        "bbox": (
                            x0 + char_index * 8.0,
                            y0,
                            x0 + (char_index + 1) * 8.0,
                            y0 + 10.0,
                        ),
                    }
                    for char_index, character in enumerate(text)
                ),
            }
            for column_index, text in enumerate(values)
            for x0 in (10.0 + column_index * 100.0,)
        )
        lines.append(
            {
                "bbox": (0.0, y0, 240.0, y0 + 10.0),
                "spans": tuple(spans),
            }
        )
    return PageSnapshot(
        schema_version=1,
        version=1,
        page_index=0,
        geometry={
            "rect": (0.0, 0.0, 240.0, 100.0),
            "x0": 0.0,
            "y0": 0.0,
            "x1": 240.0,
            "y1": 100.0,
            "width": 240.0,
            "height": 100.0,
            "rotation": 0,
        },
        text_blocks=(
            {
                "type": 0,
                "bbox": (0.0, 0.0, 240.0, 100.0),
                "lines": tuple(lines),
            },
        ),
        spans=(),
        characters=(),
        words=(),
        drawings=(),
        allowed_regions=(),
        excluded_regions=(),
        extraction_options={},
        summary={},
    )


def test_native_region_bridge_contains_shared_atoms_bands_region_and_config(
    monkeypatch,
):
    snapshot = _snapshot_for_rows(
        (
            ("项目", "金额"),
            ("甲", "10"),
            ("乙", "20"),
        )
    )
    region = BBox(0.0, 0.0, 240.0, 80.0)
    received = []

    monkeypatch.setattr(
        recoverer.rust_adapter,
        "recover_native_region",
        lambda input_dto: received.append(input_dto) or {"candidate": "sentinel"},
    )

    result = recoverer._recover_native_region_from_snapshot_rust(snapshot, region)

    assert result == {"candidate": "sentinel"}
    assert len(received) == 1
    input_dto = received[0]
    assert input_dto["schema_version"] == 1
    assert input_dto["atoms"]
    assert len(input_dto["bands"]) >= 2
    assert input_dto["region"] == {
        "schema_version": 1,
        "rect": {
            "schema_version": 1,
            "x0": 0.0,
            "y0": 0.0,
            "x1": 240.0,
            "y1": 80.0,
        },
        "source_order": 0,
        "allowed": True,
    }
    assert input_dto["config"] == {
        "schema_version": 1,
        "line_tolerance": 2.0,
        "row_tolerance": 2.0,
        "column_tolerance": 2.0,
        "span_tolerance": 2.0,
        "numeric_tolerance": 2.0,
    }


def test_native_region_bridge_page_spy_success_uses_snapshot_without_page_text(
    monkeypatch,
):
    snapshot = _snapshot_for_rows(
        (
            ("项目", "金额"),
            ("甲", "10"),
            ("乙", "20"),
        )
    )

    class PageSpy:
        def __getattr__(self, name):
            return getattr(snapshot, name)

        def get_text(self, *args, **kwargs):
            raise AssertionError("bridge must not read page text")

    received = []
    monkeypatch.setattr(
        recoverer.rust_adapter,
        "recover_native_region",
        lambda input_dto: received.append(input_dto) or {"received": True},
    )

    result = recoverer._recover_native_region_from_snapshot_rust(
        PageSpy(), BBox(0.0, 0.0, 240.0, 80.0)
    )

    assert result == {"received": True}
    assert len(received) == 1
    assert len(received[0]["atoms"]) >= 4
    assert len(received[0]["bands"]) == 2


def test_native_region_bridge_atoms_and_bands_are_owned_and_keep_python_evidence(
    monkeypatch,
):
    snapshot = _snapshot_for_rows(
        (
            ("项目", "金额"),
            ("甲", "10"),
            ("乙", "20"),
        )
    )
    received = []
    monkeypatch.setattr(
        recoverer.rust_adapter,
        "recover_native_region",
        lambda input_dto: received.append(input_dto) or {"received": True},
    )

    recoverer._recover_native_region_from_snapshot_rust(
        snapshot, BBox(0.0, 0.0, 240.0, 80.0)
    )
    payload = received[0]

    atom_evidence = {
        "flow_start",
        "flow_end",
        "source_blocks",
        "source_line_start",
        "source_line_end",
        "source_position_known",
        "column_id",
    }
    for atom in payload["atoms"]:
        assert {
            "schema_version",
            "text",
            "rect",
            "run_refs",
            "row_hint",
            "col_hint",
            "order",
        } <= atom.keys()
        assert atom_evidence <= atom.keys()
        assert not {
            "bbox",
            "span_refs",
            "font",
            "font_size",
            "char_boxes",
        } & atom.keys()
        assert isinstance(atom["source_blocks"], list)
        assert all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in atom["source_blocks"]
        )

    for band in payload["bands"]:
        assert {
            "schema_version",
            "x0",
            "x1",
            "source_atoms",
            "order",
        } <= band.keys()
        assert {"id", "kind", "support", "y_support"} <= band.keys()
        assert all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in band["source_atoms"]
        )
        assert all(value >= 0 for value in band["source_atoms"])
        assert not {
            "bbox",
            "span_refs",
            "font",
            "font_size",
            "char_boxes",
        } & band.keys()


def test_native_region_preparation_keeps_python_atoms_separate_from_rust_payload(
    monkeypatch,
):
    raw_atom = {
        "candidate_label": "T1",
        "cell_id": "T1",
        "text": "项目",
        "bbox": [10.0, 10.0, 40.0, 20.0],
        "flow_start": 0,
        "flow_end": 0,
        "span_refs": ["S0"],
        "source_blocks": [14],
        "source_line_start": 0,
        "source_line_end": 0,
        "source_position_known": True,
        "font_size": 10.0,
        "bold": False,
        "script": "cjk",
        "column_id": 0,
        "source_position": [14, 0, 0],
    }
    raw_bands = [
        {"id": 1, "x0": 0.0, "x1": 100.0, "support": 1, "y_support": 1},
        {"id": 2, "x0": 100.0, "x1": 200.0, "support": 1, "y_support": 1},
    ]
    monkeypatch.setattr(recoverer, "build_text_runs", lambda spans, output_mode: [raw_atom])
    monkeypatch.setattr(recoverer, "infer_column_bands", lambda atoms, bbox: raw_bands)
    monkeypatch.setattr(
        recoverer, "prune_paired_cjk_artifact_bands", lambda atoms, bands: bands
    )
    monkeypatch.setattr(
        recoverer, "prune_sparse_alignment_artifact_bands", lambda atoms, bands: bands
    )
    monkeypatch.setattr(
        recoverer, "merge_same_band_native_line_runs", lambda atoms, bands: atoms
    )
    monkeypatch.setattr(recoverer, "refine_leaf_bands", lambda atoms, bands: (bands, None))
    monkeypatch.setattr(recoverer, "rescue_sparse_body_bands", lambda atoms, bands, cutoff: bands)
    monkeypatch.setattr(
        recoverer, "rescue_header_only_note_bands", lambda atoms, bands, cutoff: bands
    )
    monkeypatch.setattr(
        recoverer, "rescue_header_only_leaf_bands", lambda atoms, bands, cutoff: bands
    )
    monkeypatch.setattr(recoverer, "annotate_columns", lambda *args: None)

    prepared = recoverer._prepare_native_region_from_snapshot(
        _snapshot_for_rows((("项目", "金额"),)), BBox(0.0, 0.0, 240.0, 80.0)
    )

    assert prepared is not None
    assert prepared.python_atoms[0]["candidate_label"] == "T1"
    assert prepared.python_atoms[0]["cell_id"] == "T1"
    assert prepared.python_atoms[0]["font_size"] == 10.0
    assert prepared.python_atoms[0]["source_position"] == [14, 0, 0]
    assert "candidate_label" not in prepared.rust_input["atoms"][0]
    assert "cell_id" not in prepared.rust_input["atoms"][0]
    assert "font_size" not in prepared.rust_input["atoms"][0]
    assert "source_position" not in prepared.rust_input["atoms"][0]


def _native_region_payload_with_evidence():
    return {
        "schema_version": 1,
        "region": {
            "schema_version": 1,
            "rect": {
                "schema_version": 1,
                "x0": 0.0,
                "y0": 0.0,
                "x1": 200.0,
                "y1": 50.0,
            },
            "source_order": 0,
            "allowed": True,
        },
        "atoms": [
            {
                "schema_version": 1,
                "text": "项目",
                "rect": {
                    "schema_version": 1,
                    "x0": 10.0,
                    "y0": 10.0,
                    "x1": 60.0,
                    "y1": 20.0,
                },
                "run_refs": [0],
                "row_hint": 0,
                "col_hint": 0,
                "order": 0,
                "flow_start": 0,
                "flow_end": 0,
                "source_blocks": [14],
                "source_line_start": 3,
                "source_line_end": 3,
                "source_position_known": True,
                "column_id": 0,
            }
        ],
        "bands": [
            {
                "schema_version": 1,
                "x0": 0.0,
                "x1": 100.0,
                "source_atoms": [0],
                "order": 0,
                "id": 0,
                "kind": "body",
                "support": 3,
                "y_support": 3,
            }
        ],
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }


def test_native_region_roundtrip_preserves_python_evidence():
    payload = _native_region_payload_with_evidence()

    result = recoverer.rust_adapter.roundtrip_dto("native_region_input", payload)

    for field in (
        "flow_start",
        "flow_end",
        "source_blocks",
        "source_line_start",
        "source_line_end",
        "source_position_known",
        "column_id",
    ):
        assert result["atoms"][0][field] == payload["atoms"][0][field]
    for field in ("id", "kind", "support", "y_support"):
        assert result["bands"][0][field] == payload["bands"][0][field]


@pytest.mark.parametrize(
    ("mutate",),
    [
        (lambda payload: payload["atoms"][0].update({"flow_start": "0"}),),
        (lambda payload: payload["atoms"][0].update({"source_blocks": "14"}),),
        (
            lambda payload: payload["bands"][0].update({"kind": 7}),
        ),
        (
            lambda payload: payload["bands"][0].update({"source_atoms": [0, 1]}),
        ),
    ],
)
def test_native_region_roundtrip_rejects_invalid_or_misaligned_evidence(mutate):
    payload = _native_region_payload_with_evidence()
    mutate(payload)

    with pytest.raises(ValueError):
        recoverer.rust_adapter.roundtrip_dto("native_region_input", payload)


def test_native_region_builder_surfaces_malformed_snapshot_bbox():
    snapshot = _snapshot_for_rows(
        (
            ("项目", "金额"),
            ("甲", "10"),
            ("乙", "20"),
        )
    )
    block = dict(snapshot.text_blocks[0])
    line = dict(block["lines"][0])
    span = dict(line["spans"][0])
    span.pop("bbox")
    line["spans"] = (span, *line["spans"][1:])
    block["lines"] = (line, *block["lines"][1:])
    malformed = replace(snapshot, text_blocks=(block,))

    with pytest.raises((KeyError, ValueError, TypeError)):
        recoverer._build_native_region_input_from_snapshot(
            malformed, BBox(0.0, 0.0, 240.0, 80.0)
        )


def test_native_region_bridge_does_not_touch_page_spy(monkeypatch):
    class PageSpy:
        geometry = _snapshot_for_rows((("甲", "10"),)).geometry
        text_blocks = _snapshot_for_rows((("甲", "10"),)).text_blocks

        def get_text(self, *args, **kwargs):
            raise AssertionError("bridge must not read page text")

    spy = PageSpy()
    region = BBox(0.0, 0.0, 240.0, 80.0)
    monkeypatch.setattr(
        recoverer.rust_adapter,
        "recover_native_region",
        lambda input_dto: {"received": True},
    )

    assert recoverer._recover_native_region_from_snapshot_rust(spy, region) is None


def test_native_region_bridge_returns_none_without_text_or_stable_column_bands():
    region = BBox(0.0, 0.0, 240.0, 80.0)
    empty_snapshot = _snapshot_for_rows(())
    one_column_snapshot = _snapshot_for_rows((("项目",), ("甲",), ("乙",)))

    assert recoverer._build_native_region_input_from_snapshot(
        empty_snapshot, region
    ) is None
    assert recoverer._build_native_region_input_from_snapshot(
        one_column_snapshot, region
    ) is None


def test_native_region_builder_surfaces_malformed_empty_span_bbox(monkeypatch):
    malformed_span = NativeSpan(
        text="",
        bbox=BBox(float("nan"), 10.0, 20.0, 20.0),
        font="SimSun",
        size=10.0,
        order=0,
    )
    monkeypatch.setattr(
        recoverer,
        "collect_native_spans_from_snapshot",
        lambda *args, **kwargs: (malformed_span,),
    )

    with pytest.raises((ValueError, TypeError)):
        recoverer._build_native_region_input_from_snapshot(
            _snapshot_for_rows(()), BBox(0.0, 0.0, 240.0, 80.0)
        )


def test_native_region_builder_rejects_non_finite_region_rect():
    with pytest.raises((ValueError, TypeError)):
        recoverer._build_native_region_input_from_snapshot(
            _snapshot_for_rows((("项目", "金额"), ("甲", "10"))),
            BBox(float("nan"), 0.0, 240.0, 80.0),
        )
