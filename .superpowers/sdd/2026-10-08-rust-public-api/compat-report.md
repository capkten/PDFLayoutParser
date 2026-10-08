# 兼容性修复报告

日期：2026-10-08
分支：`codex/rust-public-api-compat`
起始提交：`dafe1c8`
实现提交：`191f12a5a1c7e04e66f6a34f2526b5b933a4c1db`、`4ff9992`
复测补丁：当前 worktree 包含未提交的 Type3 字形映射和无线表格输出修正。

## 改动

- 新增 `normalize_raw_page_for_public_api`：独立公开 API 可消费扫描页 native span、rawdict 和 words，同时维持 `page_type="scanned"`。`parse()` 和原规范化入口仍对扫描页早退。
- 针对缺少 `/ToUnicode` 且使用数字 glyph names 的 Type3 字体，新增 Rust 字体编码映射；第 705 页独立文本 API 已恢复为基线的 54 字符、13 行，不调用 Python 提取回退。
- 扫描页 table region 仅对空文本 `line_projection` 启用基线兼容，保留范围及 cell occupancy 冲突检查；为重现第 705 页旧公开结果，允许该专用结果保留未占用的槽位。
- 第 705 页表级 bbox、4×2 网格、`line_projection` 来源及 3 个空文本 cell 已对齐基线；cell 边界仍有约 0.1 pt 的解析引擎差异，用户接受该精度差异，未放宽全局断言。
- 第 437 页 full-page table region 禁止无线 fallback；窄化到明确区域时仍会运行无线恢复。此限制只应用于 `extract_table_in_region` 的整页 region，不改变自动探测/`parse()` 路径。
- `wireless_span_recovery` 不再从页面绘图对象补写 `h_lines/v_lines`。feature-dev 的指定区域结果两字段均为 `None`；Rust 先前把表格区域内的绘图线错误带入响应。
- Benchmark 增加公共数据规范化、诊断元数据剥离、路径 basename 归一化和文本/cell 文本哈希差异测试。table-structure skip 现在运行隔离 Python 子进程实际调用 Rust API；只有 Rust 调用输出带 `version_str` 的 `BadVersion` 才记作运行时 skip。超时、断言或其他失败抛出并中断 benchmark。未读取 Python 包版本来推断 Rust DLL 状态，也未修改生产 ORT 依赖或链接设置。

## 换机前最新状态

