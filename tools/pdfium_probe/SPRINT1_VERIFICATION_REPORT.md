# Sprint 1 实施与实测验证报告 (PDFium Probe Verification Report)

- **实施周期**: Sprint 1 (2026-09-28)
- **基线起点**: Commit `9181024`
- **实施提交**: Commit `8a958e2`、`b1cba5c`（以及本轮度规深化提交）
- **隔离分支**: `feat/pdfium-probe-sprint1`
- **隔离路径**: `d:\codes\PDFLayoutParser\.worktrees\feat-pdfium-probe-sprint1`
- **探针工程**: `tools/pdfium_probe/` (完全独立 Cargo.toml，不污染根工作区)
- **最终验收结论**: **探针工程建设完成；差分器分层度规健全；4 个真实代表页矢量路径在当前比较模型下全部匹配；文本 Snapshot 等价门禁仍失败；严禁接入表格恢复算法。**

---

## 一、生产环境与代码红线核验（100% 达标）

1. **生产构建零污染**：
   - 根目录 `Cargo.toml` 保持干净，未引入 PDFium 依赖，未注册 `tools/pdfium_probe` 成员；
   - 根目录执行 `cargo check` 正常通过（0.09s），零编译阻断。
2. **生产算法文件零修改**：
   - `rust/wireless_structure.rs`、`rust/wired.rs`、`rust/native_span.rs`、`rust/types.rs` 等所有算法文件代码修改量严格为 **0**。
3. **探针工程独立与警告清理**：
   - 探针工程位于 `tools/pdfium_probe/`，拥有独立的 Cargo.toml；
   - `cargo check` 实现 **0 警告、0 错误**；
   - 探针启动前自动核验动态库 SHA-256，杜绝静默版本漂移。
4. **多平台元数据实测核验 (`manifest.json`)**：
   - 锁定官方 `bblanchon/pdfium-binaries` Release `chromium/8066`；
   - Windows x64：本地完成压缩包与解压动态库的双重 SHA-256 实测验证；
   - Linux x64 / macOS arm64 / macOS x64：完成官方发布源压缩包流式 SHA-256 核验并在 manifest 中明确标注验证状态；
   - 提供 `scripts/download_pdfium.py` 实现多平台自动下载与确定性哈希核验。

---

## 二、矢量线段（Drawings）容差体系与真实样本实测

### 1. 矢量线段容差体系定义
不同 PDF 引擎在矢量线条提取上存在浮点舍入、发丝线表示和矩形指令差异。比较器确立了以下明确的判定容差：
*   **外包围盒容差 (`rect_tol`)**: $\le 0.5 \text{ pt}$
*   **线段端点容差 (`point_tol`)**: $\le 0.5 \text{ pt}$（支持端点正反双向判定）
*   **线宽容差 (`width_tol`)**: $\le 0.95 \text{ pt}$（以桥接 PDFium 真实发丝线 0.05 pt 与 MuPDF 默认值 1.0 pt）
*   **矩形语义等价判定**: PyMuPDF 单条 `'re'` 指令与 PDFium 4 段闭合 `'l'` 线段在 Rect 吻合时判定为语义等价 (`MATCHED_SEMANTIC_RECT`)。

### 2. 真实代表页实测表现
在探针为 `path_obj.segments()` 接入 `path_obj.matrix()?` 矩阵变换后，4 个真实页面的全部 452 条线段均在上述容差内匹配：
*   **个人征信报告页 (`credit_p0_header`)**: Base 429 条 vs Probe 429 条，**匹配 429 / 429 (100%)**；Max Rect Delta = **0.0001 pt**，Max Point Delta = **0.0 pt**，Max Width Delta = **0.0 pt**（所有线宽完全一致）；
*   **财报横版表格页 (`test_p27_table`)**: Base 21 条 vs Probe 21 条，**匹配 21 / 21 (100%)**；Max Rect Delta = **0.0 pt**，Max Point Delta = **0.0 pt**；其中 20 条表格框线线宽均为 0.48 pt（$\Delta = 0.0 \text{ pt}$），仅顶部分割发丝线产生 0.95 pt 宽度差异；
*   **财报封面 (`test_p0_cover`)**: Base 1 条 vs Probe 1 条，**匹配 1 / 1 (100%)**；Max Rect Delta = **0.0 pt**；
*   **财报目录 (`test_p1_toc`)**: Base 1 条 vs Probe 1 条，**匹配 1 / 1 (100%)**；Max Rect Delta = **0.0 pt**。

### 3. 真实 Drawing 结论的严格限定（重要）
> **结论范围限定**：上述 `452 / 452` 匹配结论**仅代表当前 4 个真实代表页面、当前 chromium/8066 动态库及当前比较器模型下有效**。
> 它**不代表**：
> 1. 所有复杂商业 PDF 类型的路径均能匹配；
> 2. 三次贝塞尔曲线（Bezier）、复杂 Clip 裁剪路径、复合 Path 运算或图元透明度等特性已经对齐；
> 3. 后续若涉及更复杂的报表页面，必须补充包含曲线与裁剪路径的专门样本。

---

## 三、文本比对的分层统计机制（候选匹配 vs 门禁通过）

为杜绝将“找到了文本候选”误读为“等价通过”，比较器现已实现 5 层分离统计：
1. **Candidate Match (`candidate_match_count`)**: 找到 1:1 相同文本候选对象的基准 Span 数；
2. **Chars Verified (`char_match_count`)**: 内部逐字符文本完全相符的 Span 数；
3. **BBox Passed (`bbox_pass_count`)**: 最大 BBox 误差 $\le \text{bbox\_tol}$ (0.5 pt) 的 Span 数；
4. **Fully Accepted (`fully_accepted_count`)**: 文本、字符与 BBox 均完全达标的最终通过数；
5. **Missing Spans (`missing_count`)**: 未能找到任何对应文本候选对象的基准 Span 数。

