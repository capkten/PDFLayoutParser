# Task 6 & 验收评审整改变更记录 (changes.md)

## 2026-10-08：Task 10 兼容修复复测

### 换机前最新状态

- 第 705 页的缺失 `/ToUnicode` Type3 字体由 Rust 读取 `/Encoding/Differences` 数字 glyph names 并建立字形映射；独立文本 API 现恢复为 54 字符、13 行，不回退到 Python。
- 第 705 页表级 bbox、4×2 网格、`line_projection` 来源和 3 个空文本 cell 已与基线对齐。cell 边界仍约有 0.1 pt 差异，按用户确认接受不同解析引擎的微小几何差异，没有放宽全局断言。
- 最近一次临时动态 ORT 配置下的 Rust 全量测试记录为 `194 passed, 6 failed`：4 项缺少 `fix/zh_all_table_pages.pdf`，1 项合成 normalizer 测试夹具缺少字符数据，1 项为已接受的扫描页 cell 几何差异。默认静态 ORT 链接的 MSVC `LNK1120` 仍未解决，因此不能称全量测试通过。
- 本轮 `cargo check --offline --manifest-path tools/pdfium_probe/Cargo.toml --lib` 与 `cargo check --offline --locked --manifest-path tools/pdfium_probe/Cargo.toml --lib` 均成功。
- 本轮 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_rust_public_api.py` 因工作树没有包内 `_pdf_fast.pyd` 而未进入收集；只有 `target/debug/_pdf_fast.dll`。这是当前本机扩展未安装状态，不能据此判定功能失败。
- Type3 修复后的 benchmark 尚未重跑，先前的性能和结果摘要不代表当前代码。`git diff --check` 成功；Rust 格式检查显示多个文件存在格式差异，未执行全量重排。

### 此前兼容修复记录（Type3 映射修复前）

- 复测的路径调用链为 `PDFParser -> pdfium_api._run -> _pdf_fast.run_public_pdf_api -> public_api.rs -> PDFium`；路径 API 不调用 PyMuPDF 提取、渲染或回退。`parse()` 主流水线仍不在迁移范围。
- wireless 指定区域结果之前由 `ordinary_table()` 从页面 drawing 快照补写 `h_lines/v_lines`，与 feature-dev 的 wireless 表格结果不符。现在 `source == "wireless_span_recovery"` 时保留 `None`。
- `page_705_scanned.pdf` 使用无 `/ToUnicode` 的 Type3 字体，`/Encoding/Differences` 是 `[0 /i255 2 /3 ... /54]`。PyMuPDF `get_text("text")` 也返回控制码；其 `get_text("words")` 基线为 54 字符标点串和 13 行。PDFium diagnostics 标记 `invalid_unicode`，包含 65 个控制字符；当前 Rust 输出仍是控制码串，且 block bbox 部分越界。临时诊断确认 `tight_bounds()` 与 loose bbox 相同，TextPage 产生 60 个重复且重叠的文本段，首个 Type3 文本对象没有可用 glyph path。普通 Rust glyph-name 映射也不能解释数字 glyph names。过滤控制字符仍无法恢复基线行/词边界和 bbox，因此保留该差异，不通过 Python 回退、单文件映射或放宽断言。
- 扫描页表级 table bbox 仍有精确差异：Rust `x0=204.9`，Python 基线 `x0=203.2`，相差 1.7 pt；未添加数值容差。

### 此前验证结果（Type3 映射修复前）

- 默认 ORT 静态链接仍在 MSVC 14.40 下 `LNK1120`，包含 13 个未解析 `__std_*` 符号。本轮 Rust 定向测试临时设置 `default-features = false`，仅启用 `std + load-dynamic + api-20`，并通过 `ORT_DYLIB_PATH` 加载本机 ONNX Runtime 1.20.1；测试后 Cargo 配置、lockfile 和进程环境变量已恢复。
- 本轮新跑 `cargo test --manifest-path tools/pdfium_probe/Cargo.toml --lib 'public_api::tests::'`：29 passed、1 failed；唯一失败是扫描页文本与 Python 基线不同。临时诊断测试已移除，没有留在生产代码中。
- `tests/test_rust_public_api.py`：14 passed、1 failed；唯一失败是相同的扫描页文本差异。无线针对性过滤运行 64 tests，全部通过。
- Python/Rust 差异 benchmark 本轮重新执行：4 个 fixture × 8 个 API，Rust 每项 5 次，共 32 个组合全部测量且无 ORT skip。Rust 有 25/32 项更慢，speedup 范围 0.008x–2.383x；无线页 `table_region` 规范化字段现在一致。按 API 汇总的中位 speedup 和摘要一致数见 `.superpowers/sdd/2026-10-08-rust-public-api/compat-report.md`。渲染和分类摘要在 4/4 fixture 一致；文字与结构化表格仍有差异。
- `git diff --check dafe1c8`：报告更新后重新检查。

当前还不能合并：扫描页回归仍失败，多种 API 输出与基线不同，默认 ORT 静态链接也未解决。结果和速度均不描述为全面等价或整体提速。

## 2026-10-08：Task 10 Rust 公开 PDF API 验收

### 范围、根因与调用链

Task 8 将七个独立路径接口与路径分类切换到 `PDFParser -> pdfium_api._run -> _pdf_fast.run_public_pdf_api -> pdfium_probe 共享 Rust 库/PDFium`。本轮仅补验收脚本和回归证明；文件路径入口没有 PyMuPDF 读取、渲染或失败后备。`fitz.Page` / `fitz.Document` 分类仅通过 `tobytes()` 将原 PDF 字节交给 Rust 分类；`parse()` 主流水线不属于本迁移范围。

### 新增覆盖与差异结果

- `tests/test_rust_public_api.py` 将 `fitz.open`、`Page.get_text/get_images/get_image_info/get_pixmap/get_drawings` 与 `Document.extract_image` 替换为立即失败桩，并调用每个公开路径 API；另外对 fitz 对象分类记录 `tobytes()`，确认调用来源只包含这项序列化操作。
- `src/hexai_pdf_parser/debug/rust_public_api_benchmark.py` 读取且不改写保存的 Python 基线，对四个 fixture 的八个 API 报告基线中位数、Rust 预热后五次测量的中位数、speedup 和规范化公开结果摘要。基线中的 `file`、解码状态和哈希是捕获脚本添加的诊断元数据，不是 Image/RenderInfo 公共字段；摘要忽略这些诊断键，并对数值统一保留六位小数。完整结果写到 `output/rust-public-api-benchmark.json`。
- 实际结果仍有未解决差异，故不宣称两端等价：扫描页 `page_705_scanned.pdf` 的 `text_region` 与 `table_region` 在 Python 基线中分别有 1 项内容和 1 张表，Rust 当前均返回空；`page_437_wireless.pdf` 的全页 `table_region` 基线为空，Rust 返回 `wireless_span_recovery` 的 44 行、2 列、88 cells。后者需要确认是否误把相邻表合并；`table_structure` 因 ORT 不兼容未能对比。
- 文本 bbox 有可见数值偏差：`page_000_vector.pdf` 首个文本框 y0/y1 分别约偏 1.34/1.13 pt，wireless 页首个框约偏 0.068 pt。Task 10 未擅自设容差；这些偏差以及文本/单元格内容摘要差异都保留在 benchmark 的 `difference_summary` 中。
- 图片导出 metadata、页码、资源索引、bbox、尺寸、扩展名和路径的摘要在三个有图像 fixture 上未报告字段差异。基线附加的文件哈希/解码字段已从比较中剔除；渲染 PNG 的公开像素尺寸一致，但 Rust 与基线图片摘要的其余内容仍应以 benchmark JSON 差异摘要为准。

### 命令与实测结果

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 E:\softanaconda\envs\langchain_chat\python.exe -m pytest -q tests/test_rust_public_api.py`：**13 passed**。
- `PYTHONPATH=src E:\softanaconda\envs\langchain_chat\python.exe src/hexai_pdf_parser/debug/rust_public_api_benchmark.py --baseline tests/fixtures/rust_public_api/python_baseline.json --runs 5 --output output/rust-public-api-benchmark.json`：生成 32 个 fixture/API 行，其中 28 个完成两侧中位数比较，4 个 `table_structure` 明确标记 skipped；Rust 端每个已测 API/fixture 先预热一次，再采集 5 次。
- `cargo test --manifest-path tools/pdfium_probe/Cargo.toml` 和 `cargo test --manifest-path Cargo.toml --lib`：均因 MSVC 14.40 链接失败退出 1，报 `LNK1120` 与 13 个 ONNX Runtime 静态链接的 `__std_*` 未解析符号。未改生产 ORT 链接模式。
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 E:\softanaconda\envs\langchain_chat\python.exe -m pytest -q tests/test_pdf_parser.py tests/test_classify_pdf_page.py tests/test_page_classifier.py tests/test_extract_table_region.py tests/test_image_extractor.py tests/test_rust_public_api.py`：**82 passed、32 skipped、17 failed**。首次表格结构调用加载失败：`BadVersion { version_str: "1.17.1" }`，后续因 PDFium 互斥状态被 panic 污染而出现连锁失败。Python 包元数据显示 ORT 1.20.1，但 Rust 运行时实际加载 DLL 报告 1.17.1。
- 获取匹配 ORT 动态库失败：NuGet 下载因 DNS 报“未知主机”；`pip download --no-deps --only-binary=:all: --timeout 60 --retries 1 ... onnxruntime==1.28.0` 解析到 cp311 win_amd64 wheel 元数据，但 13.8 MB wheel 下载超过 60 秒无进度后中断，临时目录无 wheel。未改 Python 环境或提交 DLL。
- 无线表格页面独立输出目录：`C:\Users\Capkin\.codex\worktrees\rust-public-api\PDFLayoutParser\output\rust-public-api-wireless-v29e_slk`。`render_pages(page_indices=[0])` 成功，生成 `renders/page-000.png`（595×843），人工查看截图可见页面上三张表格边界和间距清楚，相邻表未在图像渲染上误并。`extract_table_structure(page_indices=[0])` 在 ORT DLL 版本错误处 panic，故本轮没有结构化 Cell/跨度/bbox/空槽位检查结果。

Task 10 当前不满足合并条件：表格结构结果缺失、Rust 与 Python 回归/Rust 链接测试失败，且已确认的扫描页输出差异和无线表格区域误合并疑点待针对性修复。未切换或合并 `dev-rust`。

## 1. 任务背景与核心改动

本任务完成了 **Task 6: 样本矩阵、确定性输出和中文验收报告**，并根据行为验收评审反馈落实了 5 项核心治理：
1. 修复矩阵退出码门禁缺陷（将 `unsupported > 0` 纳入退出码为 1 的阻断条件，防止 CI 假绿）；
2. 重新归因空格差异，将 TextPage 分析器在对象边界产生的合成分隔空格与真正的字符映射缺失严格区分，解除对 6 个矢量样本的误杀；
3. 为断续线样本 `synth_segmented_lines` 补充表格区域，并真实激活 `test_p27_table`（无线表格）和 `credit_p1_detail`（有线表格）的双路表格恢复、单元格拓扑与 Markdown 比对；
4. 优化重叠文本的行内水平重叠判定（水平重叠超过 30% 分离为独立行），使 `synth_invisible_text` 恢复正确自然阅读顺序并 Passed；
5. 消除 EOF 多余空白行，确保 `git diff --check 4d01c48..HEAD` 退出码严格为 0；统一依赖锁定说明为 `chromium/8066`。

### 主要改动文件

1. **`tools/pdfium_probe/scripts/export_pymupdf_baseline.py`**:
   - 适配环境变量 `PDFIUM_OUTPUT_ROOT`，当环境变量存在时将合成基线和真实基线分别输出至 `${PDFIUM_OUTPUT_ROOT}/baseline` 与 `${PDFIUM_OUTPUT_ROOT}/real_baseline`。
   - 在导出的 PyMuPDF baseline JSON 顶层增加 `source_file_sha256` 存证字段，支持与实时源 PDF SHA 进行防篡改/防过期校验。
   - 严格遵循 Python 3.7 兼容性，类型注解均引用自 `typing`。
2. **`tools/pdfium_probe/scripts/run_behavioral_matrix.py`**:
   - 核心接口契约：`run_behavioral_matrix(*, fixture_manifest: Path, pdfium_roots: Sequence[Path], output_dir: Path) -> Dict[str, Any]`。
   - 门禁退出码：在 `summary["unsupported"] > 0` 时严格退出码为 1。
   - `get_repo_root()` 增加回退路径支持，确保未显式传环境变量时自动定位根仓库中的 `test.pdf`。
   - 规范化 Canonical JSON 序列化：递归键排序、UTF-8 紧凑编码、浮点数统一 round 到 4 位；文本与 Markdown 严格不 trim、不折叠内部空格。
   - 供应链信息采集：从 `manifest.json` 读取当前平台的 `release_tag`、`archive_sha256`、`library_relpath` 及预期 `library_sha256`，校验与 raw snapshot 中的动态库哈希一致性。
   - 表格 Overlay 导出接口：`render_table_overlays(pdf_path, page_index, pdfium_tables, pymupdf_tables, output_dir)`，复用 `hexai_pdf_parser.debug.table_visualizer.render_table_visualization` 生成两侧引擎的 200 DPI PNG 视图。
3. **`tools/pdfium_probe/src/main.rs`**:
   - `MappingDiagnostics` 增加 `synthetic_space_count` 字段，支持 serde 默认值反序列化向后兼容。
   - 提取文本时通过 `text.trim_end_matches(' ') == extracted_text` 统计合成分隔空格，不误置 `has_char_mismatch`。
   - 映射有效性使用 `visible_text_scalar_count == extracted_char_scalar_count + synthetic_space_count` 进行校验。
4. **`tools/pdfium_probe/scripts/pdfium_classification.py`**:
   - 同样支持 `char_text == text.rstrip(" ")` 放行合成分隔空格，只有实质字符缺失或乱码才降级为 `scanned`。
5. **`tools/pdfium_probe/scripts/pdfium_normalizer.py`**:
   - `_ensure_mapping_diagnostics_if_missing` 增加合成分隔空格统计支持。
   - `_VisualLine.matches_span` 增加水平重叠度判定：同一行内的 Span 若水平重叠超过 30%，判定为独立行，防止图层重叠文本被误并。
6. **`tools/pdfium_probe/test_data/behavioral/fixtures.json`**:
   - `synth_segmented_lines` 补充表格区域：`[{"kind": "wired", "x0": 50.0, "y0": 80.0, "x1": 450.0, "y1": 180.0}]`。
7. **`tools/pdfium_probe/SPRINT2_BEHAVIORAL_REPORT.md`**:
   - 完整的中文行为影子矩阵与确定性验收审计报告。

---

## 2. 根因、判定条件与调用约束

### 2.1 空格差异与字符映射缺失严格区分
- **现象**: 此前 6 个样本被分类门禁判定为 `invalid_unicode_mapping` 并降级为 `scanned`，与 PyMuPDF 的 `vector` 产生分类分歧。
- **根因**: PDFium `text_obj.text()` 在对象边界自动合成了末尾空格，而字符列表 `chars` 仅包含字形字符。两端在非空白 CJK 字符的 Unicode 标量序列上 100% 吻合，并无字形映射缺失。
- **治理**: 探针与分类器引入 `synthetic_space_count` 并放行合成分隔空格，恢复其真实的 `vector` 分类。

### 2.2 表格结构恢复与不回读 words 约束
- `test_p27_table`: 无线表格恢复实际执行，PyMuPDF 恢复 9 行 2 列，PDFium 恢复 27 行 2 列。比对器如实检出结构差异，并在 Overlay PNG 中标注单元格选框。
- `credit_p1_detail`: 有线表格恢复实际执行，双端均恢复 11 行 11 列（121 个单元格），**`table_structure_equal: true` 拓扑完全一致**！
- 结构恢复阶段严格仅消费原子 TextObject、native span、列带、物理单元格和逻辑 Cell，绝不回读 `page.get_text("words")`。

---

## 3. 测试验证结果

1. **Rust 原生探针测试**:
   - 执行命令: `cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
   - 结果: **11 passed; 0 failed; finished in 0.00s**。
