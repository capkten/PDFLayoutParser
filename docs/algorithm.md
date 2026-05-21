# PDFLayoutParser 算法与流程详解

> 基于 PyMuPDF (`fitz`) 的矢量 PDF 解析器：将 PDF 转为结构化 JSON / Markdown，包含文本层级、表格、图片、印章和页面预览。
>
> 本文档对应 `src/pdflayoutparser/` 当前实现，按"整体流水线 → 各模块算法细节"组织。

---

## 1. 整体流水线

入口为 `Pipeline.run()`（`src/pdflayoutparser/pipeline.py`）。流程分两阶段：先做文档级元数据加载，再逐页执行 9 步处理；处理完所有页后输出整文档级 JSON / Markdown。

```
                         Pipeline.run
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
        Loader.load                  逐页处理（for page）
   (Document + Page 元数据)                  │
                                            ▼
        ┌───────────────────────────────────────────────────────┐
        │  a. TextExtractor       Block→Line→Word→Char         │
        │  b. LayoutMapper        Block → LayoutElement(text)   │
        │  c. TableExtractor      Table 集合 + 单元格            │
        │  d. ImageExtractor      Image + 文件落盘               │
        │  e. Seal 注入           外部坐标 → Seal                │
        │  f. LayoutBuilder       text + table + image 合并      │
        │  g. 追加 seal LayoutElement                           │
        │  h. 写回 page.layout_elements                          │
        │  i. RenderEngine        page → PNG                    │
        │  j. JSONWriter / MarkdownWriter（单页）                │
        └───────────────────────────────────────────────────────┘
                              │
                              ▼
        JSONWriter / MarkdownWriter（整文档：output.json / output.md）
```

输出目录布局（`output_dir/`）：

```
output_dir/
├── images/                    # 页内图片资源
│   └── page-XXX-img-YYY.<ext>
├── pages/                     # 单页输出
│   ├── page-XXX.png           # 页面预览（render_engine 写入此目录）
│   ├── page-XXX.json
│   └── page-XXX.md
├── output.json                # 全文档 JSON
└── output.md                  # 全文档 Markdown
```

> 注：`RenderEngine` 接收 `output_dir` 作为渲染输出根目录；`Pipeline` 把它直接传入 `RenderEngine(self.output_dir, self.render_dpi)`，并不保证 PNG 落入 `pages/` 子目录。这与 JSON / MD 单页输出的 `pages/` 目录是平行的两条路径。

---

## 2. 数据模型（`models.py`）

所有模型都是 `@dataclass`：

| 模型 | 关键字段 | 说明 |
| ---- | ---- | ---- |
| `BBox` | `x0,y0,x1,y1` | 轴对齐包围盒，PDF 用户单位（pt）|
| `Char` | `text, bbox, font, size, color, flags` | 单字符 |
| `Word` | `text, bbox, chars[]` | 一个 span 的文本与字符列表 |
| `Line` | `text, bbox, words[]` | 一行文本（PyMuPDF 提供的 line）|
| `Block` | `text, bbox, lines[]` | 文本块；`text` 用 `\n` 拼 line |
| `Span` | `text, bbox, font, size` | 样式分段（用于 LayoutElement.spans）|
| `Cell` | `text, row_index, col_index, bbox, rowspan, colspan` | 表格单元格 |
| `Table` | `bbox, rows, cols, cells[], confidence, source` | 表格 |
| `Image` | `bbox, page_index, resource_index, width, height, path, ext` | 嵌入图片 |
| `Seal` | `bbox, page_index, path` | 印章（外部坐标传入）|
| `RenderInfo` | `path, width, height, dpi` | 页面预览 PNG |
| `LayoutElement` | `type, bbox, order, content, spans, lines, words, chars` | 通用页面元素，`type ∈ {text, table, image, seal, separator}` |
| `Page` | `index, size, rotation, blocks, tables, images, seals, render, layout_elements` | 单页结果 |
| `Document` | `file_name, page_count, pages` | 顶层文档 |

`LayoutElement.content` 字段类型由 `type` 决定：`text` 为字符串（block.text）；`table/image/seal` 为对应 dataclass。

