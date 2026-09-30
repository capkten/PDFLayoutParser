import json
import os
import subprocess
import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from typing import Any, Dict, List, Optional
import pytest

from hexai_pdf_parser import rust_adapter
from fixtures_normalizer import make_raw_page, make_span
from pdfium_normalizer import (
    NormalizedPage,
    normalize_from_rust_dto,
    normalize_raw_page,
    normalize_raw_snapshot,
    normalize_with_rust_probe,
)


def test_one_object_becomes_one_block_line_span() -> None:
    page = normalize_raw_page(make_raw_page([make_span("Hello", 0, 10, 50, 20)]))
    assert page.page_type == "vector"
    assert page.page_snapshot is not None
    assert page.page_snapshot["text_blocks"][0]["lines"][0]["spans"][0]["text"] == "Hello"


def test_same_baseline_is_sorted_by_x() -> None:
    page = normalize_raw_page(
        make_raw_page(
            [
                make_span("right", 50, 10, 80, 20, order=0),
                make_span("left", 0, 10, 30, 20, order=1),
            ]
        )
    )
    assert page.page_snapshot is not None
    spans = page.page_snapshot["text_blocks"][0]["lines"][0]["spans"]
    assert [item["text"] for item in spans] == ["left", "right"]


def test_different_baselines_create_two_lines() -> None:
    page = normalize_raw_page(
        make_raw_page(
            [
                make_span("A", 0, 10, 10, 20),
                make_span("B", 0, 30, 10, 40),
            ]
        )
    )
    assert page.page_snapshot is not None
    assert len(page.page_snapshot["text_blocks"][0]["lines"]) == 2


def test_words_are_derived_from_normalized_chars() -> None:
    page = normalize_raw_page(make_raw_page([make_span("Hello world", 0, 10, 70, 20)]))
    assert [item[4] for item in page.words] == ["Hello", "world"]


def test_scanned_page_has_no_text_views() -> None:
    page = normalize_raw_page(make_raw_page([make_span("坏\ufffd字", 0, 10, 30, 20)]))
    assert page.page_type == "scanned"
    assert page.page_snapshot is None
    assert page.rawdict is None
    assert page.words == []


def test_rawdict_contract_and_distinction_from_snapshot() -> None:
    page = normalize_raw_page(make_raw_page([make_span("Sample", 10, 20, 60, 30)]))
    assert page.rawdict is not None
    assert "blocks" in page.rawdict
    raw_block = page.rawdict["blocks"][0]
    assert "bbox" in raw_block
    assert "rect" not in raw_block
    raw_line = raw_block["lines"][0]
    assert "bbox" in raw_line
    raw_span = raw_line["spans"][0]
    assert raw_span["text"] == "Sample"
    assert "bbox" in raw_span
    assert "chars" in raw_span
    assert raw_span["chars"][0]["c"] == "S"
    assert "bbox" in raw_span["chars"][0]

    # Verify wire snapshot uses rect / characters / text
    assert page.page_snapshot is not None
    snap_block = page.page_snapshot["text_blocks"][0]
    assert "rect" in snap_block
    assert "bbox" not in snap_block
    snap_span = snap_block["lines"][0]["spans"][0]
    assert "rect" in snap_span
    assert "characters" in snap_span
    assert snap_span["characters"][0]["text"] == "S"
    assert "rect" in snap_span["characters"][0]
    assert "raw_source_position" in snap_span["characters"][0]
    assert len(snap_span["characters"][0]["raw_source_position"]) >= 4


def test_rust_adapter_digest_and_collect_native_spans() -> None:
    raw_page = make_raw_page(
        [
            make_span("Heading", 10, 10, 60, 20, order=0),
            make_span("Value 1", 10, 30, 50, 40, order=1),
            make_span("Value 2", 70, 30, 110, 40, order=2),
        ]
    )
    norm = normalize_raw_page(raw_page)
    dto = norm.page_snapshot
    assert dto is not None

    digest = rust_adapter.page_snapshot_digest(dto)
    assert isinstance(digest, str)
    assert len(digest) == 64

    spans = rust_adapter.collect_native_spans_from_snapshot(dto)
    assert len(spans) == 3
    assert [s.text for s in spans] == ["Heading", "Value 1", "Value 2"]


