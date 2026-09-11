# PDFLayoutParser 测试调用文档

本文档面向测试人员，说明当前项目的命令行调用、Python API 调用、输出文件和结果核对方式。

文档以当前源码为准，推荐测试入口如下：

- 命令行：`python -m hexai_pdf_parser.cli`。
- Python：`from hexai_pdf_parser import PDFParser`。
- 完整结果：优先核对 `output.json`、`output.md`、逐页 JSON 和可视化 PNG。

> 注意：页码索引从 `0` 开始；区域坐标使用相对于页面宽高的 `0~1` 归一化坐标。测试时请为每次运行使用新的输出目录，避免旧文件影响判断。

## 1. 安装 wheel

本项目的正常交付方式是先构建 wheel，再由测试或业务使用方安装 wheel。测试人员不需要把源码仓库作为运行前置条件，也不需要执行 `pip install -e .`。

### 1.1 运行环境

- Python `>=3.7`。
- 必需依赖：PyMuPDF（部分环境包名为 `PyMuPDF`，导入名为 `fitz`）。
- 使用 ML 表格检测时，安装项目的 `ml` 可选依赖：`onnxruntime`、`numpy`、`opencv-python`。
- 发布 wheel 应包含项目运行所需的代码和内置表格检测模型；只有需要替换模型时才需要通过 `--ml-model` 或 `ml_model_path` 指定自定义模型。

### 1.2 安装已构建 wheel

将发布包复制到测试机后，在 wheel 所在目录执行。将 `<version>` 替换为实际版本号：

```powershell
python -m pip install "dist/hexai_pdf_parser-<version>-py3-none-any.whl"
```

如果需要 ML 依赖：

```powershell
python -m pip install "dist/hexai_pdf_parser-<version>-py3-none-any.whl[ml]"
```

如果 wheel 不在 `dist` 目录，直接填写实际路径；例如 wheel 已复制到当前目录时：

```powershell
python -m pip install ".\hexai_pdf_parser-<version>-py3-none-any.whl"
```

安装或升级时建议使用：

```powershell
python -m pip install --upgrade --force-reinstall "dist/hexai_pdf_parser-<version>-py3-none-any.whl"
```

### 1.3 安装检查

```powershell
python -m pip show hexai_pdf_parser
python -c "import hexai_pdf_parser; print(hexai_pdf_parser.__file__)"
python -c "from hexai_pdf_parser import PDFParser; print('hexai_pdf_parser import ok')"
python -m hexai_pdf_parser.cli --help
```

检查重点：

- `pip show` 显示的版本和本次交付版本一致。
- `hexai_pdf_parser.__file__` 指向当前测试环境的 `site-packages`，而不是开发机源码目录。
- CLI 帮助中包含 `--pages`、`--ml-confidence`、`--debug-pipeline` 和 `--backend`。

### 1.4 版本替换和卸载

```powershell
python -m pip uninstall hexai_pdf_parser
```

如果测试多个 wheel 版本，建议每个版本使用独立虚拟环境；至少在升级前使用 `--force-reinstall`，避免旧版本文件残留。卸载操作只针对包本身，不会删除输入 PDF 或测试输出目录。

> 开发人员如需从源码联调，可以在源码仓库内使用 `python -m pip install -e .`；这不是测试人员安装交付包的标准流程。

## 2. 命令行调用

### 2.1 基本格式

位置参数形式：

```powershell
python -m hexai_pdf_parser.cli <input.pdf> --output <output_dir>
```

显式参数形式：

```powershell
python -m hexai_pdf_parser.cli --pdf_path <input.pdf> --output <output_dir>
```

安装 console script 后也可以使用：

```powershell
hexai_pdf_parser <input.pdf> --output <output_dir>
```

也支持：

```powershell
python -m hexai_pdf_parser <input.pdf> --output <output_dir>
```

建议始终指定独立的 `--output` 目录，不要使用默认的当前目录 `.`，因为默认目录可能会被写入 `output.json`、`output.md`、PNG 和其他结果文件。

