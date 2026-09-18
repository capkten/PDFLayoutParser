# -*- coding: utf-8 -*-
"""Sprint 009: Test suite for English zebra, general wireless, and legacy algorithms in Rust."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hexai_pdf_parser import rust_adapter


def _english_word(x0, y0, x1, y1, text):
    return (float(x0), float(y0), float(x1), float(y1), text)


def _english_row(words, y0, y1, is_header):
    from hexai_pdf_parser.tables.extractors.english_table_extractor import _RowData

    return _RowData(words=words, y0=y0, y1=y1, color=None, is_header=is_header)


def _english_cell_dto(text, row, col, x0, y0, x1, y1, rowspan=1, colspan=1):
    return {
        "schema_version": 1,
        "text": text,
        "row": row,
        "col": col,
        "rect": {
            "schema_version": 1,
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
        },
        "rowspan": rowspan,
        "colspan": colspan,
        "source": None,
    }


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


def test_detect_columns_routes_edge_geometry_to_rust_owned_dto(monkeypatch):
    """Currency, percentage, empty-gap, and boundary-overlap rules belong to Rust."""
    from hexai_pdf_parser.core.models import BBox
    from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor

    words = [
        _english_word(10, 10, 42, 20, "Revenue"),
        _english_word(82, 10, 104, 20, "12%"),
        _english_word(158, 10, 163, 20, "$"),
        _english_word(166, 10, 202, 20, "1,000"),
        _english_word(10, 30, 45, 40, "Margin"),
        _english_word(82, 30, 105, 40, "8%"),
        _english_word(158, 30, 163, 40, "$"),
        _english_word(166, 30, 202, 40, "900"),
    ]
    expected = [
        {"schema_version": 1, "x0": 0.0, "x1": 70.0, "source_atoms": [], "order": 0},
        {"schema_version": 1, "x0": 70.0, "x1": 140.0, "source_atoms": [], "order": 1},
        {"schema_version": 1, "x0": 140.0, "x1": 220.0, "source_atoms": [], "order": 2},
        {"schema_version": 1, "x0": 220.0, "x1": 300.0, "source_atoms": [], "order": 3},
    ]
    seen = {}

    def fake_infer(input_dto):
        seen["input"] = input_dto
        return expected

    monkeypatch.setenv("PDF_RUST_MODE_ENGLISH_WIRELESS", "rust")
    monkeypatch.setattr(rust_adapter, "infer_english_columns", fake_infer)

    columns = EnglishTableExtractor()._detect_columns(
        words=words,
        data_rows=[],
        page=SimpleNamespace(get_drawings=lambda: []),
        table_y0=0.0,
        table_bbox=BBox(0.0, 0.0, 300.0, 50.0),
    )

    assert columns == [(0.0, 70.0), (70.0, 140.0), (140.0, 220.0), (220.0, 300.0)]
    assert [word["text"] for word in seen["input"]["words"]] == [word[4] for word in words]
    assert seen["input"]["region"]["rect"] == {
        "schema_version": 1,
        "x0": 0.0,
        "y0": 0.0,
        "x1": 300.0,
        "y1": 50.0,
    }


def test_english_grid_input_collects_visible_horizontal_lines():
    """可见长水平线必须作为 Rust 行边界吸附输入，白色/过短线不能进入 DTO。"""
    from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor

    point = lambda x=0.0, y=0.0: SimpleNamespace(x=x, y=y)
    rect = lambda x0, y0, x1, y1: SimpleNamespace(
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        width=x1 - x0,
        height=y1 - y0,
    )
    drawings = [
        {
            "fill": None,
            "color": (0.0, 0.0, 0.0),
            "items": [("l", point(0.0, 10.0), point(100.0, 10.0))],
        },
        {
            "fill": None,
            "color": (0.0, 0.0, 0.0),
            "items": [("re", rect(0.0, 20.0, 100.0, 21.0))],
        },
        {
            "fill": (1.0, 1.0, 1.0),
            "color": None,
            "items": [("l", point(0.0, 30.0), point(100.0, 30.0))],
        },
        {
            "fill": None,
            "color": (0.0, 0.0, 0.0),
            "items": [("l", point(0.0, 40.0), point(10.0, 40.0))],
        },
    ]

    lines = EnglishTableExtractor._english_horizontal_lines(
        SimpleNamespace(get_drawings=lambda: drawings)
    )

    assert lines == [10.0, 20.5]


def test_build_wireless_table_consumes_rust_cells_for_headers_rowspan_and_empty_slots(monkeypatch):
    """Rust Cell DTOs define multi-level headers, spans, and explicit empty slots."""
    from hexai_pdf_parser.core.models import BBox
    from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor

    header_rows = [
        _english_row([_english_word(0, 0, 35, 10, "Item"), _english_word(80, 0, 200, 10, "Portfolio")], 0.0, 10.0, True),
        _english_row([_english_word(80, 15, 120, 25, "Amount"), _english_word(160, 15, 195, 25, "Rate")], 15.0, 25.0, True),
    ]
    data_rows = [
        _english_row([_english_word(0, 30, 35, 40, "Alpha"), _english_word(80, 30, 125, 40, "$100")], 30.0, 40.0, False),
    ]
    rust_cells = [
        _english_cell_dto("Item", 0, 0, 0, 0, 80, 25, rowspan=2),
        _english_cell_dto("Portfolio", 0, 1, 80, 0, 300, 15, colspan=2),
        _english_cell_dto("Amount", 1, 1, 80, 15, 160, 25),
        _english_cell_dto("Rate", 1, 2, 160, 15, 300, 25),
        _english_cell_dto("Alpha", 2, 0, 0, 30, 80, 40),
        _english_cell_dto("$100", 2, 1, 80, 30, 160, 40),
        _english_cell_dto("", 2, 2, 160, 30, 300, 40),
    ]
    seen = {}

    def fake_build(input_dto):
        seen["input"] = input_dto
        return rust_cells

    monkeypatch.setenv("PDF_RUST_MODE_ENGLISH_WIRELESS", "rust")
    monkeypatch.setattr(rust_adapter, "build_english_cells", fake_build)

    table = EnglishTableExtractor()._build_wireless_table(
        header_rows=header_rows,
        data_rows=data_rows,
        columns=[(0.0, 80.0), (80.0, 160.0), (160.0, 300.0)],
        table_bbox=BBox(0.0, 0.0, 300.0, 40.0),
        page=SimpleNamespace(get_drawings=lambda: []),
        source="english_general_wireless",
    )

    assert table is not None
    assert (table.rows, table.cols) == (3, 3)
    assert [(cell.row_index, cell.col_index, cell.text, cell.rowspan, cell.colspan) for cell in table.cells] == [
        (0, 0, "Item", 2, 1),
        (0, 1, "Portfolio", 1, 2),
        (1, 1, "Amount", 1, 1),
        (1, 2, "Rate", 1, 1),
        (2, 0, "Alpha", 1, 1),
        (2, 1, "$100", 1, 1),
        (2, 2, "", 1, 1),
    ]
    assert len(seen["input"]["words"]) == 6
    assert len(seen["input"]["backgrounds"]) == 3
    assert seen["input"]["horizontal_lines"] == []


def test_group_into_tables_routes_adjacent_backgrounds_through_unified_rust_path(monkeypatch):
    """Two separated background groups remain two tables when Rust is primary."""
    from hexai_pdf_parser.tables.extractors.english_table_extractor import EnglishTableExtractor

    calls = []

    def fake_route(mode, python_fn, rust_fn, input_dto=None, path=""):
        calls.append(path)
        return rust_fn(input_dto)

    monkeypatch.setenv("PDF_RUST_MODE_ENGLISH_WIRELESS", "rust")
    monkeypatch.setattr(rust_adapter, "run_python_or_rust", fake_route)
    monkeypatch.setattr(
        rust_adapter,
        "group_backgrounds",
        lambda backgrounds, gap_threshold: [
            [
                {"rect": {"y0": 0.0, "y1": 10.0}, "color": 0.5},
                {"rect": {"y0": 10.0, "y1": 20.0}, "color": 1.0},
            ],
            [
                {"rect": {"y0": 80.0, "y1": 90.0}, "color": 0.5},
                {"rect": {"y0": 90.0, "y1": 100.0}, "color": 1.0},
            ],
        ],
    )

    groups = EnglishTableExtractor()._group_into_tables(
        [(0.0, 10.0, "colored"), (10.0, 20.0, "white"), (80.0, 90.0, "colored"), (90.0, 100.0, "white")]
    )

    assert len(groups) == 2
    assert calls == ["english-wireless/background-groups"]


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
