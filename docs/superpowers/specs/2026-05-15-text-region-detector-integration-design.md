# Text Region Detector 接入设计

日期：2026-05-15

## 背景

当前的无线表格链路位于 `TableExtractor._extract_via_text_alignment()` 中，职责是混在一起的：

1. 从 `page.get_text("words")` 收集文本行
2. 发现疑似表格区域
3. 合并可能的表头 span
4. 裁掉不结构化的正文行
5. 推断列导线
6. 构建 `Cell` 和 `Table`

新的 `text_region_detector.py` 已经实现了一套更强的“区域发现”原型，但它目前还没有接入生产流程。这次改造的目标，是在**不改变有线表格主路径**、**不同时重写单元格构建逻辑**的前提下，把这套区域检测逻辑接入无线表格分支。

## 目标

把 `TableExtractor._extract_via_text_alignment()` 内部的无线表格流程，显式重构成两个阶段：

1. 区域发现
2. 区域内建格

第一步只替换第 1 个阶段，也就是“候选区域发现”这部分。后续已有的表头合并、trim、列导线推断和 cell 构建逻辑保持不变。

## 非目标

- 不修改 `pipeline.py` 的主流程边界
- 不修改线框表格提取路径
- 不修改 PyMuPDF fallback 路径
- 不修改 `LayoutBuilder` 的行为
- 不在这一步完整重写 `_extract_via_text_alignment()`
- 不让 `text_region_detector` 在这一步直接负责最终列结构或单元格构建

## 当前流程

目前无线表格相关流程如下：

```text
page.get_text("words")
-> _collect_text_rows(words)
-> _collect_text_candidate_regions(rows, page_bbox)
-> _merge_header_like_span(...)
-> _trim_span_to_structured_rows(...)
-> _infer_column_guides(region_rows)
-> token-to-column assignment
-> Cell / Table
```

本次设计要替换的是 `_collect_text_candidate_regions(...)` 这一段，其余后半段逻辑先保留。

## 设计方案

### 接入位置

接入保持在 `TableExtractor.extract()` 体系内，只修改 `_extract_via_text_alignment()` 的内部实现。`Pipeline.run()` 不需要改动，仍然像现在一样调用 `TableExtractor.extract()`。

### 新的内部边界

在 `table_extractor.py` 中引入一个新的辅助方法：

- `_detect_text_regions(rows, page) -> list[dict]`

这个方法作为 `table_extractor` 行结构与 `text_region_detector` 之间的适配层。

### `_detect_text_regions` 的职责

`_detect_text_regions(rows, page)` 负责：

1. 把 `_collect_text_rows()` 产出的行结构转换成 `text_region_detector` 所需的 row/fragment 结构
2. 在可行时，从页面中提取水平分隔线提示
3. 调用 `detect_candidate_regions(...)`
4. 把返回的 `CandidateRegion` 映射回 `table_extractor` 当前使用的原始 row dict
5. 返回与 `_extract_via_text_alignment()` 后续逻辑兼容的 region 记录

返回的 region 记录至少应包含：

- `rows`：检测命中的原始 row dict 对象列表
- `bbox`：这些行合并后的 bbox

这一步**不产出新的列结构**，也不负责最终表格建格。

## 详细数据流

接入后的无线表格流程如下：

```text
page.get_text("words")
-> _collect_text_rows(words)
-> _detect_text_regions(rows, page)
-> for each region:
   -> _merge_header_like_span(...)
   -> _trim_span_to_structured_rows(...)
   -> _infer_column_guides(region_rows)
   -> token-to-column assignment
   -> Cell / Table
```

这样可以保留现有列导线推断和 cell 构建语义，同时把“区域发现”明确拆成一个独立阶段。

## 适配层设计

### 行结构转换

`_collect_text_rows()` 已经返回了包含 token 列表和行 bbox 的 row dict。适配层应基于这些现有数据，构造 `text_region_detector` 需要的轻量 visual row。

每个 visual row 至少保留：

- 行 bbox
- token 文本
- token bbox
- token 在行内的顺序

同时，适配层必须维护一套稳定映射，使每个 visual row 都能对应回原始 row dict。这个映射是把 `CandidateRegion.rows` 还原成 `table_extractor` 行 span 的关键，不能再次依赖重新解析文本。

### 分隔线提示

如果成本合适，`_detect_text_regions()` 可以向 `detect_candidate_regions(...)` 传入水平分隔线提示。

但在第一步里，这个分隔线提取必须保持保守：

- 只使用强信号的水平视觉分隔线
- 不引入过于宽松或猜测性的 separator
- 如果无法稳定提取，就直接不传

区域检测逻辑必须在**没有 separator 提示**时仍然可用。

### 区域映射

`detect_candidate_regions(...)` 返回候选区域后，需要：