---

## 3. 模块算法细节

### 3.1 Loader（`loader.py`）

- 用 `fitz.open(file_path)` 打开 PDF。
- 读取页数，遍历每页拿到 `page.rect`（宽高）和 `page.rotation`。
- 构造 `Document(file_name, page_count, pages=[Page(index, size, rotation), ...])` 并返回。

此阶段只填 `Page` 元数据，`blocks/tables/images/seals/render/layout_elements` 都留空。

### 3.2 TextExtractor（`text_extractor.py`）

入口：`extract_blocks(page) -> List[Block]`。

1. 调用 `page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)`，保留 PDF 中的空白字符。
2. 遍历 `page_dict["blocks"]`：
   - 跳过 `type != 0` 的非文本块（图片块）。
   - 每个 block 遍历 `lines → spans`。
3. **字符层处理**：
   - 若 `span_dict.get("chars")` 存在，直接逐字符封装为 `Char`，字段（font/size）回退到 span 级别。
   - 若 PyMuPDF 没有提供 char 数据，用 span 文本长度均分 span 宽度，**合成等距 Char**：
     ```
     char_width = (span.x1 - span.x0) / len(span_text)
     char_i.bbox = (x0 + i*w, y0, x0 + (i+1)*w, y1)
     ```
4. 每个 span 封装为一个 `Word`（带其字符）；line 文本由其下所有 word 的 `text` **直接 join**（无空格，因为 PDF 内 span 之间通常已含必要空白且 `TEXT_PRESERVE_WHITESPACE` 已保留它们）。
5. block 文本由其下所有 line 的 `text` 用 `\n` join。

**说明**：PyMuPDF 默认不返回 char 级几何，只有部分版本/标志位会给。这里的"等距合成"是降级方案，宽度信息粗略，不应用于精确字宽分析。

### 3.3 LayoutMapper（`layout_mapper.py`）

把 `Block` 列表线性映射为 `LayoutElement(type="text", ...)`：

- `bbox` = block.bbox；`order` 为输入顺序索引；`content` = block.text。
- 同时把每个 block 内的 `lines/words/chars` 扁平化挂在 `LayoutElement.lines/words/chars` 三个列表上，方便下游不再下钻。

不做任何阅读顺序重排或过滤——这些发生在 `LayoutBuilder`。

### 3.4 TableExtractor（`table_extractor.py`）

整个仓库最复杂的模块。**核心思想：从 PDF 矢量绘制指令中提取细长矩形作为水平/垂直线段，由线段交点构造单元格网格。** 当线段法明显失败（碎片化或行/列异常）时，降级到 `page.find_tables()`。

主入口：`extract(page)`：

```python
tables = self._extract_via_lines(page)
if not tables:
    tables = self._extract_via_pymupdf(page)
elif self._should_fallback(tables):
    tables = self._extract_via_pymupdf(page)
return tables
```

参数（构造时可调）：

| 参数 | 默认 | 含义 |
| ---- | ---- | ---- |
| `line_tolerance` | 2.0 | 线段定义阈值（细长矩形判定 + 容差）|
| `merge_group_tol` | 0.3 | 合并共线线段时的 y/x 分组容差 |
| `row_gap_threshold` | 30.0 | 同页区分多个表的水平线行间隔阈值 |
| `fallback_max_cols` | 30 | 平均列数超过此值视为过度分割 |
| `fallback_max_tables` | 10 | 表格数量超过此值视为碎片化 |

#### 3.4.1 主流程 `_extract_via_lines`

```
_extract_lines_from_drawings  →  原始 h/v 线
_merge_h_lines / _merge_v_lines  →  合并共线线段
_find_table_regions           →  连通分量 → 表格区域 → cells
_assign_text_to_cells         →  词级文本回填
_merge_oversegmented_columns  →  消窄空白列
封装为 Table(source="line_projection", confidence=0.9)
```

#### 3.4.2 线段提取（`_extract_lines_from_drawings`）

仅消费"可见笔画 / 可见填充矩形"，并排除被后续不透明绘制完全覆盖的矩形。这层可见性筛选由 `_iter_effective_drawing_rects` 完成：

