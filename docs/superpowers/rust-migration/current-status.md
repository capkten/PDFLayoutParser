# Rust 迁移当前状态与新窗口交接

> 更新时间：2026-09-23
> 本文是新窗口的第一入口；逐任务的完整证据仍以 `.superpowers/sdd/progress.md`、对应 report 和 sprint handoff 为准。

## 一句话结论

Python → Rust 的迁移已经完成 Rust 审计、计划重排、Python-derived `NativeRegionInput` 边界、Snapshot/strict-output 边界、span/text-run/atom 的字段级差分观测、Task 3B、Task 4A–4D，以及 Task 5/6 的页面验收与最终审计。Task 5/6 已完成交付闭环，但五个真实页面仍暴露 Rust page/region parity defects；默认生产路径继续保持 Python，不能切换 Rust primary。

## 2026-09-23 bounded follow-up

在 `C:\Users\23662\.codex\worktrees\task5-parity-repair\PDFLayoutParser-Fast` 的 `codex/task5-parity-repair` worktree 中继续执行了 Task 5 修复。该分支独立于上文记录的 dirty replan worktree；未提交、合并或切换默认路由。细节见[Task 5 问题审计](task5-problem-audit-2026-09-23.md)和[修复计划](../../plans/2026-09-23-rust-task5-parity-repair.md)。

最新五页结果在 `D:\codes\PDFLayoutParser\output\rust_migration_task5_tracks_20260923_r12\`：结构 mismatch `0`、routing diagnostic `12`；Python/Rust 表格数仍为 `2/2/2/2/4`，五页 overlay PNG 与 Python 及 r11 相同。结构相等仍由 fallback 后输出相同产生，不构成 Rust 独立 parity；Python page baseline 的 49 个 occupancy conflict 保留。focused pytest `188 passed`、`cargo test --lib` `63 passed`、`cargo check` 与 `git diff --check` 通过；全仓 `cargo fmt --all -- --check` 仍被既有 rustfmt 差异挡住，未做全仓格式化。未运行性能门禁，Rust primary 仍关闭。

本轮确认页 184 多出一条轨迹的直接原因：Python 保留原始 '----  ---------' separator span 为一个 strip，Rust `split_packed_numeric_span()` 将其按空格拆成两个 atom，令 x≈446 的片段与 x≈449 标签形成额外轨迹。现在纯 separator span 不再按 packed-number 规则拆分；完整页面候选在具有 `row_hint` 时改为 Python track-first 分配、spanning-row 和轨迹覆盖 colspan，region 路径仍使用原 band/grid。新增三轨迹但只有两条 overlap band 的宽字段 oracle 测试通过。真实页候选依然受 Python 候选本身的 occupancy conflict 限制：页 184 raw Rust 保留首张 4×5 候选，第二张 9×10 因 19 个冲突未进入结果并触发 fallback；固定五页 fallback 总数没有减少。

下一步先遵守明确的 occupancy 检查，不通过隐藏冲突降低 fallback；完成冲突兼容约定后，再继续处理 188/189 的候选分组与 region 路径差异。

## 工作区与权威入口

- Worktree：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`
- 分支：`codex/rust-migration-replan`
- 实现基线：`056856f`（已包含 Task 4A–4D 的列带、物理网格、逻辑行、表头跨度事务和空槽位物化实现）。
- 用户未提交改动，必须保留：
  - `tests/test_wireless_extractor_split.py`
  - `tests/test_wireless_structure_recoverer.py`
- 当前执行计划：[2026-09-21-rust-migration-replan.md](../plans/2026-09-21-rust-migration-replan.md)
- 任务账本：[.superpowers/sdd/progress.md](../../../.superpowers/sdd/progress.md)
- 最近 bounded slice 报告：[task-3b-atom-metadata-report.md](../../../.superpowers/sdd/task-3b-atom-metadata-report.md)
- Task 4D 报告：[task-4d-report.md](../../../.superpowers/sdd/task-4d-report.md)
- 最终 review package：[review-03d7da0..45fec29.diff](../../../.superpowers/sdd/review-03d7da0..45fec29.diff)
- Task 4C 报告：[task-4c-report.md](../../../.superpowers/sdd/task-4c-report.md)
- Task 5/6 sprint handoff：[sprint-007.md](sprints/sprint-007.md)
- Task 5/6 evaluation：[sprint-007.md](evaluations/sprint-007.md)
- Task 5 问题审计：[task5-problem-audit-2026-09-23.md](task5-problem-audit-2026-09-23.md)
- 页面验收输出：`D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`

## 已完成任务

### Task 0：Rust 审计与计划重排

