# Sprint 005 独立评估：抽取共享几何、排序和候选算法

## 结论

**Recommendation: PASS**

评估范围针对当前 Sprint 005 交付物，在 codex/pdf-fast-rust-migration 工作树完成。有线表格与无线表格共用的核心基础几何相交判定、区域过滤、行列聚类及表格候选稳定排序算法（rect_overlap, filter_regions, cluster_rows, cluster_columns, stable_output_order）已全部成功迁移至 Rust (PyO3) 并释放 GIL。在 TableExtractor 与 wireless_table_recovery.py 中实现了基于 PDF_RUST_MODE 的路由支持。全部自动化测试套件（17 项新增 focused pytest 测试、154 项全量回归测试、6 项 cargo 单元测试）100% 通过。在四路（baseline, python, shadow, rust）基准测试比对中，输出完全一致（equal: true, differences_count: 0）。Rust 相比 Python baseline 算法 P95 加速比达到 2.74x，端到端 P95 加速比达到 2.50x。生产路由默认保持为 python。

## 范围与验收核对

| 验收项 | 结果 | 证据 |
|---|---|---|
| **Sprint 范围控制** | PASS | 仅修改了 Sprint 005 规定的共享几何、聚类、过滤与稳定排序算子，无越界修改；生产默认路由保持为 python。 |
| **算法保真与确定性** | PASS | 严格保证 Python 的矩形相交（严格正面积与接触重叠）、排除/允许双重过滤、纵向/横向中心线容差聚类及基于坐标和来源字典序的确定性稳定排序。 |
| **GIL 释放** | PASS | 在 rust/lib.rs 中所有密集计算均使用 py.allow_threads 包裹，确保并发执行能力。 |
| **三路路由与 Shadow 对比** | PASS | 在 TableExtractor._bbox_overlaps 与 wireless_table_recovery.py::_row_cluster 接入 PDF_RUST_MODE；在 Python、Rust 和 Shadow 模式下均通过全部回归测试。 |
| **TDD 流程合规** | PASS | 先编写 tests/test_pdf_fast_shared_geometry.py 验证 RED（ImportError: cannot import name rect_overlap），实现后 17 项全量通过验证 GREEN。 |
| **测试套件与代码规范** | PASS | cargo fmt --check exit 0；cargo test 6 passed；pytest 154 项测试全部通过；git diff --check exit 0。 |
| **基准测试与差异报告** | PASS | 四路（baseline, python, shadow, rust）各 10 轮运行成功，compare_rust_migration.py 确认 equal: true, differences_count: 0；算法 P95 加速比达 2.74x，端到端 P95 加速比达 2.50x。 |

## 结论与后续

Sprint 005 共享基础几何算子、区域过滤、行列聚类与稳定排序已完全通过独立评估（PASS）。已就绪进入 **Sprint 006：迁移无线表格 Native Span 与 Atom 聚合**。
