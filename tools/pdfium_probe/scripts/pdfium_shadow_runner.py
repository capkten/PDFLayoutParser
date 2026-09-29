"""Explicit region shadow runner comparing PDFium and PyMuPDF extractions."""

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from behavioral_contract import (
    _IMAGE_OR_SEAL_RE,
    build_layout_signature,
    compare_behavior,
)
from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox, Cell, Document, Page, Table
from hexai_pdf_parser.extractors.layout_builder import LayoutBuilder
from hexai_pdf_parser.extractors.layout_mapper import LayoutMapper
from hexai_pdf_parser.extractors.page_classifier import classify_page_type
from hexai_pdf_parser.extractors.text_extractor import TextExtractor
from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot
from hexai_pdf_parser.writers.markdown_writer import MarkdownWriter
from pdfium_classification import classify_raw_page
from pdfium_normalizer import normalize_drawings, normalize_raw_page
from pdfium_page_adapter import PdfiumPageAdapter


def _make_table_signature(table: Any) -> Dict[str, Any]:
    rows = (
        getattr(table, "rows", 0)
        if not isinstance(table, Mapping)
        else table.get("rows", 0)
    )
    cols = (
        getattr(table, "cols", 0)
        if not isinstance(table, Mapping)
        else table.get("cols", 0)
    )
    cells_raw = (
        getattr(table, "cells", [])
        if not isinstance(table, Mapping)
        else table.get("cells", [])
    )
    clean_cells: List[Dict[str, Any]] = []
    for c in cells_raw:
        if isinstance(c, Mapping):
            r = c.get("row", c.get("row_index", 0))
            col = c.get("col", c.get("col_index", 0))
            rs = c.get("rowspan", 1)
            cs = c.get("colspan", 1)
            txt = c.get("text", "")
        else:
            r = getattr(c, "row_index", getattr(c, "row", 0))
            col = getattr(c, "col_index", getattr(c, "col", 0))
            rs = getattr(c, "rowspan", 1)
            cs = getattr(c, "colspan", 1)
            txt = getattr(c, "text", "")
        clean_cells.append(
            {
                "row": int(r),
                "col": int(col),
                "rowspan": int(rs),
                "colspan": int(cs),
                "text": str(txt),
            }
        )
    clean_cells.sort(key=lambda cell: (cell["row"], cell["col"]))
    return {
        "rows": int(rows),
        "cols": int(cols),
        "cells": clean_cells,
    }