- 把 detector 的 rows 映射回原始 row dict
- 用映射后的原始行重新计算 region bbox，而不是使用扩张后的启发式 bbox
- 保持行顺序与 `_collect_text_rows()` 的原始顺序一致

这样可以避免后续逻辑处理“合成行”或“重排后的行”。

## 为什么这样设计

这个方案的优点是改动边界窄、可测试性强：

- `text_region_detector` 负责区域发现
- `table_extractor` 继续负责最终表格装配
- 有线表格路径不受影响
- ML 和 PyMuPDF 分支不受影响
- 现有无线表格后处理逻辑先不动

这是在当前阶段里，能真正把新模块接进来、同时又能保持重构风险可控的最小改动方案。

## 被否决的方案

### 方案 1：只在前序路径失败时才启用

否决原因：当前目标不是做一个窄 fallback，而是让 region detector 成为无线表格分支的默认入口。

### 方案 2：把 detector 藏进 `_collect_text_candidate_regions()`

否决原因：这样表面上接口不变，但会把新旧启发式继续混在一起，后续清理成本更高。

### 方案 3：一次性完整重写 `_extract_via_text_alignment()`

否决原因：第一步就同时动区域发现、列推断和 cell 构建，回归面会明显过大。应该先把区域边界稳定下来，再考虑后续阶段重构。

## 对有线表格的影响

这次改动**不应直接改变**有线表格提取路径，因为：

- 线框表格仍然优先执行
- PyMuPDF fallback 仍然独立执行
- 接入点仅位于 `_extract_via_text_alignment()` 内部

但仍有两类间接风险：

- region bbox 变化可能影响重叠去重
- region bbox 变化可能影响 `LayoutBuilder` 后续文本过滤范围

因此，这一步里 region bbox 必须严格基于命中行 union 计算，不能做额外扩边。

## 风险

### 行结构不一致

`text_region_detector` 使用的是 visual row / fragment 结构，`table_extractor` 当前使用的是 row dict / token dict 结构。如果适配不一致，可能出现“区域命中了，但无法稳定映射回原始行”的问题。

缓解方式：

- 建立一对一适配层
- 以原始 row dict 作为唯一真源
- 增加针对映射关系的测试

### 区域框过宽

如果检测出的 region 超出真实结构化行范围，后续版面合并时可能会错误吞掉正文文本。

缓解方式：

- region bbox 仅根据映射后的原始行计算
- 本步骤不做 bbox padding

### 无线表格行为漂移

候选区域选择变化，可能导致行 span 改变，进而影响列导线推断和最终 cell 分组。

缓解方式：

- 下游逻辑保持不变
- 用代表性的无线表格样例补足回归测试

## 测试策略

### 1. Region 适配层测试

围绕新的 `_detect_text_regions()` 增加测试，验证：

- detector 输出能映射回正确的原始 row span
- 映射后的行顺序保持不变
- 映射后的 bbox 等于原始行的 union bbox

### 2. 无线表格集成测试

在 `tests/test_table_extractor.py` 中新增或更新以下场景：

- 通用稀疏对齐文本表格
- 中文长财务表
- 表头 span 合并到主体
- 带 separator 的多段式表格区域

断言重点应放在最终 `rows/cols/cells` 和 cell 文本内容，而不只是中间 region 数量。

### 3. 误判保护测试

继续保留并补强以下场景：

- 正文中带重复数字
- 稠密叙述行
- 局部对齐但不应识别为表格的文本

### 4. 有线路径安全性测试

运行受影响的有线表格测试，确认把 detector 接入无线分支后，不会改变线框表格结果。

## 实现顺序

建议实现顺序如下：

1. 新增 `_detect_text_regions(rows, page)` 适配层
2. 把 `_extract_via_text_alignment()` 的候选区域生成替换为 `_detect_text_regions(...)`
3. 保留现有 header/trim/guide/cell 下游逻辑
4. 增加适配层测试
5. 更新无线表格回归测试
6. 运行受影响的 `pytest` 用例

## 后续演进

等这一步稳定后，可以再评估后续重构方向：

- 把更多表头处理逻辑前移到区域发现阶段
- 用更 region-aware 的方式替换 `_infer_column_guides()`
- 将 detector 特征作为最终表格接受度的置信度输入
- 逐步简化甚至移除旧的 `_collect_text_candidate_regions(...)`

## 成功标准

当满足以下条件时，可以认为这版设计达成目标：

- 每次进入 `_extract_via_text_alignment()`，都会让 `text_region_detector` 参与区域发现
- 有线表格路径行为保持不变
- 无线表格结构在代码上被明确拆分为“区域发现”和“区域内建格”
- 现有无线表格测试继续通过，或仅在新 region 边界明显更合理时更新预期
- 代码边界上形成清晰的职责分离：region discovery 负责找范围，table assembly 负责建格
