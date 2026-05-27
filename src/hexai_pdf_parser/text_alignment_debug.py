import os

import fitz


def render_text_alignment_debug_page(
    page: fitz.Page,
    debug_payload: dict,
    output_path: str,
    dpi: int,
) -> None:
    for region in debug_payload.get("regions", []):
        bbox = region["bbox"]
        page.draw_rect(
            fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]),
            color=(0.62, 0.20, 0.89),
            width=2.0,
            overlay=True,
        )

        for row in region.get("rows", []):
            page.draw_rect(
                fitz.Rect(row["x0"], row["y0"], row["x1"], row["y1"]),
                color=(0.95, 0.34, 0.14),
                width=1.3,
                overlay=True,
            )

        for guide_x in region.get("column_guides", []):
            page.draw_line(
                p1=(guide_x, bbox["y0"]),
                p2=(guide_x, bbox["y1"]),
                color=(0.05, 0.55, 0.95),
                width=1.0,
                overlay=True,
            )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(output_path)
