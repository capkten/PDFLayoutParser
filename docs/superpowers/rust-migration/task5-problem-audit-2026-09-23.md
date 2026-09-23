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

### P6 — 低层 page helper 有 occupancy 冲突，不能等同于最终解析输出

五页低层 Python `recover_wireless_tables()` 候选表格累计 49 个重复逻辑槽位，而同页 `recover_cells_from_region()` 为 0。这是 helper 级诊断，不代表这些冲突会原样进入完整 `Pipeline` 输出；也不应未经决定就要求 Rust 复制冲突状态。

证据位置：[`sprint-007 evaluation`](evaluations/sprint-007.md) 的结构化验收段和 comparison occupancy 字段。

**`feature-dev` 复核（2026-09-23）：** 用当前 `feature-dev@9fab02e` 对同一 `zh_all_table_pages.pdf` 和五个验收页直接调用 `recover_wireless_tables()`，仍得到相同的 49 个重复槽位；逐表 `recover_cells_from_region()` 均为 0。用户指出的 `个人信用报告(本人简版)_20260923_full_run` 是另一份五页产品输出，最终 JSON 共 10 张表、重复槽位为 0；第 0 页表格来源为 `line_projection`、尺寸 4×5，属于个人征信有线表格路径，不是本审计的通用无线恢复入口。

进一步对同一 `zh_all_table_pages.pdf` 使用当前 `feature-dev@9fab02e` 完整 `Pipeline` 复核（`page_indices=[184,188,189,191,192]`、`use_ml_table_detector=False`、串行、72 DPI）：最终表格尺寸分别为 184=`4×3,16×7`、188=`4×5,21×4`、189=`12×4,8×3`、191=`17×3,5×7`、192=`2×4,2×5,6×9,8×5`。最终 Cell 网格在 184、188、189、191 页无重复槽位；192 页仅剩 1 个：第 0 张 2×4 表的零基槽位 `(1,2)`，由两个相邻分隔符 Cell（`=====` 跨 2 列、`================` 占 1 列）重叠，bbox 横向交叠约 2.6 pt。故低层 helper 的 49 个冲突没有整体传到完整解析结果。后续 Task 5 必须分开验收 helper parity 与完整 Pipeline 的用户可见 parity。

近期 `feature-dev` 的 `0e2821a`（征信元数据过滤保留有线表格）和 `00e8484`（征信专用 `wired_line_tolerance=2.0`）针对该有线产品路径，不会修复上述通用无线 page-level helper。它们可能改变征信页面的候选表格及边界；不应整体同步进 Task 5。若 Rust 后续覆盖个人征信有线入口，应单独移植这两项语义并用对应五页产品输出重新验收。

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

## 2026-09-23 修复执行补记：页面候选列锚点

在页面候选路径实现 Python `_column_tracks()` / `_assign_column()` 的列锚点语义：数字取 bbox 右沿，标签取 bbox 左沿；只有所有 atom 都带候选行号、轨迹数量与 Rust 推断列带数量相同才应用重映射。区域 NativeRegion 输入没有候选行号，不经过这段重映射；列数不一致时保留原有 Rust 分配，避免把 Python 轨迹位置错误解释为 Rust band 下标。

