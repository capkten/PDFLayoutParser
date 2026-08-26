"""Table visualization module for PDFLayoutParser.

Renders detected table bounding boxes, metadata labels, and cell structures
directly onto PDF page rasterizations (PNG).
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Union

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from hexai_pdf_parser.core.models import Table

# ==============================================================================
# 路径与参数配置区域（可直接在此修改路径）
# ==============================================================================
PDF_INPUT_DIR = r"C:\Users\92410\Desktop\git\hexai_pdf_parser\src\hexai_pdf_parser\data\zh_all_pages"
OUTPUT_DIR = r"C:\Users\92410\Desktop\git\hexai_pdf_parser\src\hexai_pdf_parser\data\zh_all_pages\out_debug"
RENDER_DPI = 200
USE_ML = True
# ==============================================================================

# Color palette for table visualization
TABLE_BORDER_COLOR = (0.90, 0.15, 0.15)      # Red for table outer boundary
TABLE_BADGE_FILL = (0.90, 0.15, 0.15)        # Badge background
TABLE_TEXT_COLOR = (1.0, 1.0, 1.0)           # Badge text (White)
CELL_BORDER_COLOR = (0.10, 0.55, 0.90)       # Cyan/Blue for 2D cell grid
TEXT_BORDER_COLOR = (0.95, 0.60, 0.15)       # Amber/Orange for inner text bounding box


def _format_table_label(table: Table, index: int) -> str:
    """Build a concise label describing table index, source, and dimensions."""
    parts = [f"Table {index + 1}"]
    if table.source:
        parts.append(f"[{table.source}]")
    if table.rows and table.cols:
        parts.append(f"{table.rows}x{table.cols}")
    elif table.confidence:
        parts.append(f"({table.confidence:.2f})")
    return " ".join(parts)


def _get_table_score(table: Table) -> float:
    """Extract or calculate table confidence / quality score."""
    if table.confidence is not None and table.confidence > 0.0:
        return float(table.confidence)
    if table.cells:
        filled_ratio = sum(1 for c in table.cells if c.text.strip()) / max(1, len(table.cells))
        base_score = 0.90 if (table.source and "wireless" in table.source.lower()) else 0.95
        return round(min(1.0, base_score + 0.04 * filled_ratio), 2)
    return 0.85


def _compute_cell_grid_rects(table: Table) -> list[tuple[Cell, fitz.Rect]]:
    """Compute visual 2D cell grid rectangles for all cells in a table.

    For line-projection tables with already full grid cells, uses cell.bbox directly.
    For wireless / text-alignment tables, derives full cell grid boundaries from row
    and column midpoints.
    """
    if not table.cells:
        return []

    if table.rows <= 0 or table.cols <= 0:
        return [(c, fitz.Rect(c.bbox.x0, c.bbox.y0, c.bbox.x1, c.bbox.y1)) for c in table.cells]

    if table.source == "line_projection":
        return [(c, fitz.Rect(c.bbox.x0, c.bbox.y0, c.bbox.x1, c.bbox.y1)) for c in table.cells]

    row_tops: dict[int, float] = {}
    row_bottoms: dict[int, float] = {}
    col_lefts: dict[int, float] = {}
    col_rights: dict[int, float] = {}

    for c in table.cells:
        ri, ci = c.row_index, c.col_index
        if c.rowspan == 1:
            row_tops[ri] = min(row_tops.get(ri, c.bbox.y0), c.bbox.y0)
            row_bottoms[ri] = max(row_bottoms.get(ri, c.bbox.y1), c.bbox.y1)
        if c.colspan == 1 and c.text.strip():
            col_lefts[ci] = min(col_lefts.get(ci, c.bbox.x0), c.bbox.x0)
            col_rights[ci] = max(col_rights.get(ci, c.bbox.x1), c.bbox.x1)

    for c in table.cells:
        ri_start = c.row_index
        ri_end = c.row_index + max(1, c.rowspan) - 1
        ci_start = c.col_index
        ci_end = c.col_index + max(1, c.colspan) - 1
        row_tops[ri_start] = min(row_tops.get(ri_start, c.bbox.y0), c.bbox.y0)
        row_bottoms[ri_end] = max(row_bottoms.get(ri_end, c.bbox.y1), c.bbox.y1)
        if c.text.strip():
            col_lefts[ci_start] = min(col_lefts.get(ci_start, c.bbox.x0), c.bbox.x0)
            col_rights[ci_end] = max(col_rights.get(ci_end, c.bbox.x1), c.bbox.x1)

    tb = table.bbox
    for ri in range(table.rows):
        if ri not in row_tops:
            row_tops[ri] = row_bottoms.get(ri - 1, tb.y0)
        if ri not in row_bottoms:
            row_bottoms[ri] = row_tops.get(ri + 1, row_tops[ri] + 12.0)

    for ci in range(table.cols):
        if ci not in col_lefts:
            col_lefts[ci] = col_rights.get(ci - 1, tb.x0)
        if ci not in col_rights:
            col_rights[ci] = col_lefts.get(ci + 1, col_lefts[ci] + 20.0)

    sorted_rows = sorted(range(table.rows))
    sorted_cols = sorted(range(table.cols))

    row_bounds = [tb.y0]
    for i in range(len(sorted_rows) - 1):
        r_cur = sorted_rows[i]
        r_nxt = sorted_rows[i + 1]
        boundary = (row_bottoms[r_cur] + row_tops[r_nxt]) / 2.0
        boundary = max(boundary, row_tops[r_cur])
        boundary = min(boundary, row_tops[r_nxt])
        row_bounds.append(boundary)
    row_bounds.append(tb.y1)

    col_bounds = [tb.x0]
    for i in range(len(sorted_cols) - 1):
        c_cur = sorted_cols[i]
        c_nxt = sorted_cols[i + 1]
        boundary = (col_rights[c_cur] + col_lefts[c_nxt]) / 2.0
        boundary = max(boundary, col_lefts[c_cur])
        boundary = min(boundary, col_lefts[c_nxt])
        col_bounds.append(boundary)
    col_bounds.append(tb.x1)

    results = []
    for c in table.cells:
        r_start = min(max(0, c.row_index), table.rows - 1)
        r_end = min(max(0, c.row_index + max(1, c.rowspan) - 1), table.rows - 1)
        c_start = min(max(0, c.col_index), table.cols - 1)
        c_end = min(max(0, c.col_index + max(1, c.colspan) - 1), table.cols - 1)

        y0 = row_bounds[r_start]
        y1 = row_bounds[r_end + 1]
        x0 = col_bounds[c_start]
        x1 = col_bounds[c_end + 1]
        results.append((c, fitz.Rect(x0, y0, x1, y1)))

    return results


def draw_tables_on_page(
    page: fitz.Page,
    tables: Sequence[Table],
    draw_text_boxes: bool = True,
) -> None:
    """Draw table bounding boxes, tags, score badges, full cell grids, and text boxes onto a fitz.Page."""
    if not tables:
        return

    shape = page.new_shape()
    for idx, table in enumerate(tables):
        tb = table.bbox
        table_rect = fitz.Rect(tb.x0, tb.y0, tb.x1, tb.y1)

        # 1. Compute and draw full 2D Cell Grid boundaries
        cell_grid_pairs = _compute_cell_grid_rects(table)
        for cell, grid_rect in cell_grid_pairs:
            # Draw outer 2D cell grid
            shape.draw_rect(grid_rect)
            shape.finish(color=CELL_BORDER_COLOR, width=0.8)

            # Draw inner text bounding box if different from grid
            if draw_text_boxes and cell.text.strip():
                cb = cell.bbox
                text_rect = fitz.Rect(cb.x0, cb.y0, cb.x1, cb.y1)
                # If text box is smaller than grid cell, outline it with subtle amber border
                if abs(text_rect.width - grid_rect.width) > 3.0 or abs(text_rect.height - grid_rect.height) > 3.0:
                    shape.draw_rect(text_rect)
                    shape.finish(color=TEXT_BORDER_COLOR, width=0.5)

        # 2. Draw table outer rectangle
        shape.draw_rect(table_rect)
        shape.finish(color=TABLE_BORDER_COLOR, width=2.0)

        # 3. Draw left label badge (Index, source, shape)
        label = _format_table_label(table, idx)
        font_size = 7.5
        badge_w = min(page.rect.width - tb.x0, len(label) * 5.0 + 8.0)
        badge_h = 11.0

        badge_y0 = max(0.0, tb.y0 - badge_h)
        badge_y1 = badge_y0 + badge_h
        badge_rect = fitz.Rect(tb.x0, badge_y0, tb.x0 + badge_w, badge_y1)

        shape.draw_rect(badge_rect)
        shape.finish(fill=TABLE_BADGE_FILL, color=TABLE_BORDER_COLOR)
        shape.insert_text(
            fitz.Point(badge_rect.x0 + 3.0, badge_rect.y1 - 2.5),
            label,
            fontsize=font_size,
            color=TABLE_TEXT_COLOR,
        )

        # 4. Draw right score badge (Confidence metric)
        score = _get_table_score(table)
        score_text = f"Score: {score:.2f}"
        score_w = len(score_text) * 5.2 + 8.0

        score_x1 = min(page.rect.width, tb.x1)
        score_x0 = max(0.0, score_x1 - score_w)
        if score_x0 < badge_rect.x1 + 4.0:
            score_x0 = badge_rect.x1 + 4.0
            score_x1 = min(page.rect.width, score_x0 + score_w)

        score_rect = fitz.Rect(score_x0, badge_y0, score_x1, badge_y1)

        # Color coding by score level
        if score >= 0.90:
            score_fill = (0.13, 0.60, 0.32)  # Emerald Green
        elif score >= 0.75:
            score_fill = (0.12, 0.50, 0.85)  # Sky Blue
        else:
            score_fill = (0.88, 0.50, 0.12)  # Amber Orange

        shape.draw_rect(score_rect)
        shape.finish(fill=score_fill, color=score_fill)
        shape.insert_text(
            fitz.Point(score_rect.x0 + 3.0, score_rect.y1 - 2.5),
            score_text,
            fontsize=font_size,
            color=TABLE_TEXT_COLOR,
        )

    shape.commit()


def render_table_visualization(
    source: Union[str, fitz.Page],
    tables: Sequence[Table],
    output_path: str,
    page_index: Optional[int] = None,
    dpi: int = 200,
) -> str:
    """Render a PDF page with table detection overlays and save to output_path.

    Parameters
    ----------
    source:
        Either a PDF file path (str) or an existing ``fitz.Page`` object.
    tables:
        Sequence of detected ``Table`` objects on this page.
    output_path:
        Destination PNG image path.
    page_index:
        Page index when *source* is a file path. Defaults to 0.
    dpi:
        Rasterization resolution in DPI (default 200).

    Returns
    -------
    str:
        The absolute or relative path to the saved PNG.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)

    if isinstance(source, fitz.Page):
        # Draw directly on the provided page
        draw_tables_on_page(source, tables)
        pix = source.get_pixmap(matrix=matrix, alpha=False)
        pix.save(output_path)
        return output_path

    # If file path is provided, open a fresh page handle
    idx = page_index if page_index is not None else 0
    doc = fitz.open(source)
    try:
        page = doc[idx]
        draw_tables_on_page(page, tables)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(output_path)
        return output_path
    finally:
        doc.close()





