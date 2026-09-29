# Sprint 2 行为影子矩阵、确定性输出与双解析器验收报告

## 1. 报告综述与执行概况

本报告基于 PDFium 探针与 PyMuPDF 双引擎的影子执行矩阵（Behavioral Shadow Matrix），针对 Sprint 2 的原子 TextObject 规范化、矢量图元标准化、Unicode 映射门禁及表格恢复链路进行全样本验证与跨运行确定性审计。在收到行为验收评审反馈后，已进一步落实 5 项关键治理：修复退出码门禁缺陷、重新归因合成分隔空格以解除误杀、激活真实表格与阅读流比对、消除代码格式警告并统一锁定依赖版本。

### 1.1 执行环境与运行参数

- **执行工作区**: `C:\Users\23662\.codex\worktrees\pdfium-shadow-markdown\PDFLayoutParser`
- **真实 PDF 根目录 (`REPO_ROOT`)**: `D:\codes\PDFLayoutParser`
- **Python 运行时**: Python 3.12 (兼容 Python 3.7 静态类型规范)
- **PyMuPDF 运行时版本**: PyMuPDF 1.28.2 (MuPDF 1.28.2)
- **PDFium 原生库供应链信息**:
  - `release_tag`: `chromium/8066`
  - 选型依据: `bblanchon/pdfium-binaries` 官方发布的 `chromium/8066` 具备各主流操作系统架构（Windows x64、Linux x64、macOS arm64/x64）完整的官方 SHA-256 校验链，各平台发布哈希均记录于 `manifest.json`。
  - 目标平台: `win-x64`
  - 官方压缩包 SHA-256: `739a57d597d864297909cc40a2411eba728490c76a0fa25e3ea299c7f6b07020`
  - 动态库路径: `native/win-x64/pdfium.dll`
  - 预期动态库 SHA-256: `d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b`
  - 运行时实际动态库 SHA-256: `d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b` (强校验一致: `verified`)
- **运行轮次**: 3 次独立原生抽取与基准比对 (`native-run-1`, `native-run-2`, `native-run-3`)
- **输出目录**: `tools/pdfium_probe/test_data/behavioral_output/final-run`

### 1.2 确定性与比对判定总结

| 指标 | 统计值 | 结论说明 |
| :--- | :--- | :--- |
| **样本总数 (Fixtures)** | 11 | 覆盖合成样本 (8 项) 与真实样本 (3 项) |
| **执行轮次 (Runs)** | 3 | 三次独立执行，输出至独立根目录 |
| **确定性判定 (Deterministic)** | **100% 吻合 (`all_equal: true`)** | 11 个样本在 3 次运行中的规范化 Canonical SHA-256 完全相同 |
| **通过数量 (Passed)** | 7 | 合成旋转、裁切偏移、混合字体及重叠不可见文本样本两引擎行为完全等价 |
| **不支持/分歧 (Unsupported)** | 3 | 真实样本未建模水印/印章 (`unsupported_element_kind`) 与断续线无闭合网格 (`no_valid_grid`) |
| **失败 (Failed)** | 1 | `test_p27_table` 无线表格两端分别恢复出 9 行与 27 行，比对器如实检出结构与阅读顺序差异 |
| **未分类 (Unclassified)** | 0 | 所有样本均明确判定分类 |
| **阻断输入 (Blocked Input)** | 0 | 所有 PDF 来源及 SHA 校验均完好，无过期/缺失输入 |

---

## 2. 样本矩阵清单与显式区域配置

行为矩阵样本定义位于 `tools/pdfium_probe/test_data/behavioral/fixtures.json`：

