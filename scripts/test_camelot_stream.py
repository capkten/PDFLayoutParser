from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdflayoutparser.camelot_stream_demo import run_camelot_stream_demo


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Camelot stream mode on a PDF page and export a preview."
    )
    parser.add_argument("pdf_path", help="Path to the input PDF")
    parser.add_argument("--page", type=int, default=1, help="1-based page number")
    parser.add_argument(
        "--output",
        "-o",
        default="output/camelot_stream_demo",
        help="Output directory",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Preview render DPI",
    )
    args = parser.parse_args()

    result = run_camelot_stream_demo(
        args.pdf_path,
        page=args.page,
        output_dir=args.output,
        dpi=args.dpi,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
