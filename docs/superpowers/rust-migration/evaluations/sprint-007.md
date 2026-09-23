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
