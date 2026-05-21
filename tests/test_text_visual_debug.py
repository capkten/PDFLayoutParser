import json
from pathlib import Path

import fitz

from pdflayoutparser.text_visual_debug import (
    TextFragment,
    build_visual_rows,
    make_text_fragments,
    render_text_debug_pages,
)


def test_make_text_fragments_merges_nearby_cjk_words():
    words = [
        (20.0, 30.0, 36.0, 42.0, "应收", 0, 0, 0),
        (38.0, 30.0, 54.0, 42.0, "账款", 0, 0, 1),
        (150.0, 30.0, 186.0, 42.0, "123,456", 0, 0, 2),
    ]

    fragments = make_text_fragments(words)

    assert [fragment.text for fragment in fragments] == ["应收账款", "123,456"]
    assert fragments[0].bbox.x0 == 20.0
    assert fragments[0].bbox.x1 == 54.0


def test_make_text_fragments_keeps_wide_column_gap_separate():
    words = [
        (20.0, 30.0, 30.0, 42.0, "A", 0, 0, 0),
        (70.0, 30.0, 80.0, 42.0, "B", 0, 0, 1),
    ]

    fragments = make_text_fragments(words)

    assert [fragment.text for fragment in fragments] == ["A", "B"]


def test_build_visual_rows_groups_fragments_on_same_band():
    fragments = [
        TextFragment(text="项目", bbox=(20.0, 30.0, 54.0, 42.0)),
        TextFragment(text="123", bbox=(150.0, 31.0, 178.0, 43.0)),
        TextFragment(text="下一行", bbox=(20.0, 60.0, 64.0, 72.0)),
    ]

    rows = build_visual_rows(fragments)

    assert len(rows) == 2
    assert [fragment.text for fragment in rows[0].fragments] == ["项目", "123"]
    assert rows[0].bbox.x0 == 20.0
    assert rows[0].bbox.x1 == 178.0
    assert [fragment.text for fragment in rows[1].fragments] == ["下一行"]


def test_render_text_debug_pages_creates_overlay_images(tmp_dir):
    pdf_path = Path(tmp_dir) / "text_debug_demo.pdf"
    output_dir = Path(tmp_dir) / "out"

    doc = fitz.open()
    try:
        page = doc.new_page()
        page.insert_text((20, 40), "应收")
        page.insert_text((38, 40), "账款")
        page.insert_text((150, 40), "123,456")
        page.insert_text((20, 70), "存货")
        page.insert_text((150, 70), "654,321")
        doc.save(str(pdf_path))
    finally:
        doc.close()

    outputs = render_text_debug_pages(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        page_numbers=[1],
        dpi=120,
    )

    assert len(outputs) == 1
    assert outputs[0]["page_number"] == 1
    assert Path(outputs[0]["image_path"]).exists()
    assert Path(outputs[0]["json_path"]).exists()


def test_render_text_debug_pages_exports_candidate_regions(tmp_dir):
    pdf_path = Path(tmp_dir) / "text_region_demo.pdf"
    output_dir = Path(tmp_dir) / "out"

    doc = fitz.open()
    try:
        page = doc.new_page(width=360, height=220)
        page.insert_text((20, 40), "项目A")
        page.insert_text((180, 40), "10")
        page.insert_text((300, 40), "20")
        page.insert_text((20, 58), "项目B")
        page.insert_text((180, 58), "11")
        page.insert_text((300, 58), "21")
        doc.save(str(pdf_path))
    finally:
        doc.close()

    outputs = render_text_debug_pages(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        page_numbers=[1],
        dpi=120,
    )

    payload = json.loads(Path(outputs[0]["json_path"]).read_text(encoding="utf-8"))
    assert "candidate_regions" in payload
    assert len(payload["candidate_regions"]) == 1
