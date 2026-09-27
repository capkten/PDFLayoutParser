from __future__ import annotations

from types import SimpleNamespace

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.table_extractor import TableExtractor


def _row(tokens):
    return {
        "tokens": tokens,
        "x0": min(token["x0"] for token in tokens),
        "y0": min(token["y0"] for token in tokens),
        "x1": max(token["x1"] for token in tokens),
        "y1": max(token["y1"] for token in tokens),
    }


def _token(x0, y0, x1, y1, text):
    return {
        "x0": float(x0),
        "y0": float(y0),
        "x1": float(x1),
        "y1": float(y1),
        "text": text,
        "is_numeric": text.replace(",", "").replace(".", "", 1).isdigit(),
    }


def test_text_alignment_grid_consumes_rust_owned_cells(monkeypatch):
    rows = [
        _row([_token(10, 10, 30, 20, "Label"), _token(110, 10, 140, 20, "100")]),
        _row([_token(10, 30, 30, 40, "Next"), _token(110, 30, 140, 40, "200")]),
    ]
    sentinel = [
        {
            "schema_version": 1,
            "text": "rust-grid",
            "row": 0,
            "col": 1,
            "rowspan": 1,
            "colspan": 1,
            "rect": {"x0": 100.0, "y0": 10.0, "x1": 150.0, "y1": 20.0},
            "source": None,
        }
    ]
    seen = {}

    def fake_build(input_dto):
        seen["input"] = input_dto
        return sentinel

    monkeypatch.setenv("PDF_RUST_MODE_TABLE_TEXT_ALIGNMENT", "rust")
    monkeypatch.setattr(rust_adapter, "build_general_wireless_cells", fake_build)

    rows_count, cols_count, cells = TableExtractor()._build_text_alignment_table(
        rows,
        [10.0, 100.0, 150.0],
        BBox(0.0, 0.0, 160.0, 50.0),
        page=SimpleNamespace(get_drawings=lambda: []),
    )

    assert (rows_count, cols_count) == (1, 2)
    assert [(cell.row_index, cell.col_index, cell.text) for cell in cells] == [
        (0, 1, "rust-grid")
    ]
    assert len(seen["input"]["atoms"]) == 4
    assert len(seen["input"]["bands"]) == 3


def test_text_alignment_grid_python_mode_does_not_call_rust(monkeypatch):
    monkeypatch.setenv("PDF_RUST_MODE_TABLE_TEXT_ALIGNMENT", "python")

    def fail(*args, **kwargs):
        raise AssertionError("Rust text grid must not run in python mode")

    monkeypatch.setattr(rust_adapter, "build_general_wireless_cells", fail)
    rows_count, cols_count, cells = TableExtractor()._build_text_alignment_table(
        [_row([_token(10, 10, 30, 20, "Label")])],
        [10.0, 100.0],
        BBox(0.0, 0.0, 120.0, 30.0),
    )

    assert (rows_count, cols_count) == (1, 1)
    assert cells[0].text == "Label"


def test_text_alignment_grid_rust_preserves_rows_and_column_assignments(monkeypatch):
    monkeypatch.setenv("PDF_RUST_MODE_TABLE_TEXT_ALIGNMENT", "rust")
    rows_count, cols_count, cells = TableExtractor()._build_text_alignment_table(
        [
            _row([_token(10, 10, 30, 20, "Label"), _token(110, 10, 140, 20, "100")]),
            _row([_token(10, 30, 30, 40, "Next"), _token(110, 30, 140, 40, "200")]),
        ],
        [10.0, 100.0, 150.0],
        BBox(0.0, 0.0, 160.0, 50.0),
    )

    assert (rows_count, cols_count) == (2, 3)
    assert [(cell.row_index, cell.col_index, cell.text) for cell in cells] == [
        (0, 0, "Label"),
        (0, 2, "100"),
        (1, 0, "Next"),
        (1, 2, "200"),
    ]


def test_text_alignment_grid_rejects_rust_rows_beyond_source_rows(monkeypatch):
    monkeypatch.setenv("PDF_RUST_MODE_TABLE_TEXT_ALIGNMENT", "rust")
    monkeypatch.setattr(
        rust_adapter,
        "build_general_wireless_cells",
        lambda input_dto: [
            {
                "schema_version": 1,
                "text": "first",
                "row": 1,
                "col": 0,
                "rowspan": 1,
                "colspan": 1,
                "rect": {"x0": 10.0, "y0": 30.0, "x1": 30.0, "y1": 40.0},
                "source": None,
            },
            {
                "schema_version": 1,
                "text": "later",
                "row": 2,
                "col": 1,
                "rowspan": 1,
                "colspan": 1,
                "rect": {"x0": 110.0, "y0": 50.0, "x1": 140.0, "y1": 60.0},
                "source": None,
            },
        ],
    )

    rows_count, cols_count, cells = TableExtractor()._build_text_alignment_table(
        [
            _row([_token(10, 10, 30, 20, "header")]),
            _row([_token(10, 30, 30, 40, "first")]),
        ],
        [10.0, 100.0, 150.0],
        BBox(0.0, 0.0, 160.0, 70.0),
    )

    assert (rows_count, cols_count) == (3, 2)
    assert [cell.text for cell in cells] == ["first", "later"]
