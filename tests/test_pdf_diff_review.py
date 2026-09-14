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
    classification = json.loads((review_dir / "classification.json").read_text(encoding="utf-8"))
    assert classification["pages"][0]["page_index"] == 0
    assert classification["pages"][0]["primary_category"] == "body_text"
    assert classification["pages"][0]["label_path"] == "labels/page-000.md"
    assert classification["pages"][0]["source_markdown"] == "part_000_pages_0000_0000/pages/page-000.md"
    assert "-标签文本" in classification["pages"][0]["diff"]
    assert "+当前文本" in classification["pages"][0]["diff"]
    assert summary["category_counts"] == {"body_text": 1}

    image_bytes = (review_dir / "images" / "page-000.png").read_bytes()
    assert image_bytes.startswith(b"\x89PNG")
    decoded = fitz.Pixmap(str(review_dir / "images" / "page-000.png"))
    assert decoded.width > 0
    assert decoded.height > 0


def test_build_review_keeps_page_when_actual_resources_are_missing(tmp_path: Path) -> None:
    testset_root = tmp_path / "testset"
    (testset_root / "labels").mkdir(parents=True)
    (testset_root / "labels" / "page-000.md").write_text("标签", encoding="utf-8")
    (testset_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "page_count": 1,
                "pages": [{"page_index": 0, "markdown_status": "markdown", "label_path": "labels/page-000.md"}],
                "failed_pages": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pages_dir = tmp_path.joinpath("actual", "part_000_pages_0000_0000", "pages")
    pages_dir.mkdir(parents=True)
    (pages_dir / "page-000.json").write_text(
        json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8"
    )

    summary = build_review(tmp_path / "actual", testset_root, tmp_path / "review")

    page = summary["pages"][0]
    assert page["page_index"] == 0
    assert page["primary_category"] == "missing_resource"
    assert any("Markdown" in error for error in page["errors"])
    assert any("PNG" in error for error in page["errors"])
    assert (tmp_path / "review" / "images" / "page-000.png").is_file()


def test_build_review_does_not_classify_absent_expected_as_missing_markdown(tmp_path: Path) -> None:
    testset_root = tmp_path / "testset"
    testset_root.mkdir()
    label_visual = testset_root / "label.png"
    _write_png(label_visual)
    (testset_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "page_count": 1,
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "absent_expected",
                        "source_visual_path": "label.png",
                    }
                ],
                "failed_pages": [],
            }
        ),
        encoding="utf-8",
    )
    pages_dir = tmp_path / "actual" / "page-000" / "pages"
    tables_dir = pages_dir.parent / "tables"
    pages_dir.mkdir(parents=True)
    tables_dir.mkdir()
    (pages_dir / "page-000.json").write_text(
        json.dumps({"index": 0, "page_type": "scanned"}), encoding="utf-8"
    )
    _write_png(tables_dir / "page-000.png")

    summary = build_review(tmp_path / "actual", testset_root, tmp_path / "review")

    page = summary["pages"][0]
    assert page["primary_category"] != "missing_resource"
    assert not any("Markdown" in error for error in page["errors"])


def test_build_review_preserves_scan_error_and_validates_fallback_pages(tmp_path: Path) -> None:
    testset_root = tmp_path / "testset"
    testset_root.mkdir()
    (testset_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "page_count": 2,
                "pages": [
                    {"page_index": 0, "markdown_status": "absent_expected"},
                    {"page_index": 1, "markdown_status": "absent_expected"},
                ],
                "failed_pages": [],
            }
        ),
        encoding="utf-8",
    )
    actual_root = tmp_path / "actual"
    pages_dir = actual_root / "part_000_pages_0000_0001" / "pages"
    tables_dir = pages_dir.parent / "tables"
    pages_dir.mkdir(parents=True)
    tables_dir.mkdir()
    (pages_dir / "page-000.json").write_text(
        json.dumps({"index": 99, "page_type": "scanned"}), encoding="utf-8"
    )
    (pages_dir / "page-001.json").write_text(
        json.dumps({"index": 1, "page_type": "scanned"}), encoding="utf-8"
    )
    _write_png(tables_dir / "page-000.png")
    _write_png(tables_dir / "page-001.png")

    summary = build_review(actual_root, testset_root, tmp_path / "review")

    assert summary["scan_errors"]
    assert any("JSON index" in error for error in summary["pages"][0]["errors"])
    assert not any("JSON index" in error for error in summary["pages"][1]["errors"])


def test_find_label_image_uses_manifest_candidate_order(tmp_path: Path) -> None:
    testset_root = tmp_path / "testset"
    testset_root.mkdir()
    root_visual = testset_root / "visual.png"
    parent_visual = testset_root.parent / "visual.png"
    root_table = testset_root / "table.png"
    _write_png(root_visual)
    _write_png(parent_visual)
    _write_png(root_table)
    (testset_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "page_count": 1,
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "absent_expected",
                        "source_visual_path": "visual.png",
                        "source_table_png": "table.png",
                    }
                ],
                "failed_pages": [],
            }
        ),
        encoding="utf-8",
    )
    pages_dir = tmp_path / "actual" / "page-000" / "pages"
    tables_dir = pages_dir.parent / "tables"
    pages_dir.mkdir(parents=True)
    tables_dir.mkdir()
    (pages_dir / "page-000.json").write_text(
        json.dumps({"index": 0, "page_type": "scanned"}), encoding="utf-8"
    )
    _write_png(tables_dir / "page-000.png")

    summary = build_review(tmp_path / "actual", testset_root, tmp_path / "review")

    assert summary["pages"][0]["label_png"] == "visual.png"


def test_build_review_records_corrupt_png_read_error(tmp_path: Path) -> None:
    testset_root = tmp_path / "testset"
    (testset_root / "labels").mkdir(parents=True)
    (testset_root / "labels" / "page-000.md").write_text("标签", encoding="utf-8")
    (testset_root / "label.png").write_bytes(b"not a png")
    (testset_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "page_count": 1,
                "pages": [
                    {
                        "page_index": 0,
                        "markdown_status": "markdown",
                        "label_path": "labels/page-000.md",
                        "source_visual_path": "label.png",
                    }
                ],
                "failed_pages": [],
            }
        ),
        encoding="utf-8",
    )
    pages_dir = tmp_path / "actual" / "page-000" / "pages"
    tables_dir = pages_dir.parent / "tables"
    pages_dir.mkdir(parents=True)
    tables_dir.mkdir()
    (pages_dir / "page-000.md").write_text("当前", encoding="utf-8")
    (pages_dir / "page-000.json").write_text(
        json.dumps({"index": 0, "page_type": "vector"}), encoding="utf-8"
    )
    _write_png(tables_dir / "page-000.png")

    summary = build_review(tmp_path / "actual", testset_root, tmp_path / "review")

    assert any(
        "label PNG" in error and "unknown image file format" in error
        for error in summary["pages"][0]["errors"]
    )
