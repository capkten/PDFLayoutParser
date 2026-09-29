# Task 6 & 验收评审整改变更记录 (changes.md)

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
