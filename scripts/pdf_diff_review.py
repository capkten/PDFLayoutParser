"""Classify semantic differences between two Markdown snapshots."""

from collections import Counter
import difflib
from html.parser import HTMLParser
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

from scripts.markdown_golden_testset import _load_manifest, scan_page_outputs, source_page_index


_WS_RE = re.compile(r"\s+")


def _clean_text(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[Dict[str, Any]] = []
        self._table_stack: List[Dict[str, Any]] = []
        self._row: Optional[List[Dict[str, Any]]] = None
        self._cell: Optional[Dict[str, Any]] = None
        self.body_units: List[str] = []
        self.visible_units: List[str] = []

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        tag = tag.lower()
        if tag == "table":
            table = {"rows": [], "texts": []}
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag == "tr" and self._table_stack and self._cell is None:
            self._row = []
            self._table_stack[-1]["rows"].append(self._row)
        elif tag in {"td", "th"} and self._row is not None and self._cell is None:
            values = dict(attrs)
            self._cell = {
                "text": [],
                "rowspan": self._span(values.get("rowspan")),
                "colspan": self._span(values.get("colspan")),
            }
            self._row.append(self._cell)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None:
            text = _clean_text("".join(self._cell["text"]))
            self._cell["text"] = text
            self._table_stack[-1]["texts"].append(text)
            self.visible_units.append(text)
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
            return
        if self._table_stack:
            return
        for line in data.splitlines():
            text = _clean_text(line)
            if text:
                self.body_units.append(text)
                self.visible_units.append(text)

    @staticmethod
    def _span(value: Optional[str]) -> int:
        try:
            return max(1, int(value or "1"))
        except ValueError:
            return 1


def parse_markdown(markdown: str) -> Dict[str, Any]:
    parser = _MarkdownParser()
    parser.feed(markdown)
    parser.close()
    tables = []
    for table in parser.tables:
        rows = table["rows"]
        tables.append(
            {
                "rows": len(rows),
                "cells_per_row": [len(row) for row in rows],
                "spans": [
                    [(cell["rowspan"], cell["colspan"]) for cell in row]
                    for row in rows
                ],
                "texts": list(table["texts"]),
            }
        )
    return {
        "table_count": len(tables),
        "tables": tables,
        "body_units": parser.body_units,
        "visible_units": parser.visible_units,
    }


def _table_shapes(snapshot: Dict[str, Any]) -> List[Any]:
    return [
        (table["rows"], tuple(table["cells_per_row"]), tuple(map(tuple, table["spans"])))
        for table in snapshot["tables"]
    ]


def _table_text(snapshot: Dict[str, Any]) -> List[str]:
    return [text for table in snapshot["tables"] for text in table["texts"]]


def _normal_form(markdown: str) -> str:
    parser = parse_markdown(markdown)
    body = "\n".join(parser["body_units"])
    tables = repr((_table_shapes(parser), _table_text(parser)))
    return f"{body}\n{tables}"


def detect_signals(expected: Dict[str, Any], actual: Dict[str, Any]) -> List[str]:
    signals: List[str] = []
    same_count = expected["table_count"] == actual["table_count"]
    shapes_differ = _table_shapes(expected) != _table_shapes(actual)
    table_text_differ = _table_text(expected) != _table_text(actual)
    body_differ = Counter(expected["body_units"]) != Counter(actual["body_units"])
    visible_same = Counter(expected["visible_units"]) == Counter(actual["visible_units"])
    visible_order_differ = expected["visible_units"] != actual["visible_units"]

    if not same_count:
        signals.append("table_count")
    if same_count and shapes_differ:
        signals.append("table_structure")
    if same_count and not shapes_differ and table_text_differ:
        signals.append("table_text")
    if same_count and body_differ:
        signals.append("body_text")
    if visible_same and visible_order_differ:
        signals.append("reading_order")
    return signals


def build_classification(
    expected: str, actual: str, signals: List[str]
) -> Dict[str, Any]:
    if len(signals) == 1:
        primary = signals[0]
        categories = signals
    elif signals:
        primary = "mixed"
        categories = ["mixed"]
    elif _normal_form(expected) == _normal_form(actual) and expected != actual:
        primary = "formatting"
        categories = ["formatting"]
    else:
        primary = "same"
        categories = ["same"]
    expected_snapshot = parse_markdown(expected)
    actual_snapshot = parse_markdown(actual)
    return {
        "primary_category": primary,
        "categories": categories,
        "signals": signals if signals else (["formatting"] if primary == "formatting" else []),
        "evidence": {
            "table_count": {
                "expected": expected_snapshot["table_count"],
                "actual": actual_snapshot["table_count"],
            },
            "table_shapes_differ": _table_shapes(expected_snapshot)
            != _table_shapes(actual_snapshot),
            "table_text_differ": _table_text(expected_snapshot)
            != _table_text(actual_snapshot),
            "body_text_differ": Counter(expected_snapshot["body_units"])
            != Counter(actual_snapshot["body_units"]),
        },
    }


def classify_markdown(expected: str, actual: str) -> Dict[str, Any]:
    expected_snapshot = parse_markdown(expected)
    actual_snapshot = parse_markdown(actual)
    signals = detect_signals(expected_snapshot, actual_snapshot)
    return build_classification(expected, actual, signals)


def _relative(root: Path, path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _actual_pages(actual_root: Path) -> Tuple[Dict[int, Dict[str, Any]], List[str]]:
    """Use the established scanner, but retain a tolerant index for incomplete pages."""
    try:
        return scan_page_outputs(actual_root), []
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        scan_error = str(exc)

    pages: Dict[int, Dict[str, Any]] = {}
    errors: List[str] = []
    for json_path in sorted(actual_root.rglob("*.json")):
        if json_path.parent.name != "pages":
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            local_index = int(json_path.stem.rsplit("-", 1)[1])
            page_index = source_page_index(json_path, local_index)
            page_type = data.get("page_type")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append("{}: {}".format(json_path, exc))
            continue
        markdown_path = json_path.with_suffix(".md")
        visual_path = json_path.parent.parent / "tables" / (json_path.stem + ".png")
        pages[page_index] = {
            "page_index": page_index,
            "page_type": page_type,
            "json_index": data.get("index"),
            "local_page_index": local_index,
            "source_page_index": page_index,
            "json_path": json_path,
            "markdown_path": markdown_path if markdown_path.exists() else None,
            "visual_path": visual_path if visual_path.exists() else None,
            "visualized_image_path": None,
            "visualized_image_name": None,
        }
    if not pages and scan_error:
        errors.append(scan_error)
    return pages, errors


def _find_label_image(testset_root: Path, page: Dict[str, Any]) -> Optional[Path]:
    for key in ("source_visual_path", "source_table_png"):
        source = page.get(key)
        if not source:
            continue
        for root in (testset_root, testset_root.parent):
            candidate = (root / source).resolve()
            if candidate.exists():
                return candidate
    return None


def make_side_by_side(
    expected_png: Optional[Path], actual_png: Optional[Path], output_png: Path, page_index: int
) -> None:
    """Render two PNGs on one PyMuPDF page, including placeholders for missing inputs."""
    pixmaps: List[Optional[fitz.Pixmap]] = []
    for path in (expected_png, actual_png):
        try:
            pixmaps.append(fitz.Pixmap(str(path)) if path is not None else None)
        except (OSError, RuntimeError, ValueError):
            pixmaps.append(None)
    valid = [pix for pix in pixmaps if pix is not None]
    max_height = max([pix.height for pix in valid] or [360])
    scale = min(1.0, 900.0 / max_height)
    gap = 16
    header = 36
    widths = [max(180, int((pix.width if pix else 360) * scale)) for pix in pixmaps]
    doc = fitz.open()
    page = doc.new_page(width=sum(widths) + gap, height=int(max_height * scale) + header)
    labels = ("LABEL", "CURRENT")
    for index, pix in enumerate(pixmaps):
        x = sum(widths[:index]) + (gap if index else 0)
        rect = fitz.Rect(x, header, x + widths[index], page.rect.height)
        page.insert_text((x + 6, 22), labels[index], fontsize=12, color=(0.1, 0.1, 0.1))
        if pix is None:
            page.draw_rect(rect, color=(0.8, 0.2, 0.2), fill=(0.96, 0.9, 0.9), width=1)
            page.insert_textbox(rect, "MISSING RESOURCE", fontsize=12, align=1, color=(0.6, 0.1, 0.1))
        else:
            page.insert_image(rect, pixmap=pix, keep_proportion=True)
    page.insert_text((page.rect.width - 100, 22), "PAGE {:03d}".format(page_index), fontsize=10)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_png))
    doc.close()


