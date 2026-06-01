import fitz

doc = fitz.open("D:/codes/PDFLayoutParser/152590_20230428_N7ZK_0.pdf")
page = doc[45]  # page 46 (0-indexed)

# Try to extract text with xhtml to see all content
print("=== Full page text (xhtml) ===")
text = page.get_text("xhtml")
# Print just the text portions
import re
# Extract text between tags
lines = text.split("\n")
for line in lines:
    line = line.strip()
    if line and not line.startswith("<?xml") and not line.startswith("<") and not line.startswith("</"):
        print(line)

doc.close()