---

## 四、靶向合成测试实测表现（未通过门禁）

在合成样本上执行严格门禁比较，检出 9 项门禁违规，门禁以退出码 `1` 拦截：

| 合成测试用例 | 靶向机制 | Base Spans | Probe Spans | 候选匹配 | 字符相符 | BBox达标 | 最终通过 | 丢失数 | 逆序数 | Max BBox Delta | Drawings 匹配 | 门禁判定 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `synth_crop_offset.pdf` | CropBox 视口平移 | 3 | 3 | 3 | 3 | **0** | **0** | 0 | 0 | 4.858 pt | 0 / 0 | **FAIL** (超差) |
| `synth_invisible_text.pdf` | 不可见/重叠文字 | 4 | 4 | 4 | 4 | **0** | **0** | 0 | 0 | 5.744 pt | 0 / 0 | **FAIL** (超差) |
| `synth_mixed_fonts.pdf` | 混排与字号突变 | 5 | 4 | 4 | 4 | **0** | **0** | **1** | 0 | 5.026 pt | 0 / 0 | **FAIL** (缺Span+超差) |
| `synth_rotations.pdf` | 0°/90°/180°/270° 旋转 | 4 | 4 | 4 | 4 | **0** | **0** | 0 | 0 | 4.984 pt | 0 / 0 | **FAIL** (超差) |
| `synth_segmented_lines.pdf` | 连续/断续线段网格 | 2 | 2 | 2 | 2 | **0** | **0** | 0 | 0 | 4.164 pt | **6 / 6 (100%)** | **FAIL** (文本超差) |

---

## 五、真实代表页差分实测数据（分层指标）

```text
┌───────────────────────────────── 真实样本分层指标汇总 ─────────────────────────────────┐
│                                                                                       │
│  1. 页面几何 (Geometry): 宽高与旋转全部 100% 严丝合缝                                  │
│                                                                                       │
│  2. 矢量图元 (Drawings) 拓扑: 452 / 452 满足 (rect_tol=0.5, point_tol=0.5, width_tol=0.95)│
│                                                                                       │
│  3. 文本图元分层审计 (Text Grain & Quality Gate Breakdown):                            │
│     * 基准 Span 总数 (Total Base Spans)       : 302                                   │
│     * 探针图元总数 (Total Probe Objects)     : 2493 (粒度膨胀比: 8.25x)               │
│     * 候选文本匹配 (Candidate Matches)        : 92  (30.5%)                           │
│     * 字符内容相符 (Chars Verified)           : 92                                    │
│     * BBox 门禁达标 (BBox Gate Passed)        : 1   (0.3%)                            │
│     * 最终完全接收 (Fully Accepted Spans)     : 1   (0.3% - 门禁彻底失败)              │
│     * 缺失基准 Span (Missing Base Spans)      : 210 (69.5%)                           │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

数据清晰证实：虽然在部分孤立字符上找到了 92 个候选，但由于 8.25 倍的图元碎裂与 LineBox/GlyphBox 垂直差，**最终合格率仅为 0.3%，门禁明确处于失败状态**。

---

## 六、Sprint 2 方向规划：只读聚合实验 (Read-Only Span Aggregator)

Sprint 2 坚定遵循**不接入生产算法**的原则，在输入适配层开展“只读聚合实验”：

### 1. 实验闭环设计
1. **输入源**：PDFium 原生原子 TextObject 集合；
2. **处理过程**：编写实验性纯 Rust 聚合器，按字符几何与连续性构建只读内存对象；
3. **输出物**：仅导出为独立的差分 JSON Snapshot，**不喂给**任何有线/无线表格算法。

### 2. 核心比对与验证的 5 大维度
*   **维度 1：字符完整性 (Character Completeness)**：验证聚合后字符总数与内容是否有丢失、重复或漏字；
*   **维度 2：来源连续性 (Source Continuity Provenance)**：在聚合产生的 DTO 中保留每个字符来源于哪一个原子 TextObject 索引；
*   **维度 3：视觉行归属与倾斜容忍 (Visual Line Attribution)**：制定基于基线 Y 坐标的动态行聚类，避免不同行汉字误聚；
*   **维度 4：差异化切分状态机**：
    - CJK 汉字：以字距与紧邻度连续成词；
    - 西文与数字：依据实际空格宽度（Space Width）显式插值空格，区分词内字符与词间间隔；
    - 标点符号：处理悬挂与贴合规则；
*   **维度 5：与现有 `NativeSpanDto` 契约兼容性**：确保生成的 DTO 字段（`bbox`、`font`、`size`、`characters`）与生产接口完全兼容。

### 3. 5 pt 垂直差异的观测性原则
*   将 5 pt 差异作为纯观测项，重点验证现有 Rust 表格算法的行聚类容差 `tol = max(2.4, size * 0.38)` 是否已经天然具备容忍能力；
*   **严禁**为了刻意将差分降到 0.5 pt 而盲目在适配器层强行扩大 BBox。

---

## 七、分支封存与交付边界

1. **分支状态**：`feat/pdfium-probe-sprint1` 分支保留为**可审计的 Sprint 1 探针与差分器加固基准**；
2. **严守主线**：严禁合并进 `feature-dev` 或主分支；
3. **二进制文件政策**：`pdfium.dll` 与真实差分 JSON 仅作为复反复验依据保留在当前隔离分支，生产主线永久保持纯文本轻量形态。
