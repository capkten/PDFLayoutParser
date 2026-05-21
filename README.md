# PDFLayoutParser

PDFLayoutParser parses PDF documents into structured JSON, Markdown, and page previews.

## Quick Start

```bash
python -m pdflayoutparser.cli input.pdf -o out
```

## Optional ML Table Detection

The parser can use the bundled YOLO layout model to detect table regions first, then
recover table structure from the text blocks inside those regions.

Enable it with:

```bash
python -m pdflayoutparser.cli input.pdf -o out --ml
```

Optional flags:

```bash
python -m pdflayoutparser.cli input.pdf -o out --ml --ml-confidence 0.25
```

Notes:

- `--ml` uses the bundled `src/models/layoutanalysis/layoutanalysis.onnx` model by default.
- The ML path is for table-region detection only.
- Table structure is still built from text alignment inside each detected region.
- Line-based table extraction remains enabled and continues to handle tables with visible borders.

## Python API

```python
from pdflayoutparser import parse_pdf

document = parse_pdf("input.pdf", output_dir="out", use_ml=True)
```

## Development

Run tests with:

```bash
pytest
```