- 最近一次临时动态 ORT 配置下的 Rust 全量测试记录为 `194 passed, 6 failed`：4 项因缺少 `fix/zh_all_table_pages.pdf`，1 项合成 normalizer 夹具未提供字符数据，1 项为上述约 0.1 pt 的 cell 几何差异。该结果不是全绿；静态 ORT 默认链接的 MSVC `LNK1120` 问题仍未解决。
- 本轮 `cargo check --offline --manifest-path tools/pdfium_probe/Cargo.toml --lib` 和随后 `cargo check --offline --locked --manifest-path tools/pdfium_probe/Cargo.toml --lib` 均成功。
- 本轮 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_rust_public_api.py` 未进入测试收集：当前工作树没有包内 `_pdf_fast.pyd`，只有 `target/debug/_pdf_fast.dll`。这是本机扩展未安装状态，不据此判断 API 功能失败。
- Type3 修复后的 benchmark 尚未重跑；先前的速度和差异摘要不能代表当前代码。
- `git diff --check` 成功。单文件 `rustfmt --check` 报出大量既有格式差异，未执行全量重排。

## 历史 TDD 与验证（Type3 字形映射修复前）

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

默认静态链接配置仍在 MSVC 14.40 链接 ORT 时失败：`LNK1120`，含 13 个未解析的 `__std_*` 符号。为取得本地行为证据，复测期间临时设置 `default-features = false`，仅启用 `std`、`load-dynamic`、`api-20`，并通过 `ORT_DYLIB_PATH` 加载本机 ONNX Runtime 1.20.1。明确关闭默认 features，避免仍启用 `api-27`。运行结束后恢复 `Cargo.toml`、Cargo lockfile 和进程环境变量；此动态构建只用于复测，不代表默认生产配置已能链接。

使用当前修复分支动态构建根目录 PyO3 扩展，并通过 Python 包装层实际调用 Rust 入口，结果：

```powershell
$env:PYTHONPATH='C:\Users\Capkin\.codex\worktrees\rust-public-api\PDFLayoutParser\src'; $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'E:\softanaconda\envs\langchain_chat\python.exe' -m pytest -q -o pythonpath= tests/test_rust_public_api.py -k 'scanned_region_apis or wireless_full_page_region'
```

`tests/test_rust_public_api.py`：`14 passed, 1 failed`；唯一失败是扫描页文本与 Python 基线不一致。`public_api::tests`：`29 passed, 1 failed`，同样只失败于扫描页基线断言。无线 full-page 拒绝误报、指定区域恢复和 `h_lines/v_lines == None` 均通过。

扫描页 `page_705_scanned.pdf` 使用 Type3 字体，字体字典没有 `/ToUnicode`；其 `/Encoding/Differences` 为 `[0 /i255 2 /3 ... /54]`，包含非标准数字 glyph names。PyMuPDF `get_text("text")` 也返回控制码；`get_text("words")` 才把该字形序列变为基线中的 54 字符标点串，并分成 13 行。这些标点没有 PDF 声明的 Unicode 字符映射。PDFium diagnostics 为 `invalid_unicode`，含 65 个控制字符；公开 API 返回一个 block/一行，字符框约 280 pt 高且有负 x、越界坐标，和 Python 的 13 行结果不同。临时诊断确认 `tight_bounds()` 与 loose bbox 一样；PDFium TextPage 有 60 个重复重叠段，Type3 首个文本对象也没有可用 glyph path。过滤控制字符无法恢复字形语义、词边界或行分组。检查 Rust `pdf-extract` 的 Type3 路径也未找到通用解法：它按 Adobe glyph names 映射，无法给本文件的数字 glyph names 定义 Unicode。本轮没有加入单文件映射、Python 回退、新解析依赖或放宽基线断言。

扫描页 table region 的结构为 4×2、3 个空文本 cell、`line_projection`，但表级 bbox 仍不同：Rust `x0=204.9`，Python 基线 `x0=203.2`，相差 1.7 pt。严格基线测试保持原样，没有新增容差；由于文本断言先失败，最终当前测试运行没有到达 table bbox/cell 几何断言。

### 速度与结果差异

以保存的 Python 基线中位数对比 Rust 动态构建的每项 5 次测量，共 4 个 fixture × 8 个 API = 32 个组合；全部 32 项完成，没有 ORT skip。下表为四个 fixture 的 speedup 中位数（Python/Rust，>1 表示 Rust 更快）：

| API | 中位 speedup | 规范化结果一致 |
| --- | ---: | ---: |
| `text_region` | 0.023x | 1/4 |
| `table_region` | 1.406x | 2/4 |
| `table_structure` | 0.519x | 1/4 |
| `images` | 1.229x | 3/4 |
| `image_region` | 1.181x | 3/4 |
| `render_pages` | 0.052x | 4/4 |
| `render_region` | 0.050x | 4/4 |
| `classify_page` | 0.022x | 4/4 |

本轮基准重新执行 4 个 fixture × 8 个 API，每项 Rust 调用 5 次，32 项均完成且无 ORT skip。总体 32 个组合中 Rust 有 25 个更慢；render-pages 和 render-region 中位数约为 Python 的 19–20 倍。主要耗时可能包括每次 Rust API 调用重新绑定 PDFium、打开 PDF 和编码 PNG；这是根据调用路径推断，未用 profiler 单独拆分。`difference_summary` 忽略了 baseline 的 `file`、解码状态和哈希诊断字段，因此“一致”表示规范化公开摘要一致，不代表生成文件字节相同。

### 其他检查

- `cargo check --manifest-path tools/pdfium_probe/Cargo.toml --tests`：成功，`Finished dev profile`。
- `tests/test_rust_public_api_benchmark.py`：4 passed。
- 当前严格基线回归在动态 ORT 配置下：`cargo test --manifest-path tools/pdfium_probe/Cargo.toml --lib 'public_api::tests::'` 为 29 passed、1 failed；`tests/test_rust_public_api.py` 为 14 passed、1 failed。两处唯一失败都是扫描页 Type3 文本映射；Rust 返回控制码串而 Python 基线为标点串。Wireless full-page 拒绝误报、指定区域恢复和 `h_lines/v_lines == None` 通过。
- `git diff --check dafe1c8`：报告修正后退出码 0。
- `cargo fmt --manifest-path tools/pdfium_probe/Cargo.toml -- --check`：失败，报告仓库大量既有 Rust 文件格式差异；未运行全量格式化，避免重写无关文件。
- Python-facing 路径测试确认公开路径 API 调用 `_pdf_fast`，并在禁止 `fitz.open` 时运行；当前动态构建下仍有扫描页差异，不能称为 Python/Rust 全面等价。

## 范围与剩余事项

- 未改 `parse()`、Python baseline、生产 ORT 版本/链接配置，也未修改其他 worktree。动态构建所用 `_pdf_fast.pyd` 为临时文件，测试后已移除。
- `cargo tree --manifest-path tools/pdfium_probe/Cargo.toml -e features -i ort` 确认当前 feature 树从 `api-17` 递进至 `api-27`，即 Rust API 下限为 27；benchmark 不再把 Python `onnxruntime` 包元数据当作 Rust 实际加载 DLL 的证据。隔离 probe 只证明该次 table-structure 调用是否遇到具体 `BadVersion`，不证明其他运行配置或机器上的兼容性。
- 第 705 页表格的兼容输出包含 4×2 网格中的 3 个 cell，且留有未占用槽位；这是保存的 Python 公开结果形状。本轮只在扫描页公开 region 的空文本 line-projection 特例中保留此行为，正常表格和 wireless occupancy 检查不放宽。
- 复测确认结果差异：`text_region` 仅 1/4 fixture 一致；`table_region` 2/4；`table_structure` 1/4；`images` 与 `image_region` 各 3/4；`render_pages`、`render_region`、`classify_page` 均 4/4。
- 当前分支未满足严格基线验收：扫描页 Python-facing 与 Rust 集成回归各失败 1 项，多项 benchmark 结果仍与基线不同，默认静态 ORT 链接仍失败。本轮按兼容修复 brief 保持分支未合并；未改动 `dev-rust`、`feature-dev` 或其他 worktree。

## 文件

- `src/hexai_pdf_parser/debug/rust_public_api_benchmark.py`
- `tests/test_rust_public_api_benchmark.py`
- `tests/test_rust_public_api.py`
- `tools/pdfium_probe/src/normalizer.rs`
- `tools/pdfium_probe/src/public_api.rs`
- `tools/pdfium_probe/src/table_engine/mod.rs`
- `tools/pdfium_probe/changes.md`
