# Sprint 008：迁移共享 Native Recovery 与候选选择算子

## 目标与范围

将共享无线表格恢复内核与候选选择迁移至 Rust (PyO3) 并释放 GIL：
1. `table_quality`: 评估表格候选质量评分，与 Python `(confidence, populated, size)` 字典序一致。
2. `select_candidates`: 依据 excluded/allowed 区域过滤候选，并在重叠阈值 >= 0.20 时依据质量评分解决重叠冲突。
3. `recover_wireless_tables`: 端到端无线表格恢复管线，纯消费 DTO，支持 `PDF_RUST_MODE` (python, shadow, rust) 路由，严格禁止回读 `words`。

遵循中文无线表格约束：
- 结构恢复阶段只消费 NativeSpanDto、AtomDto、ColumnBandDto、PhysicalCell、LogicalGridDto 和 CellDto，严格禁止再次调用 `page.get_text("words")`。
- 独立字段默认保留为独立叶子列；不得仅因两个 atom/span 位于同一候选槽位就合并它们。
- 所有未被现有 rowspan/colspan 覆盖的槽位均生成独立 text=""、1x1 Cell，按推断网格边界直接切分。
- 最终每个逻辑槽位必须恰好被一个 Cell 占用，任何跨度调整后重新执行 occupancy conflict 检查，冲突结果不得进入最终表格。

## 拥有的文件与变更清单

- `rust/wireless_structure.rs`: 实现 `table_quality`、`select_candidates`、`recover_wireless_tables` 算法内核及 Rust 单元测试。
- `rust/types.rs`: 新增 `WirelessRecoveryInput`、`WirelessRecoveryOutput` DTO 结构，登记到 `roundtrip_dto`。
- `rust/lib.rs`: 导出上述 3 个算子并在密集计算处使用 `py.allow_threads` 释放 GIL。
- `src/hexai_pdf_parser/rust_adapter.py`: 暴露强类型 Python 包装签名。
- `src/hexai_pdf_parser/tables/wireless_table_recovery.py`: 接入 `PDF_RUST_MODE` 路由（默认 python，支持 shadow 与 rust），保护原诊断结构格式兼容性。
- `tests/test_pdf_fast_shared_recovery.py`: 新增 6 个针对质量评分、候选选择过滤与冲突排除、DTO roundtrip、端到端 recover_wireless_tables 以及 PageSpy（确保无 words 回读）的单元测试。
- `scripts/benchmark_rust_migration.py`: 增加 `shared-wireless` suite 测量支持。
- `docs/superpowers/rust-migration/evaluations/sprint-008-benchmark.md`: 四路基准测试比对报告。
- `docs/superpowers/rust-migration/sprints/sprint-008-shared-recovery.md`: 本总结文档。
- `docs/superpowers/rust-migration/evaluations/sprint-008.md`: 独立评估报告。

## 验证与测试结果

- **TDD 单元测试**:
  - `cargo test`: 全部通过。
  - `pytest tests/test_pdf_fast_shared_recovery.py`: 6 passed, 0 failed.
  - 全量无线测试套件：244 passed, 0 failed.
  - `cargo fmt --check`: 格式检查通过，0 警告。
  - `git diff --check`: 检查通过，0 警告。

## 基准测试测量工件 (Benchmark Artifacts)

在 `--suite shared-wireless --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 1 --runs 3` 下采集四路对比：
- 基线输出: `output/rust_migration_benchmark/sprint-008/baseline/shared-wireless-python.json`
- Python 输出: `output/rust_migration_benchmark/sprint-008/python/shared-wireless-python.json`
- Shadow 输出: `output/rust_migration_benchmark/sprint-008/shadow/shared-wireless-shadow.json`
- Rust 输出: `output/rust_migration_benchmark/sprint-008/rust/shared-wireless-rust.json`
- 对比报告: `docs/superpowers/rust-migration/evaluations/sprint-008-benchmark.md`
  - equal: True
  - differences_count: 0
  - 结构化输出结果完全一致，无冲突、无缺失。