| 样本名称 (Name) | 样本来源 | 相对路径 | 页码 | 预期类型 | 表格显式区域 (table_regions) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `synth_crop_offset` | `probe` | `test_data/synthetic/synth_crop_offset.pdf` | 0 | `vector` | `[]` (全页阅读流) |
| `synth_rotations_0` | `probe` | `test_data/synthetic/synth_rotations.pdf` | 0 | `vector` | `[]` (全页阅读流) |
| `synth_rotations_90` | `probe` | `test_data/synthetic/synth_rotations.pdf` | 1 | `vector` | `[]` (全页阅读流) |
| `synth_rotations_180` | `probe` | `test_data/synthetic/synth_rotations.pdf` | 2 | `vector` | `[]` (全页阅读流) |
| `synth_rotations_270` | `probe` | `test_data/synthetic/synth_rotations.pdf` | 3 | `vector` | `[]` (全页阅读流) |
| `synth_invisible_text` | `probe` | `test_data/synthetic/synth_invisible_text.pdf` | 0 | `vector` | `[]` (全页阅读流) |
| `synth_mixed_fonts` | `probe` | `test_data/synthetic/synth_mixed_fonts.pdf` | 0 | `vector` | `[]` (全页阅读流) |
| `synth_segmented_lines`| `probe` | `test_data/synthetic/synth_segmented_lines.pdf` | 0 | `vector` | `[{"kind": "wired", "x0": 50.0, "y0": 80.0, "x1": 450.0, "y1": 180.0}]` |
| `test_p27_table` | `repo` | `test.pdf` | 27 | `vector` | `[{"kind": "wireless", "x0": 20.0, "y0": 100.0, "x1": 575.0, "y1": 450.0}]` |
| `credit_p0_header` | `repo` | `征信解析样例.pdf` | 0 | `vector` | `[]` (全页阅读流) |
| `credit_p1_detail` | `repo` | `征信解析样例.pdf` | 1 | `vector` | `[{"kind": "wired", "x0": 28.0, "y0": 32.0, "x1": 565.0, "y1": 153.0}]` |

---

## 3. 页面分类判定与根因分析

根据 Sprint 2 设计，PDFium 在进入 Normalizer 之前必须经过 `pdfium_classification.py` 的 Unicode 映射与几何校验门禁。

### 3.1 空格差异与合成分隔空格归因

在 Sprint 2 早期实现中，PDFium 的 TextPage 分析器在 TextObject 边界处自动注入的末尾空格（`' '`）未被单独识别，导致 `visible_text_scalar_count` 与实际字形字符数 `extracted_char_scalar_count` 不相等，被机械判定为 `invalid_unicode_mapping` 并降级为 `scanned`，造成 6 个有效矢量样本被误杀。

在本轮整改中：
1. 底层探针 `main.rs` 与分类器 `pdfium_classification.py` 严格比对非空白 Unicode 字符序列；若 `text.trim_end_matches(' ') == extracted_text`，累加 `synthetic_space_count` 并放行；
2. 只有当剔除合成分隔空格后字符序列实质不匹配、存在非法控制字符或 `\ufffd` 时，才归入映射异常；
3. 调整后，所有 11 个有效矢量样本在两端均一致判定为 `vector` / `valid`，真实激活了后续正文与表格抽取。

### 3.2 样本逐页分类与比对判定

1. **`synth_crop_offset`**:
   - PDFium 探针分类: `vector` (`valid`)，PyMuPDF 分类: `vector`
   - 判定: **Passed**。CropBox 偏移转换经几何重映射后正确恢复自然阅读流。
2. **`synth_rotations` (0° / 90° / 180° / 270°)**:
   - PDFium 探针分类: 全部为 `vector` (`valid`)，PyMuPDF 分类: 全部为 `vector`
   - 判定: **Passed**。四个视口旋转角度在两个引擎下均实现坐标体系对齐与阅读顺序一致。
3. **`synth_invisible_text`**:
   - PDFium 探针分类: `vector` (`valid`)，PyMuPDF 分类: `vector`
   - 判定: **Passed**。针对重叠文本（`Overlapped Text Base` 与 `Overlapped Text Top`）优化了行内水平重叠判定（水平重叠超过 30% 不得合并到同一行），成功分离为独立行并排布至正确自然阅读流。
4. **`synth_mixed_fonts`**:
   - PDFium 探针分类: `vector` (`valid`)，PyMuPDF 分类: `vector`
   - 判定: **Passed**。放行 3 处合成分隔空格，实质字符序列 100% 匹配。