已完成。审计确认现有 direct Snapshot Rust 重建器与 Python helper 链是两套算法，存在简化的 text-run/column/grid/header 规则和页面坐标阈值。Rust `refine_leaf_bands()` 本身有实现并由 `recover_native_region()` 调用；Task 5 活跃的 direct Snapshot route 绕过这条 helper 链，不能把“未接入”写成“函数 no-op”。因此 Rust 单测不能单独作为 Python page parity 证据。详见[Task 5 问题审计](task5-problem-audit-2026-09-23.md)。

### Task 1：Python-derived `NativeRegionInput` bridge

已完成并通过独立 Luna review。Python 在 capture 后生成拥有型 core DTO，保留必要的 source/evidence；Rust 边界严格校验 geometry、类型、引用和 evidence cardinality。未回读 `fitz.Page` 或 `page.get_text("words")`，没有接入 direct Snapshot parity route。

主要提交：`dd9c187`、`da6e400`、`ee91f55`、`803f673`、`1720ffb`。

### Task 2：Snapshot / strict-output 边界

已完成并通过独立 Luna review。显式 cell `rect`、可选 `page_y0`、未知字段拒绝、grid/occupancy 校验及 route fallback 已固定；这只代表边界合同通过，不代表无线结构算法 parity 已通过。

主要提交：`4362b59`、`b8224ce`、`a332661`。

### Task 3A：span/text-run/atom 字段级差分观测

已完成并通过独立 Luna review。差分 harness 使用同一 owned 输入比较 Python oracle 与 Rust helper，并按字段输出稳定 mismatch ledger；没有用 broad ignore 隐藏差异。

主要提交：`eee1685`、`fa1e574`、`70de696`。

- 稳定 mismatch ledger：`564` 条
- canonical digest：`5093640efdb9d73e66d6f8adacafc7f635c0e0eded129989677407083044ab59`
- 这 `564` 条是后续迁移输入，不是已接受的 parity，也不是允许忽略的差异。

### Task 3B-1：`TextRunDto` source/evidence 透传

实现已完成，范围仅限 text-run 的 owned evidence：

- 可选 `evidence` 包含 `schema_version`、`source_positions`、`fonts`、`sizes`、`flags`。
- `build_text_runs` 从实际参与 run 的 `NativeSpanDto` 按顺序生成 evidence。
- 校验 `span_refs` 与各 evidence 列表 cardinality、元素类型以及 `NaN/Inf` size。
- 没有 evidence 时旧 DTO 的字段形状和 digest 不变。
- 没有修改 `rust/wireless_structure.rs`、生产 Python、默认/shadow/fallback route、Task 3A fixture/normalizer 或用户 dirty 文件。

主要提交：`6c0e2b9`、`fa547c5`、`5829deb`。

最终独立复审已通过：`fa547c5..5829deb` 为 Spec Compliance ✅、Task quality ✅ Approved。3B-1 可以封存；下一个语义规则 slice 仍必须重新走独立 Luna review。

### Task 3B-WM：wrapped field merge

已完成并通过独立 Luna re-review。Rust `build_text_runs()` 现在在视觉行 run 构造之后，使用
过滤和 packed split 后按 source/fragment 顺序建立的私有 native-flow ordinal 执行 wrapped
chain merge；公开 `TextRunDto.order` 仍保持视觉输出顺序，`source_start/source_end` 仍表示
原始 source bounds。合并保留换行文本、union bbox、span refs、source/evidence，并保留
数字、占位符、字体/字号、几何、right witness 和 strong fallback veto。

主要提交：`3fc2844`、`23240f5`、`aee23c1`。

回归夹具覆盖 `vertical_wrapped_witness`、filtered-source-gap、witness 缺失、几何拒绝、
来源不连续、packed numeric、superscript 和独立字段反例。独立 Luna re-review 对
`3fc2844..aee23c1` 给出 Spec Compliance ✅、Task quality ✅ Approved，无 Critical、Important
或 Minor findings。

### Task 3B-AC：alignment corridor veto

已完成。Rust native span 的行内合并现在复现 Python alignment corridor 的判定顺序和
条件；三组以上稳定左右对齐列带且 corridor 足够宽时会拒绝误合并。该 slice 未修改
wrapped merge、`build_atoms` 后逻辑、column/grid/header 或 route。

主要提交：`7fb8ea0`。alignment 正例、support 控制和组合 differential 回归已通过独立
review；alignment semantic defect 已清零。

### Task 3B-PN：packed numeric span split

已完成并通过独立 Luna review。Rust 对 packed numeric span 进行与 Python oracle 对齐的
fragment split，保留 fragment 的 source/evidence 和顺序，不把独立字段重新合并。

