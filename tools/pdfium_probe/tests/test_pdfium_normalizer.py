import os
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
from pdfium_normalizer import NormalizedPage, normalize_raw_page, normalize_raw_snapshot


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
