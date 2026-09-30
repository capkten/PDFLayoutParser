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

from hexai_pdf_parser.core.models import BBox, LayoutElement, Line, Table, Word
from hexai_pdf_parser.extractors.layout_builder import LayoutBuilder
from hexai_pdf_parser.extractors.layout_mapper import LayoutMapper
from hexai_pdf_parser.extractors.text_extractor import TextExtractor
from pdfium_layout_adapter import (
    _find_pdfium_probe_bin,
    extract_layout_with_rust_probe,
    serialize_tables_to_json,
)
from pdfium_normalizer import normalize_with_rust_probe
from pdfium_page_adapter import PdfiumPageAdapter


def _get_synth_pdf(name: str) -> Path:
    probe_root = _TEST_DIR.parent
    pdf_path = probe_root / "test_data" / "synthetic" / name
    assert pdf_path.is_file(), f"Synthetic PDF not found: {pdf_path}"
    return pdf_path


def _get_repo_root() -> Path:
    probe_root = _TEST_DIR.parent
    fallback_repo = probe_root.parents[1] if len(probe_root.parents) > 1 else probe_root.parent.parent
    return Path(os.environ.get("REPO_ROOT", str(fallback_repo)))


def test_rust_layout_cli_invocation(tmp_path: Path) -> None:
    probe_bin_str = _find_pdfium_probe_bin()
    assert probe_bin_str is not None, "pdfium_probe binary not found"
    probe_bin = Path(probe_bin_str)
    assert probe_bin.is_file()

    synth_pdf = _get_synth_pdf("synth_crop_offset.pdf")
    out_json = tmp_path / "crop_offset_layout.json"

    cmd = [
        str(probe_bin),
        "layout",
        str(synth_pdf),
        "0",
        "[]",
        str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, f"pdfium_probe layout CLI failed: {res.stderr}"
    assert out_json.is_file()

    with open(out_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list)
    assert len(data) == 3
    assert [elem["element_type"] for elem in data] == ["text", "text", "text"]
    assert [elem["order"] for elem in data] == [0, 1, 2]
    assert [elem["text"] for elem in data] == [
        "Outside of CropBox",
        "Header in CropBox",
        "Normal Body Text",
    ]

    elements = extract_layout_with_rust_probe(synth_pdf, 0, [])
    assert len(elements) == 3
    for idx, elem in enumerate(elements):
        assert isinstance(elem, LayoutElement)
        assert elem.type == "text"
        assert elem.order == idx
        assert isinstance(elem.bbox, BBox)
        assert elem.bbox.x1 > elem.bbox.x0
        assert elem.bbox.y1 > elem.bbox.y0
        assert len(elem.lines) > 0
        assert isinstance(elem.lines[0], Line)
        assert len(elem.words) > 0
        assert isinstance(elem.words[0], Word)

    assert [e.content for e in elements] == [
        "Outside of CropBox",
        "Header in CropBox",
        "Normal Body Text",
    ]


def test_rust_layout_adapter_with_tables(tmp_path: Path) -> None:
    synth_pdf = _get_synth_pdf("synth_crop_offset.pdf")

    # Table covering the "Header in CropBox" region [100.0, 107.33, 219.04, 122.95]
    tbl_bbox = BBox(100.0, 100.0, 220.0, 150.0)
    table_obj = Table(bbox=tbl_bbox, rows=2, cols=2, source="wireless")

    elements = extract_layout_with_rust_probe(synth_pdf, 0, [table_obj])
    assert len(elements) == 3
    assert [e.type for e in elements] == ["text", "table", "text"]
    assert [e.order for e in elements] == [0, 1, 2]

    # Verify Header in CropBox was deducted, and the table element was injected
    assert elements[0].type == "text"
    assert elements[0].content == "Outside of CropBox"

    assert elements[1].type == "table"
    assert elements[1].content is table_obj
    assert getattr(elements[1], "table", None) is table_obj
    assert pytest.approx(elements[1].bbox.x0, abs=0.1) == 100.0
    assert pytest.approx(elements[1].bbox.y0, abs=0.1) == 100.0
    assert pytest.approx(elements[1].bbox.x1, abs=0.1) == 220.0
    assert pytest.approx(elements[1].bbox.y1, abs=0.1) == 150.0

    assert elements[2].type == "text"
    assert elements[2].content == "Normal Body Text"

    # Also test table passed as dict format
    dict_table = {"bbox": [100.0, 100.0, 220.0, 150.0], "table_id": 99}
    elements_dict = extract_layout_with_rust_probe(synth_pdf, 0, [dict_table])
    assert len(elements_dict) == 3
    assert elements_dict[1].type == "table"
    assert elements_dict[1].content == dict_table

    # Test real PDF sample if present
    repo_root = _get_repo_root()
    real_pdf = repo_root / "test.pdf"
    if real_pdf.is_file():
        p27_table = Table(
            bbox=BBox(20.0, 100.0, 575.0, 450.0),
            rows=27,
            cols=2,
            source="wireless",
        )
        real_elements = extract_layout_with_rust_probe(real_pdf, 27, [p27_table])
        assert len(real_elements) > 1
        assert any(e.type == "table" for e in real_elements)
        assert [e.order for e in real_elements] == list(range(len(real_elements)))


def test_rust_and_python_layout_parity() -> None:
    synth_pdf = _get_synth_pdf("synth_crop_offset.pdf")
    tbl_bbox = BBox(100.0, 100.0, 220.0, 150.0)
    table_obj = Table(bbox=tbl_bbox, rows=2, cols=2, source="wireless")

    # 1. Baseline Python layout
    norm = normalize_with_rust_probe({"source_file": str(synth_pdf), "page_index": 0})
    assert norm is not None
    adapter = PdfiumPageAdapter(norm, pdf_path=synth_pdf)

    te = TextExtractor()
    lm = LayoutMapper()
    lb = LayoutBuilder()

    py_blocks = te.extract_layout_blocks(adapter, [table_obj])
    py_mapped = lm.map_blocks(py_blocks)
    py_elements = lb.build(py_mapped, [table_obj], [])

    # 2. Rust layout
    rust_elements = extract_layout_with_rust_probe(synth_pdf, 0, [table_obj])

    # 3. Parity validation
    assert len(rust_elements) == len(py_elements)
    assert [e.type for e in rust_elements] == [e.type for e in py_elements]
    assert [e.order for e in rust_elements] == [e.order for e in py_elements]

    for r_elem, py_elem in zip(rust_elements, py_elements):
        assert r_elem.type == py_elem.type
        assert r_elem.order == py_elem.order
        if r_elem.type == "text":
            assert r_elem.content == py_elem.content
        assert pytest.approx(r_elem.bbox.x0, abs=0.5) == py_elem.bbox.x0
        assert pytest.approx(r_elem.bbox.y0, abs=0.5) == py_elem.bbox.y0
        assert pytest.approx(r_elem.bbox.x1, abs=0.5) == py_elem.bbox.x1
        assert pytest.approx(r_elem.bbox.y1, abs=0.5) == py_elem.bbox.y1

    # 4. Parity check on synth_invisible_text without tables
    synth_inv = _get_synth_pdf("synth_invisible_text.pdf")
    norm_inv = normalize_with_rust_probe({"source_file": str(synth_inv), "page_index": 0})
    assert norm_inv is not None
    adapter_inv = PdfiumPageAdapter(norm_inv, pdf_path=synth_inv)

    py_blocks_inv = te.extract_layout_blocks(adapter_inv, [])
    py_mapped_inv = lm.map_blocks(py_blocks_inv)
    py_elements_inv = lb.build(py_mapped_inv, [], [])

    rust_elements_inv = extract_layout_with_rust_probe(synth_inv, 0, [])

    assert len(rust_elements_inv) == len(py_elements_inv)
    assert [e.type for e in rust_elements_inv] == [e.type for e in py_elements_inv]
    assert [e.order for e in rust_elements_inv] == [e.order for e in py_elements_inv]
    assert [e.content for e in rust_elements_inv] == [e.content for e in py_elements_inv]
