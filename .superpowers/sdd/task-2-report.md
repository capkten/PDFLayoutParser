# Task 2 收尾报告：中文/混合 native-span 与共享无线完整接入

## 状态

已完成验证并提交。生产入口消费 Rust sentinel 返回值，并将 owned DTO 转换为项目 `Cell`/`Table`；Rust 输出的空槽位、占用冲突和网格边界由 Rust/Python 两层校验，异常时保留 Python fallback。

## RED/GREEN 证据

### RED

在独立临时 worktree（基于收尾前 `HEAD`，仅复制当前 sentinel 测试文件和已存在的 `_pdf_fast.pyd` 以满足导入）运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py -k 'sentinel'
```

关键输出：

```text
FF [100%]
2 failed, 14 deselected in 1.26s
```

失败原因符合 sentinel 设计：旧 `recover_cells_from_region` 返回 `PYTHON_BASELINE`，旧 `recover_wireless_tables` 返回 0 张表，说明 Rust adapter 返回值曾被丢弃。

### GREEN

当前 Task 2 实现运行相同 sentinel 测试：

```text
.. [100%]
2 passed, 14 deselected in 0.40s
```

## 验证命令与结果

1. 相关 Python 测试：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py tests/test_wireless_table_recovery.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_shared_recovery.py
```

结果：`53 passed in 0.71s`。

2. Rust 测试：

```powershell
cargo test
```

结果：Rust 单元测试 `14 passed; 0 failed`；Doc-tests `0 passed; 0 failed`。

3. 差异空白检查：

```powershell
git diff --check
```

结果：通过，无输出。

4. 初次 cargo 验证曾暴露 `occupancy` 被双层 `move` 闭包移动、随后无法借用的问题；已在 `rust/wireless_structure.rs` 改为借用式双层遍历，之后 cargo test 通过。

## 差异分类

- Python 生产接入：`recoverer.py` 和 `wireless_table_recovery.py` 使用 `get_rust_mode` 与 `run_python_or_rust`，消费 `recover_native_region`/`recover_wireless_tables` 的结果。
- DTO 转换：Rust `CellDto`/candidate 转换为项目 `Cell`/`Table`，保留文本、bbox、source、rows/cols 和 rowspan/colspan。
- 结构安全：Rust 与 Python 检查跨度边界及 occupancy conflict；未占用槽位物化为独立空 Cell；冲突或不完整网格触发 Python fallback。
- Rust 结构输出：`wireless_structure.rs` 保留每个逻辑槽位恰好一个 Cell，并记录 occupancy diagnostics；相邻 candidate 的冲突不进入最终候选。
- 测试：sentinel RED/GREEN、空槽位、独立叶子列、表头冲突、跨度完整性、相邻表格边界和无 `get_text("words")` 回读覆盖。

## 文件清单

本次提交文件：

- `rust/wireless_structure.rs`
- `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`
- `src/hexai_pdf_parser/tables/wireless_table_recovery.py`
- `tests/test_wireless_structure_recoverer.py`
- `.superpowers/sdd/task-2-report.md`

未纳入提交的现有未跟踪迁移记录文件已保留在工作区：

- `迁移记录/baseline.md`
- `迁移记录/capability-matrix.md`
- `迁移记录/decisions.md`
- `迁移记录/migration-plan.md`

本 worktree 不存在 brief 指定的 `迁移记录/sprints/sprint-002.md`，因此未创建新文件。

## 自审

- 未修改 `rust_adapter.py`、`rust/lib.rs`、English/table_extractor/normalizers、`scripts/pdf_diff_review.py`。
- 未修改或覆盖旧 PDF diff review 文件；本报告仅覆盖 `.superpowers/sdd/task-2-report.md`。
- 中文/混合结构恢复消费 native span、atom、column bands、physical/logical Cell；结构恢复路径未新增 `page.get_text("words")` 读取。
- Python fallback 仍由 `run_python_or_rust` 和异常回退路径保留；Rust 返回不完整、越界或冲突结构不会进入项目结果。
- 仅发现并修复一个编译阻塞；修复后重新运行相关 Python 测试、cargo test 和 diff check，均通过。
