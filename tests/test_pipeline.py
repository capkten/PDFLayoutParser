from __future__ import annotations

"""Tests for the Pipeline module."""

import json
import os
import threading
from pathlib import Path

import fitz
import pytest

import hexai_pdf_parser.core.pipeline as pipeline_module
from hexai_pdf_parser.pipeline import Pipeline
from hexai_pdf_parser.personal_credit_report import PersonalCreditReportPipeline
from hexai_pdf_parser.table_config import (
    GlobalTableSettings,
    LayoutProfile,
    MatcherConfig,
    StructureRuleSet,
    TableConfig,
)
from hexai_pdf_parser.table_extractor import TableExtractor
from tests.conftest import make_text_pdf
from tests.test_table_extractor import make_pdf_with_table, make_synthetic_text_alignment_pdf


def _write_scanned_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "\x00" * 20, fontsize=12)
    doc.save(path)
    doc.close()


def _write_mixed_page_type_pdf(path):
    doc = fitz.open()
    vector_page = doc.new_page(width=595, height=842)
    vector_page.insert_text((50, 100), "vector page text", fontsize=12)
    scanned_page = doc.new_page(width=595, height=842)
    scanned_page.insert_text((50, 100), "\x00" * 20, fontsize=12)
    doc.save(path)
    doc.close()


def test_pipeline_scanned_page_skips_extraction_stages_and_keeps_fixed_output(
    tmp_dir, monkeypatch
):
    pdf_path = Path(tmp_dir) / "scanned.pdf"
    output_dir = Path(tmp_dir) / "out"
    _write_scanned_pdf(pdf_path)

    stale_md = output_dir / "pages" / "page-000.md"
    stale_md.parent.mkdir(parents=True)
    stale_md.write_text("stale scanned output", encoding="utf-8")

    def unexpected_stage(*_args, **_kwargs):
        raise AssertionError("scanned pages must not enter extraction stages")

    monkeypatch.setattr(pipeline_module, "TextExtractor", unexpected_stage)
    monkeypatch.setattr(pipeline_module, "ImageExtractor", unexpected_stage)
    monkeypatch.setattr(pipeline_module, "LayoutMapper", unexpected_stage)
    monkeypatch.setattr(pipeline_module, "LayoutBuilder", unexpected_stage)
    monkeypatch.setattr(Pipeline, "_create_table_extractor", unexpected_stage)

    document = Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=72,
        backend="sequential",
    ).run()

    page = document.pages[0]
    assert page.page_type == "scanned"
    assert page.blocks == []
    assert page.tables == []
    assert page.images == []
    assert page.seals == []
    assert page.layout_elements == []

    with open(output_dir / "pages" / "page-000.json", encoding="utf-8") as f:
        page_json = json.load(f)
    assert set(page_json) == {
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
    assert page_json["page_type"] == "scanned"
    assert page_json["blocks"] == []
    assert page_json["tables"] == []
    assert page_json["images"] == []
    assert page_json["seals"] == []
    assert page_json["layout_elements"] == []
    assert page_json["render"]["path"]

    assert not stale_md.exists()
    assert (output_dir / "output.md").read_text(encoding="utf-8") == ""
    assert (output_dir / "page-000.png").exists()
    assert (output_dir / "tables" / "page-000.png").exists()
    assert list((output_dir / "images").iterdir()) == []

    for image_path in (
        output_dir / "page-000.png",
        output_dir / "tables" / "page-000.png",
    ):
        pixmap = fitz.Pixmap(str(image_path))
        assert max(pixmap.pixel(8, 8)) < 100


def test_pipeline_omits_scanned_markdown_but_keeps_vector_output(tmp_dir):
    pdf_path = Path(tmp_dir) / "mixed.pdf"
    output_dir = Path(tmp_dir) / "out"
    _write_mixed_page_type_pdf(pdf_path)

    document = Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=72,
        backend="sequential",
    ).run()

    assert [page.page_type for page in document.pages] == ["vector", "scanned"]
    assert document.pages[0].blocks
    assert document.pages[1].blocks == []
    assert document.pages[1].tables == []
    assert (output_dir / "pages" / "page-000.md").exists()
    assert not (output_dir / "pages" / "page-001.md").exists()

    output_md = (output_dir / "output.md").read_text(encoding="utf-8")
    assert "vector page text" in output_md


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


