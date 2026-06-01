import fitz

doc = fitz.open("D:/codes/PDFLayoutParser/152590_20230428_N7ZK_0.pdf")
page = doc[45]  # page 46 (0-indexed)

# Render at 2x for clarity
pix = page.get_pixmap(dpi=200)
pix.save("D:/codes/PDFLayoutParser/out_review/page46_preview.png")
print("Saved page46_preview.png")

# Also try to get text with better encoding handling
print("\n=== Text with raw dict (checking fonts) ===")
data = page.get_text("rawdict")
for block in data["blocks"]:
    if block["type"] == 0:
        for line in block["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    print(f"  font={span['font']} size={span['size']:.1f} text='{span['text']}' bbox=({span['bbox'][0]:.1f},{span['bbox'][1]:.1f},{span['bbox'][2]:.1f},{span['bbox'][3]:.1f})")

doc.close()