def test_word_tuples_eight_elements_and_block_line_indices() -> None:
    page = normalize_raw_page(
        make_raw_page(
            [
                make_span("First line", 0, 10, 80, 20),
                make_span("Second line", 0, 30, 90, 40),
            ]
        )
    )
    words = page.words
    assert len(words) == 4
    for w in words:
        assert len(w) == 8
        x0, y0, x1, y1, text, b_idx, l_idx, w_idx = w
        assert isinstance(x0, float)
        assert isinstance(y0, float)
        assert isinstance(x1, float)
        assert isinstance(y1, float)
        assert isinstance(text, str)
        assert isinstance(b_idx, int)
        assert isinstance(l_idx, int)
        assert isinstance(w_idx, int)

    assert words[0][4] == "First"
    assert words[0][5] == 0
    assert words[0][6] == 0
    assert words[1][4] == "line"
    assert words[1][5] == 0
    assert words[1][6] == 0

    assert words[2][4] == "Second"
    assert words[2][5] == 0
    assert words[2][6] == 1
    assert words[3][4] == "line"
    assert words[3][5] == 0
    assert words[3][6] == 1


def test_word_snapshot_mappings_have_required_fields() -> None:
    page = normalize_raw_page(make_raw_page([make_span("Test 123", 0, 10, 50, 20)]))
    assert page.page_snapshot is not None
    snap_words = page.page_snapshot["words"]
    assert len(snap_words) == 2
    for sw in snap_words:
        assert sw["schema_version"] == 1
        assert "text" in sw
        assert "rect" in sw
        assert "order" in sw
        assert "block" in sw
        assert "line" in sw
        assert "raw_source_position" in sw
        assert len(sw["raw_source_position"]) >= 4


def test_normalize_raw_snapshot_multiple_pages() -> None:
    page1 = make_raw_page([make_span("Page 1", 0, 10, 50, 20)])
    page1["page_index"] = 0
    page2 = make_raw_page([make_span("Page 2", 0, 10, 50, 20)])
    page2["page_index"] = 1
    snapshot = {
        "schema_version": "pdfium_raw_snapshot_v1.0",
        "page_count": 2,
        "pages": [page1, page2],
    }
    normalized = normalize_raw_snapshot(snapshot)
    assert len(normalized) == 2
    assert normalized[0].page_snapshot["page_index"] == 0
    assert normalized[1].page_snapshot["page_index"] == 1


def test_numeric_continuity_negative_and_thousands() -> None:
    page = normalize_raw_page(
        make_raw_page(
            [
                make_span("-12.34", 0, 10, 50, 20, order=0),
                make_span("1,000", 60, 10, 100, 20, order=1),
                make_span("1,000.50", 110, 10, 160, 20, order=2),
                make_span("-50%", 170, 10, 200, 20, order=3),
            ]
        )
    )
    words = [w[4] for w in page.words]
    assert words == ["-12.34", "1,000", "1,000.50", "-50%"]


def test_merged_span_preserves_character_provenance() -> None:
    span_a = make_span("A", 0, 10, 8, 20, order=10)
    span_a["provenance"] = {
        "pdfium_object_index": 10,
        "char_start_index": 0,
        "char_end_index": 1,
    }
    span_b = make_span("B", 9, 10, 17, 20, order=20)
    span_b["provenance"] = {
        "pdfium_object_index": 20,
        "char_start_index": 0,
        "char_end_index": 1,
    }

    page = normalize_raw_page(make_raw_page([span_a, span_b]))
    assert page.page_snapshot is not None
    spans = page.page_snapshot["text_blocks"][0]["lines"][0]["spans"]
    assert len(spans) == 1
    merged = spans[0]
    assert merged["text"] == "AB"
    assert len(merged["characters"]) == 2

    # Character 0 must retain original object index 10
    char_0 = merged["characters"][0]
    assert char_0["text"] == "A"
    assert char_0["raw_source_position"] == [0, 10, 0, 0]

    # Character 1 must retain original object index 20
    char_1 = merged["characters"][1]
    assert char_1["text"] == "B"
    assert char_1["raw_source_position"] == [0, 20, 0, 0]

    # Word must also span the characters
    assert len(page.page_snapshot["words"]) == 1
    word_0 = page.page_snapshot["words"][0]
    assert word_0["text"] == "AB"
    assert word_0["raw_source_position"] == [0, 10, 0, 0]


def test_rawdict_bbox_tuples_and_rust_rawdict_collector() -> None:
    page = normalize_raw_page(make_raw_page([make_span("Hello", 10, 20, 50, 30)]))
    rawdict = page.rawdict
    assert rawdict is not None

    block = rawdict["blocks"][0]
    assert isinstance(block["bbox"], tuple)
    assert len(block["bbox"]) == 4

    line = block["lines"][0]
    assert isinstance(line["bbox"], tuple)
    assert len(line["bbox"]) == 4

    span = line["spans"][0]
    assert isinstance(span["bbox"], tuple)
    assert len(span["bbox"]) == 4

    char = span["chars"][0]
    assert isinstance(char["bbox"], tuple)
    assert len(char["bbox"]) == 4

    # Test that rust_adapter.collect_native_spans_from_rawdict succeeds and extracts spans
    rust_spans = rust_adapter.collect_native_spans_from_rawdict(rawdict, 100.0, 0.0)
    assert len(rust_spans) == 1
    assert rust_spans[0].text == "Hello"


