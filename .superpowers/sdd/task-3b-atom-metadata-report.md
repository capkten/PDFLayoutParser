# Task 3B Atom Metadata Bounded Slice 报告

## Review Fix（2026-09-21）

### Reviewer findings resolution

1. **Important：atom order 使用错误来源。** `rust/native_span.rs::build_atoms()` 现在在 `flow_start` 存在时将其写入 `AtomDto.order`，只有 legacy run 无 flow 时才回退到 `TextRunDto.order`；`run_refs` 仍直接来自 `run.span_refs`。回归锁定 packed numeric fragment 的 `1/2` order，以及 filtered source gap 后 wrapped chain 的 `flow_start=1`、`order=1`。
2. **Important：partial atom metadata bundle。** `rust/lib.rs::build_atoms_binding()` 现在只有在 `flow_start`、`flow_end` 和非空 `evidence.source_positions` 同时存在时，才一起输出 `flow_start`、`flow_end`、`source_blocks`、`source_line_start`、`source_line_end`、`source_position_known` 六个 key。evidence-only/no-flow、flow-only 或空 source evidence 均不添加任何新 atom metadata；legacy TextRunDto 无 evidence shape 保持不变。
3. **Minor：differential normalizer 过度忽略。** `_normalized_atoms()` 现在读取 Rust 实际 atom `order`、`flow_start/end`，run 的 `source_start/end`，以及完整 source continuity bundle；不再用 `None` broad ignore。旧 semantic fixture 断言保留。

### TDD 记录

先添加回归测试，未修改生产代码：

```text
focused atom metadata：3 failed, 2 passed, 20 deselected
normalizer real metadata：1 failed, 24 deselected
```

失败分别捕获：packed/wrapped atom order 仍使用视觉 order、evidence-only/no-flow 仍输出 partial source metadata，以及 normalizer 将 Rust flow/source 字段置为 `None`。随后执行 `maturin develop --release`，实现最小修复并运行：

```text
focused atom metadata：6 passed, 19 deselected
tests/test_rust_native_span_differential.py：25 passed
```

### 新 Differential ledger

- ledger 每条 mismatch 现在显式记录 `reason`；`empty_whitespace_and_separator` 的两条 `flow/order` mismatch 均为 `requires_adaptation`，但根因分层记录：`text_runs/S2` 是 Rust 普通 text run 未透传 flow metadata，Python 保留 separator 过滤后的 source flow `2`；`atoms/S2` 是 Rust 暴露过滤后的 local flow/order `1`，而 Python atom 保留 source order `2`。两者的 `source_start/source_end` 均为 `2`，不应合并描述为单条差异。
- total：`111`
- fixture counts：`alignment_corridor_veto=40`、`cjk_non_whitelist_spacing=10`、`cjk_whitelist_spacing=5`、`empty_whitespace_and_separator=6`、`independent_fields_counterexample=10`、`packed_numeric_split=10`、`single_field_control=5`、`source_block_line_noncontinuous=10`、`superscript_inline_gap=5`、`vertical_wrapped_witness=10`
- field counts：`flow/order=23`、`font/script=22`、`source continuity=22`、`span/run refs=44`
- classification counts：`defect=8`、`requires_adaptation=15`、`unsupported=88`
- SHA256：`cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81`

真实 metadata 参与比较后，atom source continuity mismatch 清零；separator fixture 的两条 flow/order 差异现在按 text_runs 与 atoms 分别可审计，均属于既有过滤流 adaptation，不属于本 review fix。没有修改 `tests/test_wireless_extractor_split.py`、`tests/test_wireless_structure_recoverer.py`，没有修改 `rust/wireless_structure.rs` 或 column/grid/header/route。

### 未解决 concerns

- 本次仅覆盖 native span/text-run/atom binding 和 differential synthetic fixtures；页面级 PDF JSON/PNG 重跑未执行。
- `AtomDto` core contract 未扩展，metadata 仍是 binding 的可选附加字段；legacy caller 的旧 order/source bounds/evidence 语义保持不变。

## 范围与基线

- 工作目录：`D:/codes/PDFLayoutParser-Fast/.worktrees/rust-migration-replan`
- 基线：`7fb8ea0`（alignment corridor 已通过独立 review）
- 仅修改 `rust/native_span.rs`、`rust/types.rs`、`rust/lib.rs`、`tests/test_rust_native_span_differential.py`、`changes.md` 和本报告。
- `tests/test_wireless_extractor_split.py`、`tests/test_wireless_structure_recoverer.py` 的既有 dirty 改动原样保留，未提交。

## 根因

1. `rust/native_span.rs::build_atoms()` 使用 `TextRunDto.order` 构造 `run_refs`，丢失了 run 自有的 `span_refs`；当视觉顺序与 source span 集合不同，atom 不能保留来源连续性。
2. `WrappedRun` 内部已经维护过滤后、packed split 后的 native flow ordinal，但普通 run 和 `merge_run_chain()` 返回 `TextRunDto` 时没有透传 flow 区间。
3. `TextRunEvidenceDto` 保留了 source positions，但原 binding 只序列化 core `AtomDto`，因此 atom 边界看不到 source block/line evidence。

## 实现与判定

