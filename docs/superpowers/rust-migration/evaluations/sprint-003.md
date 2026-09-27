# Sprint 003 独立评估：迁移有线几何和线网区域算法

## 结论

**Recommendation: PASS**

评估范围针对当前 Sprint 003 交付物（Commit `facb350`），在 `codex/pdf-fast-rust-migration` 工作树完成。有线表格提取核心纯几何与区域拓扑算法（`merge_h_lines`, `merge_v_lines`, `merge_region_line_coordinates`, `lines_intersect`, `find_table_regions`, `snap_coordinates`, `snap_grid_coordinates`, `complete_partial_outer_boundaries`）已全部成功迁移至 Rust (PyO3) 并释放 GIL。在 `wired_table_extractor.py` 中实现了基于 `PDF_RUST_MODE` 的三路解耦。全部自动化测试套件（131 项 pytest 测试、6 项 cargo 单元测试）100% 通过。在四路（baseline, python, shadow, rust）基准测试比对中，输出完全一致（`equal: true, differences_count: 0`）。生产路由默认保持为 `python`。

## 范围与验收核对

| 验收项 | 结果 | 证据 |
|---|---|---|
| **Sprint 范围控制** | PASS | 仅迁移了计划规定的纯几何与线网区域算法，无多余抽象或非计划改动；生产默认路由保持为 `python`。 |
| **算法保真与确定性** | PASS | 严格保证 Python 的银行家舍入排序、间距容差合并规则、连通图双向 BFS/DFS 查找以及外边界完整覆盖度判定；测试覆盖全部边界场景。 |
| **GIL 释放** | PASS | 在 `rust/lib.rs` 中密集计算均使用 `py.allow_threads` 包裹，确保并发执行能力。 |
| **三路路由与 Shadow 对比** | PASS | `wired_table_extractor.py` 支持 `PDF_RUST_MODE` 读取；在 Python 和 Rust 模式下均通过全部已有测试。 |
| **TDD 流程合规** | PASS | 先编写 `tests/test_pdf_fast_wired.py` 验证 RED（`ImportError: cannot import name 'merge_v_lines'`），实现后全量通过验证 GREEN（12 passed）。 |
| **测试套件与代码规范** | PASS | `cargo fmt --check` exit 0；`cargo test` 6 passed；`pytest` 131 项测试全部通过；`git diff --check` exit 0。 |
| **基准测试与差异报告** | PASS | 四路（baseline, python, shadow, rust）各 10 轮运行成功，`compare_rust_migration.py` 生成报告确认 `equal: true, differences_count: 0`。 |

## 复现凭证

### 1. 自动化测试执行
```powershell
cargo fmt --check
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_pdf_fast_dto.py tests/test_pdf_fast_binding.py tests/test_rust_migration_benchmark.py
$env:PDF_RUST_MODE='rust'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py
```
- Cargo 测试结果: `6 passed; 0 failed; 0 ignored; finished in 0.00s`。
- Pytest 测试结果: `131 passed, 5 warnings in 12.75s`（默认模式）；`75 passed in 12.27s`（Rust 模式）。

### 2. 基准测试比对
```powershell
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-003/baseline/wired-geometry-python.json --python output/rust_migration_benchmark/sprint-003/python/wired-geometry-python.json --rust output/rust_migration_benchmark/sprint-003/rust/wired-geometry-rust.json --shadow output/rust_migration_benchmark/sprint-003/shadow/wired-geometry-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-003-benchmark.md
```
- 比对输出:
  - `equal: True`
  - `differences_count: 0`

## 结论与后续

Sprint 003 所有 5 个步骤全部完成并通过独立评估，验收判定为 **PASS**。可以推进至 **Sprint 004：迁移有线 Cell、文字归属和区域装配**。