### 2.2 CLI 参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `pdf_path_arg` | 无 | 输入 PDF 路径，位置参数形式。 |
| `--pdf_path` | 无 | 输入 PDF 路径；与位置参数二选一即可。 |
| `--output` / `-o` | `.` | 输出目录。建议每个测试用例使用新的目录。 |
| `--dpi` | `200` | 页面和调试图片的渲染 DPI。数值越高图片越清晰、文件越大。 |
| `--pages` | 全部页面 | 指定要处理的页面索引，支持一个或多个 0-based 整数，例如 `--pages 0 3 10`。 |
| `--ml-model` | `None` | 自定义 ONNX 表格检测模型路径。 |
| `--ml-confidence` | `0.40` | ML 表格检测置信度阈值。 |
| `--table-config` | `None` | 表格布局规则 JSON 文件路径。 |
| `--debug` | 关闭 | 导出文本对齐表格的调试叠加图；只有页面最终产生对应文本对齐结果时才会生成。 |
| `--debug-pipeline` | 关闭 | 导出每个表格提取阶段的调试 JSON 和 PNG。 |
| `--workers` / `-w` | 自动 | 并行处理页数。未指定时，多页任务最多自动使用 4 个 worker。 |
| `--backend` / `-b` | `thread` | 并行后端，可选 `thread`、`process`、`sequential`。 |

说明：`--pages` 是处理过滤条件，不代表重新编号。输出中的页面 `index` 仍然是原 PDF 的 0-based 页索引。

### 2.3 常用命令

#### 全量解析

```powershell
python -m hexai_pdf_parser.cli `
  "input.pdf" `
  --output "output/case_full"
```

成功时命令行会打印耗时统计和类似下面的结果：

```text
Success! Output written to: output/case_full
```

#### 只处理指定页面

```powershell
python -m hexai_pdf_parser.cli `
  "input.pdf" `
  --output "output/case_pages_000_005" `
  --pages 0 5 `
  --backend sequential
```

`sequential` 适合复现问题和单页调试；`--pages` 后面使用空格分隔页码，不使用逗号字符串。

#### 导出完整流水线调试结果

```powershell
python -m hexai_pdf_parser.cli `
  "input.pdf" `
  --output "output/case_pipeline_debug" `
  --debug-pipeline `
  --backend sequential
```

#### 导出文本对齐调试图

```powershell
python -m hexai_pdf_parser.cli `
  "input.pdf" `
  --output "output/case_text_alignment_debug" `
  --debug `
  --pages 0 1
```

#### 指定自定义模型和表格配置

```powershell
python -m hexai_pdf_parser.cli `
  "input.pdf" `
  --output "output/case_custom_config" `
  --ml-model "models/table_detector.onnx" `
  --ml-confidence 0.40 `
  --table-config "config/table_config.json"
```

### 2.4 `--debug` 与 `--debug-pipeline` 的区别

| 选项 | 适用场景 | 主要输出 |
|---|---|---|
| `--debug` | 重点分析文本对齐无线表格的行、列和文本归属 | `debug/text-alignment/page-NNN.png`（有对应结果时） |
| `--debug-pipeline` | 分析完整表格流水线：原始 drawing、线条、候选区域、单元格、文本对齐和最终表格 | `debug/pipeline/page-NNN/debug.json` 及多个阶段 PNG |

两者可以同时开启。测试表格边界、行列或单元格异常时，建议同时保留结构化 JSON 和对应 PNG。

## 3. 输出目录和文件

当 CLI 指定 `--output out`，或 Python API 调用 `parse(output_dir="out")` 时，典型目录如下：

```text
out/
├─ output.json                         # 全文档结构化 JSON
├─ output.md                           # 全文档 Markdown
├─ timings.json                        # 流水线耗时
├─ page-000.png                        # 页面渲染图
├─ images/                             # PDF 内嵌图片
│  └─ ...
├─ pages/                              # 逐页结构化输出
│  ├─ page-000.json
│  ├─ page-000.md
│  └─ ...
├─ tables/                             # 表格区域和单元格叠加图
│  ├─ page-000.png
│  └─ ...
└─ debug/                              # 仅在开启调试选项且有结果时生成
   ├─ pipeline/
   │  └─ page-000/
   │     ├─ debug.json
   │     ├─ 00-original.png
   │     ├─ 01-drawings.png
   │     ├─ 02-lines.png
   │     ├─ 03-regions.png
   │     ├─ 04-cells.png
   │     ├─ 05-text-alignment.png
   │     └─ 06-final-tables.png
   └─ text-alignment/
      └─ page-000.png