- 新增 `test_recover_wireless_tables_uses_python_left_anchor_for_wide_labels`。合成布局中“宽标签” bbox 横跨数值列起点，Python 按左锚点放入标签列；旧 Rust 路径产生 occupancy fallback（RED），重映射后实际 Rust 路径输出 3×2、六个 1×1 cells 且无 fallback（GREEN）。
- fresh release binding 下迁移 focused pytest 为 `187 passed`；`cargo test --lib` 为 `62 passed`；release 扩展构建成功。
- 新五页 acceptance 输出：`D:\codes\PDFLayoutParser\output\rust_migration_task5_left_anchor_20260923_r11\`，PDF SHA256 `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`。summary 是结构 mismatch `0`、routing diagnostics `12`。Python/Rust table counts 为 `184:2, 188:2, 189:2, 191:2, 192:4`；五页 PNG hash 与 Python 及 r10 相同。
- **验收限制：** `0` 结构 mismatch 仍由 fallback 后输出相同而来；五页页面候选 occupancy fallback 共十条 shadow/rust routing records，page 188 区域入口另有两条。r11 没有减少 r10 的 fallback，也没有证明真实页 Rust 独立 parity 或速度收益。Python primary 保持开启、Rust primary 保持关闭。
- fallback 前的 page 184 trace 表明列锚点映射的数量保护正在生效：第一个候选 Python/Rust 锚点轨迹数均为 5，但 Rust overlap-band 只有 3；第二个候选 Python 有 10 条轨迹，Rust 产生 11 条轨迹，却只推断 2 个 overlap-band。因此不能把 Rust track index 直接套成 band index。第一个候选的首要分歧已定位为 Rust bbox-overlap band inference 合并了 Python 的独立逻辑列；第二个候选还需要比较输入 strip/atom 与轨迹分组的差异，不能把额外 track 原因先归到某个阈值。
- 后续不要继续扩大重映射条件。先为真实候选对比 `visual_rows → candidate_runs → column_tracks → nearest-track assignment → cell grouping → spanning_single_rows → bbox/quality` 的阶段输出，并解释轨迹与 inferred bands 数量/顺序何时不一致；在找到第一处分歧及最小 Python oracle fixture 前，不做同槽聚合。

## 2026-09-23 修复执行结果

在独立分支/worktree `codex/task5-parity-repair` 上执行了 Task 5 bounded repair。原审计 worktree 的 dirty 测试文件保持未修改，未提交或切换默认路由。

- 完成了结构 mismatch 与 routing diagnostic 拆分、两行 rowspan Python oracle、NativeRegion band ID→零基位置映射、保留 separator 的 Rust page text runs、Rust 候选单字段行切分/标题前置、冒号字段 continuation veto，以及 NativeRegion 无稳定列带时与 Python 一致地返回空网格。
- Rust page candidate confidence 从常量 `0.90` 改为 Python 的 multi-column row support/active-column 公式；合成 differential 先复现 `0.90` 对 `0.80` 的 RED，再 GREEN 验证 cell 结构与 confidence 同值。
- 最终输出：`D:\codes\PDFLayoutParser\output\rust_migration_task5_confidence_20260923_r10\`；输入 PDF SHA256 与原验收相同：`376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`。
- 最新 summary：结构差异 `0`、路由诊断 `12`。Python/Rust 表格数量逐页相同：184=2、188=2、189=2、191=2、192=4；五页 wireless overlay PNG SHA256 逐页相同。页 189 两个候选现被分为与 Python 一样的两张表。
- **解释限制：** Rust page 路由仍在五页都报告 occupancy conflict 后 fallback 到 Python；188 页 region 入口在 shadow 和 rust 模式另有两条 occupancy fallback。因此 `0` 结构差异和相同 PNG 是 fallback 后的外部结果，不证明 Rust 算法独立地产生同一结果。Python page-level 已有的 49 个 occupancy conflicts 仍保留，不作静默归一。
- 曾试验按 row/column 对候选 physical cells 无条件聚合；该版本产生 `1475` 条结构 mismatch，已撤回，最终源代码不包含该试验。它暴露出仅按槽位合并会绕过 Python `_column_tracks()`、nearest-track assignment、跨列标题及 bbox 语义。后续应先比较这些阶段，再选择最早分歧修复。
- 最终源文件 focused pytest `186 passed`、`cargo test --lib` `62 passed`、`git diff --check` 通过。`cargo fmt --all -- --check` 退出码 `1`，在 `rust/lib.rs`、`rust/native_span.rs` 等多个已修改 Rust 文件报告 rustfmt 差异；没有运行全仓格式化，避免无关改动。未运行性能门禁，Rust primary 保持关闭。
## 2026-09-23 修复补记：separator atom 与候选 track-first

在修复 worktree 继续 page 184 调查。实际保留分隔符 Rust route 的候选 1 有 96 个 AtomDto，其中 94 个进入列轨迹宽度统计；中位宽度 31.5 pt、容差 13.23 pt。Python 的关键 separator strip 为单个原始 span “----  ---------”，bbox 横跨约 x=416.76..493.59。Rust packed-number helper 会按字符 bbox 的大空隙将它拆成 “----” 与 “---------”两个 atom；右半段左沿约 446，与“坏账准备”左沿约 449 形成重复锚点，随后和 462 的破折号锚点分轨。这是额外轨迹的直接来源，不是容差公式不同。

修复仅令纯 separator span 不参加 packed-number 拆分；合法数值串的拆分合同保持不变。页面候选路由只在所有 atoms 都携带 candidate row_hint 时走 Python 风格 track-first：按 label 左沿 / number 右沿寻找最近轨迹，按 row/column 聚合 atom，同步重建 centered/short-title spanning 行、bbox、轨迹覆盖 colspan 和 confidence。无 row_hint 的区域入口继续使用 band/grid，不扩大通用列带逻辑。

新增两个 oracle 回归：
- 带原始逐字符 bbox 的 spaced separator span：修复前产出两个 Rust run，修复后保持一个 run，文本与总 bbox 保留。
- 三条稳定逻辑轨迹被一个宽字段连接成两个 bbox-overlap band：实际 Rust route 与 Python 输出 3×3 单元格、wide cell colspan 和 confidence 一致，无 fallback。

真实页的冲突合同仍未解决，因此该修复没有移除 fallback。页 184 direct Rust 保留 4×5 / 14-cell 第一候选；9×10 第二候选在 occupancy 检查阶段出现 19 个槽位冲突而被拒绝，Python wrapper 回退后仍返回 Python 原结果。五页 r12 acceptance summary 为结构 mismatch 0、routing diagnostic 12；fallback 仍为五页页面入口十条加 188 页 region 入口两条。页 184–192 的真实输出没有证明 Rust 独立 parity 或性能收益。

r12 输出位于 D:\codes\PDFLayoutParser\output\rust_migration_task5_tracks_20260923_r12\，输入 SHA256 为 376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89。focused pytest 188 passed，cargo test --lib 63 passed，cargo check 与 git diff --check 通过；cargo fmt --all -- --check 仍报告仓库中多处既有格式差异，未做全仓格式化。Python 默认路由、未提交状态和 Rust fallback 保持不变；benchmark 未运行。

## 2026-09-23 修复补记：region 最终列带与候选宽字段

页 188 的第二个固定区域有 4 条 Python 最终列带，其中一条稀疏列先被 Python prune、后被 `rescue_header_only_leaf_bands()` 按表头结构恢复。Rust 收到该最终 DTO 后又调用 `refine_leaf_bands()`，重复剪掉已恢复列，导致两列数值映射到同一槽位并报 occupancy conflict。修复后：非空 `NativeRegionInput.bands` 视为 Python 已完成准备的列带；仅在 bands 为空、需要 Rust 自行推断时执行 Rust refine/rescue。页 188 两个真实 region 都无 Rust diagnostic，并与 Python 的 4×5 / 21×4 输出逐字段一致。

页面候选路径另按 Python `_split_wide_field_strip()` 的限定条件拆分临时 atom：只有以至少三个空白分隔、片段数等于轨迹数且每片都含字段冒号时才拆；其余正文和字段数不匹配输入保持原样。合成正例与反例通过。该修复没有改变本次五页 PNG，也没有减少仍由 occupancy conflict 触发的 page fallback。

五页 r14 输出：`D:\codes\PDFLayoutParser\output\rust_migration_task5_track_field_split_20260923_r14\`，PDF SHA256 `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`。summary：结构字段差异 `0`、routing diagnostic `10`；10 条全部来自 5 页 page route 在 shadow/rust 两种模式的 occupancy fallback。region route 无 fallback，五页归一化结构与 Python 相同。五页 Python/shadow/rust PNG SHA256 逐页相同，Rust 表格数为 `2/2/2/2/4`。

验证：focused migration pytest `190 passed`，`cargo test --lib` `64 passed`，`maturin develop --release --skip-install` 成功。runner 因保留的 10 条 page fallback diagnostics 返回退出码 1；这不是结构差异通过 Rust 独立输出的证据。Rust primary 仍关闭，page-level Python 的 49 个 occupancy conflict 合同仍待用户决定；没有隐藏冲突或切换默认路由。本轮未做性能 benchmark。
