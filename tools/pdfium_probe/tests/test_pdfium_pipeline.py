from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

import pytest

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from pdfium_pipeline_adapter import (
    _find_pdfium_probe_bin,
    parse_pdf_with_rust_probe,
)


def _get_synth_pdf(name: str = "synth_crop_offset.pdf") -> Path:
    probe_root = _TEST_DIR.parent
    pdf_path = probe_root / "test_data" / "synthetic" / name
    assert pdf_path.is_file(), f"Synthetic PDF not found: {pdf_path}"
    return pdf_path


def test_parse_pdf_with_rust_probe_end_to_end(tmp_path: Path) -> None:
    pdf_path = _get_synth_pdf("synth_crop_offset.pdf")
    out_dir = tmp_path / "e2e_out"

    result = parse_pdf_with_rust_probe(
        pdf_path=str(pdf_path),
        output_dir=str(out_dir),
        render_dpi=72.0,
        export_renders=True,
        export_pages=True,
    )

    assert isinstance(result, dict)
    assert "document" in result
    assert "pages" in result
    assert len(result["pages"]) >= 1

    out_json = out_dir / "output.json"
    out_md = out_dir / "output.md"
    page_json = out_dir / "pages" / "page-000.json"
    page_md = out_dir / "pages" / "page-000.md"
    render_png = out_dir / "renders" / "page-000.png"

    for p in (out_json, out_md, page_json, page_md, render_png):
        assert p.is_file(), f"Expected output file missing: {p}"
        assert p.stat().st_size > 0, f"Expected non-empty output file: {p}"


def test_parse_pdf_page_selection(tmp_path: Path) -> None:
    pdf_path = _get_synth_pdf("synth_crop_offset.pdf")
    out_dir = tmp_path / "page_sel_out"

    result = parse_pdf_with_rust_probe(
        pdf_path=str(pdf_path),
        output_dir=str(out_dir),
        page_indices=[0],
        render_dpi=72.0,
    )

    assert isinstance(result, dict)
    assert "pages" in result
    assert len(result["pages"]) == 1
    assert result["pages"][0]["index"] == 0


def test_parse_pdf_fallback_when_binary_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pdfium_pipeline_adapter

    # Monkeypatch binary finder to return None, forcing Python fallback
    monkeypatch.setattr(pdfium_pipeline_adapter, "_find_pdfium_probe_bin", lambda: None)

    pdf_path = _get_synth_pdf("synth_crop_offset.pdf")
    out_dir = tmp_path / "fallback_out"

    result = parse_pdf_with_rust_probe(
        pdf_path=str(pdf_path),
        output_dir=str(out_dir),
        page_indices=[0],
        render_dpi=72.0,
    )

    assert isinstance(result, dict)
    assert "document" in result
    assert "pages" in result
    assert len(result["pages"]) == 1
    assert (out_dir / "output.json").is_file()
    assert (out_dir / "output.json").stat().st_size > 0


def test_parse_pdf_export_flags(tmp_path: Path) -> None:
    pdf_path = _get_synth_pdf("synth_crop_offset.pdf")
    out_dir = tmp_path / "flags_out"

    result = parse_pdf_with_rust_probe(
        pdf_path=str(pdf_path),
        output_dir=str(out_dir),
        render_dpi=72.0,
        export_renders=False,
        export_pages=False,
    )

    assert isinstance(result, dict)
    assert "pages" in result

    out_json = out_dir / "output.json"
    out_md = out_dir / "output.md"
    render_png = out_dir / "renders" / "page-000.png"
    page_json = out_dir / "pages" / "page-000.json"

    assert out_json.is_file()
    assert out_md.is_file()
    assert not render_png.is_file()
    assert not page_json.is_file()

