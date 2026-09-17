# Sprint 007：迁移中文/混合无线表格结构恢复算子

## 目标与范围

将中文/混合语言无线表格的结构恢复内核迁移至 Rust (PyO3) 并释放 GIL：
1. `infer_column_bands`: 依据区域与 Atom 的 x 重叠组件推断列带，过滤过宽跨列表头。
2. `refine_leaf_bands`: 精化叶子列带并计算表头 cutoff。
3. `build_grid`: 构建物理行与列带并完成初步单元格槽位匹配与冲突检测。
4. `build_logical_grid`: 构建逻辑网格，将未覆盖槽位严格物化为独立空 1x1 Cell（text=""），计算 empty_slots。
5. `recover_native_region`: 统一管道，整合推断列带、物理网格与逻辑网格物化，输出 NativeRegionOutput。

遵循中文无线表格约束：
- 结构恢复阶段只消费 NativeSpanDto、AtomDto、ColumnBandDto、PhysicalCell、LogicalGridDto 和 CellDto，严格禁止再次调用 `page.get_text("words")`。
- 独立字段默认保留为独立叶子列；不得仅因两个 atom/span 位于同一候选槽位就合并它们。
- 所有未被现有 rowspan/colspan 覆盖的槽位均生成独立 text=""、1x1 Cell，按推断网格边界直接切分，不合并相邻空单元格。
- 最终每个逻辑槽位必须恰好被一个 Cell 占用，任何跨度调整后重新执行 occupancy conflict 检查，冲突结果不得进入最终表格。

## 拥有的文件与变更清单

- `rust/wireless_structure.rs`: 实现 `infer_column_bands`、`refine_leaf_bands`、`build_grid`、`build_logical_grid`、`recover_native_region` 算法内核及 Rust 单元测试。
- `rust/types.rs`: 新增 `NativeRegionInput`、`NativeRegionOutput` DTO 结构，登记到 `roundtrip_dto`。
- `rust/lib.rs`: 导出上述 5 个算子并在密集计算处使用 `py.allow_threads` 释放 GIL。
- `src/hexai_pdf_parser/rust_adapter.py`: 暴露强类型 Python 包装签名。
- `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`: 接入 `PDF_RUST_MODE` 路由（默认 python，支持 shadow 与 rust）。
- `tests/test_pdf_fast_wireless_structure.py`: 新增 8 个针对列带推断、叶子精化、物理网格、空槽单元格物化、端到端区域恢复、独立叶子列不误并、槽位唯一占用及 PageSpy（确保无 words 回读）的单元测试。
- `tests/fixtures/rust_migration/wireless/chinese_structure.json`: 中文无线结构恢复基准测试工件。
- `scripts/benchmark_rust_migration.py`: 增加 `chinese_wireless_structure` fixture 的四路分段采集支持。
- `docs/superpowers/rust-migration/evaluations/sprint-007-benchmark.md`: 四路基准测试比对报告。
- `docs/superpowers/rust-migration/sprints/sprint-007-chinese-structure.md`: 本总结文档。
- `docs/superpowers/rust-migration/evaluations/sprint-007.md`: 独立评估报告。

## 验证与测试结果

- **TDD RED 阶段**: 先编写 `tests/test_pdf_fast_wireless_structure.py`，确认 `ImportError: cannot import name 'infer_column_bands'` 预期失败。
- **TDD GREEN 阶段**:
  - `cargo test`: 9 passed, 0 failed.
  - `pytest tests/test_pdf_fast_wireless_structure.py`: 8 passed, 0 failed.
  - 全量无线测试套件：230 passed, 0 failed in 2.16s。
  - `cargo fmt --check`: 格式检查通过，0 警告。
  - `git diff --check`: 检查通过，0 警告。

## 基准测试测量工件 (Benchmark Artifacts)

在 `--suite chinese-wireless --fixture tests/fixtures/rust_migration/wireless/chinese_structure.json --warmups 1 --runs 3` 下采集四路对比：
- 基线输出: `output/rust_migration_benchmark/sprint-007/baseline/chinese-wireless-python.json`
- Python 输出: `output/rust_migration_benchmark/sprint-007/python/chinese-wireless-python.json`
- Shadow 输出: `output/rust_migration_benchmark/sprint-007/shadow/chinese-wireless-shadow.json`
- Rust 输出: `output/rust_migration_benchmark/sprint-007/rust/chinese-wireless-rust.json`
- 对比报告: `docs/superpowers/rust-migration/evaluations/sprint-007-benchmark.md`
  - equal: True
  - differences_count: 0
  - 结构化输出结果完全一致，无冲突、无空槽位遗漏。
