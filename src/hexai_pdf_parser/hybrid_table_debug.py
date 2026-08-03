"""中文使用说明：PDF 表格区域和二维结构可视化模块。

用途：并列展示有线表、Span 无线/混合表和 Camelot Stream 对照候选，方便
人工检查区域边界、分表结果和单元格归属。绿色 R 为有线表，紫色 W 为无线
或混合表，橙色虚线 C 仅是 Camelot 对照候选。

PowerShell 最小运行方式（页码从 1 开始）：
``$env:PYTHONPATH = 'src'`` 后执行
``python -m hexai_pdf_parser.hybrid_table_debug 输入.pdf --output 输出目录 --pages 3 4 --dpi 160``。
输出每页的彩色 PNG、HTML 结构表和 JSON 诊断证据。激活 ``company_tool``
环境后可直接使用 ``python``。

Hybrid table diagnostics for ruled and borderless native PDF tables.

绿色代表 PyMuPDF 找到的有线表，紫色代表改进后的 Span 无线恢复，
橙色代表 Camelot Stream 候选区域。单元格使用与父表相同的浅色，便于
人工检查区域归属、分表边界和二维结构。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import fitz

from hexai_pdf_parser.models import Cell, Table
from hexai_pdf_parser.table_extractor import TableExtractor


_COLORS = {
    "ruled": (0.05, 0.60, 0.30),
    "wireless": (0.62, 0.20, 0.89),
    "camelot_stream": (0.95, 0.45, 0.05),
}
_CELL_COLORS = {
    "ruled": (0.15, 0.70, 0.42),
    "wireless": (0.08, 0.50, 0.95),
}


def _kind(source: str | None) -> str:
    return "wireless" if source == "wireless_span_recovery" else "ruled"


def _bbox_payload(table: Table) -> Dict[str, float]:
    return {
        "x0": table.bbox.x0,
        "y0": table.bbox.y0,
        "x1": table.bbox.x1,
        "y1": table.bbox.y1,
    }


def _cell_payload(cell: Cell) -> Dict[str, Any]:
    return {
        "row": cell.row_index,
        "col": cell.col_index,
        "rowspan": cell.rowspan,
        "colspan": cell.colspan,
        "text": cell.text,
        "bbox": {
            "x0": cell.bbox.x0,
            "y0": cell.bbox.y0,
            "x1": cell.bbox.x1,
            "y1": cell.bbox.y1,
        },
    }


def _has_complete_ruled_grid(table: Table) -> bool:
    """Reject find_tables artifacts made from isolated colour bands or prose lines."""

    if table.rows < 2 or table.cols < 2:
        return False
    covered = sum(
        max(1, cell.rowspan) * max(1, cell.colspan)
        for cell in table.cells
        if cell.text.strip()
    )
    return covered / float(table.rows * table.cols) >= 0.60


def _is_numbered_prose(table: Table) -> bool:
    """Reject wrapped numbered paragraphs that merely happen to share two x positions."""

    long_numbered = [
        cell for cell in table.cells
        if re.match(r"^\s*\d+[.、]", cell.text) and len(cell.text.strip()) >= 45
    ]
    return len(long_numbered) >= 2


def _camelot_stream_regions(pdf_path: str, page_index: int, page_height: float) -> List[Dict[str, Any]]:
    """Read Camelot Stream only as a visible comparison signal, never as truth."""

    try:
        import camelot  # type: ignore
    except ImportError:
        return []
    try:
        tables = camelot.read_pdf(pdf_path, pages=str(page_index + 1), flavor="stream")
    except Exception as exc:
        return [{"error": str(exc)}]
    regions: List[Dict[str, Any]] = []
    for index, table in enumerate(tables, start=1):
        x0, y0, x1, y1 = (float(value) for value in getattr(table, "_bbox", (0, 0, 0, 0)))
        report = getattr(table, "parsing_report", {}) or {}
        cols = int(table.shape[1])
        regions.append({
            "id": f"C{index}",
            "kind": "camelot_stream",
            "bbox": {"x0": x0, "y0": page_height - y1, "x1": x1, "y1": page_height - y0},
            "rows": int(table.shape[0]),
            "cols": cols,
            "accuracy": float(report.get("accuracy", 0.0)),
            "whitespace": float(report.get("whitespace", 0.0)),
            "accepted": cols >= 2,
            "rejected_reason": None if cols >= 2 else "Camelot Stream 单列候选，判定为正文而非二维表格",
        })
    return regions


def analyse_hybrid_tables(pdf_path: str, page_index: int) -> Tuple[fitz.Document, fitz.Page, Dict[str, Any]]:
    """Collect both parser structures and Camelot Stream comparison evidence."""

    document = fitz.open(pdf_path)
    page = document[page_index]
    tables = TableExtractor().extract(page)
    numbered: List[Dict[str, Any]] = []
    rejected_ruled: List[Dict[str, Any]] = []
    rejected_wireless: List[Dict[str, Any]] = []
    accepted: List[Table] = []
    counts = {"ruled": 0, "wireless": 0}
    for table in tables:
        kind = _kind(table.source)
        if table.source == "text_alignment":
            rejected_ruled.append({
                "source": table.source,
                "rows": table.rows,
                "cols": table.cols,
                "bbox": _bbox_payload(table),
                "rejected_reason": "legacy text alignment is a fallback candidate, not confirmed ruled-grid evidence",
            })
            continue
        if kind == "ruled" and not _has_complete_ruled_grid(table):
            rejected_ruled.append({
                "source": table.source,
                "rows": table.rows,
                "cols": table.cols,
                "bbox": _bbox_payload(table),
                "rejected_reason": "有线候选的单元格覆盖不足，疑似色带或正文分隔线",
            })
            continue
        if kind == "wireless" and _is_numbered_prose(table):
            rejected_wireless.append({
                "source": table.source,
                "rows": table.rows,
                "cols": table.cols,
                "bbox": _bbox_payload(table),
                "rejected_reason": "编号正文的换行片段，不是二维表格",
            })
            continue
        accepted.append(table)
    for table in sorted(accepted, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        kind = _kind(table.source)
        counts[kind] += 1
        numbered.append(
            {
                "id": ("R" if kind == "ruled" else "W") + str(counts[kind]),
                "kind": kind,
                "source": table.source,
                "rows": table.rows,
                "cols": table.cols,
                "confidence": table.confidence,
                "bbox": _bbox_payload(table),
                "cells": [_cell_payload(cell) for cell in table.cells],
                "_table": table,
            }
        )
    result = {
        "page_index": page_index,
        "legend": {
            "R": "绿色：有线表（PyMuPDF / 线条结构）",
            "W": "紫色：无线表（原始 Span + 空间列轨迹）",
            "C": "橙色：Camelot Stream 对照候选",
        },
        "tables": numbered,
        "rejected_ruled": rejected_ruled,
        "rejected_wireless": rejected_wireless,
        "camelot_stream": _camelot_stream_regions(pdf_path, page_index, page.rect.height),
    }
    return document, page, result


def _html_table(item: Dict[str, Any]) -> str:
    cells = {(cell["row"], cell["col"]): cell for cell in item["cells"]}
    rows: List[str] = []
    for row in range(item["rows"]):
        parts: List[str] = []
        col = 0
        while col < item["cols"]:
            cell = cells.get((row, col))
            if cell is None:
                parts.append("<td></td>")
                col += 1
                continue
            attrs = ""
            if cell["colspan"] > 1:
                attrs += f' colspan="{cell["colspan"]}"'
            if cell["rowspan"] > 1:
                attrs += f' rowspan="{cell["rowspan"]}"'
            parts.append(f"<td{attrs}>{html.escape(cell['text']).replace(chr(10), '<br>')}</td>")
            col += max(1, cell["colspan"])
        rows.append("<tr>" + "".join(parts) + "</tr>")
    return f"<section class='{item['kind']}'><h2>{item['id']} · {html.escape(str(item['source']))} · {item['rows']}×{item['cols']}</h2><table>{''.join(rows)}</table></section>"


def export_hybrid_debug(pdf_path: str, page_index: int, output_dir: str, dpi: int = 180) -> Dict[str, str]:
    """Export one page's colored regions, cell structure, HTML and JSON evidence."""

    document, page, result = analyse_hybrid_tables(pdf_path, page_index)
    try:
        os.makedirs(output_dir, exist_ok=True)
        stem = f"page-{page_index + 1:03d}-hybrid"
        json_path = os.path.join(output_dir, stem + ".json")
        html_path = os.path.join(output_dir, stem + ".html")
        image_path = os.path.join(output_dir, stem + ".png")
        serializable = {key: value for key, value in result.items() if key != "tables"}
        serializable["tables"] = [{key: value for key, value in item.items() if key != "_table"} for item in result["tables"]]
        Path(json_path).write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        markup = "".join(_html_table(item) for item in result["tables"]) or "<p>未发现表格。</p>"
        Path(html_path).write_text(
            "<!doctype html><meta charset='utf-8'><style>body{font-family:Arial,sans-serif;padding:20px}table{border-collapse:collapse;margin-bottom:28px}td{border:1px solid #999;padding:4px 8px;vertical-align:top}.ruled h2{color:#0a994d}.wireless h2{color:#9e33df}</style>"
            + markup,
            encoding="utf-8",
        )

        overlay = fitz.open()
        try:
            target = overlay.new_page(width=page.rect.width, height=page.rect.height)
            target.show_pdf_page(target.rect, document, page_index)
            for candidate in result["camelot_stream"]:
                if "bbox" not in candidate or not candidate.get("accepted", False):
                    continue
                box = candidate["bbox"]
                target.draw_rect(fitz.Rect(box["x0"], box["y0"], box["x1"], box["y1"]), color=_COLORS["camelot_stream"], width=1.1, dashes="[4 3] 0", overlay=True)
                target.insert_text((box["x0"] + 2, max(10, box["y0"] - 3)), candidate["id"], fontsize=7, color=_COLORS["camelot_stream"], overlay=True)
            for item in result["tables"]:
                table = item["_table"]
                color = _COLORS[item["kind"]]
                target.draw_rect(fitz.Rect(table.bbox.x0, table.bbox.y0, table.bbox.x1, table.bbox.y1), color=color, width=1.8, overlay=True)
                target.insert_text((table.bbox.x0 + 2, max(10, table.bbox.y0 - 3)), item["id"], fontsize=8, color=color, overlay=True)
                for cell in table.cells:
                    cell_color = _CELL_COLORS[item["kind"]]
                    target.draw_rect(fitz.Rect(cell.bbox.x0, cell.bbox.y0, cell.bbox.x1, cell.bbox.y1), color=cell_color, width=0.7, fill=cell_color, fill_opacity=0.04, overlay=True)
            pix = target.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            pix.save(image_path)
        finally:
            overlay.close()
        return {"json": json_path, "html": html_path, "image": image_path}
    finally:
        document.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize ruled, wireless and Camelot Stream table structures.")
    parser.add_argument("pdf_path")
    parser.add_argument("--output", "-o", default="hybrid-table-debug")
    parser.add_argument("--pages", type=int, nargs="+", required=True, help="1-based page numbers")
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()
    for page_number in args.pages:
        paths = export_hybrid_debug(args.pdf_path, page_number - 1, args.output, args.dpi)
        print(json.dumps({"page": page_number, **paths}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