5. **`synth_segmented_lines`**:
   - PDFium 探针分类: `vector` (`valid`)，PyMuPDF 分类: `vector`
   - 表格恢复判定: 两端均调用 `extract_wired_region` 处理断续线表格区域；由于底层线条为断续不闭合线段，双端均无法形成有效封闭表格网格，一致归因于 `no_valid_grid: empty grids or regions`。
   - 判定: **Unsupported**。
6. **`test_p27_table` (真实代表样本)**:
   - PDFium 探针分类: `vector` (`valid`)，PyMuPDF 分类: `vector`
   - 表格恢复判定: 两端均调用 `recover_cells_from_snapshot` 处理无线表格区域。PDFium 恢复出 27 行 2 列表格，PyMuPDF 恢复出 9 行 2 列表格。
   - 判定: **Failed**。由于无线表格在 Native Span 聚类为逻辑行时的启发式策略存在差异，比对器如实检出并报告了 `reading_order`、`table_structure`、`table_text` 与 `body_text` 差异，并输出了带有单元格选框的叠加对比图。
7. **`credit_p0_header` (真实代表样本)**:
   - PDFium 探针分类: `vector` (`valid`)，PyMuPDF 分类: `vector`
   - 判定: **Unsupported**。两端均进入正文阅读流组装；由于 PyMuPDF 页面包含未建模的水印/印章图元，依据规范标记为 `unsupported_element_kind`。
8. **`credit_p1_detail` (真实代表样本)**:
   - PDFium 探针分类: `vector` (`valid`)，PyMuPDF 分类: `vector`
   - 表格恢复判定: 两端均调用 `extract_wired_region` 处理顶部信贷明细有线表格，**两端均恢复出 11 行 11 列（共 121 个单元格）的有线表格，`table_structure_equal: true` 拓扑结构完全吻合**！
   - 判定: **Unsupported**。由于该页同样包含未建模印章/水印图元，标记为 `unsupported_element_kind`。

---

## 4. Markdown 输出与阅读顺序对齐

对于成功通过比对的 7 个页面，两侧解析器生成的最终 Markdown、阅读顺序与布局结构完全一致：

```markdown
<!-- synth_crop_offset.md -->
Outside of CropBox

Header in CropBox

Normal Body Text
```

```markdown
<!-- synth_rotations.md (4页) -->
Page Rotation 0 Text
---
Page Rotation 90 Text
---
Page Rotation 180 Text
---
Page Rotation 270 Text
```

- **内部空格与换行约束**: Markdown 文本未做 trim，内部空格未做不可逆折叠。
- **无回读 words 约束**: 全流程严格基于 Native Span、Line 与 Block 的逻辑拓扑构建，未再次调用 `page.get_text("words")` 进行二次重构。

---

## 5. 差异分类与诊断原则

- **BBox / 图元对象数量仅为诊断**:
  PDFium 原生 TextObject 的碎片化（拆分为逐字或逐片段存储）导致两引擎的对象绝对数量不同，且两引擎的字体测量/曲线逼近存在细微浮点差异。这些指标在 `diagnostics.json` 与 `diff.json` 中仅作追踪记录，不计入阻断门禁。
- **门禁阻断与退出码联动**:
  当矩阵中存在任何 `unsupported > 0`、`failed > 0`、`blocked_input > 0` 或 `unclassified > 0` 时，`run_behavioral_matrix.py` 严格返回退出码 1，阻断 CI 假绿。

---

## 6. 表格可视化 Overlay PNG 人工核对结论

针对配置有 `table_regions` 的代表样本，`run_behavioral_matrix` 通过 `render_table_overlays()` 分别调用底层 `hexai_pdf_parser.debug.table_visualizer.render_table_visualization()` 生成了 200 DPI 的页面级叠加示意图：

