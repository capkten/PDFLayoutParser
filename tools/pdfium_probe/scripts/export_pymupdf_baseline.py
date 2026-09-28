import json
import os
import glob
import pymupdf as fitz

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
                spans.append({
                    "order": order,
                    "text": text,
                    "bbox": [round(v, 4) for v in item["bbox"]],
                    "font": item.get("font"),
                    "size": round(item.get("size", 0.0), 4) if item.get("size") is not None else None,
                    "flags": item.get("flags"),
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

    return {
        "page_index": page_index,
        "width": round(rect.width, 4),
        "height": round(rect.height, 4),
        "rotation": rotation,
        "crop_box": [round(crop.x0, 4), round(crop.y0, 4), round(crop.x1, 4), round(crop.y1, 4)],
        "media_box": [round(media.x0, 4), round(media.y0, 4), round(media.x1, 4), round(media.y1, 4)],
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
        "page_count": len(pages_data),
        "pages": pages_data,
    }

    out_file = os.path.join(out_dir, f"{base_name}_pymupdf.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Exported baseline: {out_file}")

def export_real_samples(real_baseline_dir: str):
    os.makedirs(real_baseline_dir, exist_ok=True)
    real_targets = [
        ("d:/codes/PDFLayoutParser/test.pdf", 0, "test_p0_cover"),
        ("d:/codes/PDFLayoutParser/test.pdf", 1, "test_p1_toc"),
        ("d:/codes/PDFLayoutParser/test.pdf", 27, "test_p27_table"),
        ("d:/codes/PDFLayoutParser/征信解析样例.pdf", 0, "credit_p0_header"),
        ("d:/codes/PDFLayoutParser/征信解析样例.pdf", 1, "credit_p1_detail"),
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
    synthetic_dir = os.path.join(root, "test_data", "synthetic")
    baseline_dir = os.path.join(root, "test_data", "baseline")
    real_baseline_dir = os.path.join(root, "test_data", "real_baseline")
    os.makedirs(baseline_dir, exist_ok=True)

    pdf_files = glob.glob(os.path.join(synthetic_dir, "*.pdf"))
    for pdf in pdf_files:
        process_file(pdf, baseline_dir)

    export_real_samples(real_baseline_dir)

if __name__ == "__main__":
    main()
