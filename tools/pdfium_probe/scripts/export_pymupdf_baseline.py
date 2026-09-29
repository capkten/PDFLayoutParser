import glob
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import pymupdf as fitz


def compute_file_sha256(path: str) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def export_page_baseline(page: fitz.Page, page_index: int) -> dict:
    rect = page.rect
    crop = page.cropbox
    media = page.mediabox
    rotation = page.rotation

    # 1. 提取 rawdict (保留空白)
    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    spans = []
    order = 0
    for block_index, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            for span_index, item in enumerate(line.get("spans", [])):
                text = "".join(c.get("c", "") for c in item.get("chars", []))
                if not text:
                    continue
                chars = [
                    {"c": c.get("c", ""), "bbox": [round(v, 4) for v in c["bbox"]]}
                    for c in item.get("chars", [])
                    if c.get("c", "")
                ]
                flags = item.get("flags")
                is_invisible = bool(flags & 64) if flags is not None else False
                spans.append({
                    "order": order,
                    "text": text,
                    "bbox": [round(v, 4) for v in item["bbox"]],
                    "font": item.get("font"),
                    "size": round(item.get("size", 0.0), 4) if item.get("size") is not None else None,
                    "flags": flags,
                    "render_mode": None, # PyMuPDF rawdict has no native render_mode
                    "is_invisible": is_invisible,
                    "source_position": [block_index, line_index, span_index],
                    "characters": chars,
                })
                order += 1

    # 2. 提取 drawings
    drawings_raw = page.get_drawings()
    drawings = []
    for d_idx, d in enumerate(drawings_raw):
        items = []
        for it in d.get("items", []):
            cmd = it[0]
            pts = [[round(p.x, 4), round(p.y, 4)] for p in it[1:] if hasattr(p, "x")]
            items.append({"cmd": cmd, "points": pts})
        drawings.append({
            "drawing_index": d_idx,
            "rect": [round(v, 4) for v in d["rect"]],
            "width": round(d.get("width", 0.0), 4) if d.get("width") is not None else 1.0,
            "color": [round(c, 4) for c in d.get("color", [])] if d.get("color") else None,
            "fill": [round(c, 4) for c in d.get("fill", [])] if d.get("fill") else None,
            "items": items,
        })

    has_invisible_text = any(s.get("is_invisible", False) for s in spans)

    return {
        "page_index": page_index,
        "width": round(rect.width, 4),
        "height": round(rect.height, 4),
        "rotation": rotation,
        "crop_box": [round(crop.x0, 4), round(crop.y0, 4), round(crop.x1, 4), round(crop.y1, 4)],
        "media_box": [round(media.x0, 4), round(media.y0, 4), round(media.x1, 4), round(media.y1, 4)],
        "has_invisible_text": has_invisible_text,
        "spans": spans,
        "drawings": drawings,
    }

def process_file(pdf_path: str, out_dir: str):
    doc = fitz.open(pdf_path)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    pages_data = []
    for idx, page in enumerate(doc):
        pages_data.append(export_page_baseline(page, idx))
    doc.close()

    result = {
        "generator": f"PyMuPDF_{fitz.__version__}",
        "source_file": os.path.basename(pdf_path),
        "source_file_sha256": compute_file_sha256(pdf_path),
        "page_count": len(pages_data),
        "pages": pages_data,
    }

    out_file = os.path.join(out_dir, f"{base_name}_pymupdf.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Exported baseline: {out_file}")

def get_repo_root():
    if "REPO_ROOT" in os.environ:
        return os.environ["REPO_ROOT"]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    direct = os.path.abspath(os.path.join(root, "..", ".."))
    if os.path.exists(os.path.join(direct, "test.pdf")):
        return direct
    worktree_parent = os.path.abspath(os.path.join(direct, "..", ".."))
    if os.path.exists(os.path.join(worktree_parent, "test.pdf")):
        return worktree_parent
    return direct

def export_real_samples(real_baseline_dir: str):
    os.makedirs(real_baseline_dir, exist_ok=True)
    repo_root = get_repo_root()
    test_pdf = os.path.join(repo_root, "test.pdf")
    credit_pdf = os.path.join(repo_root, "征信解析样例.pdf")
    real_targets = [
        (test_pdf, 0, "test_p0_cover"),
        (test_pdf, 1, "test_p1_toc"),
        (test_pdf, 27, "test_p27_table"),
        (credit_pdf, 0, "credit_p0_header"),
        (credit_pdf, 1, "credit_p1_detail"),
    ]
    for pdf_path, p_idx, sname in real_targets:
        if not os.path.exists(pdf_path):
            continue
        doc = fitz.open(pdf_path)
        if p_idx < len(doc):
            page_data = export_page_baseline(doc[p_idx], p_idx)
            result = {
                "generator": f"PyMuPDF_{fitz.__version__}",
                "source_file": os.path.basename(pdf_path),
                "source_file_sha256": compute_file_sha256(pdf_path),
                "sample_name": sname,
                "page_count": 1,
                "pages": [page_data],
            }
            out_file = os.path.join(real_baseline_dir, f"{sname}_pymupdf.json")
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"Exported real baseline: {out_file}")
        doc.close()

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if "PDFIUM_OUTPUT_ROOT" in os.environ:
        out_root = os.environ["PDFIUM_OUTPUT_ROOT"]
        baseline_dir = os.path.join(out_root, "baseline")
        real_baseline_dir = os.path.join(out_root, "real_baseline")
    else:
        baseline_dir = os.path.join(root, "test_data", "baseline")
        real_baseline_dir = os.path.join(root, "test_data", "real_baseline")

    synthetic_dir = os.path.join(root, "test_data", "synthetic")
    os.makedirs(baseline_dir, exist_ok=True)
    os.makedirs(real_baseline_dir, exist_ok=True)

    pdf_files = glob.glob(os.path.join(synthetic_dir, "*.pdf"))
    for pdf in pdf_files:
        process_file(pdf, baseline_dir)

    export_real_samples(real_baseline_dir)

if __name__ == "__main__":
    main()
