# PDFLayoutParser 公开 API 设计规格

## 概述

将 PDFLayoutParser 打包为 `.whl` 分发包，对外暴露一个 `PDFParser` 类，封装全部解析功能。外部调用者通过 `pip install` 安装后，使用 `from pdflayoutparser import PDFParser` 即可调用。

### 核心设计决策

1. **类封装**：所有功能通过 `PDFParser` 类的方法暴露，不提供独立函数。
2. **双构造方式**：接受 PDF 文件路径或已解析的 `Document` 对象。
3. **缓存机制**：`parse()` 结果缓存在实例中，重复调用直接返回。
4. **上下文管理器**：支持 `with` 语句，自动关闭底层 PDF 句柄。
5. **默认不写磁盘**：库 API 默认纯内存操作，仅 `extract_images`、`render_pages`、`extract_image_in_region`、`render_region` 因输出二进制文件而必须指定 `output_dir`。
6. **区域坐标归一化**：区域提取函数使用 0~1 归一化坐标（相对于页面尺寸）。

---

## 类设计：`PDFParser`

### 构造函数

```python
class PDFParser:
    def __init__(
        self,
        source: str | Document,
        *,
        render_dpi: int = 200,
        seal_coords: list[dict] | None = None,
        use_ml: bool = False,
        ml_model_path: str | None = None,
        ml_confidence: float = 0.25,
    ):
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | `str \| Document` | 必填 | PDF 文件路径，或已解析的 `Document` 对象 |
| `render_dpi` | `int` | `200` | 渲染 PNG 的分辨率 |
| `seal_coords` | `list[dict] \| None` | `None` | 印章坐标列表，格式：`[{"page_index": 0, "x0": ..., "y0": ..., "x1": ..., "y1": ...}]` |
| `use_ml` | `bool` | `False` | 是否启用 ML 模型辅助表格检测（需要 `pdflayoutparser[ml]`） |
| `ml_model_path` | `str \| None` | `None` | 自定义 ONNX 模型路径，`None` 使用内置模型 |
| `ml_confidence` | `float` | `0.25` | ML 模型置信度阈值 |

**构造行为：**
- `source` 为 `str`：记录路径，延迟加载（首次调用方法时才打开 PDF）。
- `source` 为 `Document`：缓存为已有解析结果，后续 `parse()` 直接返回。

### 上下文管理器

```python
def __enter__(self) -> PDFParser: ...
def __exit__(self, *exc) -> None: ...
```

`__exit__` 关闭内部持有的 `fitz.Document` 句柄（如果有）。

---

## 方法清单

### 1. `parse` — 完整解析

```python
def parse(
    self,
    *,
    page_indices: list[int] | None = None,
    output_dir: str | None = None,
) -> Document:
```

**行为：**
- 运行完整 pipeline（加载 → 文本提取 → 表格检测 → 图片提取 → 布局构建）。
- 结果缓存在 `self._document`，重复调用直接返回缓存。
- `output_dir=None`（默认）：不写磁盘，只返回 `Document`。
- `output_dir="./out"`：同时写 JSON、Markdown、图片、渲染 PNG 到指定目录（兼容现有 CLI 行为）。
- `page_indices`：只解析指定页（0-indexed），`None` 解析全部。

**返回：** `Document` 对象。

### 2. `extract_tables` — 提取表格

```python
def extract_tables(
    self,
    *,
    page_indices: list[int] | None = None,
) -> list[Table]:
```

**行为：**
- 若已有缓存的 `Document`，直接从 `doc.pages[i].tables` 返回。
- 若无缓存，内部加载 PDF 并仅运行表格检测阶段。
- `page_indices` 筛选页面。

**返回：** 所有页面的 `Table` 列表。

### 3. `extract_text` — 提取文本

```python
def extract_text(
    self,
    *,
    page_indices: list[int] | None = None,
) -> list[Block]:
```

**行为：**
- 若已有缓存的 `Document`，直接从 `doc.pages[i].blocks` 返回。
- 若无缓存，内部加载 PDF 并仅运行文本提取阶段。

**返回：** 所有页面的 `Block` 列表。

### 4. `extract_images` — 提取图片

```python
def extract_images(
    self,
    output_dir: str,
    *,
    page_indices: list[int] | None = None,
) -> list[Image]:
```

**行为：**
- 从 PDF 中提取嵌入的图片资源，写入 `output_dir`。
- `output_dir` 为必填参数（图片是二进制文件，必须写磁盘）。

**返回：** `Image` 列表，每个 `Image.path` 指向写入的文件。

### 5. `render_pages` — 渲染页面

```python
def render_pages(
    self,
    output_dir: str,
    *,
    dpi: int | None = None,
    page_indices: list[int] | None = None,
) -> list[RenderInfo]:
```

**行为：**
- 将 PDF 页面渲染为 PNG，写入 `output_dir`。
- `dpi` 默认使用构造时的 `render_dpi`。
- `output_dir` 为必填参数。

**返回：** `RenderInfo` 列表。

### 6. `to_json` — 转 JSON 字符串

```python
def to_json(
    self,
    document: Document | None = None,
) -> str:
```

**行为：**
- `document` 传入时，序列化该对象。
- `document=None` 时，自动调用 `self.parse()` 获取缓存的 Document。
- 纯内存操作，不写文件。

**返回：** JSON 字符串。

### 7. `to_markdown` — 转 Markdown 字符串

```python
def to_markdown(
    self,
    document: Document | None = None,
) -> str:
```

**行为：** 同 `to_json`，输出格式为 Markdown。

**返回：** Markdown 字符串。

---

## 区域提取方法

### 区域坐标格式

```python
region = {
    "page_index": 0,    # 页码（0-indexed）
    "x0": 0.1,          # 左边界，0~1，相对于页面宽度
    "y0": 0.2,          # 上边界，0~1，相对于页面高度
    "x1": 0.5,          # 右边界
    "y1": 0.8,          # 下边界
}
```

所有区域方法的 `region` 参数支持 `dict`（单区域）或 `list[dict]`（多区域）。

### 8. `extract_text_in_region` — 区域内文本提取

```python
def extract_text_in_region(
    self,
    region: dict | list[dict],
) -> list[Block]:
```

**行为：**
- 将归一化坐标转换为 PDF 点坐标。
- 提取该区域内的文本，返回被裁剪到区域边界内的 `Block` 列表。
- 多区域时，返回所有区域的 Block 合并列表。

**返回：** `list[Block]`。

### 9. `extract_table_in_region` — 区域内表格提取

```python
def extract_table_in_region(
    self,
    region: dict | list[dict],
) -> Table | list[Table] | None:
```

**行为：**
- 将指定区域当作一个表格来解析（运行表格检测逻辑）。
- 单区域返回 `Table | None`（无法识别为表格时返回 `None`）。
- 多区域返回 `list[Table]`（跳过无法识别的区域）。

**返回：** 单区域时 `Table | None`，多区域时 `list[Table]`。

### 10. `extract_image_in_region` — 区域内图片提取

```python
def extract_image_in_region(
    self,
    region: dict | list[dict],
    output_dir: str,
) -> Image | list[Image] | None:
```

**行为：**
- 提取指定区域内的图片资源，写入 `output_dir`。
- 单区域返回 `Image | None`，多区域返回 `list[Image]`。

**返回：** 单区域时 `Image | None`，多区域时 `list[Image]`。

### 11. `render_region` — 区域渲染

```python
def render_region(
    self,
    region: dict | list[dict],
    output_dir: str,
    dpi: int | None = None,
) -> RenderInfo | list[RenderInfo]:
```

**行为：**
- 将指定区域渲染为 PNG，写入 `output_dir`。
- `dpi` 默认使用构造时的 `render_dpi`。
- 单区域返回 `RenderInfo`，多区域返回 `list[RenderInfo]`。

**返回：** 单区域时 `RenderInfo`，多区域时 `list[RenderInfo]`。

---

## 导出定义

```python
# pdflayoutparser/__init__.py
from pdflayoutparser.pdf_parser import PDFParser
from pdflayoutparser.models import (
    Document, Page, Block, Line, Word, Char,
    Table, Cell, Image, Seal, RenderInfo,
    LayoutElement, BBox, Span,
)

