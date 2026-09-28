# Sprint 1 实施与实测验证报告 (PDFium Probe Verification Report)

- **实施周期**: Sprint 1 (2026-09-28)
- **基线起点**: Commit `9181024`
- **实施提交**: Commit `8a958e2`、`b1cba5c`、`efd5d58`、`88d68e0` 及终局闭环提交
- **隔离分支**: `feat/pdfium-probe-sprint1`
- **隔离路径**: `d:\codes\PDFLayoutParser\.worktrees\feat-pdfium-probe-sprint1`
- **探针工程**: `tools/pdfium_probe/` (完全独立 Cargo.toml，不污染根工作区)
- **终局验收结论**: **探针工程建设与差分器严格加固全面完成；5 个真实代表页矢量路径（888/888）在当前比较模型下全部拓扑匹配；三次重复运行规范化 JSON 哈希 100% 确定性稳定；文本 Snapshot 等价门禁彻底失败（合格率仅 0.4%）；验收不通过；严禁接入表格恢复算法；分支封存，绝不合并至主线。**

---

## 一、生产环境与代码红线核验（100% 达标）

1. **生产构建零污染**：
   - 根目录 `Cargo.toml` 保持纯净，未引入任何 PDFium 依赖，未注册 `tools/pdfium_probe` 成员；
   - 根目录执行 `cargo check` 正常通过，零编译阻断。
2. **生产算法文件零修改**：
   - `rust/wireless_structure.rs`、`rust/wired.rs`、`rust/native_span.rs`、`rust/types.rs` 等所有生产核心算法文件代码修改量严格为 **0**。
3. **探针工程独立与质量保障**：
   - 探针工程位于 `tools/pdfium_probe/`，拥有独立工作区配置与独立 Cargo.toml；
   - `cargo check` 实现 **0 警告、0 错误**；
   - `cargo test` 自动化单元测试 5 项全部通过（100% PASS）；
   - 探针启动前自动核验动态库 SHA-256，杜绝静默版本漂移。
4. **多平台元数据实测核验 (`manifest.json`)**：
   - 锁定官方 `bblanchon/pdfium-binaries` Release `chromium/8066`；
   - Windows x64：本地完成压缩包与解压动态库的双重 SHA-256 实测核验；
   - Linux x64 / macOS arm64 / macOS x64：完成官方发布源压缩包流式 SHA-256 核验并在 manifest 中明确标注验证状态；
   - 提供 `scripts/download_pdfium.py` 实现多平台自动下载与确定性哈希核验。

---

## 二、来源凭证诚实性改造与契约命名（解决阻断问题）

### 1. 消除伪造三元组，重构 `ProvenanceSidecar`
- **历史问题**：此前代码将探针提取的每个 Span 的 `source_position` 固定硬编码为 `[0, 0, order]`，冒充 PyMuPDF 的 `[block_idx, line_idx, span_idx]` 来源凭据，违反诚实性原则。
- **重构方案**：彻底移除伪造的 `source_position`，引入独立 Sidecar 凭据结构：
  ```rust
  #[derive(Debug, Clone, Serialize, Deserialize)]
  pub struct ProvenanceSidecar {
      pub page_index: usize,
      pub pdfium_object_index: usize,
      pub character_count: usize,
      pub is_derived: bool,
      pub derived_block: Option<usize>,
      pub derived_line: Option<usize>,
  }
  ```
  探针生成的每一个原子 TextObject 均诚实记录其在 PDFium 中的原始对象索引与字符数量，并显式标注 `is_derived: false`、`derived_block: None`、`derived_line: None`，绝不虚构块/行层级信息。

### 2. 输出结构命名重构与 Schema 版本标注（拒绝冒充）
- 探针数据结构明确重构为 `PdfiumRawSnapshot`、`PdfiumRawPage`、`PdfiumRawSpan` 及 `PdfiumRawDrawing`；
- 输出 JSON 顶部显式标注：
  ```json
  "schema_version": "pdfium_raw_snapshot_v1.0",
  "generator": "pdfium_probe_0.1.0"
  ```
