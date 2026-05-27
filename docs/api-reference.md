# PDFParser API 调用文档

## 安装

```bash
pip install dist/hexai_pdf_parser-0.1.0-py3-none-any.whl
```

## 快速开始

```python
from hexai_pdf_parser import PDFParser

# 最简用法：解析 PDF，获取 Document 对象
with PDFParser("report.pdf") as parser:
    doc = parser.parse()
    print(f"共 {doc.page_count} 页")
```

---

## 构造函数

```python
PDFParser(
    source,                        # str: PDF 文件路径，或 Document: 已解析的对象
    *,
    render_dpi=200,                # int: 渲染 PNG 的分辨率
    seal_coords=None,              # list[dict]: 印章坐标（可选）
    use_ml=False,                  # bool: 启用 ML 表格检测
    ml_model_path=None,            # str: 自定义 ONNX 模型路径
    ml_confidence=0.25,            # float: ML 置信度阈值
)
```

**两种构造方式：**

```python
# 方式一：从文件路径
parser = PDFParser("report.pdf")

# 方式二：从已解析的 Document
doc = parser.parse()
parser2 = PDFParser(doc)
```

**支持 `with` 语句：**

```python
with PDFParser("report.pdf") as parser:
    doc = parser.parse()
```

---

## 方法一览

### parse — 完整解析

运行完整 pipeline（文本提取 + 表格检测 + 图片提取 + 布局构建），返回 `Document` 对象。结果会缓存，重复调用直接返回。

```python
def parse(
    *,
    page_indices: list[int] | None = None,  # 只解析指定页（0-indexed），None=全部
    output_dir: str | None = None,           # 输出目录，None=不写磁盘
) -> Document
```

**示例：**

```python
parser = PDFParser("report.pdf")

# 纯内存，不写文件
doc = parser.parse()

# 同时输出文件（JSON、Markdown、图片、渲染 PNG）
doc = parser.parse(output_dir="./out")

# 只解析前两页
doc = parser.parse(page_indices=[0, 1])
```

---

### extract_text — 提取文本

只运行文本提取阶段，返回 `Block` 列表。若已有缓存的 Document，直接从缓存返回。

```python
def extract_text(
    *,
    page_indices: list[int] | None = None,
) -> list[Block]
```

**示例：**

```python
parser = PDFParser("report.pdf")

# 提取所有页的文本
blocks = parser.extract_text()
for block in blocks:
    print(block.text)

# 只提取第 2 页
blocks = parser.extract_text(page_indices=[1])
```

**Block 结构：**
- `block.text` — 整个文本块的文本
- `block.bbox` — 边界框（`BBox(x0, y0, x1, y1)`）
- `block.lines` — `Line` 列表，每个 Line 包含 `words`，每个 Word 包含 `chars`

---

### extract_tables — 提取表格

只运行表格检测阶段，返回 `Table` 列表。

```python
def extract_tables(
    *,
    page_indices: list[int] | None = None,
) -> list[Table]
```

**示例：**

```python
parser = PDFParser("report.pdf")
tables = parser.extract_tables()
for table in tables:
    print(f"表格: {table.rows}行 x {table.cols}列")
    for cell in table.cells:
        print(f"  [{cell.row_index},{cell.col_index}] = {cell.text}")
```

**Table 结构：**
- `table.rows` / `table.cols` — 行列数
- `table.cells` — `Cell` 列表
- `table.bbox` — 表格边界框
- `table.source` — 检测来源（`"line_projection"` / `"pymupdf"` / `"text_alignment"` 等）
- `cell.text` / `cell.row_index` / `cell.col_index` / `cell.rowspan` / `cell.colspan`

---

### extract_images — 提取图片

从 PDF 中提取嵌入的图片资源，**写入磁盘**。

```python
def extract_images(
    output_dir: str,                       # 图片保存目录（必填）
    *,
    page_indices: list[int] | None = None,
) -> list[Image]
```

**示例：**

```python
parser = PDFParser("report.pdf")
images = parser.extract_images("./images")
for img in images:
    print(f"图片: {img.width}x{img.height}, 保存到 {img.path}")
```

---

### render_pages — 渲染页面

将 PDF 页面渲染为 PNG 图片，**写入磁盘**。

```python
def render_pages(
    output_dir: str,                       # PNG 保存目录（必填）
    *,
    dpi: int | None = None,                # 渲染 DPI，默认用构造时的 render_dpi
    page_indices: list[int] | None = None,
) -> list[RenderInfo]
```

**示例：**

```python
parser = PDFParser("report.pdf", render_dpi=200)

# 使用默认 DPI
renders = parser.render_pages("./renders")

# 指定 DPI
renders = parser.render_pages("./renders", dpi=150)
```

---

### to_json — 转 JSON 字符串

将 Document 序列化为 JSON 字符串，**纯内存操作**，不写文件。

```python
def to_json(
    document: Document | None = None,  # None 时自动调用 parse()
) -> str
```

**示例：**

```python
parser = PDFParser("report.pdf")

# 自动解析 + 转 JSON
json_str = parser.to_json()

# 已有 Document 时直接传入
doc = parser.parse()
json_str = parser.to_json(doc)

# 可以直接存数据库、发 HTTP 响应等
import json
data = json.loads(json_str)
```

---

### to_markdown — 转 Markdown 字符串

将 Document 序列化为 Markdown 字符串，**纯内存操作**。

```python
def to_markdown(
    document: Document | None = None,  # None 时自动调用 parse()
) -> str
```