2. **Probe 自动化测试套件**:
   - 执行命令: `pytest -q tools/pdfium_probe/tests/`
   - 结果: **78 passed in 1.33s**。
3. **主 Rust 库与 Python 回归**:
   - `cargo test --lib`: **103 passed; 0 failed**。
   - 核心回归测试: **105 passed in 37s**。
4. **完整行为矩阵运行**:
   - Fixtures: 11
   - Runs: 3
   - **Deterministic: True** (`all_equal: true`，3 次运行全样本 Canonical SHA-256 100% 一致)
   - Passed: 7
   - Failed: 1 (`test_p27_table` 无线表格行聚类算法差异)
   - Unsupported: 3 (`credit_p0_header` 与 `credit_p1_detail` 含未建模印章，`synth_segmented_lines` 断续线无闭合网格)
   - Blocked Input: 0
   - Unclassified: 0
   - 退出码: 1（门禁有效阻断）
5. **代码规范与格式检查**:
   - `git diff --check 4d01c48..HEAD`: 退出码 0，无任何空白或冲突警告。
   - 生产代码（`src/`、`rust/`、根 `Cargo.toml`）零修改。
   - 既有未暂存 PDF (`synth_crop_offset.pdf`, `synth_mixed_fonts.pdf`) 完好保留。

