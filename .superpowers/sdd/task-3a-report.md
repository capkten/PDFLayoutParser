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

## 初始 GREEN 与重复性（eee1685）

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

## Reviewer 修复的 TDD RED/GREEN

针对 reviewer 指出的五个观测缺口，先加入失败断言：固定字段顺序/排序、缺失 run 逐字段 identity、raw refs/source bounds、atom layer、bbox 长度严格比较。命令：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH=(Resolve-Path 'src').Path; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rust_native_span_differential.py
```

修复前 RED 输出：

```text
..FFFFF                                                                  [100%]
5 failed, 2 passed in 0.97s
```

失败均对应真实 harness 缺口：`FIELDS` 是 set、缺失 run 没有逐字段记录、raw run refs/source bounds 丢失、没有 atoms layer、bbox `zip` 静默忽略长度差异。

修复后 focused GREEN 输出：

```text
.........                                                                [100%]
9 passed in 2.75s
```

其中 `test_ledger_json_is_identical_across_hash_seeds` 在独立子进程使用 `PYTHONHASHSEED=1` 和 `PYTHONHASHSEED=2`，对 canonical JSON 做 byte-for-byte 比较；`test_complete_ledger_is_locked_by_count_summary_and_digest` 精确锁定 `334` 条 ledger、fixture/field/class 分布和 SHA-256。

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

修订后的重复运行生成 `334` 条 mismatch；测试精确锁定总数、fixture 分布、字段分布、分类分布和 UTF-8 canonical JSON SHA-256 `8673d7a0bc15072af58ad8e2913937c08e21f1640a0fc9f5509e4b20eb626ac6`。没有 `accepted` 分类，也没有 broad ignore。字段总计如下：

| field | count |
|---|---:|
| presence | 8 |
| value | 32 |
| grouping | 32 |
| text | 32 |
| bbox | 32 |
| ordering | 16 |
| flow/order | 50 |
| font/script | 22 |
| span/run refs | 50 |
| source continuity | 44 |
| errors | 16 |

分类总计：`requires_adaptation=136`、`defect=114`、`unsupported=84`。

每条 ledger 记录均包含 `fixture`、`layer`、`run_identity`、`field`、`python_value`、`rust_value`、`classification`。`run_identity` 用 canonical span refs 标识配对或单侧缺失 run；缺失 run 逐字段记录，不仅记录数量。按 fixture 的完整字段集合如下；同一 fixture 下未列出的字段没有 mismatch：

| fixture | layer | mismatch fields and classification |
|---|---|---|
| `packed_numeric_split` | `span_chain`/`text_runs` + `atoms` | 36 条：`presence,value,grouping,text,bbox,ordering,flow/order,span/run refs,errors=requires_adaptation`; `font/script,source continuity=unsupported`；缺失 Python `S0.2` 逐字段记录 |
| `empty_whitespace_and_separator` | `text_runs` + `atoms` | 7 条：`flow/order,span/run refs=requires_adaptation`; `font/script,source continuity=unsupported` |
| `cjk_whitelist_spacing` | `text_runs` + `atoms` | 7 条：`flow/order,span/run refs=requires_adaptation`; `font/script,source continuity=unsupported` |
| `cjk_non_whitelist_spacing` | `text_runs` + `atoms` | 14 条：`flow/order,span/run refs=requires_adaptation`; `font/script,source continuity=unsupported` |
| `superscript_inline_gap` | `text_runs` + `atoms` | 33 条：`presence,value,grouping,text,bbox,ordering,flow/order,span/run refs,errors=requires_adaptation`; `font/script,source continuity=unsupported` |
| `vertical_wrapped_witness` | `text_runs` + `atoms` | 64 条：`presence,value,grouping,text,bbox,ordering,flow/order,span/run refs,errors=requires_adaptation`; `font/script,source continuity=unsupported` |
| `source_block_line_noncontinuous` | `text_runs` + `atoms` | 14 条：`flow/order,span/run refs=requires_adaptation`; `font/script,source continuity=unsupported` |
| `alignment_corridor_veto` | `text_runs` + `atoms` | 138 条：语义字段与缺失 run 记录为 `defect`；Rust 缺失 metadata 为 `unsupported` |
| `independent_fields_counterexample` | `text_runs` + `atoms` | 14 条：`flow/order,span/run refs=requires_adaptation`; `font/script,source continuity=unsupported`；semantic text/grouping/bbox/presence 保持一致 |
| `single_field_control` | `text_runs` + `atoms` | 7 条：`flow/order,span/run refs=requires_adaptation`; `font/script,source continuity=unsupported` |

关键字段差异：

- packed numeric：Python text 为 `100`, `200`，Rust 为 `100 200`；Python 第一 run bbox 为 `[20, 10, 38, 20]`，Rust 为 `[20, 10, 84, 20]`。
- superscript：Python 将 `基` 与小号 `2` 合并为 `基2`，Rust 保持两个 run。
- wrapped witness：Python 生成 `第一行\n第二行\n第三行`，Rust 保持垂直行 run 分离。
- alignment corridor veto：Python 保持 8 个独立 run，Rust 因基础 inline gap 规则合并为 4 个 run；该语义差异标为 `defect`。
- 缺失 run：`packed_numeric_split` 的 Python `S0.2` 不再只产生一条 presence count mismatch，而是按 `value/grouping/text/bbox/ordering/flow/order/font/script/span/run refs/source continuity/errors` 逐字段保留单侧值和 `run_identity`。
- refs/source：text-run normalizer 保留两侧 raw `span_refs` 及 Rust `source_start/source_end`；atom layer 通过现有 Python `_native_atom_core` 与 Rust `rust_adapter.build_atoms` 比较真实 `run_refs`，不可用的 metadata 显式为 `unsupported`。
- atom：ledger 新增 `atoms` layer；当前 binding 存在，因此没有伪造 capability gap。
- 空白/分隔符、CJK whitelist/non-whitelist、source 不连续、独立字段反例和单字段 control 的 semantic fields（presence/value/ordering/grouping/text/bbox）没有 mismatch；控制行为已由测试逐项断言。

## 限制与后续

Rust `build_text_runs` DTO 当前只返回 text、rect、span_refs、source_start/source_end、order；Rust `AtomDto` 当前只返回 text、rect、run_refs、row_hint、col_hint、order。因此 normalizer 对 Rust 缺失的 font/script、Python flow 区间和 source continuity 显式记录 `unsupported`，并保留可用 raw values。这不是接受差异，也不是为差异加 ignore；后续适配必须以本 ledger 为输入。

本任务不修生产算法。只有 Task 3A reviewer 通过后，才允许 Task 3B 修改 `rust/native_span.rs`。

## 最终检查

命令：

```powershell
git diff --check
```

预期输出为空（无 whitespace error）。提交前会再次运行该检查，并确认提交只包含 Task 3A 文件；既有 dirty 文件保留不变。
