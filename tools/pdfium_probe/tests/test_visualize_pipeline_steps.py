from pathlib import Path
import sys

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import json
import tempfile
from typing import Any, Dict

import pytest

from visualize_pipeline_steps import (
    SampleConfig,
    generate_visualization_readme,
    get_font,
    get_probe_root,
    get_repo_root,
    run_pipeline_for_sample,
)


def test_get_font_returns_usable_font():
    font = get_font(12, bold=False)
    assert font is not None


def test_sample_config_initialization():
    probe_root = get_probe_root()
    repo_root = get_repo_root()
    cfg = SampleConfig(
        name="test_sample",
        pdf_path=probe_root / "test_data/synthetic/synth_invisible_text.pdf",
        page_index=0,
        table_regions=[],
        pdfium_raw_path=probe_root / "test_data/pdfium_output/synth_invisible_text_pdfium.json",
        pymupdf_baseline_path=probe_root / "test_data/baseline/synth_invisible_text_pymupdf.json",
        description="Test sample description",
    )
    assert cfg.name == "test_sample"
    assert cfg.page_index == 0


def test_run_pipeline_for_synthetic_sample(tmp_path: Path):
    probe_root = get_probe_root()
    sample = SampleConfig(
        name="synth_invisible_text",
        pdf_path=probe_root / "test_data/synthetic/synth_invisible_text.pdf",
        page_index=0,
        table_regions=[],
        pdfium_raw_path=probe_root / "test_data/pdfium_output/synth_invisible_text_pdfium.json",
        pymupdf_baseline_path=probe_root / "test_data/baseline/synth_invisible_text_pymupdf.json",
        description="Synthetic sample test",
    )

    meta = run_pipeline_for_sample(sample, tmp_path, dpi=72)
    sample_dir = tmp_path / "synth_invisible_text"

    assert sample_dir.is_dir()
    assert (sample_dir / "01_raw_spans_and_drawings.png").is_file()
    assert (sample_dir / "02_lines_and_blocks.png").is_file()
    assert (sample_dir / "03_table_recovery.png").is_file()
    assert (sample_dir / "04_final_reading_order.png").is_file()
    assert (sample_dir / "pdfium_01_raw.png").is_file()
    assert (sample_dir / "pymupdf_01_raw.png").is_file()
    assert (sample_dir / "meta.json").is_file()

    assert meta["sample_name"] == "synth_invisible_text"
    assert meta["stats"]["pdfium"]["spans"] > 0

    generate_visualization_readme([meta], tmp_path)
    assert (tmp_path / "README.md").is_file()
    readme_content = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "synth_invisible_text" in readme_content
