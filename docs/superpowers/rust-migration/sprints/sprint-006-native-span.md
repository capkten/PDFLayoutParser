# Sprint 006：迁移无线表格 Native Span、Atom 和 Text Run 数据流

## 目标与范围

将中文无线表格 Native Span 数据流、Atom 聚类成词、Text Run 构建、换行续写合并以及阅读顺序推断算法迁移到 Rust (PyO3) 并释放 GIL：
1. `build_text_runs`: 将区域内视觉连续的 NativeSpanDto 片段依据 CJK 白名单词对规则（覆盖 20 组大字距白名单）、单字限制（普通 CJK 严格 1.25 倍字距，防止相邻字段误并）以及 ASCII/混合文字成词规则聚类构建 TextRunDto。
2. `build_atoms`: 将 TextRunDto 转化为后续网格划分消费的 AtomDto，支持可选区域限定过滤。
3. `merge_wrapped_rows`: 识别相邻且纵向紧密的同一字段换行续写 Atom 并安全合并。
4. `infer_output_order_mode`: 依据几何间距与阅读顺序推断表格排版模式（如 `row_interleaved` 与 `columnar`）。
5. `recover_native_candidates`: 消费 NativeRecoveryInput（包含 PageDto, NativeSpanDto[], RegionDto, StructureConfig），一次性在 Rust 内部完成端到端无线表格候选初筛与网格拓扑检测，输出 NativeRecoveryOutput。

遵循中文无线表格约束：
- 纯消费 NativeSpanDto，禁止调用 `page.get_text("words")`，严格不回读 words。
- 白名单词对大字距最大允许 2.5 倍字距间距；非白名单普通 CJK 单字严格限制在 1.25 倍字距以内，拒绝误并“男/女”等反例。

## 拥有的文件与变更清单

- `rust/native_span.rs`: 实现 `build_text_runs`、`build_atoms`、`merge_wrapped_rows`、`infer_output_order_mode`、`recover_native_candidates` 算法内核及 Rust 单元测试。
- `rust/types.rs`: 扩展 `NativeRecoveryInput`、`NativeRecoveryOutput` DTO 结构，登记到 `roundtrip_dto`。
- `rust/lib.rs`: 导出上述 5 个算子并在密集计算处使用 `py.allow_threads` 释放 GIL。
- `src/hexai_pdf_parser/rust_adapter.py`: 暴露强类型 Python 包装签名。
- `tests/test_pdf_fast_wireless.py`: 新增 8 个针对白名单词对合并、反例不合并、ASCII 混合成词、Atom 构建、换行续写、阅读顺序推断及 PageSpy（确保无 words 回读）的单元测试。
- `tests/fixtures/rust_migration/wireless/native_span.json`: 无线 native span 与 atom 基准测试工件（480 spans）。
- `scripts/benchmark_rust_migration.py`: 增加 `wireless_native_span` fixture 的四路分段采集支持。
- `docs/superpowers/rust-migration/evaluations/sprint-006-benchmark.md`: 四路基准测试比对报告。
- `docs/superpowers/rust-migration/sprints/sprint-006-native-span.md`: 本总结文档。
- `docs/superpowers/rust-migration/evaluations/sprint-006.md`: 独立评估报告。

## 验证与测试结果

- **TDD RED 阶段**: 先编写 `tests/test_pdf_fast_wireless.py`，确认 `ImportError: cannot import name 'build_text_runs'` 预期失败。
- **TDD GREEN 阶段**:
 - cargo test: 8 passed, 0 failed.
 - pytest tests/test_pdf_fast_wireless.py: 8 passed, 0 failed.
 - 核心 fast 测试套件：69 passed in 0.60s.
 - git diff --check: 检查通过，0 警告。

## 基准测试测量工件 (Benchmark Artifacts)

在 --suite native-span --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 2 --runs 5 下采集四路对比：
- 基线输出: output/benchmarks/sprint-006/native-span-python.json
- Python 输出: output/benchmarks/sprint-006/native-span-python.json
- Shadow 输出: output/benchmarks/sprint-006/native-span-shadow.json
- Rust 输出: output/benchmarks/sprint-006/native-span-rust.json
- 对比报告: docs/superpowers/rust-migration/evaluations/sprint-006-benchmark.md
 - equal: True
 - differences_count: 0
 - **Algorithm P95 Speedup**: **1.32x**
 - **Total P95 Speedup**: **1.46x**
