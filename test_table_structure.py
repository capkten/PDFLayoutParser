"""Full validation: extract_table_structure() on all pages of all PDFs."""

import json
import os
import sys

sys.path.insert(0, "src")

import fitz

from hexai_pdf_parser import PDFParser
from hexai_pdf_parser.json_writer import JSONWriter


def run_validation():
    pdf_files = [
        "万马股份2024财报.pdf",
        "152590_20230428_N7ZK_0.pdf",
        "0000899689_10-Q_20250505.pdf",
    ]

    output_dir = "out_table_structure"
    os.makedirs(output_dir, exist_ok=True)
    writer = JSONWriter()

    for pdf_path in pdf_files:
        if not os.path.exists(pdf_path):
            print(f"SKIP: {pdf_path} not found")
            continue

        pdf_name = os.path.basename(pdf_path).replace(" ", "_").replace(".", "_")
        print(f"\n{'='*60}")
        print(f"Processing: {pdf_path}")
        print(f"{'='*60}")

        with PDFParser(pdf_path) as parser:
            parse_result = parser.parse()
            if parse_result.code != 1:
                print(f"  Parse failed: {parse_result.message}")
                continue

            doc = parse_result.data
            total_tables = 0

            for page in doc.pages:
                result = parser.extract_table_structure(
                    page_indices=[page.index]
                )
                if result.code != 1 or not result.data:
                    continue

                structures = result.data
                total_tables += len(structures)

                # Print summary
                for ts_idx, ts in enumerate(structures):
                    cell_preview = []
                    for c in ts.cells[:3]:
                        cell_preview.append(f"[{c.row_index},{c.col_index}]={c.text[:25]!r}")
                    preview_str = " | ".join(cell_preview)
                    print(
                        f"  Page {page.index:3d} Table {ts_idx}: "
                        f"{ts.rows:2d}x{ts.cols} {ts.source:20s} "
                        f"cells={len(ts.cells):3d}  {preview_str}"
                    )

                # Visualize
                doc_fitz = fitz.open(pdf_path)
                ph = doc_fitz[page.index]
                shape = ph.new_shape()
                for ts in structures:
                    for cell in ts.cells:
                        if len(cell.cell_coord) < 4:
                            continue
                        pts = [fitz.Point(x, y) for x, y in cell.cell_coord]
                        for i in range(4):
                            shape.draw_line(pts[i], pts[(i + 1) % 4])
                        shape.finish(color=(1, 0, 0), width=0.5)
                        if cell.text_block and cell.text_block.chars:
                            tb = cell.text_block.bbox
                            shape.draw_rect(fitz.Rect(tb.x0, tb.y0, tb.x1, tb.y1))
                            shape.finish(color=(0, 0, 1), width=0.3)
                shape.commit()
                pix = ph.get_pixmap(matrix=fitz.Matrix(2, 2))
                vis = os.path.join(output_dir, f"{pdf_name}_p{page.index:03d}.png")
                pix.save(vis)
                doc_fitz.close()

                # JSON
                js = os.path.join(output_dir, f"{pdf_name}_p{page.index:03d}.json")
                with open(js, "w", encoding="utf-8") as f:
                    json.dump(
                        writer.table_structures_to_dict(structures),
                        f, ensure_ascii=False, indent=2,
                    )

            print(f"\n  Total tables: {total_tables}")

    print(f"\nDone. Output in: {output_dir}/")


if __name__ == "__main__":
    run_validation()