def test_dto_block_and_line_order_and_source_order() -> None:
    page = normalize_raw_page(
        make_raw_page(
            [
                make_span("L1", 0, 10, 20, 20),
                make_span("L2", 0, 30, 20, 40),
            ]
        )
    )
    assert page.page_snapshot is not None
    block = page.page_snapshot["text_blocks"][0]
    assert block["order"] == 0
    assert block["source_order"] == 0

    lines = block["lines"]
    assert lines[0]["order"] == 0
    assert lines[0]["source_order"] == 0
    assert lines[1]["order"] == 1
    assert lines[1]["source_order"] == 1


def test_rust_probe_normalize_cli_and_dto_parity(tmp_path: Path) -> None:
    from pdfium_normalizer import _find_pdfium_probe_bin
    probe_bin_str = _find_pdfium_probe_bin()
    assert probe_bin_str is not None, "pdfium_probe binary not found"
    probe_bin = Path(probe_bin_str)

    probe_root = _TEST_DIR.parent
    synth_pdf = probe_root / "test_data" / "synthetic" / "synth_crop_offset.pdf"
    assert synth_pdf.is_file(), f"Synthetic test PDF not found: {synth_pdf}"

    out_json = tmp_path / "synth_crop_offset_norm.json"
    cmd = [
        str(probe_bin),
        "normalize",
        str(synth_pdf),
        "0",
        str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, f"CLI normalize failed: {res.stderr}"
    assert out_json.is_file()

    with open(out_json, "r", encoding="utf-8") as f:
        rust_dto = json.load(f)

    norm_page = normalize_from_rust_dto(rust_dto)
    assert norm_page.page_type == "vector"
    assert norm_page.page_snapshot is not None
    assert norm_page.rawdict is not None
    assert len(norm_page.words) > 0

    digest = rust_adapter.page_snapshot_digest(norm_page.page_snapshot)
    assert isinstance(digest, str)
    assert len(digest) == 64

    snap_spans = rust_adapter.collect_native_spans_from_snapshot(norm_page.page_snapshot)
    assert len(snap_spans) == 3
    assert [s.text for s in snap_spans] == [
        "Outside of CropBox",
        "Header in CropBox",
        "Normal Body Text",
    ]

    raw_spans = rust_adapter.collect_native_spans_from_rawdict(norm_page.rawdict, 100.0, 0.0)
    assert len(raw_spans) == 3
    assert [s.text for s in raw_spans] == [
        "Outside of CropBox",
        "Header in CropBox",
        "Normal Body Text",
    ]

    raw_snapshot_path = probe_root / "test_data" / "pdfium_output" / "synth_crop_offset_pdfium.json"
    assert raw_snapshot_path.is_file(), f"Raw snapshot file not found: {raw_snapshot_path}"
    with open(raw_snapshot_path, "r", encoding="utf-8") as f:
        raw_page = json.load(f)["pages"][0]

    py_norm = normalize_raw_page(raw_page)
    assert py_norm.page_type == norm_page.page_type
    assert py_norm.words == norm_page.words
    assert len(py_norm.page_snapshot["text_blocks"]) == len(norm_page.page_snapshot["text_blocks"])
    assert len(py_norm.page_snapshot["spans"]) == len(norm_page.page_snapshot["spans"])
    assert len(py_norm.page_snapshot["words"]) == len(norm_page.page_snapshot["words"])
    assert len(py_norm.rawdict["blocks"]) == len(norm_page.rawdict["blocks"])

    py_digest = rust_adapter.page_snapshot_digest(py_norm.page_snapshot)
    assert py_digest == digest, f"Digest mismatch: py={py_digest} vs rust={digest}"

    py_snap_spans = rust_adapter.collect_native_spans_from_snapshot(py_norm.page_snapshot)
    assert [s.text for s in py_snap_spans] == [s.text for s in snap_spans]

    py_raw_spans = rust_adapter.collect_native_spans_from_rawdict(py_norm.rawdict, 100.0, 0.0)
    assert [s.text for s in py_raw_spans] == [s.text for s in raw_spans]

    probe_norm = normalize_with_rust_probe(raw_page, pdf_path=str(synth_pdf))
    assert probe_norm is not None
    assert rust_adapter.page_snapshot_digest(probe_norm.page_snapshot) == digest
