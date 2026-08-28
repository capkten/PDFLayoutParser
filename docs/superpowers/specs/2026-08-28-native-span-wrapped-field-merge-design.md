# 中文无线表格换行字段合并设计

## 背景与根因

`output/zh_all_table_pages_rerun_20260827/tables/page-191.png` 下方表格中，`与本公司/关系`、`业务/性质`、`法定/代表人` 和 `本公司实/际控制人` 是同一字段的上下换行文本，但当前结果被恢复为不同逻辑行。

这些文本在 PDF native source 中分别满足同一 source line、flow 连续、横向重叠和紧密垂直间距。当前 `build_text_runs()` 只组合视觉同一行的 span，随后物理网格按全表 y 中心聚类。其他列的居中文本插入中间物理行后，目标文本分别落在 `R1/R3` 和 `R4/R6`。网格后的 `merge_multiline_cells()` 又要求物理行严格相邻，因此拒绝合并。

根因是同一字段的文字组合发生得过晚：来源连续性仍完整时没有在 span 到 atom 阶段完成组合，进入物理网格后再依赖行号补救。

## 目标

- 在 `build_text_runs()` 输出 atom 前组合具有完整来源和几何证据的上下换行字段。
- 让目标页面下方表格由错误的 `7x7` 恢复为 `3x7`，并保留 7 个叶子列。
- 保留独立字段和相邻数据行，不因同列、相近或候选槽位相同而误合并。
- 全程只消费 native span 及其派生数据，不调用 `page.get_text("words")`。

## 非目标

- 不放宽网格后 `merge_multiline_cells()` 的物理行相邻约束。
- 不修改 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或 page words 路径。
- 不引入业务文字白名单，不针对“与本公司”“法定代表人”等文本硬编码。
- 不重构列带、逻辑网格、rowspan/colspan 或空单元格物化流程。

## 方案

在 `wireless_structure/text_runs.py` 内增加一个保守的换行字段组合步骤。现有同视觉行 span 组合完成后、atom 返回给列带推断前，对按 native flow 排序的相邻 run 做判定。

一对 run 只有同时满足以下条件才组合：

1. 来源连续：属于同一 native block 和 source line，且后一个 run 的 `flow_start` 等于前一个 run 的 `flow_end + 1`。
2. 文本兼容：脚本类型一致，字体和粗体属性一致；纯数值/占位符组合不参与该合并。
3. 几何连续：后一个 run 位于前一个下方，横向重叠至少达到较窄 run 宽度的 45%，垂直间距不超过字体大小与既有紧密间距阈值的上限。
4. 交错行证据：两个 run 的垂直中心之间存在其他 run，且这些中间 run 与目标字段的横向区域不形成竞争性重叠。这表明目标列是上下换行，而其他列文字在字段整体高度内居中。
5. 唯一性：前后 run 均不能同时与另一个候选形成同等有效组合；证据不唯一时拒绝合并。

组合后的 atom：

- 文本按 native flow 使用换行符连接。
- bbox 取来源 run 的联合区域。
- `span_refs`、flow 范围、source line 范围和字符框完整保留。
- `merge_kind` 标记为换行字段组合，供测试和诊断识别。

该步骤仍属于 span 到 atom 的构造过程。后续列带、物理 Cell 和逻辑 Cell 只接收已经组合完成的 atom。

## 数据流

```text
native spans
  -> 同视觉行 span 组合
  -> 基于来源连续性和交错行证据组合换行字段
  -> atoms
  -> 列带与列标注
  -> 物理网格
  -> 逻辑网格、跨度恢复、空槽位物化
```

目标页面中，四组上下文本组合后的中心 y 将分别与原先位于中间的表头或数据文字对齐，因此物理网格不再产生两条额外伪行。

## 拒绝条件

以下情况必须保持独立：

- native flow 不连续，或来源 block/source line 不同。
- 仅因为两个文本位于同一列或同一候选槽位。
- 两个纯数字、金额、比例或占位符位于相邻数据行。
- 中间没有其他列的交错文字，无法证明这是单元格内部换行。
- 横向重叠不足、垂直间距过大、字体/粗体或脚本不兼容。
- 一个 run 对应多个同等候选，来源连续性不能唯一确定。

## 测试设计

### 正例

- 在 `tests/test_wireless_structure_text_runs.py` 构造与页面 191 一致的交错布局，验证四组文本在 `build_text_runs()` 内组合，并检查文本、bbox、flow、span_refs 和 `merge_kind`。
- 在 `tests/test_wireless_structure_recoverer.py` 构造 7 列、两层表头和两条数据记录，验证最终结构为 `3x7`，四组文本各自只占一个 `1x1` Cell，且 occupancy 无冲突。

### 反例

- 构造同列、native flow 连续、间距相近但没有交错行证据的两条独立记录，验证不合并。
- 保留并运行既有“独立表头字段不因间距相近而连接”、数字/占位符、列带和 occupancy 测试。

## 页面级验证

使用 `fix/zh_all_table_pages.pdf` 的页面索引 `191` 重跑到新的独立目录，例如：

```text
output/page_191_wrapped_field_merge_20260828/
```

核对项目：

- 页面语言仍走 `zh`/native-span 路径。
- 页面表格数量和相邻表格边界不变。
- 下方目标表格 source 为 `wireless_span_recovery`，结构为 `3x7`。
- 四组换行文本各自成为一个 Cell；所有未覆盖槽位仍按 `1x1` 空 Cell 物化。
- occupancy 无冲突，组内/组间线框正确，相邻表格未误并。
- 最终 PNG 中不再出现由换行字段产生的伪水平分割线。

## 影响范围

生产代码仅修改 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py`。测试修改 `tests/test_wireless_structure_text_runs.py` 和必要的 `tests/test_wireless_structure_recoverer.py`。交付记录更新 `changes.md`，记录根因、判定条件、调用位置、不回读 words 的约束、测试结果和页面输出路径。
