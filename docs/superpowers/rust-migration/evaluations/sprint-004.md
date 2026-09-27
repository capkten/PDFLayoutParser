# Sprint 004 独立评估：迁移有线 Cell、文字归属和区域装配

## 结论

**Recommendation: PASS**

评估范围针对当前 Sprint 004 交付物（Commit `b213840`），在 `codex/pdf-fast-rust-migration` 工作树完成。有线表格提取核心纯几何线网 Cell 拓扑生成、幽灵行修剪、超切列合并、文字归属与区域装配算法（`build_cells_for_region`, `trim_ghost_edge_rows`, `merge_oversegmented_line_columns`, `assign_text_to_line_cells`, `extract_wired_region`）已全部成功迁移至 Rust (PyO3) 并释放 GIL。在 `wired_table_extractor.py` 中实现了基于 `PDF_RUST_MODE` 的三路解耦与页面级 words/raw_chars 集中单次获取。全部自动化测试套件（90 项 focused pytest 测试、6 项 cargo 单元测试）100% 通过。在真实 PDF 页面（P196, P415）端到端提取比对及四路（baseline, python, shadow, rust）基准测试比对中，输出完全一致（`equal: true, differences_count: 0`）。Rust 相比 Python baseline 算法 P95 加速比达到 **7.30x**，端到端 P95 加速比达到 **2.01x**。生产路由默认保持为 `python`。

## 范围与验收核对

| 验收项 | 结果 | 证据 |
|---|---|---|
| **Sprint 范围控制** | PASS | 仅修改了 Sprint 004 规定的有线 Cell、幽灵行修剪、超切列合并和文字归属算法与导出工具，无多余抽象或非计划改动；生产默认路由保持为 `python`。 |
| **算法保真与确定性** | PASS | 严格保证 Python 的连通分量矩形切分、物理横线支撑幽灵行修剪、超切空列合并、基于银行家舍入的字词中心点排序及字符级边界拆分；测试覆盖全部边界拓扑。 |
| **GIL 释放** | PASS | 在 `rust/lib.rs` 中密集计算均使用 `py.allow_threads` 包裹，确保并发执行能力。 |
| **不回读 words 约束** | PASS | 在 `WiredTableExtractor.extract()` 页面入口一次性提取并缓存 `words` 与 `raw_chars`；通过 `PageSpy` 验证全流程对 `get_text("words")` 与 `get_text("rawdict")` 的调用次数均为 1 次，Rust 只接收 WordDto 与 CharacterDto。 |
| **三路路由与 Shadow 对比** | PASS | `wired_table_extractor.py` 支持 `PDF_RUST_MODE` 读取；在 Python、Rust 和 Shadow 模式下均通过全部 90 项 focused 专项测试。 |
| **TDD 流程合规** | PASS | 先编写 `tests/test_pdf_fast_wired.py` 验证 RED（`ImportError: cannot import name 'build_cells_for_region'`），实现后全量通过验证 GREEN（20 passed）。 |
| **测试套件与代码规范** | PASS | `cargo fmt --check` exit 0；`cargo test` 6 passed；`pytest` focused 专项 90 项测试全部通过；`git diff --check` exit 0。 |
| **真实页面对比** | PASS | 运行 `export_rust_migration_e2e.py` 重跑真实 PDF `fix/zh_all_table_pages.pdf` P196 与 P415，manifest 对比确认 `equal: true, differences_count: 0`。 |
| **基准测试与差异报告** | PASS | 四路（baseline, python, shadow, rust）各 10 轮运行成功，`compare_rust_migration.py` 确认 `equal: true, differences_count: 0`；算法 P95 加速比达 7.30x。 |

## 复现凭证

### 1. 自动化测试执行
```powershell
cargo fmt --check
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_wireless_extractor_split.py
$env:PDF_RUST_MODE='rust'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_wireless_extractor_split.py
$env:PDF_RUST_MODE='shadow'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_wireless_extractor_split.py
```
- Cargo 测试结果: `6 passed; 0 failed; 0 ignored; finished in 0.00s`。
- Pytest 测试结果: `90 passed, 5 warnings`（Python、Rust、Shadow 三种模式下均 100% 通过）。

### 2. 端到端真实页面验证
```powershell
$env:PDF_RUST_MODE='python'
python scripts/export_rust_migration_e2e.py --mode python --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --dpi 200 --output-dir output/pdf_rust_migration_wired_python_20260916
$env:PDF_RUST_MODE='rust'
python scripts/export_rust_migration_e2e.py --mode rust --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --dpi 200 --output-dir output/pdf_rust_migration_wired_rust_20260916
python scripts/compare_rust_migration.py --manifests output/pdf_rust_migration_wired_python_20260916/manifest.json output/pdf_rust_migration_wired_rust_20260916/manifest.json --report docs/superpowers/rust-migration/evaluations/sprint-004-pages.md
```
- 比对输出:
  - `equal: True`
  - `differences_count`: 0

### 3. 基准测试比对
```powershell
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-004/baseline/wired-cells-python.json --python output/rust_migration_benchmark/sprint-004/python/wired-cells-python.json --rust output/rust_migration_benchmark/sprint-004/rust/wired-cells-rust.json --shadow output/rust_migration_benchmark/sprint-004/shadow/wired-cells-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-004-benchmark.md
```
- 比对输出:
  - `equal: True`
  - `differences_count`: 0
  - `algorithm_p95 speedup`: 7.30x
  - `total_p95 speedup`: 2.01x

## 结论与后续

Sprint 004 所有 5 个步骤全部完成并通过独立评估，验收判定为 **PASS**。可以推进至 **Sprint 005：抽取共享几何、排序和候选算法**。