主要提交：`02fac09`、`ad4e210`、`7a2fd10`。packed numeric semantic mismatch 已清零。

### Task 3B-SG：superscript inline gap

已完成并通过独立 Luna re-review。Rust 仅在字号和 inline x corridor 同时满足时合并
superscript；placeholder、numeric、垂直中心和 source continuity veto 保持有效。

主要提交：`dd5d7b9`、`3d5953d`。正例、字号阈值反例和 x corridor 反例均已覆盖。

### Task 3B-AM：atom metadata

已完成并通过最终独立 Luna review。`build_atoms()` 使用 source `span_refs`；atom `order`
优先使用 native `flow_start`，legacy run 才回退视觉 `run.order`；flow/source metadata
只有组成完整 bundle 时才输出，legacy DTO shape 保持不变。differential normalizer 现在
比较实际 atom order、flow/source bounds 和完整 source continuity metadata。

主要提交：`d7a195b`、`03d7da0`、`45fec29`。最终 reviewer 对
`03d7da0..45fec29` 报告无 Critical、Important 或 Minor，结论为 Ready to merge。

### Task 3B 总结

Task 3B 的全部 bounded slices 已完成：alignment corridor、packed numeric、superscript
inline gap、wrapped merge 和 atom metadata。span/text-run/atom 层未回读 `fitz.Page` 或
`page.get_text("words")`，未修改 column/grid/header/route。最终 ledger 为 `111` 条，
分类为 `defect=8`、`requires_adaptation=15`、`unsupported=88`，SHA256 为
`cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81`。

### Task 4A / 4B / 4C / 4D：column bands、logical grid 与 header topology

Task 4A owned-input differential harness、Task 4B Rust 列带 refine/rescue、Task 4C physical row/grid/occupancy 和 Task 4D logical row/header-span transaction 已完成。Task 4D 依据 native continuation 所有权压缩逻辑行；完整且连续的二叶子拓扑才恢复 `colspan=2`，非空标题阻断 `rowspan`，跨度 proposal 冲突时回滚，并将每个未覆盖逻辑槽位物化为独立空 Cell。Task 4D focused 验证为 Python `102 passed`、Rust `31 passed`。页面级 JSON/PNG 验收已在 Task 5 完成。

### Task 5：双路 shadow 与真实页面验收

已完成。新增字段级 normalizer、三模式 runner 和五页 JSON/PNG 输出，覆盖 `recover_wireless_tables()` 与 `recover_cells_from_region()`。输入为 `zh_all_table_pages.pdf` 的 0-based `184,188,189,191,192`，输出目录为 `D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`。三个 manifest 均有五页且输入 SHA256 一致；shadow 结构化结果与 Python 语义结果一致，17 条 Rust 观测诊断完整保留。

comparison 报告共有 `2894` 条记录：`2874` 条结构字段差异（regions 2241、tables 632、table_count 1）及 `20` 条 routing diagnostics（shadow 17、Rust fallback 3）；均被分类，`unclassified_count=0`，但不是 2894 个独立根因。Rust page route 在 188、189 页产生真实结构差异；184、191、192 页因 occupancy conflict 触发既有 Python fallback。固定 Python table bbox 的 Rust region route 在五页均有字段差异。Python page-level baseline 自身累计 49 个 table occupancy conflict、region occupancy conflict 为 0；该基线问题已记录。视觉核验已覆盖五页 Python/Rust overlay，188、189 的 Rust 边界/行列切分差异与 JSON 一致。完整清单见[Task 5 问题审计](task5-problem-audit-2026-09-23.md)。

### Task 6：最终审计与交付门禁

已完成审计和回归矩阵：Task 5 focused `8 passed`，组合迁移矩阵 `140 passed`，`cargo test --lib` `60 passed`，`cargo check` 和 `git diff --check` 通过。Task 6 的交付结论为“验收闭环完成，Rust primary 未通过”：默认 route 保持 Python，shadow 继续观测，Rust fallback/diagnostic 保持；后续若切换 primary，必须逐项修复 sprint-007 evaluation 中的 defect 并重新生成独立页面输出。

## 当前门禁与已知限制

