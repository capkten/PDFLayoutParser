# Sprint 006：Rust 无线结构列带、网格与表头拓扑迁移

> 日期：2026-09-22
> Worktree：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`
> 分支：`codex/rust-migration-replan`

## 当前阶段

Task 4A 已完成差分观测基础设施。当前只证明 Python oracle 与 Rust helper 可以在同一 owned atom/band/region 输入上按字段比较；尚未宣称 column/grid/header parity。

## 夹具范围

`tests/fixtures/rust_migration/wireless/wireless_structure_differential.json` 固定以下形态：

- paired-CJK artifact 与 sparse alignment artifact；
- header-only note/leaf rescue；
- 近中心但不同物理行、left-shifted CJK continuation；
- 独立 leaf、完整/不完整二叶子父表头；
- 空覆盖 rowspan、非空标题阻断 rowspan；
- occupancy conflict、越界和独立空槽位。

## 运行记录

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_wireless_structure_differential.py
10 passed in 0.65s
```

`git diff --check` 在提交前执行；Rust 生产实现和 route 尚未修改。

## Task 4A re-review handoff

最终 focused differential contract 为 10 个测试，覆盖 14 个 fixture。ledger 现在直接覆盖 normalized `source-reference`，并以 exact expected mismatch/category 集合加显式 allowed additions 防止 wildcard 漂移。Rust normalized-output 的 duplicate、out-of-range、uncovered-slot 和 ownership mismatch 必须返回独立 rejection contract；预期 Rust/Python mismatch 仍保留在 ledger 中供后续迁移观察。

适配边界已明确：Rust adapter 继续消费 fixture-owned raw atoms/bands；Python 侧负责 prune/refine/rescue，Rust 侧仍记录为 `rust_no_binding_for_python_band_prune_refine_rescue`，因此 4A 不宣称 column/grid/header parity。Task 4B 接手 raw-input 到 prepared-band 的适配；Task 4C 接手 physical/logical occupancy contract；Task 4D 接手 header span 与 empty-slot materialization。后续每个 slice 继续复用 source-reference、rejection contract 和 fixture 闭合集合。

## 下一步

1. Task 4B：迁移 owned-input 的列带 refine/rescue、header cutoff 与 geometry-based annotation。
2. Task 4C：迁移 physical row/grid、column span 和 occupancy contract。
3. Task 4D：迁移 logical row/header-span transaction 与 empty-slot materialization。

每个 bounded slice 都必须先 RED、再 GREEN，并由独立 `gpt-5.6-luna` reviewer 给出 Spec Compliance 与 Task quality 结论。默认 Python route、shadow route 和 fallback policy 保持不变。

## Task 4B 完成记录（2026-09-22）

Task 4B 已接入 Rust owned atom/band 的列带准备：paired-CJK 与 sparse-alignment 伪列裁剪、正文数值轨道和最低表头子列 refine、header cutoff、稀疏正文 rescue，以及保守的 header-only rescue。`recover_native_region` 先执行 prepared-band 阶段，再进入既有 grid/occupancy 流程；默认 Python route、shadow route、Snapshot capture 和 fallback policy 未改动。

TDD RED：新增 `test_refine_leaf_bands_splits_independent_body_tracks` 在旧 stub 上失败，输出 `left: 1, right: 2`。GREEN：focused Rust module suite `22 passed`；focused differential/columns/header suite `72 passed`。paired-CJK 与 sparse-alignment 的 bands presence mismatch 已消除，其余未迁移逻辑差异继续按 `requires_adaptation`、`defect`、`unsupported` ledger 分类保留。Task 4B 不宣称页面级 JSON/PNG parity。

## Task 4C 完成记录（2026-09-22）

Task 4C 接入 physical grid 与 occupancy contract：行聚类使用 median positive height 和垂直 overlap；左移 CJK continuation 只有 source refs 连续、向下移动、CJK-only、左移和宽字段几何证据完整时才允许进入同一物理行；有效 `col_hint` 优先于宽 bbox 推断；source-contiguous inline fragment 合并后重新计算 occupancy diagnostic；负索引和超出推断网格的 physical Cell 生成显式 `occupancy_out_of_bounds` diagnostic，不再静默跳过。

TDD 接手时的 RED 为 `25 passed; 2 failed`，失败分别是左移 continuation 正例和合法 same-slot fragment 被 stale occupancy diagnostic 误报。修复后的验证结果为：`cargo test --lib wireless_structure` 为 `27 passed`；differential/grid/recoverer focused pytest 为 `49 passed`；`git diff --check` 通过。Task 4C 仍不宣称页面级 JSON/PNG parity；Task 4D 接手 logical row/header-span transaction 和最终逻辑槽位合同。
