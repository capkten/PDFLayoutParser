# 兼容性修复报告

日期：2026-10-08  
分支：`codex/rust-public-api-compat`  
起始提交：`dafe1c8`
实现提交：`191f12a5a1c7e04e66f6a34f2526b5b933a4c1db`

## 改动

- 新增 `normalize_raw_page_for_public_api`：独立公开 API 可消费扫描页 native span、rawdict 和 words，同时维持 `page_type="scanned"`。`parse()` 和原规范化入口仍对扫描页早退。
- 扫描页 table region 仅对空文本 `line_projection` 启用基线兼容，保留范围及 cell occupancy 冲突检查；为重现第 705 页旧公开结果，允许该专用结果保留未占用的槽位。
- 第 437 页 full-page table region 禁止无线 fallback；窄化到明确区域时仍会运行无线恢复。此限制只应用于 `extract_table_in_region` 的整页 region，不改变自动探测/`parse()` 路径。
- Benchmark 增加公共数据规范化、诊断元数据剥离、路径 basename 归一化和文本/cell 文本哈希差异测试。table-structure skip 现在运行隔离 Python 子进程实际调用 Rust API；只有 Rust 调用输出带 `version_str` 的 `BadVersion` 才记作运行时 skip。超时、断言或其他失败抛出并中断 benchmark。未读取 Python 包版本来推断 Rust DLL 状态，也未修改生产 ORT 依赖或链接设置。

## TDD 与验证

### Benchmark

先添加测试并运行：

```powershell
$env:PYTHONPATH='src'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'E:\softanaconda\envs\langchain_chat\python.exe' -m pytest -q tests/test_rust_public_api_benchmark.py
```

RED：`2 passed, 1 failed`。失败为 `AttributeError: module 'rust_public_api_benchmark_test' has no attribute 'subprocess'`，因为当时没有隔离 runtime probe 实现。

实现后再运行同命令：GREEN：`4 passed in 0.30s`。覆盖 `_public_data` 去除嵌套 `file`/解码/hash 诊断字段、path 归一化与公开字段保留；文本和 cell 文本摘要差异；真实 Rust probe 的明确 ORT 版本失败、非版本错误、成功，以及 `run()` 只据 probe 结果写 skip。

### 扫描页与无线表格

Rust 集成回归先加入 `public_api.rs`。首次尝试运行：

```powershell
cargo test --manifest-path tools/pdfium_probe/Cargo.toml --lib public_api::tests::scanned_region_apis_match_the_saved_text_and_empty_table_baseline -- --exact
```

未执行断言：MSVC 14.40 链接 ORT 静态库失败，`LNK1120`，含 13 个未解析的 `__std_*` 符号。之后的 `cargo check --manifest-path tools/pdfium_probe/Cargo.toml --tests` 成功，确认 Rust 库和测试可编译；它不等价于测试运行。

为捕获兼容差异，我通过 Task 10 已构建扩展运行新增 Python-facing 回归（`-o pythonpath=` 用于选用该扩展）：

```powershell
$env:PYTHONPATH='C:\Users\Capkin\.codex\worktrees\rust-public-api\PDFLayoutParser\src'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'E:\softanaconda\envs\langchain_chat\python.exe' -m pytest -q -o pythonpath= tests/test_rust_public_api.py -k 'scanned_region_apis or wireless_full_page_region'
```

RED：`2 failed, 13 deselected in 0.78s`。扫描页 API 实际返回 `code=0, message='no text found in region', data=[]`，而基线要求 code 1 且 1 个 54 字符文本 block。full-page wireless 实际返回 `44x2`、88 cells，而期望 `None`。同一 Task 10 扩展对指定区域 `[0.14, 0.17, 0.86, 0.35]` 仍返回 `wireless_span_recovery`；这验证了保留指定区域提取的回归输入。该二进制来自未修改的 `rust-public-api` worktree，因此这是旧实现 RED 证据，不是本分支修复后的运行结果。

本分支新实现没有可运行的 `_pdf_fast` 二进制，且 Cargo 链接问题阻止重建；因此本轮没有新 Rust runtime GREEN，也没有新差异 benchmark 或页面结构输出。不得将当前状态描述为基线已全面一致。

### 其他检查

- `cargo check --manifest-path tools/pdfium_probe/Cargo.toml --tests`：成功，`Finished dev profile`。
- `tests/test_rust_public_api_benchmark.py`：4 passed。
- `git diff --check`：退出码 0。
- `cargo fmt --manifest-path tools/pdfium_probe/Cargo.toml -- --check`：失败，报告仓库大量既有 Rust 文件格式差异；未运行全量格式化，避免重写无关文件。
- Python-facing新行为测试未能在本分支新二进制上验证；Cargo 定向测试被 ORT 静态链接的 MSVC 错误挡住。

## 范围与剩余事项

- 未改 `parse()`、Python baseline、生产 ORT 版本/链接配置，也未修改其他 worktree。
- `cargo tree --manifest-path tools/pdfium_probe/Cargo.toml -e features -i ort` 确认当前 feature 树从 `api-17` 递进至 `api-27`，即 Rust API 下限为 27；benchmark 不再把 Python `onnxruntime` 包元数据当作 Rust 实际加载 DLL 的证据。隔离 probe 只证明该次 table-structure 调用是否遇到具体 `BadVersion`，不证明其他运行配置或机器上的兼容性。
- 第 705 页表格的兼容输出包含 4×2 网格中的 3 个 cell，且留有未占用槽位；这是保存的 Python 公开结果形状。本轮只在扫描页公开 region 的空文本 line-projection 特例中保留此行为，正常表格和 wireless occupancy 检查不放宽。
- 向量页和 wireless 文本的既有摘要/bbox 差异，以及修复后所有 baseline 差异，均因无法重建扩展而未重新测量。

## 文件

- `src/hexai_pdf_parser/debug/rust_public_api_benchmark.py`
- `tests/test_rust_public_api_benchmark.py`
- `tests/test_rust_public_api.py`
- `tools/pdfium_probe/src/normalizer.rs`
- `tools/pdfium_probe/src/public_api.rs`
- `tools/pdfium_probe/src/table_engine/mod.rs`
- `tools/pdfium_probe/changes.md`
