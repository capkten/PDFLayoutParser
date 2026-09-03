# 中文无线表格输出顺序模式与合并边界设计

## 背景与根因

`fix/zh_all_table_pages.pdf` 的页面索引 `591`（PDF 第 592 页，页面显示页码
`7`）在无线表格恢复时出现大量结构错误和文本漏失。当前输出目录为
`output/fix_full_rerun_current_20260901/`。

目标表格的 native PDF 输出顺序不是按视觉行交错，而是先连续输出左侧项目列，再
输出右侧表头和金额列：

```text
左1、左2、左3、...、右1、右2、右3、...
```

现有 `build_text_runs()` 在同一视觉行完成 span 到 atom 的组合后，调用
`_merge_wrapped_field_runs()`。该函数把 `flow` 连续、纵向重叠且有右侧 witness
的 run 视为一个上下换行字段。591 页左列相邻项目恰好连续满足这些条件，因此多条
独立记录被串成一个巨大 atom。后续 `merge_multiline_cells()` 又依据连续 native
flow 和同列几何继续合并，最终导致左列文本集中到一个 Cell，物理行数量被压缩，
网格冲突时还可能整体返回空结果。

另一个根因是 `NativeSpan` 当前没有保存 `rawdict` 的 block/line 来源。
`span_chain._native_dict()` 只能使用 `(0, 0, order)` 作为默认来源，无法可靠区分
“同一 native block 的真实换行”和“不同 block 的独立字段”。

## 目标

1. 在表格区域级别识别 native 输出更接近按行交错还是按列连续。
2. 按列连续时，使用单个文本块的几何位置参与列带、行和网格恢复，不使用跨 block
   的顺序驱动换行合并。
3. 同一 native block 内的相邻真实换行仍允许合并为一个逻辑 Cell。
4. 按行交错或模式不明确时保持现有顺序驱动路径，避免影响已经正确恢复的页面。
5. 继续只消费 native span、atom、列带、物理 Cell 和逻辑 Cell；中文/混合页面不回读
   `page.get_text("words")`，不回退 legacy 或 zebra 路径。
6. 保留列带、列标注、物理网格、逻辑网格、表头跨度、空槽位物化和 occupancy 检查。

## 非目标

- 不根据“年初数”“金额”等业务文字判断输出模式。
- 不为某个 PDF、页码或表格文字增加硬编码白名单。
- 不重写列带推断、rowspan/colspan 拓扑和空单元格物化。
- 不修改英文无线表格或 legacy page-words 文本对齐路径。
- 不把相邻空槽位合并，不放宽最终 occupancy 冲突检查。

## 方案

### 1. 保存 native 来源

扩展 `NativeSpan`，保存 `rawdict` 遍历时的
`(block_index, line_index, span_index)`。`collect_native_spans()` 在构造对象时
填充该来源，`span_chain._native_dict()` 和 `region_spans()` 原样保留。

对没有来源信息的测试 double 或外部调用，保留兼容默认值，但标记来源未知；来源未知
的对象不能被判定为“同一 native block 的真实换行”证据。

### 2. 区域级输出模式判定

在 `recover_cells_from_region()` 中，完成 `region_spans()` 后、构造最终 atom 前，
调用一个只依赖 native span 顺序和 bbox 的模式判定函数。判定使用以下几何证据：

- 连续 flow 项是否大多处于同一视觉行；
- 连续 flow 项是否大多位于相同 x 区域、中心 y 递增；
- 页面区域是否存在至少两个有明显水平分离的 x 轨迹；
- 纵向连续证据是否显著强于同一行交错证据。

只有在多列区域中存在足够长、足够稳定的纵向连续轨迹时才判为
`columnar`（按列连续）。`left1/right1/left2/right2` 这种交错顺序的垂直证据不足，
判为 `row_interleaved`。证据不足时使用 `row_interleaved`，保持原有行为。

模式是表格区域级状态，不根据业务文本分类，也不读取 page words。

### 3. 两种 atom 合并策略

`build_text_runs()` 接收判定出的模式，但保留现有同一 native line 的 span 组合，
包括字体分裂、紧邻中文字符、货币符号和必要的同一行 Latin 片段组合。

- `row_interleaved`：继续执行现有 `_merge_wrapped_field_runs()`，保留有右侧 witness
  的跨 block 换行字段恢复。
