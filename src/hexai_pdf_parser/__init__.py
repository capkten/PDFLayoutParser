"""hexai_pdf_parser: High-performance layout and table parser for PDF documents."""

import importlib
import sys
from importlib.abc import MetaPathFinder

# Ensure PyMuPDF (fitz) compatibility across packaging variants
try:
    import fitz
    if not hasattr(fitz, "open") or not hasattr(fitz, "Page"):
        import pymupdf as _pymupdf
        sys.modules["fitz"] = _pymupdf
except ImportError:
    try:
        import pymupdf as _pymupdf
        sys.modules["fitz"] = _pymupdf
    except ImportError:
        pass

# Dynamic backward compatibility mapping for legacy module paths
_LEGACY_MODULE_MAP = {
    "models": "hexai_pdf_parser.core.models",
    "loader": "hexai_pdf_parser.core.loader",
    "pipeline": "hexai_pdf_parser.core.pipeline",
    "pdf_parser": "hexai_pdf_parser.core.pdf_parser",
    "text_extractor": "hexai_pdf_parser.extractors.text_extractor",
    "image_extractor": "hexai_pdf_parser.extractors.image_extractor",
    "layout_mapper": "hexai_pdf_parser.extractors.layout_mapper",
    "layout_builder": "hexai_pdf_parser.extractors.layout_builder",
    "language_detector": "hexai_pdf_parser.extractors.language_detector",
    "personal_credit_report": "hexai_pdf_parser.extractors.personal_credit_report",
    "table_extractor": "hexai_pdf_parser.tables.table_extractor",
    "table_config": "hexai_pdf_parser.tables.table_config",
    "table_header_normalizer": "hexai_pdf_parser.tables.normalizers.table_header_normalizer",
    "table_profile_matcher": "hexai_pdf_parser.tables.table_profile_matcher",
    "table_region_rules": "hexai_pdf_parser.tables.table_region_rules",
    "table_structure_rules": "hexai_pdf_parser.tables.table_structure_rules",
    "table_rule_handlers": "hexai_pdf_parser.tables.table_rule_handlers",
    "table_template_engine": "hexai_pdf_parser.tables.table_template_engine",
    "wireless_table_recovery": "hexai_pdf_parser.tables.wireless_table_recovery",
    "wired_table_extractor": "hexai_pdf_parser.tables.extractors.wired_table_extractor",
    "english_table_extractor": "hexai_pdf_parser.tables.extractors.english_table_extractor",
    "chinese_table_extractor": "hexai_pdf_parser.tables.extractors.chinese_table_extractor",
    "wireless_table_extractor": "hexai_pdf_parser.tables.extractors.wireless_table_extractor",
    "financial_header_handler": "hexai_pdf_parser.tables.normalizers.financial_header_handler",
    "ml_table_detector": "hexai_pdf_parser.ml.ml_table_detector",
    "yolo_layout_utils": "hexai_pdf_parser.ml.yolo_layout_utils",
    "json_writer": "hexai_pdf_parser.writers.json_writer",
    "markdown_writer": "hexai_pdf_parser.writers.markdown_writer",
    "render_engine": "hexai_pdf_parser.writers.render_engine",
    "table_visualizer": "hexai_pdf_parser.debug.table_visualizer",
    "pipeline_debug": "hexai_pdf_parser.debug.pipeline_debug",
    "hybrid_table_debug": "hexai_pdf_parser.debug.hybrid_table_debug",
    "text_alignment_debug": "hexai_pdf_parser.debug.text_alignment_debug",
    "text_region_detector": "hexai_pdf_parser.debug.text_region_detector",
    "text_visual_debug": "hexai_pdf_parser.debug.text_visual_debug",
    "benchmark_utils": "hexai_pdf_parser.debug.benchmark_utils",
    "table_templates": "hexai_pdf_parser.tables.table_templates",
}


import importlib.util

