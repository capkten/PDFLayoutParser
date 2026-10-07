"""Tests for the render engine."""

from pathlib import Path

import fitz
import pytest

import hexai_pdf_parser.writers.render_engine as render_engine_module
from hexai_pdf_parser.render_engine import RenderEngine
from tests.conftest import make_text_pdf


class TestRenderEngine:
    def test_render_page_to_image(self, tmp_dir):
        """Render a single-page PDF to PNG and verify RenderInfo."""
        pdf_path = Path(tmp_dir) / "render_test.pdf"
        make_text_pdf(pdf_path, text="Hello Render")

        engine = RenderEngine(output_dir=tmp_dir, dpi=150)
        render_info = engine.render(str(pdf_path), 0)

        assert render_info.path is not None
        assert Path(render_info.path).exists()
        assert render_info.dpi == 150
        assert render_info.width is not None
        assert render_info.height is not None

    def test_render_passes_page_type_to_visual_annotation(self, tmp_dir, monkeypatch):
        pdf_path = Path(tmp_dir) / "render_scanned.pdf"
        make_text_pdf(pdf_path, text="Rendered page")
        calls = []

        monkeypatch.setattr(
            render_engine_module,
            "draw_page_type_label",
            lambda _page, page_type: calls.append(page_type),
            raising=False,
        )

        RenderEngine(output_dir=tmp_dir, dpi=72).render(
            str(pdf_path), 0, page_type="scanned"
        )

        assert calls == ["scanned"]

    def test_render_page_uses_existing_document(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "render_existing_page.pdf"
        make_text_pdf(pdf_path, text="Existing page")

        document = fitz.open(str(pdf_path))
        try:
            render_info = RenderEngine(output_dir=tmp_dir, dpi=72).render_page(
                document,
                page_index=0,
                page=document[0],
                page_already_normalized=True,
            )
        finally:
            document.close()

        assert render_info.path is not None
        assert Path(render_info.path).exists()

    def test_render_page_can_skip_normalization(self, tmp_dir, monkeypatch):
        pdf_path = Path(tmp_dir) / "render_no_normalization.pdf"
        make_text_pdf(pdf_path, text="Already normalized")
        calls = []
        monkeypatch.setattr(
            render_engine_module,
            "normalize_page_rotation",
            lambda _page: calls.append(True),
        )

        document = fitz.open(str(pdf_path))
        try:
            RenderEngine(output_dir=tmp_dir, dpi=72).render_page(
                document,
                page_index=0,
                page=document[0],
                page_already_normalized=True,
            )
        finally:
            document.close()

        assert calls == []
