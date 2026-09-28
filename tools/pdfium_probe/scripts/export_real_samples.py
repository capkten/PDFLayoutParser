import json
import os
import pymupdf as fitz
from export_pymupdf_baseline import export_page_baseline

REAL_SAMPLES = [
    {"pdf": "d:/codes/PDFLayoutParser/test.pdf", "page": 0, "name": "test_p0_cover"},
    {"pdf": "d:/codes/PDFLayoutParser/test.pdf", "page": 1, "name": "test_p1_toc"},
    {"pdf": "d:/codes/PDFLayoutParser/test.pdf", "page": 27, "name": "test_p27_table"},
    {"pdf": "d:/codes/PDFLayoutParser/征信解析样例.pdf", "page": 0, "name": "credit_p0_header"},
]

def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(root, "test_data", "real_baseline")
    os.makedirs(out_dir, exist_ok=True)

    for item in REAL_SAMPLES:
        if not os.path.exists(item["pdf"]):
            print(f"Warning: {item['pdf']} does not exist")
            continue
        doc = fitz.open(item["pdf"])
        page = doc[item["page"]]
        data = export_page_baseline(page, item["page"])
        doc.close()

        result = {
            "generator": f"PyMuPDF_{fitz.__version__}",
            "source_file": os.path.basename(item["pdf"]),
            "sample_name": item["name"],
            "page_count": 1,
            "pages": [data],
        }
        out_file = os.path.join(out_dir, f"{item['name']}_pymupdf.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Exported real baseline: {out_file}")

if __name__ == "__main__":
    main()
