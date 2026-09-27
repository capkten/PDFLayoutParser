# Repair Sprint 003：严格 Cell 网格字段

## 范围

本 repair 只处理 `_rust_cells_to_project()` 的 `row`、`col`、`rowspan`、`colspan` 类型边界。没有修改 Rust 无线结构算法、默认路由或已有 dirty 文件。

## 根因

转换函数原先对四个字段直接调用 `int()`。因此 `-0.5` 可能变为 `0` 并通过边界检查，`True` 也会被 Python 当作整数处理。非法 Rust 输出可能因此进入 Python `Cell` facade。

## RED/GREEN

- RED：Generator 在旧实现上运行新增的 12 个参数化用例，结果为 `12 failed`。
- GREEN：修复后 Generator 报告 focused 用例为 `12 passed, 7 deselected`；独立复核确认四个字段无遗漏。
- 独立复核：Luna Evaluator 运行 `pytest -q tests/test_pdf_fast_shared_recovery.py`，结果为 `19 passed in 0.53s`；`git diff --check` 无输出。

## 实现判定

`type(value) is int` 是唯一允许的 Cell 网格字段类型，因此拒绝 `bool`、浮点、字符串、`Decimal` 等可截断值。正整数、占用冲突、边界、bbox 和未覆盖槽位的既有校验保留。路由层仍由 Rust 异常记录 `rust_fallback` 并回退 Python，`shadow` 仍返回 Python 结果。

## 宽验证

- `pytest -q tests/test_rust_snapshot_route_red.py tests/test_pdf_fast_shared_recovery.py tests/test_wireless_structure_recoverer.py tests/test_wireless_extractor_split.py tests/test_rust_migration_routing.py`：`87 passed`。
- `cargo test --lib`：`44 passed`。
- `cargo check`：通过。
- `git diff --check`：通过。
- `cargo fmt --check`：失败于既有 `rust/lib.rs`、`rust/types.rs`、`rust/wireless_structure.rs` 格式差异；本 repair 未改动这些基线差异。

## 未完成能力

本 repair 不代表中文/混合无线结构 Rust parity 完成。span/atom、列带、物理/逻辑网格、表头拓扑的字段级差分，以及两条入口的真实页面 JSON/PNG 验收仍需后续 sprint；默认路由继续使用 Python。
