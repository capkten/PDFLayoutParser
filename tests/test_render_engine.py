"""Tests for the render engine."""

from pathlib import Path

import pytest

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
