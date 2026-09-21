# Task 3A 报告：span/text-run/atom 字段级差分观测

## 结论

Task 3A harness 已建立。它从同一份 UTF-8 JSON fixture 读取 owned synthetic native-span vectors，分别构造 Python `NativeSpan` → `region_spans()` → `build_text_runs()` 输入，以及现有 `rust_adapter.build_text_runs()` 所需 DTO；未读取 `fitz.Page`，未调用 `page.get_text("words")`。

生产算法、`rust/native_span.rs`、`rust/wireless_structure.rs`、生产 Python、默认 route、shadow 返回语义、fallback 合同和已有 dirty 用户文件均未修改。

## TDD RED

先创建最小 fixture 与测试，命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py
```

RED 输出：

```text
F                                                                        [100%]
AssertionError: assert ['100', '200'] == ['100 200']
1 failed in 0.66s
```

失败原因是实际 packed numeric 字段的文本/分组差异：Python `region_spans()` 依据字符 bbox 拆成两个字段，Rust helper 保留为一个 run；不是语法错误、fixture 错误或数量-only 断言。

## GREEN 与重复性

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py
```

输出：

```text
..                                                                       [100%]
2 passed in 0.40s
```

测试两次生成 ledger 并要求完全相等；同时验证 fixture 场景集合、字段级 key、分类白名单、Python control 结果、wrapped newline 结果，以及默认 Python route 和 shadow 保持 Python 返回值。

## 相关既有测试

命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_columns.py tests/test_rust_snapshot_span_parity.py
```

输出：

```text
.........................................................                [100%]
57 passed in 4.12s
```

Rust 单测命令：

```powershell
cargo test --lib native_span
```

输出摘要：

```text
running 4 tests
test native_span::tests::test_filters_spaced_text_separator_rows ... ok
test native_span::tests::test_whitelist_cjk_merge ... ok
test native_span::tests::test_non_whitelist_cjk_separated ... ok
test wireless_structure::tests::test_recover_wireless_tables_normalizes_split_native_spans_before_grid ... ok
test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 46 filtered out
```

## 完整 mismatch ledger 摘要

重复运行生成 `95` 条 mismatch；没有 `accepted` 分类，也没有 broad ignore。字段总计如下：

| field | count |
|---|---:|
| presence | 4 |
| value | 8 |
| grouping | 8 |
| text | 8 |
| bbox | 8 |
| flow/order | 17 |
| font/script | 17 |
| span/run refs | 8 |
| source continuity | 17 |

分类总计：`requires_adaptation=36`、`defect=25`、`unsupported=34`。

每条 ledger 记录均包含 `fixture`、`layer`、`field`、`python_value`、`rust_value`、`classification`。按 fixture 的完整字段集合如下；同一 fixture 下未列出的字段没有 mismatch：

| fixture | layer | mismatch fields and classification |
|---|---|---|
| `packed_numeric_split` | `span_chain`/`text_runs` | `presence,value,grouping,text,flow/order,span/run refs,bbox=requires_adaptation`; `font/script,source continuity=unsupported` |
| `empty_whitespace_and_separator` | `text_runs` | `flow/order=requires_adaptation`; `font/script,source continuity=unsupported` |
| `cjk_whitelist_spacing` | `text_runs` | `flow/order=requires_adaptation`; `font/script,source continuity=unsupported` |
| `cjk_non_whitelist_spacing` | `text_runs` | `flow/order=requires_adaptation`; `font/script,source continuity=unsupported` |
| `superscript_inline_gap` | `text_runs` | `presence,value,grouping,text,flow/order,span/run refs,bbox=requires_adaptation`; `font/script,source continuity=unsupported` |
| `vertical_wrapped_witness` | `text_runs` | `presence,value,grouping,text,flow/order,span/run refs,bbox=requires_adaptation`; `font/script,source continuity=unsupported` |
| `source_block_line_noncontinuous` | `text_runs` | `flow/order=requires_adaptation`; `font/script,source continuity=unsupported` |
| `alignment_corridor_veto` | `text_runs` | `presence,value,grouping,text,flow/order,span/run refs,bbox=defect`; `font/script,source continuity=unsupported` |
| `independent_fields_counterexample` | `text_runs` | `flow/order=requires_adaptation`; `font/script,source continuity=unsupported`; semantic text/grouping/bbox/presence 保持一致 |
| `single_field_control` | `text_runs` | `flow/order=requires_adaptation`; `font/script,source continuity=unsupported` |

关键字段差异：

- packed numeric：Python text 为 `100`, `200`，Rust 为 `100 200`；Python 第一 run bbox 为 `[20, 10, 38, 20]`，Rust 为 `[20, 10, 84, 20]`。
- superscript：Python 将 `基` 与小号 `2` 合并为 `基2`，Rust 保持两个 run。
- wrapped witness：Python 生成 `第一行\n第二行\n第三行`，Rust 保持垂直行 run 分离。
- alignment corridor veto：Python 保持 8 个独立 run，Rust 因基础 inline gap 规则合并为 4 个 run；该语义差异标为 `defect`。
- 空白/分隔符、CJK whitelist/non-whitelist、source 不连续、独立字段反例和单字段 control 的 semantic fields（presence/value/ordering/grouping/text/bbox）没有 mismatch；控制行为已由测试逐项断言。

## 限制与后续

Rust `build_text_runs` DTO 当前只返回 text、rect、span_refs、source_start/source_end、order，因此 normalizer 对 Rust 缺失的 font/script、Python flow 区间和 source continuity 显式记录 `unsupported`。这不是接受差异，也不是为差异加 ignore；后续适配必须以本 ledger 为输入。

本任务不修生产算法。只有 Task 3A reviewer 通过后，才允许 Task 3B 修改 `rust/native_span.rs`。

## 最终检查

命令：

```powershell
git diff --check
```

预期输出为空（无 whitespace error）。提交前会再次运行该检查，并确认提交只包含 Task 3A 文件；既有 dirty 文件保留不变。
