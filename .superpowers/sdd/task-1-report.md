# Task 1 完整报告：统一 Rust 路由和可观测性

## 状态

Task 1 路由实现已完成；本轮已完成 wired shadow 探针复审修复，提交 hash 以最终 Git 提交为准。

## 实现内容

问题根因位于 `src/hexai_pdf_parser/rust_adapter.py` 的 `run_python_or_rust`：

1. `mode` 未先做类型校验，`None` 直接调用 `.strip()`，导致 `AttributeError`，而不是路由契约要求的 `ValueError`。
2. 诊断 path 使用 `path or "unknown"`，全空白字符串被视为有效 path，返回了 `'   '` 而非 `'unknown'`。

最小修复为：

- 增加 `_normalize_diagnostic_path`，统一处理空白 path，并用于路由诊断和 `assert_equivalent` 的 mismatch 诊断。
- 在 `run_python_or_rust` 调用 `.strip()` 前拒绝非字符串 mode；保留 `python`、`shadow`、`rust` 的现有路由语义和错误消息格式。

未修改 `scripts/pdf_diff_review.py`、Rust 源码或算法路径。中文/混合 wireless 的既有约束不受本任务影响；本任务没有回读 page words，也没有进行页面级输出重跑。wired 复审修复只调整 shadow 探针的路由和异常诊断，不改变 `extract()` 的返回值。

`af15c28` 在 RED 阶段新增了 `tests/test_rust_migration_routing.py` 中的三类回归测试：Rust sentinel 路由、空白 path 归一化、非字符串 mode 校验。该测试文件并非“上一代理已留下且本任务未修改”；本任务确实新增了这些测试。Rust 异常 fallback 测试为既有测试，继续用于验证原有回退语义。

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
108 passed in 1.11s
```

该命令使用 Python 3.12 并禁用外部 pytest 插件，退出码为 0。此前已真实取得的同一集合结果 `108 passed, 5 warnings in 0.92s` 仍保留在 Sprint 记录的历史证据中。

## 差异检查

命令：

```powershell
git diff --check
```

真实输出：无输出，退出码 `0`。

## 修改文件清单

- `src/hexai_pdf_parser/rust_adapter.py`：生产路由校验和诊断 path 归一化。
- `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py`：本轮复审修复 wired shadow 探针，统一 mode 路由和 Rust 异常诊断。
- `tests/test_rust_migration_routing.py`：本任务 RED 阶段新增 sentinel、空白 path 和非字符串 mode 测试；保留既有 Rust fallback 测试。
- `tests/test_wired_table_extractor.py`：本轮新增 wired shadow 路由回归测试。
- `迁移记录/sprints/sprint-001.md`：中文 Sprint 记录。
- `.superpowers/sdd/task-1-report.md`：本报告。

工作区中已有的 `.superpowers/sdd/progress.md`、Task 2/3/4 简报和其他迁移记录目录均未改动、未清理。

## 自审结果

- `python` 模式仍只调用 Python。
- `shadow` 模式仍返回 Python 结果，并记录 mismatch 或 Rust 异常诊断。
- `rust` 模式仍优先返回 Rust 结果，异常时记录 `rust_fallback` 并回退 Python。
- 每条本任务涉及的路由诊断保留 `schema_version`、`status`、`path`。
- 未使用裸 `except Exception: pass`，未触碰算法迁移和 `scripts/pdf_diff_review.py`。
- wired shadow 探针只在 `get_rust_mode("wired") == "shadow"` 时运行；统一路由返回的 Python 结果仍未改变 `extract()` 的返回值。

## 未解决事项

- 当前 Python 3.12 相关测试未产生阻断性错误；默认 `pytest -q tests/test_rust_migration_routing.py` 使用的解释器在 conftest 收集阶段因 `ModuleNotFoundError: No module named 'fitz'` 退出，不能写成代码测试通过。本轮没有遇到 numpy/OpenCV 错误。
- CodeGraph 索引未初始化：`codegraph query run_python_or_rust` 返回 `CodeGraph not initialized`；`codegraph explore ...` 返回 `unknown command 'explore'`。因此使用本地源码、测试和 diff 完成调用链核对。
- 本 Task 不要求且未执行页面级 PDF/PNG 验收。

## Reviewer 反馈后的覆盖重跑

本轮修改了 wired extractor、wired 回归测试和本报告/Sprint 记录，未修改 Rust 算法、Task 2+ 文件或其他生产模块。

路由覆盖命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_rust_migration_routing.py
```

路由测试本轮真实结果：

```text
............                                                             [100%]
12 passed in 0.50s
```

退出码为 `0`。本次使用 Python 3.12 解释器运行。wired 相关命令 `tests/test_wired_table_extractor.py tests/test_pdf_fast_wired.py` 真实结果为 `84 passed in 5.27s`。默认 `pytest` 入口本轮实际在 conftest 收集阶段因缺少 `fitz` 失败；该环境事实不计入通过数字。
