# 无线表格调试可视化设计

日期：2026-05-15

## 背景

当前无线表格链路已经接入 `text_region_detector`，并通过 `_detect_text_regions()` 进入 `_extract_via_text_alignment()`。这使得无线表格的处理流程逐步拆分为：

1. 区域发现
2. 区域内建格

但在实际调试时，现有输出主要是：

- 页面渲染图
- JSON
- Markdown

这些结果只能看到最终结构，不能直观看到“候选区域找得对不对”“行框切得对不对”“列导线推断歪没歪”。为了支持后续无线表格算法调试，需要增加一套可选的、面向主流程运行的调试可视化输出。

## 目标

当用户通过 CLI 或 `Pipeline` 打开 `debug` 开关时，系统在正常输出解析结果的同时，额外输出**无线表格调试图**，用于可视化以下信息：

1. 候选区域 bbox
2. 区域内行框
3. 区域内列导线

调试图只针对**命中了 `text_alignment` 表格的页面**生成，不对所有页面无差别输出。

## 非目标

- 不修改默认运行行为
- 不改变 `output.json` / `output.md` schema
- 不为有线表格路径新增调试图
- 不在第一步里绘制最终 cell 框
- 不把可视化逻辑直接堆进 CLI
- 不要求 `TableExtractor.extract()` 对外改成复杂返回值

## 设计选择

本次设计基于以下已确认的决策：

- 调试开关挂在 CLI / `Pipeline` 层
- 调试图内容为“候选区域 bbox + 行框 + 列导线”
- 只输出命中无线表格分支的页面

## 设计方案

### 触发方式

在 [`cli.py`](</D:/codes/PDFLayoutParser/src/hexai_pdf_parser/cli.py>) 增加 `--debug` 参数，并透传到 [`Pipeline`](</D:/codes/PDFLayoutParser/src/hexai_pdf_parser/pipeline.py>)。

`Pipeline` 内部保存一个布尔开关，例如：

- `debug: bool = False`

默认关闭。关闭时行为与当前版本一致。

### 输出目录

当 `debug=True` 时，在输出目录下创建独立的调试目录，例如：

```text
<output_dir>/debug/text-alignment/
```

调试图文件名采用页号命名：

```text
page-046.png
page-051.png
page-058.png
```

这样可以直接与已有的 `page-046.json`、`page-046.md`、`page-046.png` 对照。

### 输出条件

只有当某一页满足以下条件时，才输出无线表格调试图：

1. 该页无线表格分支被执行
2. 该页产生了至少一个 `source="text_alignment"` 的表格
3. 该页存在可视化所需的调试数据

这意味着：

- 没有无线表格命中的页，不输出 debug 图
- 纯线框表格页，不输出 debug 图
- 纯 PyMuPDF fallback 页，不输出 debug 图

## 可视化内容

每张调试图叠加以下三类信息：

### 1. 候选区域 bbox

对 `_detect_text_regions()` 返回的每个候选区域绘制外框。

目的：

- 判断 region detector 的命中范围是否合理
- 判断区域是否过宽、过窄、跨段错误合并

### 2. 行框

对候选区域中的每一行绘制 bbox。

目的：

- 判断 `_collect_text_rows()` / 区域映射后的行结构是否正确
- 判断 trim 后保留下来的行范围是否稳定

### 3. 列导线

对每个候选区域最终用于建格的 `column_guides` 画竖向导线。

目的：

- 判断 `_infer_column_guides()` 的结果是否偏移
- 判断列是否被过度切碎或错误合并

## 不画的内容

第一步明确不画：

- 最终 cell bbox
- token bbox
- 文本内容标签
- 多颜色区分不同 cell

原因是第一步目标是优先看“区域发现 + 列推断”，如果把 cell 和 token 也加上，图面会明显过杂，不利于快速审阅。

## 接入位置

### CLI / Pipeline

[`cli.py`](</D:/codes/PDFLayoutParser/src/hexai_pdf_parser/cli.py>) 负责解析 `--debug` 参数。

[`pipeline.py`](</D:/codes/PDFLayoutParser/src/hexai_pdf_parser/pipeline.py>) 负责：

- 接收 `debug` 参数
- 创建 debug 输出目录
- 在逐页处理时判断是否需要输出无线表格调试图
- 调用调试渲染器写出 PNG

### TableExtractor