def _extract_wired_table(
    dto: Dict[str, Any],
    region: Mapping[str, Any],
    is_pdfium: bool = False,
) -> Tuple[List[Table], List[Dict[str, Any]]]:
    """Collect lines intersecting region and extract wired table using rust_adapter."""
    rx0 = float(region.get("x0", 0.0))
    ry0 = float(region.get("y0", 0.0))
    rx1 = float(region.get("x1", 0.0))
    ry1 = float(region.get("y1", 0.0))
    tol = 2.3

    h_lines: List[Dict[str, Any]] = []
    v_lines: List[Dict[str, Any]] = []
    unsupported_evidence: List[Dict[str, Any]] = []

    drawings = dto.get("drawings") or []
    for d in drawings:
        if is_pdfium:
            path_type = d.get("path_type") or d.get("kind", "")
            if path_type == "unknown":
                unsupported_evidence.append(
                    {
                        "category": "unknown_path_type",
                        "drawing_order": d.get("source_order"),
                    }
                )
                continue

        lines = d.get("lines") or []
        for line in lines:
            l_r = line.get("rect") or {}
            if isinstance(l_r, (list, tuple)) and len(l_r) == 4:
                lx0, ly0, lx1, ly1 = float(l_r[0]), float(l_r[1]), float(l_r[2]), float(l_r[3])
            elif isinstance(l_r, Mapping):
                lx0 = float(l_r.get("x0", 0.0))
                ly0 = float(l_r.get("y0", 0.0))
                lx1 = float(l_r.get("x1", 0.0))
                ly1 = float(l_r.get("y1", 0.0))
            elif hasattr(l_r, "x0"):
                lx0, ly0, lx1, ly1 = float(l_r.x0), float(l_r.y0), float(l_r.x1), float(l_r.y1)
            else:
                continue

            # Check bounding box intersection with tolerance
            if lx1 < rx0 - 2.0 or lx0 > rx1 + 2.0 or ly1 < ry0 - 2.0 or ly0 > ry1 + 2.0:
                continue

            w = abs(lx1 - lx0)
            h = abs(ly1 - ly0)
            rect_dict = {
                "schema_version": 1,
                "x0": min(lx0, lx1),
                "y0": min(ly0, ly1),
                "x1": max(lx0, lx1),
                "y1": max(ly0, ly1),
            }
            line_dto = {
                "schema_version": 1,
                "rect": rect_dict,
                "width": float(line["width"]) if line.get("width") is not None else None,
                "color": float(line["color"]) if isinstance(line.get("color"), (int, float)) else None,
                "source_order": int(line.get("source_order", 0)),
            }

            if h <= tol and w >= 1.0:
                h_lines.append(line_dto)
            elif w <= tol and h >= 1.0:
                v_lines.append(line_dto)

    if is_pdfium and unsupported_evidence:
        return [], unsupported_evidence

    page_meta = dto.get("page") or {}
    page_dict = {
        "schema_version": 1,
        "width": float(page_meta.get("width", 0.0)),
        "height": float(page_meta.get("height", 0.0)),
        "rotation": int(page_meta.get("rotation", 0)),
    }

    input_data = {
        "schema_version": 1,
        "page": page_dict,
        "h_lines": h_lines,
        "v_lines": v_lines,
        "words": list(dto.get("words") or []),
        "tolerance": tol,
    }

    try:
        wired_out = rust_adapter.extract_wired_region(input_data)
    except Exception as exc:
        unsupported_evidence.append({"category": "extract_wired_region_error", "error": str(exc)})
        return [], unsupported_evidence

    diags = wired_out.get("diagnostics") or []
    if diags:
        unsupported_evidence.append({"category": "blocking_diagnostics", "diagnostics": diags})
        return [], unsupported_evidence

    grids = wired_out.get("grids") or []
    regions_out = wired_out.get("regions") or []
    cells_out = wired_out.get("cells") or []

    if not grids or not regions_out:
        unsupported_evidence.append({"category": "no_valid_grid", "reason": "empty grids or regions"})
        return [], unsupported_evidence

    tables: List[Table] = []
    for i, r in enumerate(regions_out):
        if i >= len(grids):
            break
        g = grids[i]
        rows = int(g.get("rows", 0))
        cols = int(g.get("cols", 0))
        if rows <= 0 or cols <= 0:
            unsupported_evidence.append(
                {"category": "no_valid_grid", "rows": rows, "cols": cols}
            )
            return [], unsupported_evidence

        r_rect = r.get("rect") or {}
        tx0 = float(r_rect.get("x0", rx0))
        ty0 = float(r_rect.get("y0", ry0))
        tx1 = float(r_rect.get("x1", rx1))
        ty1 = float(r_rect.get("y1", ry1))
        table_bbox = BBox(tx0, ty0, tx1, ty1)

        region_cells: List[Cell] = []
        for c in cells_out:
            c_r = c.get("rect") or {}
            cx0 = float(c_r.get("x0", 0.0))
            cy0 = float(c_r.get("y0", 0.0))
            cx1 = float(c_r.get("x1", 0.0))
            cy1 = float(c_r.get("y1", 0.0))

            if (
                cx0 >= table_bbox.x0 - 2.0
                and cx1 <= table_bbox.x1 + 2.0
                and cy0 >= table_bbox.y0 - 2.0
                and cy1 <= table_bbox.y1 + 2.0
            ):
                region_cells.append(
                    Cell(
                        text=str(c.get("text", "")),
                        row_index=int(c.get("row", 0)),
                        col_index=int(c.get("col", 0)),
                        bbox=BBox(cx0, cy0, cx1, cy1),
                        rowspan=int(c.get("rowspan", 1)),
                        colspan=int(c.get("colspan", 1)),
                    )
                )

        tables.append(
            Table(
                bbox=table_bbox,
                rows=rows,
                cols=cols,
                cells=region_cells,
                source="wired",
            )
        )

    return tables, unsupported_evidence