```

### 3.1 文件说明

- `output.json`：由 `Document` 序列化得到的全量结果，顶层包含 `document` 和 `pages`。
- `output.md`：按页面布局顺序生成的文本、表格、图片和印章 Markdown。
- `pages/page-NNN.json`：单页结果，适合定位某一页的问题。
- `pages/page-NNN.md`：单页 Markdown。扫描页不会保留普通文本 Markdown 内容。
- `page-NNN.png`：原页面渲染图，页面索引为 0-based，文件名补足 3 位。
- `tables/page-NNN.png`：在原页面上叠加表格和单元格边界的可视化图。
- `images/`：从 PDF 中提取的内嵌图片，不等同于页面截图。
- `timings.json`：包含总页数、总耗时、平均每页耗时、阶段耗时和每页耗时。
- `debug/pipeline/page-NNN/`：完整表格识别阶段的证据，包含 `debug.json` 和 7 个阶段图片。

### 3.2 `output.json` 顶层结构

```json
{
  "document": {
    "file_name": "input.pdf",
    "page_count": 1
  },
  "pages": [
    {
      "index": 0,
      "size": {"width": 595.0, "height": 842.0},
      "rotation": 0,
      "page_type": "vector",
      "blocks": [],
      "tables": [],
      "images": [],
      "seals": [],
      "render": {
        "path": ".../page-000.png",
        "width": 1653,
        "height": 2339,
        "dpi": 200
      },
      "layout_elements": []
    }
  ]
}
```

实际结果中的 `blocks`、`tables` 和 `layout_elements` 会根据页面内容填充。

### 3.3 表格字段

`pages/page-NNN.json` 或 `output.json` 中的每个表格包含：

```json
{
  "bbox": {"x0": 40.0, "y0": 100.0, "x1": 550.0, "y1": 300.0},
  "rows": 4,
  "cols": 5,
  "cells": [
    {
      "text": "项目",
      "row_index": 0,
      "col_index": 0,
      "bbox": {"x0": 40.0, "y0": 100.0, "x1": 140.0, "y1": 130.0},
      "rowspan": 1,
      "colspan": 1
    }
  ],
  "confidence": 0.9,
  "source": "line_projection"
}
```

重点字段：

- `rows`、`cols`：推断出的表格行数和列数。
- `cells`：单元格列表；空单元格也可能以 `text: ""` 返回。
- `row_index`、`col_index`：从 `0` 开始的网格位置。
- `rowspan`、`colspan`：跨行、跨列数量，默认值为 `1`。
- `bbox`：PDF 坐标系中的边界框，单位是 PDF point，不是 `0~1` 归一化坐标。
- `source`：检测来源示例包括 `line_projection`、`PyMuPDF.find_tables`、`text_alignment`、`wireless_span_recovery`、`hybrid_line_span_recovery` 等；它是结果来源标记，不应当当成固定枚举全集。

## 4. Python API 统一返回契约

除 `Pipeline.run()` 等底层直接调用外，`PDFParser` 公共方法统一返回 `ApiResult`：

```python
from dataclasses import dataclass

@dataclass
class ApiResult:
    code: int
    message: str
    data: object | None = None
```

| `code` | 含义 | 测试处理方式 |
|---:|---|---|
| `1` | 调用成功，并且有内容 | 继续核对 `data`。 |
| `0` | 调用完成，但没有内容 | 不是异常；核对输入页、区域和页面类型。 |
| `-1` | 调用过程中发生异常 | 记录 `message`、输入、命令和输出目录，作为失败信息。 |

推荐统一判断方式：

```python
result = parser.extract_tables(page_indices=[0])

