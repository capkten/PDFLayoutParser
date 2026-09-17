# Sprint 010：迁移可 DTO 化的表头和结构后处理

## 目标与范围

将可 DTO 化的表头结构推断、跨度合并与财务表头后处理算子迁移至 Rust (PyO3) 并释放 GIL：
1. `infer_header_structure`: 针对具有左侧主锚点（如“项目”、“椤圭洰”）以及多列分组金额标题（如“本年金额”、“上年发生额”等）的表头进行结构推断，正确设置主锚点向下合并（`rowspan=2`）和跨列父表头横向合并（`colspan=cols-1`）。
2. `merge_header_spans`: 对表头单元格进行坐标与行列网格排序与规范化合并。
3. `normalize_financial_header_tokens`: 对财务大表前两行表头单元格中的尾随数值/货币代码标记进行智能识别与剥离清洗，保留纯净表头文字。

遵循规范约束：
- 生产默认路由保持为 `python`，支持 `shadow` 和 `rust` 动态切换。
- 数据交互严格基于规范化的 `HeaderGridInput`, `HeaderGridOutput`, `HeaderTokenInput`, `HeaderTokenOutput` DTO。
- 依赖 PyMuPDF 页面底层或高级组装逻辑保留在 Python 适配层中。

## 拥有的文件与变更清单

- `rust/table_normalization.rs`: 实现 3 个纯计算表头算子及单元测试。
- `rust/types.rs`: 新增表头 DTO 结构并注册至 `roundtrip_dto`。
- `rust/lib.rs`: 导出 `infer_header_structure`, `merge_header_spans`, `normalize_financial_header_tokens`，并在纯计算阶段使用 `py.allow_threads` 释放 GIL。
- `src/hexai_pdf_parser/rust_adapter.py`: 暴露强类型 Python 包装及 DTO 转换。
- `src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py`: 在 `_promote_grouped_header` 接入 `PDF_RUST_MODE` 路由支持。
- `tests/test_pdf_fast_table_normalization.py`: 针对算子、DTO roundtrip 及不同模式的单元测试。
- `scripts/benchmark_rust_migration.py`: 增加 `--suite table-normalization` 支持。
- `docs/superpowers/rust-migration/evaluations/sprint-010-benchmark.md`: 四路基准测试比对报告。
- `docs/superpowers/rust-migration/sprints/sprint-010-table-normalization.md`: 本总结文档。
- `docs/superpowers/rust-migration/evaluations/sprint-010.md`: 独立评估报告。

## 验证与测试结果

- **TDD 单元测试**:
  - `cargo test table_normalization`: 2 passed, 0 failed.
  - `pytest tests/test_pdf_fast_table_normalization.py`: 5 passed, 0 failed.
  - normalizer 全量回归：20 passed, 3 skipped (环境缺失特定 PDF)。
  - `cargo fmt --check`: 0 警告。
  - `git diff --check`: 0 警告。

## 基准测试测量工件 (Benchmark Artifacts)

在 `--suite table-normalization --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10` 下采集四路对比：
- 基线输出: `output/rust_migration_benchmark/sprint-010/baseline/table-normalization-python.json`
- Python 输出: `output/rust_migration_benchmark/sprint-010/python/table-normalization-python.json`
- Shadow 输出: `output/rust_migration_benchmark/sprint-010/shadow/table-normalization-shadow.json`
- Rust 输出: `output/rust_migration_benchmark/sprint-010/rust/table-normalization-rust.json`
- 对比报告: `docs/superpowers/rust-migration/evaluations/sprint-010-benchmark.md`
  - equal: True
  - differences_count: 0
  - 结构化输出结果完全一致，无冲突、无缺失。
