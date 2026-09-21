# Task 3B Atom Metadata Bounded Slice 报告

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