if result.code == 1:
    tables = result.data
elif result.code == 0:
    print(f"调用成功但没有结果: {result.message}")
    tables = []
else:
    raise RuntimeError(result.message)
```

不要只判断 `result.data is not None`：空结果可能是正常的 `code == 0`，异常时 `data` 为 `None` 且 `code == -1`。

## 5. `PDFParser` Python API

### 5.1 导入和构造

```python
from hexai_pdf_parser import PDFParser

parser = PDFParser(
    "input.pdf",
    render_dpi=200,
    seal_coords=None,
    ml_model_path=None,
    ml_confidence=0.40,
    num_workers=None,
    backend="thread",
    debug_pipeline=False,
)
```

构造参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `source` | 必填 | PDF 文件路径，或已经存在的 `Document`。 |
| `render_dpi` | `200` | 页面和调试图默认渲染 DPI。 |
| `seal_coords` | `None` | 印章区域坐标列表，供完整流水线使用。 |
| `ml_model_path` | `None` | 自定义 ONNX 表格模型路径。 |
| `ml_confidence` | `0.40` | ML 表格检测阈值。 |
| `num_workers` | `None` | 并行 worker 数；`None` 时自动选择。 |
| `backend` | `"thread"` | `thread`、`process` 或 `sequential`。 |
| `debug_pipeline` | `False` | 是否导出完整表格流水线调试结果；需要同时传 `output_dir` 才会落盘。 |

推荐使用上下文管理器：

```python
from hexai_pdf_parser import PDFParser

with PDFParser("input.pdf") as parser:
    result = parser.parse(
        page_indices=[0],
        output_dir="output/python_full",
    )
    if result.code == -1:
        raise RuntimeError(result.message)
    document = result.data
```

`PDFParser` 也接受 `Document` 对象，但以下需要重新读取 PDF 文件或写页面文件的方法必须使用 PDF 路径：

- `extract_images`
- `render_pages`
- `extract_text_in_region`
- `extract_table_in_region`
- `extract_table_structure`
- `extract_image_in_region`
- `render_region`

### 5.2 `parse`：完整解析

```python
result = parser.parse(
    page_indices=None,       # None=全部页面；例如 [0, 3]
    output_dir=None,         # None=只返回内存对象，不写文件
)
```

- 返回：`ApiResult`，`data` 为 `Document`。
- 处理内容：页面加载、文本、表格、图片、布局和页面渲染。
- `output_dir` 不为 `None` 时写入第 3 节列出的文件。
- 解析结果会缓存；同一个 `PDFParser` 对象完成解析后重复调用 `parse()` 会复用已缓存文档。

最小示例：

```python
with PDFParser("input.pdf", backend="sequential") as parser:
    result = parser.parse(
        page_indices=[0, 1],
        output_dir="output/parse_pages_000_001",
    )
    if result.code == 1:
        print(f"页数: {result.data.page_count}")
```

### 5.3 `extract_text`：提取文本块

```python
result = parser.extract_text(page_indices=None)
```

- 返回：`ApiResult`，`data` 为 `list[Block]`。
- `Block` 包含 `text`、`bbox` 和 `lines`。
- `Line` 继续包含 `words`，`Word` 继续包含 `chars`。
- 只传 `page_indices=[N]` 时，返回指定页的文本块。

```python
result = parser.extract_text(page_indices=[1])
if result.code == 1:
    for block in result.data:
        print(block.text)
```

### 5.4 `extract_tables`：提取表格

```python
result = parser.extract_tables(page_indices=None)
```

- 返回：`ApiResult`，`data` 为跨页面汇总的 `list[Table]`。
- 该方法只执行表格检测相关阶段，不负责生成完整 Markdown。
- 适合快速核对表格数量、来源、行列数、bbox 和单元格内容。

```python
result = parser.extract_tables(page_indices=[12])
if result.code == 1:
    for table_index, table in enumerate(result.data, start=1):
        print(
            table_index,
            table.source,
            f"{table.rows}x{table.cols}",
            table.confidence,
        )
        for cell in sorted(table.cells, key=lambda item: (item.row_index, item.col_index)):
            print(cell.row_index, cell.col_index, repr(cell.text))
