# Sprint 002：扩展统一 DTO 和 PyO3 批量边界

## 目标与范围

实现纯 Rust 拥有的强类型 DTO 结构体系统与跨 PyO3 边界的往返转换（`roundtrip_dto`），严格落实 `dto-schema.md` 中的所有类型定义和边界安全约束：
1. 强制 `schema_version = 1`，非 1 立即抛错 `PyValueError`。
2. 强制浮点数有限性检查（`val.is_finite()`），遇到 NaN、Inf 或 -Inf 立即抛错 `PyValueError`，杜绝静默接收或转换。
3. `PageDto.rotation` 严格限制在 `0, 90, 180, 270`，其余值报错拒绝。
4. 必填字段缺失严格抛错，可选字段显式支持 `None / null`，不猜测隐式默认值。
5. 所有核心算法只消费 Rust owned DTO，不持有 PyMuPDF `Page` 对象，不回调 Python。

## 拥有的文件与变更清单

- `rust/types.rs`: 新增完整的统一 owned DTO 结构体及 `from_py` / `to_py` 序列化与严格校验：
  - `PageDto`, `Rect4`, `Line4`, `LineDto`, `DrawingDto`, `OrderedRectDto`, `WordDto`, `CharacterDto`, `SourcePositionDto`, `NativeSpanDto`, `TextRunDto`, `AtomDto`, `ColumnBandDto`, `RegionDto`, `GridDto`, `PhysicalCell`, `CellDto`, `LogicalGridDto`, `TableCandidateDto`, `RowClusterDto`, `ColumnClusterDto`, `StructureConfig`, `BackgroundDto`, `BackgroundGroupDto`, `RowBandDto`, `DiagnosticValueDto`, `DiagnosticDto`。
  - `roundtrip_dto_py`: 分发执行各 DTO 的从 Python 字典构建 struct 并转换回 Python 字典的往返操作。
- `rust/lib.rs`: 引入 `pub mod types;` 并向 PyO3 扩展模块导出 `roundtrip_dto`。
- `src/hexai_pdf_parser/rust_adapter.py`: 导出 `roundtrip_dto(dto_type: str, data: Dict[str, Any]) -> Dict[str, Any]`。
- `tests/fixtures/rust_migration/dto/basic.json`: 提供包含页面、带多级单元格与物理 Cell 来源引用的表格、原生 span 与字符框等完整字段的 DTO fixture。
- `tests/test_pdf_fast_dto.py`: 编写 18 项覆盖 NaN/Inf 拒绝、旋转校验、负坐标、CJK 字符、可选字段为 None、空槽位网格、Diagnostic 错误类型以及必填项缺失的单元测试。
- `docs/superpowers/rust-migration/evaluations/sprint-002-benchmark.md`: 生成 Sprint 002 四路对比报告。

## 验证与测试结果

- **TDD RED 阶段**: 在实现 Rust struct 前运行测试，确认 `ImportError: cannot import name 'roundtrip_dto'` 失败。
- **TDD GREEN 阶段**:
  - `cargo fmt --check`: 格式合规，无任何警告。
  - `cargo test`: 6 passed, 0 failed, 0 ignored.
  - `python -m pytest -q tests/test_pdf_fast_dto.py tests/test_pdf_fast_binding.py`: 24 passed, 0 failed.
  - `python -m pytest -q tests/test_rust_migration_benchmark.py`: 32 passed, 0 failed.
- **`git diff --check`**: 检查通过，无额外空白或冲突标记。

## 基准测试测量工件 (Benchmark Artifacts)

按计划在 `--suite dto --fixture tests/fixtures/rust_migration/dto/basic.json --warmups 3 --runs 10` 下采集四路对比：
- 基线输出: `output/rust_migration_benchmark/sprint-002/baseline/dto-python.json`
- Python 输出: `output/rust_migration_benchmark/sprint-002/python/dto-python.json`
- Shadow 输出: `output/rust_migration_benchmark/sprint-002/shadow/dto-shadow.json`
- Rust 输出: `output/rust_migration_benchmark/sprint-002/rust/dto-rust.json`
- 对比报告: `docs/superpowers/rust-migration/evaluations/sprint-002-benchmark.md`
  - `equal`: True
  - `differences_count`: 0
  - `algorithm_p95 speedup`: 1.0
  - `total_p95 speedup`: ~0.995 (FFI 往返额外验证耗时微小)
