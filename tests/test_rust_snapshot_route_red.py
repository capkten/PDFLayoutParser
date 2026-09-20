from __future__ import annotations

import pytest

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.models import BBox
from hexai_pdf_parser.pdf_snapshot import PageSnapshot
from hexai_pdf_parser.tables.wireless_table_recovery import (
    collect_native_spans_from_snapshot as python_collect_native_spans,
)


def _span(text: str, x0: float, y0: float, position: tuple[int, int, int]) -> dict:
    x1 = x0 + max(8.0, len(text) * 8.0)
    chars = tuple(
        {
            "c": character,
            "bbox": (x0 + index * 8.0, y0, x0 + (index + 1) * 8.0, y0 + 12.0),
            "raw_source_position": (*position, index),
            "source_order": index,
        }
        for index, character in enumerate(text)
    )
    return {
        "text": text,
        "bbox": (x0, y0, x1, y0 + 12.0),
        "font": "SimSun",
        "size": 10.0,
        "flags": 0,
        "chars": chars,
        "raw_source_position": position,
        "source_order": position[2],
    }


def _snapshot_with_text_blocks(*blocks: dict, y0: float = 0.0, height: float = 100.0) -> PageSnapshot:
    spans = tuple(
        span
        for block in blocks
        for line in block.get("lines", ())
        for span in line["spans"]
    )
    return PageSnapshot(
        schema_version=1,
        version=1,
        page_index=0,
        geometry={
            "rect": (0.0, y0, 300.0, y0 + height),
            "x0": 0.0,
            "y0": y0,
            "x1": 300.0,
            "y1": y0 + height,
            "width": 300.0,
            "height": height,
            "rotation": 0,
        },
        text_blocks=tuple(blocks),
        spans=spans,
        characters=(),
        words=(),
        drawings=(),
        allowed_regions=(),
        excluded_regions=(),
        extraction_options={},
        summary={},
    )


def _empty_snapshot() -> PageSnapshot:
    return _snapshot_with_text_blocks()


def test_snapshot_native_span_collection_skips_non_text_blocks_in_both_paths():
    text_block = {
        "type": 0,
        "bbox": (10.0, 10.0, 80.0, 24.0),
        "raw_source_position": (0,),
        "source_order": 0,
        "lines": ({
            "bbox": (10.0, 10.0, 80.0, 24.0),
            "raw_source_position": (0, 0),
            "source_order": 0,
            "spans": (_span("保留", 10.0, 10.0, (0, 0, 0)),),
        },),
    }
    non_text_block = {
        "type": 1,
        "bbox": (10.0, 40.0, 80.0, 54.0),
        "raw_source_position": (1,),
        "source_order": 1,
        "lines": ({
            "bbox": (10.0, 40.0, 80.0, 54.0),
            "raw_source_position": (1, 0),
            "source_order": 1,
            "spans": (_span("不应进入", 10.0, 40.0, (1, 0, 0)),),
        },),
    }
    snapshot = _snapshot_with_text_blocks(text_block, non_text_block)

    python_spans = python_collect_native_spans(snapshot)
    rust_spans = rust_adapter.collect_native_spans_from_snapshot(snapshot)

    assert [span.text for span in python_spans] == ["保留"]
    assert [span.text for span in rust_spans] == ["保留"]


def test_snapshot_native_span_collection_does_not_fallback_to_span_text_without_chars():
    span = _span("不应使用", 10.0, 10.0, (0, 0, 0))
    span["chars"] = ()
    text_block = {
        "type": 0,
        "bbox": (10.0, 10.0, 80.0, 24.0),
        "raw_source_position": (0,),
        "source_order": 0,
        "lines": ({
            "bbox": (10.0, 10.0, 80.0, 24.0),
            "raw_source_position": (0, 0),
            "source_order": 0,
            "spans": (span,),
        },),
    }
    snapshot = _snapshot_with_text_blocks(text_block)

    assert python_collect_native_spans(snapshot) == ()
    assert rust_adapter.collect_native_spans_from_snapshot(snapshot) == ()


