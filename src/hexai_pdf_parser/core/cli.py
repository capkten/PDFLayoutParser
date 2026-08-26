"""Command-line interface for PDFLayoutParser."""

import argparse
import json
import sys

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

from hexai_pdf_parser.core.pipeline import Pipeline
from hexai_pdf_parser.tables.table_config import TableConfig


def main() -> int:
    """Run the PDFLayoutParser CLI."""
    parser = argparse.ArgumentParser(
        prog="hexai_pdf_parser",
        description="Parse PDF layouts into structured JSON and Markdown.",
    )
    parser.add_argument(
        "pdf_path_arg",
        nargs="?",
        help="Path to input PDF file (positional form)",
    )
    parser.add_argument(
        "--pdf_path",
        dest="pdf_path_option",
        default=None,
        help="Path to input PDF file",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Render DPI (default: 200)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        nargs="+",
        help="Specific page indices to parse (0-indexed)",
    )
    parser.add_argument(
        "--ml-model",
        default=None,
        help="Path to custom ONNX model for table detection",
    )
    parser.add_argument(
        "--ml-confidence",
        type=float,
        default=0.70,
        help="Confidence threshold for ML table detection (default: 0.70)",
    )
    parser.add_argument(
        "--table-config",
        default=None,
        help="Path to JSON table layout config file",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Export debug overlays for text-aligned tables",
    )
    parser.add_argument(
        "--debug-pipeline",
        action="store_true",
        default=False,
        help="Export visual diagnostics for every table-extraction stage",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=None,
        help="Number of worker threads for parallel page processing (default: auto-detected)",
    )
    parser.add_argument(
        "--backend",
        "-b",
        choices=["thread", "process", "sequential"],
        default="thread",
        help="Concurrency backend to use for processing: thread, process, or sequential (default: thread)",
    )

    args = parser.parse_args()

    table_config = None
    if args.table_config:
        table_config = TableConfig.load(args.table_config)

    pdf_path = args.pdf_path_option or args.pdf_path_arg
    if not pdf_path:
        parser.error("a PDF path is required (positional path or --pdf_path)")

    pipeline = Pipeline(
        pdf_path=pdf_path,
        output_dir=args.output,
        render_dpi=args.dpi,
        page_indices=args.pages,
        ml_model_path=args.ml_model,
        ml_confidence=args.ml_confidence,
        debug=args.debug,
        debug_pipeline=args.debug_pipeline,
        table_config=table_config,
        num_workers=args.workers,
        backend=args.backend,
    )
    pipeline.run()

    print(f"Success! Output written to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