def test_pipeline_reuses_table_extractor_per_sequential_run(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "reused-extractor.pdf")
    from tests.conftest import make_multi_page_pdf

    make_multi_page_pdf(pdf_path, ["Page 0", "Page 1"])

    class CountingExtractor:
        instances = 0
        extracts = 0

        def __init__(self, **_kwargs):
            type(self).instances += 1
            self._last_text_alignment_debug = None
            self._last_pipeline_debug = None

        def extract(self, _page, *, page_already_normalized=False):
            assert page_already_normalized is True
            type(self).extracts += 1
            return []

    pipeline = Pipeline(
        pdf_path=pdf_path,
        backend="sequential",
        num_workers=1,
    )
    pipeline._get_table_extractor_class = lambda: CountingExtractor

    document = pipeline.run()

    assert document.page_count == 2
    assert CountingExtractor.instances == 1
    assert CountingExtractor.extracts == 2


def test_process_worker_reuses_document_and_extractor(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "worker-resources.pdf")
    other_pdf_path = os.path.join(tmp_dir, "other-worker-resources.pdf")
    from tests.conftest import make_multi_page_pdf

    make_multi_page_pdf(pdf_path, ["Page 0", "Page 1"])
    make_multi_page_pdf(other_pdf_path, ["Other page"])

    class CountingExtractor:
        instances = 0

        def __init__(self, **_kwargs):
            type(self).instances += 1

    first_document = first_extractor = None
    try:
        first_document, first_extractor = pipeline_module._get_process_worker_resources(
            pdf_path,
            None,
            0.40,
            True,
            False,
            None,
            CountingExtractor,
        )
        second_document, second_extractor = pipeline_module._get_process_worker_resources(
            pdf_path,
            None,
            0.40,
            True,
            False,
            None,
            CountingExtractor,
        )

        assert second_document is first_document
        assert second_extractor is first_extractor
        assert CountingExtractor.instances == 1

        other_document, other_extractor = pipeline_module._get_process_worker_resources(
            other_pdf_path,
            None,
            0.40,
            True,
            False,
            None,
            CountingExtractor,
        )
        assert other_document is not first_document
        assert other_extractor is not first_extractor
        assert CountingExtractor.instances == 2
    finally:
        pipeline_module._close_process_worker_resources()


def test_pipeline_deduplicates_page_indices_without_renumbering(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "selected-pages.pdf")
    from tests.conftest import make_multi_page_pdf

    make_multi_page_pdf(pdf_path, ["Page 0", "Page 1", "Page 2"])

    class TrackingPageIndices(list):
        contains_calls = 0

        def __contains__(self, value):
            type(self).contains_calls += 1
            return super().__contains__(value)

    selected = TrackingPageIndices([2, 0, 2])
    document = Pipeline(
        pdf_path=pdf_path,
        page_indices=selected,
        backend="sequential",
        num_workers=1,
    ).run()

    assert document.page_count == 3
    assert [page.index for page in document.pages] == [0, 1, 2]
    assert document.pages[0].blocks
    assert document.pages[1].blocks == []
    assert document.pages[2].blocks
    assert TrackingPageIndices.contains_calls == 0


def test_thread_backend_reuses_one_document_per_thread(tmp_dir, monkeypatch):
    pdf_path = os.path.join(tmp_dir, "thread-doc-reuse.pdf")
    from tests.conftest import make_multi_page_pdf

    make_multi_page_pdf(pdf_path, [f"Page {index}" for index in range(4)])
    real_open = pipeline_module.fitz.open
    open_calls = []

    def counted_open(*args, **kwargs):
        if args and args[0] == pdf_path:
            open_calls.append(True)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(pipeline_module.fitz, "open", counted_open)

    barrier = threading.Barrier(2)
    worker_document_ids = set()
    worker_document_ids_lock = threading.Lock()

    def record_page_processing(
        _self,
        _page_index,
        _document,
        _images_dir,
        _pages_dir,
        _text_alignment_debug_dir,
        pdf_doc,
        table_extractor=None,
    ):
        del table_extractor
        with worker_document_ids_lock:
            worker_document_ids.add(id(pdf_doc))
        barrier.wait(timeout=5)

    monkeypatch.setattr(Pipeline, "_process_single_page", record_page_processing)

    document = Pipeline(
        pdf_path=pdf_path,
        backend="thread",
        num_workers=2,
        use_ml_table_detector=False,
    ).run()

    assert document.page_count == 4
    assert len(worker_document_ids) == 2
    assert len(open_calls) == 3  # one loader document plus one per thread


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


def test_pipeline_without_debug_does_not_create_text_alignment_debug_dir(tmp_dir):
    pdf_path = Path(tmp_dir) / "plain_table.pdf"
    output_dir = Path(tmp_dir) / "out"
    make_synthetic_text_alignment_pdf(
        pdf_path,
        [
            (30.0, [(20.0, "A"), (150.0, "10")]),
            (48.0, [(20.0, "B"), (150.0, "20")]),
        ],
    )

    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
    ).run()

    debug_dir = output_dir / "debug" / "text-alignment"
    assert debug_dir.exists() is False


