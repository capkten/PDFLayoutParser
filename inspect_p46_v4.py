import fitz

doc = fitz.open("D:/codes/PDFLayoutParser/152590_20230428_N7ZK_0.pdf")
page = doc[45]  # page 46

# Render full page at 300 DPI for clarity
pix = page.get_pixmap(dpi=300)
pix.save("D:/codes/PDFLayoutParser/out_review/page46_full_300dpi.png")
print("Full page saved at 300 DPI")

# Also check: are there ANY drawings (lines, rects, curves) on this page?
drawings = page.get_drawings()
print(f"\nTotal drawings: {len(drawings)}")
for i, d in enumerate(drawings):
    items = d["items"]
    print(f"Drawing {i}: type={d.get('type','?')} items={len(items)} rect=({d['rect']})")
    for item in items:
        print(f"  item: {item}")

# Check for tables using find_tables
tables = page.find_tables()
print(f"\nfind_tables found: {len(tabs.tables) if (tabs := tables) else 0} tables")
if tabs.tables:
    for ti, tab in enumerate(tabs.tables):
        print(f"  Table {ti}: rows={tab.row_count} cols={tab.col_count} bbox={tab.bbox}")

doc.close()