| 样本名称 | 检验项 | 人工核对结论 |
| :--- | :--- | :--- |
| `test_p27_table` | 表格选框与页面光栅化 | **选框核验完成**。两引擎均调用无线表格恢复算法，并在 Overlay PNG 中真实绘制了表格边界与单元格选框。直观反映出 PDFium 侧行切分较细（27 行）与 PyMuPDF 侧行合并较粗（9 行）的结构差异。页面光栅化底图完整（宽 841.9pt，高 595.3pt）。 |
| `credit_p1_detail` | 表格选框与页面光栅化 | **选框核验合格**。两引擎均调用有线表格恢复算法，并在 Overlay PNG 中真实绘制了 11 行 11 列的网格选框。两端单元格矩形选框与印刷实线 100% 严密贴合，文字填充边界完全吻合。 |
| `synth_segmented_lines` | 断续线表格区域 | **核验完成**。由于断续线段未闭合，两端均未识别出有效网格，Overlay 显示为裸底图视图，符合 `no_valid_grid` 预期。 |
| 两引擎图片比对 | 输入 PDF 完整性 | **合格**。渲染器在独立内存副本中绘制，源 PDF 文件 SHA-256 完全保持不变。两引擎生成的底图位图大小与内容完全一致。 |

*注：生成图片路径位于各 run 子目录下的 `pdfium_overlay.png` 与 `pymupdf_overlay.png`。*

---

## 7. 跨运行确定性数据台账 (Deterministic Hash Ledger)

以下为 11 个样本在 3 次独立原生运行中的 Canonical Result SHA-256 判定哈希：

| 样本名称 (Fixture Name) | 运行 #1 Canonical SHA-256 | 运行 #2 Canonical SHA-256 | 运行 #3 Canonical SHA-256 | 一致性 |
| :--- | :--- | :--- | :--- | :---: |
| `synth_crop_offset` | `83f5dd7faec7b1b64c2d16eeb12c615f3a02850724fba6bc7d2363dce4196b43` | `83f5dd7faec7b1b64c2d16eeb12c615f3a02850724fba6bc7d2363dce4196b43` | `83f5dd7faec7b1b64c2d16eeb12c615f3a02850724fba6bc7d2363dce4196b43` | **PASS** |
| `synth_rotations_0` | `34709dd3c9851d8e7f27d8f2402be8db127ff38d81465eadeb4fec581dc22b05` | `34709dd3c9851d8e7f27d8f2402be8db127ff38d81465eadeb4fec581dc22b05` | `34709dd3c9851d8e7f27d8f2402be8db127ff38d81465eadeb4fec581dc22b05` | **PASS** |
| `synth_rotations_90` | `bf38f026663d2d8ea9e129b451d9974c56c310a8e183b1920866253edcafcd1c` | `bf38f026663d2d8ea9e129b451d9974c56c310a8e183b1920866253edcafcd1c` | `bf38f026663d2d8ea9e129b451d9974c56c310a8e183b1920866253edcafcd1c` | **PASS** |
| `synth_rotations_180`| `eb203b1c7a7260a585bf2815deb3b05934d16efabbc0ef74827fb023825a81ea` | `eb203b1c7a7260a585bf2815deb3b05934d16efabbc0ef74827fb023825a81ea` | `eb203b1c7a7260a585bf2815deb3b05934d16efabbc0ef74827fb023825a81ea` | **PASS** |
| `synth_rotations_270`| `6e53b2c04854e37438c8913517e004d5e4cf7426c906ca1e916a2fce8e307831` | `6e53b2c04854e37438c8913517e004d5e4cf7426c906ca1e916a2fce8e307831` | `6e53b2c04854e37438c8913517e004d5e4cf7426c906ca1e916a2fce8e307831` | **PASS** |
| `synth_invisible_text`| `6695d7e622af171a39dbf7597043cef14adb8b2df9d64ba98c4cdfc25e3e5dc0` | `6695d7e622af171a39dbf7597043cef14adb8b2df9d64ba98c4cdfc25e3e5dc0` | `6695d7e622af171a39dbf7597043cef14adb8b2df9d64ba98c4cdfc25e3e5dc0` | **PASS** |
| `synth_mixed_fonts` | `494d9ad1bb03d72187e042c3454fa4c141a694e3a6df3f4645c3d48dcc666d2d` | `494d9ad1bb03d72187e042c3454fa4c141a694e3a6df3f4645c3d48dcc666d2d` | `494d9ad1bb03d72187e042c3454fa4c141a694e3a6df3f4645c3d48dcc666d2d` | **PASS** |
| `synth_segmented_lines`| `c0bc73fb04607ab4427c4d162e78dcdc2a4f4afcfa62632e21f85bda940533f2` | `c0bc73fb04607ab4427c4d162e78dcdc2a4f4afcfa62632e21f85bda940533f2` | `c0bc73fb04607ab4427c4d162e78dcdc2a4f4afcfa62632e21f85bda940533f2` | **PASS** |
| `test_p27_table` | `7c9b0204e3c278b782694d982da979cb9f09d14c92ec0389c9e869dad18ff49e` | `7c9b0204e3c278b782694d982da979cb9f09d14c92ec0389c9e869dad18ff49e` | `7c9b0204e3c278b782694d982da979cb9f09d14c92ec0389c9e869dad18ff49e` | **PASS** |
| `credit_p0_header` | `dd5a0c77fc94fb8cdaaafb3192032c9609acac7f5e9c09463e1ac01681e7adda` | `dd5a0c77fc94fb8cdaaafb3192032c9609acac7f5e9c09463e1ac01681e7adda` | `dd5a0c77fc94fb8cdaaafb3192032c9609acac7f5e9c09463e1ac01681e7adda` | **PASS** |
| `credit_p1_detail` | `f8e03dcc09ee45704d99d404890851a1f91dd26ec5e102796c4420dd2b782094` | `f8e03dcc09ee45704d99d404890851a1f91dd26ec5e102796c4420dd2b782094` | `f8e03dcc09ee45704d99d404890851a1f91dd26ec5e102796c4420dd2b782094` | **PASS** |

