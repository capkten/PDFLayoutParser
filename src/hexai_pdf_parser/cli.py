"""Command-line interface for PDFLayoutParser."""

import argparse
import sys

from hexai_pdf_parser.pipeline import Pipeline


def main() -> int:
    """Run the PDFLayoutParser CLI."""
    parser = argparse.ArgumentParser(
        prog="hexai_pdf_parser",
        description="Parse PDF layouts into structured JSON and Markdown.",
    )
    parser.add_argument(
        "pdf_path",
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
        "--ml",
        action="store_true",
        default=False,
        help="Enable ML-based table region detection with the bundled YOLO model (requires hexai_pdf_parser[ml])",
    )
    parser.add_argument(
        "--ml-model",
        default=None,
        help="Path to custom ONNX model for table detection",
    )
    parser.add_argument(
        "--ml-confidence",
        type=float,
        default=0.25,
        help="Confidence threshold for ML table detection (default: 0.25)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Export debug overlays for text-aligned tables",
    )

    args = parser.parse_args()

    pipeline = Pipeline(
        pdf_path=args.pdf_path,
        output_dir=args.output,
        render_dpi=args.dpi,
        page_indices=args.pages,
        use_ml=args.ml,
        ml_model_path=args.ml_model,
        ml_confidence=args.ml_confidence,
        debug=args.debug,
    )
    pipeline.run()

    print(f"Success! Output written to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
