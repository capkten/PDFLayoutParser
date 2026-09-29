import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from run_behavioral_matrix import (
    canonical_json_bytes,
    canonical_sha256,
    render_table_overlays,
    run_behavioral_matrix,
)

PROBE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "single_behavioral_fixture.json"


def test_matrix_writes_one_result_per_fixture(tmp_path: Path) -> None:
    summary = run_behavioral_matrix(
        fixture_manifest=FIXTURES,
        pdfium_roots=[PROBE_ROOT / "test_data"],
        output_dir=tmp_path / "run",
    )
    assert summary["fixture_count"] == 1
    assert (tmp_path / "run" / "run-01" / "synth_mixed_fonts" / "result.json").is_file()
    assert (tmp_path / "run" / "run-01" / "synth_mixed_fonts" / "ledger.json").is_file()


def test_matrix_hashes_match_for_repeated_identical_inputs(tmp_path: Path) -> None:
    summary = run_behavioral_matrix(
        fixture_manifest=FIXTURES,
        pdfium_roots=[PROBE_ROOT / "test_data"] * 3,
        output_dir=tmp_path / "repeat",
    )
    assert summary["deterministic"]["all_equal"] is True


def test_render_table_overlays_writes_both_parser_pngs(tmp_path: Path) -> None:
    import fitz
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    document = fitz.open()
    page = document.new_page(width=100, height=100)
    page.insert_text((20, 30), "A", fontsize=10)
    pdf_path = tmp_path / "overlay-source.pdf"
    document.save(pdf_path)
    document.close()
    table = Table(
        bbox=BBox(10, 10, 50, 50),
        rows=1,
        cols=1,
        cells=[Cell("A", 0, 0, BBox(10, 10, 50, 50))],
    )

    paths = render_table_overlays(
        pdf_path, 0, [table], [table], tmp_path / "overlays"
    )

    assert set(paths) == {"pdfium", "pymupdf"}
    assert all(Path(path).is_file() for path in paths.values())


def test_blocked_input_on_missing_pdf(tmp_path: Path) -> None:
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(
        json.dumps(
            [
                {
                    "name": "missing_pdf_sample",
                    "pdf_root": "probe",
                    "pdf_path": "test_data/non_existent.pdf",
                    "pdfium_raw_snapshot": "pdfium_output/synth_mixed_fonts_pdfium.json",
                    "pymupdf_baseline": "baseline/synth_mixed_fonts_pymupdf.json",
                    "page_index": 0,
                    "expected_page_type": "vector",
                    "table_regions": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    summary = run_behavioral_matrix(
        fixture_manifest=bad_manifest,
        pdfium_roots=[PROBE_ROOT / "test_data"],
        output_dir=tmp_path / "out",
    )
    assert summary["blocked_input"] >= 1
    assert (
        tmp_path / "out" / "run-01" / "missing_pdf_sample" / "result.json"
    ).is_file()
    res = json.loads(
        (
            tmp_path / "out" / "run-01" / "missing_pdf_sample" / "result.json"
        ).read_text(encoding="utf-8")
    )
    assert res["status"] == "blocked_input"


def test_blocked_input_on_sha_mismatch(tmp_path: Path) -> None:
    # Create a synthetic PDF and raw JSON where source_file_sha256 intentionally mismatches
    dummy_pdf = tmp_path / "sample.pdf"
    import fitz

    doc = fitz.open()
    doc.new_page(width=100, height=100)
    doc.save(dummy_pdf)
    doc.close()

    raw_dir = tmp_path / "raw_root" / "pdfium_output"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_json = raw_dir / "sample_pdfium.json"
    raw_json.write_text(
        json.dumps(
            {
                "schema_version": "pdfium_raw_snapshot_v1.1",
                "generator": "pdfium_probe_0.1.0",
                "source_file": "sample.pdf",
                "source_file_sha256": "0" * 64,  # intentional wrong hash
                "native_library_sha256": "d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b",
                "native_library_expected_sha256": "d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b",
                "page_count": 1,
                "pages": [{"page_index": 0, "spans": [], "drawings": []}],
            }
        ),
        encoding="utf-8",
    )

    base_dir = tmp_path / "raw_root" / "baseline"
    base_dir.mkdir(parents=True, exist_ok=True)
    base_json = base_dir / "sample_pymupdf.json"
    base_json.write_text(
        json.dumps(
            {
                "generator": "PyMuPDF_1.24.0",
                "source_file": "sample.pdf",
                "source_file_sha256": "0" * 64,
                "page_count": 1,
                "pages": [{"page_index": 0, "spans": [], "drawings": []}],
            }
        ),
        encoding="utf-8",
    )

    manifest_file = tmp_path / "mismatch_manifest.json"
    manifest_file.write_text(
        json.dumps(
            [
                {
                    "name": "mismatched_sample",
                    "pdf_root": "probe",
                    "pdf_path": str(dummy_pdf.relative_to(tmp_path)),
                    "pdfium_raw_snapshot": "pdfium_output/sample_pdfium.json",
                    "pymupdf_baseline": "baseline/sample_pymupdf.json",
                    "page_index": 0,
                    "expected_page_type": "vector",
                    "table_regions": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    # Monkeypatch probe root so relative path resolves to dummy_pdf
    import run_behavioral_matrix as rbm

    orig_get_probe_root = rbm.get_probe_root
    rbm.get_probe_root = lambda: tmp_path

    try:
        summary = run_behavioral_matrix(
            fixture_manifest=manifest_file,
            pdfium_roots=[tmp_path / "raw_root"],
            output_dir=tmp_path / "mismatch_out",
        )
        assert summary["blocked_input"] >= 1
        res = json.loads(
            (
                tmp_path
                / "mismatch_out"
                / "run-01"
                / "mismatched_sample"
                / "result.json"
            ).read_text(encoding="utf-8")
        )
        assert res["status"] == "blocked_input"
    finally:
        rbm.get_probe_root = orig_get_probe_root


def test_canonical_json_bytes_and_sha256() -> None:
    data1 = {"b": 1.234567, "a": "hello"}
    data2 = {"a": "hello", "b": 1.2346}
    assert canonical_json_bytes(data1) == canonical_json_bytes(data2)
    assert canonical_sha256(data1) == canonical_sha256(data2)
