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
    result = parser.to_json()
    if result.code == 1:
        print(result.data)
    else:
        print(result.message)
```

## Optional ML Table Detection

```bash
python -m hexai_pdf_parser.cli input.pdf -o out --ml
```

## Table Layout Rules

通过 JSON 配置文件定制表格提取行为：

```bash
python -m hexai_pdf_parser.cli input.pdf -o out --table-config config.json
```

配置文件示例：

```json
{
  "profiles": [
    {
      "name": "financial",
      "priority": 10,
      "matcher": {"required_keywords": ["资产负债表"]},
      "structure_rules": {"trim_trailing_summary": true}
    }
  ]
}
```

详见 `docs/algorithm.md` 第 6 节。

## Development

```bash
pip install -e ".[dev]"
pytest
```
