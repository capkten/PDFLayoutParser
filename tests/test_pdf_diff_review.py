import json
from pathlib import Path

import fitz

from scripts.pdf_diff_review import build_review, classify_markdown


def test_classify_reading_order_only() -> None:
    expected = "标题\n第一段\n第二段"
    actual = "标题\n第二段\n第一段"

    result = classify_markdown(expected, actual)

    assert result["primary_category"] == "reading_order"
    assert result["categories"] == ["reading_order"]


def test_classify_table_structure_change() -> None:
    expected = "<table><tr><td>A</td><td>B</td></tr></table>"
    actual = '<table><tr><td colspan="2">A</td></tr></table>'

    result = classify_markdown(expected, actual)

    assert result["primary_category"] == "table_structure"
    assert result["evidence"]["table_count"]["expected"] == 1
    assert result["evidence"]["table_shapes_differ"] is True


def test_classify_table_text_change() -> None:
    expected = "<table><tr><td>A</td></tr></table>"
    actual = "<table><tr><td>C</td></tr></table>"

    result = classify_markdown(expected, actual)

    assert result["primary_category"] == "table_text"
    assert result["categories"] == ["table_text"]
    assert result["evidence"]["table_text_differ"] is True


def test_classify_table_count_change() -> None:
    expected = "<table><tr><td>A</td></tr></table>"
    actual = "A"

    result = classify_markdown(expected, actual)

    assert result["primary_category"] == "table_count"
    assert result["categories"] == ["table_count"]


def test_classify_body_text_change() -> None:
    expected = "说明 A\n\n<table><tr><td>相同</td></tr></table>"
    actual = "说明 B\n\n<table><tr><td>相同</td></tr></table>"

    result = classify_markdown(expected, actual)

    assert result["primary_category"] == "body_text"
    assert result["categories"] == ["body_text"]


def test_classify_mixed_structure_and_body_change() -> None:
    expected = "说明 A\n<table><tr><td>A</td><td>B</td></tr></table>"
    actual = '说明 B\n<table><tr><td colspan="2">A</td></tr></table>'

    result = classify_markdown(expected, actual)

    assert result["primary_category"] == "mixed"
    assert result["categories"] == ["mixed"]
    assert result["signals"] == ["table_structure", "body_text"]


def test_classify_formatting_only() -> None:
    expected = "<table><tr><td>A</td></tr></table>"
    actual = "<table>\n  <tbody>\n    <tr>\n      <td>A</td>\n    </tr>\n  </tbody>\n</table>"

    result = classify_markdown(expected, actual)

    assert result["primary_category"] == "formatting"
    assert result["categories"] == ["formatting"]


def _write_png(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=24, height=24)
    page.get_pixmap().save(str(path))
    doc.close()


def test_build_review_writes_json_images_and_html(tmp_path: Path) -> None:
    testset_root = tmp_path / "testset_markdown"
    labels_dir = testset_root / "labels"
    labels_dir.mkdir(parents=True)
    (labels_dir / "page-000.md").write_text("标签文本", encoding="utf-8")

    baseline_root = testset_root.parent
    visual_dir = baseline_root / "visualized_images"
    visual_dir.mkdir()
    _write_png(visual_dir / "page-000.png")

    manifest = {
        "schema_version": 1,
        "input_pdf": str(tmp_path / "input.pdf"),
        "input_pdf_posix": (tmp_path / "input.pdf").as_posix(),
        "page_count": 1,
        "generated_at": "2026-09-14T00:00:00+08:00",
        "excluded_visuals": [],
        "failed_pages": [],
        "pages": [
            {
                "page_index": 0,
                "page_type": "vector",
                "markdown_status": "markdown",
                "label_path": "labels/page-000.md",
                "source_visual_path": "visualized_images/page-000.png",
                "source_table_png": "visualized_images/page-000.png",
            }
        ],
    }
    testset_root.joinpath("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    actual_root = tmp_path / "actual"
    pages_dir = actual_root / "part_000_pages_0000_0000" / "pages"
    tables_dir = actual_root / "part_000_pages_0000_0000" / "tables"
    pages_dir.mkdir(parents=True)
    tables_dir.mkdir(parents=True)
    (pages_dir / "page-000.md").write_text("当前文本", encoding="utf-8")
    (pages_dir / "page-000.json").write_text(
        json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8"
    )
    _write_png(tables_dir / "page-000.png")

    review_dir = tmp_path / "review"
    summary = build_review(actual_root, testset_root, review_dir)

    assert summary["diff_count"] == 1
    assert (review_dir / "classification.json").is_file()
    assert (review_dir / "summary.json").is_file()
    assert (review_dir / "index.html").is_file()
    assert (review_dir / "images" / "page-000.png").is_file()
    html = (review_dir / "index.html").read_text(encoding="utf-8")
    assert "page-000.png" in html
