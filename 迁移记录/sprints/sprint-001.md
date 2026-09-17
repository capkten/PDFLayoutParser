# Sprint 001：统一 Rust 路由和可观测性

## 目标

统一 `run_python_or_rust(mode, python_fn, rust_fn, input_dto=None, path="")` 的路由行为和诊断字段，保持 Python 公共返回结构兼容。允许模式为 `python`、`shadow`、`rust`。

## 根因与判定

- `src/hexai_pdf_parser/rust_adapter.py:run_python_or_rust` 原先直接调用 `mode.strip()`，`mode=None` 在模式校验前抛出 `AttributeError`，不符合入口契约要求的 `ValueError`。
- 路由诊断原先使用 `path or "unknown"`，只能处理空字符串，不能把全空白 path 归一化为 `unknown`。
- Rust 成功、shadow mismatch、Rust 异常回退的既有路由语义无需改变；Rust 异常仍统一记录 `rust_fallback` 后回退 Python。

## 实现

- 增加 `_normalize_diagnostic_path`，对非空字符串执行去首尾空白，对空字符串、全空白和非字符串统一返回 `unknown`。
- `run_python_or_rust` 在 `.strip()` 前拒绝非字符串 mode，并继续使用现有允许模式集合校验。
- `run_python_or_rust` 的所有诊断和 `assert_equivalent` 共用路径归一化逻辑。
- 未修改 Rust 算法、`rust/*.rs`、其他生产模块或 `scripts/pdf_diff_review.py`。

## TDD 证据

### RED

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_rust_migration_routing.py -vv
```

真实结果：`12` 项中 `10 passed, 2 failed`。失败为：

```text
FAILED tests/test_rust_migration_routing.py::test_diagnostic_path_is_normalized_and_has_common_fields
E       AssertionError: assert '   ' == 'unknown'

FAILED tests/test_rust_migration_routing.py::test_run_python_or_rust_rejects_non_string_mode
E       AttributeError: 'NoneType' object has no attribute 'strip'
```

### GREEN

同一命令重新执行后：

```text
12 passed, 5 warnings in 0.36s
```

## 验证

相关 Python 测试命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_pdf_fast_binding.py tests/test_pdf_fast_dto.py tests/test_pdf_fast_english_wireless.py tests/test_pdf_fast_shared_geometry.py tests/test_pdf_fast_shared_recovery.py tests/test_pdf_fast_table_normalization.py tests/test_pdf_fast_wired.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_wireless.py tests/test_rust_migration_routing.py
```

真实结果：

```text
108 passed, 5 warnings in 0.92s
```

`git diff --check` 无输出且退出码为 0。

## 文件清单

- `src/hexai_pdf_parser/rust_adapter.py`
- `tests/test_rust_migration_routing.py`（上一代理已留下，本任务未再修改测试）
- `迁移记录/sprints/sprint-001.md`
- `.superpowers/sdd/task-1-report.md`

## 自审与未解决问题

- 诊断字段继续包含 `schema_version`、`status`、`path`；shadow 模式仍返回 Python，rust 模式仍优先返回 Rust，Rust 异常仍回退 Python。
- 当前测试运行产生 5 个既有 PyMuPDF 类型弃用警告，不影响退出码。
- CodeGraph 目录存在，但本 worktree 的索引未初始化，`codegraph explore` 子命令也不可用；未因此扩大文件范围。
- 本 Sprint 不包含页面级 PDF 重跑，也未修改页面解析算法。
