# 跨页无线表格续表候选切分修复设计

## 背景

目标个人信用报告中，机构查询记录表跨页延续。上一页已经输出编号 1--7，下一页应继续输出编号 8--19，但下一页的候选区域被切成三个 `3x4` 碎片，编号 8、9、12、13、16、17 落在候选框之外。碎片中还出现了机构名称的残留续写文字，被错误当成下一张表的表头。目标 PDF 共 2 页，问题页是 0-based 的第 1 页。

目标输入 PDF：

```text
D:\codes\PDFLayoutParser\个人信用报告\test\test\2_PDFsam_a1e4baf2-5f46-4f6b-865d-2d9240362880.pdf
```

问题输出目录：

```text
D:\codes\PDFLayoutParser\output\demo_personal_credit_test_20260918\2_PDFsam_a1e4baf2-5f46-4f6b-865d-2d9240362880
```

## 根因

当前无线表格候选生成路径为：

```text
native span -> TextStrip -> visual rows -> merge_wrapped_rows()
           -> _table_runs() -> _prepend_headers()
           -> _build_table() -> recover_wireless_tables()
```

机构名称的单行续写在 `merge_wrapped_rows()` 中同时满足以下两个几何条件：

- 与上一逻辑行已有字段列带水平重叠；
- 文本整体中心接近上一行的几何中心。

实现中“居中小标题”条件在续行判定中具有否决作用，因此即使文字实际属于上一行机构列，也会被保留为独立行。随后 `_table_runs()` 遇到该单字段行结束当前候选，`_prepend_headers()` 又将它错误补回后一个候选的开头。

直接把整张机构表区域交给 `recover_cells_from_region()` 可以恢复为 `12x4`、48 个 Cell，说明 native-span 网格恢复不是本次根因；必须在候选区域生成阶段修复。

## 目标

- 对属于上一逻辑行已有列带的单字段续写，优先执行续行合并。
- 保留真正位于列带之间、没有水平重叠的居中章节标题。
- 让目标续表在候选阶段保持为一个完整区域，编号 8--19 不丢失。
- 保持中文/混合页面的 native-span 路径，不回退到 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或 `page.get_text("words")` 二次重建。
- 不改变跨页面 `Table` 的页面级 bbox；跨页逻辑关联不在本次范围内。

## 非目标

- 不通过修改 `_prepend_headers()` 单独隐藏伪表头；这样不能找回已经落在候选区域外的记录。
- 不修改 native span 到 atom、列带、物理 Cell、逻辑 Cell、跨度恢复和空槽位物化算法。
- 不硬编码“机构查询”或其他业务文字。
- 不把相邻页面合并为一个跨页面几何表格，也不引入 `logical_table_id` 数据模型。

## 方案

在 `src/hexai_pdf_parser/tables/wireless_table_recovery.py` 的 `merge_wrapped_rows()` 中调整判定优先级：

1. 继续使用现有的 `aligned` 判定，检查当前单字段行是否与上一逻辑行任一已有字段的 x 区间相交（保留现有 8pt 几何容差）。
2. 只有在当前行不与上一行列带重叠时，才允许“整体居中”作为独立小标题的证据。
3. 当前行还必须满足既有的紧密垂直间距、稀疏行、非数字和非字段格式约束，才能合并为续行。
4. 对同时满足“单字段、列带重叠、几何上居中”的特殊续写，不把它作为同一视觉行中的第五个独立 `TextStrip`；将其文字、Span 来源和 bbox 并入水平重叠的上一行字段条。这样 `_column_tracks()` 仍看到原来的四个字段位置，不会把机构名称的续写片段推断成新列。

普通的非居中同列续行保持现有行为，仍以独立 `TextStrip` 追加到上一逻辑行；只有上述特殊续写采用字段条内合并。核心不变量是：**水平列带归属优先于整体几何居中；整体居中不能否决已经确认的列带重叠，也不能制造新的逻辑列。**

这个改动使机构名称续写和同一行的编号字段继续参与同一个 `_table_runs()` 候选。后续仍由 native-span `_build_table()`/`recover_wireless_tables()` 生成候选表格，不增加任何文字二次读取；独立的 `recover_cells_from_region()` 网格恢复路径保持不变。

## 数据流与错误边界

```text
native spans
  -> TextStrip
  -> visual rows
  -> 列带重叠优先的续行合并（必要时并入已有字段条）
  -> 连续候选区域
  -> native-span 候选表格构造
  -> 物理/逻辑 Cell、跨度与空槽位校验
```

如果续写行与上一行列带不重叠，或者垂直距离、文本类型不满足既有约束，则保留独立行。候选区域生成失败时不通过后处理伪造编号或扩大跨页面 bbox；测试必须暴露实际候选缺失。

## 测试设计

### 单元正例

- 构造上一行含机构名称列和编号列、下一行含居中但落入机构列的单字段续写，验证 `merge_wrapped_rows()` 将其合并。
- 验证该特殊续写并入对应字段条，而不是使视觉行出现第五个独立文本条；文本顺序、bbox 和所有来源 Span 均保留。
- 保留现有普通同列续行正例，验证非居中续写仍作为同一视觉行中的独立文本条处理。

### 单元反例

- 构造位于两列之间、与任一已有列带都不重叠的真正居中标题，验证仍保持独立。
- 继续覆盖现有数字行、字段行和普通同列续写测试，确保不放宽既有吸收条件。

### 目标 PDF 回归

- 在目标 PDF 的第 1 页（0-based）机构查询区域验证候选结果不再是三个 `3x4` 碎片，而是覆盖编号 8--19 的单一机构查询候选。
- 验证机构查询表最终为 `12x4`，编号 8--19 全部出现在结构化 Cell 文本中。
- 验证同页“本人查询记录明细”仍是独立表格，未被机构查询候选吸收。
- 验证每个逻辑槽位恰好由一个 Cell 占用，occupancy conflict 为 0，未引入空槽位异常。

## 页面级交付

修复后使用新的独立输出目录重跑目标 PDF，不覆盖已有诊断结果。核对：

- 页索引 1 与语言分类；
- 每页表格数量、`source`、行列数和 bbox；
- 异常页结构化 JSON；
- 异常页最终 PNG，重点检查表格边界、组内/组间线框、编号 8--19 和相邻本人查询表；
- 测试命令、通过/失败数量及任何与本次无关的既有环境失败。

`changes.md` 使用中文记录根因、判定条件、调用位置、native-span 不回读 words 的约束、测试结果和新输出路径。

## 影响文件

- 修改：`src/hexai_pdf_parser/tables/wireless_table_recovery.py`
- 修改：`tests/test_wireless_table_recovery.py`
- 修改：`changes.md`
- 不修改：`src/hexai_pdf_parser/tables/wireless_structure/` 下的 native-span 网格恢复实现
