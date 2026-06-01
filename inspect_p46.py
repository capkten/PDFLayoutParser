import fitz

doc = fitz.open("D:/codes/PDFLayoutParser/152590_20230428_N7ZK_0.pdf")
page = doc[45]  # 0-indexed, page 46

print("=== Page size ===")
print(f"Width: {page.rect.width}, Height: {page.rect.height}")

print("\n=== Text blocks with bbox ===")
data = page.get_text("dict")
for block in data["blocks"]:
    if block["type"] == 0:  # text
        print(f"\nBlock bbox=({block['bbox'][0]:.1f}, {block['bbox'][1]:.1f}, {block['bbox'][2]:.1f}, {block['bbox'][3]:.1f})")
        for line in block["lines"]:
            spans_text = []
            for span in line["spans"]:
                spans_text.append(span["text"])
            bbox = line["bbox"]
            line_text = " ".join(spans_text)
            print(f"  L ({bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f}): {line_text}")

print("\n=== Drawings (lines/rects) ===")
drawings = page.get_drawings()
for i, d in enumerate(drawings):
    for item in d["items"]:
        if item[0] == "l":  # line
            print(f"  draw[{i}] line: ({item[1].x:.1f},{item[1].y:.1f}) -> ({item[2].x:.1f},{item[2].y:.1f})")
        elif item[0] == "re":  # rect
            r = item[1]
            print(f"  draw[{i}] rect: ({r.x0:.1f},{r.y0:.1f},{r.x1:.1f},{r.y1:.1f}) w={r.width:.1f} h={r.height:.1f}")

print("\n=== Tables found by find_tables() ===")
tabs = page.find_tables()
for ti, tab in enumerate(tabs.tables):
    print(f"\nTable {ti}: bbox=({tab.bbox[0]:.1f},{tab.bbox[1]:.1f},{tab.bbox[2]:.1f},{tab.bbox[3]:.1f})")
    print(f"  Rows: {tab.row_count}, Cols: {tab.col_count}")
    for ri in range(tab.row_count):
        row_data = []
        for ci in range(tab.col_count):
            cell = tab.extract()[ri][ci]
            row_data.append(cell.strip() if cell else "")
        print(f"  Row {ri}: {row_data}")

doc.close()
