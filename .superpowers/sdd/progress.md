# Superpowers SDD Progress

## Migration: PageSnapshot 到 Rust 无线结构行为等价

- Worktree: `D:\\codes\\PDFLayoutParser-Fast\\.worktrees\\rust-migration-replan`
- Branch: `codex/rust-migration-replan`
- Required subagent model: `gpt-5.6-luna`
- Active plan: `docs/superpowers/plans/2026-09-21-rust-migration-replan.md`
- Current review gate: Task 3A differential observability is independently approved through `70de696`; Task 3B-1 evidence slice is independently approved through `5829deb`; all Task 3B bounded slices, including the final atom metadata fix, are independently approved through `45fec29`; Task 4A–4D are implemented with focused verification; Task 5/6 page acceptance and final audit are complete with an explicit Rust-primary hold. Task 4C/4D reviews were intentionally not dispatched because the user selected direct implementation. The default Python route remains unchanged.

## Task ledger

- Task 0: Rust audit and plan reorganization — complete; independent Luna Planner audit recorded in `.superpowers/sdd/rust-plan-review-luna-20260921.md`
- Task 1: Python-derived NativeRegionInput transition boundary — complete and independently approved; commits `dd9c187`, `da6e400`, `ee91f55`, `803f673`, `1720ffb`; focused pytest `99 passed`, `cargo test --lib` `50 passed`
- Task 2: Snapshot/native-span DTO and strict Rust output slice — complete and independently approved; commits `4362b59`, `b8224ce`, `a332661`; focused pytest `89 passed`, `cargo test --lib` `50 passed`
- Task 3A: field-level span/text-run/atom differential observability — complete and independently approved; commits `eee1685`, `fa1e574`, `70de696`; focused differential `9 passed`, related Python `57 passed`, `cargo test --lib native_span` `4 passed`; stable ledger `564` records with canonical digest recorded in the report
- Task 3B-1: `TextRunDto` source/font/size/flags evidence passthrough — complete and independently approved; commits `6c0e2b9`, `fa547c5`, `5829deb`; final evidence/legacy-shape pytest `28 passed`, Task 3A differential `11 passed`, related text-run/columns Python `54 passed`, `cargo test --lib native_span` `4 passed`; `git diff --check` passed
- Task 3B-PN: packed numeric span split — complete and independently approved; commits `02fac09`, `ad4e210`, `7a2fd10`; final focused Python `19 + 11 + 56 passed`, `cargo test --lib native_span` `4 passed`; ledger reduced from `564` to `510` records, with packed semantic mismatch reduced to `0`; final reviewer approved Spec Compliance and Task quality.
- Task 3B-SG: superscript inline gap — complete and independently approved; commits `dd5d7b9`, `3d5953d`; RED included the `基2` positive and placeholder/numeric veto counterexamples; fresh binding differential/text-run `59 passed`, packed numeric `20 passed`, `cargo test --lib native_span` `4 passed`; re-review approved Spec Compliance and Task quality with no findings.
- Task 3B-WM: wrapped field merge — complete and independently approved; commits `3fc2844`, `23240f5`, `aee23c1`; RED covered missing witness merge and filtered-source flow gap, and the final private flow ordinal preserves public `TextRunDto.order`/source bounds; fresh combination regression `84 passed`, `cargo test --lib native_span` `4 passed`, `git diff --check` passed; independent Luna re-review approved Spec Compliance and Task quality with no findings. Next bounded slice is alignment corridor.
- Task 3B-AC: alignment corridor veto — complete and independently approved; commit `7fb8ea0`; alignment semantic defect was removed while column/grid/header/route remained untouched.
- Task 3B-AM: atom metadata and final ledger — complete and independently approved; commits `d7a195b`, `03d7da0`, `45fec29`; final differential `26 passed`, evidence/text-runs/packed numeric combination `74 passed`, ledger/separator/hash-seed checks `5 passed`, `cargo test --lib native_span` `4 passed`, `git diff --check` passed; final reviewer found no Critical/Important/Minor and returned `Ready to merge: Yes`.
- Task 3B: span chain and text-run/atom semantic migration — complete; all bounded slices are closed, final ledger has `111` records with SHA256 `cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81`.
- Task 4A: owned-input wireless structure differential harness — complete and independently approved; commits `fad4b92`, `d0774c2`, `ba3afe1`, `b48c56b`, `8c866bd`; focused differential pytest `10 passed`, reconstructed baseline RED exit `1` (explicitly non-historical), `git diff --check` passed, final Luna re-review approved Spec Compliance and Task quality.
- Task 4: column bands, physical grid and header topology parity — bounded implementation complete; Task 4A–4D focused verification complete; page-level acceptance remains Task 5.
- Task 4C: physical grid and occupancy contract — implementation committed as `ed8fa7c`; focused Rust `27 passed`, focused Python `49 passed`, full Rust lib `56 passed`, `cargo check` and `git diff --check` passed; independent review intentionally not dispatched by explicit user choice.
- Task 4D: logical row/header-span transaction and empty-slot materialization — committed as `056856f`; focused Python `102 passed`, focused Rust `31 passed`, full Rust lib `60 passed`, fresh maturin binding rebuilt, `cargo check` and `git diff --check` passed; independent review intentionally not dispatched by explicit user choice.
- Task 5: two-route shadow and page acceptance — complete; five-page three-mode output generated at `D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`; focused normalizer/runner `8 passed`; shadow semantic equality holds for all five pages; comparison has 2894 explicitly classified `defect` records and 0 unclassified records.
- Task 6: final review and completion verification — complete as an audit/handoff; combination matrix `140 passed`, `cargo test --lib` `60 passed`, `cargo check` and `git diff --check` passed. Rust primary remains blocked by the recorded page/region defects; default Python route unchanged.

