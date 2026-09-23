"""Tests for unified owned DTOs across the Rust FFI boundary."""

import math
import pytest
from hexai_pdf_parser.rust_adapter import roundtrip_dto


def test_page_dto_roundtrip_normal():
    data = {
        "schema_version": 1,
        "width": 595.0,
        "height": 842.0,
        "rotation": 90,
    }
    result = roundtrip_dto("page", data)
    assert result == data


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_page_dto_rotation_valid(rotation):
    data = {
        "schema_version": 1,
        "width": 100.0,
        "height": 200.0,
        "rotation": rotation,
    }
    assert roundtrip_dto("page", data)["rotation"] == rotation


def test_page_dto_rotation_invalid():
    data = {
        "schema_version": 1,
        "width": 100.0,
        "height": 200.0,
        "rotation": 45,
    }
    with pytest.raises(ValueError, match=r"rotation"):
        roundtrip_dto("page", data)


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf")])
def test_page_dto_rejects_nan_inf(bad_val):
    data = {
        "schema_version": 1,
        "width": bad_val,
        "height": 200.0,
        "rotation": 0,
    }
    with pytest.raises(ValueError, match=r"(?i)nan|inf"):
        roundtrip_dto("page", data)


def test_rect4_roundtrip_negative_coords():
    data = {
        "schema_version": 1,
        "x0": -10.5,
        "y0": -20.0,
        "x1": 100.0,
        "y1": 200.0,
    }
    result = roundtrip_dto("rect", data)
    assert result == data


def test_rect4_rejects_nan():
    data = {
        "schema_version": 1,
        "x0": float("nan"),
        "y0": 0.0,
        "x1": 10.0,
        "y1": 10.0,
    }
    with pytest.raises(ValueError, match=r"(?i)nan|inf"):
        roundtrip_dto("rect", data)


def test_native_span_dto_roundtrip_cjk_and_characters():
    data = {
        "schema_version": 1,
        "text": "测试中文",
        "rect": {
            "schema_version": 1,
            "x0": 10.0,
            "y0": 20.0,
            "x1": 80.0,
            "y1": 35.0,
        },
        "font": "SimSun",
        "size": 12.0,
        "flags": 4,
        "order": 0,
        "characters": [
            {
                "schema_version": 1,
                "text": "测",
                "rect": {"schema_version": 1, "x0": 10.0, "y0": 20.0, "x1": 25.0, "y1": 35.0},
                "order": 0,
            },
            {
                "schema_version": 1,
                "text": "试",
                "rect": {"schema_version": 1, "x0": 25.0, "y0": 20.0, "x1": 40.0, "y1": 35.0},
                "order": 1,
            },
        ],
        "source_position": {
            "schema_version": 1,
            "block": 1,
            "line": 2,
        },
        "block": 1,
        "line": 2,
    }
    result = roundtrip_dto("native_span", data)
    assert result == data


def test_native_span_dto_optional_fields_null():
    data = {
        "schema_version": 1,
        "text": "",
        "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0},
        "font": None,
        "size": None,
        "flags": None,
        "order": 0,
        "characters": [],
        "source_position": {"schema_version": 1, "block": 0, "line": 0},
        "block": 0,
        "line": 0,
    }
    result = roundtrip_dto("native_span", data)
    assert result["font"] is None
    assert result["size"] is None
    assert result["flags"] is None
    assert result["characters"] == []


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
    assert roundtrip_dto("text_run", data) == data


def test_cell_and_logical_grid_roundtrip_empty_slots():
    data = {
        "schema_version": 1,
        "grid": {
            "schema_version": 1,
            "rows": 2,
            "cols": 2,
            "row_edges": [0.0, 50.0, 100.0],
            "col_edges": [0.0, 50.0, 100.0],
            "occupancy": [[0, None], [None, 1]],
        },
        "cells": [
            {
                "schema_version": 1,
                "text": "Cell 0,0",
                "row": 0,
                "col": 0,
                "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 50.0},
                "rowspan": 1,
                "colspan": 1,
                "source": {
                    "schema_version": 1,
                    "text": "Cell 0,0",
                    "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 50.0},
                    "row": 0,
                    "col": 0,
                    "source_refs": [0, 1],
                },
            },
            {
                "schema_version": 1,
                "text": "Cell 1,1",
                "row": 1,
                "col": 1,
                "rect": {"schema_version": 1, "x0": 50.0, "y0": 50.0, "x1": 100.0, "y1": 100.0},
                "rowspan": 1,
                "colspan": 1,
                "source": None,
            },
        ],
        "empty_slots": [[0, 1], [1, 0]],
    }
    result = roundtrip_dto("logical_grid", data)
    assert result == data


def test_drawing_dto_optional_fill_stroke_clip():
    data = {
        "schema_version": 1,
        "kind": "rect",
        "lines": [
            {
                "schema_version": 1,
                "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 0.0},
                "width": 1.0,
                "color": 0.0,
                "source_order": 0,
            }
        ],
        "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
        "fill": None,
        "stroke": 0.5,
        "clip": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 100.0},
        "source_order": 0,
    }
    result = roundtrip_dto("drawing", data)
    assert result == data


def test_diagnostic_dto_roundtrip():
    data = {
        "schema_version": 1,
        "status": "rust_output_mismatch",
        "path": "tables[0].cells[1].text",
        "error_type": None,
        "message": "Mismatch detected",
        "traceback_id": None,
        "field": "text",
        "python_value": {"schema_version": 1, "kind": "string", "text": "expected"},
        "rust_value": {"schema_version": 1, "kind": "string", "text": "actual"},
        "classification": "defect",
    }
    result = roundtrip_dto("diagnostic", data)
    assert result == data


def test_schema_version_mismatch_rejected():
    data = {
        "schema_version": 2,
        "width": 100.0,
        "height": 200.0,
        "rotation": 0,
    }
    with pytest.raises(ValueError, match=r"schema_version"):
        roundtrip_dto("page", data)


def test_missing_required_field_rejected():
    data = {
        "schema_version": 1,
        "width": 100.0,
        # missing height
        "rotation": 0,
    }
    with pytest.raises((ValueError, KeyError, TypeError)):
        roundtrip_dto("page", data)
