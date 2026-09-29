# Task 6 变更记录 (changes.md)

## 1. 任务背景与核心改动

本任务完成了 **Task 6: 样本矩阵、确定性输出和中文验收报告**。
主要建立了跨 PDFium 原生探针与 PyMuPDF 双引擎的行为影子对比矩阵，规范化 3 次执行的确定性输出，输出完整的审计台账与验收报告。

### 主要改动文件

1. **`tools/pdfium_probe/scripts/export_pymupdf_baseline.py`**:
   - 适配环境变量 `PDFIUM_OUTPUT_ROOT`，当环境变量存在时将合成基线和真实基线分别输出至 `${PDFIUM_OUTPUT_ROOT}/baseline` 与 `${PDFIUM_OUTPUT_ROOT}/real_baseline`。
   - 在导出的 PyMuPDF baseline JSON 顶层增加 `source_file_sha256` 存证字段，支持与实时源 PDF SHA 进行防篡改/防过期校验。
   - 严格遵循 Python 3.7 兼容性，类型注解均引用自 `typing`。
2. **`tools/pdfium_probe/scripts/run_behavioral_matrix.py`**:
   - 核心接口契约：`run_behavioral_matrix(*, fixture_manifest: Path, pdfium_roots: Sequence[Path], output_dir: Path) -> Dict[str, Any]`。
   - 实现 `--manifest`、多值 `--pdfium-root` 与 `--output` 的 CLI 命令行支持。
   - 跨轮次执行管理：为每个 root 分配 `run-01`、`run-02`、`run-03` 等独立目录，隔离运行产物。
   - 防篡改与阻断校验：校验 live PDF SHA-256 与 raw snapshot / baseline 中记录的源哈希，不匹配或输入缺失时如实记录为 `blocked_input`。
   - 规范化 Canonical JSON 序列化：递归键排序、UTF-8 紧凑编码、浮点数统一 round 到 4 位；文本与 Markdown 严格不 trim、不折叠内部空格。
   - 供应链信息采集：从 `manifest.json` 读取当前平台的 `release_tag`、`archive_sha256`、`library_relpath` 及预期 `library_sha256`，校验与 raw snapshot 中的动态库哈希一致性。
   - 表格 Overlay 导出接口：`render_table_overlays(pdf_path, page_index, pdfium_tables, pymupdf_tables, output_dir)`，复用 `hexai_pdf_parser.debug.table_visualizer.render_table_visualization` 生成两侧引擎的 200 DPI PNG 视图。
3. **`tools/pdfium_probe/test_data/behavioral/fixtures.json`**:
   - 包含 11 个标准代表性测试样本：`synth_crop_offset`、`synth_rotations` (0/90/180/270 四页)、`synth_invisible_text`、`synth_mixed_fonts`、`synth_segmented_lines`、`test_p27_table`、`credit_p0_header`、`credit_p1_detail`。
   - 包含 `table_regions` 显式表格区域配置。
4. **`tools/pdfium_probe/tests/test_behavioral_matrix.py`**:
   - 6 个自动化测试用例，覆盖单样本运行、多轮次确定性哈希校验、表格叠加图导出、缺失文件阻断、哈希不匹配阻断及 Canonical 序列化不变性。
5. **`tools/pdfium_probe/tests/fixtures/single_behavioral_fixture.json`**:
   - 单样本单元测试轻量级 fixture 定义。
6. **`tools/pdfium_probe/SPRINT2_BEHAVIORAL_REPORT.md`**:
   - 完整的中文行为影子矩阵与确定性验收审计报告。

---

## 2. 根因、判定条件与调用约束

### 2.1 页面分类分歧根因 (Root Cause)

- 在 `synth_invisible_text`、`synth_mixed_fonts`、`synth_segmented_lines` 等样本中，PDFium 在行尾自动合成了空格，导致 `visible_text_scalar_count` 与 `extracted_char_scalar_count` 产生了细微差异。
- 在真实代表样本（`test_p27_table`、`credit_p0_header`、`credit_p1_detail`）中，部分中文字体缺少标准 ToUnicode CMap 映射，部分字形为非标 Identity-H。
- **CJK unknown 未继续解析**：探针遵循安全门禁原则，遇到字符映射异常时不强行转码产生带 `\ufffd` 的乱码 Markdown，而是诚实标记为 `invalid_unicode_mapping` 并将页面类型判定为 `scanned`；由于 PyMuPDF 判定为 `vector`，双引擎产生分类分歧（`scanned` vs `vector`），影子运行器将其安全归类为 `unsupported`。

### 2.2 不回读 words 约束 (No Re-reading Words)

- 在 `pdfium_normalizer.py`、`pdfium_page_adapter.py` 以及 `pdfium_shadow_runner.py` 全流程中，结构恢复阶段严格仅消费原子 TextObject、native span、列带、物理单元格和逻辑 Cell。
- 进入结构推断阶段后，代码中禁止调用 `page.get_text("words")` 进行二次重读，杜绝基于单词聚类对结构恢复造成的非幂等破坏。

---

## 3. 测试验证结果

1. **单元测试**:
   - 执行命令: `pytest -q tools/pdfium_probe/tests/`
   - 结果: 76 passed in 1.35s。
