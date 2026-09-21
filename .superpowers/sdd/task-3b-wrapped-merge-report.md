# Task 3B Wrapped Merge 实现报告

## 任务范围

本次只实现 Rust `build_text_runs()` 的 wrapped field merge bounded slice，工作目录为
`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`。未修改 Python
生产实现、默认/shadow/fallback route、alignment corridor、`build_atoms` 之后的
column/grid/header/Cell 逻辑，也未修改用户已有 dirty 文件
`tests/test_wireless_extractor_split.py` 和 `tests/test_wireless_structure_recoverer.py`。

## 根因与实现

Rust `rust/native_span.rs::build_text_runs()` 已经完成同一视觉行的 run 构造，但随后直接
返回，缺少 Python oracle `text_runs.py` 中 `_merge_wrapped_field_runs()` 的语义层，因此
`vertical_wrapped_witness` 的左侧三行保持为三个 run。

修复只增加 wrapped merge 的本地 helper，并在 `build_text_runs()` 返回前调用：

- 按 source order 排序并逐个相邻 pair 检查，支持三行链式合并；
- 保留 native flow 连续、数字/placeholder veto、字体粗细和字号阈值、下方几何、横向重叠及垂直间距条件；
- 只有存在右侧 witness 时允许普通路径；无普通 witness 时仅允许 oracle 的 strong native vertical pair 加 multiline witness fallback；
- 合并时使用换行连接文本，union bbox，按链顺序扁平化 `span_refs`，并拼接 source positions/fonts/sizes/flags/fragment evidence；
- 全程只消费 native span 派生的 DTO/run/evidence，不回读 `fitz.Page` 或 `page.get_text("words")`。

## RED

初始新增正例、去 witness、字体/间距/重叠拒绝和来源控制测试后运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan\src'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py -k wrapped
```

结果：`1 failed, 2 passed, 14 deselected`。失败为 Rust 输出四个独立 run，期望为合并后的左侧三行和独立右侧字段，证明测试捕获的是缺失 wrapped merge。

为新增来源 fallback 反例做可逆 RED 验证，临时将最终 merge 调用替换为直接返回并重建 binding，再运行同一 focused 命令，结果为：`1 failed, 3 passed, 14 deselected`。随后立即恢复 merge 调用并重建。

## GREEN 与回归

正式实现恢复后执行：

```powershell
maturin develop --release
```

结果：构建并安装 `hexai_pdf_parser-1.1.1` 成功，退出码 `0`。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan\src'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py -k wrapped
```

结果：`4 passed, 14 deselected`。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan\src'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py
```

结果：`18 passed`。

```powershell
cargo test --lib native_span
```

结果：`4 passed, 0 failed`。

```powershell
git diff --check
```

结果：无输出，退出码 `0`。

brief 要求的组合 Python 回归命令在 ledger 更新后首次运行时为 `82 passed, 1 failed`；唯一失败是
测试文件内 `semantic_mismatches` 断言在局部变量定义前执行的测试 harness 错误，不是生产行为差异。
将断言移动到定义之后后，独立 differential 文件最终为 `18 passed`，wrapped focused 最终为
`4 passed`。packed numeric、superscript、placeholder/numeric veto 和普通 numeric join 的既有
断言均包含在相关回归中并保持通过。

## Differential ledger

wrapped 修复后实际 ledger：

- total：`364`
- fixture counts：`alignment_corridor_veto=266`、`cjk_non_whitelist_spacing=14`、`cjk_whitelist_spacing=7`、`empty_whitespace_and_separator=7`、`independent_fields_counterexample=14`、`packed_numeric_split=14`、`single_field_control=7`、`source_block_line_noncontinuous=14`、`superscript_inline_gap=7`、`vertical_wrapped_witness=14`
- field counts：`bbox=24`、`errors=24`、`flow/order=52`、`font/script=38`、`grouping=24`、`ordering=24`、`presence=26`、`source continuity=52`、`span/run refs=52`、`text=24`、`value=24`
- classification counts：`defect=218`、`requires_adaptation=28`、`unsupported=118`
- SHA256：`8358c75e03dc5e12086127a75cc9b4ed94e7d829ea63ccefc0f06ac09d701fcc`
- `vertical_wrapped_witness` 的 semantic mismatch fields：空集合

## 测试覆盖

新增/更新测试覆盖：

1. `vertical_wrapped_witness` 正例：文本、union bbox、span refs、source bounds 和完整 evidence；
2. 删除右侧 witness 后拒绝 wrapped merge；
3. 字体粗细不兼容、垂直间距过大、横向重叠不足时拒绝；
4. 右侧 witness 在 flow 前时，source block 不连续或 source line 不连续的 strong fallback pair 拒绝；
5. 既有 source block/line 控制、packed numeric、superscript、placeholder/numeric veto、normal numeric join 和 CJK whitelist/non-whitelist 回归。

## 范围自审

本 slice 仅修改：

- `rust/native_span.rs`
- `tests/test_rust_native_span_differential.py`
- `changes.md`
- 本报告

用户已有 dirty 文件保持未修改；未添加 broad ignore、未放宽 normalizer、未改变 mismatch classification 来掩盖差异。提交前再次检查只暂存上述四个文件。