---

## 4. 端到端表格解析与模型检测接入（End-to-End Table Extraction & ML Detector Integration）

### 4.1 背景与需求

用户指出流水线不应依赖人工硬编码表格配置，而是需要完整的**端到端 PDF 解析（End-to-End PDF Parsing）**，包含完整的**模型调用（Model Calling）**。架构需与生产级流水线保持一致：
1. 执行规则预筛（`_detect_rule_candidates`）；
2. 检测到候选表格信号时调用 ML 表格检测模型（`MLTableDetector` / YOLO ONNX）定位候选框；
3. 执行表格结构恢复（有线物理网格 / 无线 span 恢复）；
4. 扣除检出表格后组装正文与表格穿插的自然阅读顺序流。

### 4.2 根因定位与治理措施

- **根因 1（矢量图元结构不兼容导致有线提取器失效）**:
  - `WiredTableExtractor` 消费 `get_drawings()` 时，期望元素为 `('l', p1, p2)` 且 `p1.x, p1.y` 拥有点属性；同时若 `color is None and fill is None` 会直接判定为不可见图元。此前 `PdfiumPageAdapter` 仅返回原始 JSON 字典，导致提取器无法获取有效线条。
  - **治理**: 在 `PdfiumPageAdapter.get_drawings()` 中实现与 PyMuPDF 完全同构的转换逻辑，生成包含 `type`、`rect` (`fitz.Rect`)、默认前景色 `color=(0,0,0)`、以及具备 `.x`, `.y` 属性的 `fitz.Point` 点元组，使有线提取器自发识别所有网格线。
- **根因 2（缺少底图光栅化接口导致 ML 检测模型抛异常）**:
  - `MLTableDetector` 依赖 `page.get_pixmap()` 进行页面渲染送入 YOLO 模型；此前适配器缺少此方法，导致模型调用报错并静默降级为 0 表格。
  - **治理**: 在 `PdfiumPageAdapter` 中实现 `get_pixmap(matrix=None, dpi=72, alpha=False)`，调用 `pypdfium2` 原生引擎光栅化为 RGB 缓冲区，并封装 `PdfiumPixmap` 包装类（提供 `width`, `height`, `samples`, `n`, `stride`, `tobytes()`）。
- **根因 3（硬编码表格配置导致裁切与表格丢失）**:
  - 用户此前质疑的 `test_p27_table` 异常选框，根因是旧配置硬编码了 `x1: 575.0`，而实际横版表格全宽 `841.9`，导致右侧 4 列被物理截断并产生散落绿色碎片；`credit_p1_detail` 旧配置仅人工指定了顶部 1 个表格，导致整页其余 5 个明细表格全部丢失。
  - **治理**: 移除人工硬编码依赖，全面启用端到端全自动检测提取模式。

### 4.3 主要改动文件

1. **`tools/pdfium_probe/scripts/pdfium_page_adapter.py`**:
   - 新增 `PdfiumPixmap` 类，适配下游图像消费协议。
   - 新增 `get_pixmap()` 方法，支持 `pypdfium2` 原生渲染及 PyMuPDF 降级。
   - 重构 `get_drawings()`，完全对齐 PyMuPDF 绘图指令格式与点线拓扑。
   - 构造函数增加 `pdf_path` 参数与源文件定位推断。
2. **`tools/pdfium_probe/scripts/pdfium_shadow_runner.py`**:
   - 新增 `auto_detect_tables` 与 `pdf_path` 参数。
   - 在自动模式下调用 `TableExtractor.extract(pdfium_adapter)`，全链路打通规则预筛 -> YOLO 模型检测 -> 结构恢复。
3. **`tools/pdfium_probe/scripts/visualize_pipeline_steps.py`**:
   - Stage 3 升级为端到端全自动表格检测与结构恢复可视化，动态获取实测表格区域与单元格。
   - Stage 4 动态扣除实测检出表格，组装真实穿插阅读顺序。
4. **`tools/pdfium_probe/tests/test_pdfium_page_adapter.py`**:
   - 增补 `test_pdfium_pixmap_wrapper`、`test_pdfium_page_adapter_get_pixmap`、`test_pdfium_page_adapter_get_drawings_compatibility`、`test_pdfium_page_adapter_end_to_end_wired_extraction` 等 10 项测试。

### 4.4 验收与对比结果

- **`test_p27_table`**:
  - 端到端自动检出全宽 9×9 表格（覆盖 `66.4..771.2pt`，共 46 个单元格），两端检测框与单元格 100% 吻合。
  - 彻底消除了右侧 4 列截断与散落绿色文字碎片；Stage 4 正常输出为单一穿插表格节点。
- **`credit_p1_detail`**:
  - 端到端自动检出并恢复全页全部 6 个明细表格（11×11, 6×4, 4×5, 4×4, 3×4, 2×7）。
  - 两端表格数量、维度及单元格结构完全一致；Stage 4 呈现完美的正文与 6 个表格穿插阅读顺序（17 个流节点）。
- **自动化测试**:
  - Probe Python: **85 passed**
  - Probe Rust: **11 passed**
  - Main Rust: **103 passed**
  - Core Python 回归: **77 passed, 1 skipped**
  - 生产代码（`src/`、`rust/`、根 `Cargo.toml`）严格保持零修改。

---

## 5. 纯 Rust 页面渲染与剔除 pypdfium2 依赖（Pure Rust Page Rendering & pypdfium2 Elimination）

### 5.1 背景与根因定位

