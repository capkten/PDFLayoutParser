# -*- coding: utf-8 -*-
"""Tests and benchmarks for packed/flattened buffer transfer in wireless table recovery."""

import time
import pytest

from hexai_pdf_parser.rust_adapter import (
    recover_wireless_tables,
    recover_wireless_tables_packed,
    pack_wireless_recovery_input,
)


def _rect(x0, y0, x1, y1):
    return {
        "schema_version": 1,
        "x0": float(x0),
        "y0": float(y0),
        "x1": float(x1),
        "y1": float(y1),
    }


def _create_sample_input():
    page = {"schema_version": 1, "width": 595.0, "height": 842.0, "rotation": 0}
    # 2 rows, 2 columns table
    spans = [
        {
            "schema_version": 1,
            "text": "项目",
            "rect": _rect(10, 10, 40, 20),
            "font": "SimSun",
            "size": 10.0,
            "flags": 0,
            "order": 0,
            "characters": [
                {"schema_version": 1, "text": "项", "rect": _rect(10, 10, 25, 20), "order": 0},
                {"schema_version": 1, "text": "目", "rect": _rect(25, 10, 40, 20), "order": 1},
            ],
            "source_position": {"schema_version": 1, "block": 0, "line": 0},
            "block": 0,
            "line": 0,
        },
        {
            "schema_version": 1,
            "text": "金额",
            "rect": _rect(100, 10, 140, 20),
            "font": "SimSun",
            "size": 10.0,
            "flags": 0,
            "order": 1,
            "characters": [
                {"schema_version": 1, "text": "金", "rect": _rect(100, 10, 120, 20), "order": 0},
                {"schema_version": 1, "text": "额", "rect": _rect(120, 10, 140, 20), "order": 1},
            ],
            "source_position": {"schema_version": 1, "block": 0, "line": 0},
            "block": 0,
            "line": 0,
        },
        {
            "schema_version": 1,
            "text": "营收",
            "rect": _rect(10, 30, 40, 40),
            "font": "SimSun",
            "size": 10.0,
            "flags": 0,
            "order": 2,
            "characters": [
                {"schema_version": 1, "text": "营", "rect": _rect(10, 30, 25, 40), "order": 0},
                {"schema_version": 1, "text": "收", "rect": _rect(25, 30, 40, 40), "order": 1},
            ],
            "source_position": {"schema_version": 1, "block": 0, "line": 1},
            "block": 0,
            "line": 1,
        },
        {
            "schema_version": 1,
            "text": "100",
            "rect": _rect(100, 30, 130, 40),
            "font": "SimSun",
            "size": 10.0,
            "flags": 0,
            "order": 3,
            "characters": [
                {"schema_version": 1, "text": "1", "rect": _rect(100, 30, 110, 40), "order": 0},
                {"schema_version": 1, "text": "0", "rect": _rect(110, 30, 120, 40), "order": 1},
                {"schema_version": 1, "text": "0", "rect": _rect(120, 30, 130, 40), "order": 2},
            ],
            "source_position": {"schema_version": 1, "block": 0, "line": 1},
            "block": 0,
            "line": 1,
        },
    ]
    regions = [
        {"schema_version": 1, "rect": _rect(0, 0, 595, 842), "source_order": 0, "allowed": True}
    ]
    config = {
        "schema_version": 1,
        "line_tolerance": 2.0,
        "row_tolerance": 2.0,
        "column_tolerance": 2.0,
        "span_tolerance": 2.0,
        "numeric_tolerance": 2.0,
    }
    return {
        "schema_version": 1,
        "page": page,
        "spans": spans,
        "regions": regions,
        "config": config,
    }


def test_packed_wireless_recovery_matches_dict_recovery():
    """Verify that packed recovery produces identical results to dict recovery."""
    input_dto = _create_sample_input()
    dict_res = recover_wireless_tables(input_dto)
    packed_args = pack_wireless_recovery_input(input_dto)
    packed_res = recover_wireless_tables_packed(*packed_args)

    assert len(dict_res["candidates"]) == len(packed_res["candidates"])
    for c_dict, c_pack in zip(dict_res["candidates"], packed_res["candidates"]):
        assert c_dict["rows"] == c_pack["rows"]
        assert c_dict["cols"] == c_pack["cols"]
        assert c_dict["confidence"] == pytest.approx(c_pack["confidence"])
        assert len(c_dict["cells"]) == len(c_pack["cells"])
        for cell_dict, cell_pack in zip(c_dict["cells"], c_pack["cells"]):
            assert cell_dict["text"] == cell_pack["text"]
            assert cell_dict["row"] == cell_pack["row"]
            assert cell_dict["col"] == cell_pack["col"]
            assert cell_dict["rowspan"] == cell_pack["rowspan"]
            assert cell_dict["colspan"] == cell_pack["colspan"]
            assert cell_dict["rect"]["x0"] == pytest.approx(cell_pack["rect"]["x0"])
            assert cell_dict["rect"]["y0"] == pytest.approx(cell_pack["rect"]["y0"])
            assert cell_dict["rect"]["x1"] == pytest.approx(cell_pack["rect"]["x1"])
            assert cell_dict["rect"]["y1"] == pytest.approx(cell_pack["rect"]["y1"])


