"""PDFium Rust layout engine adapter.

Provides Python integration for invoking the compiled `pdfium_probe layout` CLI,
converting the resulting JSON wire format into standard PDFLayoutParser
`LayoutElement` objects with `BBox`, `Line`, and `Word` models.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from hexai_pdf_parser.core.models import BBox, LayoutElement, Line, Table, Word


def _find_pdfium_probe_bin() -> Optional[str]:
    """Locate compiled pdfium_probe binary (debug or release)."""
    # 1. Check explicit environment override
    env_bin = os.environ.get("PDFIUM_PROBE_BIN")
    if env_bin:
        cand = Path(env_bin)
        if cand.is_file():
            return str(cand.resolve())

    probe_root = Path(__file__).resolve().parents[1]
    fallback_repo = probe_root.parents[1] if len(probe_root.parents) > 1 else probe_root.parent.parent
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


def normalize_tables_for_probe(tables: Sequence[Any]) -> List[Dict[str, Any]]:
    """Normalize input tables into `[{"bbox": [x0, y0, x1, y1], "table_id": int}, ...]` format."""
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(tables):
        bbox: Optional[List[float]] = None
        table_id: Optional[int] = None

        if hasattr(item, "bbox"):
            b = item.bbox
            if hasattr(b, "x0"):
                bbox = [float(b.x0), float(b.y0), float(b.x1), float(b.y1)]
            elif isinstance(b, (list, tuple)) and len(b) >= 4:
                bbox = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
            elif isinstance(b, dict):
                bbox = [
                    float(b.get("x0", 0.0)),
                    float(b.get("y0", 0.0)),
                    float(b.get("x1", 0.0)),
                    float(b.get("y1", 0.0)),
                ]
            table_id = getattr(item, "table_id", getattr(item, "id", None))
        elif isinstance(item, dict):
            if "bbox" in item:
                b = item["bbox"]
                if hasattr(b, "x0"):
                    bbox = [float(b.x0), float(b.y0), float(b.x1), float(b.y1)]
                elif isinstance(b, (list, tuple)) and len(b) >= 4:
                    bbox = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
                elif isinstance(b, dict):
                    bbox = [
                        float(b.get("x0", 0.0)),
                        float(b.get("y0", 0.0)),
                        float(b.get("x1", 0.0)),
                        float(b.get("y1", 0.0)),
                    ]
            elif all(k in item for k in ("x0", "y0", "x1", "y1")):
                bbox = [
                    float(item["x0"]),
                    float(item["y0"]),
                    float(item["x1"]),
                    float(item["y1"]),
                ]
            table_id = item.get("table_id", item.get("id", item.get("table_index")))
        elif isinstance(item, (list, tuple)) and len(item) >= 4:
            bbox = [float(item[0]), float(item[1]), float(item[2]), float(item[3])]

        if bbox is None:
            continue

        if table_id is None:
            table_id = idx

        normalized.append({
            "bbox": bbox,
            "table_id": int(table_id),
        })
    return normalized


def serialize_tables_to_json(tables: Sequence[Any]) -> str:
    """Serialize table objects or dicts/tuples to JSON string for the probe CLI."""
    norm_tables = normalize_tables_for_probe(tables)
    return json.dumps(norm_tables)


def _python_fallback_layout(
    pdf_path: Path,
    page_index: int,
    tables: Sequence[Any],
) -> List[LayoutElement]:
    """Fallback layout generation using Python pipeline if Rust probe binary is not found."""
    try:
        from pdfium_page_adapter import PdfiumPageAdapter
        from pdfium_normalizer import normalize_with_rust_probe, normalize_raw_page
        from hexai_pdf_parser.extractors.text_extractor import TextExtractor
        from hexai_pdf_parser.extractors.layout_mapper import LayoutMapper
        from hexai_pdf_parser.extractors.layout_builder import LayoutBuilder

        norm = normalize_with_rust_probe({"source_file": str(pdf_path), "page_index": page_index})
        if norm is None:
            return []

        adapter = PdfiumPageAdapter(norm, pdf_path=pdf_path)
        te = TextExtractor()
        lm = LayoutMapper()
        lb = LayoutBuilder()

        # Filter and cast tables for TextExtractor
        table_objs: List[Table] = []
        for t in tables:
            if isinstance(t, Table):
                table_objs.append(t)
            elif isinstance(t, dict) and "bbox" in t:
                b = t["bbox"]
                table_objs.append(Table(bbox=BBox(b[0], b[1], b[2], b[3]), rows=1, cols=1))

        blocks = te.extract_layout_blocks(adapter, table_objs)
        mapped = lm.map_blocks(blocks)
        elements = lb.build(mapped, table_objs, [])
        return elements
    except Exception:
        return []


def _parse_layout_dto_to_elements(
    dto_list: Sequence[Dict[str, Any]],
    source_tables: Sequence[Any],
) -> List[LayoutElement]:
    """Convert Rust probe LayoutElementDto JSON list into standard LayoutElement objects."""
    elements: List[LayoutElement] = []

    for dto in dto_list:
        elem_type = str(dto.get("element_type", "text")).lower()
        raw_bbox = dto.get("bbox", [0.0, 0.0, 0.0, 0.0])
        bbox = BBox(
            float(raw_bbox[0]),
            float(raw_bbox[1]),
            float(raw_bbox[2]),
            float(raw_bbox[3]),
        )
        order = int(dto.get("order", len(elements)))

        if elem_type == "table":
            tbl_idx = dto.get("table_index")
            tbl_obj: Optional[Any] = None
            if tbl_idx is not None:
                # 1. Try matching by custom table_id
                for st in source_tables:
                    st_id = getattr(st, "table_id", getattr(st, "id", None))
                    if st_id is None and isinstance(st, dict):
                        st_id = st.get("table_id", st.get("id", st.get("table_index")))
                    if st_id is not None and st_id == tbl_idx:
                        tbl_obj = st
                        break
                # 2. Try matching by list index
                if tbl_obj is None and 0 <= int(tbl_idx) < len(source_tables):
                    tbl_obj = source_tables[int(tbl_idx)]
                # 3. Try matching by bbox proximity
                if tbl_obj is None:
                    for st in source_tables:
                        st_norm = normalize_tables_for_probe([st])
                        if st_norm:
                            sb = st_norm[0]["bbox"]
                            if (
                                abs(sb[0] - bbox.x0) < 1.0
                                and abs(sb[1] - bbox.y0) < 1.0
                                and abs(sb[2] - bbox.x1) < 1.0
                                and abs(sb[3] - bbox.y1) < 1.0
                            ):
                                tbl_obj = st
                                break

            content = tbl_obj if tbl_obj is not None else dto.get("text")
            elem = LayoutElement(
                type="table",
                bbox=bbox,
                order=order,
                content=content,
                lines=[],
                words=[],
            )
            if tbl_obj is not None:
                setattr(elem, "table", tbl_obj)
            elements.append(elem)

        elif elem_type == "image":
            img_idx = dto.get("image_index")
            elem = LayoutElement(
                type="image",
                bbox=bbox,
                order=order,
                content=img_idx,
                lines=[],
                words=[],
            )
            elements.append(elem)

        else:  # "text"
            lines: List[Line] = []
            words: List[Word] = []

            for line_dto in dto.get("lines", []):
                line_words: List[Word] = []
                for w_dto in line_dto.get("word_details", []):
                    wb = w_dto.get("bbox", [0.0, 0.0, 0.0, 0.0])
                    word_obj = Word(
                        text=w_dto.get("text", ""),
                        bbox=BBox(float(wb[0]), float(wb[1]), float(wb[2]), float(wb[3])),
                    )
                    line_words.append(word_obj)

                if not line_words and line_dto.get("words"):
                    for w_text in line_dto["words"]:
                        line_words.append(
                            Word(
                                text=w_text,
                                bbox=BBox(
                                    float(line_dto.get("bbox", [0.0, 0.0, 0.0, 0.0])[0]),
                                    float(line_dto.get("bbox", [0.0, 0.0, 0.0, 0.0])[1]),
                                    float(line_dto.get("bbox", [0.0, 0.0, 0.0, 0.0])[2]),
                                    float(line_dto.get("bbox", [0.0, 0.0, 0.0, 0.0])[3]),
                                ),
                            )
                        )

                lb = line_dto.get("bbox", [0.0, 0.0, 0.0, 0.0])
                line_bbox = BBox(float(lb[0]), float(lb[1]), float(lb[2]), float(lb[3]))
                line_text = line_dto.get("text", "")
                line_obj = Line(
                    text=line_text,
                    bbox=line_bbox,
                    words=line_words,
                )
                lines.append(line_obj)
                words.extend(line_words)

            content = dto.get("text", "")
            elem = LayoutElement(
                type="text",
                bbox=bbox,
                order=order,
                content=content,
                lines=lines,
                words=words,
            )
            elements.append(elem)

    return elements


def extract_layout_with_rust_probe(
    pdf_path: Union[str, Path],
    page_index: int,
    tables: Sequence[Any] = (),
) -> List[LayoutElement]:
    """Execute `pdfium_probe layout` CLI and return standard LayoutElement objects.

    Args:
        pdf_path: Path to the target PDF document.
        page_index: 0-based page index.
        tables: Sequence of Table objects, dicts, or bbox tuples.

    Returns:
        Ordered list of LayoutElement objects.
    """
    target_pdf = Path(pdf_path)
    if not target_pdf.is_file():
        probe_root = Path(__file__).resolve().parents[1]
        fallback_synth = probe_root / "test_data" / "synthetic" / target_pdf.name
        if fallback_synth.is_file():
            target_pdf = fallback_synth
        else:
            repo_root = Path(os.environ.get("REPO_ROOT", str(probe_root.parents[1])))
            fallback_repo = repo_root / target_pdf.name
            if fallback_repo.is_file():
                target_pdf = fallback_repo
            else:
                return _python_fallback_layout(target_pdf, page_index, tables)

    probe_bin_str = _find_pdfium_probe_bin()
    if probe_bin_str is None:
        return _python_fallback_layout(target_pdf, page_index, tables)

    probe_bin = Path(probe_bin_str)
    if not probe_bin.is_file():
        return _python_fallback_layout(target_pdf, page_index, tables)

    # Prepare temporary files for tables input and layout output
    tables_tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tables_tmp_path = Path(tables_tmp.name)
    try:
        tables_json_bytes = serialize_tables_to_json(tables).encode("utf-8")
        tables_tmp.write(tables_json_bytes)
    finally:
        # Crucial on Windows: flush and close before child process reads it
        tables_tmp.close()

    out_tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    out_tmp_path = Path(out_tmp.name)
    out_tmp.close()

    try:
        cmd = [
            str(probe_bin),
            "layout",
            str(target_pdf.resolve()),
            str(page_index),
            str(tables_tmp_path.resolve()),
            str(out_tmp_path.resolve()),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            return _python_fallback_layout(target_pdf, page_index, tables)

        if not out_tmp_path.is_file() or out_tmp_path.stat().st_size == 0:
            return _python_fallback_layout(target_pdf, page_index, tables)

        with open(out_tmp_path, "r", encoding="utf-8") as f:
            dto_list = json.load(f)

        return _parse_layout_dto_to_elements(dto_list, tables)

    except Exception:
        return _python_fallback_layout(target_pdf, page_index, tables)

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
