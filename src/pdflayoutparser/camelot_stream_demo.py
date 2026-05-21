"""Standalone Camelot stream demo helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz


def _load_camelot() -> Any:
    try:
        import camelot  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised in manual use
        raise ImportError(
            "camelot is required for the stream demo. Install with "
            "`pip install pdflayoutparser[demo]`."
        ) from exc
    return camelot


def extract_camelot_stream_tables(pdf_path: str, page: int) -> list[Any]:
    """Run Camelot stream mode and return raw table objects."""

    camelot = _load_camelot()
    return list(camelot.read_pdf(pdf_path, pages=str(page), flavor="stream"))


def _table_bbox(table: Any) -> tuple[float, float, float, float]:
    bbox = getattr(table, "bbox", None) or getattr(table, "_bbox", None)
    if bbox is None:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(float(v) for v in bbox)


def _table_rows(table: Any) -> list[list[str]]:
    df = getattr(table, "df", None)
    if df is None:
        return []
    if hasattr(df, "astype"):
        try:
            return df.astype(str).fillna("").values.tolist()
        except Exception:
            pass
    if hasattr(df, "to_dict"):
        try:
            records = df.to_dict(orient="records")
            return [
                [str(value) for value in row.values()]
                for row in records
            ]
        except Exception:
            pass
    return []


def summarize_camelot_tables(tables: list[Any], page: int) -> dict[str, Any]:
    summary_tables: list[dict[str, Any]] = []
    for table in tables:
        rows = _table_rows(table)
        nrows = len(rows)
        ncols = len(rows[0]) if rows else getattr(table, "shape", (0, 0))[1]
        summary_tables.append(
            {
                "rows": nrows,
                "cols": ncols,
                "bbox": {
                    "x0": _table_bbox(table)[0],
                    "y0": _table_bbox(table)[1],
                    "x1": _table_bbox(table)[2],
                    "y1": _table_bbox(table)[3],
                },
                "sample_rows": rows[:5],
            }
        )

    return {
        "page": page,
        "table_count": len(summary_tables),
        "tables": summary_tables,
    }


def render_camelot_preview(
    pdf_path: str,
    page: int,
    tables: list[Any],
    output_path: str,
    dpi: int = 200,
) -> str:
    doc = fitz.open(pdf_path)
    try:
        page_obj = doc[page - 1]
        for table in tables:
            x0, y0, x1, y1 = _table_bbox(table)
            rect = fitz.Rect(x0, y0, x1, y1)
            page_obj.draw_rect(rect, color=(0.95, 0.2, 0.1), width=2.0, overlay=True)

        pix = page_obj.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        pix.save(output_path)
        return output_path
    finally:
        doc.close()


def run_camelot_stream_demo(
    pdf_path: str,
    *,
    page: int,
    output_dir: str,
    dpi: int = 200,
) -> dict[str, Any]:
    tables = extract_camelot_stream_tables(pdf_path, page)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_path = out_dir / f"page-{page:03d}-camelot-stream.png"
    summary_path = out_dir / f"page-{page:03d}-camelot-stream.json"

    preview = render_camelot_preview(pdf_path, page, list(tables), str(preview_path), dpi=dpi)
    summary = summarize_camelot_tables(list(tables), page)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "preview_path": preview,
        "summary_path": str(summary_path),
        "summary": summary,
    }
