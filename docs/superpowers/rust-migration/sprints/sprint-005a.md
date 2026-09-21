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

## Reviewer 修复记录

reviewer 指出 eee1685 的字段遍历受 hash seed 影响、缺失 run 只有 count mismatch、raw refs/source 被丢弃、没有 atom layer、bbox 长度不严格。先加入五个最小失败断言，RED 为 `5 failed, 2 passed`；修复后 focused 为 `9 passed`。

现在使用固定 `FIELDS` tuple、稳定 ledger key 和独立 `PYTHONHASHSEED=1/2` 子进程比较；缺失 run 按 `run_identity` 逐字段记录；保留 raw span refs、Rust source bounds 和 atom run refs；通过现有 Python `_native_atom_core` 与 Rust `rust_adapter.build_atoms` 比较 atoms；bbox 先比较长度再使用 0.01 容差。

re-review 又发现中间缺失 run 不能按 index 配对。先加 RED（`1 failed, 9 passed`），再改为按 canonical grouping/span refs identity buckets 对齐；修复后 focused 为 `11 passed`。相同 identity 配对，单侧 identity 生成具体 presence 和全部字段，重复 identity 生成 errors，不使用位置 fallback。

完整 ledger 已锁定为 `564` 条，SHA-256 为 `5093640efdb9d73e66d6f8adacafc7f635c0e0eded129989677407083044ab59`；分类为 `requires_adaptation=208`、`defect=218`、`unsupported=138`。

## 验证与限制

- RED 先证明 packed numeric 的实际字段差异：Python 为 `100`, `200`，Rust 为 `100 200`。
- 初始 GREEN focused differential 为 `2 passed`；第一轮 reviewer 修复后为 `9 passed`；re-review identity 修复后为 `11 passed`。
- 既有相关 Python tests 为 `57 passed`。
- `cargo test --lib native_span` 为 `4 passed`。
- Rust helper 当前不输出 font/script、Python flow 区间和 source continuity；这些缺口在 ledger 中标为 `unsupported`，没有标成 accepted，也没有 broad ignore。atom layer 已实际调用两侧 helper，未伪造能力。
- alignment corridor 场景记录为 `defect`；packed numeric、superscript、wrapped witness 记录为 `requires_adaptation`。

## Handoff gate

Task 3A reviewer 通过前不得开始 Task 3B，不得修改 `rust/native_span.rs` 或 `rust/wireless_structure.rs`。其他 dirty 用户文件保持原样。