class _LegacySubmoduleRedirector(MetaPathFinder):
    """Dynamic finder that aliases hexai_pdf_parser.<old_module> to the appropriate subpackage."""

    def find_spec(self, fullname, path=None, target=None):
        prefix = "hexai_pdf_parser."
        if fullname.startswith(prefix):
            subname = fullname[len(prefix):]
            if subname in _LEGACY_MODULE_MAP:
                target_module_name = _LEGACY_MODULE_MAP[subname]
                spec = importlib.util.find_spec(target_module_name)
                if spec is not None:
                    return spec
        return None


if not any(isinstance(f, _LegacySubmoduleRedirector) for f in sys.meta_path):
    sys.meta_path.insert(0, _LegacySubmoduleRedirector())

# Pre-populate sys.modules aliases so that identical module objects are shared
for _subname, _target_module_name in _LEGACY_MODULE_MAP.items():
    _mod = importlib.import_module(_target_module_name)
    sys.modules[f"hexai_pdf_parser.{_subname}"] = _mod

# Core High-level APIs & Pipeline
from hexai_pdf_parser.core.pdf_parser import PDFParser
from hexai_pdf_parser.core.pipeline import Pipeline
from hexai_pdf_parser.core.loader import Loader

# Shared Data Models
from hexai_pdf_parser.core.models import (
    ApiResult,
    BBox,
    Block,
    Cell,
    CellStructure,
    Char,
    Document,
    Image,
    LayoutElement,
    Line,
    Page,
    RenderInfo,
    Seal,
    Span,
    Table,
    TableStructure,
    TextBlock,
    TextChar,
    Word,
)

# Extractors & Builders
from hexai_pdf_parser.extractors.text_extractor import TextExtractor
from hexai_pdf_parser.tables.table_extractor import TableExtractor
from hexai_pdf_parser.tables.extractors import (
    ChineseTableExtractor,
    EnglishTableExtractor,
)
from hexai_pdf_parser.extractors.image_extractor import ImageExtractor
from hexai_pdf_parser.extractors.layout_mapper import LayoutMapper
from hexai_pdf_parser.extractors.layout_builder import LayoutBuilder

# Writers & Renderers
from hexai_pdf_parser.writers.json_writer import JSONWriter
from hexai_pdf_parser.writers.markdown_writer import MarkdownWriter
from hexai_pdf_parser.writers.render_engine import RenderEngine
from hexai_pdf_parser.debug.table_visualizer import (
    draw_tables_on_page,
    render_table_visualization,
)

# Rules & Specialized Parsers
from hexai_pdf_parser.tables.table_config import TableConfig
from hexai_pdf_parser.extractors.personal_credit_report import parse_personal_credit_report

# Subpackages
from hexai_pdf_parser import core, extractors, tables, ml, writers, debug


def __getattr__(name: str):
    """PEP 562 module-level attribute lookup for legacy module names."""
    if name in _LEGACY_MODULE_MAP:
        mod = importlib.import_module(_LEGACY_MODULE_MAP[name])
        sys.modules[f"hexai_pdf_parser.{name}"] = mod
        return mod
    raise AttributeError(f"module 'hexai_pdf_parser' has no attribute {name!r}")


__all__ = [
    # Core APIs
    "PDFParser",
    "Pipeline",
    "Loader",
    # Data Models
    "ApiResult",
    "BBox",
    "Block",
    "Cell",
    "CellStructure",
    "Char",
    "Document",
    "Image",
    "LayoutElement",
    "Line",
    "Page",
    "RenderInfo",
    "Seal",
    "Span",
    "Table",
    "TableStructure",
    "TextBlock",
    "TextChar",
    "Word",
    # Extractors & Builders
    "TextExtractor",
    "TableExtractor",
    "EnglishTableExtractor",
    "ChineseTableExtractor",
    "ImageExtractor",
    "LayoutMapper",
    "LayoutBuilder",
    # Writers & Renderers
    "JSONWriter",
    "MarkdownWriter",
    "RenderEngine",
    "draw_tables_on_page",
    "render_table_visualization",
    # Configurations & Domain Tools
    "TableConfig",
    "parse_personal_credit_report",
    # Subpackages
    "core",
    "extractors",
    "tables",
    "ml",
    "writers",
    "debug",
]
