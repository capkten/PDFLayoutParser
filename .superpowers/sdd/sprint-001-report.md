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