[`table_extractor.py`](</D:/codes/PDFLayoutParser/src/hexai_pdf_parser/table_extractor.py>) 负责在无线表格链路内部收集调试所需数据，但仍然保持对外主职责是“返回表格结果”。

建议不要把 `extract()` 的公开返回值改成 `(tables, debug_payload)`。第一步更稳妥的方式是：

- `extract()` 继续返回 `List[Table]`
- 在 `TableExtractor` 实例上保存最近一页的 debug snapshot

例如：

- `self._last_text_alignment_debug: dict | None`

这个快照只作为 `Pipeline` 调试输出的内部数据来源，不进入最终输出 schema。

### 调试渲染器

新增一个小型 renderer 模块，职责单一：

- 输入：PDF 页、调试快照、输出路径、dpi
- 输出：叠加候选区域 bbox / 行框 / 列导线的 PNG

它不参与解析逻辑，只负责画图。

## 调试快照数据结构

建议每页只保存一份面向无线表格的 snapshot，包含：

- `page_index`
- `regions`

每个 `region` 至少包含：

- `bbox`
- `rows`
- `column_guides`

其中：

- `rows` 只需要保存行级 bbox，不需要完整 token
- `column_guides` 保留最终用于建格的 guide 列表

这套结构应尽量轻量，避免为了调试而复制过多页面文本数据。

## 数据流

开启 `debug` 时，页面处理流程变为：

```text
Pipeline.run()
-> TableExtractor.extract(page)
-> _extract_via_text_alignment()
-> _detect_text_regions()
-> 生成 text-alignment tables
-> 在 extractor 上记录 _last_text_alignment_debug
-> Pipeline 检查该页是否命中 text_alignment
-> 若命中，则调用 debug renderer 输出 page-XXX.png
```

默认关闭时：

```text
Pipeline.run()
-> TableExtractor.extract(page)
-> 正常输出，无额外调试图
```

## 为什么这样设计

这个方案的优点是：

- 调试入口统一，适合整份 PDF 跑批
- 默认行为不变
- 输出只覆盖需要关注的无线表格页面
- 调试图和主流程结果天然按页对应
- 可视化逻辑与解析逻辑解耦

同时，这个方案也保留了后续扩展空间：如果以后要继续画 token 或 cell，可以在同一调试 renderer 上逐步加层，而不需要重改 CLI 或 Pipeline 接口。

## 风险

### 调试逻辑污染主逻辑

如果为了调试而改动 `extract()` 主返回值，或者在主流程里塞过多条件分支，会让正式解析逻辑变得更难维护。

缓解方式：

- `extract()` 公开接口保持不变
- 调试数据只作为实例级 side data
- 调试渲染器独立成模块

### 调试图误导

如果画的是中间态 guide，而不是最终真正用于建格的 guide，调试图会和最终结果对不上。

缓解方式：

- 调试图中的行框和列导线必须使用最终参与建格的数据

### 输出过多

如果对所有页面都输出调试图，长 PDF 会产生大量文件，影响使用体验。

缓解方式：

- 只输出命中 `text_alignment` 的页面

## 测试策略

### 1. CLI / Pipeline 参数测试

验证：

- 默认不传 `--debug` 时，不生成调试目录
- 传 `--debug` 时，会创建调试目录

### 2. 命中页输出测试

构造带无线表格的测试 PDF，验证：

- 存在 `source="text_alignment"` 时，会生成对应 debug PNG
- 文件名与页号一致

### 3. 非命中页不输出测试

验证以下场景不应生成调试图：

- 无表格页
- 仅线框表格页
- 仅 PyMuPDF fallback 页

### 4. 调试快照结构测试

验证 `TableExtractor` 产出的调试快照中：

- region bbox 存在
- row bbox 列表存在
- column_guides 存在

### 5. 主流程回归测试

验证开启 `debug` 不改变：

- `output.json`
- `output.md`
- 表格数量和来源

## 后续演进

如果第一步稳定，后续可以继续扩展：

- 增加 cell bbox 可视化
- 增加 token bbox 可视化
- 增加每个 region 的来源标签或颜色分组
- 增加只输出指定页的 debug 参数

## 成功标准

当满足以下条件时，可以认为这版设计达成目标：

- `--debug` 可通过 CLI / `Pipeline` 打开
- 只对命中无线表格的页面输出调试图
- 调试图中包含候选区域 bbox、行框、列导线
- 默认运行行为保持不变
- 开启 `debug` 不改变 JSON / Markdown / 表格识别结果