```

### 5.5 `extract_images`：提取 PDF 内嵌图片

```python
result = parser.extract_images(
    output_dir="output/images",
    page_indices=None,
)
```

- `output_dir` 必填，图片会写入磁盘。
- 返回：`ApiResult`，`data` 为 `list[Image]`。
- `Image` 主要包含 `bbox`、`page_index`、`resource_index`、`width`、`height`、`path` 和 `ext`。
- 该接口提取的是 PDF 内嵌图片资源，不是整页截图。
- 如果 `PDFParser` 是由 `Document` 构造的，会返回 `code == -1`，消息为需要 PDF 文件路径。

```python
result = parser.extract_images("output/extracted_images", page_indices=[0])
if result.code == 1:
    for image in result.data:
        print(image.page_index, image.width, image.height, image.path)
```

### 5.6 `render_pages`：渲染页面 PNG

```python
result = parser.render_pages(
    output_dir="output/renders",
    dpi=None,                 # None=使用构造函数中的 render_dpi
    page_indices=None,
)
```

- 返回：`ApiResult`，`data` 为 `list[RenderInfo]`。
- 输出文件名为 `page-NNN.png`。
- `RenderInfo` 包含 `path`、`width`、`height` 和 `dpi`。

```python
result = parser.render_pages(
    "output/renders_page_000",
    dpi=150,
    page_indices=[0],
)
if result.code == 1:
    print(result.data[0].path)
```

### 5.7 `to_json`：生成 JSON 字符串

```python
result = parser.to_json(document=None)
```

- 纯内存操作，不自动写文件。
- `document=None` 时自动调用 `parse()`；也可以传入已有 `Document`。
- 返回：`ApiResult`，`data` 为 JSON 字符串。

```python
import json

with PDFParser("input.pdf") as parser:
    result = parser.to_json()
    if result.code == 1:
        data = json.loads(result.data)
        print(data["document"]["page_count"])
```

如果需要直接写文件，推荐使用 `parse(output_dir=...)` 生成标准的 `output.json`，或自行将 `result.data` 写入指定位置。

### 5.8 `to_markdown`：生成 Markdown 字符串

```python
result = parser.to_markdown(document=None)
```

- 纯内存操作，不自动写文件。
- `document=None` 时自动调用 `parse()`。
- 返回：`ApiResult`，`data` 为 Markdown 字符串。

```python
with PDFParser("input.pdf") as parser:
    result = parser.to_markdown()
    if result.code == 1:
        print(result.data[:1000])
```

### 5.9 `extract_table_structure`：提取表格结构坐标

按页面提取：

```python
result = parser.extract_table_structure(page_indices=[0, 5])
```

按区域提取：

```python
result = parser.extract_table_structure(
    region={
        "page_index": 0,
        "x0": 0.05,
        "y0": 0.20,
        "x1": 0.95,
        "y1": 0.80,
    }
)
```

- 返回：`ApiResult`，`data` 为 `list[TableStructure]`。
- `TableStructure` 包含 `bbox`、`rows`、`cols`、`cells`、`confidence` 和 `source`。
- `CellStructure` 除 `text`、`row_index`、`col_index`、`bbox` 外，还包含：
  - `cell_coord`：单元格四角坐标列表，通常长度为 4；
  - `text_block`：字符级文本块，包含 `chars`；
  - `tl_row`、`tl_col`、`br_row`、`br_col`：考虑跨度后的网格覆盖范围。
- `region` 和 `page_indices` 二选一；传入 `region` 时按区域分支处理。

该接口适合需要检查单元格几何结构、合并范围和字符坐标的测试，不等同于 `extract_tables` 的普通 `Cell` 结果。

### 5.10 区域坐标格式

所有区域接口使用如下结构：

```python
region = {
    "page_index": 0,
    "x0": 0.10,
    "y0": 0.20,
    "x1": 0.90,
    "y1": 0.80,
}
```

字段含义：

- `page_index`：0-based 页面索引。
- `x0`、`x1`：页面宽度方向的相对位置。
- `y0`、`y1`：页面高度方向的相对位置。
- 通常要求 `0 <= x0 < x1 <= 1`、`0 <= y0 < y1 <= 1`。

也可以传入 `list[dict]` 批量处理多个页面或多个区域。

### 5.11 `extract_text_in_region`：区域文本

```python
result = parser.extract_text_in_region(region)
```

- 单区域或多区域都返回 `list[Block]`。
- 使用 PDF word-level 文本与区域相交关系提取内容。
- 没有匹配文字时返回 `code == 0`、`data == []`。

```python
result = parser.extract_text_in_region({
    "page_index": 0,
    "x0": 0.05, "y0": 0.05,
    "x1": 0.95, "y1": 0.20,
})
if result.code == 1:
    print("区域文本:", [block.text for block in result.data])