在前期实现端到端表格检测与 MLTableDetector 接入时，为提供图像底图光栅化功能，适配层曾在 Python 侧引入了第三方库 `pypdfium2`。然而，该方案带来了显著的架构隐患与依赖割裂：
1. **双重底层绑定与环境脆弱性**：Rust 侧已通过 `pdfium-render` 静态/动态绑定了经过严格哈希锁定的官方 `chromium/8066` 原生库，而 Python 侧再引入 `pypdfium2`（基于 ctypes/CFFI 重新绑定或分发其内置动态库），导致双重运行时绑定，易发生 DLL 符号冲突、版本不一致或多平台分发缺陷。
2. **零外部 Python PDF 库规范约束**：根据项目架构演进规范，Python 侧探针和适配器必须保持轻量与独立，不依赖任何第三方 Python PDF 抽取库（如 `pypdfium2`），所有的页面底层解析、图元抽取以及位图光栅化职责必须收敛于纯 Rust 引擎实现。

### 5.2 Rust 原生光栅化实现细节

在 `tools/pdfium_probe/src/main.rs` 中实现了纯 Rust 的页面位图光栅化能力：
1. **CLI 命令与位置参数契约**：
   - 增加渲染命令：`pdfium_probe render <pdf_path> <page_index> <dpi> <out_png>`；
   - 参数校验：校验位置参数数量，对 `<page_index>` 使用 `u16::try_from(page_idx)` 防止溢出回绕，并打印输出路径存证。
2. **光栅化与零依赖编码管道 (`render_page_to_png`)**：
   - 几何尺度换算：按照 `scale = (dpi / 72.0).max(0.1)` 换算目标像素尺寸，并确保 `target_w = target_w.max(1); target_h = target_h.max(1);` 防御 0 或负尺寸异常；
   - 配置与渲染：构建 `PdfRenderConfig::new().set_target_width(target_w).set_target_height(target_h)`，调用 `page.render_with_config(&render_config)` 生成内存位图；
   - 零依赖无损 PNG 编码 (`save_rgba_as_png`)：将 RGBA 像素流通过标准 RFC 1950 (zlib wrapper) 与 RFC 1951 (Deflate uncompressed blocks `btype=00`) 规范装配，结合 Adler32 与 CRC32 校验码，手工流式组装 `IHDR`、`IDAT`、`IEND` Chunk 写入 PNG 文件，彻底避免引入外部 `image::codecs::png::PngEncoder` 或庞大图形编解码 crate；
   - 渲染容错与告警：在 `process_pdf_file` 同步渲染 72/180 DPI 底图时，增加失败告警日志 `eprintln!("[pdfium_probe] Warning: failed to render page: {}", e)` 代替静默丢弃；
   - 单元测试：`test_render_page_to_png_contract`，验证渲染宽高几何比例与 PNG 文件头完整性。

### 5.3 Python 适配器改造与零外部库调用约束

在 `tools/pdfium_probe/scripts/pdfium_page_adapter.py` 中彻底剔除了 `pypdfium2`：
1. **全面移除第三方库引用**：删除所有 `import pypdfium2` 代码与相关分支；
2. **纯 Rust 子进程光栅化对接**：
   - `get_pixmap(matrix=None, dpi=72, alpha=False)`：定位 `pdfium_probe` 编译二进制（支持 `CARGO_TARGET_DIR` 环境变量、`probe_root/target`、`repo_root/tools/pdfium_probe/target` 之 `release`/`debug` 及 `PATH` 系统路径）；
   - 优先复用 Rust 探针批量生成的预渲染底图（`${base_name}_page_${page_num}_dpi${dpi}.png`）；
   - 若预渲染底图不存在，动态调用子进程 `pdfium_probe render <pdf_path> <page_index> <dpi> <out_png>` 进行跨进程即时渲染；
   - 增加 30 秒安全超时限制（`timeout=30`），避免子进程死锁并具备超时优雅降级能力；
   - 使用标准库 `PIL.Image.open()` 读取临时 PNG，装配为下游兼容的 `PdfiumPixmap`（包含 `width`、`height`、`samples`、`n`、`stride` 与 `tobytes()`）；
   - 仅保留 PyMuPDF 作为基准对照降级备选，彻底消除了对 `pypdfium2` 的依赖。
3. **结构恢复不回读 words 约束**：
   - 页面文本抽取与表格结构恢复完全基于 native span、atom、列带和物理/逻辑 Cell 展开，严禁回退调用 `page.get_text("words")`，保证了端到端纯净与无损。

### 5.4 验收与测试验证结果

全量测试套件与端到端可视化流水线验证均 100% 通过：
1. **Probe Python 自动化测试**：
   - 执行命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tools/pdfium_probe/tests`
   - 结果：全部通过（包含 `test_dynamic_subprocess_render_and_timeout` 动态子进程光栅化与超时治理用例，以及 `test_find_pdfium_probe_bin_with_cargo_target_dir` 环境变量定位用例）。
2. **Probe Rust 全量测试**：
   - 执行命令：`cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
   - 结果：**12 passed; 0 failed; finished in 0.14s**（包含 `test_render_page_to_png_contract`）。
3. **主 Rust 库测试**：
   - 执行命令：`cargo test`
   - 结果：**103 passed; 0 failed; finished in 0.07s**。
