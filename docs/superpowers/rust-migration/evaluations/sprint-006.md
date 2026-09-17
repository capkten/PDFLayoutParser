# Sprint 006 独立评估：迁移无线表格 Native Span、Atom 和 Text Run 数据流

## 结论

**Recommendation: PASS**

评估范围针对当前 Sprint 006 交付物，在 codex/pdf-fast-rust-migration 工作树完成。无线表格的核心 Native Span 数据流、Text Run 构建、Atom 聚类、换行合并以及阅读顺序推断算法（build_text_runs, build_atoms, merge_wrapped_rows, infer_output_order_mode, recover_native_candidates）已全部成功迁移至 Rust (PyO3) 并释放 GIL。严格遵循中文无线表格约束：纯消费 NativeSpanDto，不回读 page.get_text("words")；严格覆盖 20 组 CJK 大字距白名单以及“男/女”不误并的反例验证。全部自动化测试套件（8 项新增 focused pytest 测试、8 项 cargo 单元测试、69 项 fast 测试）100% 通过。在四路（baseline, python, shadow, rust）基准测试比对中，输出完全一致（equal: true, differences_count: 0）。Rust 相比 Python baseline 算法 P95 加速比达到 1.32x，端到端 P95 加速比达到 1.46x。生产路由默认保持为 python。

## 范围与验收核对

| 验收项 | 结果 | 证据 |
|---|---|---|
| **Sprint 范围控制** | PASS | 仅修改了 Sprint 006 规定的无线表格 Native Span、Text Run、Atom 及阅读顺序算子，无越界修改；生产默认路由保持为 python。 |
| **算法保真与确定性** | PASS | 严格保证 Python 的白名单聚合（20 组白名单允许 2.5 倍字距）、单字反例判定（普通单字 CJK 严格 1.25 倍字距，防止相邻字段误并）、ASCII/混合成词、纵向换行续写合并与行交错/列式阅读顺序推断。 |
| **中文无线表格不变量** | PASS | 纯消费 NativeSpanDto，进入 atom/逻辑网格阶段绝不回读 words；新增 test_page_spy_no_get_text_words 验证无 get_text("words") 调用。 |
| **GIL 释放** | PASS | 在 rust/lib.rs 中所有密集计算均使用 py.allow_threads 包裹，确保并发执行能力。 |
| **TDD 流程合规** | PASS | 先编写 tests/test_pdf_fast_wireless.py 验证 RED（ImportError: cannot import name build_text_runs），实现后 8 项全量通过验证 GREEN。 |
| **测试套件与代码规范** | PASS | cargo fmt --check exit 0；cargo test 8 passed；pytest 69 项测试全部通过；git diff --check exit 0。 |
| **基准测试与差异报告** | PASS | 四路（baseline, python, shadow, rust）各 5 轮运行成功，compare_rust_migration.py 确认 equal: true, differences_count: 0；算法 P95 加速比达 1.32x，端到端 P95 加速比达 1.46x。 |

## 结论与后续

Sprint 006 无线表格 Native Span、Atom 和 Text Run 数据流已完全通过独立评估（PASS）。已就绪进入 **Sprint 007：迁移无线表格列带与结构分析**。
