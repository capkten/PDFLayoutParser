from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from hexai_pdf_parser.core.models import (
    BBox,
    Cell,
    Document,
    LayoutElement,
    Line,
    Page,
    Table,
    Word,
)
from hexai_pdf_parser.writers.json_writer import JSONWriter
from hexai_pdf_parser.writers.markdown_writer import MarkdownWriter
from pdfium_layout_adapter import extract_layout_with_rust_probe
from pdfium_writer_adapter import (
    _find_pdfium_probe_bin,
    export_json_with_rust_probe,
    normalize_full_tables_for_probe,
    render_markdown_with_rust_probe,
)


def _get_synth_pdf(name: str) -> Path:
    probe_root = _TEST_DIR.parent
    pdf_path = probe_root / "test_data" / "synthetic" / name
    assert pdf_path.is_file(), f"Synthetic PDF not found: {pdf_path}"
    return pdf_path


def _get_repo_root() -> Path:
    probe_root = _TEST_DIR.parent
    fallback_repo = (
        probe_root.parents[1]
        if len(probe_root.parents) > 1
        else probe_root.parent.parent
    )
    return Path(os.environ.get("REPO_ROOT", str(fallback_repo)))


def test_rust_markdown_cli_invocation(tmp_path: Path) -> None:
    probe_bin_str = _find_pdfium_probe_bin()
    assert probe_bin_str is not None, "pdfium_probe binary not found"
    probe_bin = Path(probe_bin_str)
    assert probe_bin.is_file()

    synth_pdf = _get_synth_pdf("synth_crop_offset.pdf")
    out_md = tmp_path / "crop_offset.md"

    cmd = [
        str(probe_bin),
        "markdown",
        str(synth_pdf),
        "0",
        "[]",
        str(out_md),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, f"pdfium_probe markdown CLI failed: {res.stderr}"
    assert out_md.is_file()

    content = out_md.read_text(encoding="utf-8")
    assert "Outside of CropBox" in content
    assert "Header in CropBox" in content
    assert "Normal Body Text" in content

    # Test adapter function directly
    md_str = render_markdown_with_rust_probe(synth_pdf, 0, [])
    assert "Outside of CropBox" in md_str
    assert "Header in CropBox" in md_str
    assert "Normal Body Text" in md_str


def test_rust_markdown_table_spans_and_sparse_parity(tmp_path: Path) -> None:
    # Complex table with rowspan, colspan, missing cells, HTML characters (&, <, >), and numbers with spaces
    table = Table(
        bbox=BBox(50.0, 50.0, 300.0, 200.0),
        rows=3,
        cols=3,
        cells=[
            Cell(
                text="Header 1 & 2",
                row_index=0,
                col_index=0,
                bbox=BBox(50.0, 50.0, 200.0, 80.0),
                rowspan=1,
                colspan=2,
            ),
            Cell(
                text="Header <3>",
                row_index=0,
                col_index=2,
                bbox=BBox(200.0, 50.0, 300.0, 80.0),
                rowspan=1,
                colspan=1,
            ),
            Cell(
                text="Spanning Item > A",
                row_index=1,
                col_index=0,
                bbox=BBox(50.0, 80.0, 100.0, 160.0),
                rowspan=2,
                colspan=1,
            ),
            # (row=1, col=1) is intentionally missing to verify sparse table rendering
            Cell(
                text="1 234.56",
                row_index=1,
                col_index=2,
                bbox=BBox(200.0, 80.0, 300.0, 120.0),
                rowspan=1,
                colspan=1,
            ),
            Cell(
                text="- 98.70",
                row_index=2,
                col_index=1,
                bbox=BBox(100.0, 120.0, 200.0, 160.0),
                rowspan=1,
                colspan=1,
            ),
            Cell(
                text="0. 05",
                row_index=2,
                col_index=2,
                bbox=BBox(200.0, 120.0, 300.0, 160.0),
                rowspan=1,
                colspan=1,
            ),
        ],
    )

    py_writer = MarkdownWriter()
    py_lines = py_writer._render_table(table)
    py_table_html = "\n".join(py_lines).strip()

    synth_pdf = _get_synth_pdf("synth_crop_offset.pdf")
    rust_md = render_markdown_with_rust_probe(synth_pdf, 0, [table])

    assert py_table_html in rust_md
    assert '<td colspan="2">Header 1 &amp; 2</td>' in rust_md
    assert "<td>Header &lt;3&gt;</td>" in rust_md
    assert '<td rowspan="2">Spanning Item &gt; A</td>' in rust_md
    assert "<td></td>" in rust_md
    assert "<td>1234.56</td>" in rust_md
    assert "<td>-98.70</td>" in rust_md
    assert "<td>0.05</td>" in rust_md


def test_rust_json_export_parity(tmp_path: Path) -> None:
    synth_pdf = _get_synth_pdf("synth_crop_offset.pdf")
    table = Table(
        bbox=BBox(100.0, 100.0, 220.0, 150.0),
        rows=2,
        cols=2,
        cells=[
            Cell(text="C0", row_index=0, col_index=0, bbox=BBox(100.0, 100.0, 160.0, 125.0)),
            Cell(text="C1", row_index=0, col_index=1, bbox=BBox(160.0, 100.0, 220.0, 125.0)),
            Cell(text="C2", row_index=1, col_index=0, bbox=BBox(100.0, 125.0, 160.0, 150.0)),
            Cell(text="C3", row_index=1, col_index=1, bbox=BBox(160.0, 125.0, 220.0, 150.0)),
        ],
        source="synthetic",
    )

    rust_page_dict = export_json_with_rust_probe(synth_pdf, 0, [table])

    # 1. Verify schema keys match Python JSONWriter._page_to_dict expectation
    expected_page_keys = {
        "index",
        "size",
        "rotation",
        "page_type",
        "blocks",
        "tables",
        "images",
        "seals",
        "render",
        "layout_elements",
    }
    assert set(rust_page_dict.keys()) == expected_page_keys
    assert rust_page_dict["index"] == 0
    assert rust_page_dict["page_type"] == "vector"
    assert "width" in rust_page_dict["size"] and "height" in rust_page_dict["size"]

    # 2. Verify table schema and {x0, y0, x1, y1} bbox format
    assert len(rust_page_dict["tables"]) == 1
    t_dict = rust_page_dict["tables"][0]
    expected_table_keys = {"bbox", "rows", "cols", "cells", "confidence", "source"}
    assert set(t_dict.keys()) == expected_table_keys
    assert set(t_dict["bbox"].keys()) == {"x0", "y0", "x1", "y1"}
    assert t_dict["rows"] == 2
    assert t_dict["cols"] == 2
    assert len(t_dict["cells"]) == 4

    for cell_d in t_dict["cells"]:
        expected_cell_keys = {"text", "row_index", "col_index", "bbox", "rowspan", "colspan"}
        assert set(cell_d.keys()) == expected_cell_keys
        assert set(cell_d["bbox"].keys()) == {"x0", "y0", "x1", "y1"}

    # 3. Verify layout_elements structure
    assert len(rust_page_dict["layout_elements"]) == 3
    for elem_d in rust_page_dict["layout_elements"]:
        assert "type" in elem_d
        assert "bbox" in elem_d
        assert set(elem_d["bbox"].keys()) == {"x0", "y0", "x1", "y1"}
        assert "order" in elem_d
        assert "content" in elem_d

    table_elem = [e for e in rust_page_dict["layout_elements"] if e["type"] == "table"][0]
    assert isinstance(table_elem["content"], dict)
    assert table_elem["content"]["rows"] == 2


def test_end_to_end_document_export_parity() -> None:
    for sample_name in [
        "synth_crop_offset.pdf",
        "synth_rotations.pdf",
        "synth_invisible_text.pdf",
    ]:
        pdf_path = _get_synth_pdf(sample_name)

        # 1. Markdown comparison
        rust_md = render_markdown_with_rust_probe(pdf_path, 0, [])
        assert isinstance(rust_md, str)
        assert len(rust_md.strip()) > 0

        elements = extract_layout_with_rust_probe(pdf_path, 0, [])
        page = Page(
            index=0,
            size={"width": 612.0, "height": 792.0},
            rotation=0,
            layout_elements=elements,
        )
        doc = Document(file_name=sample_name, page_count=1, pages=[page])

        py_writer = MarkdownWriter()
        py_md = py_writer.to_string(doc)

        assert rust_md.strip() == py_md.strip()

        # 2. JSON comparison
        rust_json = export_json_with_rust_probe(pdf_path, 0, [])
        assert rust_json["index"] == 0
        assert rust_json["page_type"] == "vector"
        assert len(rust_json["layout_elements"]) == len(elements)
        for r_elem, py_elem in zip(rust_json["layout_elements"], elements):
            assert r_elem["type"] == py_elem.type
            assert r_elem["order"] == py_elem.order
            assert pytest.approx(r_elem["bbox"]["x0"], abs=0.5) == py_elem.bbox.x0
            assert pytest.approx(r_elem["bbox"]["y0"], abs=0.5) == py_elem.bbox.y0
            assert pytest.approx(r_elem["bbox"]["x1"], abs=0.5) == py_elem.bbox.x1
            assert pytest.approx(r_elem["bbox"]["y1"], abs=0.5) == py_elem.bbox.y1


def test_normalize_full_tables_for_probe_variations() -> None:
    # Test Table dataclass
    tbl_dataclass = Table(
        bbox=BBox(10.0, 20.0, 100.0, 200.0),
        rows=2,
        cols=2,
        cells=[
            Cell(text="Cell 1", row_index=0, col_index=0, bbox=BBox(10.0, 20.0, 50.0, 100.0)),
            Cell(text="Cell 2", row_index=0, col_index=1, bbox=BBox(50.0, 20.0, 100.0, 100.0), colspan=2),
        ],
        confidence=0.9,
        source="test",
    )
    norm = normalize_full_tables_for_probe([tbl_dataclass])
    assert len(norm) == 1
    assert norm[0]["bbox"] == [10.0, 20.0, 100.0, 200.0]
    assert norm[0]["rows"] == 2
    assert norm[0]["cols"] == 2
    assert len(norm[0]["cells"]) == 2
    assert norm[0]["cells"][0]["text"] == "Cell 1"
    assert norm[0]["cells"][1]["colspan"] == 2
    assert norm[0]["confidence"] == 0.9
    assert norm[0]["source"] == "test"

    # Test dict format with inferred rows/cols
    tbl_dict = {
        "bbox": {"x0": 5.0, "y0": 10.0, "x1": 50.0, "y1": 80.0},
        "cells": [
            {
                "text": "Cell Inferred",
                "row_index": 1,
                "col_index": 2,
                "rowspan": 2,
                "colspan": 1,
                "bbox": [5.0, 10.0, 25.0, 40.0],
            }
        ],
    }
    norm_dict = normalize_full_tables_for_probe([tbl_dict])
    assert len(norm_dict) == 1
    assert norm_dict[0]["bbox"] == [5.0, 10.0, 50.0, 80.0]
    assert norm_dict[0]["rows"] == 3
    assert norm_dict[0]["cols"] == 3
    assert norm_dict[0]["cells"][0]["rowspan"] == 2