```

### 5.12 `extract_table_in_region`：区域表格

```python
result = parser.extract_table_in_region(region)
```

返回形态取决于输入：

| 输入 | `data` 类型 | 无结果时 |
|---|---|---|
| 单个 `dict` | `Table` | `None`，通常 `code == 0` |
| `list[dict]` | `list[Table]` | `[]`，通常 `code == 0` |

单区域示例：

```python
result = parser.extract_table_in_region({
    "page_index": 0,
    "x0": 0.0, "y0": 0.35,
    "x1": 1.0, "y1": 0.85,
})
if result.code == 1:
    print(result.data.rows, result.data.cols)
```

该接口会先运行表格提取，再筛选与指定区域相交的表格；区域不是表格时不应把 `code == 0` 当成程序异常。

### 5.13 `extract_image_in_region`：区域图片

```python
result = parser.extract_image_in_region(
    region,
    output_dir="output/region_images",
)
```

- 单区域：`data` 为 `Image` 或 `None`。
- 多区域：`data` 为 `list[Image]`。
- 图片文件会写入 `output_dir`。

### 5.14 `render_region`：区域渲染

```python
result = parser.render_region(
    region,
    output_dir="output/region_renders",
    dpi=200,
)
```

- 单区域：`data` 为 `RenderInfo`。
- 多区域：`data` 为 `list[RenderInfo]`。
- 多区域文件名形如 `region-000-000.png`，前一段是页面索引，后一段是本次区域序号。

## 6. 表格配置

### 6.1 CLI 配置

```powershell
python -m hexai_pdf_parser.cli `
  "input.pdf" `
  --output "output/config_case" `
  --table-config "config/table_config.json"
```

### 6.2 配置文件示例

```json
{
  "settings": {
    "line_tolerance": 2.0,
    "merge_group_tol": 0.3,
    "row_gap_threshold": 30.0,
    "fallback_max_cols": 30,
    "fallback_max_tables": 10,
    "separator_min_width": 200.0,
    "separator_max_height": 1.5
  },
  "profiles": [
    {
      "name": "financial",
      "priority": 10,
      "matcher": {
        "required_keywords": ["资产负债表"],
        "optional_keywords": [],
        "forbidden_keywords": [],
        "header_order": [],
        "max_header_distance": 200.0,
        "min_match_score": 0.5
      },
      "region_rules": {
        "expand_anchors": [],
        "stop_keywords": [],
        "min_row_window": 2,
        "merge_distance": 20.0,
        "enabled": true
      },
      "structure_rules": {
        "header_rows": 1,
        "main_columns": [],
        "trim_trailing_summary": true,
        "numeric_column_bias": false,
        "narrow_header_split": false,
        "enabled": true
      }
    }
  ]
}
```

规则说明：

- 顶层支持 `settings` 和 `profiles`；未知顶层字段会被忽略。
- 每个 profile 必须有非空字符串 `name`。
- `settings` 会覆盖表格检测的全局阈值；profile 用于按页面特征匹配并应用区域/结构规则。
- 配置 JSON 语法错误、profile 缺少 `name` 或字段类型不正确时，应记录完整错误信息。

