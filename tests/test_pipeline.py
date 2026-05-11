"""Tests for the Pipeline module."""

import json
import os

import fitz
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


def test_pipeline_sorts_seals_into_page_order(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "seal_order.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Top")
    page.insert_text((72, 320), "Bottom")
    doc.save(pdf_path)
    doc.close()

    pipeline = Pipeline(
        pdf_path=pdf_path,
        output_dir=tmp_dir,
        render_dpi=150,
        seal_coords=[
            {
                "page_index": 0,
                "x0": 60,
                "y0": 180,
                "x1": 120,
                "y1": 240,
            }
        ],
    )
    document = pipeline.run()

    page = document.pages[0]
    assert [element.type for element in page.layout_elements] == [
        "text",
        "seal",
        "text",
    ]


def test_pipeline_writes_timing_report(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "timing.pdf")
    make_text_pdf(pdf_path, text="Timing Test")

    pipeline = Pipeline(pdf_path=pdf_path, output_dir=tmp_dir, render_dpi=150)
    pipeline.run()

    timing_path = os.path.join(tmp_dir, "timings.json")
    assert os.path.exists(timing_path)

    with open(timing_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["page_count"] == 1
    assert data["total_seconds"] >= 0
    assert data["avg_seconds_per_page"] >= 0
    assert "stage_totals" in data
    assert "page_totals" in data
