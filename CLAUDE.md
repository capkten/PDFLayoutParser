# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 提供本仓库的开发指引。

## 项目概述

PDFLayoutParser 是一个 Python 库，用于将矢量 PDF 解析为结构化的 JSON 和 Markdown。它提取文本层级结构（block → line → word → char），检测表格，提取内嵌图片，渲染页面预览图，并支持基于给定坐标的印章提取。项目以 PyMuPDF (`fitz`) 作为主要引擎，不进行 OCR 或图像语义识别。

## 开发命令

```bash
# 以可编辑模式安装，包含开发依赖
pip install -e ".[dev]"

# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/test_table_extractor.py

# 以详细模式运行测试
pytest -v

# 运行 CLI
python -m pdflayoutparser.cli <pdf路径> -o <输出目录> --dpi 200

# 或使用安装后的入口命令（pip install 后）
pdflayoutparser <pdf路径> -o <输出目录> --dpi 200
```

## 架构

代码采用流水线（pipeline）架构，每个模块职责单一。`Pipeline` 类（位于 `src/pdflayoutparser/pipeline.py`）负责编排完整的逐页处理流程。

### 处理流程

1. `loader`：打开 PDF，构建包含每页元数据（尺寸、旋转角度）的 `Document`。
2. `text_extractor`：使用 `get_text("dict")` 并配合 `TEXT_PRESERVE_WHITESPACE` 标志，从每页提取文本层级，产出 `Block` → `Line` → `Word` → `Char`。当 PyMuPDF 无法提供单字符数据时，根据 span 宽度合成等距的 `Char` 对象。
3. `layout_mapper`：将原始 `Block` 对象转换为 `LayoutElement(type="text", ...)`，并扁平化 words 和 chars 供下游使用。
4. `table_extractor`：使用线段投影法检测表格：
   - 从页面绘制指令中提取细长矩形作为水平/垂直线段。
   - 以紧容差（`merge_group_tol=0.3`）合并共线线段，保留网格结构。
   - 通过线段交点构建单元格网格；对列结构变化的表格使用基于行的降级策略。
   - **WPS/Office 财务表**：通过填充单元格矩形检测子行，按文本模式（中文章节标记如 `一、`、`（一）`、`1.`）合并行，并删除过度分割的空白列。
   - 当线段投影产生过度碎片化的结果（>30 列或 >10 个表）时，降级使用 `page.find_tables()`。
5. `image_extractor`：通过 `page.get_images()` 提取内嵌图片资源并写入磁盘。
6. `layout_builder`：将文本元素、表格和图片合并为单页有序的 `LayoutElement` 列表。中心点落入表格 bbox 的文本元素会被移除，避免重复输出。
7. 印章坐标（如传入 `Pipeline`）被转换为 `Seal` 对象，并作为 `LayoutElement(type="seal", ...)` 追加。
8. `json_writer` 和 `markdown_writer` 序列化结果。每页的 JSON 和 Markdown 也会写入 `output_dir/pages/`。
9. `render_engine`：使用 `page.get_pixmap()` 将每页渲染为 PNG。

### 核心数据模型

所有模型定义位于 `src/pdflayoutparser/models.py`：

- `Document` → `Page` → `Block` → `Line` → `Word` → `Char`
- `Table` → `Cell`（含 `rowspan`/`colspan`）
- `Image`、`Seal`、`RenderInfo`
- `LayoutElement` — 统一的页面元素，含 `type`、`bbox`、`order`、`content`

JSON 输出格式：顶层键为 `document`（元数据）和 `pages`（页面数组）。每页包含 `blocks`、`tables`、`images`、`seals`、`render`、`layout_elements`。

### 表格提取细节

`table_extractor.py` 是最复杂的模块。修改时需注意以下关键行为：

- `_extract_lines_from_drawings`：水平线判定为 `height < 2pt` 且 `width >= 4pt` 的矩形；垂直线判定为 `width < 2pt` 且 `height >= 4pt` 的矩形。
- `_merge_oversegmented_columns`：从列数 >10 的表中删除完全为空的间隔列（密度 == 0.0）。
- `_assign_text_to_cells`：使用词级粒度；同行词以空格连接，不同行词直接拼接（用于处理窄财务单元格中换行的数字）。

## 编码规范

- **所有源文件必须使用 UTF-8 编码。**
- 文件读写操作必须显式指定 `encoding="utf-8"`。
- JSON 序列化使用 `ensure_ascii=False` 以保留中文字符。
- 字符串字面量统一使用双引号，文档字符串使用 `"""`。
- 类型注解使用 `from __future__ import annotations` 或 Python 3.10+ 语法。
- 模块级 docstring 说明模块职责；类和方法级 docstring 说明用法和参数。

## 测试

测试位于 `tests/` 目录，使用 pytest。`tests/conftest.py` 提供 fixture（`tmp_dir`）和辅助函数（`make_text_pdf`、`make_multi_page_pdf`、`make_pdf_with_image`），这些函数使用 PyMuPDF 创建临时 PDF。无需外部 PDF 测试文件。

## 设计规格

完整设计规格见 `docs/superpowers/specs/2026-04-28-pdflayoutparser-design.md`（中文）。v1.0 明确不做：OCR、图像语义识别、印章自动检测、多栏阅读顺序优化、页眉页脚自动剔除。
