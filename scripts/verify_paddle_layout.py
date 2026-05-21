"""Verify Paddle layout detection on a PDF and visualize the results.

This script compares Paddle layout detections against the existing
line-based table extraction results, then writes:

* per-page overlay PNGs on the original page image
* a machine-readable summary JSON

It is intentionally standalone so it can be run once the Paddle runtime
dependencies are available in the environment.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

import fitz

from pdflayoutparser.models import BBox
from pdflayoutparser.table_extractor import TableExtractor


@dataclass
class PageSummary:
    page_index: int
    source_image: str
    overlay_image: str
    line_table_count: int
    paddle_table_count: int
    retained_table_count: int
    dropped_table_count: int
    labels: dict[str, int]
    render_seconds: float
    line_extract_seconds: float
    paddle_seconds: float
    filter_seconds: float
    overlay_seconds: float
    total_seconds: float


def _label_color(label: str) -> tuple[float, float, float]:
    """Map Paddle labels to stable overlay colors."""
    if label == "table":
        return (0.10, 0.45, 0.95)
    if label in {
        "image",
        "figure",
        "chart",
        "header_image",
        "footer_image",
    }:
        return (0.95, 0.55, 0.10)
    if label in {"doc_title", "paragraph_title", "figure_title", "chart_title", "table_title"}:
        return (0.62, 0.20, 0.89)
    if label in {"header", "footer", "footnote", "aside_text"}:
        return (0.45, 0.45, 0.45)
    if label in {"formula", "formula_number", "number"}:
        return (0.18, 0.68, 0.66)
    if label == "seal":
        return (0.85, 0.20, 0.18)
    return (0.22, 0.58, 0.28)


def _require_paddle_layout_model(model_name: str, model_dir: str, backend: str):
    """Create a Paddle layout detector using whichever runtime is available."""
    last_error: Exception | None = None

    if backend in {"auto", "paddleocr"}:
        try:
            from paddleocr import LayoutDetection

            return LayoutDetection(
                model_name=model_name,
                model_dir=model_dir,
                device="cpu",
            )
        except Exception as exc:  # pragma: no cover - import/runtime dependent
            last_error = exc
            if backend == "paddleocr":
                raise

    if backend in {"auto", "paddlex"}:
        try:
            from paddlex import create_model

            return create_model(model_name=model_name, model_dir=model_dir)
        except Exception as exc:  # pragma: no cover - import/runtime dependent
            last_error = exc
            if backend == "paddlex":
                raise

    raise RuntimeError(
        "Unable to create a Paddle layout detector. "
        "Install paddleocr or paddlex, then retry."
    ) from last_error


def _box_to_bbox(box: dict[str, Any]) -> BBox:
    x0, y0, x1, y1 = box["coordinate"]
    return BBox(float(x0), float(y0), float(x1), float(y1))


def _overlap_ratio(a: BBox, b: BBox) -> float:
    ix0 = max(a.x0, b.x0)
    iy0 = max(a.y0, b.y0)
    ix1 = min(a.x1, b.x1)
    iy1 = min(a.y1, b.y1)
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area = max((a.x1 - a.x0) * (a.y1 - a.y0), 1e-6)
    return inter / area


def _has_significant_overlap(box: BBox, line_tables: list[BBox], threshold: float) -> bool:
    return any(_overlap_ratio(box, wire_box) >= threshold for wire_box in line_tables)


def _render_overlay(
    page: fitz.Page,
    line_boxes: list[BBox],
    paddle_boxes: list[dict[str, Any]],
    retained_boxes: list[BBox],
    output_path: Path,
    dpi: int,
) -> None:
    """Draw comparison boxes on a page and save the rendered PNG."""
    for bbox in line_boxes:
        page.draw_rect(
            fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
            color=(0.12, 0.62, 0.26),
            width=2.0,
            overlay=True,
        )

    for item in paddle_boxes:
        bbox = item["bbox"]
        label = item["label"]
        color = _label_color(label)
        page.draw_rect(
            fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
            color=color,
            width=1.2,
            overlay=True,
        )
        label_y = max(bbox.y0 - 2, 6)
        page.insert_text(
            (bbox.x0 + 1, label_y),
            label,
            fontsize=4.5,
            color=color,
            overlay=True,
        )

    for bbox in retained_boxes:
        page.draw_rect(
            fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
            color=(0.90, 0.20, 0.15),
            width=2.2,
            overlay=True,
        )

    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(str(output_path))


def _to_result_iter(raw_result: Any) -> Iterable[Any]:
    if hasattr(raw_result, "json"):
        return [raw_result]
    if isinstance(raw_result, list):
        return raw_result
    try:
        return list(raw_result)
    except TypeError:
        return [raw_result]


def _extract_boxes_from_result(result: Any) -> list[dict[str, Any]]:
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if payload is None:
        payload = result

    if isinstance(payload, str):
        payload = json.loads(payload)

    if isinstance(payload, dict):
        res = payload.get("res", payload)
        return list(res.get("boxes", []))

    raise TypeError(f"Unsupported Paddle result payload: {type(payload)!r}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Paddle layout detection on a PDF and visualize overlap with line tables.",
    )
    parser.add_argument("pdf_path", help="Path to the PDF to analyze")
    parser.add_argument(
        "-o",
        "--output",
        default="out_paddle_verify",
        help="Directory for generated visualizations and stats",
    )
    parser.add_argument(
        "--model-name",
        default="PP-DocLayout-M",
        help="Paddle layout model name",
    )
    parser.add_argument(
        "--model-dir",
        default=str(Path("src") / "models" / "PP-DocLayout-M_infer"),
        help="Path to the Paddle inference model directory",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "paddleocr", "paddlex"],
        default="auto",
        help="Which Paddle runtime to use",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Render DPI for page overlays",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="Layout confidence threshold",
    )
    parser.add_argument(
        "--overlap-threshold",
        type=float,
        default=0.3,
        help="Overlap ratio threshold for removing Paddle boxes that match wired tables",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    output_dir = Path(args.output)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    detector = _require_paddle_layout_model(
        model_name=args.model_name,
        model_dir=args.model_dir,
        backend=args.backend,
    )

    summary_pages: list[PageSummary] = []
    overall_start = perf_counter()
    pdf_doc = fitz.open(str(pdf_path))
    try:
        wired_extractor = TableExtractor()

        for page in pdf_doc:
            page_start = perf_counter()
            page_index = page.number
            source_image = pages_dir / f"page-{page_index:03d}-source.png"
            overlay_image = pages_dir / f"page-{page_index:03d}-overlay.png"

            render_start = perf_counter()
            matrix = fitz.Matrix(args.dpi / 72.0, args.dpi / 72.0)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            pix.save(str(source_image))
            render_seconds = perf_counter() - render_start

            line_start = perf_counter()
            wired_tables = wired_extractor._extract_via_lines(page)
            line_boxes = [t.bbox for t in wired_tables]
            line_extract_seconds = perf_counter() - line_start

            paddle_start = perf_counter()
            raw_result = detector.predict(
                str(source_image),
                batch_size=1,
                threshold=args.threshold,
                layout_nms=True,
            )
            paddle_boxes: list[dict[str, Any]] = []
            labels: Counter[str] = Counter()
            for result in _to_result_iter(raw_result):
                for box in _extract_boxes_from_result(result):
                    label = box.get("label", "unknown")
                    labels[label] += 1
                    paddle_boxes.append(
                        {
                            "bbox": _box_to_bbox(box),
                            "label": label,
                            "score": box.get("score"),
                        }
                    )
            paddle_seconds = perf_counter() - paddle_start

            filter_start = perf_counter()
            paddle_table_boxes = [
                item["bbox"] for item in paddle_boxes if item["label"] == "table"
            ]
            retained_boxes = [
                box
                for box in paddle_table_boxes
                if not _has_significant_overlap(
                    box, line_boxes, threshold=args.overlap_threshold
                )
            ]
            dropped_count = len(paddle_table_boxes) - len(retained_boxes)
            filter_seconds = perf_counter() - filter_start

            overlay_start = perf_counter()
            _render_overlay(
                page=page,
                line_boxes=line_boxes,
                paddle_boxes=paddle_boxes,
                retained_boxes=retained_boxes,
                output_path=overlay_image,
                dpi=args.dpi,
            )
            overlay_seconds = perf_counter() - overlay_start

            total_seconds = perf_counter() - page_start
            summary_pages.append(
                PageSummary(
                    page_index=page_index,
                    source_image=str(source_image.relative_to(output_dir)),
                    overlay_image=str(overlay_image.relative_to(output_dir)),
                    line_table_count=len(line_boxes),
                    paddle_table_count=len(paddle_boxes),
                    retained_table_count=len(retained_boxes),
                    dropped_table_count=dropped_count,
                    labels=dict(labels),
                    render_seconds=render_seconds,
                    line_extract_seconds=line_extract_seconds,
                    paddle_seconds=paddle_seconds,
                    filter_seconds=filter_seconds,
                    overlay_seconds=overlay_seconds,
                    total_seconds=total_seconds,
                )
            )
    finally:
        pdf_doc.close()

    total_seconds = perf_counter() - overall_start
    summary = {
        "pdf_path": str(pdf_path),
        "model_name": args.model_name,
        "model_dir": str(Path(args.model_dir)),
        "page_count": len(summary_pages),
        "total_seconds": total_seconds,
        "pages": [asdict(item) for item in summary_pages],
        "totals": {
            "line_tables": sum(item.line_table_count for item in summary_pages),
            "paddle_tables": sum(item.paddle_table_count for item in summary_pages),
            "retained_tables": sum(item.retained_table_count for item in summary_pages),
            "dropped_tables": sum(item.dropped_table_count for item in summary_pages),
            "render_seconds": sum(item.render_seconds for item in summary_pages),
            "line_extract_seconds": sum(item.line_extract_seconds for item in summary_pages),
            "paddle_seconds": sum(item.paddle_seconds for item in summary_pages),
            "filter_seconds": sum(item.filter_seconds for item in summary_pages),
            "overlay_seconds": sum(item.overlay_seconds for item in summary_pages),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    stats_path = output_dir / "summary.json"
    stats_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    print(f"Wrote: {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