1. **`_has_visible_stroke(path)`**：path `type ∈ {"s","fs"}`，`stroke_opacity > 0`，`width > 0`，`color != None`。
2. **`_is_visible_fill_line_rect(path, rect)`**：path `type == "f"`，`fill_opacity > 0`，`fill != None`，且形状细长（h<tol 且 w≥2tol，或 w<tol 且 h≥2tol）。
3. **`_is_rect_fully_covered_later(rect, seqno, bboxlog)`**：用 `page.get_bboxlog()` 查找 seqno 之后的 `fill-path / fill-image / fill-shade`；如果某一项与 rect 的相交面积 ≥98%，认为后续被完全覆盖，剔除。

得到候选矩形后逐一分类：

```
h < line_tolerance  且  w ≥ 2*line_tolerance   →  水平线，y 取矩形垂直中心
w < line_tolerance  且  h ≥ 2*line_tolerance   →  垂直线，x 取矩形水平中心
w ≥ tol 且 h ≥ tol 且 面积 < 50% 页面面积      →  普通矩形 → 拆 4 条边线
其它（角点小矩形、过大背景）                     →  忽略
```

把普通矩形拆 4 条边线，是为了让"WPS/Office 这类用矩形而不是线段画表格"的情况也能进入网格构造。50% 面积上限避免把整页背景当成表格。

> 历史保留：仓库里仍能看到 `_extract_lines_from_drawings_legacy`（旧版本不做可见性过滤），当前主路径已切到 `_iter_effective_drawing_rects`。

#### 3.4.3 线段合并（`_merge_h_lines` / `_merge_v_lines`）

水平线为例：

1. 按 `(y, x0)` 排序。
2. 顺序扫描，同组判定：`|y - group_y| <= merge_group_tol(=0.3)`。
3. 一组结束（flush）时：
   - 该组内的线按 x0 排序；
   - 维护当前合并区间 `[cur_x0, cur_x1]`，若下一段 `x0 <= cur_x1 + line_tolerance(=2.0)` 则延展，否则产出区间并新开。
   - 新行上的 y 取组内 y 的算术平均。

垂直线同理（x/y 调换）。

设计要点：**`merge_group_tol=0.3` 极小**，意图是只合并"同一条边在矢量层被 PDF 拆成多个共线碎片"，绝对不让相邻行/相邻列被误并到同一条边——这是矩形拆边法保留网格分辨率的关键。

> 文件中还存在 `_filter_lines_by_components` 的连通分量过滤实现，但 `_extract_via_lines` 已注释掉（"多余的线不影响表格结构"）。该方法不再参与主流程。

#### 3.4.4 连通分量与表格区域（`_find_table_regions`）

```
_find_line_components → _select_primary_component_lines
                     → _build_cells_in_region (网格优先)
                     → 必要时 _build_cells_row_based  (按行降级)
                     → _merge_adjacent_tables
```

**`_find_line_components`**：以 h/v 交点为边构建无向图，BFS 找连通分量。判定相交：

```
hx0 - tol ≤ vx ≤ hx1 + tol   且   vy0 - tol ≤ hy ≤ vy1 + tol
```

只保留 `|h| ≥ 2 且 |v| ≥ 2` 的分量。

**`_select_primary_component_lines`**（每个分量内）：

- 计算分量的 `width = max_x - min_x`，`height = max_y - min_y`。
- "主竖线"过滤：`(y1-y0) ≥ 0.6*height` 的 v_line。
- "主横线"过滤：`(x1-x0) ≥ 0.5*width` 的 h_line。
- 若过滤后 < 2 条，回退到原集合。

意图：财务表中"小填充矩形"会贡献短局部线段；这些线不应作为整表的全局列/行边界。

进入区域构造：

- `valid_h_group`：保留与本分量 v_lines 真正有交点的 h_lines。
- 由 `valid_h_group` 的 y 集合得 `h_ys`，v_group 的 x 集合得 `v_xs`，区域 `bbox = (v_xs[0], h_ys[0], v_xs[-1], h_ys[-1])`。
- 调用 `_build_cells_in_region(h_ys, v_xs, valid_h_group, v_group)` 构造 cells。