def _diff(expected: str, actual: str) -> str:
    lines = difflib.unified_diff(
        expected.splitlines(), actual.splitlines(), fromfile="label", tofile="current", lineterm=""
    )
    return "\n".join(lines)


def build_review(actual_root: Path, testset_root: Path, review_dir: Path) -> Dict[str, Any]:
    actual_root = Path(actual_root)
    testset_root = Path(testset_root)
    review_dir = Path(review_dir)
    manifest = _load_manifest(testset_root)
    actual_pages, scan_errors = _actual_pages(actual_root)
    pages: List[Dict[str, Any]] = []
    category_counts: Counter = Counter()
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "images").mkdir(parents=True, exist_ok=True)

    manifest_pages = {page["page_index"]: page for page in manifest["pages"]}
    for page_index in range(manifest["page_count"]):
        manifest_page = manifest_pages.get(page_index, {"page_index": page_index, "markdown_status": "failed_no_output"})
        actual = actual_pages.get(page_index)
        expected_md = None
        label_path = manifest_page.get("label_path")
        if label_path:
            expected_md = (testset_root / label_path).resolve()
        actual_md = actual.get("markdown_path") if actual else None
        expected_text = expected_md.read_text(encoding="utf-8") if expected_md and expected_md.exists() else ""
        actual_text = actual_md.read_text(encoding="utf-8") if actual_md and actual_md.exists() else ""
        errors: List[str] = []
        if expected_md is None:
            errors.append("missing label Markdown")
        if actual_md is None:
            errors.append("missing actual Markdown")
        expected_png = _find_label_image(testset_root, manifest_page)
        actual_png = actual.get("visual_path") if actual else None
        if expected_png is None:
            errors.append("missing label PNG")
        if actual_png is None:
            errors.append("missing actual PNG")
        classification = classify_markdown(expected_text, actual_text)
        if errors:
            primary = "missing_resource"
            category_counts[primary] += 1
        else:
            primary = classification["primary_category"]
            category_counts[primary] += 1
        image_path = review_dir / "images" / "page-{:03d}.png".format(page_index)
        make_side_by_side(expected_png, actual_png, image_path, page_index)
        record = dict(classification)
        record.update(
            {
                "page_index": page_index,
                "primary_category": primary,
                "diff": _diff(expected_text, actual_text),
                "label_path": _relative(testset_root, expected_md),
                "source_markdown": _relative(actual_root, actual_md),
                "label_png": _relative(testset_root, expected_png),
                "source_png": _relative(actual_root, actual_png),
                "source_visual_path": manifest_page.get("source_visual_path"),
                "source_table_png": manifest_page.get("source_table_png"),
                "image_path": "images/page-{:03d}.png".format(page_index),
                "errors": errors,
                "source_json": _relative(actual_root, actual.get("json_path") if actual else None),
            }
        )
        pages.append(record)

    payload = {"pages": pages, "category_counts": dict(category_counts)}
    (review_dir / "classification.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "page_count": len(pages),
        "diff_count": sum(1 for page in pages if page["primary_category"] != "same"),
        "category_counts": dict(category_counts),
        "pages": pages,
        "scan_errors": scan_errors,
    }
    (review_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data = json.dumps(pages, ensure_ascii=False).replace("</", "<\\/")
    links = "\n".join(
        '<li>Page {0}: <a href="images/page-{0:03d}.png">page-{0:03d}.png</a></li>'.format(page["page_index"])
        for page in pages
    )
    (review_dir / "index.html").write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>PDF diff review</title>"
        "<ul>{}</ul><script>window.reviewPages={};</script>".format(links, data),
        encoding="utf-8",
    )
    return summary