def test_snapshot_native_span_collection_skips_explicit_none_block_type_in_both_paths():
    block = {
        "type": None,
        "bbox": (10.0, 10.0, 80.0, 24.0),
        "raw_source_position": (0,),
        "source_order": 0,
        "lines": ({
            "bbox": (10.0, 10.0, 80.0, 24.0),
            "raw_source_position": (0, 0),
            "source_order": 0,
            "spans": (_span("不应进入", 10.0, 10.0, (0, 0, 0)),),
        },),
    }
    snapshot = _snapshot_with_text_blocks(block)

    assert python_collect_native_spans(snapshot) == ()
    assert rust_adapter.collect_native_spans_from_snapshot(snapshot) == ()


def test_snapshot_native_span_collection_accepts_non_text_block_without_lines():
    block = {
        "type": 1,
        "bbox": (10.0, 10.0, 80.0, 24.0),
        "raw_source_position": (0,),
        "source_order": 0,
    }
    snapshot = _snapshot_with_text_blocks(block)

    assert python_collect_native_spans(snapshot) == ()
    assert rust_adapter.collect_native_spans_from_snapshot(snapshot) == ()


def test_snapshot_native_span_collection_nonzero_origin_uses_snapshot_y_origin_for_footer_filter():
    footer = {
        "type": 0,
        "bbox": (10.0, 0.0, 180.0, 12.0),
        "raw_source_position": (0,),
        "source_order": 0,
        "lines": ({
            "bbox": (10.0, 0.0, 180.0, 12.0),
            "raw_source_position": (0, 0),
            "source_order": 0,
            "spans": (_span("第 1 页 / 共 2 页", 10.0, 0.0, (0, 0, 0)),),
        },),
    }
    snapshot = _snapshot_with_text_blocks(footer, y0=-100.0, height=100.0)

    assert python_collect_native_spans(snapshot) == ()
    assert rust_adapter.collect_native_spans_from_snapshot(snapshot) == ()
    assert rust_adapter.page_snapshot_to_rust_input(snapshot)["page_y0"] == -100.0


@pytest.mark.parametrize(
    ("rows", "cols", "cells", "failure_reason"),
    [
        (
            1,
            1,
            [
                {
                    "row": 1,
                    "col": 0,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": "越界",
                    "rect": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
                }
            ],
            "outside its grid",
        ),
        (1, 1, [], "unmaterialized"),
        (0, 1, [], "positive|empty grid"),
        (-1, 1, [], "positive|non-negative"),
        (
            1,
            1,
            [{
                "row": 0,
                "col": 0,
                "rowspan": 0,
                "colspan": 1,
                "text": "非法跨度",
                "rect": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
            }],
            "positive",
        ),
        (
            1,
            1,
            [{
                "row": 0,
                "col": 0,
                "rowspan": 1,
                "colspan": 0,
                "text": "非法跨度",
                "rect": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
            }],
            "positive",
        ),
        (
            1,
            1,
            [
                {
                    "row": 0,
                    "col": 0,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": "A",
                    "rect": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
                },
                {
                    "row": 0,
                    "col": 0,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": "B",
                    "rect": {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 10.0},
                },
            ],
            "occupancy conflict",
        ),
        (
            1,
            1,
            [{
                "row": 0,
                "col": 0,
                "rowspan": 1,
                "colspan": 1,
                "text": "缺少矩形",
            }],
            "missing a rectangle",
        ),
    ],
)
def test_snapshot_adapter_rejects_invalid_rust_grid_output(
    monkeypatch, rows, cols, cells, failure_reason
):
    class FakeRustExtension:
        @staticmethod
        def recover_cells_from_snapshot(snapshot, region):
            return {
                "grid": {"grid": {"rows": rows, "cols": cols}},
                "cells": cells,
            }

    monkeypatch.setattr(rust_adapter, "_pdf_fast", FakeRustExtension())

    with pytest.raises(ValueError, match=failure_reason):
        rust_adapter.recover_cells_from_snapshot(_empty_snapshot(), BBox(0, 0, 20, 20))
