"""Per-page visual diagnostics for the PDF table-extraction pipeline."""

from __future__ import annotations

import json
import os

import fitz


STAGE_NAMES = (
    "00-original",
    "01-drawings",
    "02-lines",
    "03-regions",
    "04-cells",
    "05-text-alignment",
    "06-final-tables",
)


def render_pipeline_debug_page(
    pdf_path: str,
    page_index: int,
    output_dir: str,
    debug_payload: dict,
    dpi: int,
) -> dict:
    """Write one PNG for each extraction stage plus its JSON snapshot."""
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "debug.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(debug_payload, handle, ensure_ascii=False, indent=2)

    for stage in STAGE_NAMES:
        _render_stage(pdf_path, page_index, output_dir, stage, debug_payload, dpi)

    return {
        "page_index": page_index,
        "output_dir": output_dir,
        "json_path": json_path,
        "stages": [os.path.join(output_dir, f"{stage}.png") for stage in STAGE_NAMES],
    }


def _render_stage(
    pdf_path: str,
    page_index: int,
    output_dir: str,
    stage: str,
    payload: dict,
    dpi: int,
) -> None:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        if stage == "01-drawings":
            _draw_drawings(page, payload.get("drawings", []))
        elif stage == "02-lines":
            _draw_lines(page, payload)
        elif stage == "03-regions":
            _draw_regions(page, payload.get("line_regions", []))
        elif stage == "04-cells":
            _draw_cells(page, payload.get("line_cells", []))
        elif stage == "05-text-alignment":
            _draw_text_alignment(page, payload.get("text_alignment"))
        elif stage == "06-final-tables":
            _draw_final_tables(page, payload.get("final_tables", []))

        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        pix.save(os.path.join(output_dir, f"{stage}.png"))
    finally:
        doc.close()


def _rect(data: dict) -> fitz.Rect:
    return fitz.Rect(data["x0"], data["y0"], data["x1"], data["y1"])


def _draw_drawings(page: fitz.Page, drawings: list[dict]) -> None:
    for drawing in drawings:
        color = (0.95, 0.45, 0.05) if drawing.get("dashes") else (0.05, 0.35, 0.95)
        for item in drawing.get("items", []):
            if item["type"] == "line":
                page.draw_line(
                    (item["p1"]["x"], item["p1"]["y"]),
                    (item["p2"]["x"], item["p2"]["y"]),
                    color=color,
                    width=1.4,
                    overlay=True,
                )
            elif item["type"] == "rect":
                page.draw_rect(_rect(item["bbox"]), color=color, width=1.0, overlay=True)


def _draw_lines(page: fitz.Page, payload: dict) -> None:
    raw = payload.get("raw_lines", {})
    merged = payload.get("merged_lines", {})
    for x0, y, x1, _ in raw.get("horizontal", []):
        page.draw_line((x0, y), (x1, y), color=(0.95, 0.55, 0.05), width=0.8, overlay=True)
    for x, y0, _, y1 in raw.get("vertical", []):
        page.draw_line((x, y0), (x, y1), color=(0.95, 0.55, 0.05), width=0.8, overlay=True)
    for x0, y, x1, _ in merged.get("horizontal", []):
        page.draw_line((x0, y), (x1, y), color=(0.05, 0.55, 0.95), width=1.8, overlay=True)
    for x, y0, _, y1 in merged.get("vertical", []):
        page.draw_line((x, y0), (x, y1), color=(0.05, 0.55, 0.95), width=1.8, overlay=True)


def _draw_regions(page: fitz.Page, regions: list[dict]) -> None:
    for region in regions:
        page.draw_rect(_rect(region["bbox"]), color=(0.65, 0.10, 0.85), width=2.0, overlay=True)


def _draw_cells(page: fitz.Page, line_cells: list[dict]) -> None:
    for region in line_cells:
        for cell in region.get("cells", []):
            page.draw_rect(_rect(cell["bbox"]), color=(0.05, 0.70, 0.35), width=1.0, overlay=True)


def _draw_text_alignment(page: fitz.Page, payload: dict | None) -> None:
    if not payload:
        return
    for region in payload.get("regions", []):
        bbox = _rect(region["bbox"])
        page.draw_rect(bbox, color=(0.65, 0.10, 0.85), width=2.0, overlay=True)
        for row in region.get("rows", []):
            page.draw_rect(_rect(row), color=(0.95, 0.25, 0.10), width=1.2, overlay=True)
        for guide_x in region.get("column_guides", []):
            page.draw_line(
                (guide_x, bbox.y0),
                (guide_x, bbox.y1),
                color=(0.05, 0.55, 0.95),
                width=1.0,
                overlay=True,
            )


def _draw_final_tables(page: fitz.Page, tables: list[dict]) -> None:
    for table in tables:
        page.draw_rect(_rect(table["bbox"]), color=(0.95, 0.05, 0.05), width=2.2, overlay=True)
        for cell in table.get("cells", []):
            page.draw_rect(_rect(cell["bbox"]), color=(0.95, 0.50, 0.05), width=0.8, overlay=True)
