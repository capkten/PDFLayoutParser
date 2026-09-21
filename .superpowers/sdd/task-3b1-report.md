# Task 3B-1：Rust text-run source/evidence 透传报告

## 范围

本 slice 只为 `TextRunDto` 增加可选的 owned evidence，并由 `build_text_runs` 从实际参与 run 的 `NativeSpanDto` 按 run 内 span 顺序透传 `source_positions`、`fonts`、`sizes` 和 `flags`。未修改 `rust/wireless_structure.rs`、任何生产 Python、默认/shadow/fallback route、Task 3A fixture 或用户 dirty 文件；未开始 packed numeric、superscript、wrapped merge、alignment corridor、column/grid/header。

## TDD 记录

### RED

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Resolve-Path 'src').Path
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_evidence.py tests/test_pdf_fast_dto.py
```

结果：`6 failed, 19 passed`。失败原因均为目标行为缺失：producer/roundtrip 没有 `evidence`，长度不一致、错误类型和 `Inf` evidence 未被 DTO 解析拒绝；不是 fixture、语法或导入错误。

### GREEN

重建当前 worktree 的 PyO3 扩展后，使用同一命令：

```text
25 passed in 0.57s
```

真实输入来自 Task 3A differential fixture 转换出的 `NativeSpanDto` 字典，并经现有 PyO3 `build_text_runs` binding 调用；没有用手写 Rust 预期替代真实调用。

## 合同核对

- 旧的无 evidence `text_run` DTO roundtrip 输出字段集合和值完全不变，`to_py()` 不输出 `evidence`。
- evidence roundtrip 保留 `schema_version: 1`、每个 span 的 `{schema_version, block, line}`，以及等长的 `Option<String>` fonts、`Option<f64>` sizes、`Option<i64>` flags 列表。
- producer 的 evidence 长度与 `span_refs` 等长，source/font/size/flags 均直接来自 owned `NativeSpanDto`。
- DTO 解析拒绝 source_positions 与任一 evidence 列表长度不一致、列表元素错误类型和 NaN/Inf size，并以 `ValueError` 可观察失败。

## 回归验证

```powershell
cargo test --lib native_span
```

结果：`4 passed, 0 failed`。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Resolve-Path 'src').Path
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py
```

结果：`11 passed`；其中 564-record ledger、fixture/field/classification 计数和 `5093640efdb9d73e66d6f8adacafc7f635c0e0eded129989677407083044ab59` digest 均保持锁定。

```powershell
git diff --check
```

结果：通过。

```powershell
cargo fmt --check
```

结果：退出码 1。失败来自本 sprint 之前的既有格式差异（`rust/lib.rs`、`rust/types.rs` 既有区域以及禁止修改的 `rust/wireless_structure.rs`）；本任务未运行全仓格式化，也未修改这些文件来掩盖基线问题。

## 未解决限制

- `build_atoms` 仍按 brief 保持现状，不消费或继续透传 TextRun evidence；Atom metadata 留给后续 slice。
- Task 3A differential 仍只比较既有 semantic ledger 字段，新增 evidence 不改变 ledger schema、564 条记录或 digest。
- `cargo fmt --check` 的仓库基线失败需要单独治理；不能在本任务中修改禁止文件。
- 独立 reviewer 仍需在本提交上复核后，才能进入后续 packed numeric/superscript/wrapped semantic slice。

## Reviewer 修复轮次

独立 Luna reviewer 发现并要求修复：

1. `TextRunDto::from_py` 原先只校验 evidence 内部列表等长，未校验 `source_positions.len() == span_refs.len()`。
2. evidence 非有限 size 需要同时覆盖 NaN 与 Inf。
3. legacy-shape 兼容断言应归入 evidence focused test，恢复 `tests/test_pdf_fast_dto.py` 的既有文件范围。

修复前 RED 使用同一 focused 命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Resolve-Path 'src').Path
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_evidence.py tests/test_pdf_fast_dto.py
```

结果：`1 failed, 26 passed`；唯一失败为 `span_refs` 长度 2 而 evidence 长度 1 未拒绝。NaN 用例在修复前已通过，说明现有 finite 校验有效但缺少明确回归覆盖。

修复后 GREEN：

```text
27 passed in 0.56s
```

最终回归命令与输出：

```powershell
cargo test --lib native_span
```

`4 passed, 0 failed`。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Resolve-Path 'src').Path
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py
```

`11 passed`；564-record ledger 与原 digest 未变化。

```powershell
git diff --check
```

通过。legacy-shape 断言现位于 `tests/test_rust_native_span_evidence.py`，`tests/test_pdf_fast_dto.py` 已恢复为 reviewer 前内容。

## 工作区保护

`tests/test_wireless_extractor_split.py` 和 `tests/test_wireless_structure_recoverer.py` 的用户 dirty 改动已保留，未修改或清理。

## 最终独立复审

Review range：`fa547c5..5829deb`。独立 `gpt-5.6-luna` reviewer 判定：Spec Compliance ✅，Task quality ✅ Approved。

- 本范围只恢复 `tests/test_pdf_fast_dto.py:139-149` 的完整 no-evidence `TextRunDto` round-trip shape/value 断言，共 13 行新增。
- reviewer 确认 `evidence` 字段被明确排除，旧 DTO 字段集合和值由 exact dictionary equality 锁定。
- focused verification：`1 passed`；`git diff --check`：通过。
- 未发现 Critical、Important 或 Minor issue。
- reviewer 说明 evidence producer/validation 不在本次恢复提交范围内；它们仍由前述 3B-1 实现与本报告记录的 focused tests 覆盖。

因此 Task 3B-1 已封存；下一 bounded slice 为 packed numeric split。不要在该 slice 通过之前进入 superscript、wrapped merge、alignment corridor 或 column/grid/header。

## 交接前 fresh verification（2026-09-21）

为核对恢复 legacy-shape 测试后的最终工作区，重新运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Resolve-Path 'src').Path
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_evidence.py tests/test_pdf_fast_dto.py
```

结果：`28 passed`。

```powershell
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py
```

结果：`11 passed`。

```powershell
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_columns.py
```

结果：`54 passed`。

```powershell
cargo test --lib native_span
git diff --check
```

结果：Rust `4 passed`；`git diff --check` 通过。