- `columnar`：跳过 `_merge_wrapped_field_runs()`。新增一个更窄的同 block 换行步骤，
  只在以下条件同时成立时合并：来源 block 相同、source line 相邻、文本位于下方、
  bbox 横向重叠充分、字号/粗体兼容、文本不是纯数值或占位符。合并文本使用换行符，
  并保留所有 span 引用、字符框、来源行范围和联合 bbox。

这个步骤的职责仍是 span 到 atom 的文本组合；列带和网格阶段不再重新拼接文字。

### 4. Cell 阶段的合并边界

`merge_same_slot_fragments()` 继续复用，用于同一物理槽位内已有来源证据的同一行
片段组合。

`merge_multiline_cells()` 增加模式约束：

- `row_interleaved` 保持当前跨 block、连续 flow 的保守多行 Cell 合并；
- `columnar` 不允许跨 block 的 flow 连续合并，只允许同一 native block 的来源行证据，
  且该类文本通常已经在 atom 阶段完成组合。

这样不会因为两个 atom 被分配到同一列或同一候选槽位就自动合并。`merge_column_continuations()`
仍只负责将已标注列的 atom 转成候选 Cell，不承担跨行文本拼接。

### 5. 下游结构保持不变

两种模式均继续经过：

```text
native spans
  -> 输出模式判定
  -> 同视觉行 span 组合
  -> 模式限定的 atom 组合
  -> 列带推断与列标注
  -> 物理行、物理 Cell
  -> 同槽位片段组合
  -> 模式限定的多行 Cell 合并
  -> 逻辑网格、表头跨度、空槽位物化
  -> occupancy 检查与项目 Cell
```

每次跨度调整后仍执行 occupancy 检查。任何冲突结果都不得进入最终表格。

## 测试设计

实现前先增加最小失败测试，并确认测试因缺少新模式行为而失败。

### 模式判定

- 构造 `左1、左2、左3、右1、右2、右3` 的 native 顺序，验证判为
  `columnar`。
- 构造 `左1、右1、左2、右2` 的 native 顺序，验证判为
  `row_interleaved`。
- 构造单列或证据不足的输入，验证不会错误进入列连续模式。

### atom 合并

- 591 页式输入验证相邻独立左列项目保持独立，不出现一个覆盖多条记录的巨大 atom。
- 同一 native block 的两条相邻 source line 验证合并为一个带换行文本。
- 不同 native block 即使 x 相同、y 相邻、flow 连续，也验证保持独立。
- 既有同视觉行组合、数字/占位符分离、字体和表头间距反例继续通过。

### Cell 与网格

- `columnar` 模式下验证跨 block 的 `merge_multiline_cells()` 不合并。
- 保留 `row_interleaved` 下已有换行字段和独立记录测试。
- 验证空槽位仍逐格物化，所有逻辑槽位恰好由一个 Cell 占用，且没有 occupancy 冲突。
- 运行相关无线结构、recoverer、hybrid body 和表格提取测试。

## 页面级验收

使用源文件 `fix/zh_all_table_pages.pdf` 的页索引 `591`，重跑到新的独立目录：

```text
output/fix_full_rerun_current_20260902_page591_output_order/
```

核对：

- 页面仍走 `zh`/native-span 路径，不调用 page words 重建；
- 目标表格不再把左侧项目列串成一个巨大 Cell；
- 结构化结果中的表格数量、source、行列数、Cell 文本和 bbox 合理；
- 左列连续项目各自归入正确视觉行，右侧表头和金额文本不漏失；
- 同一 native block 的真实换行仍是同一逻辑 Cell；
- 空槽位、跨度和 occupancy 无冲突；
- 最终 PNG 的表格边界、行列线框和相邻区域没有误并。

## 影响文件与交付记录

预计修改：

- `src/hexai_pdf_parser/tables/wireless_table_recovery.py`：保存 native block/line 来源；
- `src/hexai_pdf_parser/tables/wireless_structure/span_chain.py`：传播来源并标记来源可靠性；
- `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py`：输出模式判定和模式化 atom 合并；
- `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py`：限制列连续模式下的跨 block 合并；
- `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`：传递区域输出模式；
- 相关测试文件；
- `changes.md`：记录根因、判定条件、调用位置、不回读 words 约束、测试结果和页面输出路径。

不修改工作区中与本任务无关的已有改动。