def batch_visualize_directory(
    input_dir: str = PDF_INPUT_DIR,
    output_dir: str = OUTPUT_DIR,
    dpi: int = RENDER_DPI,
    use_ml: bool = USE_ML,
) -> list[str]:
    """Batch parse and visualize all PDF files in input_dir.

    Creates a dedicated parent folder named after the PDF for each file.
    All saved visualization and output files in subdirectories are explicitly
    named as ``<pdf_stem>_page_<page_index>.<ext>``.

    Parameters
    ----------
    input_dir:
        Directory containing PDF files.
    output_dir:
        Root output directory.
    dpi:
        Rendering resolution DPI.
    use_ml:
        Whether to enable YOLO table detector assistance.

    Returns
    -------
    list[str]:
        List of generated output parent directory paths.
    """
    from pathlib import Path
    import json
    from hexai_pdf_parser.core.pdf_parser import PDFParser
    from hexai_pdf_parser.writers.json_writer import JSONWriter
    from hexai_pdf_parser.writers.markdown_writer import MarkdownWriter

    input_path = Path(input_dir)
    if input_path.is_file():
        pdf_files = [input_path]
    else:
        pdf_files = sorted(
            [p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
        )
    if not pdf_files:
        print(f"[table_visualizer] No PDF files found in: {input_dir}")
        return []

    print(f"[table_visualizer] Found {len(pdf_files)} PDF file(s) in: {input_dir}")
    os.makedirs(output_dir, exist_ok=True)

    generated_dirs: list[str] = []
    for pdf_file in pdf_files:
        pdf_stem = pdf_file.stem
        pdf_parent_dir = os.path.join(output_dir, pdf_stem)
        tables_dir = os.path.join(pdf_parent_dir, "tables")
        pages_dir = os.path.join(pdf_parent_dir, "pages")
        images_dir = os.path.join(pdf_parent_dir, "images")

        os.makedirs(tables_dir, exist_ok=True)
        os.makedirs(pages_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)

        print(f"\n[table_visualizer] Processing: {pdf_file.name} -> {pdf_parent_dir}")

        try:
            with PDFParser(str(pdf_file), render_dpi=dpi, use_ml=use_ml) as parser:
                res = parser.parse()
                if res.code != 1 or not res.data:
                    print(f"[table_visualizer] Error parsing {pdf_file.name}: {res.message}")
                    continue

                doc = res.data

                # 1. Export Global JSON & Markdown named after PDF
                json_writer = JSONWriter()
                md_writer = MarkdownWriter()

                json_writer.write(doc, os.path.join(pdf_parent_dir, f"{pdf_stem}.json"))
                md_writer.write(doc, os.path.join(pdf_parent_dir, f"{pdf_stem}.md"))

                # 2. Extract Images named with PDF and page/image index
                for page in doc.pages:
                    for img_idx, img in enumerate(page.images):
                        if img.data:
                            img_name = f"{pdf_stem}_page_{page.index:03d}_img_{img_idx:03d}.{img.extension or 'png'}"
                            with open(os.path.join(images_dir, img_name), "wb") as ifh:
                                ifh.write(img.data)

                # 3. Render Table Visualizations and Page Previews with <pdf_stem>_page_<idx> naming
                doc_handle = fitz.open(str(pdf_file))
                try:
                    for page in doc.pages:
                        page_idx = page.index
                        page_handle = doc_handle[page_idx]

                        # Page Preview
                        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
                        page_pix = page_handle.get_pixmap(matrix=matrix, alpha=False)
                        page_img_path = os.path.join(pages_dir, f"{pdf_stem}_page_{page_idx:03d}.png")
                        page_pix.save(page_img_path)

                        # Page JSON & Markdown
                        page_json_path = os.path.join(pages_dir, f"{pdf_stem}_page_{page_idx:03d}.json")
                        json_writer.write_page(page, page_json_path)

                        page_md_path = os.path.join(pages_dir, f"{pdf_stem}_page_{page_idx:03d}.md")
                        md_writer.write_page(page, page_md_path)

                        # Single Page PDF
                        page_pdf_path = os.path.join(pages_dir, f"{pdf_stem}_page_{page_idx:03d}.pdf")
                        single_page_doc = fitz.open()
                        single_page_doc.insert_pdf(doc_handle, from_page=page_idx, to_page=page_idx)
                        single_page_doc.save(page_pdf_path, deflate=True)
                        single_page_doc.close()

                        # Table Visualization with Score Badges
                        table_img_path = os.path.join(tables_dir, f"{pdf_stem}_page_{page_idx:03d}.png")
                        draw_tables_on_page(page_handle, page.tables)
                        table_pix = page_handle.get_pixmap(matrix=matrix, alpha=False)
                        table_pix.save(table_img_path)

                finally:
                    doc_handle.close()

                print(f"[table_visualizer] Success! Visualizations written to:")
                print(f"  - Tables: {tables_dir} ({pdf_stem}_page_*.png)")
                print(f"  - Pages:  {pages_dir} ({pdf_stem}_page_*.png/.json/.md/.pdf)")
                generated_dirs.append(pdf_parent_dir)

        except Exception as exc:
            print(f"[table_visualizer] Exception while processing {pdf_file.name}: {exc}")

    return generated_dirs


if __name__ == "__main__":
    batch_visualize_directory(
        input_dir=PDF_INPUT_DIR,
        output_dir=OUTPUT_DIR,
        dpi=RENDER_DPI,
        use_ml=USE_ML,
    )

