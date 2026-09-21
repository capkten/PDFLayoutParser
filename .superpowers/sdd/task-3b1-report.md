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

## 工作区保护

`tests/test_wireless_extractor_split.py` 和 `tests/test_wireless_structure_recoverer.py` 的用户 dirty 改动已保留，未修改或清理。