### 6.3 Python 直接调用 `Pipeline`

测试人员通常使用 CLI 或 `PDFParser`。需要同时控制 `debug`、`debug_pipeline` 和 `table_config` 时，可以直接调用：

```python
from hexai_pdf_parser import Pipeline, TableConfig

config = TableConfig.load("config/table_config.json")
document = Pipeline(
    pdf_path="input.pdf",
    output_dir="output/pipeline_config_case",
    page_indices=[0],
    render_dpi=200,
    ml_confidence=0.40,
    debug=True,
    debug_pipeline=True,
    table_config=config,
    backend="sequential",
).run()

print(document.page_count)
```

`Pipeline.run()` 直接返回 `Document`，不会包装成 `ApiResult`。

## 7. 数据模型速查

| 模型 | 关键字段 | 测试用途 |
|---|---|---|
| `Document` | `file_name`、`page_count`、`pages` | 核对文件名、总页数和页面集合。 |
| `Page` | `index`、`size`、`rotation`、`page_type`、`blocks`、`tables`、`images`、`render`、`layout_elements` | 核对页面类型、提取数量和渲染结果。 |
| `Block` | `text`、`bbox`、`lines` | 核对普通文本块和边界框。 |
| `Line` | `text`、`bbox`、`words` | 核对文本行顺序。 |
| `Word` | `text`、`bbox`、`chars` | 核对词级坐标和拆分。 |
| `Char` | `text`、`bbox`、`font`、`size` | 核对字符级字体和坐标信息。 |
| `Table` | `bbox`、`rows`、`cols`、`cells`、`confidence`、`source` | 核对表格区域、结构和来源。 |
| `Cell` | `text`、`row_index`、`col_index`、`bbox`、`rowspan`、`colspan` | 核对单元格文本、位置和跨度。 |
| `TableStructure` | `bbox`、`rows`、`cols`、`cells`、`source` | 核对带几何结构的表格结果。 |
| `Image` | `bbox`、`page_index`、`width`、`height`、`path`、`ext` | 核对内嵌图片和保存路径。 |
| `RenderInfo` | `path`、`width`、`height`、`dpi` | 核对 PNG 是否生成及分辨率。 |
| `BBox` | `x0`、`y0`、`x1`、`y1` | 核对 PDF 坐标范围。 |

## 8. 测试执行和验收清单

### 8.1 基础执行

1. 确认输入 PDF 路径可读、页数和待测页面索引。
2. 为本次用例新建独立输出目录。
3. 先用 `--backend sequential` 跑目标页，便于复现；全量性能测试再使用默认 `thread` 或显式 worker 数。
4. 保存完整命令、输入 PDF、输出目录和运行时间。

示例：

```powershell
$out = "output/test_case_20260908"
python -m hexai_pdf_parser.cli `
  "input.pdf" `
  --output $out `
  --pages 0 1 `
  --backend sequential `
  --debug-pipeline
