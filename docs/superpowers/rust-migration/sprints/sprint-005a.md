# Sprint 005A：Task 3A 字段级差分观测 handoff

## 交付范围

本 sprint 只建立 Python `span_chain/text_runs` oracle 与现有 Rust PyO3 `build_text_runs` helper 的字段级差分观测 harness。输入来自同一份 owned synthetic native-span vector fixture；没有修改生产 Rust、生产 Python、默认 route、shadow route 或 fallback 合同。

## 交付文件

- `tests/test_rust_native_span_differential.py`
- `tests/fixtures/rust_migration/wireless/native_span_differential.json`
- `.superpowers/sdd/task-3a-report.md`
- 本 handoff

## 观测覆盖

fixture 明确覆盖 packed numeric split、空白/分隔符、CJK whitelist/non-whitelist、superscript inline gap、vertical wrapped witness、source block/line 不连续、alignment corridor veto、单字段 control 和不相邻独立字段反例。

normalizer 按字段比较 presence、value、ordering、grouping、text、bbox（0.01 容差）、flow/order、font/script、span/run refs、source continuity、errors。每条差异包含 fixture、layer、field、两侧值和分类；分类只使用 `requires_adaptation`、`defect`、`unsupported`。

## 验证与限制

- RED 先证明 packed numeric 的实际字段差异：Python 为 `100`, `200`，Rust 为 `100 200`。
- GREEN focused differential 为 `2 passed`。
- 既有相关 Python tests 为 `57 passed`。
- `cargo test --lib native_span` 为 `4 passed`。
- Rust helper 当前不输出 font/script、Python flow 区间和 source continuity；这些缺口在 ledger 中标为 `unsupported`，没有标成 accepted，也没有 broad ignore。
- alignment corridor 场景记录为 `defect`；packed numeric、superscript、wrapped witness 记录为 `requires_adaptation`。

## Handoff gate

Task 3A reviewer 通过前不得开始 Task 3B，不得修改 `rust/native_span.rs` 或 `rust/wireless_structure.rs`。其他 dirty 用户文件保持原样。