- 严格杜绝冒充生产环境的 `PageSnapshotDto`，防止未经聚合验证的裸图元被下游错误反序列化接入。

### 3. 空白保留与隐藏文本提取
- **空白保留**：移除 `.trim()` 操作，完整保留包含空格的原生 TextObject 字符串；
- **渲染模式提取**：调用 `text_obj.render_mode()`，识别 `PdfPageTextRenderMode::Invisible`（PDF 规范模式 3）及其他渲染模式；
- **隐藏文本标记**：在 Span 级别记录 `render_mode: u8` 和 `is_invisible: bool`，在页面级别记录 `has_invisible_text: bool`；
- **差分器对齐**：比较器同步提取并核验双方的 `render_mode` 及隐藏文字标记。

---

## 三、旋转与坐标契约：PyMuPDF 未旋转坐标系科学实测

### 1. 坐标系真相推导与实测证据
在对包含 0°、90°、180°、270° 旋转的合成样本（`synth_rotations.pdf`）以及财报横版表格（`test_p27_table.pdf`，页面自身包含 90° 旋转）进行深度调试后，确立了以下科学事实：
1. **PyMuPDF `rawdict` 的几何坐标本质**：
   - 实测证明：PyMuPDF 的 `page.get_text("rawdict")` 与 `page.get_drawings()` 返回的所有图元 BBox 与点坐标，**默认全部处于未旋转的页面局部坐标系（Unrotated Page Space）**，根本不会随着 `page.rotation` 旋转轴向！
   - 现有的生产端 Rust 算法库 `collect_native_spans_from_rawdict` 在消费 `rawdict` 时，直接处理的就是该未旋转局部坐标系。
2. **探针坐标契约对齐**：
   - 探针 `transform_point_to_page_coords` 将 PDF 原始左下角原点（Bottom-Left）正确翻转为左上角原点（Top-Left）：`[x, page_height - y]`；
   - 探针同时实现了视口仿射变换 `transform_point_to_viewport`（供旋转渲染场景使用），并在自动化单元测试中验证了 0°/90°/180°/270° 四角映射的数学一致性；
   - 当探针保持未旋转局部坐标系契约时，`synth_rotations.pdf` 的 4 个页面（0°、90°、180°、270°）与基准的 BBox Delta **完全恒定为 4.984 pt**，彻底排除了坐标系轴向错乱的假象。

---

## 四、矢量线段（Drawings）容差体系与真实样本实测

### 1. 矢量线段容差体系定义与浮点精度红线
比较器确立了以下明确的判定容差与精度规则：
*   **外包围盒容差 (`rect_tol`)**: $\le 0.5 \text{ pt}$
*   **线段端点容差 (`point_tol`)**: $\le 0.5 \text{ pt}$（支持端点正反双向判定）
*   **线宽容差 (`width_tol`)**: $\le 0.95 \text{ pt}$（以桥接 PDFium 真实发丝线 0.05 pt 与 MuPDF 默认值 1.0 pt）
*   **浮点门禁精度原则（严禁舍入伪通过）**：门禁判定一律基于未经舍入的原始浮点数绝对差（`raw_width_delta = abs(b_w - p_w)`、`raw_max_bbox_delta`），杜绝因预先四舍五入截断产生的假绿灯；`round(..., 4)` 仅用于生成 JSON 报告与终端展示。
*   **数据缺失显式标记**：若图元一侧包含线宽而另一侧缺失，直接标记为 `WIDTH_DATA_MISSING` 状态，严禁将缺失值伪装为 0 差异。
*   **矩形语义等价判定**: PyMuPDF 单条 `'re'` 指令与 PDFium 4 段闭合 `'l'` 线段在 Rect 吻合且线宽满足 `width_tol` 时判定为语义等价 (`MATCHED_SEMANTIC_RECT`)。