## Decisions

- Python current behavior is the candidate oracle.
- `PageSnapshot` is the only structure-recovery input after capture.
- Default routing remains Python; shadow returns Python; Rust errors fall back to Python.
- No parity may be manufactured by broad tolerance, business-text special cases, or swallowed occupancy conflicts.
- Full Chinese/mixed wireless Rust parity is not complete and must not be claimed until differential/page evidence supports it.
- Task 1 review: independent Luna reviewer approved `803f673..1720ffb`; malformed Snapshot span geometry is observable before collector filtering, present evidence/run refs are strict, and Python raw oracle atoms remain separate from Rust core DTOs.
- Task 2 review: independent Luna reviewer approved `1720ffb..a332661`; explicit cell `rect`, optional `page_y0`, strict unknown keys, and PageSpy route isolation are covered. Minor: PageSpy uses an empty Snapshot and is not a non-empty extraction proof.
- Task 3A plan: build the field-level normalizer and mismatch ledger before changing `rust/native_span.rs`; current differences must be observed and classified, not hidden or pre-accepted.
- Task 3A review: independent Luna reviewer approved `fa1e574..70de696`; identity-bucket matching, single-sided run field records, duplicate-identity errors, stable ordering/hash-seed output, atom observations, raw refs/source bounds, and exact ledger digest are covered. The 564 observed differences remain migration inputs, not accepted parity.
- Task 3B-1 review: independent Luna reviewer approved `fa547c5..5829deb`; the restored legacy no-evidence DTO shape assertion is exact and scoped to the requested compatibility contract. Evidence producer/validation remains covered by the preceding 3B-1 implementation commits and focused tests.
- Task 3B-WM review: independent Luna reviewer initially found that raw source order and visual run order were not Python flow; the bounded fix introduced private filtered native-flow ordinals while keeping public source bounds unchanged. Re-review of `3fc2844..aee23c1` approved Spec Compliance and Task quality with no Critical/Important/Minor findings.
- Task 3B final review: independent Luna reviewer checked `review-03d7da0..45fec29.diff`; no Critical, Important, or Minor findings. The final ledger is `111` records with SHA256 `cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81`. Page-level PDF JSON/PNG rerun remains a Task 5/page-acceptance item, not a Task 3B blocker.

## Task 5/6 final decision (2026-09-23)

- 页面验收脚本：`scripts/run_task5_shadow_acceptance.py`；字段 normalizer：`src/hexai_pdf_parser/debug/rust_task5_acceptance.py`；测试：`tests/test_rust_wireless_shadow_differential.py`。
- 代表页面：184、188、189、191、192（0-based）；覆盖 `recover_wireless_tables()` 和 `recover_cells_from_region()`。
- 结构化验收：python/shadow/rust 各 5 页，artifact 路径和 input SHA256 已核对；shadow 返回 Python 结果，Rust diagnostics/fallback 保留。
- comparison 分类：`defect=2894`、`unclassified=0`。184/191/192 的 Rust page route 触发 occupancy fallback；188/189 的 Rust page route 结构与 Python 不同；region route 五页均有差异。
- 视觉验收：五页 Python/Rust overlay 已检查，188/189 的 Rust 视觉缺陷与结构报告一致；184/191/192 的相同 overlay 不能被当成 Rust parity，因为对应 page route 发生了 fallback。
- 门禁：Task 5/6 交付完整，但 Rust primary gate FAIL；继续保持 Python primary，后续修复必须基于 defect ledger 和新的独立输出目录。
