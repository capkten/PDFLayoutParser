# Task 1 完整报告：统一 Rust 路由和可观测性

## 状态

实现已完成，提交信息为 `feat: unify rust routing diagnostics`（提交 hash 以最终 Git 提交为准）。

## 实现内容

问题根因位于 `src/hexai_pdf_parser/rust_adapter.py` 的 `run_python_or_rust`：

1. `mode` 未先做类型校验，`None` 直接调用 `.strip()`，导致 `AttributeError`，而不是路由契约要求的 `ValueError`。
2. 诊断 path 使用 `path or "unknown"`，全空白字符串被视为有效 path，返回了 `'   '` 而非 `'unknown'`。

最小修复为：

- 增加 `_normalize_diagnostic_path`，统一处理空白 path，并用于路由诊断和 `assert_equivalent` 的 mismatch 诊断。
- 在 `run_python_or_rust` 调用 `.strip()` 前拒绝非字符串 mode；保留 `python`、`shadow`、`rust` 的现有路由语义和错误消息格式。

未修改 `scripts/pdf_diff_review.py`、Rust 源码、其他生产模块或算法路径。中文/混合 wireless 的既有约束不受本任务影响；本任务没有回读 page words，也没有进行页面级输出重跑。

## TDD RED 证据

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_rust_migration_routing.py -vv
```

真实输出摘要：

```text
============================= test session starts =============================
collected 12 items
...
tests/test_rust_migration_routing.py::test_diagnostic_path_is_normalized_and_has_common_fields FAILED [ 75%]
tests/test_rust_migration_routing.py::test_run_python_or_rust_rejects_non_string_mode FAILED [ 83%]
...
E       AssertionError: assert '   ' == 'unknown'
E       AttributeError: 'NoneType' object has no attribute 'strip'
================== 2 failed, 10 passed, 5 warnings in 0.90s ===================
```

这两个失败均为目标行为缺失，不是收集错误或测试拼写错误。

## TDD GREEN 证据

同一命令在实现后重新执行：

```text
============================= test session starts =============================
collected 12 items
tests/test_rust_migration_routing.py::test_default_mode_is_python PASSED [  8%]
tests/test_rust_migration_routing.py::test_valid_modes PASSED            [ 16%]
tests/test_rust_migration_routing.py::test_invalid_mode_raises PASSED    [ 25%]
tests/test_rust_migration_routing.py::test_path_specific_feature_gate PASSED [ 33%]
tests/test_rust_migration_routing.py::test_run_python_or_rust_python_mode PASSED [ 41%]
tests/test_rust_migration_routing.py::test_run_python_or_rust_rust_mode_success PASSED [ 50%]
tests/test_rust_migration_routing.py::test_run_python_or_rust_routes_sentinel_without_changing_shadow_result PASSED [ 58%]
tests/test_rust_migration_routing.py::test_run_python_or_rust_rust_mode_fallback PASSED [ 66%]
tests/test_rust_migration_routing.py::test_diagnostic_path_is_normalized_and_has_common_fields PASSED [ 75%]
tests/test_rust_migration_routing.py::test_run_python_or_rust_rejects_non_string_mode PASSED [ 83%]
tests/test_rust_migration_routing.py::test_run_python_or_rust_shadow_mode PASSED [ 91%]
tests/test_rust_migration_routing.py::test_assert_equivalent PASSED      [100%]
======================= 12 passed, 5 warnings in 0.36s ========================
```

## 相关测试证据

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_pdf_fast_binding.py tests/test_pdf_fast_dto.py tests/test_pdf_fast_english_wireless.py tests/test_pdf_fast_shared_geometry.py tests/test_pdf_fast_shared_recovery.py tests/test_pdf_fast_table_normalization.py tests/test_pdf_fast_wired.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_wireless.py tests/test_rust_migration_routing.py
```

真实输出：

```text
........................................................................ [ 66%]
....................................                                     [100%]
108 passed, 5 warnings in 0.92s
```

警告为既有 PyMuPDF `SwigPyPacked`、`SwigPyObject`、`swigvarlink` 类型的 `DeprecationWarning`，测试退出码为 0。

## 差异检查

命令：

```powershell
git diff --check
```

真实输出：无输出，退出码 `0`。

## 修改文件清单

- `src/hexai_pdf_parser/rust_adapter.py`：生产路由校验和诊断 path 归一化。
- `tests/test_rust_migration_routing.py`：上一代理已正确留下 sentinel、fallback、空白 path 和非字符串 mode 测试；本任务未再修改该文件。
- `迁移记录/sprints/sprint-001.md`：中文 Sprint 记录。
- `.superpowers/sdd/task-1-report.md`：本报告。

工作区中已有的 `.superpowers/sdd/progress.md`、Task 2/3/4 简报和其他迁移记录目录均未改动、未清理。

## 自审结果

- `python` 模式仍只调用 Python。
- `shadow` 模式仍返回 Python 结果，并记录 mismatch 或 Rust 异常诊断。
- `rust` 模式仍优先返回 Rust 结果，异常时记录 `rust_fallback` 并回退 Python。
- 每条本任务涉及的路由诊断保留 `schema_version`、`status`、`path`。
- 未使用裸 `except Exception: pass`，未触碰算法迁移和 `scripts/pdf_diff_review.py`。

## 未解决事项

- 当前测试环境仍产生 5 个既有弃用警告。
- CodeGraph 索引未初始化：`codegraph query run_python_or_rust` 返回 `CodeGraph not initialized`；最初的 `codegraph explore ...` 返回 `unknown command 'explore'`。因此使用本地源码、测试和 diff 完成调用链核对。
- 本 Task 不要求且未执行页面级 PDF/PNG 验收。
