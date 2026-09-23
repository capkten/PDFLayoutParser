# Task 4：列带、物理网格与表头拓扑迁移设计

> 日期：2026-09-22
> Worktree：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`
> 分支：`codex/rust-migration-replan`

## 目标

在 Task 3B 已完成的 `NativeRegionInput -> atom` 边界之后，把 Python 无线结构恢复链中的列带推断、物理行列网格、表头拓扑和空槽位物化迁移到 Rust，并以同一 owned input 的字段级 differential 固定行为。默认 Python 路由、shadow 返回 Python、Rust 异常 fallback 和 direct Snapshot 重建路径保持不变。

## 根因与范围

现有 `rust/wireless_structure.rs` 已有列带、网格和逻辑网格雏形，但与 Python helper 链并非同一算法：`refine_leaf_bands()` 仍是 no-op，行聚类和表头推断使用简化规则，跨度调整后的 occupancy 复核和空槽位表达也需要与 Python oracle 对齐。Task 4 只消费 `NativeRegionInput` 中的 owned atom、band、region 和 evidence，不持有 `fitz.Page`，不回读 `page.get_text("words")`，不调用 `extract_zebra()` 或 legacy `_rebuild_text_aligned_table()`。

本任务覆盖：

1. `infer_column_bands` 之后的 paired-CJK artifact、sparse alignment artifact、header-only leaf/note rescue 和 leaf-band refinement；
2. physical row clustering、column span、left-shifted CJK continuation、重复槽位冲突和基础网格输出；
3. header cutoff、二叶子父表头 `colspan=2`、完整拓扑拒绝规则、`rowspan` 的空覆盖条件、事务式 occupancy 检查；
4. logical grid 的空槽位物化与 normalized differential 输出。

不在本任务中做页面级 PDF JSON/PNG 验收、默认 Rust route 切换、性能优化或业务标题关键词特判；这些属于后续 Task 5/6。

## 设计与调用边界

Python oracle 的调用顺序保持为：

```text
NativeRegionInput
  -> atoms / bands
  -> prune + refine/rescue + annotate_columns
  -> merge_column_continuations
  -> build_grid
  -> merge_same_slot_fragments / merge_multiline_cells
  -> build_logical_grid
  -> merge_header_spans（事务式提交，冲突则保留基础网格）
  -> materialize_empty_cells
```

Rust 侧在 `rust/wireless_structure.rs` 内按相同阶段组织纯 owned helper。每个阶段只接收前一阶段的值并返回新的 owned 值；不得用动态 Python 字典、页面坐标常量或页面业务文字作为隐式输入。header cutoff 必须由 region/atom geometry 和已有 evidence 推导，禁止 `cy <= 686.0` 一类固定页面阈值。

## 不变量

- 每个逻辑槽位恰好由一个 Cell 占用；越界、重复占用和未覆盖槽位都显式检查。
- 所有跨度调整后都重新建立 occupancy；存在冲突时放弃整层表头推断，保留已验证的基础逻辑网格。
- `rowspan` 只能在物理行压缩生成逻辑网格之后恢复；父标题与叶子标题之间的覆盖槽位必须全部为空，存在非空标题时拒绝扩展。
- 空槽位是结构的一部分：未被跨度覆盖的每个槽位生成独立 `text=""`、`rowspan=1`、`colspan=1` Cell，不合并相邻空槽位。
- 不因同一候选槽位、相近 bbox 或相近中心点合并独立 atom；同一 cell 的文本组合必须来自前置 atom/run continuity。
- 二叶子父表头只有在同层父标题与下一层连续叶子标题形成完整、无重叠的 `1:2` 配对时才恢复 `colspan=2`；任一组不成立时放弃整层推断。
- 不修改用户已有的 `tests/test_wireless_extractor_split.py` 和 `tests/test_wireless_structure_recoverer.py` dirty 改动。

## 分阶段执行

### 4A：RED 与 normalized differential

新建 `tests/test_rust_wireless_structure_differential.py`，固定 Python oracle 与 Rust helper 的同一输入和字段级 normalizer。先覆盖 paired-CJK、sparse alignment、header-only rescue、row overlap、left-shifted continuation、独立 leaf、不完整二叶子配对、完整二叶子配对、rowspan 空覆盖和 occupancy conflict。每个新增行为先在当前实现上确认失败或确认 mismatch 被观察到。

### 4B：列带与 rescue/refine

在 Rust 中实现与 Python `columns.py`、`header_topology.py` 对齐的 geometry/topology 判定，保留 atom/source continuity 证据；不通过业务文本和页面常量猜列。验证 artifact 删除、header-only band 恢复、sparse body band 恢复以及稳定 band order。

### 4C：physical grid

对齐 Python `grid.py` 的 visual-row 聚类、同列互斥、left-shifted CJK continuation、column span 与重复 occupancy 检查。输出必须携带正确的 row/column edges 与 physical cell span，冲突不得被吞掉。

### 4D：header topology 与 logical grid

对齐 `header_topology.py`、`logical_grid.py` 和 recoverer 的事务式 header-span 提交。先生成基础 logical grid，再在副本上恢复 `rowspan/colspan`，复核 occupancy；失败时回退基础网格，最后只物化仍未覆盖的空槽位。

### 4E：集成证据

运行 Task 4 focused pytest、Rust wireless_structure unit tests、既有 wireless grid/header/recoverer 回归和 `git diff --check`。将 RED/GREEN 命令、计数、normalized mismatch 分类、未解决限制写入 `docs/superpowers/rust-migration/sprints/sprint-006.md` 与 `.superpowers/sdd/task-4-report.md`。Task 4 的结果只证明 owned-input helper parity，不宣称页面级 parity 或 Rust primary 可切换。

## 验收标准

- Task 4 differential 能按 rows、columns、cells、empty slots、rowspan、colspan、occupancy 和 diagnostics 定位差异。
- 目标正例与拒绝误合并反例均有回归测试，且测试先 RED 后 GREEN。
- Rust 输出与 Python normalized 结构对齐；每个逻辑槽位恰好一次占用，空槽位独立物化。
- 无 page words 回读、页面坐标阈值、业务标题硬编码、宽容度放宽或 silent conflict recovery。
- 独立 `gpt-5.6-luna` reviewer 对每个阶段给出 Spec Compliance 与 Task quality 结论；Critical/Important finding 修复并复审后才能结束 Task 4。
