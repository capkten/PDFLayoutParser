# Sprint 007 最终评估：无线结构页面验收与迁移门禁

## 结论

**Recommendation: CONDITIONAL PASS（验收闭环完成，Rust primary 暂不通过）**

Task 5 的双路 shadow、真实 PDF 页面 JSON/PNG 导出、两条高层入口覆盖和字段级 comparison report 已完成；Task 6 的回归矩阵、artifact 审计和差异分类也已完成。证据显示 shadow 保持 Python 结果，但 Rust 直出尚未达到中文/混合无线页面 parity。因此本次交付完成“可审计迁移验收”，不宣称 Rust primary 已就绪。

## 范围与产物

| 项目 | 结果 |
|---|---|
| 输入 PDF | `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf` |
| 页面 | 184、188、189、191、192（0-based） |
| 语言 | mixed、mixed、mixed、zh、mixed |
| 模式 | python、shadow、rust |
| 高层入口 | `recover_wireless_tables()`、`recover_cells_from_region()` |
| 输出根目录 | `D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\` |
| 页面产物 | 15 个 page JSON、15 个 overlay PNG、15 个 debug JSON/HTML 组合、3 个 manifest |
| 比较报告 | `D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\comparison\comparison.json` |

## 结构化验收

- 三个 manifest 均包含完整的五个页面，输入 SHA256 一致，artifact 路径为存在的绝对路径。
- shadow page/table/region 语义结果与 Python 一致；执行模式字段是报告元数据，不参与结构比较。
- Rust route 的 17 条 shadow diagnostics 和 fallback/mismatch 都被保留；没有吞掉异常或把 fallback 当作 Rust parity。
- comparison report 有 `2894` 条记录：结构字段差异 `2874` 条（regions 2241、tables 632、table_count 1），routing diagnostics `20` 条（shadow 17、Rust fallback 3）；当前均标为 `defect`、`unclassified_count=0`。该数量是字段/诊断记录数，不是独立根因数；完整拆解见 [`task5-problem-audit-2026-09-23.md`](../task5-problem-audit-2026-09-23.md)。
- Python page-level baseline 的 table cells 在五页累计 49 个 occupancy conflict，region 入口为 0；这个已知基线问题被保留在验收记录中，未由 normalizer 掩盖。

## 页面结构差异

Python 基线的 table 结构是：

- 184：4×5、9×10；
- 188：5×8、21×8；
- 189：13×9、10×5；
- 191：17×8、6×6；
- 192：2×4、2×3、4×8、7×5。

Rust page route 在 188、189 页分别输出 8×3/11×4 和 6×4/2×3/3×3；184、191、192 页的 page route 因 occupancy conflict 触发 Python fallback。固定 Python table bbox 的 Rust region route 在五页均有字段级差异。差异分类为 `defect`，后续修复必须以该报告逐项收敛，不能通过扩大容差、业务标题特判或移除 occupancy 检查消除。

## Visual QA

已检查五页 Python/Rust overlay PNG。184、191、192 的 Rust page overlay 与 Python 视觉上相同，但对应 page route 已发生 fallback；188、189 可见 Rust 表格边界、分组范围和行列切分与 Python 不一致，尤其是 188 页上方资本公积表未形成对应 Rust 候选，189 页多个相邻区段被拆成不同 Rust table。该结果与 JSON 结构差异一致。

## 验证矩阵

| 检查 | 结果 |
|---|---:|
| Task 5 normalizer/runner focused pytest | 8 passed |
| Task 5/4 differential and routing matrix | 140 passed |
| `cargo test --lib` | 60 passed |
| `cargo check` | passed |
| `git diff --check` | passed |
| 未解释差异 | 0 |
| 默认 route | Python，未修改 |

## 最终门禁

Task 5/6 的文档、脚本、测试和页面证据可以封存；生产切换门禁不通过。当前安全状态为：Python primary、shadow 观测、Rust fallback/diagnostic 保留。Rust primary 只有在修复本报告的 page/region defect，并重新生成新的独立输出目录、重新检查 JSON 与 PNG 后才能重新评估。

## 2026-09-23 bounded repair follow-up

修复分支 `codex/task5-parity-repair` 上重跑了五页验收，输出目录为 `D:\codes\PDFLayoutParser\output\rust_migration_task5_confidence_20260923_r10\`，输入 SHA256 仍为 `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`。comparison 汇总现在拆分显示结构 mismatch `0`、routing diagnostics `12`；Python/Rust table counts 分别在 184/188/189/191/192 为 `2/2/2/2/4`，五页 wireless PNG 逐页 SHA256 相同。新增 confidence differential 将 Rust 固定 `0.90` 改为 Python 依据多列行支持数和活动列数计算，并用 `0.80` synthetic oracle GREEN。

这些结构结果由 Rust occupancy fallback 到 Python 后得到，不能覆盖原始判断“Rust page route 未通过 parity”。12 条 diagnostics 为五页页面入口各有 shadow/rust occupancy fallback（10 条），以及 188 页 region 入口两种模式各一条 occupancy fallback。Python page-level baseline 的 49 个 occupancy conflicts 仍是未决兼容合同；本轮不修改 Python 输出、不静默清除这些 conflict，也不把它们当作 Rust 已通过的依据。

修复包括 mismatch 分类计数、Python oracle test correction、band-ID 映射、separator 行保留、候选行切分/标题前置/冒号续行拒绝、无稳定列带时空网格结果一致，以及页面候选 confidence 公式对齐。尝试按相同 row/column 无条件聚合候选 cells 产生 `1475` 个结构 mismatch，已回退；候选 `_column_tracks()`、列 assignment、跨列标题和 bbox 仍是后续最早需对比的阶段。focused pytest `186 passed`，最终源码 `cargo test --lib` `62 passed`，`git diff --check` 通过；`cargo fmt --all -- --check` 因 `rust/lib.rs`、`rust/native_span.rs` 等文件的 rustfmt 差异退出 `1`，未作全仓格式化。没有运行 benchmark，Rust primary 不开放。

## 2026-09-23 最近 slice：页面候选列锚点

在 `rust/wireless_structure.rs` 页面候选路径实现 Python 的 `_column_tracks()` 与 `_assign_column()` 锚点规则：数字使用右沿、标签使用左沿。仅当 candidate atoms 都具有 `row_hint` 且 Python-style track 数等于 Rust inferred band 数时才映射到相同列序号；区域入口与不匹配网格不变。新增宽标签与数值 bbox 重叠的 differential，旧 Rust 路径因 occupancy conflict fallback（RED），新路径得到 Python 3×2 / 六个独立 cell 且无 diagnostic（GREEN）。

- release binding：`maturin develop --release --skip-install` 成功。
- focused migration matrix：`187 passed`；`cargo test --lib`：`62 passed`。
- 五页新 acceptance：`D:\codes\PDFLayoutParser\output\rust_migration_task5_left_anchor_20260923_r11\`，输入 hash `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`。summary `structural_mismatch_count=0`、`routing_diagnostic_count=12`；Rust/Python table counts `2/2/2/2/4`，五页 PNG 哈希相同且与 r10 一致。
- 真实页 occupancy fallback 未减少：页面入口仍十条，188 页 region route 两条。0 个结构差异仍是 fallback 后的比较结果；不宣称 Rust 独立 parity 或性能收益，Rust primary 继续关闭。
- page 184 fallback 前 trace：candidate 0 的 Python/Rust 锚点轨迹数都是 5，Rust overlap-band 数为 3；candidate 1 是 Python 10、Rust 11 条轨迹，Rust 只有 2 个 band。当前按轨迹数量守卫跳过映射是必要的；candidate 0 已证明 bbox-overlap band 会合并独立逻辑列。candidate 1 多出的 Rust track 需要继续从输入 strip/atom 与 clustering tolerance 差异定位。
- 下一步针对 fallback 前的数据建立候选中间阶段 ledger，定位 `visual_rows → candidate_runs → column_tracks → nearest-track assignment → cell grouping → spanning_single_rows → bbox/quality` 第一处不一致。不要在无 Python oracle 的情况下放宽列映射，也不要再尝试按 row/column 无条件聚合。
## 2026-09-23 follow-up：separator span 与 page candidate track-first

本轮定位并修复页 184 候选列轨迹的一个精确分歧。Python 把原始 span “----  ---------”保留为一个 strip；Rust 的 packed-number 分割会把它按字符间空隙切成两个 atom，额外产生 x≈446 的左锚点，继而与 x≈449 的标签形成独立轨迹。现在 separator-only span 在 packed-number 拆分阶段整体保留，并新增带逐字符 bbox 的 Rust 回归：RED 时得到 2 个 run，修复后为 1 个完整 separator run。

页面候选建表现在在 atom 带 row_hint 时直接沿 Python _column_tracks、_assign_column、单行 spanning、轨迹覆盖 colspan 与 confidence 公式生成候选，不再将逻辑轨迹索引错误套到 overlap band 网格。region 恢复仍走原有 band/grid。新增“三条重复逻辑轨迹 + 宽字段只形成两条 overlap band”的真实 Rust route differential；旧路径因 occupancy conflict fallback，track-first 后输出 Python 3×3 候选、宽标签 colspan=2 且无诊断。

五页验收在 D:\codes\PDFLayoutParser\output\rust_migration_task5_tracks_20260923_r12\，PDF SHA256 为 376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89。summary 为结构 mismatch 0、routing diagnostic 12；各页 table counts 仍为 2/2/2/2/4，Python/Rust PNG SHA256 逐页相同且与 r11 一致。raw Rust 页 184 只保留第一张 4×5 候选；第二张 9×10 候选因 19 个 occupancy conflict 被拒绝并继续 fallback。188、189、191、192 的 full-page candidates 也仍有 occupancy conflict / out-of-bounds diagnostics。0 个结构 mismatch 来自 wrapper fallback 后 Python 输出，不代表 Rust 独立 parity；fallback 数没有减少。

验证：迁移 focused pytest 188 passed；cargo test --lib 63 passed；cargo check 通过；git diff --check 通过。cargo fmt --all -- --check 仍因多个已存在 Rust 文件格式差异退出 1，本轮没有全仓格式化。未运行性能门禁，Python primary 保持开启。

## 2026-09-23 follow-up：预处理列带与宽字段片段

NativeRegion 收到非空列带时现在直接消费 Python 完成 refine/rescue 的最终列带；Rust 只在输入列带为空时运行自己的推断与 refine/rescue。这消除了页 188 稀疏表头列被二次剪除的问题。页面候选 track-first 在 Python 同样的三条件下拆分宽字段片段（至少三个空白、片段数等于轨迹数、每片是带冒号字段），prose 和不匹配片段数不拆。

r14 输出位于 `D:\codes\PDFLayoutParser\output\rust_migration_task5_track_field_split_20260923_r14\`，输入 SHA256 与之前一致。比较结果结构差异 `0`、routing diagnostics `10`；仅五页 page route 的 shadow/rust 入口各有一条 occupancy fallback。五页 region route 无 fallback 且归一化结构与 Python 相同；Python/shadow/rust PNG 逐页 hash 相同，表格数仍为 `2/2/2/2/4`。0 个结构差异仍包含 page fallback 后的 Python 输出，不代表 page Rust parity。

验证：focused migration pytest `190 passed`，Rust lib `64 passed`，release binding 构建成功。runner 以 exit code 1 结束是因为 10 条保留的 routing diagnostics；未运行性能 benchmark，未切换 Python 默认路由或 Rust primary。Python page-level 49 个 occupancy conflict 的兼容合同仍待确认。
