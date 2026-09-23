# Task 2 Review-Fix 报告

## 状态

review-fix 已完成 GREEN 验证。范围限定为：两个 Python native-span 无线入口的统一 Rust fallback 路由，以及 Rust 排序后的 occupancy 索引重建。

## RED

### Python 入口诊断

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py -k 'routes_native_span_exception_to_diagnostic'
```

结果：

```text
2 failed, 16 deselected
```

两个失败都表现为 `len(diagnostics) == 0`。根因是 native span/DTO 构造在 `run_python_or_rust` 调用之前，入口级 `except` 直接回退 Python，绕过了 `rust_fallback` 记录。

### Rust occupancy

```powershell
cargo test wireless_structure
```

结果：`1 passed; 1 failed; 13 filtered out`。失败断言显示 occupancy 中的索引仍指向排序前 cell。

## GREEN

### 目标 review-fix 测试

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py -k 'routes_native_span_exception_to_diagnostic'
```

结果：`2 passed, 16 deselected`。

```powershell
cargo test wireless_structure
```

结果：`2 passed, 0 failed; 13 filtered out`。

### 相关 wireless 测试

执行了以下 wireless 相关测试文件：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_table_recovery.py tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_span_chain.py tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_columns.py tests/test_wireless_output_order.py tests/test_wireless_extractor_split.py tests/test_unify_wireless_recovery.py tests/test_rust_migration_routing.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_wireless.py tests/test_pdf_fast_english_wireless.py tests/test_hybrid_body_recovery.py
```

结果：`270 passed in 2.00s`。

### 完整 Rust 测试

```powershell
cargo test
```

结果：Rust 单元测试 `15 passed, 0 failed`；Doc-tests `0 passed, 0 failed`。

### 差异检查

```powershell
git diff --check
```

结果：通过，无输出。

## 修复摘要

- `recover_cells_from_region` 和 `recover_wireless_tables` 将 native span 收集、DTO 构造、Rust 调用和结果转换放入 `rust_fn`，统一由 `run_python_or_rust` 捕获异常。
- `python` 模式不构造 Rust DTO；`rust` 模式在异常时记录 path 对应的 `rust_fallback` 并回退 Python；`shadow` 模式保留 Python 返回语义并记录 Rust 异常/差异。
- `build_logical_grid` 和 `recover_native_region` 在 cells 排序后按行列及跨度重建 occupancy，不使用旧索引；跨度冲突继续生成 `occupancy_conflict` diagnostics。
- native span 进入 atom 后，结构恢复阶段不回读 `page.get_text("words")`。
- 空槽位继续按逻辑网格逐槽物化为独立空 Cell；最终 occupancy 索引指向排序后的 cell。

## 差异分类

- Python 路由：修复诊断可见性和 fallback 边界，未改 `rust_adapter.py`。
- Rust 结构：修复排序后的索引一致性，保留 occupancy 冲突诊断。
- 测试：已有 review-fix RED 测试转 GREEN，相关 wireless 和 Rust 回归均通过。
- 文档：本报告替换旧 PDF diff review 内容；新增 `迁移记录/sprints/sprint-002.md`。未修改 `scripts/pdf_diff_review.py` 或其他历史报告。

## 文件范围

本次提交只包含：

- `rust/wireless_structure.rs`
- `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`
- `src/hexai_pdf_parser/tables/wireless_table_recovery.py`
- `tests/test_wireless_structure_recoverer.py`
- `迁移记录/sprints/sprint-002.md`
- `.superpowers/sdd/task-2-report.md`

工作区已有的 `迁移记录/baseline.md`、`capability-matrix.md`、`decisions.md`、`migration-plan.md` 未纳入本次提交。

## Concerns

本轮没有执行 PDF 页面级全量重跑、最终 PNG 视觉核对或 PDF diff review；这些不属于本次指定的 review-fix 测试集合。其余要求的 RED/GREEN、相关 wireless 测试、完整 Rust 测试和 `git diff --check` 均有上方实测结果。
