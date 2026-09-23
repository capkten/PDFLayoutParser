# Task 5 Rust 页面 parity 问题审计

> 审计日期：2026-09-23
> 范围：Rust 无线表格 `recover_wireless_tables()` / `recover_cells_from_region()` 页面级与区域级差分；不实施算法修复。
> 验收输入：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`，SHA-256 `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`，0-based 页 `184, 188, 189, 191, 192`。
> 结果目录：`D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`。
> 代码基线：验收工件记录 commit `44be1efb16ba780540a5593f16173057ea70a89f`；审计 worktree 为 `2e9c792ad024f543ffee111a7e28a50b4d9ac99b`。两者间生产入口和 Rust 结构源码无差异。

## 结论

当前 Rust primary 不能放行。问题不是一个 `rowspan` 特例，而是 Task 5 的活跃 Rust Snapshot 路径与 Python oracle 的 helper 链是两套结构算法；五页的 region 路径全部有字段差异，page 路径三页因 occupancy conflict 回退到 Python、另两页直接输出不同的表格结构。

比较文件有 `2,894` 条记录，但这不是 2,894 个独立根因：其中 `2,874` 条是结构字段差异（`regions=2,241`、`tables=632`、`table_count=1`），另有 `20` 条 routing diagnostics（shadow `17`、Rust fallback `3`）。全部记录当前都标成 `defect`，`unclassified=0`；应按“结构差异”和“解释/回退诊断”分别理解。

## 真实页面结果

| 页（0-based） | Python 表格 rows×cols | Rust page 结果 | 结构差异记录 | routing diagnostics | 可见性/影响 |
|---|---|---|---:|---:|---|
| 184 | 4×5、9×10 | occupancy conflict 后 Python fallback | 687 | 4（3 shadow + 1 fallback） | page PNG 看起来相同是因为回退；region 路径仍不一致 |
| 188 | 5×8、21×8 | 8×3、11×4 | 1,083 | 3（shadow） | 表格范围、分组和行列拓扑不同；上方资本公积表未形成对应 Rust 候选 |
| 189 | 13×9、10×5 | 6×4、2×3、3×3 | 534 | 3（shadow） | 相邻区段被拆成不同 Rust table，边界和行列切分不同 |
| 191 | 17×8、6×6 | occupancy conflict 后 Python fallback | 64 | 4（3 shadow + 1 fallback） | page PNG 看起来相同是因为回退；region 路径仍不一致 |
| 192 | 2×4、2×3、4×8、7×5 | occupancy conflict 后 Python fallback | 506 | 6（5 shadow + 1 fallback） | page PNG 看起来相同是因为回退；region 路径仍不一致 |

所有五页的固定 Python table bbox 区域级 Rust 输出均与 Python 不一致。原始差异、Cell 字段和路由记录见 `comparison/comparison.json`；原始 JSON/PNG 分模式保存在上述结果目录。Python 页面级基线本身另有累计 `49` 个 cell occupancy conflict，而 region 入口为 `0`，因此 Python 是当前候选 oracle，但不是无缺陷的结构规范。

## 问题清单

### P1 — 活跃区域入口没有复用 Python-derived NativeRegionInput 路径

Python 路径从 `_prepare_native_region_from_snapshot()` 开始，依次构造 text runs、列带、refine/rescue、列标注和逻辑网格；但公开的 `recover_cells_from_region()` 在 Rust/shadow 模式直接调用 `rust_adapter.recover_cells_from_snapshot()`。PyO3 再直接进入 Rust `recover_cells_from_snapshot()`，从 Snapshot native spans 独立重建行、列和 Cell。

另一个 `NativeRegionInput` 桥（`_recover_native_region_from_snapshot_rust()` → `recover_native_region()`）没有接入这个公开 Rust 分支；当前调用点只在 helper 定义及专门测试中。于是 Task 4 已实现的 NativeRegion 列带/网格/header 逻辑并不等于 Task 5 实际验收的 direct Snapshot 算法。**这是五页区域差异的主要架构性风险；各页具体字段的单一算法根因仍需从 defect ledger 逐项定位，不能把所有差异归成一个规则。**

证据位置：[`recoverer.py`](../../../src/hexai_pdf_parser/tables/wireless_structure/recoverer.py#L431)、[`recoverer.py`](../../../src/hexai_pdf_parser/tables/wireless_structure/recoverer.py#L512)、[`recoverer.py`](../../../src/hexai_pdf_parser/tables/wireless_structure/recoverer.py#L617)、[`rust_adapter.py`](../../../src/hexai_pdf_parser/rust_adapter.py#L578)、[`rust/lib.rs`](../../../rust/lib.rs#L317)、[`rust/wireless_structure.rs`](../../../rust/wireless_structure.rs#L2807)。

### P2 — Page 路径要么回退，要么结构直接不同

- 184、191、192：Rust page recovery 因 occupancy conflict 抛出 `ValueError` 并走 Python fallback。最终 PNG 相同不构成 Rust parity 通过证据。
- 188、189：没有由该 fallback 掩盖的等价结果，Rust 输出行列数及 table 分组均与 Python 不同；PNG 已有核验，差异与结构 JSON 相符。
- 五页 region route 都不通过，即使某页 page route 视觉相同也不能代表该 region route 正确。

证据位置：[`sprint-007 evaluation`](evaluations/sprint-007.md)、结果目录 `rust/page-184.json` 等 JSON 与对应 `*-wireless.png`。

### P3 — 两行样例的 Rust 测试合同与 Python oracle 不一致

`header_body_start()` 对 `physical_rows <= 2` 直接返回 `physical_rows`，即把两行都划为 header；`recover_native_region()` 随后以该 cutoff 调用 vertical continuation merge，因此这个样例的 `项目\n名称` 得到 `rowspan=1`。现有 Rust DTO 测试却要求该 Cell 的 `rowspan=2`。本次在当前 worktree 重跑该测试，结果为 `1 failed`，实际 `(row=0,col=0,rowspan=1,colspan=1)`，测试期望 `(0,0,2,1)`。

重要限定：对该视觉布局构造的同一 `PageSnapshot` 调用 Python helper，结果是 `2×2`，四个独立 `1×1` Cell；Python 并不支持这条测试当前写下的 `rowspan=2` 期望。因此这是**已确认的 Rust 特殊规则 + 测试/基线合同冲突**，尚不能直接登记为“Rust 违背 Python parity”。修复前要先确定用户可观察语义，再调整测试或算法。

证据位置：[`rust/wireless_structure.rs`](../../../rust/wireless_structure.rs#L1835)、[`rust/wireless_structure.rs`](../../../rust/wireless_structure.rs#L3401)、[`test_pdf_fast_wireless_structure.py`](../../../tests/test_pdf_fast_wireless_structure.py#L147)。Python helper 当次探针输出：`2 rows × 2 cols`，四个 Cell 的跨度均为 `1×1`。

### P4 — 未接入的 NativeRegion 桥存在列 ID / 列索引语义错位

Python 列带 ID 从 `1` 开始，`annotate_columns()` 将该 ID 写入 atom `column_id`；DTO 转换又原值复制到 `col_hint`。Rust `build_grid()` 将 `col_hint` 当作从 `0` 开始的 `bands` 下标使用（若 dash assignment 没有先提供列）。两列时，ID `1` 会被解释成第二列，ID `2` 越界后改用 bbox 猜列。该桥若接入当前公开入口会有确定的错列风险。

这是独立于 P1 的**潜伏缺陷**，不是当前 Task 5 direct Snapshot route 产生五页差异的直接原因，也没有计入上述页面 mismatch。

证据位置：[`columns.py`](../../../src/hexai_pdf_parser/tables/wireless_structure/columns.py#L140)、[`header_topology.py`](../../../src/hexai_pdf_parser/tables/wireless_structure/header_topology.py#L1513)、[`recoverer.py`](../../../src/hexai_pdf_parser/tables/wireless_structure/recoverer.py#L327)、[`wireless_structure.rs`](../../../rust/wireless_structure.rs#L529)。

### P5 — mismatch 汇总把结构字段差异与 routing diagnostics 合在一个数里

`comparison.json` 的 2,894 条记录中，`2,874` 条来自 `regions/tables/table_count` 字段比较；`20` 条是路由诊断：shadow 17 条 Rust 观测/fallback 事件，Rust 3 条 page fallback。诊断揭示真实 Rust 问题，但它们不是另外 20 个独立 Cell/table 结构根因。报告虽然逐条有分类，单看 `mismatch_count` 或 `by_classification.defect` 会夸大“问题个数”。

建议后续报告分别输出：结构 diff 数、唯一 fixture/route 数、fallback/observer diagnostic 数；保留原始 ledger，不丢弃 diagnostics。

证据位置：[`run_task5_shadow_acceptance.py`](../../../scripts/run_task5_shadow_acceptance.py#L185)、`comparison/comparison.json` 的 `summary.by_mode` 与 `summary.by_classification`。

### P6 — 页面 Python baseline 自身有 occupancy 冲突

五页 Python page-level table cells 累计 49 个 occupancy conflicts，而 Python region recovery 为 0。此现象不应掩盖 Rust 的 parity 缺口，也不应未经决定就要求 Rust 复制 Python 的冲突状态。后续必须把“兼容旧 Python 输出”和“满足唯一槽位结构合同”区分记录；否则 oracle 会把已有 Python 缺陷固化为 Rust 目标。

证据位置：[`sprint-007 evaluation`](evaluations/sprint-007.md) 的结构化验收段和 comparison occupancy 字段。

### P7 — 活跃 region Rust binding 没有释放 Python GIL

`recover_cells_from_region()` 调用的 `recover_cells_from_snapshot_binding()` 在 PyO3 中直接执行 Rust 核心；相比之下，`recover_wireless_tables_binding()` 用 `py.allow_threads()` 包住核心调用。它不影响当前已测的单线程结构字段结果，但会限制 region route 并行运行时释放 GIL 的能力。Task 5 没有并发性能验收，需单独补测，不能沿用另一入口的 GIL 结论。

证据位置：[`rust/lib.rs`](../../../rust/lib.rs#L317)、[`rust/lib.rs`](../../../rust/lib.rs#L729)。

### P8 — 迁移状态文档有过期/不准确陈述

1. `sprints/sprint-012-final-evaluation.md` 声称所有模式 `differences_count=0`、Task 5/6 门禁全部完成；它引用的是较早的代表页集合和早期输出，不能证明当前 Task 5 五页 parity。当前权威页面结果是 `evaluations/sprint-007.md`。
2. 旧 `current-status.md` 把 `refine_leaf_bands()` 描述为 no-op。当前 Rust helper 有实际 refine/split 实现，并由 `recover_native_region()` 调用；真正的问题是 Task 5 活跃的 `recover_cells_from_snapshot()` 没有走这条 helper 链。该表述会把“调用路径未接入”误报为“函数未实现”。
3. “Task 5/6 完成”只表示页面验收设施、审计和文档闭环完成，不代表 Rust parity 或 Rust-primary 发布门禁通过。

本次已在 `current-status.md` 增加本审计链接、拆分 mismatch 计数并修正 `refine_leaf_bands()` 描述；Sprint 012 原始报告保留历史结果并加上适用范围提示。

## 本次验证边界

- 重跑两行 DTO 回归：`1 failed`，复现 `rowspan=1` 与测试期望 `rowspan=2` 的差异。
- 同输入 Python Snapshot helper：输出 `2×2`、四个 `1×1` Cell；证明当前 Python oracle 不支持该 test expectation。
- 页面级 `comparison.json`、manifest、JSON/PNG 均来自 Task 5 独立输出目录；生产源码从验收记录 commit `44be1ef` 到审计 HEAD 未改动。
- Task 5 报告中的 focused `8 passed`、迁移矩阵 `140 passed`、Rust lib `60 passed` 是既有验收记录，不是本次重新执行的结果；这些测试通过不覆盖上述真实页 parity。
- 仅修改迁移文档；未改 Rust/Python 算法、测试、路由、输出产物或用户 dirty worktree。

## 建议的后续顺序（本次不执行）

1. 先按 route/layer 整理 `comparison.json`，保留 diagnostics 但从结构 diff 总数中分离。
2. 明确 Task 5 公开 region route 的唯一结构入口；修复/验证列 ID 到零基索引映射后，再决定是否接入 NativeRegion bridge。不要假设“两份 Rust 算法等价”。
3. 以 188/189 的 table segmentation/grid 差异和 184/191/192 的 occupancy fallback 为独立 RED 用例，逐类缩小，不一次性把全部 2,874 条字段差异当成同一个 bug。
4. 对两行 `rowspan` 先确定兼容合同；不能只为了让当前 Rust-only expectation 变绿而改变所有两行表格。
5. 每个修复 slice 都用新的独立目录重跑对应真实页 JSON 与 PNG；只有五页无未接受结构差异、fallback 合同明确、文档/门禁一致后，才重新评估 Rust primary。