### 输入文件 SHA-256 溯源存证

- `synth_crop_offset.pdf`: `ec79342983afad18f6ecd80b56f85c50dd3164283585590e300aa2185b3f9639`
- `synth_rotations.pdf`: `a55204bd060386454d4eef4250af81604fe4070eb859f1af4646154fef23636b`
- `synth_invisible_text.pdf`: `26df94ae3eef27fffa24ae4263f8675f6fdb4715895cc3b0b35c3dded661ec9a`
- `synth_mixed_fonts.pdf`: `c52c51c441a7fc29029e0458fbc63b962069cc66a4f9fd38c32acfd7c97932cb`
- `synth_segmented_lines.pdf`: `1d8cab5eb1a74408a58c3ab5752fcefcc1ccfb0a813da847c82c76c85a01efff`
- `test.pdf`: `9d910b7b6a78fe2ccae1345c8651ca2e592d83b04bc2705f51d611ec0e1545a8`
- `征信解析样例.pdf`: `c5ca492db2158913cde305efd8b4e9f41ba27d26c7b13bc9a9ae1acedda81a60`

---

## 8. 验收结论

1. **确定性达标**: PDFium 原生提取链路、PageSnapshotDto 转换与影子比对在 3 次重复执行中达到 100% 确定性哈希一致（`all_equal: true`）。
2. **门禁机制完备且退出码有效阻断**: 矩阵脚本与分类门禁已将 `unsupported` 和 `failed` 均纳入退出码阻断（返回 1），杜绝了 CI 假绿。
3. **表格与正文恢复真实激活**:
   - `credit_p1_detail` 有线表格双端恢复出的 11x11 网格结构完全吻合（`table_structure_equal: true`）；
   - `test_p27_table` 无线表格真实运行两端算法，暴露了行切分启发式算法差异；
   - `synth_invisible_text` 成功实现阅读顺序与 Markdown 完全对齐。
4. **交付规范严格达标**: 代码严格局限在 `tools/pdfium_probe/` 目录，生产库 `src/` 与 `rust/` 零污染；`git diff --check 4d01c48..HEAD` 无空白警告；未提交的两个既有合成 PDF 原样保留。
5. **Sprint 行为验收结论**: 依据行为验收严格标准，由于真实样本存在无线表格算法差异（Failed: 1）与未建模印章图元（Unsupported: 3），当前 Sprint 2 **不能标记为行为验收全量通过**；但已成功完成隔离原型建设、双引擎影子比对、100% 确定性验证与关键门禁治理，为后续 Sprint 调优表格行聚类与印章建模奠定了可量化比对基础。
