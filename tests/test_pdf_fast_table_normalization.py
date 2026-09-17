# -*- coding: utf-8 -*-
"""Sprint 010: Test suite for table header normalization and token normalization in Rust."""

from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.tables.normalizers.table_header_normalizer import _promote_grouped_header


def test_roundtrip_table_normalization_dtos():
    """Verify that Sprint 010 DTO types roundtrip properly through Rust FFI."""
    cfg = {
        "schema_version": 1,
        "line_tolerance": 2.0,
        "row_tolerance": 2.0,
        "column_tolerance": 2.0,
        "span_tolerance": 2.0,
        "numeric_tolerance": 2.0,
    }
    cell = {
        "schema_version": 1,
        "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 20.0},
        "text": "项目",
        "row": 0,
        "col": 0,
        "rowspan": 1,
        "colspan": 1,
        "source": None,
    }
    grid_dto = {
        "schema_version": 1,
        "grid": {
            "schema_version": 1,
            "rows": 2,
            "cols": 3,
            "row_edges": [0.0, 25.0, 50.0],
            "col_edges": [0.0, 50.0, 100.0, 150.0],
            "occupancy": [[0, None, None], [None, None, None]],
        },
        "cells": [cell],
        "empty_slots": [],
    }

    h_in = rust_adapter.roundtrip_dto("header_grid_input", {
        "schema_version": 1,
        "grid": grid_dto,
        "config": cfg,
    })
    assert h_in["schema_version"] == 1
    assert len(h_in["grid"]["cells"]) == 1

    diag = {
        "schema_version": 1,
        "status": "info",
        "path": "test",
    }
    h_out = rust_adapter.roundtrip_dto("header_grid_output", {
        "schema_version": 1,
        "grid": grid_dto,
        "cells": [cell],
        "diagnostics": [diag],
    })
    assert h_out["schema_version"] == 1
    assert len(h_out["diagnostics"]) == 1

    t_in = rust_adapter.roundtrip_dto("header_token_input", {
        "schema_version": 1,
        "cells": [cell],
        "config": cfg,
    })
    assert t_in["schema_version"] == 1

    t_out = rust_adapter.roundtrip_dto("header_token_output", {
        "schema_version": 1,
        "cells": [cell],
        "diagnostics": [],
    })
    assert t_out["schema_version"] == 1


def test_infer_header_structure_rust():
    """Test inferring grouped header and anchor spans directly via Rust kernel."""
    cells = [
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 20.0},
            "text": "项目",
            "row": 0,
            "col": 0,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 50.0, "y0": 0.0, "x1": 150.0, "y1": 20.0},
            "text": "本年金额",
            "row": 0,
            "col": 1,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 50.0, "y0": 20.0, "x1": 100.0, "y1": 40.0},
            "text": "收入",
            "row": 1,
            "col": 1,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 100.0, "y0": 20.0, "x1": 150.0, "y1": 40.0},
            "text": "支出",
            "row": 1,
            "col": 2,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
    ]
    grid_dto = {
        "schema_version": 1,
        "grid": {
            "schema_version": 1,
            "rows": 2,
            "cols": 3,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 150.0, "y1": 40.0},
        },
        "cells": cells,
        "empty_slots": [],
    }
    input_dto = {
        "schema_version": 1,
        "grid": grid_dto,
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }

    out = rust_adapter.infer_header_structure(input_dto)
    res_cells = out["cells"]
    anchor = next(c for c in res_cells if c["text"] == "项目")
    group = next(c for c in res_cells if "本年金额" in c["text"])

    assert anchor["rowspan"] == 2
    assert group["colspan"] == 2


def test_merge_header_spans_rust():
    """Test merge_header_spans kernel in Rust."""
    cells = [
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 100.0, "y0": 20.0, "x1": 150.0, "y1": 40.0},
            "text": "支出",
            "row": 1,
            "col": 2,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 20.0},
            "text": "项目",
            "row": 0,
            "col": 0,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
    ]
    grid_dto = {
        "schema_version": 1,
        "grid": {
            "schema_version": 1,
            "rows": 2,
            "cols": 3,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 150.0, "y1": 40.0},
        },
        "cells": cells,
        "empty_slots": [],
    }
    input_dto = {
        "schema_version": 1,
        "grid": grid_dto,
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }
    out = rust_adapter.merge_header_spans(input_dto)
    assert len(out["cells"]) == 2
    assert out["cells"][0]["text"] == "项目"
    assert out["cells"][1]["text"] == "支出"