2. **完整行为矩阵运行 (Step 4)**:
   - 执行命令:
     ```powershell
     $env:PYTHONPATH = "src;tools/pdfium_probe/scripts"
     $env:REPO_ROOT = "D:\codes\PDFLayoutParser"
     $runRoots = @()
     1..3 | ForEach-Object {
         $env:PDFIUM_OUTPUT_ROOT = "tools/pdfium_probe/test_data/behavioral_output/native-run-$_"
         cargo run --manifest-path tools/pdfium_probe/Cargo.toml
         python tools/pdfium_probe/scripts/export_pymupdf_baseline.py
         $runRoots += $env:PDFIUM_OUTPUT_ROOT
     }
     python tools/pdfium_probe/scripts/run_behavioral_matrix.py --manifest tools/pdfium_probe/test_data/behavioral/fixtures.json --pdfium-root $runRoots[0] --pdfium-root $runRoots[1] --pdfium-root $runRoots[2] --output tools/pdfium_probe/test_data/behavioral_output/matrix-001
     ```
   - 结果:
     - Fixtures: 11
     - Runs: 3
     - **Deterministic: True** (`all_equal: true`)
     - Passed: 5
     - Failed: 0
     - Scanned: 0
     - Unsupported: 6 (触发安全门禁，符合预期)
     - Blocked Input: 0
     - Unclassified: 0
3. **输出页面与数据路径**:
   - 矩阵汇总: `tools/pdfium_probe/test_data/behavioral_output/matrix-001/summary.json`
   - 各样本执行产物位于 `tools/pdfium_probe/test_data/behavioral_output/matrix-001/run-01/` 到 `run-03/`，包含 `result.json`、`ledger.json`、`pdfium.md`、`pymupdf.md`、`diff.json`、`layout_signature.json`、`table_signature.json`、`diagnostics.json`、`errors.json` 以及 `pdfium_overlay.png` / `pymupdf_overlay.png`。

---

## 4. Task 7 最终系统验证与环境回归记录 (Task 7 Steps 1-4)

### 4.1 生产代码与构建零污染检查 (Step 1)
- `git diff --name-only 4d01c48..HEAD` 验证：所有已提交变动完全局限于 `tools/pdfium_probe/` 与 `docs/superpowers/`，根目录 `Cargo.toml`、`src/` 以及 `rust/` 保持完全零改动。
- `git status --porcelain` 验证：原样保留两个预先存在的非本 Sprint 提交的 PDF 变更 (`synth_crop_offset.pdf`, `synth_mixed_fonts.pdf`)，未被污染提交。

### 4.2 根工程回归与 Wheel 构建验证 (Step 2)
- `cargo check`: 成功通过 (dev profile，未引入任何编译错误)。
- `cargo test --lib`: 成功通过，**103 passed; 0 failed; 0 ignored**。
- `maturin build --release --out tools/pdfium_probe/test_data/behavioral_output/wheel`:
  - 成功生成 `hexai_pdf_parser-1.1.4-cp37-abi3-win_amd64.whl`。
  - 解包检验确认：包含 `_pdf_fast` 原生扩展模块，且**不包含**任何 `pdfium.dll`、`libpdfium.so` 或 `libpdfium.dylib` 动态库，确保生产分发包零依赖污染。
- 根测试用例回归：
  - 执行命令: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"; $env:PYTHONPATH = "src"; python -m pytest -q tests/test_page_classifier.py tests/test_pdf_snapshot.py tests/test_markdown_writer.py tests/test_reading_order.py`
  - 结果: **105 passed in 37.04s**。

### 4.3 Probe 与 Shadow 测试套件验证 (Step 3)
- 原生探针单元测试: `cargo test --manifest-path tools/pdfium_probe/Cargo.toml`
  - 结果: **10 passed; 0 failed; finished in 0.00s**。
- 影子对比与探针 Python 测试: `$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; python -m pytest -q tools/pdfium_probe/tests`
  - 结果: **76 passed in 1.42s**。

### 4.4 行为矩阵与跨运行确定性校验 (Step 4)
- 执行命令:
  `$env:PYTHONPATH = "src;tools/pdfium_probe/scripts"; $env:REPO_ROOT = "D:\codes\PDFLayoutParser"; python tools/pdfium_probe/scripts/run_behavioral_matrix.py --manifest tools/pdfium_probe/test_data/behavioral/fixtures.json --pdfium-root tools/pdfium_probe/test_data/behavioral_output/native-run-1 --pdfium-root tools/pdfium_probe/test_data/behavioral_output/native-run-2 --pdfium-root tools/pdfium_probe/test_data/behavioral_output/native-run-3 --output tools/pdfium_probe/test_data/behavioral_output/final-run`
- 结果:
  - Fixtures: 11
  - Runs: 3
  - **Deterministic: True** (`all_equal: true`，3 次运行全样本 Canonical SHA-256 100% 一致)
  - Passed: 5
  - Failed: 0
  - Scanned: 0
  - Unsupported: 6 (明确归类为 `page_classification` 门禁分歧)
  - Blocked Input: 0
  - Unclassified: 0
- `git diff --check`: 退出码 0，无任何空白或冲突标记残留。
- 表格 Overlay PNG 人工核验：
  - `test_p27_table`: `pdfium_overlay.png` 与 `pymupdf_overlay.png` 均为完整页面光栅化视图，门禁有效阻断空表格进入推断。
  - `credit_p1_detail`: `pdfium_overlay.png` 与 `pymupdf_overlay.png` 结构清晰完整，源 PDF 保持零变更。