- 默认 route 仍返回 Python 结果。
- `shadow` 仍返回 Python 结果，只记录 Rust 观测。
- Rust DTO 解析、输出验证或 Rust 运行异常继续走 Python fallback，并保留 `rust_fallback` diagnostic。
- capture 之后结构恢复只消费 `PageSnapshot`、owned DTO、atom、band、grid、cell；不得持有 `fitz.Page`，不得以 `page.get_text("words")` 重新读取中文/混合无线表格文字。
- 中文/混合无线不回退 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或 page words 二次重建。
- 不得用放宽容差、业务标题特判、fallback bbox、`max(1, span)` 或吞掉 occupancy conflict 制造 parity。
- `cargo fmt --check` 当前仍受本 slice 之前的跨文件格式差异影响；不要为了“变绿”格式化整个仓库或修改禁止文件。该问题应单独治理。

## 下一窗口的唯一正确起点

1. 先阅读本文件、`progress.md`、`task-3b-atom-metadata-report.md` 和最终 review package，再查看 `git status`；不要重做 Task 0–3A 或已批准的 Task 3B slices。
2. Task 3B 的所有 bounded slices 已完成并独立复审，不要重复派发；Task 4A、4B 已完成，Task 4C 已本地验证，不要重复实现这些 slices。
3. Task 5/6 已封存；如继续工作，应从 comparison.json 中的 defect ledger 逐项修复，不要重复搭建验收脚本。
4. 不切换默认 Rust route，不宣称中文/混合无线 Rust parity 完成；当前页面 defect 是真实迁移输入，不是可忽略差异。
5. 保持用户 dirty 测试文件不提交；新修复必须新建隔离分支/worktree，并在新的独立输出目录重跑 JSON/PNG。

## 最近 slice 验证证据

Task 3B superscript inline gap 的独立 review 已通过，提交为 `dd5d7b9`、`3d5953d`：

- `maturin develop --release` 成功重建当前 Python binding。
- superscript focused：`3 passed`；differential/text-runs：`59 passed`。
- packed numeric 回归：`20 passed`；`cargo test --lib native_span`：`4 passed`。
- `git diff --check`：通过；普通 numeric join 与 packed fragment evidence 保持。
- reviewer verdict：Spec compliant，Task quality Approved，无 Critical/Important/Minor。

Task 3B wrapped merge 的独立 re-review 已通过，提交为 `aee23c1`：

- fresh `maturin develop --release` 成功；环境仅报告既有 invalid distribution `~ydantic` 警告。
- wrapped focused：`5 passed`；组合 differential/text-runs/packed numeric：`84 passed`。
- `cargo test --lib native_span`：`4 passed`；`git diff --check`：通过。
- ledger：`364` 条，digest `8358c75e03dc5e12086127a75cc9b4ed94e7d829ea63ccefc0f06ac09d701fcc`。
- reviewer verdict：Spec compliant，Task quality Approved，无 Critical/Important/Minor。

Task 3B atom metadata 的最终独立 review 已通过，review package 为
`review-03d7da0..45fec29.diff`：

- 目标 differential：`26 passed`；专项 ledger、separator audit 和 hash-seed 稳定性：`5 passed`。
- `cargo test --lib native_span`：`4 passed`；`git diff --check`：通过。
- ledger：`111` 条，SHA256 `cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81`。
- reviewer verdict：无 Critical、Important 或 Minor，`Ready to merge: Yes`。
- 页面级 PDF JSON/PNG 未重跑；该限制已记录在 report，并不属于本 bounded slice 的 blocker。

## 前置 slice 验证证据

Task 3B-1 的报告记录了以下结果：

- evidence + legacy-shape focused pytest：`28 passed`
- `cargo test --lib native_span`：`4 passed`
- Task 3A differential：`11 passed`
- 相关 text-run/columns Python 回归：`54 passed`
- `git diff --check`：通过

下一窗口每次修改后都要重新运行覆盖该 slice 的 focused tests；最终声明任何任务完成前，必须补 fresh verification，并在对应 report/ledger 写入命令、完整计数和 verdict。

## Task 5 follow-up（2026-09-23）

- Rust NativeRegion 对非空 `bands` 不再重复 refine/rescue；这些是 Python preparation 已完成后的最终列带。页 188 两个真实区域现由 Rust 独立输出，逐字段匹配 Python，且无 occupancy diagnostics。
- 页面候选 track-first 按 Python `_split_wide_field_strip()` 条件拆分宽字段临时片段；不是冒号字段、片段数不匹配轨迹数或不足三个分隔空白时保留原 atom。
- r14 五页结构比较 0 diff，10 条 routing diagnostics 全是 page route 的 occupancy fallback；region route 在五页都没有 fallback。PNG 哈希三种模式逐页相同。page-level Python/Rust parity 仍未通过，Python occupancy 合同待用户确认，Rust primary 维持关闭。
- 最近验证：focused pytest 190 passed；`cargo test --lib` 64 passed；release binding 构建通过。未做 benchmark。
