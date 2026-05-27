# hexai_pdf_parser

PDF矢量文件解析器组件，将 PDF 解析为结构化 JSON、Markdown 和页面预览。

## Quick Start

```bash
pip install dist/hexai_pdf_parser-0.1.0-py3-none-any.whl
python -m hexai_pdf_parser.cli input.pdf -o out
```

## Python API

```python
from hexai_pdf_parser import PDFParser

with PDFParser("input.pdf") as parser:
    doc = parser.parse()
    json_str = parser.to_json()
```

## Optional ML Table Detection

```bash
python -m hexai_pdf_parser.cli input.pdf -o out --ml
```

## Development

```bash
pip install -e ".[dev]"
pytest
```
