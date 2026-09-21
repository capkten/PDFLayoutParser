# Sprint 005B-1 handoff：TextRunDto evidence 透传

## 状态

Task 3B-1 Generator 实现完成，并已通过独立 `gpt-5.6-luna` reviewer re-check（`fa547c5..5829deb`，Approved）。当前提交只覆盖 text-run source/font/size/flags evidence，不改变 Rust 行聚类、join、拆分、wrapped merge 或默认路由。

## 实现摘要

- `TextRunDto` 新增可选 `evidence`；无 evidence 的旧 DTO 输出 shape 保持不变。
- `TextRunEvidenceDto` 拥有 `source_positions`、`fonts`、`sizes`、`flags`，并在解析时执行 schema、类型、有限数值和等长校验。
- `TextRunDto` 额外拒绝 `source_positions.len() != span_refs.len()`；focused test 同时覆盖 NaN 与 Inf size。
- `build_text_runs` 从实际参与 run 的 `NativeSpanDto` 生成 evidence；不回读页面或动态 Python 对象。
- 未修改 `rust/wireless_structure.rs`、生产 Python、route、Task 3A fixture 和用户 dirty 测试。

## 验证摘要

- 初始 RED：focused pytest 为 `6 failed, 19 passed`，失败明确为 evidence 缺失/非法 evidence 未拒绝。
- Reviewer 修复 RED：`1 failed, 26 passed`，唯一失败为 span/evidence cardinality mismatch 未拒绝。
- 修复后 GREEN：`tests/test_rust_native_span_evidence.py tests/test_pdf_fast_dto.py` 在恢复 legacy-shape 测试前为 `27 passed`；恢复后 fresh verification 为 `28 passed`。
- `cargo test --lib native_span`：`4 passed, 0 failed`。
- Task 3A differential：`11 passed`；564-record ledger 和 SHA-256 digest 未变。
- `git diff --check`：通过。
- `cargo fmt --check`：因仓库既有跨文件格式差异退出码 1；本 slice 未修改禁止文件。

## 独立复审

- Review range：`fa547c5..5829deb`
- Verdict：Spec Compliance ✅；Task quality ✅ Approved
- Reviewer 确认 `tests/test_pdf_fast_dto.py:139-149` 恢复了完整 no-evidence `TextRunDto` round-trip shape/value 断言；本提交只改该测试文件，共 13 行新增。
- Reviewer focused verification：`1 passed`；`git diff --check`：通过。
- 未发现 Critical、Important 或 Minor issue。evidence producer/validation 属于前一实现范围，本复审确认其不被本恢复提交改变。

## 交接前 fresh verification

- evidence + legacy-shape focused pytest：`28 passed`
- Task 3A differential：`11 passed`
- 相关 text-run/columns Python 回归：`54 passed`
- `cargo test --lib native_span`：`4 passed`
- `git diff --check`：通过

## 后续边界

`build_atoms` 的 metadata 继续留给后续 slice。packed numeric、superscript、wrapped merge、alignment corridor、column/grid/header 均未启动；下一 bounded slice 为 packed numeric split，仍须先 RED、再最小 GREEN、focused regression 和独立 Luna review。`cargo fmt --check` 仍受仓库既有跨文件格式差异影响，未在本任务中修改禁止文件。