4. **核心 Python 回归测试**：
   - 执行命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tests/test_classify_pdf_page.py tests/test_extract_table_region.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py`
   - 结果：**77 passed, 1 skipped in 1.83s**。
5. **端到端流水线可视化验证**：
   - 执行命令：`python tools/pdfium_probe/scripts/visualize_pipeline_steps.py --sample test_p27_table --sample credit_p1_detail`
   - 输出路径：`tools/pdfium_probe/test_data/behavioral_output/pipeline_visualization/`
   - `test_p27_table`：端到端自动恢复 9×9 完整横版表格（46 个单元格），阅读流 6 节点，与 PyMuPDF 基线完全一致；
   - `credit_p1_detail`：端到端自动检出全页全部 6 个明细表格（11×11, 6×4, 4×5, 4×4, 3×4, 2×7），阅读流 17 节点，拓扑结构完全一致。
6. **代码侵入性与约束检查**：
   - 核心生产代码（`src/`、`rust/`、根 `Cargo.toml`）严格零修改；
   - 既有未暂存 PDF 文件（`synth_crop_offset.pdf`、`synth_mixed_fonts.pdf`）完好保留。

---

## 6. Section 6: PDFium 聚类规范化 (Normalizer) 迁移至纯 Rust 原生实现

### 6.1 架构分层与核心模块

本阶段完成了将 Python 侧原有的字符、Span、Line、Block 聚类以及矢量图元规范化逻辑全面迁移至纯 Rust 原生实现，消除跨语言循环开销，提供高性能的端到端页面规范化能力：

1. **`classifier.rs`（页面分类器）**：
   - 依据字符几何有效性、Unicode 标量计数与控制字符判定规则，对原生页面进行 `vector` 或 `scanned` 分类；
   - 完整支持合成分隔空格与实际字形缺失的区分逻辑，与 Python `pdfium_classification.py` 严格对齐。
2. **`clustering.rs`（视觉几何与拓扑聚类引擎）**：
   - **Span 合并**：依据字体、字号、渲染模式及水平间距（`gap <= 0.4 * char_h`）合并同一行内的连续 Span，并完整保留字符级原始 Provenance 元数据；
   - **Line 聚类**：依据垂直重叠率（`overlap_ratio >= 0.5`）与中心距公差（`center_dist <= 0.4 * min_h`）聚集行，并增加行内水平重叠度判定（水平重叠超过 30% 严格分行，防止图层重叠文本误并）；
   - **Block 聚类**：依据行垂直间距（`line_gap <= 1.5 * ref_h`）与栏间距（`h_gutter <= 2.0 * ref_h`）划分段落块；
   - **Word 推导 (`derive_words`)**：实现对英文单词、连续数字（包括负号前缀、千分位逗号、浮点小数点、百分号后缀）及 CJK 连续文本的流式切词，同时输出 8 元组和具备 `raw_source_position` 的 Wire Word DTO。
3. **`drawings.rs`（矢量图元规范化）**：
   - 将原始线段 `l`、矩形 `re`、曲线 `c` 解析归一化为标准路径类型 `s`（描边）、`f`（填充）与 `fs`（描边填充）；
   - 提取各线段几何外框与图元属性，构造与主库 `rust_adapter` 兼容的 `WireDrawingDto`。
4. **`normalizer.rs`（聚合规范化器与 DTO 组装）**：
   - 串联分类、聚类与图元规范化，输出标准的 `NormalizedPageDto`；
   - 同步输出用于 Rust 高速恢复链路的 `PageSnapshotWireDto` 与 PyMuPDF 兼容的 `RawdictWireDto`。

### 6.2 CLI 命令扩展

在 `main.rs` 中提供规范化命令行指令：
```bash
pdfium_probe normalize <pdf_path> <page_index> <out_json>
```
- **参数控制**：接收 PDF 路径、指定页面序号（通过 `u16::try_from` 防溢出校验）和目标输出 JSON 路径；
- **原生提取与规范化**：自动加载对应操作系统架构的 PDFium 动态库（`pdfium.dll` / `libpdfium.so` / `libpdfium.dylib`），执行页面提取与全套聚类规范化；
- **输出格式**：将规范化后的 `NormalizedPageDto` 结构序列化为 Pretty JSON 写入目标文件。

### 6.3 Python 适配层接入与类型契约兼容

在 `tools/pdfium_probe/scripts/pdfium_normalizer.py` 中实现了对 Rust 规范化产物的消费与桥接：

1. **`normalize_from_rust_dto(rust_dto: Mapping[str, Any]) -> NormalizedPage`**：
   - 将 Rust 导出的 `NormalizedPageDto` 反序列化为标准 `NormalizedPage` namedtuple；
   - **`rawdict` 4 元组强类型转换**：遍历 block、line、span、char 各层级，将所有 `bbox` 强转为 4 元组 `(float(x0), float(y0), float(x1), float(y1))`。彻底解决 PyO3 `b.extract::<(f64, f64, f64, f64)>()` 对 Python `list` 类型静默忽略导致 `collect_native_spans_from_rawdict` 提取为 0 的问题；
   - **`words` 8 元组转换**：将 `rust_dto["words"]` 转换为标准的 `(x0, y0, x1, y1, text, block, line, word)` 8 元组列表；
   - **Wire Snapshot 保持**：完整保留 `page_snapshot` 字典结构供下游 `rust_adapter` 消费。
2. **`normalize_with_rust_probe(raw_page: Mapping[str, Any], pdf_path: Optional[str] = None) -> Optional[NormalizedPage]`**：
   - 定位已编译的 `pdfium_probe` 探针二进制，通过子进程执行 `pdfium_probe normalize <pdf_path> <page_index> <tmp_json>`；
   - 附带 30 秒超时保护（`timeout=30`），成功执行后通过 `normalize_from_rust_dto` 构造 `NormalizedPage`；
   - 当探测失败或超时时安全返回 `None`。
3. **`normalize_raw_page` 与 `normalize_raw_snapshot`**：
   - 自动检测并消费传入的预规范化 Rust DTO 字典（无需重复聚类）；
   - 支持显式指定 `pdf_path` 时委托给 Rust 探针原生加速；
   - 保留纯 Python 聚类与图元规范化完整实现作为离线无编译二进制环境下的可靠回退。
4. **语言兼容性约束**：
   - 严格遵循 Python 3.7+ 兼容性，所有类型标注均使用 `typing` 模块（如 `Optional`、`Union`、`Tuple` 等），杜绝 PEP 604 `|` 联合类型语法。

### 6.4 4 级全量测试与回归验证

全量 4 级回归与自动化测试 100% 通过：

1. **Probe Rust 全量测试**：
   - 执行命令：`cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
   - 结果：**40 passed; 0 failed; finished in 0.30s**（包含分类器矩阵、baselines 聚类、切词推导、Drawing 规范化、快照序列化与 JSON 往返测试）。
2. **Probe Python 自动化测试**：
   - 执行命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tools/pdfium_probe/tests/`
   - 结果：**89 passed in 4.64s**（新增并通过 `test_rust_probe_normalize_cli_and_dto_parity`）。
3. **主 Rust 库全量测试**：
   - 执行命令：`cargo test`
   - 结果：**103 passed; 0 failed; finished in 0.07s**。
4. **核心 Python 业务回归**：
   - 执行命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tests/test_classify_pdf_page.py tests/test_extract_table_region.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py`
   - 结果：**77 passed, 1 skipped in 2.40s**。
5. **端到端流水线可视化验证**：
   - 执行命令：`python tools/pdfium_probe/scripts/visualize_pipeline_steps.py --sample test_p27_table --sample credit_p1_detail`
   - 结果：两例样本全部 4 个流水线阶段图均成功生成，可视化图元和拓扑布局完全正常。
6. **双端对齐与强类型校验**：
   - 合成样本 `synth_crop_offset.pdf` 与 `synth_rotations.pdf` 的 Rust Wire Snapshot 与 Python Normalizer Snapshot 在 SHA-256 Digest 上达到 100% 字节级一致；
   - `rust_adapter.page_snapshot_digest(dto)` 计算出有效 64 字符 SHA256 哈希；
   - `rust_adapter.collect_native_spans_from_snapshot(dto)` 成功提取完整 Span 文本与坐标；
   - `rust_adapter.collect_native_spans_from_rawdict(rawdict, 100.0, 0.0)` 成功提取对应 Span，证实 4 元组 `bbox` 兼容性无误。
7. **代码约束与零侵入性**：
   - 核心生产代码（`src/`、`rust/`、根 `Cargo.toml`）严格保持零修改；
   - 既有工作区未暂存的合成测试 PDF 完好保留。

---

## 7. Section 7: PDFium 页面版面分析与自然阅读流 (Layout & Reading Order) 迁移至纯 Rust 原生实现

### 7.1 架构分层与核心算法 (Phase 2 全链路)

本阶段完成了将 Python 侧原有的表格区域扣除、行内文本重切合并、自然阅读顺序推断（Recursive XY-Cut）以及版面元素聚合（LayoutBuilder）全面迁移至纯 Rust 原生实现（`tools/pdfium_probe/src/layout.rs` 与 `main.rs`）：

1. **表格区域扣除与视觉行合并 (`deduct_tables_from_normalized_page`, `merge_same_visual_lines`)**：
   - **表格碰撞与行切断**：遍历规范化词元，按 `(block_idx, line_idx)` 聚组并按 `word_idx` 排序；当词元中心位于候选表格区域时实施行截断切分，仅保留外部词元并生成新的行候选段；
   - **视觉行合并**：对候选行按 `(y0, x0)` 排序，依据垂直重叠率（`overlap_y / min_h >= 0.5`）与水平间隙（`-2.0 <= gap_x <= 40.0`）平滑合并同一水平线上的离散分段；
   - **词间空格与跨距推导**：基于 `join_layout_words`，对于两词间距大于 1.0pt 且非中西文空白边界时自动补齐空格，保持与 Python 原生逻辑严格一致。
2. **递归 XY-Cut 自然阅读流算法 (`recursive_xy_cut`)**：
   - **投影切分 (`find_projection_cuts`)**：在区间合并后寻找无元素覆盖的投影空隙（Y 轴最小间隙 `min_y_gap = 0.0`，X 轴最小间隙 `min_x_gap = 5.0`）；
   - **跨列元素判定 (`has_spanning_element`)**：当任一元素宽度占版面总宽度 65% 以上时，禁止直接进行纵向 X-Cut 分栏，防止跨栏标题被切断；
   - **分栏有效性校验 (`is_valid_column_partition`)**：校验分栏结果，要求各栏非空且宽度在合理范围；
   - **自然行回退聚类 (`sort_items_by_row_reading_order`)**：在无法继续切分时，按垂直高度重叠聚类为行，各行内从左到右自然排序。
