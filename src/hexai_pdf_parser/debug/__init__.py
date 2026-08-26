"""Debugging, diagnostic visualizers, and performance benchmarking utilities."""

from hexai_pdf_parser.debug.table_visualizer import draw_tables_on_page, render_table_visualization
from hexai_pdf_parser.debug.pipeline_debug import render_pipeline_debug_page
from hexai_pdf_parser.debug.hybrid_table_debug import export_hybrid_debug
from hexai_pdf_parser.debug.text_alignment_debug import render_text_alignment_debug_page
from hexai_pdf_parser.debug.benchmark_utils import summarize_timings

__all__ = [
    "draw_tables_on_page",
    "render_table_visualization",
    "render_pipeline_debug_page",
    "export_hybrid_debug",
    "render_text_alignment_debug_page",
    "summarize_timings",
]
