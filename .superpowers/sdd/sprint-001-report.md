# Sprint 001 实施报告

## status

完成。已建立 benchmark harness 和 differential-comparison 基础设施，未改变生产解析路由。

## files changed

- `src/hexai_pdf_parser/debug/benchmark_utils.py`
- `src/hexai_pdf_parser/debug/rust_migration_benchmark.py`
- `scripts/benchmark_rust_migration.py`
- `scripts/compare_rust_migration.py`
- `tests/test_rust_migration_benchmark.py`
- `docs/superpowers/rust-migration/sprints/sprint-001-benchmark-baseline.md`
- `.superpowers/sdd/sprint-001-report.md`

## RED command/output

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_benchmark.py
```

默认 Python 环境因未安装 pytest 无法启动；使用项目 Python 3.12 环境执行同一命令后，收集阶段按预期失败：`ModuleNotFoundError: No module named 'hexai_pdf_parser.debug.rust_migration_benchmark'`。

## GREEN command/output

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_rust_migration_benchmark.py
```

输出：`9 passed, 5 warnings`。警告为现有 PyMuPDF SWIG 类型的弃用警告。

## fixture benchmark command/output

命令：

```powershell
python scripts/benchmark_rust_migration.py --mode python --suite fixture --pdf tests/fixtures/page_000_vector.pdf --pages 0 --warmups 1 --runs 2 --output-dir output/rust_migration_benchmark/sprint-001
```

默认解释器因缺少 `fitz` 依赖无法运行；使用项目 Python 3.12 解释器执行同一参数成功，输出：`output/rust_migration_benchmark/sprint-001/fixture-python.json`。结果包含 commit、mode、suite、input sha256、warmups、runs、timings 和 output_manifest；报告记录 `route=python_baseline`，确认 Python 模式没有调用 Rust。

## compatibility notes

- `PDF_RUST_MODE` 未设置时解析为 `python`。
- Python 生产解析 API 和默认路由未修改。
- JSON 使用 `sort_keys=True`、缩进输出和 `allow_nan=False`。
- `git diff --check` 通过。

## unresolved concerns

- `shadow` 和 `rust` 模式本 Sprint 只记录模式并运行 Python baseline，尚未接入 Rust 算法或生产路由；这是契约要求的后续范围。
- 默认 `python` 解释器缺少 pytest/fitz，验证使用项目 Python 3.12 环境完成。
- 既有 `tests/test_benchmark_utils.py` 在当前基线引用不存在的 `extract_model_profile` 和 `resolve_model_dir`，因此未作为本 Sprint 回归通过标准，也未扩大范围修复。
- CodeGraph 目录存在，但当前环境的 `codegraph` CLI 不支持 `explore` 子命令。

## commit hashes

- implementation: `b1fe9d42a7a2cce298068f3c2812f9e9ffe6e2a4`

## Sprint 001 修复记录

### reviewer findings

1. `scripts/benchmark_rust_migration.py` 的 commit provenance 原先依赖调用方当前工作目录；已改为以脚本所在仓库为基准执行 `git -C the repository containing scripts/benchmark_rust_migration.py rev-parse HEAD`，无法解析时显式抛出 `RuntimeError`。
2. `hexai_pdf_parser.debug.benchmark_utils.summarize_timings` 原先缺少百分位统计；已将 `count`、`total`、`mean`、`min`、`max`、`p50`、`p95`、`p99` 统一到该公共实现，Rust migration 模块改为直接复用它。

### RED command/output

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_rust_migration_benchmark.py
```

输出：`2 failed, 9 passed`。失败分别为公共 debug API 缺少 `p50`，以及临时 cwd 下 commit 字段为 `unknown` 而非当前 worktree HEAD。

按契约运行完整 Sprint 测试命令时，收集阶段被既有问题阻断：`tests/test_benchmark_utils.py` 导入的 `extract_model_profile` 不存在于当前 `hexai_pdf_parser.benchmark_utils` 别名模块；未修改该非本修复范围问题。

### GREEN command/output

修复后聚焦命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_rust_migration_benchmark.py
```

