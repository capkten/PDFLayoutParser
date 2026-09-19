# Snapshot parity baseline（2026-09-19）

## 状态与权威输出

本文件的唯一权威基线输出是成功重跑生成的 `snapshot-parity-baseline-20260919-rerun`。该输出已完成 17 页 Shadow 采集，但包含 `rust_output_mismatch`/`rust_fallback`，因此不能宣称 parity 通过。

旧目录 `D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919` 明确标记为历史、非权威输出；后续任务不得将其作为当前基线或据此覆盖本文件中的 `-rerun` 路径、统计和结论。

## 来源与工作树证据

- 工作树：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration`
- 模式：`shadow`
- 权威 manifest：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919-rerun\manifest.json`
- 权威 routing diagnostics：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919-rerun\routing-diagnostics.json`
- 权威输出目录绝对路径：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919-rerun`
- 历史、非权威输出目录：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919`
- 输入 PDF：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`
- 输入 PDF SHA256：`376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`
- 权威 manifest 中的运行 HEAD/commit：`e188045b5844a9e7ec6b71287d669ff0e763a9e8`
- 起始 patch SHA256（既有审计记录）：`46F3342B930F5A45062533463B1980ECDD0C475F86690927540AB44B80EA1F8A`

### 提交前 status 快照（采集于 baseline 文档提交前）

- 分支：`codex/rust-full-migration`
- 该快照记录工作树保留既有 modified/untracked 文件；未执行 reset/checkout/clean。
- 该快照不是当前状态。baseline 文档提交后的实际状态以 Git 为准；不要用本节快照替代当前 `git status`。

## 页面基线

- `page_results` 实际数量：**17**
- 17/17 页状态为 `success`
- 页索引（0-based）：`0, 75, 185, 187, 188, 191, 336, 408, 417, 423, 427, 432, 444, 984, 1005, 1013, 1018`
- dpi：`72`
- model：`rule_first`
- environment：`windows`

## Shadow 路由诊断计数

权威 `routing-diagnostics.json` 实际记录 39 条诊断：

| 分类 | 实际数量 |
| --- | ---: |
| `rust_output_mismatch` | 30 |
| `rust_fallback` | 9 |
| `candidate_rejected` | 0（JSON 中未出现） |
| `accepted_numeric_difference` | 0（JSON 中未出现） |
| 合计 | 39 |

权威 manifest 的 `routing_status_counts` 与上述 JSON 汇总一致：`rust_output_mismatch=30`、`rust_fallback=9`；`routing_diagnostics_count=39`。

## 运行参数与版本

- Python：`3.12.10`
- PyMuPDF：`1.28.2`
- Cargo/Rust：`cargo 1.96.0`、`rustc 1.96.0`
- Rust 扩展 crate/package：`hexai_pdf_parser 1.1.1`（来自当前 `Cargo.toml`）；扩展无运行时 `__version__` 字段

## Shadow 重跑证据

- brief 原始 Shadow 命令首次退出码为 `1`，原因为环境路径问题：`ImportError: cannot import name 'rust_adapter' from 'hexai_pdf_parser' (D:\codes\PDFLayoutParser\src\hexai_pdf_parser\__init__.py)`。
- 修正命令前设置 `PYTHONPATH=D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src` 后，Shadow 退出码为 `0`。
- 修正运行未覆盖历史目录；manifest 与 routing diagnostics 均生成于权威目录 `D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919-rerun`。

## 已记录的验证证据

- `cargo test`：退出码 `0`；Rust 单元测试 `43 passed; 0 failed`；doc-tests `0 passed; 0 failed`。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 下指定迁移专项 pytest：退出码 `0`；`57 passed in 1.62s`。
- `git diff --check`：退出码 `0`，无输出。

以上是基线采集阶段记录的证据；本次仅做文档修复，未重新运行测试。

## 限定结论

权威 `-rerun` 输出已生成并可作为后续任务的唯一比较输入：17/17 页成功、39 条路由诊断，其中 30 条 `rust_output_mismatch`、9 条 `rust_fallback`。这些 mismatch/fallback 保留为后续任务输入；`candidate_rejected=0` 与 `accepted_numeric_difference=0` 仅表示权威 routing JSON 中未出现，不表示额外验证已通过。历史 `snapshot-parity-baseline-20260919` 目录不具备权威性。