__all__ = [
    "PDFParser",
    "Document", "Page", "Block", "Line", "Word", "Char",
    "Table", "Cell", "Image", "Seal", "RenderInfo",
    "LayoutElement", "BBox", "Span",
]
```

---

## 包配置

`pyproject.toml` 无需修改，现有配置已满足 `.whl` 构建需求：

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "pdflayoutparser"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["PyMuPDF>=1.23.0"]

[project.scripts]
pdflayoutparser = "pdflayoutparser.cli:main"
```

构建命令：`python -m build`，产物在 `dist/` 目录。

---

## 文件结构变更

```
src/pdflayoutparser/
    __init__.py          # 修改：导出 PDFParser + 所有数据模型
    pdf_parser.py        # 新增：PDFParser 类
    pipeline.py          # 现有：内部使用，不对外暴露
    models.py            # 现有：数据模型，对外暴露
    ...                  # 其余模块不变
```

`PDFParser` 内部复用现有模块（`Pipeline`、`TextExtractor`、`TableExtractor` 等），不重新实现逻辑。

---

## 使用示例

### 基础用法

```python
from pdflayoutparser import PDFParser

# 完整解析
with PDFParser("report.pdf") as parser:
    doc = parser.parse()
    print(f"共 {doc.page_count} 页")

    # 转 JSON 字符串
    json_str = parser.to_json()

    # 转 Markdown 字符串
    md_str = parser.to_markdown()
```

### 按需提取

```python
from pdflayoutparser import PDFParser

parser = PDFParser("report.pdf")

# 只要表格
tables = parser.extract_tables(page_indices=[0, 2])
for table in tables:
    print(f"表格 {table.rows}x{table.cols}")

# 只要文本
blocks = parser.extract_text(page_indices=[0])
```

### 区域提取

```python
from pdflayoutparser import PDFParser

parser = PDFParser("report.pdf")

# 提取某个区域的文本
region = {"page_index": 0, "x0": 0.05, "y0": 0.1, "x1": 0.95, "y1": 0.3}
blocks = parser.extract_text_in_region(region)

# 将某个区域当作表格解析
table_region = {"page_index": 0, "x0": 0.0, "y0": 0.4, "x1": 1.0, "y1": 0.8}
table = parser.extract_table_in_region(table_region)

# 多区域批量提取
regions = [
    {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5},
    {"page_index": 1, "x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0},
]
all_blocks = parser.extract_text_in_region(regions)
```

### 输出到文件

```python
from pdflayoutparser import PDFParser

with PDFParser("report.pdf") as parser:
    # 完整解析并写文件（兼容现有行为）
    doc = parser.parse(output_dir="./out")

    # 提取图片
    images = parser.extract_images("./out/images", page_indices=[0])

    # 渲染页面
    renders = parser.render_pages("./out/renders", dpi=150)

    # 区域渲染
    region = {"page_index": 0, "x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9}
    info = parser.render_region(region, "./out/crops")
```

---

## v1.0 不做

- 独立函数导出（只用类）
- 异步 API
- 流式解析（逐页回调）
- 自动 OCR