**降级策略**：若 cells 数 < `(rows-1)*(cols-1) * 0.4`，或前两行至少有一行的填充率 < `expected_cols * 0.5`（顶部行稀疏，疑似合并表头），改用 `_build_cells_row_based`。降级时优先只用"纵向跨度 ≥ 0.8*table_height"的主竖线，避免子单元格小竖线把列拆碎；若主竖线 < 2 条则退回全 v_group。若按行法产出更多 cells，或包含 `colspan>1` 的合并表头，则采纳按行法的结果。

#### 3.4.5 网格法构造单元格（`_build_cells_in_region`）

对每个潜在格子 `(i, j)`：

```
y0, y1 = h_ys[i], h_ys[i+1]
x0, x1 = v_xs[j], v_xs[j+1]
```

判定保留：

1. **左/右竖边必须存在**：`_has_v_line(v_lines, x0, y0, y1)` 且 `_has_v_line(v_lines, x1, y0, y1)`。
2. **首行 (i==first_row) 与末行 (i==last_row-1)** 同时检查上/下横边都存在。中间行不要求横边横跨整列宽——这允许"合并单元格内部缺少分隔横线"。

`_has_h_line(h_lines, y, x0, x1)`：取所有 `|ly - y| ≤ line_tolerance` 的水平线，对每条计算与 `[x0,x1]` 的覆盖：

```
overlap = min(lx1, x1+tol) - max(lx0, x0-tol)
return  overlap ≥ 0.3 * (x1 - x0)
```

`_has_v_line` 对称（覆盖 ≥ 30% 即认为存在）。

> 注释里写"覆盖 ≥80%"是历史描述，现行实现使用 30% 阈值——更宽容。

最终 `len(cells) < 4` 视为非表格区域，丢弃。

#### 3.4.6 按行法构造（`_build_cells_row_based`）

每行 `i` 处理逻辑：

1. 以 `tol=line_tolerance` 容差找出"跨越当前行 ≥ 30% 行高"的所有竖线 x（行特定的 row_v_xs）。
2. 用 row_v_xs 在该行内构格；每格再分别查上/下/左/右四边是否齐全：
   - 四边都齐 → 接受。
   - 否则若是边界列（j == 0 或 j == len(row_v_xs)-2）且左右竖边存在 → 接受（可能是合并单元格）。
3. `colspan` 由 `row_v_xs[j]/row_v_xs[j+1]` 在 `global_v_xs` 中的索引差给出。
4. 总 cells < 4 丢弃。

适合"每行列结构不同的财务报表"——例如分章节标题行只有 1~2 列、明细行有完整列。

#### 3.4.7 子行边界（`_extract_subrow_boundaries`）

仅在 `_build_cells_with_subrows` 调用（当前 `_extract_via_lines` 主流程未直接调它，但作为对外能力保留）。算法：

1. 在第一列附近寻找候选填充矩形：
   - 宽 `20 ≤ w < 55`，高 `10 ≤ h < 25`；
   - `table_bbox.x0 ≤ rect.x0 ≤ table_bbox.x0 + 60`；
   - 落在 table_bbox 的 y 范围内。
2. **按 (y0, y1) 1pt 容差合并同一行**（取均值更新区间）。
3. 排序后再合并"严格重叠"的区间（`y0 < prev_y1 - 0.5` 才合并）。
4. 由有效区间和表格上下边界构造 y 边界列表（相邻边界差 > 1pt 才插入）。

`_build_cells_with_subrows(subrows, v_lines, table_bbox)` 对每个相邻 subrow 区间 `(y0, y1)`：

- 跳过 `y1-y0 < 5pt` 的过短区间。
- 在跨越整张表（`vy0 ≤ y0+1` 且 `vy1 ≥ y1-1`）的竖线中，再找跨越本行 `(vy0 ≤ y0+1 且 vy1 ≥ y1-1)` 的竖线作为列分割。
- 直接以 `row_v_xs[j]/[j+1]` 配对生成 cells（不再校验四边）。

#### 3.4.8 文本回填（`_assign_text_to_cells`）

**关键设计：词级粒度，按行分组重组文本。**

