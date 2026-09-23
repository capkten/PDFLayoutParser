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
- 未修改 Rust 算法、`rust/*.rs` 或 `scripts/pdf_diff_review.py`；本轮复审修复仅触及 wired extractor 的 shadow 探针，不改变表格返回值。

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

## 复审修复：wired shadow 探针

### RED

新增 `tests/test_wired_table_extractor.py::test_extract_shadow_probe_uses_wired_route_and_records_rust_error` 后，focused 命令首次结果为：

```text
1 failed, 63 deselected
E       assert 0 == 1
```

失败表明旧实现吞掉了 Rust 异常，没有产生统一 `rust_fallback` 诊断。

### GREEN

将 wired 探针改为 `get_rust_mode("wired")` 和 `run_python_or_rust()` 后，同一 focused 命令结果为：

```text
1 passed, 63 deselected in 0.40s
```

同时确认 shadow 探针成功路径只执行诊断探测，不改变 `extract()` 的 Python 表格返回值。

## 验证

相关 Python 测试命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_pdf_fast_binding.py tests/test_pdf_fast_dto.py tests/test_pdf_fast_english_wireless.py tests/test_pdf_fast_shared_geometry.py tests/test_pdf_fast_shared_recovery.py tests/test_pdf_fast_table_normalization.py tests/test_pdf_fast_wired.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_wireless.py tests/test_rust_migration_routing.py
```

真实结果：

```text
108 passed in 1.11s
```

`git diff --check` 无输出且退出码为 0。

当前 wired 相关测试命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q tests/test_wired_table_extractor.py tests/test_pdf_fast_wired.py
```

真实结果：`84 passed in 5.27s`。

## 文件清单

- `src/hexai_pdf_parser/rust_adapter.py`
- `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py`：本轮复审修复 wired shadow 探针路由和异常诊断。
- `tests/test_rust_migration_routing.py`：本任务 RED 阶段新增 sentinel、空白 path 和非字符串 mode 测试；保留既有 Rust fallback 测试。
- `tests/test_wired_table_extractor.py`：本轮新增 wired shadow 路由回归测试。
- `迁移记录/sprints/sprint-001.md`
- `.superpowers/sdd/task-1-report.md`

## 自审与未解决问题

- 诊断字段继续包含 `schema_version`、`status`、`path`；shadow 模式仍返回 Python，rust 模式仍优先返回 Rust，Rust 异常仍回退 Python。
- 当前测试运行产生 5 个既有 PyMuPDF 类型弃用警告，不影响退出码。
- 当前默认 `pytest -q tests/test_rust_migration_routing.py` 使用的解释器缺少 `fitz`，在 `tests/conftest.py` 收集阶段以 `ModuleNotFoundError: No module named 'fitz'` 退出；该收集错误不计为代码测试通过。使用 Python 3.12 解释器并禁用外部插件后，路由和相关测试分别取得上述通过结果。
- CodeGraph 目录存在，但本 worktree 的索引未初始化，`codegraph explore` 子命令也不可用；未因此扩大文件范围。
- 本 Sprint 不包含页面级 PDF 重跑，也未修改页面解析算法。
