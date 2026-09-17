# -*- coding: utf-8 -*-
"""Sprint 009: Test suite for English zebra, general wireless, and legacy algorithms in Rust."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hexai_pdf_parser import rust_adapter


@pytest.fixture
def sample_fixture_page():
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "rust_migration" / "english" / "english_wireless.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["pages"][0]


def test_roundtrip_all_english_dtos():
    """Verify that all Sprint 009 DTO types roundtrip properly through Rust FFI."""
    cfg = {
        "schema_version": 1,
        "line_tolerance": 2.0,
        "row_tolerance": 2.0,
        "column_tolerance": 2.0,
        "span_tolerance": 2.0,
        "numeric_tolerance": 2.0,
    }
    reg = {
        "schema_version": 1,
        "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 200.0},
        "source_order": 0,
        "allowed": True,
    }

    z_in = rust_adapter.roundtrip_dto("zebra_input", {
        "schema_version": 1,
        "page": {"schema_version": 1, "width": 100.0, "height": 200.0, "rotation": 0},
        "backgrounds": [],
        "words": [],
        "region": reg,
        "config": cfg,
    })
    assert z_in["schema_version"] == 1

    eg_in = rust_adapter.roundtrip_dto("english_grid_input", {
        "schema_version": 1,
        "region": reg,
        "words": [],
        "backgrounds": [],
        "config": cfg,
    })
    assert eg_in["schema_version"] == 1

    gw_in = rust_adapter.roundtrip_dto("general_wireless_input", {
        "schema_version": 1,
        "region": reg,
        "atoms": [],
        "bands": [],
        "config": cfg,
    })
    assert gw_in["schema_version"] == 1

    la_in = rust_adapter.roundtrip_dto("legacy_alignment_input", {
        "schema_version": 1,
        "region": reg,
        "words": [],
        "config": cfg,
    })
    assert la_in["schema_version"] == 1


def test_group_backgrounds(sample_fixture_page):
    """Test grouping background bands separated by gaps > 30pt."""
    backgrounds = sample_fixture_page["backgrounds"]
    groups = rust_adapter.group_backgrounds(backgrounds, gap_threshold=30.0)

    assert len(groups) == 2
    assert len(groups[0]) == 5
    assert len(groups[1]) == 2


def test_detect_zebra_rows(sample_fixture_page):
    """Test detecting zebra rows and filling white background bands."""
    input_dto = {
        "schema_version": 1,
        "page": sample_fixture_page["page"],
        "backgrounds": sample_fixture_page["backgrounds"],
        "words": sample_fixture_page["words"],
        "region": sample_fixture_page["region"],
        "config": sample_fixture_page["config"],
    }
    rows = rust_adapter.detect_zebra_rows(input_dto)
    assert len(rows) >= 5
    for i, r in enumerate(rows):
        assert r["row_index"] == i
        assert r["rect"]["y0"] < r["rect"]["y1"]


def test_assign_words_to_zebra_rows(sample_fixture_page):
    """Test assigning words to zebra rows and clustering unassigned words into physical rows."""
    input_dto = {
        "schema_version": 1,
        "page": sample_fixture_page["page"],
        "backgrounds": sample_fixture_page["backgrounds"],
        "words": sample_fixture_page["words"],
        "region": sample_fixture_page["region"],
        "config": sample_fixture_page["config"],
    }
    rows = rust_adapter.detect_zebra_rows(input_dto)
    assigned_rows = rust_adapter.assign_words_to_zebra_rows(
        words=sample_fixture_page["words"],
        rows=rows,
        row_tol=2.0,
    )
    assert len(assigned_rows) >= len(rows)

    total_assigned_words = sum(len(r["words"]) for r in assigned_rows)
    assert total_assigned_words == len(sample_fixture_page["words"])

    total_row = next((r for r in assigned_rows if any(w["text"] == "Total" for w in r["words"])), None)
    assert total_row is not None
    assert any(w["text"] == "2,050" for w in total_row["words"])


def test_infer_english_columns(sample_fixture_page):
    """Test inferring column bands with currency boundary alignment."""
    input_dto = {
        "schema_version": 1,
        "region": sample_fixture_page["region"],
        "words": sample_fixture_page["words"],
        "backgrounds": sample_fixture_page["backgrounds"],
        "config": sample_fixture_page["config"],
    }
    cols = rust_adapter.infer_english_columns(input_dto)
    assert len(cols) >= 3
    assert cols[0]["x1"] <= 335.0


def test_build_english_cells(sample_fixture_page):
    """Test building complete 2D cell grid for English table."""
    input_dto = {
        "schema_version": 1,
        "region": sample_fixture_page["region"],
        "words": sample_fixture_page["words"],
        "backgrounds": sample_fixture_page["backgrounds"],
        "config": sample_fixture_page["config"],
    }
    cells = rust_adapter.build_english_cells(input_dto)
    assert len(cells) > 0

    for c in cells:
        assert c["row"] >= 0
        assert c["col"] >= 0
        assert c["rowspan"] >= 1
        assert c["colspan"] >= 1


def test_build_general_wireless_cells():
    """Test building general wireless cells from atoms and bands."""
    atoms = [
        {"schema_version": 1, "text": "Item", "rect": {"schema_version": 1, "x0": 10.0, "y0": 10.0, "x1": 50.0, "y1": 20.0}, "run_refs": [0], "row_hint": None, "col_hint": None, "order": 0},
        {"schema_version": 1, "text": "Amount", "rect": {"schema_version": 1, "x0": 100.0, "y0": 10.0, "x1": 150.0, "y1": 20.0}, "run_refs": [1], "row_hint": None, "col_hint": None, "order": 1},
        {"schema_version": 1, "text": "Sales", "rect": {"schema_version": 1, "x0": 10.0, "y0": 30.0, "x1": 50.0, "y1": 40.0}, "run_refs": [2], "row_hint": None, "col_hint": None, "order": 2},
        {"schema_version": 1, "text": "1000", "rect": {"schema_version": 1, "x0": 100.0, "y0": 30.0, "x1": 140.0, "y1": 40.0}, "run_refs": [3], "row_hint": None, "col_hint": None, "order": 3},
    ]
    bands = [
        {"schema_version": 1, "x0": 10.0, "x1": 60.0, "source_atoms": [0, 2], "order": 0},
        {"schema_version": 1, "x0": 90.0, "x1": 160.0, "source_atoms": [1, 3], "order": 1},
    ]
    input_dto = {
        "schema_version": 1,
        "region": {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 200.0, "y1": 50.0},
            "source_order": 0,
            "allowed": True,
        },
        "atoms": atoms,
        "bands": bands,
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }
    cells = rust_adapter.build_general_wireless_cells(input_dto)
    assert len(cells) == 4
    texts = [c["text"] for c in cells]
    assert "Item" in texts
    assert "Amount" in texts
    assert "Sales" in texts
    assert "1000" in texts


def test_build_legacy_text_alignment():
    """Test legacy text alignment reconstruction with group header."""
    words = [
        {"schema_version": 1, "text": "本年金额", "rect": {"schema_version": 1, "x0": 100.0, "y0": 10.0, "x1": 200.0, "y1": 20.0}, "order": 0, "block": 0, "line": 0},
        {"schema_version": 1, "text": "项目", "rect": {"schema_version": 1, "x0": 10.0, "y0": 30.0, "x1": 40.0, "y1": 40.0}, "order": 1, "block": 0, "line": 1},
        {"schema_version": 1, "text": "收入", "rect": {"schema_version": 1, "x0": 100.0, "y0": 30.0, "x1": 130.0, "y1": 40.0}, "order": 2, "block": 0, "line": 1},
        {"schema_version": 1, "text": "支出", "rect": {"schema_version": 1, "x0": 160.0, "y0": 30.0, "x1": 190.0, "y1": 40.0}, "order": 3, "block": 0, "line": 1},
        {"schema_version": 1, "text": "小计", "rect": {"schema_version": 1, "x0": 10.0, "y0": 50.0, "x1": 40.0, "y1": 60.0}, "order": 4, "block": 0, "line": 2},
        {"schema_version": 1, "text": "500", "rect": {"schema_version": 1, "x0": 100.0, "y0": 50.0, "x1": 125.0, "y1": 60.0}, "order": 5, "block": 0, "line": 2},
        {"schema_version": 1, "text": "300", "rect": {"schema_version": 1, "x0": 160.0, "y0": 50.0, "x1": 185.0, "y1": 60.0}, "order": 6, "block": 0, "line": 2},
    ]
    input_dto = {
        "schema_version": 1,
        "region": {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 250.0, "y1": 70.0},
            "source_order": 0,
            "allowed": True,
        },
        "words": words,
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }
    cells = rust_adapter.build_legacy_text_alignment(input_dto)
    assert len(cells) > 0

    group_cell = next((c for c in cells if "本年金额" in c["text"]), None)
    assert group_cell is not None
    assert group_cell["colspan"] >= 2