1. 取 cells 的 union bbox，向外扩 5pt 后调 `page.get_text("words", clip=rect)` 拿词列表。
2. 每个词 `(wx0, wy0, wx1, wy1, text, ...)` 用中心点 `(cx, cy)` 落到第一个包含它的 cell（bbox 严格包含中心）。
3. 单元格内重组：
   - 词列表按 `(cy, cx)` 排序；
   - 同一行（与上一词的 |cy - last_y| ≤ 5pt）追加到当前行；
   - 换行时把当前行内词按 cx 排序后**用空格 join**；
   - 最终把所有行**直接 join（无空格）**。

这种"行内空格、行间无空格"的策略专治财务表里"窄列被强制换行的数字"——把 "1," + "234" 拼成 "1,234" 而不是 "1, 234"。

#### 3.4.9 列消空（`_merge_oversegmented_columns`）

矩形边分解会把一列实际数据拆成"一列窄竖边 + 一列实际内容"。本步合并这种"窄而空"的边列。

1. 对每列计算：
   - `col_width[ci]` = 该列所有 cell 宽度的算术平均；
   - `col_density[ci]` = 该列非空 cell 数 / 行数。
2. 识别 **窄边列**：`col_density == 0.0 且 col_width < 10pt`。
3. 把每个窄边列合并到相邻的非窄边列；候选取左右两侧中**更宽的**那个。
4. 重新编号其余列；窄边列的所有 cell 文本被并入目标列（相邻链式合并支持："窄边 → 窄边 → 数据列"也会归到末端数据列）。
5. 若没有窄边列且总列数 ≤ 10，直接返回。
6. 合并后产出新 Cell：
   - 文本是组内非空文本用空格 join；
   - bbox 是组内的并集；
   - `colspan` 由组内 cell 的 `(col_index, colspan)` 覆盖区间合并而来：`colspan = max_covered_col - min_covered_col + 1`。

> 注：`spacer_cols`（"宽空白列"）的剔除分支在当前代码里被显式留空（`spacer_cols: set[int] = set()`），仅做"窄边列"合并。

#### 3.4.10 文本模式行合并（`_merge_rows_by_text_pattern`）

注：此函数在 `_extract_via_lines` 里**未被调用**，作为可选后处理保留。算法与"中文财报章节/项目结构"强耦合：

- **章节标记判定（`_is_section_marker`）**：以下任一开头视为标记
  - 一、 二、 …… 十、（取前 2 字符比对）
  - （一）（二）……（开头 1 char `（` + 第 3 char `）`）
  - `<digit><.|．>`（如 `1.` `1．`）
  - `加：`、`减：`、`其中：`
- **行合并逻辑**：
  - 第 0 列文本带章节标记 → 开新逻辑行（且把先前 pending 收纳到新行作为首数据行的一部分）。
  - 第 0 列空：当前组若已有章节标记 → 视为续行；否则放入 `pending`，等待下一个标记行。
  - 第 0 列有文本但非标记 → 续上一组（无组则开新组）。
- 对每个逻辑行组，按列 `col_index` 收集旧 cells，文本拼接（直接相连），bbox 取并集，重编号 row_index。

#### 3.4.11 顶部稀疏行过滤（`_filter_sparse_top_rows`）

未在主流程调用，留作可选清洗。规则：从顶部第一行开始，找到第一个"满足任一条件"的行作为有效起点：

- 第 0 列文本是 numbered marker（一、/（一）/数字加点 三类，**不含 加：/减：/其中：**）；
- 行密度 ≥ 40% 且第 0 列非空。

之前的行整体丢弃并对剩余行重编号。

#### 3.4.12 相邻表格合并（`_merge_adjacent_tables`）

成对扫描所有候选表，反复迭代直到无更多合并：

- y 重叠率 = `min(y1) - max(y0) / max(height_i, height_j) > 0.3`；
- x 间隙 < 80pt（含负向重叠取 0）；
- 命中则把第二个表的 cells 平移到 `col_index + (max_col_i + 1)`，bbox 取并集。

适用场景：一行被矢量画成左右两块的表（中间空隙）被还原为一个逻辑表。