def test_normalize_financial_header_tokens_rust():
    """Test normalizing financial header tokens (cleaning trailing numbers) in Rust."""
    cells = [
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 0.0, "x1": 50.0, "y1": 20.0},
            "text": "期末余额 123.45",
            "row": 0,
            "col": 1,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
        {
            "schema_version": 1,
            "rect": {"schema_version": 1, "x0": 0.0, "y0": 40.0, "x1": 50.0, "y1": 60.0},
            "text": "合计 999",
            "row": 3,
            "col": 0,
            "rowspan": 1,
            "colspan": 1,
            "source": None,
        },
    ]
    input_dto = {
        "schema_version": 1,
        "cells": cells,
        "config": {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        },
    }
    out = rust_adapter.normalize_financial_header_tokens(input_dto)
    # Row 0 header cleaned
    assert out["cells"][0]["text"] == "期末余额"
    # Row 3 body cell preserved
    assert out["cells"][1]["text"] == "合计 999"


def test_promote_grouped_header_modes():
    """Test _promote_grouped_header across python, shadow, and rust modes."""
    cells = [
        Cell(
            text="项目",
            row_index=0,
            col_index=0,
            bbox=BBox(0.0, 0.0, 50.0, 20.0),
            rowspan=1,
            colspan=1,
        ),
        Cell(
            text="本期金额",
            row_index=0,
            col_index=1,
            bbox=BBox(50.0, 0.0, 150.0, 20.0),
            rowspan=1,
            colspan=1,
        ),
        Cell(
            text="主营业务收入",
            row_index=1,
            col_index=0,
            bbox=BBox(0.0, 20.0, 50.0, 40.0),
            rowspan=1,
            colspan=1,
        ),
        Cell(
            text="1000",
            row_index=1,
            col_index=1,
            bbox=BBox(50.0, 20.0, 100.0, 40.0),
            rowspan=1,
            colspan=1,
        ),
        Cell(
            text="2000",
            row_index=1,
            col_index=2,
            bbox=BBox(100.0, 20.0, 150.0, 40.0),
            rowspan=1,
            colspan=1,
        ),
    ]
    table = Table(
        bbox=BBox(0.0, 0.0, 150.0, 40.0),
        rows=2,
        cols=3,
        cells=cells,
        confidence=1.0,
        source="unit_test",
    )

    class DummyPage:
        def get_text(self, kind, *args, **kwargs):
            if kind == "dict":
                return {"blocks": []}
            return []

    dummy_page = DummyPage()

    # 1. Python mode
    os.environ["PDF_RUST_MODE"] = "python"
    t_py = _promote_grouped_header(table, dummy_page)
    anchor_py = next(c for c in t_py.cells if c.text == "项目")
    group_py = next(c for c in t_py.cells if "本期金额" in c.text)
    assert anchor_py.rowspan == 2
    assert group_py.colspan == 2

    # 2. Shadow mode
    os.environ["PDF_RUST_MODE"] = "shadow"
    t_shadow = _promote_grouped_header(table, dummy_page)
    anchor_shadow = next(c for c in t_shadow.cells if c.text == "项目")
    group_shadow = next(c for c in t_shadow.cells if "本期金额" in c.text)
    assert anchor_shadow.rowspan == 2
    assert group_shadow.colspan == 2

    # 3. Rust mode
    os.environ["PDF_RUST_MODE"] = "rust"
    t_rust = _promote_grouped_header(table, dummy_page)
    anchor_rust = next(c for c in t_rust.cells if c.text == "项目")
    group_rust = next(c for c in t_rust.cells if "本期金额" in c.text)
    assert anchor_rust.rowspan == 2
    assert group_rust.colspan == 2

    # Verify identical output between python and rust
    for c_py, c_r in zip(t_py.cells, t_rust.cells):
        assert c_py.text == c_r.text
        assert c_py.row_index == c_r.row_index
        assert c_py.col_index == c_r.col_index
        assert c_py.rowspan == c_r.rowspan
        assert c_py.colspan == c_r.colspan
