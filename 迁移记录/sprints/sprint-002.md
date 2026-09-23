# Sprint 002：native-span 无线结构 review-fix

## 状态

已完成本轮 review-fix 的 RED/GREEN 验证。修复范围仅覆盖两个 Python 无线入口的统一路由，以及 Rust 排序后 occupancy 索引重建。

## 根因

1. `recover_cells_from_region` 和 `recover_wireless_tables` 原先把 native span 收集、DTO 构造和 `run_python_or_rust` 放在同一个外层 `try` 中，但 DTO 构造发生在 `run_python_or_rust` 调用之前。native span/DTO 构造异常因此直接进入入口级 Python 回退，不经过统一路由，导致 `rust` 模式没有记录对应 path 的 `rust_fallback` diagnostic。
2. `rust/wireless_structure.rs` 在 `build_logical_grid` 和 `recover_native_region` 中先用排序前的 `cells.len()` 写入 occupancy，随后按行列排序 `cells`。排序改变了 cell 下标，但 occupancy 保留旧值，读取 occupancy 时会指向错误 cell。

## 修复与判定条件

- 两个入口都把 native span 收集、DTO 构造、Rust 调用和 Rust 输出转换封装为 `rust_fn`，交给 `run_python_or_rust` 统一捕获异常。
- `python` 模式只执行 Python 路径，不构造 native-span DTO，也不调用 Rust。
- `rust` 模式中，`rust_fn` 的 native span、DTO、Rust 调用或输出转换异常必须记录对应 path 的 `rust_fallback`，随后回退 Python。
- `shadow` 模式仍先返回 Python 结果；Rust 侧异常记录 `rust_fallback`，输出不被 Rust 异常替换。
- Rust 两个排序点之后都根据排序后的 cell 行、列及 `rowspan/colspan` 重建 occupancy。重建时遇到跨度覆盖冲突保留 `occupancy_conflict` diagnostic，不复用排序前索引。

## native-span 约束

native span 组合成 atom 后，结构恢复阶段只消费 native span、atom、列带、物理 Cell、逻辑 Cell 和网格 occupancy；本修复没有新增任何 `page.get_text("words")` 回读。Python fallback 也继续沿用现有 native-span 流程。

## 空槽位与 occupancy

空槽位仍按推断网格逐槽物化为独立的 `text=""`、`1x1` Cell，不合并相邻空槽位。排序完成后，最终 occupancy 的每个索引都指向排序后 `cells` 中对应的 Cell；跨度覆盖同一槽位时追加冲突诊断，冲突结果不能静默改写既有占用。

## RED/GREEN 测试

### RED

入口诊断测试：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py -k 'routes_native_span_exception_to_diagnostic'
```

结果：`2 failed, 16 deselected`，两个入口均未产生 `rust_fallback` diagnostic。

Rust occupancy 测试：

```powershell
cargo test wireless_structure
```

结果：`1 passed; 1 failed; 13 filtered out`，失败为排序后 occupancy 仍指向排序前 cell。

### GREEN

- 入口诊断测试：`2 passed, 16 deselected`。
- Rust wireless_structure：`2 passed, 0 failed; 13 filtered out`。
- 相关 wireless Python 测试：`270 passed in 2.00s`。
- 完整 Rust 测试：`15 passed, 0 failed`；Doc-tests：`0 passed, 0 failed`。
- `git diff --check`：通过，无输出。

## 差异分类

- 路由差异：异常从入口级直接 Python 回退，改为由 `run_python_or_rust` 记录 `rust_fallback` 后回退；`python`、`shadow`、`rust` 语义保持不变。
- 结构差异：排序后的 cell 使用新的 occupancy 索引；空槽位仍完整物化，跨度冲突仍产生 diagnostics。
- 测试差异：保留并通过已有 review-fix RED 测试和 Rust occupancy 回归测试。
- 文档差异：新增本 sprint 记录并覆盖旧 Task 2 报告，未修改历史 PDF diff review 文件。

## 未覆盖项

本轮未执行 PDF 页面级全量重跑、PNG 视觉核对或 PDF diff review；本任务要求的入口回归、wireless 相关测试、完整 Rust 测试和差异空白检查均已执行。
