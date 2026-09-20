# Task 1 transition report

## 交付状态

Task 1 bridge regression fixer 已完成。工作树基于 `ee91f55`，保留用户已有的
`recoverer.py` 草稿以及两个 dirty 测试文件；没有执行 reset、checkout 或 clean。

## RED

先运行唯一失败单测：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py::test_recover_cells_rebuilds_after_exact_slot_conflict_merge
```

结果：`1 failed`。实际结果为 `(rows, columns) == (0, 0)`，期望为 `(3, 3)`。

根因是 `_prepare_native_region_from_snapshot()` 的返回值同时被 Rust bridge 和
Python oracle 使用。Rust builder 将 atoms/bands 规范化为 core/evidence payload 后，
Python helper 从同一组 normalized atoms/bands 读取，丢失了 Python recovery 所需的
`candidate_label`、`cell_id`、`source_position`、`font_size` 等内部字段。

## 修复设计

- preparation 使用私有 `_PreparedNativeRegion` 同时保存 `python_atoms`、
  `python_bands` 和 `rust_input`。
- Python helper 继续使用原始 atom/band；Rust bridge 只返回 normalized core/evidence
  payload。
- `_build_native_region_input_from_snapshot()` 和
  `_recover_native_region_from_snapshot_rust()` 的 Rust-facing API 没有加入 Python
  内部字段，Rust DTO 未修改。
- Snapshot 输入、默认 route、shadow 语义和 direct Snapshot 算法均未修改。

## stale extension 误差

之前的 Task 1 草稿把 native span bbox 校验放在 Python/Rust 共用 preparation 中。
用户已有的 `tests/test_wireless_structure_recoverer.py` dirty extension 将采集结果
替换成 `object()`，用于隔离 Python grid 回归；共用校验因此抛异常，再被 Python
helper 的兼容性 catch 转成 `(0, 0)`。这不是 bridge DTO 回归本身。

本次将 span bbox 校验限定在 Rust-facing builder；Python raw oracle 不额外承担该
边界校验，同时保留 Rust bridge 对 malformed span 的显式校验。dirty 测试文件未修改。

## GREEN 与验证

新增 bridge separation regression 与原 RED 单测：

```text
2 passed
```

用户指定 focused 命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_region_transition.py tests/test_pdf_fast_dto.py tests/test_rust_migration_routing.py tests/test_wireless_structure_recoverer.py
```

结果：`80 passed`。

Rust library：

```text
50 passed; 0 failed
```

差异检查：`git diff --check` 通过，无 whitespace error。

## 提交范围

最终提交只包含：

- `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`
- `tests/test_rust_native_region_transition.py`
- `.superpowers/sdd/task-1-transition-report.md`

不提交 `tests/test_wireless_extractor_split.py` 或
`tests/test_wireless_structure_recoverer.py`。