#### 3.4.13 降级触发（`_should_fallback`）

满足任一条件即触发 `_extract_via_pymupdf`：

1. 全部表都是 `rows ≤ 1 且 cols ≤ 1`（退化）；
2. cells 总数 ≤ 表数（每表平均 ≤ 1 个 cell）；
3. 平均列数 > `fallback_max_cols(=30)`（合并单元格表过分割信号）；
4. 表数量 > `fallback_max_tables(=10)`（碎片化信号）。

#### 3.4.14 PyMuPDF 降级（`_extract_via_pymupdf`）

直接调 `page.find_tables()`，对每个 table：

- 取 `table.bbox` 作 Table.bbox；
- `table.extract()` 拿到行二维数组，行数为 rows、首行长度为 cols；
- 逐 (r, c) 生成 Cell；如果 `table.cells` 数组提供 bbox 则用它，否则给 `(0,0,0,0)` 占位。
- `confidence = 1.0`，`source = "PyMuPDF.find_tables"`。

### 3.5 ImageExtractor（`image_extractor.py`）

1. `fitz.open(file_path)` 单独打开（线程/调用安全考虑）。
2. 取目标页的 `page.get_images(full=True)`。
3. 对每个 `(xref, ...)`：
   - `doc.extract_image(xref)` 拿原始字节、`ext`、`width`、`height`。
   - 写入 `<output_dir>/page-XXX-img-YYY.<ext>`。
   - 用 `page.get_image_info()[img_index].bbox` 拿页面坐标包围盒（若索引存在）。
4. 返回 `Image` 列表。

> 注意：`page.get_images()` 返回的是页面引用了哪些图像 XObject，与 `page.get_image_info()` 顺序通常一致；当不一致或后者数量不足时，本实现会让 `bbox = None`（留给上游容错）。

### 3.6 LayoutBuilder（`layout_builder.py`）

输入：text `LayoutElement[]`、`Table[]`、`Image[]`。输出：合并后的 `LayoutElement[]`。

1. **去重**：丢弃中心点落在任一表格 bbox（含 ±2pt 缓冲）内的 text 元素——这些文本已经被 cell.text 收纳。
2. **追加 table**：每个 table 包成 `LayoutElement(type="table", content=table)`，order 顺延。
3. **追加 image**：同理 `type="image"`。
4. （Pipeline 之后再追加 seal）。

`order` 是简单的尾部追加自增；不做阅读顺序排序。

### 3.7 Pipeline 中的印章注入

`Pipeline.__init__` 接收 `seal_coords: List[dict]`，每个元素形如：

```python
{"page_index": 0, "x0": 100, "y0": 200, "x1": 250, "y1": 350}
```

逐页过滤 `coord["page_index"] == page.index` 的项，转 `Seal(bbox, page_index)`，并以 `LayoutElement(type="seal", content=seal)` 追加到 `layout_elements` 末尾。

### 3.8 RenderEngine（`render_engine.py`）

简单封装 PyMuPDF 的 `page.get_pixmap`：

```python
mat = fitz.Matrix(dpi/72, dpi/72)        # 把用户单位缩放到目标 DPI
pix = page.get_pixmap(matrix=mat)
pix.save(f"page-{page_index:03d}.png")
```

返回 `RenderInfo(path, pix.width, pix.height, dpi)`。

### 3.9 JSONWriter（`json_writer.py`）

递归把 `Document` 转字典再 `json.dump`，关键约束：

- `encoding="utf-8"` + `ensure_ascii=False`，保留中文字符。
- 顶层结构：`{"document": {...}, "pages": [page_dict, ...]}`。
- `Page.layout_elements[*].content` 通过 `_content_to_dict` 分派：
  - `Table` → `_table_to_dict`
  - `Image` → `_image_to_dict`
  - `Seal` → `_seal_to_dict`
  - `Block` → `_block_to_dict`
  - 其他基本类型直接透传（text 类型其实就是字符串）。
- `LayoutElement` 仅当 `spans/lines/words/chars` 非空时才输出对应键，避免大量空数组。

`write_page` 与 `write` 区别仅在最外层（单页只输出一个 page dict，无 document 包装）。

