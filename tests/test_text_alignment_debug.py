from pathlib import Path

import fitz

from pdflayoutparser.text_alignment_debug import render_text_alignment_debug_page


def test_render_text_alignment_debug_page_creates_png(tmp_dir):
    pdf_path = Path(tmp_dir) / "debug_page.pdf"
    output_path = Path(tmp_dir) / "page-000.png"

    doc = fitz.open()
    try:
        page = doc.new_page(width=360, height=220)
        page.insert_text((20, 40), "项目A")
        page.insert_text((180, 40), "10")
        page.insert_text((300, 40), "20")
        doc.save(str(pdf_path))
    finally:
        doc.close()

    doc = fitz.open(str(pdf_path))
    try:
        render_text_alignment_debug_page(
            page=doc[0],
            debug_payload={
                "page_index": 0,
                "regions": [
                    {
                        "bbox": {"x0": 20.0, "y0": 30.0, "x1": 320.0, "y1": 60.0},
                        "rows": [
                            {"x0": 20.0, "y0": 30.0, "x1": 320.0, "y1": 42.0},
                        ],
                        "column_guides": [20.0, 180.0, 300.0],
                    }
                ],
            },
            output_path=str(output_path),
            dpi=120,
        )
    finally:
        doc.close()

    assert output_path.exists()
    assert output_path.stat().st_size > 0
