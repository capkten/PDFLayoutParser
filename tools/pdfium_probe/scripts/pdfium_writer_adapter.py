"""PDFium Rust Markdown and JSON writer adapter.

Provides Python integration for invoking the compiled `pdfium_probe markdown` and
`pdfium_probe json` CLIs, converting tables and page layouts into standard Markdown
reading flow strings and unified page JSON dictionaries.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union


def _find_pdfium_probe_bin() -> Optional[str]:
    """Locate compiled pdfium_probe binary (debug or release)."""
    env_bin = os.environ.get("PDFIUM_PROBE_BIN")
    if env_bin:
        cand = Path(env_bin)
        if cand.is_file():
            return str(cand.resolve())

    probe_root = Path(__file__).resolve().parents[1]
    fallback_repo = (
        probe_root.parents[1]
        if len(probe_root.parents) > 1
        else probe_root.parent.parent
    )
    repo_root = Path(os.environ.get("REPO_ROOT", str(fallback_repo)))
    bin_names = (
        ["pdfium_probe.exe", "pdfium_probe"]
        if os.name == "nt"
        else ["pdfium_probe", "pdfium_probe.exe"]
    )

    candidate_dirs: List[Path] = []
    cargo_target_dir = os.environ.get("CARGO_TARGET_DIR")
    if cargo_target_dir:
        c_target = Path(cargo_target_dir)
        candidate_dirs.extend([
            c_target / "release",
            c_target / "debug",
        ])

    candidate_dirs.extend([
        probe_root / "target" / "release",
        probe_root / "target" / "debug",
        fallback_repo / "tools" / "pdfium_probe" / "target" / "release",
        fallback_repo / "tools" / "pdfium_probe" / "target" / "debug",
        repo_root / "tools" / "pdfium_probe" / "target" / "release",
        repo_root / "tools" / "pdfium_probe" / "target" / "debug",
    ])

    for cdir in candidate_dirs:
        for bname in bin_names:
            cand = cdir / bname
            if cand.is_file():
                return str(cand.resolve())

    for bname in bin_names:
        which_path = shutil.which(bname)
        if which_path:
            p = Path(which_path)
            if p.is_file():
                return str(p.resolve())

    return None


def _resolve_target_pdf(pdf_path: Union[str, Path]) -> Optional[Path]:
    target_pdf = Path(pdf_path)
    if target_pdf.is_file():
        return target_pdf

    probe_root = Path(__file__).resolve().parents[1]
    fallback_synth = probe_root / "test_data" / "synthetic" / target_pdf.name
    if fallback_synth.is_file():
        return fallback_synth

    repo_root = Path(os.environ.get("REPO_ROOT", str(probe_root.parents[1])))
    fallback_repo = repo_root / target_pdf.name
    if fallback_repo.is_file():
        return fallback_repo

    return None


def _extract_bbox_list(b: Any) -> Optional[List[float]]:
    if hasattr(b, "x0") and hasattr(b, "y0") and hasattr(b, "x1") and hasattr(b, "y1"):
        return [float(b.x0), float(b.y0), float(b.x1), float(b.y1)]
    elif isinstance(b, (list, tuple)) and len(b) >= 4:
        return [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
    elif isinstance(b, dict):
        if all(k in b for k in ("x0", "y0", "x1", "y1")):
            return [
                float(b["x0"]),
                float(b["y0"]),
                float(b["x1"]),
                float(b["y1"]),
            ]
    return None


def _normalize_cell(cell: Any) -> Dict[str, Any]:
    if isinstance(cell, dict):
        text = str(cell.get("text", ""))
        r_idx = int(cell.get("row_index", 0))
        c_idx = int(cell.get("col_index", 0))
        r_span = int(cell.get("rowspan", 1) or 1)
        c_span = int(cell.get("colspan", 1) or 1)
        cb = _extract_bbox_list(cell.get("bbox", [0.0, 0.0, 0.0, 0.0])) or [0.0, 0.0, 0.0, 0.0]
    else:
        text = str(getattr(cell, "text", ""))
        r_idx = int(getattr(cell, "row_index", 0))
        c_idx = int(getattr(cell, "col_index", 0))
        r_span = int(getattr(cell, "rowspan", 1) or 1)
        c_span = int(getattr(cell, "colspan", 1) or 1)
        cb = _extract_bbox_list(getattr(cell, "bbox", [0.0, 0.0, 0.0, 0.0])) or [0.0, 0.0, 0.0, 0.0]

    return {
        "text": text,
        "row_index": r_idx,
        "col_index": c_idx,
        "rowspan": r_span,
        "colspan": c_span,
        "bbox": cb,
    }


def normalize_full_tables_for_probe(tables: Sequence[Any]) -> List[Dict[str, Any]]:
    """Normalize input tables into `[{"table_id": int, "bbox": [x0, y0, x1, y1], "rows": int, "cols": int, "cells": [...]}]` format."""
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(tables):
        table_id = getattr(item, "table_id", getattr(item, "id", None))
        if table_id is None and isinstance(item, dict):
            table_id = item.get("table_id", item.get("id", item.get("table_index")))
        if table_id is None:
            table_id = idx

        bbox: Optional[List[float]] = None
        if hasattr(item, "bbox"):
            bbox = _extract_bbox_list(item.bbox)
        elif isinstance(item, dict):
            if "bbox" in item:
                bbox = _extract_bbox_list(item["bbox"])
            elif all(k in item for k in ("x0", "y0", "x1", "y1")):
                bbox = [float(item["x0"]), float(item["y0"]), float(item["x1"]), float(item["y1"])]
        elif isinstance(item, (list, tuple)) and len(item) >= 4:
            bbox = [float(item[0]), float(item[1]), float(item[2]), float(item[3])]

        if bbox is None:
            bbox = [0.0, 0.0, 0.0, 0.0]

        rows = getattr(item, "rows", None)
        if rows is None and isinstance(item, dict):
            rows = item.get("rows")

        cols = getattr(item, "cols", None)
        if cols is None and isinstance(item, dict):
            cols = item.get("cols")

        raw_cells = getattr(item, "cells", None)
        if raw_cells is None and isinstance(item, dict):
            raw_cells = item.get("cells", [])
        if raw_cells is None:
            raw_cells = []

        norm_cells = [_normalize_cell(c) for c in raw_cells]

        inferred_rows = max([c["row_index"] + c["rowspan"] for c in norm_cells], default=0)
        inferred_cols = max([c["col_index"] + c["colspan"] for c in norm_cells], default=0)

        final_rows = int(rows) if rows is not None and int(rows) > 0 else inferred_rows
        final_cols = int(cols) if cols is not None and int(cols) > 0 else inferred_cols

        confidence = getattr(item, "confidence", None)
        if confidence is None and isinstance(item, dict):
            confidence = item.get("confidence")

        source = getattr(item, "source", None)
        if source is None and isinstance(item, dict):
            source = item.get("source")

        tbl_dict: Dict[str, Any] = {
            "table_id": int(table_id),
            "bbox": bbox,
            "rows": final_rows,
            "cols": final_cols,
            "cells": norm_cells,
        }
        if confidence is not None:
            tbl_dict["confidence"] = float(confidence)
        if source is not None:
            tbl_dict["source"] = str(source)

        normalized.append(tbl_dict)
    return normalized


def _python_fallback_markdown(
    pdf_path: Path,
    page_index: int,
    tables: Sequence[Any],
) -> str:
    """Fallback Markdown generation using Python pipeline if probe binary is unavailable."""
    try:
        from pdfium_layout_adapter import extract_layout_with_rust_probe, _python_fallback_layout
        from hexai_pdf_parser.writers.markdown_writer import MarkdownWriter
        from hexai_pdf_parser.core.models import Page

        elements = extract_layout_with_rust_probe(pdf_path, page_index, tables)
        if not elements:
            elements = _python_fallback_layout(pdf_path, page_index, tables)

        page = Page(
            index=page_index,
            size={"width": 612.0, "height": 792.0},
            rotation=0,
            layout_elements=elements,
        )
        writer = MarkdownWriter()
        lines: List[str] = []
        for elem in page.layout_elements:
            lines.extend(writer._render_element(elem, page.index))
        return "\n".join(lines)
    except Exception:
        return ""


def _python_fallback_json(
    pdf_path: Path,
    page_index: int,
    tables: Sequence[Any],
) -> Dict[str, Any]:
    """Fallback JSON generation using Python pipeline if probe binary is unavailable."""
    try:
        from pdfium_layout_adapter import extract_layout_with_rust_probe, _python_fallback_layout
        from hexai_pdf_parser.writers.json_writer import JSONWriter
        from hexai_pdf_parser.core.models import Page

        elements = extract_layout_with_rust_probe(pdf_path, page_index, tables)
        if not elements:
            elements = _python_fallback_layout(pdf_path, page_index, tables)

        page = Page(
            index=page_index,
            size={"width": 612.0, "height": 792.0},
            rotation=0,
            layout_elements=elements,
        )
        writer = JSONWriter()
        return writer._page_to_dict(page)
    except Exception:
        return {}


def render_markdown_with_rust_probe(
    pdf_path: Union[str, Path],
    page_index: int,
    tables: Sequence[Any] = (),
) -> str:
    """Execute `pdfium_probe markdown` CLI and return rendered Markdown string.

    Args:
        pdf_path: Path to target PDF document.
        page_index: 0-based page index.
        tables: Sequence of Table objects or table dicts.

    Returns:
        Rendered Markdown reading flow string.
    """
    target_pdf = _resolve_target_pdf(pdf_path)
    if target_pdf is None:
        return _python_fallback_markdown(Path(pdf_path), page_index, tables)

    probe_bin_str = _find_pdfium_probe_bin()
    if probe_bin_str is None:
        return _python_fallback_markdown(target_pdf, page_index, tables)

    probe_bin = Path(probe_bin_str)
    if not probe_bin.is_file():
        return _python_fallback_markdown(target_pdf, page_index, tables)

    norm_tables = normalize_full_tables_for_probe(tables)

    # Windows safety: flush and close file handles before passing paths to child process
    tables_tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tables_tmp_path = Path(tables_tmp.name)
    try:
        tables_tmp.write(json.dumps(norm_tables, ensure_ascii=False).encode("utf-8"))
    finally:
        tables_tmp.close()

    out_tmp = tempfile.NamedTemporaryFile(suffix=".md", delete=False)
    out_tmp_path = Path(out_tmp.name)
    out_tmp.close()

    try:
        cmd = [
            str(probe_bin),
            "markdown",
            str(target_pdf.resolve()),
            str(page_index),
            str(tables_tmp_path.resolve()),
            str(out_tmp_path.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            return _python_fallback_markdown(target_pdf, page_index, tables)

        if not out_tmp_path.is_file():
            return _python_fallback_markdown(target_pdf, page_index, tables)

        return out_tmp_path.read_text(encoding="utf-8")

    except Exception:
        return _python_fallback_markdown(target_pdf, page_index, tables)

    finally:
        if tables_tmp_path.is_file():
            try:
                tables_tmp_path.unlink()
            except OSError:
                pass
        if out_tmp_path.is_file():
            try:
                out_tmp_path.unlink()
            except OSError:
                pass


def export_json_with_rust_probe(
    pdf_path: Union[str, Path],
    page_index: int,
    tables: Sequence[Any] = (),
) -> Dict[str, Any]:
    """Execute `pdfium_probe json` CLI and return unified page JSON dictionary.

    Args:
        pdf_path: Path to target PDF document.
        page_index: 0-based page index.
        tables: Sequence of Table objects or table dicts.

    Returns:
        Unified page JSON dictionary.
    """
    target_pdf = _resolve_target_pdf(pdf_path)
    if target_pdf is None:
        return _python_fallback_json(Path(pdf_path), page_index, tables)

    probe_bin_str = _find_pdfium_probe_bin()
    if probe_bin_str is None:
        return _python_fallback_json(target_pdf, page_index, tables)

    probe_bin = Path(probe_bin_str)
    if not probe_bin.is_file():
        return _python_fallback_json(target_pdf, page_index, tables)

    norm_tables = normalize_full_tables_for_probe(tables)

    # Windows safety: flush and close file handles before passing paths to child process
    tables_tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tables_tmp_path = Path(tables_tmp.name)
    try:
        tables_tmp.write(json.dumps(norm_tables, ensure_ascii=False).encode("utf-8"))
    finally:
        tables_tmp.close()

    out_tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_tmp_path = Path(out_tmp.name)
    out_tmp.close()

    try:
        cmd = [
            str(probe_bin),
            "json",
            str(target_pdf.resolve()),
            str(page_index),
            str(tables_tmp_path.resolve()),
            str(out_tmp_path.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            return _python_fallback_json(target_pdf, page_index, tables)

        if not out_tmp_path.is_file() or out_tmp_path.stat().st_size == 0:
            return _python_fallback_json(target_pdf, page_index, tables)

        with open(out_tmp_path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return _python_fallback_json(target_pdf, page_index, tables)

    finally:
        if tables_tmp_path.is_file():
            try:
                tables_tmp_path.unlink()
            except OSError:
                pass
        if out_tmp_path.is_file():
            try:
                out_tmp_path.unlink()
            except OSError:
                pass