def test_packed_performance_benchmark():
    """Benchmark the FFI transfer and recovery time between dict DTO and packed buffer from NativeSpans."""
    from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan
    from hexai_pdf_parser.core.models import BBox
    from hexai_pdf_parser.rust_adapter import pack_native_spans, _pdf_fast

    # Generate a realistic large table: 25 rows, 6 columns = 150 cells, with sub-spans ~150 spans, ~1200 chars
    native_spans = []
    order = 0
    for r in range(25):
        y0 = 50.0 + r * 20.0
        y1 = y0 + 15.0
        for c in range(6):
            x0 = 50.0 + c * 80.0
            x1 = x0 + 70.0
            text = f"Val_{r}_{c}"
            chars = [
                (ch, BBox(x0 + i * 8, y0, x0 + (i + 1) * 8, y1))
                for i, ch in enumerate(text)
            ]
            native_spans.append(
                NativeSpan(
                    text=text,
                    bbox=BBox(x0, y0, x1, y1),
                    font="SimSun",
                    size=9.0,
                    order=order,
                    characters=chars,
                    source_position=(0, r, c),
                )
            )
            order += 1

    # Warmup
    old_dto = {
        "schema_version": 1,
        "page": {"schema_version": 1, "width": 595.0, "height": 842.0, "rotation": 0},
        "spans": [
            {
                "schema_version": 1,
                "text": s.text,
                "rect": {"schema_version": 1, "x0": s.bbox.x0, "y0": s.bbox.y0, "x1": s.bbox.x1, "y1": s.bbox.y1},
                "font": s.font,
                "size": s.size,
                "flags": 0,
                "order": s.order,
                "characters": [
                    {"schema_version": 1, "text": ch[0], "rect": {"schema_version": 1, "x0": ch[1].x0, "y0": ch[1].y0, "x1": ch[1].x1, "y1": ch[1].y1}, "order": idx}
                    for idx, ch in enumerate(s.characters)
                ],
                "source_position": {"schema_version": 1, "block": s.source_position[0], "line": s.source_position[1]},
                "block": s.source_position[0],
                "line": s.source_position[1],
            }
            for s in native_spans
        ],
        "regions": [{"schema_version": 1, "rect": _rect(0, 0, 595, 842), "source_order": 0, "allowed": True}],
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }
    _pdf_fast.recover_wireless_tables(old_dto)
    warm_packed = pack_native_spans(native_spans)
    recover_wireless_tables_packed(*warm_packed)

    # 1. Measure Old Dict path: NativeSpan -> nested Dict tree -> _pdf_fast.recover_wireless_tables
    iterations = 25
    t0 = time.perf_counter()
    for _ in range(iterations):
        spans_dto = [
            {
                "schema_version": 1,
                "text": s.text,
                "rect": {"schema_version": 1, "x0": s.bbox.x0, "y0": s.bbox.y0, "x1": s.bbox.x1, "y1": s.bbox.y1},
                "font": s.font,
                "size": s.size,
                "flags": 0,
                "order": s.order,
                "characters": [
                    {"schema_version": 1, "text": ch[0], "rect": {"schema_version": 1, "x0": ch[1].x0, "y0": ch[1].y0, "x1": ch[1].x1, "y1": ch[1].y1}, "order": idx}
                    for idx, ch in enumerate(s.characters)
                ],
                "source_position": {"schema_version": 1, "block": s.source_position[0], "line": s.source_position[1]},
                "block": s.source_position[0],
                "line": s.source_position[1],
            }
            for s in native_spans
        ]
        input_dto = {
            "schema_version": 1,
            "page": {"schema_version": 1, "width": 595.0, "height": 842.0, "rotation": 0},
            "spans": spans_dto,
            "regions": [{"schema_version": 1, "rect": _rect(0, 0, 595, 842), "source_order": 0, "allowed": True}],
            "config": {
                "schema_version": 1,
                "line_tolerance": 2.0,
                "row_tolerance": 2.0,
                "column_tolerance": 2.0,
                "span_tolerance": 2.0,
                "numeric_tolerance": 2.0,
            },
        }
        res_dict = _pdf_fast.recover_wireless_tables(input_dto)
    dict_time = (time.perf_counter() - t0) / iterations

    # 2. Measure New Packed path: NativeSpan -> packed arrays -> recover_wireless_tables_packed
    t0 = time.perf_counter()
    for _ in range(iterations):
        packed_args = pack_native_spans(native_spans)
        res_packed = recover_wireless_tables_packed(*packed_args)
    packed_time = (time.perf_counter() - t0) / iterations

    speedup = dict_time / max(packed_time, 1e-6)
    print(f"\n[Production End-to-End Benchmark] Old Dict Path: {dict_time * 1000:.2f}ms | New Packed Path: {packed_time * 1000:.2f}ms | Speedup: {speedup:.2f}x")
    assert packed_time < dict_time