```

### 8.2 页面级检查

- 输入 PDF 总页数是否与 `output.json.document.page_count` 一致。
- `pages/` 是否包含本次指定页的逐页 JSON。
- 页面 JSON 的 `index` 是否为原始 0-based 索引。
- `page_type` 是否正确区分 `vector` 和 `scanned`。
- `page-NNN.png` 是否存在且能打开。
- `render.path`、`render.width`、`render.height`、`render.dpi` 是否与实际图片一致。
- 旋转页面的文本和表格坐标是否与渲染图方向一致。

### 8.3 表格级检查

- 表格数量是否符合人工预期。
- `source` 是否符合当前页面类型和表格形态。
- `bbox` 是否完整覆盖表格，且没有吸收页眉、标题或相邻表格。
- `rows`、`cols` 是否合理。
- 单元格是否按 `row_index`、`col_index` 排列。
- 文字是否落在正确单元格，尤其是首列短标签、金额列、百分比列和多级表头。
- `rowspan`、`colspan` 是否符合视觉结构。
- 结构中需要保留的空槽位是否存在 `text == ""` 的单元格。
- 同一网格槽位是否被多个跨度单元格重复占用。
- `tables/page-NNN.png` 中的大框、单元格框和文字位置是否与原图一致。

### 8.4 Markdown 和图片检查

- `output.md` 是否保留文本、表格和图片的页面顺序。
- 表格 Markdown 中的列数和跨列表头是否与 JSON 一致。
- 图片链接是否指向实际存在的文件。
- 需要视觉确认的异常，必须同时保存结构化 JSON 和对应 PNG，不能只看 Markdown。

### 8.5 性能检查

查看 `timings.json`：

```json
{
  "page_count": 10,
  "total_seconds": 12.3,
  "avg_seconds_per_page": 1.23,
  "stage_totals": {},
  "page_totals": [],
  "page_total_summary": {}
}
```

重点关注 `total_seconds`、`avg_seconds_per_page`、`stage_totals` 和异常慢页面。长任务需要等待进程实际结束，不能把一次 30 秒的终端等待超时直接判断为解析失败。

## 9. 扫描版页面行为

项目会识别页面类型：

- `vector`：进入普通文本、表格、图片和布局提取流程。
- `scanned`：保留页面信息并生成页面渲染图，但不进入普通提取阶段；对应页面的 `blocks`、`tables`、`images`、`seals`、`layout_elements` 通常为空。

当前项目不在 `PDFParser` 流程中自动提供 OCR。扫描页没有文本结果不代表调用异常；应结合 `page_type` 和渲染 PNG 判断。

## 10. 常见问题和排障

### 10.1 返回 `code == 0`

这表示调用正常结束但没有内容，常见原因：

- 页面索引没有命中实际页面。
- 指定区域内没有文字、表格或图片。
- 页面是扫描版，未提供 OCR 文本。
- PDF 本身没有对应类型的内容。

处理方式：先看 `message`、`page_type`、区域坐标和输入页的渲染图，不要直接当成代码异常。

### 10.2 返回 `code == -1`

这表示调用发生异常，常见原因：

- 输入 PDF 不存在、损坏或无权限读取。
- 自定义模型路径不存在或模型加载失败。
- 输出目录无写权限。
- 区域字典缺少 `page_index`、`x0`、`y0`、`x1` 或 `y1`。
- `PDFParser` 由 `Document` 构造，却调用了要求 PDF 路径的方法。

测试反馈中请完整保留 `result.message`，不要只记录“解析失败”。

### 10.3 没有生成预期文件

优先检查：

1. 是否真的传入了 `output_dir` 或 `--output`。
2. 输出目录是否复用了旧目录，导致旧文件或旧结果干扰判断。
3. 是否使用了正确的页码索引；CLI 和 Python API 都是 0-based。
4. 是否把 `extract_text`、`extract_tables` 等内存接口误认为会写文件。
5. 是否把 `--debug` 当成了完整流水线调试；完整阶段图需要 `--debug-pipeline`。

### 10.4 表格结果与图片不一致

同时核对：

- `pages/page-NNN.json` 中的 `bbox`、行列数和单元格列表；
- `tables/page-NNN.png` 的表格和单元格框；
- 原始 `page-NNN.png` 中的视觉边界；
- 如已开启 `--debug-pipeline`，再核对 `debug.json` 和 `06-final-tables.png`。

不要只通过 Markdown 文本判断表格边界，因为 Markdown 不保留全部几何信息。

## 11. 测试反馈模板

发现问题时建议按以下格式反馈：

```text
输入 PDF：
输入文件 SHA256（可选）：
执行命令：
页面索引（0-based）：
是否使用 --debug 或 --debug-pipeline：
输出目录：
预期结果：
实际结果：
涉及表格 source / rows x cols：
结构化 JSON 路径：
原始页面 PNG 路径：
表格叠加 PNG 路径：
错误信息或 result.message：
```

## 12. 相关文件

- 项目简介和最小示例：`README.md`
- 算法和表格配置说明：`docs/algorithm.md`
- 开发、单页运行和页面级验证规范：`DEVELOPMENT_WORKFLOW.md`
- 单页表格可视化脚本：`test_single.py`
