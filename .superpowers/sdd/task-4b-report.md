# Task 4B：Rust 无线结构列带 refine/rescue 与表头 annotation 报告

> 日期：2026-09-22
> Worktree：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`
> 分支：`codex/rust-migration-replan`

## 结果

在 `rust/wireless_structure.rs` 中接入了 owned atom/band 的几何列带准备：paired-CJK 伪列裁剪、稀疏对齐伪列裁剪、重复数值正文轨道 refine、最低表头子列 refine、header cutoff、稀疏正文 rescue，以及保守的 header-only rescue。`recover_native_region` 先执行 prepared-band 阶段，再进入已有 grid/occupancy 流程。

实现只消费 atom rect/text/order/run_refs 与 band/region 几何；没有 page words、业务表头文字、page-coordinate magic、fallback bbox 或吞错。Python-default route、shadow route、Snapshot capture boundary 和 fallback policy 未改动。差分 harness 分开记录 raw owned bands 与 prepared bands。

## TDD 证据

先加入 `test_refine_leaf_bands_splits_independent_body_tracks`。旧 stub 的 RED 输出：

```text
cargo test --lib wireless_structure::tests::test_refine_leaf_bands_splits_independent_body_tracks -- --exact
FAILED
assertion `left == right` failed
left: 1
right: 2
```

最小实现后该测试 GREEN，并验证边界 `(10.0, 50.0)`、`(50.0, 90.0)`。

## 验证

```text
cargo test --lib wireless_structure
22 passed; 0 failed
```

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_wireless_structure_differential.py tests/test_wireless_structure_columns.py tests/test_wireless_structure_header_topology.py
72 passed in 0.92s
```

扩展模块使用 `maturin build --release --out target\wheels` 重建；`maturin develop --release` 因当前环境没有 virtualenv 失败，但不影响 Cargo 与 focused pytest。最终执行 `git diff --check`，应无输出并以退出码 0 结束。

## 差分分类

paired-CJK 与 sparse-alignment 的 bands presence mismatch 已消除，fixture contract 已移除这两个已迁移字段。其余逻辑表头跨度、rowspan/colspan、occupancy、空槽位和页面级差异按现有 `requires_adaptation`、`defect`、`unsupported` ledger 分类保留；没有 wildcard。

## 文件、自审与剩余边界

本次提交文件：`rust/wireless_structure.rs`、`tests/test_rust_wireless_structure_differential.py`、`tests/fixtures/rust_migration/wireless/wireless_structure_differential.json`、本报告和 `docs/superpowers/rust-migration/sprints/sprint-006.md`。两个用户已有 dirty 测试文件保持未修改；未改 route policy、Snapshot、DTO 类型或 Python production code。已有 overlapping sibling band 的保守行为保持，dash right-aligned track 回归已通过。

Task 4B 不宣称页面级 JSON/PNG parity。Rust DTO 当前缺少 Python 的 font-size/source-line/block 证据，本 slice 使用现有 order/run_refs 与几何连续性；完整 logical header span、rowspan/colspan、empty-slot materialization 和页面级检查仍是后续边界。

实现提交 hash：`1737a79`（`feat(rust): migrate wireless column refinement`）。报告与实现文件已随该提交纳入；后续仅有本报告回填提交。