3. **版面构建与背景图检测 (`build_page_layout`, `sort_layout_elements`)**：
   - **表格重叠过滤 (`is_inside_any_table`)**：对扣除后的行再次执行严格几何校验（包含与 IoU > 0.5 过滤）；
   - **背景图/水印检测 (`is_background_image`)**：高度超过页面总高 40% 且绝对高度 > 150pt，并与至少 4 个文本行垂直重叠的图片识别为背景水印，在阅读流中优先排在最前列；
   - **统一编号与 DTO 组装**：按阅读流顺序为所有元素（文本、表格、图片）分配单调递增的 `order` 字段（0, 1, 2...）。
4. **CLI 命令行契约 (`pdfium_probe layout`)**：
   - 命令行接口：`pdfium_probe layout <pdf_path> <page_index> <tables_json> <out_json>`；
   - 表格参数解析（`parse_tables_json`）：同时支持内联 JSON 字符串及本地 JSON 文件路径，兼容 `[{"bbox": [...], "table_id": ...}]` 数组及包含 `tables` 键的对象包装。

### 7.2 Python 适配层接入与类型契约 (`pdfium_layout_adapter.py`)

在 `tools/pdfium_probe/scripts/pdfium_layout_adapter.py` 中实现了 Python 对 Rust 版面分析引擎的高性能调用与无缝桥接：

1. **`_find_pdfium_probe_bin() -> Optional[str]`**：
   - 支持环境变量 `PDFIUM_PROBE_BIN` 显式指定；
   - 支持环境变量 `CARGO_TARGET_DIR` 自定义构建目录；
   - 遍历 `probe_root` 与 `repo_root` 之 `target/release`、`target/debug` 路径；
   - 回退至系统 `shutil.which("pdfium_probe.exe" / "pdfium_probe")`。
2. **`normalize_tables_for_probe` 与 `serialize_tables_to_json`**：
   - 兼容多种输入对象：PDFLayoutParser 核心 `Table` dataclass、含 `bbox` 字段的字典、含 `x0, y0, x1, y1` 的字典以及 4 元组列表；
   - 序列化为 Rust 探针所需的规范 JSON 结构。
3. **`extract_layout_with_rust_probe(pdf_path, page_index, tables)`**：
   - 临时文件传输：在 Windows 平台采用安全模式（写出临时文件后立即关闭文件句柄，供子进程独占读取）；
   - 超时与错误保护：`subprocess.run(..., timeout=30)`，并包含优雅降级逻辑；
   - 强类型模型装配：将 Rust 导出的 `LayoutElementDto` 完整反序列化并构造为标准的 `LayoutElement` 对象，包含：
     - `bbox`: `BBox(x0, y0, x1, y1)`
     - `lines`: `Line(text, bbox, words)`
     - `words`: `Word(text, bbox)`
     - `type`: `"text"` / `"table"` / `"image"`
     - `order`: `int`
     - `content`: 对于表格元素自动关联输入列表中的原始 `Table` 对象，并设置 `elem.table` 属性以完全兼容下游消费习惯。
4. **语言兼容性约束**：
   - 严格兼容 Python 3.7+，所有类型注解均使用 `typing` 模块标准类，杜绝 PEP 604 语法。

### 7.3 可视化流水线接入与对齐 (`visualize_pipeline_steps.py`)

在 `tools/pdfium_probe/scripts/visualize_pipeline_steps.py` 中，将 Stage 4（最终版面与阅读流全景）的 PDFium 分支全面升级为调用原生 Rust 引擎：
- 引入 `from pdfium_layout_adapter import extract_layout_with_rust_probe`；
- 在 Stage 4 中直接通过 `extract_layout_with_rust_probe(sample.pdf_path, sample.page_index, pdfium_tables)` 获取最终版面元素；
- 端到端自动生成 04_final_reading_order.png，验证了正文徽标、表格徽标与阅读流连线轨迹的完整绘制。

### 7.4 4 级全量测试与双端 Parity 验收

全量 4 级回归与自动化测试 100% 通过：

1. **Probe Rust 全量测试**：
   - 执行命令：`cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
   - 结果：**68 passed; 0 failed; finished in 0.17s**（涵盖 XY-Cut 单/双栏/跨栏测试、投影切割、表格扣除、视觉行合并、版面构建与 CLI 契约测试）。
2. **Probe Python 自动化测试**：
   - 执行命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tools/pdfium_probe/tests/`
   - 结果：**92 passed in 7.91s**（新增并通过 `test_rust_layout_cli_invocation`、`test_rust_layout_adapter_with_tables`、`test_rust_and_python_layout_parity`）。
3. **主 Rust 库全量测试**：
   - 执行命令：`cargo test`
   - 结果：**103 passed; 0 failed; finished in 0.06s**。
4. **核心 Python 业务回归**：
   - 执行命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tests/test_classify_pdf_page.py tests/test_extract_table_region.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py`
   - 结果：**77 passed, 1 skipped in 2.17s**。
5. **端到端流水线可视化验证**：
   - 执行命令：`python tools/pdfium_probe/scripts/visualize_pipeline_steps.py --sample test_p27_table --sample credit_p1_detail`
   - 结果：`test_p27_table` 与 `credit_p1_detail` 全部 4 阶段图像与 README 成功生成，Stage 4 完美展示了 Rust 引擎驱动的自然阅读顺序流。
6. **双端对齐 (Parity)**：
   - 在 `synth_crop_offset.pdf`（含表格与不含表格）及 `synth_invisible_text.pdf` 上，Rust 原生探针输出与 Python 基线（`TextExtractor + LayoutMapper + LayoutBuilder`）在元素数量、元素类型（`text` / `table`）、阅读顺序 `order` 以及几何包围盒 `BBox` 上达到完全等价对齐。
7. **代码约束与零侵入性**：
   - 核心生产代码（`src/`、`rust/`、根 `Cargo.toml`）严格保持零修改；
   - 既有工作区未暂存的合成测试 PDF 完好保留。

---

## 8. Markdown 与 JSON 格式化导出器迁移至纯 Rust 原生实现 (Phase 3)

### 8.1 任务背景与核心目标

Phase 3 实现了将全流程下游格式化导出器（Markdown 与统一 JSON）从 Python 原生迁移至 compiled Rust 原生引擎：
1. **纯 Rust Markdown 导出核心 (`markdown.rs`)**：
   - 实现 HTML 表格渲染 (`render_html_table`)，忠实对齐 Python `MarkdownWriter._render_table`：
     - 正确处理 `rowspan > 1` 与 `colspan > 1` 属性；
     - 维护槽位覆盖集 `covered`，并在未显式声明的稀疏槽位自动补全 `<td></td>`；
     - HTML 实体转义（`&` -> `&amp;`，`<` -> `&lt;`，`>` -> `&gt;`；单双引号保持不转义，严格对齐 Python `html.escape(quote=False)`）；
     - 纯正则等价的数字内部多余断行空格清洗（`clean_number_text` 严格对齐 Python `re.compile(r"(?<=[\d,\.\-])\s+(?=[\d,\.\-])")`）。
   - 实现整页自然阅读顺序排版渲染 (`render_page_markdown`)：正文文本块段落输出、表格按版面位置就地嵌入、图片与印章占位标记。
   - CLI 命令行接口：`pdfium_probe markdown <pdf_path> <page_index> <tables_json> <out_md>`。
2. **纯 Rust 统一 JSON 导出核心 (`json_export.rs`)**：
   - 坐标契约统一：所有几何元素使用 `BBoxCoordDto` (`{"x0": f64, "y0": f64, "x1": f64, "y1": f64}`)，与 Python `JSONWriter` 数据模型完全同构；
   - 完整页面导出 (`export_page_to_json`)：包含 `index`、`size` (`width`/`height`)、`rotation`、`page_type`、`blocks`、`tables`、`images`、`seals`、`render`、`layout_elements`；
   - 完整文档导出 (`export_document_to_json`)：包含 `document` 元数据与多页 `pages` 结构；
   - CLI 命令行接口：`pdfium_probe json <pdf_path> <page_index> <tables_json> <out_json>`。
3. **表格参数解析与网格推断 (`main.rs` 中的 `parse_full_tables_json`)**：
   - 兼顾直接传入内联 JSON 字符串与读取 JSON 临时文件路径；
   - 灵活反序列化：支持原生列表 `[...]`、含 `"tables"` 包装的字典对象、单表格对象；
   - 网格缺失自动推断：当表格 `rows` 或 `cols` 未提供或为 0 时，依据包含单元格的 `row_index + rowspan` 与 `col_index + colspan` 自动推断最大网格维度。
4. **Python 适配层接入 (`pdfium_writer_adapter.py`)**：
   - 统一二进制定位器 `_find_pdfium_probe_bin() -> Optional[str]`；
   - 规范化转换器 `normalize_full_tables_for_probe(tables)`：将 Python dataclass `Table`、`Cell`、及字典等任意合法输入转换至规范线格式；
   - Windows 临时文件句柄安全：在调用子进程前显式 `close()` 临时文件句柄，避免子进程读取锁冲突；
   - 优雅回退保障：在 Rust 探针二进制未编译或执行异常时，平滑降级至 `_python_fallback_markdown` 与 `_python_fallback_json`；
   - 语言兼容性：严格遵循 Python 3.7+ 语法，类型注解全部引用自 `typing`，严禁使用 PEP 604 联合类型语法。
5. **不回读 Words 的核心架构约束**：
   - 无论 Markdown 导出还是 JSON 导出，全流程严格消费原子 TextObject、Native Span、列带、物理网格和逻辑 Cell。
   - 结构恢复与排版阶段绝对不再次调用 `page.get_text("words")` 进行二次重读。

### 8.2 4 级全量测试与双端 Parity 验收

全套 4 级验证套件 100% 通过：
1. **Probe Rust 全量测试**：
   - 命令：`cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
   - 结果：**83 passed; 0 failed; finished in 0.13s**（涵盖 `markdown`、`json_export`、`parse_full_tables_json`、`layout`、`classifier`、`clustering`、`drawings` 与 `normalizer` 全量测试）。
