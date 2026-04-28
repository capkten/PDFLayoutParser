"""Tests for the Pipeline module."""

import os

import pytest

from pdflayoutparser.pipeline import Pipeline
from tests.conftest import make_text_pdf


def test_pipeline_end_to_end(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "pipeline.pdf")
    make_text_pdf(pdf_path, text="Pipeline Test")

    pipeline = Pipeline(pdf_path=pdf_path, output_dir=tmp_dir, render_dpi=150)
    document = pipeline.run()

    assert document.file_name.endswith("pipeline.pdf")
    assert document.page_count == 1
    assert len(document.pages) == 1

    page = document.pages[0]
    assert len(page.blocks) >= 1
    assert len(page.layout_elements) >= 1

    assert os.path.exists(os.path.join(tmp_dir, "output.json"))
    assert os.path.exists(os.path.join(tmp_dir, "output.md"))
    assert os.path.exists(os.path.join(tmp_dir, "page-000.png"))
