from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
import fitz


def compare_table_payloads(
    python_tables: Sequence[Mapping[str, Any]],
    rust_tables: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    mismatches: List[Dict[str, Any]] = []

    if len(python_tables) != len(rust_tables):
        mismatches.append({
            "field": "table_count",
            "python": len(python_tables),
            "rust": len(rust_tables),
        })
        return {"mismatch_count": len(mismatches), "mismatches": mismatches}

    for t_idx, (p_tab, r_tab) in enumerate(zip(python_tables, rust_tables)):
        for key in ["_page_index", "source", "rows", "cols", "confidence"]:
            if key in p_tab or key in r_tab:
                p_val = p_tab.get(key)
                r_val = r_tab.get(key)
                if p_val != r_val:
                    mismatches.append({
                        "field": f"tables[{t_idx}].{key}",
                        "python": p_val,
                        "rust": r_val,
                    })

        p_cells = p_tab.get("cells", [])
        r_cells = r_tab.get("cells", [])
        if len(p_cells) != len(r_cells):
            mismatches.append({
                "field": f"tables[{t_idx}].cells.count",
                "python": len(p_cells),
                "rust": len(r_cells),
            })
            continue

        for c_idx, (pc, rc) in enumerate(zip(p_cells, r_cells)):
            for ckey in ["text", "row_index", "col_index", "rowspan", "colspan"]:
                pv = pc.get(ckey)
                rv = rc.get(ckey)
                if pv != rv:
                    mismatches.append({
                        "field": f"tables[{t_idx}].cells[{c_idx}].{ckey}",
                        "python": pv,
                        "rust": rv,
                    })

    return {"mismatch_count": len(mismatches), "mismatches": mismatches}


def discover_pdfs(root_dir: Path | str) -> List[str]:
    root = Path(root_dir)
    results = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".pdf":
            rel = path.relative_to(root).as_posix()
            results.append(rel)
    results.sort()
    return results


def select_pdf_paths(available: Sequence[str], selected: Sequence[str]) -> List[str]:
    selected_set = set(selected)
    return [p for p in available if p in selected_set]


def configure_rust_modes(
    environment: Mapping[str, str],
    *,
    generic_mode: str = "python",
    personal_mode: str = "rust",
    path_modes: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    env = {k: v for k, v in environment.items() if not k.startswith("PDF_RUST_MODE")}
    env["PDF_RUST_MODE"] = generic_mode
    env["PDF_RUST_MODE_PERSONAL_CREDIT"] = personal_mode

    if path_modes:
        for stage, mode in path_modes.items():
            key = f"PDF_RUST_MODE_{stage.upper().replace('-', '_')}"
            env[key] = mode

    return env


def _child_environment(
    environment: Mapping[str, str],
    *,
    source_root: Path | str,
    task_mode: str = "rust",
    generic_mode: str = "python",
    path_modes: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    env = configure_rust_modes(
        environment,
        generic_mode=generic_mode,
        personal_mode=task_mode,
        path_modes=path_modes,
    )
    src_dir = str(Path(source_root) / "src")
    existing_pp = env.get("PYTHONPATH", "")
    if existing_pp:
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing_pp}"
    else:
        env["PYTHONPATH"] = src_dir
    return env


def render_table_overlays(
    pdf_path: Path | str,
    pages: Sequence[Mapping[str, Any]],
    output_dir: Path | str,
) -> List[str]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    generated_names = []

    try:
        for p_data in pages:
            page_idx = int(p_data.get("index", 0))
            if page_idx >= len(doc):
                continue
            page = doc[page_idx]

            # Draw tables & cells
            for table in p_data.get("tables", []):
                t_bbox = table.get("bbox", {})
                if isinstance(t_bbox, (list, tuple)) and len(t_bbox) >= 4:
                    t_rect = fitz.Rect(t_bbox[0], t_bbox[1], t_bbox[2], t_bbox[3])
                elif isinstance(t_bbox, dict):
                    t_rect = fitz.Rect(t_bbox["x0"], t_bbox["y0"], t_bbox["x1"], t_bbox["y1"])
                else:
                    t_rect = None

                if t_rect:
                    page.draw_rect(t_rect, color=(0.8, 0.1, 0.1), width=1.5, overlay=True)

                for cell in table.get("cells", []):
                    c_bbox = cell.get("bbox", {})
                    if isinstance(c_bbox, (list, tuple)) and len(c_bbox) >= 4:
                        c_rect = fitz.Rect(c_bbox[0], c_bbox[1], c_bbox[2], c_bbox[3])
                    elif isinstance(c_bbox, dict):
                        c_rect = fitz.Rect(c_bbox["x0"], c_bbox["y0"], c_bbox["x1"], c_bbox["y1"])
                    else:
                        c_rect = None

                    if c_rect:
                        page.draw_rect(
                            c_rect,
                            color=(0.1, 0.4, 0.8),
                            fill=(0.1, 0.4, 0.8),
                            fill_opacity=0.05,
                            width=0.8,
                            overlay=True,
                        )

            pix = page.get_pixmap(dpi=150)
            filename = f"page-{page_idx:03d}.png"
            pix.save(str(out_dir / filename))
            generated_names.append(filename)
    finally:
        doc.close()

    return generated_names
