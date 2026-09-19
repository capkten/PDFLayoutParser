# Snapshot parity baseline（2026-09-19）

## 状态

本文件只整理前一代理已经生成的现有 Shadow 输出；本次未重跑导出命令、测试或 git 命令。它记录的是实际 JSON 内容，不代表验证已完成。

## 来源与工作树证据

- 工作树：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration`
- 模式：`shadow`
- manifest：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919\manifest.json`
- routing diagnostics：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919\routing-diagnostics.json`
- 输出目录绝对路径：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919`
- 输入 PDF：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`（路径来自 Task 1 brief；manifest 未单独保存路径）
- 输入 PDF SHA256：`376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`
- manifest 中的 HEAD/commit：`e188045b5844a9e7ec6b71287d669ff0e763a9e8`
- 起始 patch SHA256（既有审计记录）：`46F3342B930F5A45062533463B1980ECDD0C475F86690927540AB44B80EA1F8A`

### HEAD/status 说明

本次按要求未执行 git，因此没有独立采集当前 HEAD/status。上面的 `e188045...` 是 manifest 的 `commit` 字段；既有审计文件记录的起始 HEAD 是 `4f865fcf9552356e815964730924c81d5420adfb`。

既有审计文件 `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\status.txt` 记录的起始状态为分支 `codex/rust-full-migration`，并含有未提交修改和未跟踪文件；该文件不是本次重新采集的当前状态。审计目录位于工作树外的同名项目输出目录，未用历史状态替代当前状态结论。

## 页面基线

- `page_results` 实际数量：**17**
- 页索引（0-based）：`0, 75, 185, 187, 188, 191, 336, 408, 417, 423, 427, 432, 444, 984, 1005, 1013, 1018`
- dpi：`72`
- 每条 `page_results` 的状态均为 manifest 中记录的 `success`；未据此宣称测试或页面验收通过。

## Shadow 路由诊断计数

`routing-diagnostics.json` 实际记录 39 条诊断：

| 分类 | 实际数量 |
| --- | ---: |
| `rust_output_mismatch` | 30 |
| `rust_fallback` | 9 |
| `candidate_rejected` | 0（JSON 中未出现） |
| `accepted_numeric_difference` | 0（JSON 中未出现） |
| 合计 | 39 |

manifest 的 `routing_status_counts` 与上述 JSON 汇总一致：`rust_output_mismatch=30`、`rust_fallback=9`。

## 运行参数与版本采集情况

- model：`rule_first`
- environment：`windows`
- Python 版本：未采集
- PyMuPDF/fitz 版本：未采集
- Rust 版本或 Rust 扩展版本：未采集
- manifest 未保存上述版本字段；不以其它历史报告中的版本信息补写本次基线。

## 限定结论

现有 Shadow 输出和 manifest 已存在，可作为后续比较输入；但本次没有重跑测试或重新生成页面输出，因此版本、当前 git status 和页面级验证仍待补采。`candidate_rejected` 与 `accepted_numeric_difference` 仅表示在现有 routing JSON 中未出现，不表示经过额外验证。

## 最小验证补全（2026-09-19）

本次按用户要求先执行最小验证；以下结果为本次实际命令输出，不代表 17 页 Shadow 已重新生成。

### 当前工作树证据

- 当前分支：`codex/rust-full-migration`
- 当前 HEAD：`e188045b5844a9e7ec6b71287d669ff0e763a9e8`
- 当前 `git status --short --branch`：工作树保留既有改动；包括 17 个已修改文件和 4 个未跟踪文件（其中包含本 baseline 文档），未执行 reset/checkout/clean。
- 输入 PDF SHA256：`376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`
- Python：`3.12.10`
- PyMuPDF：`1.28.2`
- Cargo/Rust：`cargo 1.96.0`、`rustc 1.96.0`
- Rust 扩展 crate/package 版本：`hexai_pdf_parser 1.1.1`（来自当前 `Cargo.toml`）；扩展无运行时 `__version__` 字段。

### 命令结果

1. `cargo test`
   - 退出码：`0`
   - 摘要：Rust 单元测试 `43 passed; 0 failed`；Doc-tests `0 passed; 0 failed`。
2. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 下指定迁移专项 pytest：
   `pytest -q tests/test_rust_migration_routing.py tests/test_pdf_fast_native_span.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_english_wireless.py tests/test_pdf_fast_text_alignment.py`
   - 退出码：`0`
   - 摘要：`57 passed in 1.30s`。

### 尚未执行

- `git diff --check` 尚未执行。
- brief 要求的 17 页 Shadow 尚未重跑；现有 `snapshot-parity-baseline-20260919` 目录未覆盖。

## Task 1 收尾补充证据（2026-09-19）

以下为本次实际已获得的补充证据；与前文同名项目相比，本节记录的结果优先。基线状态更新为：**已完成基线采集，但存在 `rust_output_mismatch`/`rust_fallback`，不能宣称 parity 通过**。`mismatch`/`fallback` 保留为后续任务输入。

### 验证命令

- `cargo test`：退出码 `0`；`43 passed/0 failed`；doc-tests `0 passed/0 failed`。
- 指定迁移专项 pytest（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，5 个测试文件：`tests/test_rust_migration_routing.py`、`tests/test_pdf_fast_native_span.py`、`tests/test_pdf_fast_wireless_structure.py`、`tests/test_pdf_fast_english_wireless.py`、`tests/test_pdf_fast_text_alignment.py`）：退出码 `0`；`57 passed in 1.62s`。
- `git diff --check`：已执行，退出码 `0`，无输出。

### Shadow 运行证据

- 按 brief 原始 Shadow 命令首次退出码为 `1`，原因是环境路径问题：`ImportError: cannot import name 'rust_adapter' from 'hexai_pdf_parser' (D:\codes\PDFLayoutParser\src\hexai_pdf_parser\__init__.py)`。
- 修正命令前设置 `PYTHONPATH=D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src` 后，Shadow 退出码为 `0`。
- 本次使用 `PYTHONPATH` 修正环境，不覆盖旧输出；修正运行输出目录为：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\output\snapshot-parity-baseline-20260919-rerun`。
- 该目录已生成 manifest 和 routing-diagnostics；`page_results` 为 `17/17 success`。页索引：`0,75,185,187,188,191,336,408,417,423,427,432,444,984,1005,1013,1018`；dpi：`72`。
- routing diagnostics 共 `39` 条：`rust_output_mismatch=30`、`rust_fallback=9`、`candidate_rejected=0`、`accepted_numeric_difference=0`。

### 版本、输入与工作树

- Python `3.12.10`；PyMuPDF `1.28.2`；cargo/rustc `1.96.0`；Rust crate `hexai_pdf_parser 1.1.1`。
- 输入 PDF SHA256：`376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`。
- HEAD：`e188045b5844a9e7ec6b71287d669ff0e763a9e8`。
- 起始 patch SHA256：`46F3342B930F5A45062533463B1980ECDD0C475F86690927540AB44B80EA1F8A`。
- 当前工作树仍含既有 modified/untracked 文件；本次未清理、覆盖或回退这些改动。
