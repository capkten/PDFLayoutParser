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

## Reviewer corrected findings 与本次修订

独立 Luna reviewer 已更正此前的误判：Rust DTO evidence 与 Python raw
oracle 分离是正确的，`_PreparedNativeRegion` 保留 Python atoms/bands、Rust
payload 只传 normalized core/evidence 的设计继续保留。本次仅处理 reviewer
确认的两个 Important finding：

1. Rust-facing snapshot builder 必须在
   `collect_native_spans_from_snapshot()` 之前扫描
   `text_blocks/type=0/lines/spans`。现在 `_native_validate_snapshot_span_bboxes()`
   对缺 key、容器/对象错误、非有限坐标、反向坐标和零面积直接抛出
   `KeyError`、`TypeError` 或 `ValueError`，因此 allowed-region 中心点过滤不能
   再把坏 span 静默变成合法空结果。校验只由 `validate_spans=True` 的 Rust-facing
   builder 调用；Python oracle 仍保留 route-level empty-result policy。
2. `_native_run_refs()` 对 present `span_refs` 不再 fallback：字段必须是 list/tuple，
   每个元素必须匹配 `S<number>` 或 `S<number>.<fragment>`。Rust-facing builder
   将 native spans 的实际 `order` 集合传入并拒绝未知 base order。evidence 现在
   严格校验整数/布尔/容器类型，拒绝负 flow/source/row/band 序号，约束
   `flow_end >= flow_start`、`source_line_end >= source_line_start`，并校验
   `parent_x0/parent_x1` 成对且 `x0 < x1`、`parent_leaf_count > 0`。

## 本次 TDD RED/GREEN

新增 transition 边界覆盖：真实 `PageSnapshot` 实例中的 NaN span bbox、present
malformed/unknown `span_refs`、负 flow/source/row/band evidence、反向 evidence
范围、非法 parent geometry。RED 首次运行选中 19 个边界用例，结果为 `18 failed`
和 `1 passed`；首个失败是 NaN span 在 collector 中心点过滤后未抛异常。修复后
同一组边界为 `19 passed, 14 deselected`，transition 文件全量为 `33 passed`。

验证了 bridge 不读取 `page.get_text("words")`；Rust bridge 只消费 PageSnapshot、
native spans、atoms、bands 和 DTO evidence。由于 Python oracle 仍须保持原有
route-level empty-result policy，未启用 Rust-facing `validate_spans` 时不传递
native order 集合；此私有 shared preparation 路径仍执行 run-ref 格式、类型和
非负校验，而 unknown order 只在 Rust-facing builder 能取得实际 native order
集合时严格拒绝。该限制没有放宽 Rust-facing contract。

## 最终验证计数

```text
pytest tests/test_rust_native_region_transition.py \
  tests/test_pdf_fast_dto.py tests/test_rust_migration_routing.py \
  tests/test_wireless_structure_recoverer.py: 99 passed
cargo test --lib: 50 passed; 0 failed
git diff --check: passed
```

本次没有执行页面级 PDF/PNG 重跑；任务范围是 bridge transition validation，且
没有修改 `wireless_table_recovery.py`。最终提交仍只包含 recoverer.py、
`tests/test_rust_native_region_transition.py` 和本报告；review package、brief
文件以及两个用户已有 dirty 测试均保留未提交。