### 3.10 MarkdownWriter（`markdown_writer.py`）

按 `page.layout_elements` 顺序渲染。每种 type 的渲染规则：

| type | 渲染 |
| ---- | ---- |
| `text` | `str(content)` 一行 + 空行 |
| `table` | `_render_table()` 见下 |
| `image` | `![image](path)` 或 `[图片]` |
| `seal` | `![seal](path)` 或 `[印章: page-N]` |
| `separator` | `---` |
| 其他 | 跳过 |

**`_render_table`**：

1. 按 `row_index` 分组、`col_index` 排序。
2. 计算列总数 `col_count = max(len(row))`、空白率 `empty_ratio = empty_cells / total_cells`。
3. 找出 **存在内容的列下标集合 `non_empty_cols`**。
4. 若无内容列直接返回空。
5. **降级判断**：`empty_ratio > 0.5` 或 `len(non_empty_cols) > 15` → `_render_table_as_text`（紧凑文本版）。
6. 标准 Markdown 表：每行只渲染 `non_empty_cols`，单元格内换行替换为空格，再走 `_clean_number_text`；首行后插入分隔行 `| --- | --- | ...`。

**`_clean_number_text`**：用正则 `(?<=[\d,\.\-])\s+(?=[\d,\.\-])` 删掉**两侧都是数字相关字符的中间空格**——补上单元格内多次换行被回填空格切碎的数字（"1, 234" → "1,234"）。

**`_render_table_as_text`**：稀疏/超宽表的兜底。每行按 `non_empty_cols` 顺序拼成 `| ... | ... |`，跳过整行无内容的行，首个有内容行后追加分隔行。

### 3.11 CLI（`cli.py`）

`argparse` 三参数：

- `pdf_path`（必需）
- `--output / -o`（默认 `.`）
- `--dpi`（默认 200）

调用 `Pipeline(pdf_path, output_dir, render_dpi).run()`，打印 `Success!` 后返回 0。

`pyproject.toml` 注册了入口，安装后可以直接 `pdflayoutparser <pdf>` 使用。

---

## 4. 关键设计权衡

1. **不做 OCR**：v1.0 明确声明非目标，所有文本来自 PDF 文本层。扫描件需另行 OCR 后再喂入。
2. **不做语义重排**：`order` 字段只反映抽取顺序，不保证视觉阅读顺序。多栏 / 复杂排版需要消费方处理。
3. **表格优先线段法、PyMuPDF 兜底**：
   - 线段法对网格清晰、矩形边框分解的财务表有更好的精度（保留 colspan）；
   - PyMuPDF 的 `find_tables()` 对扫描风格、不规则表更鲁棒；
   - 选择由 `_should_fallback` 启发式决定，并非严格指标。
4. **小公差 + 矩形拆边**：`merge_group_tol = 0.3` 与 `line_tolerance = 2.0` 的搭配，在矩形拆边带来的"4 倍线段量"前提下，仍能把同一条边的 PDF 碎片合并掉，又不让相邻边粘连。
5. **去重靠中心点**：`LayoutBuilder._inside_any_table` 用 bbox 中心点判定文本是否落入表格，简单但够用；对跨边界文本（极少见）会漏。
6. **印章是外部输入**：`Seal` 不做检测，由调用方传坐标。设计文档明确不做"印章自动检测"。

---

## 5. 阅读源码的建议路径

1. 先看 `models.py` 建立类型印象。
2. `pipeline.py` 看完整执行流。
3. 单独深入 `table_extractor.py`：
   - 自顶向下：`extract` → `_extract_via_lines` → `_find_table_regions` → `_build_cells_in_region`/`_build_cells_row_based`；
   - 后处理：`_assign_text_to_cells` → `_merge_oversegmented_columns`；
   - 兜底分支：`_should_fallback` → `_extract_via_pymupdf`。
4. 输出层：`json_writer.py` 与 `markdown_writer.py` 更像格式适配器，独立看即可。
5. `tests/test_table_extractor.py` 覆盖了线段法 vs PyMuPDF 兜底的关键分支，是修改前必读的回归用例。