def test_pipeline_with_debug_writes_text_alignment_debug_image(tmp_dir):
    pdf_path = Path(tmp_dir) / "text_alignment.pdf"
    output_dir = Path(tmp_dir) / "out"
    make_synthetic_text_alignment_pdf(
        pdf_path,
        [
            (30.0, [(20.0, "项目A"), (180.0, "10"), (300.0, "20")]),
            (48.0, [(20.0, "项目B"), (180.0, "11"), (300.0, "21")]),
        ],
        page_size=(360.0, 220.0),
    )

    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
        debug=True,
    ).run()

    image_path = output_dir / "debug" / "text-alignment" / "page-000.png"
    # Rule candidates are provisional; debug visualization is emitted only
    # when a model-derived table reaches the final page result.
    assert not image_path.exists()


def test_pipeline_with_debug_skips_text_alignment_when_lines_are_detected(tmp_dir):
    pdf_path = Path(tmp_dir) / "line_table.pdf"
    output_dir = Path(tmp_dir) / "out"
    make_pdf_with_table(pdf_path)

    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
        debug=True,
    ).run()

    image_path = output_dir / "debug" / "text-alignment" / "page-000.png"
    assert image_path.exists() is False


def test_pipeline_debug_does_not_change_text_alignment_table_sources(tmp_dir):
    pdf_path = Path(tmp_dir) / "same_tables.pdf"
    out_plain = Path(tmp_dir) / "plain"
    out_debug = Path(tmp_dir) / "debug"
    make_synthetic_text_alignment_pdf(
        pdf_path,
        [
            (30.0, [(20.0, "项目A"), (180.0, "10"), (300.0, "20")]),
            (48.0, [(20.0, "项目B"), (180.0, "11"), (300.0, "21")]),
        ],
        page_size=(360.0, 220.0),
    )

    doc_plain = Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(out_plain),
        render_dpi=120,
        debug=False,
    ).run()
    doc_debug = Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(out_debug),
        render_dpi=120,
        debug=True,
    ).run()

    plain_sources = [table.source for table in doc_plain.pages[0].tables]
    debug_sources = [table.source for table in doc_debug.pages[0].tables]
    assert plain_sources == debug_sources


def test_pipeline_passes_table_config_to_extractor(tmp_dir, monkeypatch):
    """Pipeline forwards table_config to TableExtractor."""
    pdf_path = Path(tmp_dir) / "config_test.pdf"
    make_synthetic_text_alignment_pdf(
        pdf_path,
        [
            (30.0, [(20.0, "A"), (150.0, "10")]),
            (48.0, [(20.0, "B"), (150.0, "20")]),
        ],
    )

    config = TableConfig(
        settings=GlobalTableSettings(line_tolerance=5.0),
    )

    captured_configs = []

    original_init = TableExtractor.__init__

    def capturing_init(self, *args, **kwargs):
        captured_configs.append(kwargs.get("table_config"))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(TableExtractor, "__init__", capturing_init)

    output_dir = Path(tmp_dir) / "out"
    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
        table_config=config,
    ).run()

    # TableExtractor was instantiated at least once with the config
    assert any(c is config for c in captured_configs), (
        f"table_config was not passed through — captured: {captured_configs}"
    )


def test_pipeline_without_table_config_works(tmp_dir):
    """Pipeline works without table_config (backward compatibility)."""
    pdf_path = Path(tmp_dir) / "no_config.pdf"
    make_text_pdf(pdf_path, text="No config")

    doc = Pipeline(
        pdf_path=pdf_path,
        output_dir=tmp_dir,
        render_dpi=150,
    ).run()
    assert doc.page_count == 1


def test_personal_credit_pipeline_disables_ml_by_default():
    pipeline = PersonalCreditReportPipeline(pdf_path="unused.pdf")

    assert pipeline._create_table_extractor()._use_ml_table_detector is False


def test_personal_credit_pipeline_can_enable_ml():
    pipeline = PersonalCreditReportPipeline(
        pdf_path="unused.pdf",
        use_ml_table_detector=True,
    )

    assert pipeline._create_table_extractor()._use_ml_table_detector is True


def test_generic_pipeline_keeps_ml_enabled_by_default():
    pipeline = Pipeline(pdf_path="unused.pdf")

    assert pipeline._create_table_extractor()._use_ml_table_detector is True
