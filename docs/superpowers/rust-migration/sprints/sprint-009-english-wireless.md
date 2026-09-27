# Sprint 009：迁移英文 Zebra、General Wireless 和 Legacy 纯算法至 Rust

## 目标与范围

将英文无线表格提取算子迁移至 Rust (PyO3) 并释放 GIL：
1. `group_backgrounds`: 依据垂直间距（阈值 30pt）将背景带聚合为独立子表格候选。
2. `detect_zebra_rows`: 检测斑马背景行，并在相邻非白色背景带之间自动补全白色背景行（填补小计/空行）。
3. `assign_words_to_zebra_rows`: 将单词分配至对应斑马背景行，对未分配单词基于纵向容差聚类为独立物理行。
4. `infer_english_columns`: 依据单词分布与下划线聚类推断英文列带，并处理货币符号（如 `$ 1,200`）边缘归属对齐。
5. `build_english_cells`: 端到端构建英文无线表格网格（含单文本跨多列父表头推断与空白槽位补全）。
6. `build_general_wireless_cells`: 依据原子（atoms）与列带（bands）纯几何构建通用英文无线单元格网格与独立空单元格。
7. `build_legacy_text_alignment`: 迁移旧版纯文本对齐与表头跨度推断算法。

遵循中文与英文无线表格约束：
- 生产默认路由始终保持为 `python`，支持 `shadow` 和 `rust` 动态切换。
- 保证中文/混合页面无线表格绝不回退至 `words`，不进入 zebra/legacy 路径。
- 结构恢复严格由规范 DTO 承载，独立字段保留为独立叶子列，无占位冲突。

## 拥有的文件与变更清单

- `rust/english_wireless.rs`: 完整实现 7 个核心算子及 Rust 单元测试。
- `rust/types.rs`: 新增 `ZebraInput`, `EnglishGridInput`, `GeneralWirelessInput`, `LegacyAlignmentInput` DTO 结构并注册至 `roundtrip_dto`。
- `rust/lib.rs`: 注册 `pub mod english_wireless;`，导出 7 个 PyO3 绑定并在密集计算处使用 `py.allow_threads` 释放 GIL。
- `src/hexai_pdf_parser/rust_adapter.py`: 暴露 7 个算子的强类型 Python 包装及 DTO 转换。
- `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py`: 在 `_group_into_tables` 与 `_assign_words_to_zebra_rows` 接入 `PDF_RUST_MODE` 路由。
- `src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py`: 在 `_rebuild_text_aligned_table` 接入 `PDF_RUST_MODE` 路由。
- `tests/fixtures/rust_migration/english/english_wireless.json`: 创建完整的英文 Zebra、多列、货币对齐与多表工件。
- `tests/test_pdf_fast_english_wireless.py`: 8 个针对各算子及 DTO roundtrip 的单元测试。
- `scripts/benchmark_rust_migration.py`: 增加 `--suite english-wireless` 支持。
- `docs/superpowers/rust-migration/evaluations/sprint-009-benchmark.md`: 四路基准测试比对报告。
- `docs/superpowers/rust-migration/sprints/sprint-009-english-wireless.md`: 本总结文档。
- `docs/superpowers/rust-migration/evaluations/sprint-009.md`: 独立评估报告。

## 验证与测试结果

- **TDD 单元测试**:
  - `cargo test`: 12 passed, 0 failed.
  - `pytest tests/test_pdf_fast_english_wireless.py`: 8 passed, 0 failed.
  - `cargo fmt --check`: 0 警告。
  - `git diff --check`: 0 警告。

## 基准测试测量工件 (Benchmark Artifacts)

在 `--suite english-wireless --fixture tests/fixtures/rust_migration/english/english_wireless.json --warmups 1 --runs 3` 下采集四路对比：
- 基线输出: `output/rust_migration_benchmark/sprint-009/baseline/english-wireless-python.json`
- Python 输出: `output/rust_migration_benchmark/sprint-009/python/english-wireless-python.json`
- Shadow 输出: `output/rust_migration_benchmark/sprint-009/shadow/english-wireless-shadow.json`
- Rust 输出: `output/rust_migration_benchmark/sprint-009/rust/english-wireless-rust.json`
- 对比报告: `docs/superpowers/rust-migration/evaluations/sprint-009-benchmark.md`
  - equal: True
  - differences_count: 0
  - 结构化输出结果完全一致，无冲突、无缺失。
