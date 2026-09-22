# Sprint 006：Rust 无线结构列带、网格与表头拓扑迁移

> 日期：2026-09-22
> Worktree：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`
> 分支：`codex/rust-migration-replan`

## 当前阶段

Task 4A 已完成差分观测基础设施。当前只证明 Python oracle 与 Rust helper 可以在同一 owned atom/band/region 输入上按字段比较；尚未宣称 column/grid/header parity。

## 夹具范围

`tests/fixtures/rust_migration/wireless/wireless_structure_differential.json` 固定以下形态：

- paired-CJK artifact 与 sparse alignment artifact；
- header-only note/leaf rescue；
- 近中心但不同物理行、left-shifted CJK continuation；
- 独立 leaf、完整/不完整二叶子父表头；
- 空覆盖 rowspan、非空标题阻断 rowspan；
- occupancy conflict、越界和独立空槽位。

## 运行记录

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_wireless_structure_differential.py
3 passed in 0.46s
```

`git diff --check` 在提交前执行；Rust 生产实现和 route 尚未修改。

## 下一步

1. Task 4B：迁移 owned-input 的列带 refine/rescue、header cutoff 与 geometry-based annotation。
2. Task 4C：迁移 physical row/grid、column span 和 occupancy contract。
3. Task 4D：迁移 logical row/header-span transaction 与 empty-slot materialization。

每个 bounded slice 都必须先 RED、再 GREEN，并由独立 `gpt-5.6-luna` reviewer 给出 Spec Compliance 与 Task quality 结论。默认 Python route、shadow route 和 fallback policy 保持不变。