输出：`11 passed, 5 warnings`。警告为现有 PyMuPDF SWIG 弃用警告。

`git diff --check` 通过。

### fixture verification output

在 `C:\Users\23662\AppData\Local\Temp\pdf-layout-parser-sprint-001-repair-cwd-final`（非仓库 cwd）运行 fixture benchmark：

```text
C:\Users\23662\AppData\Local\Temp\pdf-layout-parser-sprint-001-repair-cwd-final\out\fixture-python.json
commit=740f2fd98407bfeae5a0ecac69f9461c2c640e31
expected=740f2fd98407bfeae5a0ecac69f9461c2c640e31
match=True
```

### compatibility notes

- 只修改 benchmark commit provenance、公共 timing summary 及其回归测试；未修改生产解析、Rust 算法、路由默认值或其他文件。
- `rust_migration_benchmark.summarize_timings` 仍保持原导入接口，但实现来自 `debug.benchmark_utils` 的统一公共函数。

### unresolved concerns

- 完整 Sprint 测试仍受既有 `tests/test_benchmark_utils.py` 收集错误影响；该错误与本修复无关，且按范围未修复。
- 聚焦测试存在 5 个现有 PyMuPDF SWIG 弃用警告。

### repair commit hashes

- repair implementation: `740f2fd98407bfeae5a0ecac69f9461c2c640e31`

## Sprint 001 bounded repair 2

### reviewer finding

`hexai_pdf_parser.benchmark_utils.summarize_timings` is a legacy public alias whose result contract is exactly `count`, `total`, `mean`, `min`, and `max`. The prior repair widened that result with percentiles for migration reporting, so the benchmark-specific percentile requirement had to move to an explicit separate API.

### RED command/output

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_rust_migration_benchmark.py
```

输出：收集阶段失败，`ImportError: cannot import name 'summarize_timings_with_percentiles'`；这是新增失败测试在实现前对缺失 API 的预期 RED。

### GREEN command/output

聚焦 benchmark 测试：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_rust_migration_benchmark.py
```

输出：`12 passed, 5 warnings`。警告为现有 PyMuPDF SWIG 类型弃用警告。

完整契约测试命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_rust_migration_benchmark.py tests/test_benchmark_utils.py
```

输出：benchmark 测试通过，但 `tests/test_benchmark_utils.py` 收集阶段仍因既有的 `extract_model_profile` 导入错误失败；未扩大本修复范围处理该问题。

### fixture benchmark verification

命令：

```powershell
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' scripts/benchmark_rust_migration.py --mode python --suite fixture --pdf tests/fixtures/page_000_vector.pdf --pages 0 --warmups 1 --runs 2 --output-dir output/rust_migration_benchmark/sprint-001-repair-2
```

输出：`output/rust_migration_benchmark/sprint-001-repair-2/fixture-python.json`；JSON 的 `timings` 包含 `p50`、`p95`、`p99`，且 `route` 为 `python_baseline`。

源代码 API 检查结果：legacy keys 为 `['count', 'max', 'mean', 'min', 'total']`；percentile-aware keys 额外包含 `p50`、`p95`、`p99`。

### compatibility notes

- `summarize_timings` 保持五键 legacy 结果不变。
- 新增 `summarize_timings_with_percentiles`；migration benchmark 通过该实现提供百分位统计，未重复实现统计逻辑。
- 更新 migration plan/spec，明确 legacy API 与 enriched migration report API 的边界。
- `git diff --check` 通过；未修改生产解析、Rust 算法、路由默认值或非本修复范围代码。

### unresolved concerns

- 完整 Sprint 测试仍受既有 `tests/test_benchmark_utils.py` 收集错误影响。
- 聚焦测试保留 5 个现有 PyMuPDF SWIG 弃用警告。

### repair commit hashes

- repair implementation: `de1bbb3`