2. **Probe Python 自动化测试**：
   - 命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tools/pdfium_probe/tests/`
   - 结果：**97 passed in 8.35s**（新增并通过 `test_pdfium_writers.py` 全部 5 项测试）。
3. **主 Rust 库全量测试**：
   - 命令：`cargo test`
   - 结果：**103 passed; 0 failed; finished in 0.06s**。
4. **核心 Python 业务回归**：
   - 命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tests/test_classify_pdf_page.py tests/test_extract_table_region.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py tests/test_markdown_writer.py tests/test_json_writer.py`
   - 结果：**82 passed, 1 skipped in 2.30s**。
5. **端到端流水线可视化验证**：
   - 命令：`python tools/pdfium_probe/scripts/visualize_pipeline_steps.py --sample test_p27_table --sample credit_p1_detail`
   - 结果：成功生成 4 阶段高分辨率可视化全景图，各阶段产物完整无报错。
6. **双端对齐 (Parity) 验收**：
   - Markdown 对齐：复杂跨度、稀疏空白单元格、特殊字符 HTML 转义及数字空格清洗在 Rust 与 Python 间实现逐字符 100% 吻合；
   - JSON 结构对齐：页面对象顶级键、表格嵌套结构、单元格字典键集合、几何 BBox 坐标字典格式完全同构；
   - 真实/合成样本端到端验证通过。

---

## 9. YOLO 表格检测器迁移至纯 Rust ONNX Runtime 原生实现 (Phase 4)

### 9.1 任务背景与核心目标

Phase 4 实现了将版面分析关键的 ML 阶段——YOLO 目标检测模型（`best.onnx`）从 Python `onnxruntime` 迁移至纯 Rust 原生实现（基于 `ort` 2.0.0-rc.9）：
1. **纯 Rust 图像预处理与张量构建 (`preprocess_image_to_nchw`)**：
   - 采用 `image` crate 的双线性插值算法将 PDF 渲染底图缩放至 640×640；
   - 提取 RGB 三通道归一化为 `[0.0, 1.0]` 的浮点数；
   - 组装标准 `[1, 3, 640, 640]` NCHW planar layout 浮点数组，完全等价于 Python OpenCV + NumPy 流程。
2. **纯 Rust 几何运算与非极大值抑制 (`non_maximum_suppression`)**：
   - 实现高精度 `BBoxFloat` 几何计算（交集、并集、IoU 计算）；
   - 实现 Greedy NMS 算法，默认 IoU 阈值 0.50，置信度阈值 0.40；
   - 支持 End-to-End YOLO (`[1, N, 6]`) 与 YOLOv8 标准输出 (`[1, 84, N]`) 双格式解码，并过滤类别 ID (`table_class_ids: [0, 4]`)。
3. **后处理算法对齐 (`filter_full_page_false_positives` & `expand_bbox_to_touching_words`)**：
   - 假阳性过滤：面积占比超过整页 85% 且置信度低于 0.50 的误检候选框自动剔除；
   - 词框向外扩展：仅对直接与原始检测框相交的文字 words 进行向外吸附扩展，不跨越未相交文字，并严格限制在页面视口包围盒内；
   - 保持架构不变量：结构恢复阶段严格不回读 `page.get_text("words")`，检测后处理只消费标准提取出的 words 几何列表。
4. **CLI 命令行接口与参数契约**：
   - 子命令：`pdfium_probe detect-tables <pdf_path> <page_index> <model_path> <out_json>`；
   - 模型路径智能解析：支持显式路径、`auto`/`default` 关键字及 `YOLO_TABLE_DETECTOR_MODEL` 环境变量；
   - 边界安全防范：对 `out_json.parent()` 过滤空路径（`.filter(|p| !p.as_os_str().is_empty())`），防止相对路径建目录报错；
   - 序列化输出：输出包含 `x0, y0, x1, y1, score, label` 的结构化 JSON。
5. **Python 适配层接入 (`pdfium_table_detector_adapter.py`)**：
   - 核心接口：`detect_tables_with_rust_probe(pdf_path, page_index=0, model_path=None, confidence_threshold=0.40) -> List[Tuple[BBox, float]]`；
   - Windows 临时文件句柄安全释放；
   - 二进制自动定位与优雅降级回退至 Python `MLTableDetector`；
   - 严格遵循 Python 3.7+ 兼容性，杜绝 PEP 604 语法。
6. **双端对齐 (Dual-Engine Parity) 验收**：
   - 在真实表格样本（`test.pdf` 第 27 页）上验证双端对齐指标：
     - 表格检出数量完全一致（1 个表格）；
     - 双端几何包围盒 IoU >= 0.996（门禁阈值 0.95）；
     - 各边坐标偏差 < 0.7 pt（门禁阈值 1.0 pt）；
     - 置信度得分偏差 < 0.0001（门禁阈值 0.05）；
     - 空白/无表格页面双端一致返回 `[]`。

### 9.2 5 级全量验证矩阵 (5-Tier Verification Suite)

