# 中文无线表格规则候选召回信号设计

## 背景与根因

`TableExtractor._detect_rule_candidates()` 的职责是筛选“值得交给模型的页面”，不是确定最终表格区域。当前实现对中文和混合页面依赖 native-span 无线恢复结果作为文本候选；只有恢复出可信 `Table` 时，候选页才会进入模型阶段。

页面索引 `983` 的实际内容包含两张上下排列的无线表格。该页被识别为 `mixed`，因此不会进入英文 zebra 分支；有线检测只得到横线、没有竖线，也不会产生有线候选。native-span 数据中，公司名称的换行片段形成单列 visual row，六个金额形成另一条 visual row，两者中心线相差约 `6.7` 至 `7.0pt`，超过当前行聚类容差。由于 `_table_runs()` 要求连续的多列 visual row，金额行被单列公司名行打断，最终所有结构恢复分支都为空，候选页提前返回，模型没有机会执行。

## 目标与边界

- 补充中文/混合页面的低成本页面级 native-span 召回信号，至少召回页面 `983` 这种“首列换行、数值行独立”的无线表格。
- 保留现有流程：规则候选页筛选 -> 候选页调用模型 -> 模型框精确定位 -> 区域级 native-span 结构恢复。
- 规则信号只用于门控，不重建最终表格区域、单元格、跨度或业务字段。
- 不调用 `page.get_text("words")`，不进入 `extract_zebra()`，不回退到 legacy 文本重建。
- 不改变模型初始化、模型推理范围、模型失败处理或最终表格来源。

允许候选阶段为了提高召回而增加少量模型调用；候选信号不追求表格边界精度，最终边界仍由模型决定。

## 方案

### 1. 在 native-span 恢复中计算独立页面信号

在 `wireless_table_recovery.py` 中复用当前已经完成的 native span -> text strip 流程，在构造最终 `Table` 之前增加一个只读的页面信号计算。信号只消费 `TextStrip` 的文本和几何，不消费最终 Cell，也不改变 `_table_runs()` 或其他结构恢复判定。

信号判定条件如下：

1. 按 native strip 的纵向几何聚类出数值 visual row；每条数值行至少包含 `4` 个可解析数字。
2. 使用数值 strip 的右边界作为列锚点，在有限的几何容差内聚合锚点；至少 `4` 个列锚点得到不少于 `3` 条数值行的支持。
3. 至少 `3` 条数值行能够映射到不少于 `4` 个稳定列锚点。
4. 左侧相邻的单列文本 strip 作为辅助证据和信号 bbox 扩展依据，允许它位于金额行的上方或下方，以覆盖首列换行；它不是硬门槛，避免无标签的纯数值表被漏掉。

数值列的锚点容差采用字号/数值宽度和固定上限共同约束，足以吸收同一物理列中数字长度变化以及页面 `983` 两张表之间的小幅列偏移，但不会跨越相邻列。检测只返回是否命中及证据 bbox、数值行数、稳定列数等诊断信息，不生成候选表格结构。

### 2. 将信号转换为候选页标记

`recover_wireless_tables()` 将页面信号写入已有 diagnostics。`TableExtractor._detect_rule_candidates()` 在中文或混合页面的文本对齐恢复没有返回表格、但 diagnostics 表明页面信号命中时，追加一个仅用于门控的标记：

```python
Table(
    bbox=signal_bbox,
    rows=0,
    cols=0,
    cells=[],
    source="wireless_page_signal",
)
```

`extract()` 保持现有早返回逻辑：候选列表非空才调用模型。`_extract_model_tables()` 只把 `source == "line_projection"` 的候选当作有线结果，因此 `wireless_page_signal` 不会泄漏到最终输出，也不会参与有线表格优先级处理。

候选阶段继续尊重已有的 `allowed_regions` 和 `excluded_regions`；被排除区域内的 native span 不得单独触发页面信号。英文页面保持现有 zebra/英文文本策略，不由本次中文页面信号改变行为。

### 3. 诊断与异常处理

页面信号证据写入无线恢复 diagnostics，至少包含 `matched`、`bbox`、`numeric_row_count`、`stable_column_count` 和 `labeled_row_count`。native span 读取或几何数据异常时，信号视为未命中，沿用当前空候选行为；不得因为信号计算异常绕过候选门控或直接调用模型。

## 测试设计

- **目标正例**：构造首列文本位于数值行附近且可换行、连续出现六列数字的 native-span 页面；确认页面信号命中，并确认 `TableExtractor.extract()` 在候选标记存在时调用模型。
- **目标页面回归**：对 `fix/zh_all_table_pages.pdf` 的 0-based 页面索引 `983` 检查候选不为空，模型被调用；页面级输出继续由模型框产生两张 `wireless_span_recovery` 表。
- **普通正文反例**：数字行少于四列、稳定列支持不足或数字锚点不稳定的正文不产生页面信号。
- **边界回归**：已有有线候选、英文页面、排除区域和中文 native-span 结构恢复测试保持通过；测试明确不请求 `words`。

## 验收标准

1. 页面 `983` 不再因 `_table_runs()` 为空而在模型前被丢弃。
2. 现有规则候选 -> 模型精确检测 -> native-span 区域恢复的 pipeline 不变。
3. `wireless_page_signal` 只存在于候选阶段，最终表格的 `source`、bbox、行列和 Cell 仍来自模型框后的结构恢复。
4. 新增测试先在旧实现上失败，再在最小实现后通过；相关测试、页面独立输出和最终 PNG 均完成核对。
