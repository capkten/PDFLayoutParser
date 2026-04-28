"""Command-line interface for PDFLayoutParser."""

import argparse
import sys

from pdflayoutparser.pipeline import Pipeline


def main() -> int:
    """Run the PDFLayoutParser CLI."""
    parser = argparse.ArgumentParser(
        prog="pdflayoutparser",
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

    args = parser.parse_args()

    pipeline = Pipeline(
        pdf_path=args.pdf_path,
        output_dir=args.output,
        render_dpi=args.dpi,
    )
    pipeline.run()

    print(f"Success! Output written to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
