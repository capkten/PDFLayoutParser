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

## Review fix：filtered-source-gap

### 根因

原实现把 `source_start/source_end` 同时用于 wrapped helper 的局部排序、相邻连续性和
witness-after 判断。`source_start/source_end` 是原始 span order 的公开来源边界；当中间
span 被 region 过滤后，它们不再表示 Python oracle 的连续 flow。该复现会使 Python 合并
三行，而旧 Rust 仅合并后两行。

### Fix RED

先新增 `test_wrapped_field_merge_ignores_filtered_source_gap`：在 wrapped spans 中插入
一个 source order 位于中间、bbox 位于 region 外的 span，并断言文本、bbox、span refs、
source bounds 和 evidence。运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan\src'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py -k filtered_source_gap
```

真实输出：`1 failed, 18 deselected`。失败显示旧 Rust 输出三个 run，而 Python 输出左侧
三行 wrapped run 和右侧独立字段，确认回归测试捕获目标缺陷。

### 最小修复与 GREEN

`build_text_runs()` 在 wrapped merge 前按已有 `source_start/source_end/order` 对已过滤的
run 建立连续 `run.order`。wrapped helper 的排序、相邻 pair 连续性、witness-after 和
chain membership 仅使用该连续 `order`；`source_start/source_end` 仍只作为原始来源边界
输出。没有修改 Python 生产路径、route、alignment corridor 或后续 atom/column/grid/header
逻辑。反例测试同时断言 Python/Rust 文本结构列表相等。

GREEN focused：`pytest -q tests/test_rust_native_span_differential.py -k wrapped`，真实输出：
`5 passed, 14 deselected`。

### 最终验证

`maturin develop --release`：`Finished release profile [optimized]`、`Built wheel`、
`Installed hexai_pdf_parser-1.1.1`，退出码 `0`；pip 输出既有 invalid distribution
`~ydantic` 警告。

组合回归命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan\src'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py tests/test_wireless_structure_text_runs.py tests/test_rust_native_span_packed_numeric.py
```

真实输出：`84 passed in 2.49s`。

`cargo test --lib native_span` 真实输出：`4 passed; 0 failed; 0 ignored; 0 measured; 46 filtered out`。

`git diff --check` 真实输出：无输出，退出码 `0`。

修复后 ledger 仍为 `364` 条，fixture/field/classification 计数不变；因 flow/order 结果按
过滤后序列变化，最终 SHA256 为
`2d139ae83aba7551db0d29a34d19225cee689dfd950fa3456122d8a0056ace76`。

### 修复范围自审

- 修改仅涉及 `rust/native_span.rs`、`tests/test_rust_native_span_differential.py`、`changes.md` 和本报告。
- 未修改用户 dirty 文件 `tests/test_wireless_extractor_split.py`、`tests/test_wireless_structure_recoverer.py`。
- 未改变 source bounds 的公开语义；未回读 `fitz.Page` 或 `page.get_text("words")`。
- wrapped、witness、geometry、packed numeric、superscript、placeholder 和 normal numeric join 回归均通过。

## 当前交付状态补充

按 bounded review 交付要求停止后续长测试。此前带临时过滤后 run 重编号的版本曾得到
focused `5 passed, 14 deselected` 和组合 `84 passed`；为遵守“直接使用
build_text_runs 已分配的 run.order”的最小化约束，移除了该额外重编号后，最终源码的
focused 命令重新运行结果为 `4 failed, 1 passed, 14 deselected`。失败原因是当前
`run.order` 仍按视觉行构造，在右侧同 y 行插入时不等于过滤后的 source-flow ordinal；
因此最终组合回归、cargo 和最终构建安装未在该最终源码状态下重新完成。该未完成状态和
concern 已如实保留，未宣称最终 GREEN。
