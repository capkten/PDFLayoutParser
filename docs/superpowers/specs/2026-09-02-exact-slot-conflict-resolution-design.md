# 中文无线表格完全同槽位冲突兜底合并设计

## 背景与根因

`fix/zh_all_table_pages.pdf` 页索引 `185` 的目标无线表格已被模型正确检测。地址字段已经在 span 到 atom 阶段组合为 `清远市新城B30号开发用土地`，当前漏表来自汇总行的物理占位冲突：

- `合` 与 `计` 是同一 native block、同一 native line 中 flow 连续的两个单字 span；
- 两者字体大小均为 `10.5pt`，视觉上处于同一行，并被 `build_grid()` 分配到完全相同的 `R3C1`；
- 两者水平间距为 `26.2804pt`；
- `_same_native_inline()` 的上限为 `7.875pt`，`_same_slot_single_cjk()` 的通用上限为 `22.05pt`，所以现有 `merge_same_slot_fragments()` 不合并；
- 普通无线恢复和 hybrid 恢复随后只检查 occupancy conflict 并返回空表，没有在确认冲突后重新尝试有证据的组合。

因此，根因不是模型漏检，也不是行列分配错误，而是现有预防性合并规则受正常字距上限约束，同时恢复链缺少一个只针对已确认冲突的保守兜底步骤。

## 目标

1. 新增独立函数 `resolve_exact_slot_conflicts(cells)`，处理普通同槽位合并后仍存在的、完全相同槽位的冲突。
2. 只组合来源连续性和视觉证据完整的分散单字 CJK 链，不通过扩大通用字距阈值修复个别文字。
3. 组合后重新执行一次 `build_grid()`，使合并 bbox 重新参与物理行划分和列槽映射。
4. 保持最终每个逻辑槽位恰好由一个 Cell 占用；兜底后仍有冲突时继续拒绝整张结构结果。

## 非目标

- 不修改 span 到 atom 的通用间距阈值，也不为“合计”等业务文字添加白名单。
- 不仅因为两个对象被分到同一槽位就组合任意文本。
- 不组合多字符独立字段、金额字段或来源位置未知的对象。
- 不处理槽位范围不同的 `rowspan/colspan` 部分重叠。
- 不回读 `page.get_text("words")`，不进入 zebra 或 legacy 二次重建路径。
- 不循环重建网格；本步骤最多触发一次重新划分。

## 函数职责与位置