### 2. 5 个真实代表页实测表现（888 / 888 拓扑匹配）
在探针为 `path_obj.segments()` 接入 `path_obj.matrix()?` 矩阵变换后，方案冻结规定的全部 5 个真实代表页面的 888 条线段在上述容差内全部匹配：
*   **个人征信表头页 (`credit_p0_header`)**: Base 429 条 vs Probe 429 条，**匹配 429 / 429 (100%)**；Max Rect Delta = **0.0001 pt**，Max Point Delta = **0.0 pt**，Max Width Delta = **0.0 pt**；
*   **个人征信明细表格页 (`credit_p1_detail`)**: Base 436 条 vs Probe 436 条，**匹配 436 / 436 (100%)**；Max Rect Delta = **0.0 pt**，Max Point Delta = **0.0 pt**，Max Width Delta = **0.0 pt**；
*   **财报横版表格页 (`test_p27_table`)**: Base 21 条 vs Probe 21 条，**匹配 21 / 21 (100%)**；Max Rect Delta = **0.0 pt**，Max Point Delta = **0.0 pt**；
*   **财报封面 (`test_p0_cover`)**: Base 1 条 vs Probe 1 条，**匹配 1 / 1 (100%)**；Max Rect Delta = **0.0 pt**；
*   **财报目录 (`test_p1_toc`)**: Base 1 条 vs Probe 1 条，**匹配 1 / 1 (100%)**；Max Rect Delta = **0.0 pt**。

> **结论范围限定**：上述 `888 / 888` 匹配结论**仅代表当前 5 个真实代表页面、当前 chromium/8066 动态库及当前比较器模型下有效**。它不代表涵盖所有复杂商业 PDF 类型的路径（如复杂 Bezier 曲线、Clip 裁剪路径或混合透明度）。

---

## 五、三次运行确定性规范化哈希核验（100% 确定性）

针对 5 个合成样本与 5 个真实代表页（共 10 个样本），运行脚本 `scripts/verify_deterministic_hashes.py` 执行了 3 次端到端独立的探针二进制提取，并对生成的规范化 JSON 计算 SHA-256。

- **核验台账文件**: [DETERMINISTIC_HASH_LEDGER.json](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/DETERMINISTIC_HASH_LEDGER.json)
- **核验结果**: **全部 10 个样本在 3 次提取运行中产生的规范化 JSON 哈希 100% 相同，没有任何漂移**。

```text
================================================================================
           Sprint 1 Deterministic Triple-Run Hash Verification Summary
================================================================================
  [real] credit_p0_header       : PASS (100% Identical) -> 1fdd7a66924318cf0d4f8510fcf6a621...
  [real] credit_p1_detail       : PASS (100% Identical) -> f9423a4007be21eabe6d543fa42b3864...
  [real] test_p0_cover          : PASS (100% Identical) -> bae808a45b96a912e27538a0f71a71c8...
  [real] test_p1_toc            : PASS (100% Identical) -> a1c347c0bdfd996571007c37796ca64a...
  [real] test_p27_table         : PASS (100% Identical) -> cc0f967221f4651301721ee717d2193f...
  [synthetic] synth_crop_offset : PASS (100% Identical) -> 62e97f252c34c2c2b508afc1c9b64a9b...
  [synthetic] synth_invisible   : PASS (100% Identical) -> 9d4bad68610d3daa36cd725ca67a9c13...
  [synthetic] synth_mixed_fonts : PASS (100% Identical) -> 6648d414138efa7754461ac2b0a94dd7...
  [synthetic] synth_rotations   : PASS (100% Identical) -> 28001b4cbee38e654e0ce9a3dc6feda7...
  [synthetic] synth_segmented   : PASS (100% Identical) -> 281daa3ad75940bf566ee32822f6e66d...
STATUS: PASSED (All 10 sample outputs exhibit 100% identical SHA-256 hashes across 3 runs)
```

---

## 六、比较器严格门禁漏洞封堵与靶向实测（CI 阻断拦截）

比较器经过全面加固，彻底封堵了历史漏洞：
1. **缺失文件封堵**：若 Probe JSON 文件缺失，标记 `PROBE_FILE_MISSING`，严禁静默跳过，直接记入门禁违约；
2. **旋转字段核实**：修复原代码误读基准旋转 `bp["rotation"]` 的笔误，正确核对 `pp["rotation"]`；
3. **多余图元惩罚**：将多余未映射图元 `BASE_MISSING` 纳入质量门禁失败判定；
4. **元数据全项审查**：增加 `page_count`、`crop_box`、`media_box` 严格一致性比对。