**示例：**

```python
parser = PDFParser("report.pdf")
md_str = parser.to_markdown()
print(md_str)
```

---

## 区域提取方法

所有区域方法使用 **0~1 归一化坐标**（相对于页面尺寸）：

```python
region = {
    "page_index": 0,    # 页码（0-indexed）
    "x0": 0.1,          # 左边界：页面宽度的 10%
    "y0": 0.2,          # 上边界：页面高度的 20%
    "x1": 0.5,          # 右边界：页面宽度的 50%
    "y1": 0.8,          # 下边界：页面高度的 80%
}
```

支持单区域（`dict`）和多区域（`list[dict]`）。

---

### extract_text_in_region — 区域内文本提取

提取与指定区域相交的文本块。

```python
def extract_text_in_region(
    region: dict | list[dict],
) -> list[Block]
```

**示例：**

```python
parser = PDFParser("report.pdf")

# 单区域
region = {"page_index": 0, "x0": 0.05, "y0": 0.1, "x1": 0.95, "y1": 0.3}
blocks = parser.extract_text_in_region(region)

# 多区域
regions = [
    {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5},
    {"page_index": 1, "x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0},
]
blocks = parser.extract_text_in_region(regions)
```

---

### extract_table_in_region — 区域内表格提取

将指定区域当作表格来解析。单区域返回 `Table | None`，多区域返回 `list[Table]`。

```python
def extract_table_in_region(
    region: dict | list[dict],
) -> Table | list[Table] | None
```

**示例：**

```python
parser = PDFParser("report.pdf")

# 单区域
region = {"page_index": 0, "x0": 0.0, "y0": 0.4, "x1": 1.0, "y1": 0.8}
table = parser.extract_table_in_region(region)
if table:
    print(f"检测到 {table.rows}x{table.cols} 表格")
else:
    print("该区域未检测到表格")
```

---

### extract_image_in_region — 区域内图片提取

提取与指定区域相交的图片。单区域返回 `Image | None`，多区域返回 `list[Image]`。

```python
def extract_image_in_region(
    region: dict | list[dict],
    output_dir: str,                   # 图片保存目录（必填）
) -> Image | list[Image] | None
```

**示例：**

```python
parser = PDFParser("report.pdf")
region = {"page_index": 0, "x0": 0.2, "y0": 0.3, "x1": 0.8, "y1": 0.7}
img = parser.extract_image_in_region(region, "./images")
```

---

### render_region — 区域渲染

将指定区域渲染为 PNG。单区域返回 `RenderInfo`，多区域返回 `list[RenderInfo]`。

```python
def render_region(
    region: dict | list[dict],
    output_dir: str,                   # PNG 保存目录（必填）
    dpi: int | None = None,            # 渲染 DPI，默认用构造时的 render_dpi
) -> RenderInfo | list[RenderInfo]
```

**示例：**

```python
parser = PDFParser("report.pdf", render_dpi=200)

# 裁剪页面左上角 50% 区域
region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
info = parser.render_region(region, "./crops")
print(f"裁剪图: {info.width}x{info.height}, 保存到 {info.path}")
```

---

## 数据模型

所有模型通过 `from hexai_pdf_parser import ...` 导入：

| 模型 | 说明 |
|------|------|
| `Document` | 顶层容器，含 `file_name`、`page_count`、`pages` |
| `Page` | 单页，含 `index`、`size`、`blocks`、`tables`、`images`、`layout_elements` |
| `Block` | 文本块，含 `text`、`bbox`、`lines` |
| `Line` | 文本行，含 `text`、`bbox`、`words` |
| `Word` | 词，含 `text`、`bbox`、`chars` |
| `Char` | 字符，含 `text`、`bbox`、`font`、`size` |
| `Table` | 表格，含 `rows`、`cols`、`cells`、`bbox`、`source` |
| `Cell` | 单元格，含 `text`、`row_index`、`col_index`、`rowspan`、`colspan` |
| `Image` | 图片，含 `bbox`、`width`、`height`、`path` |
| `RenderInfo` | 渲染信息，含 `path`、`width`、`height`、`dpi` |
| `BBox` | 边界框，含 `x0`、`y0`、`x1`、`y1` |
| `LayoutElement` | 统一布局元素，含 `type`、`bbox`、`order`、`content` |
| `Span` | 样式文本段，含 `text`、`bbox`、`font`、`size` |

---

## 完整用例

```python
from hexai_pdf_parser import PDFParser

with PDFParser("financial_report.pdf") as parser:
    # 1. 完整解析
    doc = parser.parse()

    # 2. 导出为 JSON 字符串
    json_str = parser.to_json()

    # 3. 导出为 Markdown
    md_str = parser.to_markdown()

    # 4. 只提取表格
    tables = parser.extract_tables(page_indices=[0])

    # 5. 提取指定区域的文本
    header = parser.extract_text_in_region({
        "page_index": 0,
        "x0": 0.0, "y0": 0.0,
        "x1": 1.0, "y1": 0.15,
    })

    # 6. 将页面中间区域当作表格解析
    table = parser.extract_table_in_region({
        "page_index": 0,
        "x0": 0.0, "y0": 0.3,
        "x1": 1.0, "y1": 0.8,
    })

    # 7. 裁剪并渲染页面局部
    parser.render_region(
        {"page_index": 0, "x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9},
        "./output/crops",
    )

    # 8. 完整解析并输出所有文件
    parser.parse(output_dir="./output/full")
```