- `TextRunDto` 新增可选 `flow_start`、`flow_end`。只有 native builder 产生 flow 时才写入 DTO；legacy caller 未提供时不序列化，`order`、`source_start`、`source_end` 的既有含义不变。
- `build_text_runs()` 在 region 过滤和 packed numeric split 后生成 local flow，普通 run 记录 group 的最小/最大 flow；wrapped chain 记录首 run 到末 run 的 flow 区间，因此过滤 separator/source gap 不会污染 flow，wrapped chain 也覆盖完整区间。
- `build_atoms()` 的 `run_refs` 直接来自 `run.span_refs`。
- `build_atoms` PyO3 binding 在 core atom dict 上追加可选 metadata：非空 owned evidence 的 block 去重排序后写入 `source_blocks`，line 取最小/最大值，`source_position_known=True`；无 evidence 时不添加这些 keys。core `AtomDto` 没有扩展，未知 binding keys 仍不影响 `AtomDto::from_py()`。
- 没有读取 `fitz.Page` 或 `page.get_text("words")`，没有修改 `rust/wireless_structure.rs`、column/grid/header/route 逻辑。

## TDD 记录

### RED

新增测试后运行：

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest -q tests/test_rust_native_span_differential.py -k 'build_atoms_uses_source_span_refs_not_visual_run_order or build_atoms_preserves_flow_and_owned_source_evidence or build_atoms_flow_covers_filtered_gap_and_wrapped_chain or build_atoms_keeps_legacy_no_evidence_shape'
```

结果：`3 failed, 1 passed, 20 deselected`。失败分别证明 visual order 被错误用作 `run_refs`、atom 没有 flow metadata、filtered gap/wrapped chain 没有 flow metadata；legacy no-evidence shape 保护通过。

### GREEN 与回归

| 命令 | 结果 |
|---|---|
| focused atom metadata pytest | `4 passed, 20 deselected` |
| `pytest -q tests/test_rust_native_span_differential.py` | `24 passed` |
| `pytest -q tests/test_rust_native_span_evidence.py` | `9 passed` |
| `pytest -q tests/test_wireless_structure_text_runs.py` | `45 passed` |
| `cargo test --lib native_span` | `4 passed; 0 failed`，另有 `46 filtered out` |
| `git diff --check` | exit code `0`，无输出 |
| `maturin develop --release` | 成功重建并安装 `hexai_pdf_parser-1.1.1` |

新增用例覆盖：packed numeric 两个 fragment 的 `1..1`/`2..2` flow、过滤区域外 source gap 后 wrapped chain 的 `1..3` flow、source block/line metadata、`order != span_refs` 反例、独立字段不合并路径，以及无 evidence legacy shape。

## Differential ledger

- total：`154`
- fixture counts：`alignment_corridor_veto=56`、`cjk_non_whitelist_spacing=14`、`cjk_whitelist_spacing=7`、`empty_whitespace_and_separator=7`、`independent_fields_counterexample=14`、`packed_numeric_split=14`、`single_field_control=7`、`source_block_line_noncontinuous=14`、`superscript_inline_gap=7`、`vertical_wrapped_witness=14`
- field counts：`flow/order=44`、`font/script=22`、`source continuity=44`、`span/run refs=44`
- classification counts：`defect=16`、`requires_adaptation=28`、`unsupported=110`
- SHA256：`b3fdf184452653d59047dacbc57150bef6bdb0e17498043dce35016e132e54e0`

Digest 相比基线变化是预期的：atom layer 的 run refs 现在保留 source span refs，例如 wrapped chain 从旧的 visual `[0]` 改为 `[0, 1, 2]`；总数和分类计数不变。

## 未解决限制

- 本 slice 只在 native span/text-run/atom binding 边界暴露可选 metadata；core `AtomDto` 及未要求的 recovery/structure 输出合同保持不变。
- 本次验证覆盖 synthetic differential fixtures 和 Rust/Python 相关单元测试，未执行页面级 PDF JSON/PNG 重跑；没有可用于该 bounded slice 的额外页面验收输入。

## Final Fresh Verification（2026-09-21）

最终独立 reviewer `Tesla`（`gpt-5.6-luna`）审查 `review-03d7da0..45fec29.diff`，结论如下：

- Critical：无；Important：无；Minor：无。
- Assessment：`Ready to merge: Yes`。
- Reviewer 确认 review package 仅包含预期的 3 个修复文件，没有修改生产 Rust、Task 4 文件或用户已有 dirty 文件。
- Reviewer 确认 `empty_whitespace_and_separator` 的两条 flow/order mismatch 均有显式 reason，并区分 `text_runs/S2` 与 `atoms/S2`；ledger count、field/classification counts 和 SHA256 均与测试锁定值一致。

本轮 fresh verification（在 reviewer 之后重新执行）：

| 命令 | 结果 |
|---|---|
| `maturin develop --release` | 成功；仅有既有 invalid distribution `~ydantic` 环境警告 |
| `pytest -q tests/test_rust_native_span_differential.py` | `26 passed in 1.79s` |
| `pytest -q tests/test_rust_native_span_evidence.py tests/test_wireless_structure_text_runs.py tests/test_rust_native_span_packed_numeric.py` | `74 passed in 0.54s` |
| `cargo test --lib native_span` | `4 passed; 0 failed`，另有 `46 filtered out` |
| differential ledger/separator/hash-seed tests | `5 passed, 21 deselected` |
| `git diff --check` | 通过 |

最终 ledger 仍为 `111` 条，分类为 `defect=8`、`requires_adaptation=15`、`unsupported=88`，SHA256 为
`cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81`。

Task 3B 至此完成。页面级 PDF JSON/PNG 重跑仍未执行，属于后续 Task 5 页面验收；默认 Python route、shadow route、Rust fallback policy 均保持不变。Task 4 尚未开始。