全套 5 级验证套件 100% 通过：
1. **Probe Rust 全量测试**：
   - 命令：`cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
   - 结果：**100 passed; 0 failed; finished in 1.42s**（涵盖 `detector`、`markdown`、`json_export`、`layout`、`classifier`、`clustering`、`drawings` 与 `normalizer` 全量测试）。
2. **Probe Python 自动化测试**：
   - 命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tools/pdfium_probe/tests/`
   - 结果：**103 passed in 24.52s**（新增并通过 `test_pdfium_table_detector.py` 全部 6 项对齐与降级测试）。
3. **主 Rust 库全量测试**：
   - 命令：`cargo test`
   - 结果：**103 passed; 0 failed; finished in 0.06s**。
4. **核心 Python 业务回归**：
   - 命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tests/test_classify_pdf_page.py tests/test_extract_table_region.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py tests/test_markdown_writer.py tests/test_json_writer.py tests/test_ml_table_detector.py`
   - 结果：**99 passed, 1 skipped in 3.60s**。
5. **端到端流水线可视化验证**：
   - 命令：`python tools/pdfium_probe/scripts/visualize_pipeline_steps.py --sample test_p27_table --sample credit_p1_detail`
   - 结果：成功生成 4 阶段高分辨率可视化全景图，各阶段产物完整无报错。

---

## 10. 流水线 Stage 调度编排与统一端到端 CLI 原生化 (Phase 5)

### 10.1 任务背景与核心目标

Phase 5 实现了整个 PDFLayoutParser 全链路纯 Rust 化的终极闭环——将此前各独立迁移的阶段引擎（底图光栅化渲染、Normalizer 规范化聚类、ONNX Runtime YOLO 表格检测、递归 XY-Cut 阅读序拓扑重构、Markdown 与 JSON 统一导出）汇聚成一个原生调度引擎：
1. **纯 Rust 统一流水线调度器 (`pipeline.rs`)**：
   - 统一调度：输入 PDF -> PDFium 绑定加载 -> 目标页范围过滤 -> 多阶段逐页处理 -> 文档级统一聚合输出；
   - Stage 1 (Normalizer): 规范化提取文字、词元与矢量绘制图元，执行 6 级 Unicode 门禁状态机判定与页面分类；
   - Stage 2 (Render): 页面底图光栅化导出（`output_dir/renders/page-XXX.png`）；
   - Stage 3 (Detector): ONNX Runtime YOLO 原生推理，检出表格候选框生成 `FullTableDto`；
   - Stage 4 (Layout): 扣除表格区域、合并水平视觉行、递归 XY-Cut 空间剖分重构自然阅读流拓扑；
   - Stage 5 (Writers): 导出单页 `pages/page-XXX.json` 与 `pages/page-XXX.md`；
   - 文档级聚合：导出整篇文档的 `output.json` 与 `output.md`（分页隔断 `\n\n---\n\n`）；
   - 耗时统计：返回包含各页面与总处理耗时的 `PipelineSummaryDto`。
2. **统一端到端 CLI 子命令 (`pdfium_probe parse`)**：
   - 命令格式：`pdfium_probe parse <pdf_path> [options]`；
   - 丰富选项：`-o`/`--output`（输出目录）、`--dpi`（光栅化 DPI）、`--pages`（选定页码列表）、`--model`（YOLO 模型路径，支持 `auto` 自动探测）、`--confidence`（置信度阈值）、`--no-renders`（跳过底图生成）、`--no-pages`（跳过单页文件导出）；同时支持位置参数回退 `<pdf_path> <output_dir>`；
   - 严格校验：防范非法负数/非有限 DPI、超出 `[0.0, 1.0]` 置信度、参数歧义与越界页码索引。
3. **Python 适配层接入 (`pdfium_pipeline_adapter.py`)**：
   - 核心接口：`parse_pdf_with_rust_probe(pdf_path, output_dir, page_indices=None, render_dpi=72.0, model_path=None, confidence_threshold=0.40, export_renders=True, export_pages=True) -> Dict[str, Any]`；
   - 跨平台二进制智能探测：支持环境变量 `PDFIUM_PROBE_BIN`、工作树多层 target 目录以及系统 PATH；
   - 120 秒超时防护与进程安全执行；
   - 优雅降级机制：探针缺失或子进程执行失败时无缝自动回退到 Python 原生 `Pipeline` 实现；
   - 严格遵循 Python 3.7+ 兼容性，杜绝 PEP 604 联合类型语法。
4. **端到端测试与质量验证 (`test_pdfium_pipeline.py`)**：
   - 端到端全产物持久化验证（`output.json`, `output.md`, `pages/`, `renders/` 文件有效性与非空检查）；
   - 页面切片索引选择验证；
   - 二进制缺失模拟回退验证；
   - 导出标志位过滤控制验证。

### 10.2 5 级全量验证矩阵 (5-Tier Verification Suite)

全套 5 级验证套件 100% 通过：
1. **Probe Rust 全量测试**：
   - 命令：`cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
   - 结果：**108 passed; 0 failed; finished in 6.54s**（涵盖 `pipeline`、`detector`、`markdown`、`json_export`、`layout`、`classifier`、`clustering`、`drawings` 与 `normalizer` 全量 108 项测试）。
2. **Probe Python 自动化测试**：
   - 命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tools/pdfium_probe/tests/`
   - 结果：**107 passed in 40.65s**（新增并通过 `test_pdfium_pipeline.py` 全部 4 项端到端及特性测试）。
3. **主 Rust 库全量测试**：
   - 命令：`cargo test`
   - 结果：**103 passed; 0 failed; finished in 0.06s**。
4. **核心 Python 业务回归**：
   - 命令：`$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python -m pytest -q tests/test_classify_pdf_page.py tests/test_extract_table_region.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py tests/test_markdown_writer.py tests/test_json_writer.py tests/test_ml_table_detector.py`
   - 结果：**99 passed, 1 skipped in 3.60s**。
5. **端到端流水线可视化验证**：
   - 命令：`python tools/pdfium_probe/scripts/visualize_pipeline_steps.py --sample test_p27_table --sample credit_p1_detail`
   - 结果：成功生成 4 阶段高分辨率可视化全景图，各阶段产物完整无报错。
6. **静态分析与代码格式**：
   - `cargo clippy --bin pdfium_probe -D warnings`：0 warnings / 0 errors。
   - `git diff --check`：0 格式错误。

## 2026-10-08：Task 10 公开 API 兼容性修复

- 独立 PDF 公开 API 使用新增的扫描页规范化入口：保留 `page_type="scanned"`，同时保留 PDFium native span、rawdict 与 words；主 `parse()` 路径继续使用原扫描页早退行为。
- 扫描页 `extract_table_in_region` 仅允许 `scanned` 页的 `line_projection` 返回空文本表格，并保持单元格边界检查、跨度范围检查和冲突检查；按保存的基线恢复第 705 页 4×2、3 cells 结果。
- 第 437 页的整页 `extract_table_in_region` 不再尝试无线 fallback；按明确指定的区域仍保留无线表格恢复。占位冲突检查未放宽。
- Benchmark 增加归一化、公共字段保留、文本与 cell 文本哈希差异的直接测试。`table_structure` 跳过判断改为隔离子进程实际调用 Rust API；仅识别 Rust 调用报告的 `BadVersion` 版本错误，超时、断言失败和其他错误仍作为失败上报。当前 Cargo feature 树显示 ORT API 下限为 27；未改生产 ORT 依赖或链接配置。
- 验证：`cargo check --manifest-path tools/pdfium_probe/Cargo.toml --tests` 成功；`tests/test_rust_public_api_benchmark.py` 为 4 passed；`git diff --check` 成功。目标 Rust 测试无法运行：MSVC 14.40 链接默认 ORT 静态库时出现 `LNK1120` / 13 个 `__std_*` 未解析符号。兼容修复后的 Rust 运行时结果与完整差异 benchmark 尚未获得，因此不能据此宣称其余基线差异已消除。
