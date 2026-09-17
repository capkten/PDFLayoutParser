"""Export end-to-end PDF table extraction results (JSON, PNG, manifest)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import fitz

# Ensure source root is in sys.path
source_root = Path(__file__).resolve().parent.parent / "src"
if str(source_root) not in sys.path:
    sys.path.insert(0, str(source_root))

from hexai_pdf_parser.tables.extractors.wired_table_extractor import WiredTableExtractor


def parse_pages(pages_arg: str, total_pages: int) -> List[int]:
    if not pages_arg or pages_arg.strip().lower() == "all":
        return list(range(total_pages))
    result = []
    for part in pages_arg.split(","):
        part = part.strip()
        if not part:
            continue
        idx = int(part)
        if idx >= total_pages:
            raise ValueError(f"Page index {idx} out of range (total pages: {total_pages})")
        result.append(idx)
    return result


def export_page_tables(
    doc: fitz.Document,
    page_idx: int,
    output_dir: Path,
    dpi: int,
    extractor: WiredTableExtractor,
) -> Dict[str, Any]:
    page = doc.load_page(page_idx)
    tables = extractor.extract(page)

    tables_data: List[Dict[str, Any]] = []
    total_cells = 0
    for t_idx, table in enumerate(tables):
        cells_data = []
        for cell in table.cells:
            cells_data.append({
                "text": cell.text,
                "row": cell.row_index,
                "col": cell.col_index,
                "rowspan": cell.rowspan,
                "colspan": cell.colspan,
                "bbox": {
                    "x0": round(cell.bbox.x0, 2),
                    "y0": round(cell.bbox.y0, 2),
                    "x1": round(cell.bbox.x1, 2),
                    "y1": round(cell.bbox.y1, 2),
                },
            })
        total_cells += len(cells_data)
        tables_data.append({
            "index": t_idx,
            "bbox": {
                "x0": round(table.bbox.x0, 2),
                "y0": round(table.bbox.y0, 2),
                "x1": round(table.bbox.x1, 2),
                "y1": round(table.bbox.y1, 2),
            },
            "rows": table.rows,
            "cols": table.cols,
            "confidence": table.confidence,
            "source": table.source,
            "cells_count": len(cells_data),
            "cells": cells_data,
        })

    json_path = output_dir / f"page_{page_idx:04d}_tables.json"
    json_path.write_text(json.dumps(tables_data, indent=2, ensure_ascii=False), encoding="utf-8")

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    png_path = output_dir / f"page_{page_idx:04d}.png"
    pix.save(str(png_path))

    return {
        "page_index": page_idx,
        "tables_count": len(tables_data),
        "cells_count": total_cells,
        "tables": [
            {
                "index": t["index"],
                "bbox": t["bbox"],
                "rows": t["rows"],
                "cols": t["cols"],
                "confidence": t["confidence"],
                "source": t["source"],
                "cells_count": t["cells_count"],
            }
            for t in tables_data
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export end-to-end PDF table extraction results.")
    parser.add_argument("--mode", choices=["python", "rust", "shadow"], default="python")
    parser.add_argument("--pdf", required=True, help="Path to input PDF")
    parser.add_argument("--pages", default="all", help="Pages to export (comma-separated 0-based indices or all)")
    parser.add_argument("--dpi", type=int, default=200, help="Rendering DPI for PNGs")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    os.environ["PDF_RUST_MODE"] = args.mode

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    pages_to_process = parse_pages(args.pages, len(doc))

    extractor = WiredTableExtractor()
    page_summaries = []
    total_tables = 0
    total_cells = 0

    for page_idx in pages_to_process:
        summary = export_page_tables(doc, page_idx, output_dir, args.dpi, extractor)
        page_summaries.append(summary)
        total_tables += summary["tables_count"]
        total_cells += summary["cells_count"]

    doc.close()

    manifest = {
        "schema_version": 1,
        "mode": args.mode,
        "pdf": str(pdf_path),
        "dpi": args.dpi,
        "total_pages": len(page_summaries),
        "total_tables": total_tables,
        "total_cells": total_cells,
        "pages": page_summaries,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(page_summaries)} pages to {output_dir} (tables: {total_tables}, cells: {total_cells})")


if __name__ == "__main__":
    main()
