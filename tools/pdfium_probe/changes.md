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