在 `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 中新增：

```python
def resolve_exact_slot_conflicts(
    cells: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    ...
```

该函数只负责识别并组合可证明属于同一字段的完全同槽位冲突链。它不负责建立网格、不修改列带、不处理多行 Cell，也不决定最终表格是否有效。

返回值沿用现有 Cell 字典结构。调用者通过结果数量是否减少判断是否发生组合；函数不修改输入对象。

## 判定规则

先按 `(row_start, row_end, col_start, col_end)` 完全一致的槽位键分组。只有组内至少两个 Cell 时才进入判定。

一个冲突组必须同时满足以下条件才可组合：

1. 组内每个 Cell 的 `row_start/row_end/col_start/col_end` 完全相同。
2. 该槽位覆盖范围没有与任何不同槽位键的 Cell 重叠；如果还存在部分 `rowspan/colspan` 重叠，整组不处理。
3. 每个 Cell 均为单个 CJK 字符，不能是多字符标签、数字金额或标点占位符。
4. 每个 Cell 的 `source_position_known` 为真。
5. 按 `flow_start` 排序后，后一项的 `flow_start` 必须严格等于前一项的 `flow_end + 1`。
6. 全组来自同一 `source_blocks`，且每项均位于同一 native line，即 `source_line_start == source_line_end`，所有项的 line 值相同。
7. 全组处于同一视觉行：任意相邻项的中心 y 差不超过 `max(2.0, min_font_size * 0.35)`，且 bbox 的 `x0` 按 flow 严格递增，不发生反向穿插。
8. 字体层级兼容：`bold` 完全一致，`script` 均为 `cjk`，任意相邻项的字体大小差不超过 `max(0.5, min_font_size * 0.1)`。

满足以上条件后，不再检查水平 gap。原因是该函数只在物理网格已经证明这些单字争用同一完整槽位时运行，槽位冲突是比通用字距更强、但仍需来源证据约束的触发信号。

任一条件不成立时保持原 Cell 不变，由最终 occupancy 检查拒绝不确定结果，不能删除其中一个 Cell 或输出重叠表格。

## 合并结果

可组合冲突链按 native flow 顺序无分隔符拼接文本，并复用现有 `_merge_pair()` 逐项折叠，以统一维护：

- 联合 `bbox`；
- `flow_start/flow_end`；
- `span_refs`；
- `source_blocks` 和 `source_line_start/end`；
- `merged_from` 与 `cell_id`。

新合并类型记录为 `merge_kind="exact_slot_conflict"`，便于页面级诊断。

## 调用流程

普通无线恢复和 hybrid 恢复采用相同的单次重建流程：

```text
build_grid(candidates, bands)
  -> merge_same_slot_fragments(grid_cells)
  -> 若仍有 occupancy conflict：
       resolve_exact_slot_conflicts(cells)
       -> 若数量减少：build_grid(resolved_cells, bands) 重新划分一次
       -> 再执行 merge_same_slot_fragments()
  -> merge_multiline_cells()
  -> occupancy conflict 检查
  -> logical grid / span / empty-cell 流程
```

初次普通合并后无冲突时，不调用兜底，也不重建网格。兜底未发生组合时直接沿用现有流程，并在最终检查处拒绝冲突。兜底发生组合时只重建一次，重建后不递归调用兜底。

重建使用合并后的 native-span Cell 字典和既有列带，不读取 page words。`build_grid()` 返回的新 `physical_rows` 和 `columns` 替换旧值，保证后续逻辑网格使用重新划分后的拓扑。

## 测试设计

测试先行，至少覆盖以下用例：

1. 正例：两个宽间距的 `合`、`计` 被分到完全相同的 `1x1` 槽位，flow 连续、同 block/line、视觉同行，兜底组合为 `合计`，并记录 `exact_slot_conflict`。
2. 反例：两个完全同槽位的多字符独立字段保持分离。
3. 反例：单字 CJK 的 flow 不连续时保持分离。
4. 反例：单字 CJK 来自不同 native line 或来源位置未知时保持分离。
5. 反例：完全同槽位组同时与另一个不同跨度 Cell 部分重叠时不处理。
6. 集成正例：恢复器在兜底组合后重新调用 `build_grid()`，最终 occupancy 唯一并输出表格。
7. hybrid 既有独立同槽位字段和跨列重叠拒绝用例继续通过。
8. 既有 `merge_same_slot_fragments`、网格、逻辑网格、表头跨度和空槽物化测试继续通过。

## 页面级验收

使用 `D:/codes/PDFLayoutParser/fix/zh_all_table_pages.pdf` 页索引 `185`，重跑到新的独立输出目录，不覆盖既有结果。验收内容包括：

- 模型区域仍为目标表格区域，表格来源不变；
- 地址字段保持为 `清远市新城B30号开发用土地`；
- `合/计` 组合为 `合计`，不再产生 `R3C1` 冲突；
- 目标表恢复为 `3x3`，所有槽位 occupancy 唯一；
- 核对最终 PNG 的表格边界、行列线框、文字归属以及相邻内容未误并。

验证结果和新输出绝对路径记录到中文 `changes.md`。

## 失败处理

- 无法满足完整证据链：不组合，保留原冲突并拒绝结构结果。
- 合并后重新划分仍有任何 occupancy conflict：拒绝结构结果。
- 逻辑网格、表头跨度或空槽物化后出现冲突：沿用各阶段现有拒绝或事务回退规则，不因本兜底放宽最终不变量。