def run_shadow_page(
    *,
    pdfium_raw_page: Mapping[str, Any],
    pymupdf_page: Any,
    page_index: int,
    table_regions: Sequence[Mapping[str, Any]] = (),
    output_dir: Path,
) -> Dict[str, Any]:
    """Run shadow extraction comparison between PDFium and PyMuPDF."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    errors: List[str] = []
    diagnostics: Dict[str, Any] = {}

    # 1. Page classification
    pdfium_class = classify_raw_page(pdfium_raw_page)
    pdfium_type = str(pdfium_class.get("page_type", "scanned"))
    diagnostics["pdfium_classification"] = pdfium_class

    if pymupdf_page is None:
        pymupdf_type = pdfium_type
        pymupdf_reason = None
    else:
        try:
            pymupdf_type = str(classify_page_type(pymupdf_page))
        except Exception as exc:
            pymupdf_type = "unknown"
            errors.append(f"PyMuPDF classification failed: {exc}")
        pymupdf_reason = getattr(pymupdf_page, "classification_reason", None)

    diagnostics["page_classification"] = {
        "pdfium": pdfium_type,
        "pymupdf": pymupdf_type,
        "pymupdf_reason": pymupdf_reason,
    }

    if pdfium_type != pymupdf_type:
        diff = {
            "passed": False,
            "categories": ["page_classification"],
            "unclassified": [],
            "diagnostics": diagnostics["page_classification"],
        }
        (out_path / "pdfium.md").write_text("", encoding="utf-8")
        (out_path / "pymupdf.md").write_text("", encoding="utf-8")
        (out_path / "layout_signature.json").write_text(
            json.dumps({"pdfium": [], "pymupdf": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (out_path / "table_signature.json").write_text(
            json.dumps({"pdfium": [], "pymupdf": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (out_path / "diff.json").write_text(
            json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_path / "diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_path / "errors.json").write_text(
            json.dumps(["Page classification disagreement"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "status": "unsupported",
            "pdfium_page_type": pdfium_type,
            "pymupdf_page_type": pymupdf_type,
            "pdfium_markdown": "",
            "pymupdf_markdown": "",
            "tables": {"pdfium": [], "pymupdf": []},
            "diff": diff,
        }

    # 2. Both scanned
    if pdfium_type == "scanned" and pymupdf_type == "scanned":
        diff = compare_behavior(
            {"page_type": "scanned", "markdown": "", "tables": []},
            {"page_type": "scanned", "markdown": "", "tables": []},
        )
        (out_path / "pdfium.md").write_text("", encoding="utf-8")
        (out_path / "pymupdf.md").write_text("", encoding="utf-8")
        (out_path / "layout_signature.json").write_text(
            json.dumps({"pdfium": [], "pymupdf": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (out_path / "table_signature.json").write_text(
            json.dumps({"pdfium": [], "pymupdf": []}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (out_path / "diff.json").write_text(
            json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_path / "diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_path / "errors.json").write_text(
            json.dumps([], indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {
            "status": "compared",
            "pdfium_page_type": "scanned",
            "pymupdf_page_type": "scanned",
            "pdfium_markdown": "",
            "pymupdf_markdown": "",
            "tables": {"pdfium": [], "pymupdf": []},
            "diff": diff,
        }

    # 3. Both vector
    norm_pdfium = normalize_raw_page(pdfium_raw_page)
    pdfium_dto = norm_pdfium.page_snapshot or {}

    if isinstance(pymupdf_page, Mapping) and "schema_version" in pymupdf_page:
        py_dto = dict(pymupdf_page)
    else:
        py_snap = capture_page_snapshot(
            pymupdf_page, page_index=page_index, lightweight=False
        )
        py_dto = rust_adapter.page_snapshot_to_rust_input(py_snap)

    pdfium_digest = rust_adapter.page_snapshot_digest(pdfium_dto)
    py_digest = rust_adapter.page_snapshot_digest(py_dto)
    diagnostics["digests"] = {"pdfium": pdfium_digest, "pymupdf": py_digest}

    _ = rust_adapter.collect_native_spans_from_snapshot(pdfium_dto)
    _ = rust_adapter.collect_native_spans_from_snapshot(py_dto)

    # 4 & 5. Table recovery
    pdfium_tables: List[Table] = []
    py_tables: List[Table] = []
    unsupported_table_evidence: List[Dict[str, Any]] = []

    for reg in table_regions:
        kind = reg.get("kind", "wireless")
        rx0 = float(reg.get("x0", 0.0))
        ry0 = float(reg.get("y0", 0.0))
        rx1 = float(reg.get("x1", 0.0))
        ry1 = float(reg.get("y1", 0.0))
        region_bbox = BBox(rx0, ry0, rx1, ry1)

        if kind == "wireless":
            p_rows, p_cols, p_cells = rust_adapter.recover_cells_from_snapshot(
                pdfium_dto, reg
            )
            if p_rows > 0 and p_cols > 0 and p_cells:
                pdfium_tables.append(
                    Table(
                        bbox=region_bbox,
                        rows=p_rows,
                        cols=p_cols,
                        cells=p_cells,
                        source="wireless",
                    )
                )

            m_rows, m_cols, m_cells = rust_adapter.recover_cells_from_snapshot(
                py_dto, reg
            )
            if m_rows > 0 and m_cols > 0 and m_cells:
                py_tables.append(
                    Table(
                        bbox=region_bbox,
                        rows=m_rows,
                        cols=m_cols,
                        cells=m_cells,
                        source="wireless",
                    )
                )

        elif kind == "wired":
            p_tbls, p_unsupported = _extract_wired_table(pdfium_dto, reg, is_pdfium=True)
            if p_unsupported:
                unsupported_table_evidence.extend(p_unsupported)
            else:
                pdfium_tables.extend(p_tbls)

            m_tbls, m_unsupported = _extract_wired_table(py_dto, reg, is_pdfium=False)
            if m_unsupported:
                unsupported_table_evidence.extend(m_unsupported)
            else:
                py_tables.extend(m_tbls)

    # 6. Layout assembly & markdown generation
    pdfium_adapter = PdfiumPageAdapter(norm_pdfium)
    text_extractor = TextExtractor()
    layout_mapper = LayoutMapper()
    layout_builder = LayoutBuilder()
    markdown_writer = MarkdownWriter()

    # PDFium layout
    pdfium_blocks = text_extractor.extract_layout_blocks(pdfium_adapter, pdfium_tables)
    pdfium_mapped = layout_mapper.map_blocks(pdfium_blocks)
    pdfium_layout = layout_builder.build(pdfium_mapped, pdfium_tables, [])
    p_w = float(pdfium_dto.get("page", {}).get("width", 0.0))
    p_h = float(pdfium_dto.get("page", {}).get("height", 0.0))
    p_rot = int(pdfium_dto.get("page", {}).get("rotation", 0))
    pdfium_page_obj = Page(
        index=page_index,
        size={"width": p_w, "height": p_h},
        rotation=p_rot,
        tables=pdfium_tables,
        layout_elements=pdfium_layout,
        page_type="vector",
    )
    pdfium_doc = Document(file_name="pdfium.pdf", page_count=1, pages=[pdfium_page_obj])
    pdfium_markdown = markdown_writer.to_string(pdfium_doc)

    # PyMuPDF layout
    py_blocks = text_extractor.extract_layout_blocks(pymupdf_page, py_tables)
    py_mapped = layout_mapper.map_blocks(py_blocks)
    py_layout = layout_builder.build(py_mapped, py_tables, [])
    m_w = float(py_dto.get("page", {}).get("width", 0.0))
    m_h = float(py_dto.get("page", {}).get("height", 0.0))
    m_rot = int(py_dto.get("page", {}).get("rotation", 0))
    py_page_obj = Page(
        index=page_index,
        size={"width": m_w, "height": m_h},
        rotation=m_rot,
        tables=py_tables,
        layout_elements=py_layout,
        page_type="vector",
    )
    py_doc = Document(file_name="pymupdf.pdf", page_count=1, pages=[py_page_obj])
    pymupdf_markdown = markdown_writer.to_string(py_doc)

    # Check unmodeled image/seal in PyMuPDF
    has_unmodeled_image = False
    if hasattr(pymupdf_page, "get_images"):
        try:
            imgs = pymupdf_page.get_images()
            if imgs:
                has_unmodeled_image = True
        except Exception:
            pass
    if not has_unmodeled_image and _IMAGE_OR_SEAL_RE.search(pymupdf_markdown):
        has_unmodeled_image = True

    # 7. Signatures and behavioral comparison
    pdfium_layout_sig = build_layout_signature(pdfium_layout)
    py_layout_sig = build_layout_signature(py_layout)

    pdfium_table_sigs = [_make_table_signature(t) for t in pdfium_tables]
    py_table_sigs = [_make_table_signature(t) for t in py_tables]

    diff = compare_behavior(
        expected={
            "page_type": "vector",
            "markdown": pymupdf_markdown,
            "tables": py_table_sigs,
            "reading_order": py_layout_sig,
        },
        actual={
            "page_type": "vector",
            "markdown": pdfium_markdown,
            "tables": pdfium_table_sigs,
            "reading_order": pdfium_layout_sig,
        },
    )

    if has_unmodeled_image:
        if "unsupported_element_kind" not in diff["categories"]:
            diff["categories"].append("unsupported_element_kind")
        diff["passed"] = False
        diagnostics["unsupported_element_kind"] = "unmodeled image or seal present on page"

    if unsupported_table_evidence:
        diff["passed"] = False
        diagnostics["unsupported_table_evidence"] = unsupported_table_evidence

    status = (
        "unsupported"
        if (has_unmodeled_image or unsupported_table_evidence)
        else "compared"
    )

    # 8. Output artifacts
    (out_path / "pdfium.md").write_text(pdfium_markdown, encoding="utf-8")
    (out_path / "pymupdf.md").write_text(pymupdf_markdown, encoding="utf-8")
    (out_path / "layout_signature.json").write_text(
        json.dumps(
            {"pdfium": pdfium_layout_sig, "pymupdf": py_layout_sig},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (out_path / "table_signature.json").write_text(
        json.dumps(
            {"pdfium": pdfium_table_sigs, "pymupdf": py_table_sigs},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (out_path / "diff.json").write_text(
        json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_path / "diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_path / "errors.json").write_text(
        json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "status": status,
        "pdfium_page_type": pdfium_type,
        "pymupdf_page_type": pymupdf_type,
        "pdfium_markdown": pdfium_markdown,
        "pymupdf_markdown": pymupdf_markdown,
        "tables": {
            "pdfium": pdfium_tables,
            "pymupdf": py_tables,
        },
        "diff": diff,
    }
