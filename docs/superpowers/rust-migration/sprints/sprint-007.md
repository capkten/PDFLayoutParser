# Sprint 007：Rust 无线结构双路 Shadow 与真实页面验收

> 日期：2026-09-22
> Worktree：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`
> 分支：`codex/rust-migration-replan`

## 目标与边界

本 sprint 完成 Task 5 的页面级验收基础设施和 Task 6 的最终审计闭环，不切换默认生产 route。验收固定使用：

- 输入：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`
- 0-based 页面：`184, 188, 189, 191, 192`
- 模式：`python`、`shadow`、`rust`
- 入口：`recover_wireless_tables()`、`recover_cells_from_region()`
- 输出：`D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`

结构恢复阶段仍只消费 PageSnapshot/native span/atom/grid/Cell；本 sprint 没有新增 `page.get_text("words")`、`extract_zebra()` 或 legacy 无线重建调用。

## 实现内容

1. `src/hexai_pdf_parser/debug/rust_task5_acceptance.py`
   - 新增 `normalize_recovery()`、`normalize_region_result()` 和 `compare_normalized()`。
   - 统一保留 source、行列、bbox、Cell 文本和跨度、空槽位、occupancy owner/conflict/out-of-bounds。
   - 比较器只允许 0.01pt 以内 bbox 浮点误差，并忽略执行模式元数据；没有 wildcard ignore。
   - routing diagnostic 只保留稳定字段，详细证据仍由既有 debug JSON 保存。
2. `scripts/run_task5_shadow_acceptance.py`
   - 每页在同一 PDF 上依次执行三种模式。
   - Python 接受的 table bbox 被固定为三种模式的 region 输入，覆盖两条高层入口。
   - 为每个模式输出 page JSON、debug JSON、HTML、overlay PNG、manifest 和统一 comparison JSON。
   - 每个未对齐字段和每条 routing diagnostic 都附带显式 `classification`。
3. `tests/test_rust_wireless_shadow_differential.py`
   - 覆盖 normalizer、occupancy、shadow 返回 Python、模式隔离、runner payload 和 bbox 容差合同。

## 页面结果摘要

Python 基线的页面级 table 结构为：

| 页面 | 语言 | table 结构（rows×cols） | region 数量 |
|---|---|---|---:|
| 184 | mixed | 4×5、9×10 | 2 |
| 188 | mixed | 5×8、21×8 | 2 |
| 189 | mixed | 13×9、10×5 | 2 |
| 191 | zh | 17×8、6×6 | 2 |
| 192 | mixed | 2×4、2×3、4×8、7×5 | 4 |

页面产物检查结果：三种模式各有 5 个 page JSON、5 个 overlay PNG 和 1 个 manifest；输入 SHA256 在三个 manifest 中一致；所有 artifact 路径均为存在的绝对路径。

## Shadow 与 Rust 结果

- `shadow` 的结构化 page/table/region 结果在五页上与 Python 语义结果一致；差异只来自 Rust 观测诊断，共 17 条。
- `rust` 直出在 184、191、192 页的 page 入口因 occupancy conflict 走既有 Python fallback；fallback diagnostic 被保留。
- `rust` 直出在 188、189 页的 page 入口分别得到 `8×3、11×4` 与 `6×4、2×3、3×3`，与 Python 基线不同。
- 固定 Python table bbox 后，Rust `recover_cells_from_region()` 在五页都存在结构差异；这是真实 Rust 结构缺口，不通过放宽比较器隐藏。
- 页面级 Python 基线自身的高层 `Table.cells` 在这五页累计出现 49 个 table occupancy conflict；region 结果为 0。该基线现象单独记录，不能被解释为 Rust 已通过最终槽位合同。

## 验收与决策

Task 5 的 runner、字段级报告、JSON/PNG 导出和 visual QA 已完成；Task 6 的审计、分类和最终回归已完成。比较报告中 2894 条差异全部标为 `defect`，`unclassified_count=0`，因此没有未解释差异。

结论是“验收闭环完成，Rust primary 未通过”：默认模式继续保持 Python；shadow 可用于观测；Rust 直出仍受页面级 parity defect 和 fallback 约束，不能切换为 primary。后续若要推进 Rust primary，应以 comparison.json 中的 defect 字段逐项新增失败用例、修复并重新生成独立输出目录。

## 验证命令

```powershell
$env:PYTHONPATH='D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan\src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.12 -m pytest -q tests/test_rust_wireless_shadow_differential.py
# 8 passed

py -3.12 -m pytest -q tests/test_rust_wireless_shadow_differential.py tests/test_rust_wireless_structure_differential.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_recoverer.py tests/test_rust_migration_routing.py
# 140 passed

cargo test --lib
# 60 passed
cargo check
git diff --check
```
