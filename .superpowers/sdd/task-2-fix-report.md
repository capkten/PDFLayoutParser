# Task 2 Repair 报告：Snapshot/DTO/Strict Output 行为一致性

## 状态

修复已完成并提交。由于用户在长时间验证前要求立即收束，`cargo test --lib` 和简报中更宽的回归测试未运行，见“未解决事项”。

## RED 证据

修复前运行：

```powershell
pytest -q tests/test_rust_snapshot_route_red.py tests/test_pdf_fast_shared_recovery.py
```

关键输出：

```text
8 failed, 12 passed in 1.39s
```

失败行为包括：empty `chars` 回退 span 文本、显式 `type=None` 未跳过、无 `lines` 的 non-text block 在 adapter 处失败、非零 `page_y0` 未传入 Rust、非法跨度未拒绝、缺失 rect 被 fallback bbox 补全、以及 `0x0` candidate 被接受。

## 实现与 GREEN 证据

### 1. Snapshot block/span 行为

- `rust_adapter.py`：non-text block 的 `lines` 缺失时按空列表 DTO 化；text block 仍要求 `lines`；显式 `type=None` 保留为 `None`。
- `rust/types.rs`：`TextBlockDto.block_type` 改为可表达缺失/`None`/整数；non-text block 缺失 lines 时接受空列表；`PageSnapshotDto` 增加兼容默认值为 `0.0` 的 `page_y0`。
- `rust/snapshot.rs`：仅 `block_type == Some(0)` 收集；span/line 文本严格从 `characters` 重建，empty chars 不回退 span.text；footer 使用 DTO 的 `page_y0`。
- `rust_adapter.py`：仅非零 geometry y0 输出 `page_y0`，保持现有零原点 DTO 形状/digest。

修复后 focused GREEN：

```powershell
pytest -q tests/test_rust_snapshot_route_red.py -k "without_chars or explicit_none or nonzero_origin or invalid_rust_grid"
```

```text
11 passed, 2 deselected in 0.71s
```

### 2. Strict cell/grid 输出

- `_rust_cells_to_project` 拒绝 rows/cols `<= 0`、负索引、非正 rowspan/colspan、越界和 occupancy conflict。
- 不再用 `max(1, ...)` 修正非法跨度。
- 不再用 `fallback_bbox` 补全缺失 cell rect；缺失 rect 直接报错。
- snapshot recovery adapter 统一经过 strict cell 转换并拒绝空 grid。

```powershell
pytest -q tests/test_pdf_fast_shared_recovery.py -k "zero or candidate"
```

```text
3 passed, 4 deselected in 0.67s
```

完整两个 focused 文件：

```powershell
pytest -q tests/test_rust_snapshot_route_red.py tests/test_pdf_fast_shared_recovery.py
```

```text
20 passed in 0.58s
```

其他已运行验证：

```powershell
cargo check
```

```text
Finished `dev` profile [unoptimized + debuginfo]
```

```powershell
git diff --check
```

无输出，退出成功。

构建 Rust 扩展：

```powershell
maturin develop --release
```

构建成功，生成 abi3 Windows wheel；pytest focused 结果为上面的 GREEN 结果。

## 文件清单

本次提交仅包含：

- `rust/snapshot.rs`
- `rust/types.rs`
- `src/hexai_pdf_parser/rust_adapter.py`
- `src/hexai_pdf_parser/tables/wireless_table_recovery.py`
- `tests/test_rust_snapshot_route_red.py`
- `tests/test_pdf_fast_shared_recovery.py`

保留但未提交的既有 dirty 改动：

- `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`
- `tests/test_wireless_extractor_split.py`
- `tests/test_wireless_structure_recoverer.py`
- `.superpowers/sdd/planner-audit-rust-migration.md`
- `.superpowers/sdd/progress.md`
- `.superpowers/sdd/task-2-fix-brief.md`

## 提交

提交 subject：`Fix Task 2 snapshot DTO and strict Rust output parity`

## 未解决事项 / concerns

- 按用户中断要求，未运行 `cargo test --lib`。
- 未运行简报要求的四个测试文件宽回归套件：`tests/test_wireless_structure_recoverer.py`、`tests/test_wireless_extractor_split.py`、`tests/test_rust_migration_routing.py` 及其与 focused tests 的组合。
- 直接从当前 worktree 根目录执行 `python -c "import hexai_pdf_parser._pdf_fast"` 受环境包路径影响而失败；maturin 构建成功，pytest focused 测试已通过实际 adapter 路径。
- 未实现完整 Chinese wireless recovery algorithm；默认 Python 路由、shadow 返回 Python、Rust fallback 语义未主动修改。

## Task 2 bounded fixer 追加记录（2026-09-21）

本次仅关闭 Snapshot/strict-output 边界 reviewer Important，并补齐 bounded minor；未修改 Rust wireless layout 算法、默认 Python route、shadow 返回语义或无关 dirty 文件。

### RED

新增回归测试后、生产代码修改前：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_migration_routing.py -k 'nonzero_page_origin_mapping'
```

```text
1 failed, 29 deselected in 0.71s
```

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_migration_routing.py -k 'nonzero_page_origin_mapping' tests/test_pdf_fast_shared_recovery.py -k 'bbox_without_explicit_rect or page_spy_no_get_text_words'
```

```text
1 failed, 1 passed, 48 deselected in 0.75s
```

失败均为预期行为：digest-bearing Mapping 因 `page_y0` 被 exact key check 拒绝；only-bbox cell 被候选 bbox 错误补全。PageSpy 回归已真正调用 `recover_cells_from_region`，基线即保持无 `words` 读取。

### GREEN

最小修复后 focused GREEN：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_migration_routing.py -k 'nonzero_page_origin_mapping or page_snapshot_contract_roundtrips_and_rust_digest_matches or recover_native_text_input_requires_matching_snapshot_digest'
```

```text
3 passed, 27 deselected in 0.45s
```

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_pdf_fast_shared_recovery.py -k 'bbox_without_explicit_rect or page_spy_no_get_text_words or zero_by_zero_grid'
```

```text
3 passed, 17 deselected in 0.45s
```

brief 要求的完整 Python 回归集：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_snapshot_route_red.py tests/test_pdf_fast_shared_recovery.py tests/test_wireless_structure_recoverer.py tests/test_wireless_extractor_split.py tests/test_rust_migration_routing.py
```

```text
89 passed in 1.99s
```

Rust 与最终检查：

```powershell
cargo check
```

```text
Finished `dev` profile [unoptimized + debuginfo]
```

```powershell
cargo test --lib
```

```text
running 50 tests
test result: ok. 50 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

```powershell
git diff --check
```

无输出，退出码 0。

### 本次改动文件

- `src/hexai_pdf_parser/rust_adapter.py`
- `src/hexai_pdf_parser/tables/wireless_table_recovery.py`
- `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`
- `tests/test_rust_migration_routing.py`
- `tests/test_pdf_fast_shared_recovery.py`
- `.superpowers/sdd/task-2-fix-report.md`

严格 cell 转换现在只接受显式 `rect`，已移除 `fallback_bbox` 签名及全部调用参数；digest-bearing Mapping 允许可选 `page_y0`，其余字段仍保持严格集合校验。零原点 DTO shape/digest 既有测试保持通过。

### 未解决问题 / concerns

本次任务范围内无未解决问题。工作区中其他既有 dirty 文件和既有报告历史内容均未清理、未纳入本次修复 commit；未实现完整 Chinese wireless parity，符合本任务边界。