### 靶向合成测试实测表现 (Exit Code: 1，检出 19 项违规违约)

| 合成测试用例 | 靶向机制 | Base Spans | Probe Spans | 候选匹配 | 字符相符 | BBox达标 | 最终通过 | 丢失数 | 逆序数 | Max BBox Delta | Drawings 匹配 | 门禁判定 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `synth_crop_offset.pdf` | CropBox 视口平移 | 3 | 3 | 3 | 3 | **0** | **0** | 0 | 0 | 4.858 pt | 0 / 0 | **FAIL** (超差) |
| `synth_invisible_text.pdf` | 不可见/重叠文字 | 4 | 4 | 3 | 3 | **0** | **0** | 1 | 0 | 5.744 pt | 0 / 0 | **FAIL** (空格形态/超差) |
| `synth_mixed_fonts.pdf` | 混排与字号突变 | 5 | 4 | 1 | 1 | **0** | **0** | **4** | 0 | 3.949 pt | 0 / 0 | **FAIL** (缺Span+超差) |
| `synth_rotations.pdf` | 0°/90°/180°/270° 旋转 | 4 | 4 | 4 | 4 | **0** | **0** | 0 | 0 | 4.984 pt | 0 / 0 | **FAIL** (超差) |
| `synth_segmented_lines.pdf` | 连续/断续线段网格 | 2 | 2 | 1 | 1 | **0** | **0** | 1 | 0 | 4.164 pt | **6 / 6 (100%)** | **FAIL** (文本超差) |

---

## 七、真实代表页差分实测数据（摸底诊断分层指标）

```text
┌───────────────────────────────── 5 个真实样本分层指标汇总 ───────────────────────────────┐
│                                                                                       │
│  1. 页面几何 (Geometry): 宽高与旋转全部 100% 严丝合缝                                  │
│                                                                                       │
│  2. 矢量图元 (Drawings) 拓扑: 888 / 888 满足 (rect_tol=0.5, point_tol=0.5, width_tol=0.95)│
│                                                                                       │
│  3. 文本图元分层审计 (Text Grain & Quality Gate Breakdown):                            │
│     * 基准 Span 总数 (Total Base Spans)       : 518                                   │
│     * 探针图元总数 (Total Probe Objects)     : 2867 (粒度膨胀比: 5.53x)               │
│     * 候选文本匹配 (Candidate Matches)        : 58  (11.2%)                           │
│     * 字符内容相符 (Chars Verified)           : 58                                    │
│     * BBox 门禁达标 (BBox Gate Passed)        : 2   (0.4%)                            │
│     * 最终完全接收 (Fully Accepted Spans)     : 2   (0.4% - 门禁彻底失败)              │
│     * 缺失基准 Span (Missing Base Spans)      : 460 (88.8%)                           │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

数据清晰证实：探针在未经词级聚合的情况下，输出的是原生的原子 TextObject（呈现高达 5.53x 的图元碎裂），且 BBox 处于字形边界（GlyphBox）而非行级边界（LineBox），**最终合格率仅为 0.4%，文本输入契约等价门禁彻底失败**。

---

## 八、Sprint 1 终局闭环与分支封存规范

1. **Sprint 1 终局定性**：
   - 探针工程构建完成；
   - 差分框架与严格门禁全面健全；
   - 矢量图元在当前 5 个样本下拓扑匹配；
   - 规范化哈希确定性核验 100% 通过；
   - **文本输入契约验证彻底失败，验收不通过**；
   - **严禁接入 `wireless_structure`、`wired`、`native_span` 等任何生产表格恢复算法**。
2. **分支封存操作**：
   - 当前工作区 `feat/pdfium-probe-sprint1` 分支就地封存，保留完整的差分台账、测试用例与验证报告作为审计证据；
   - 绝对不合并至 `feature-dev` 或主干分支；
   - 后续如需开展 Span 聚合研究，将在独立的只读实验分支中探索，并继续遵循非侵入式原则。
