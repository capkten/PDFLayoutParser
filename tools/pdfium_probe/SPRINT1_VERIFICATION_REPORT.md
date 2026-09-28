# Sprint 1 实施与实测验证报告 (PDFium Probe Verification Report)

- **实施周期**: Sprint 1 (2026-09-28)
- **基线起点**: Commit `9181024`
- **实施提交**: Commit `8a958e2`、`b1cba5c`、`efd5d58`、`88d68e0`、`b53e89f` 及终局闭环提交
- **隔离分支**: `feat/pdfium-probe-sprint1`
- **隔离路径**: `d:\codes\PDFLayoutParser\.worktrees\feat-pdfium-probe-sprint1`
- **探针工程**: `tools/pdfium_probe/` (完全独立 Cargo.toml，不污染根工作区)
- **终局验收结论**: **PDFium raw probe 与差分基础设施全面完成；5 个真实代表页面的几何线段（888 / 888）在当前几何拓扑比较模型下全部匹配；10 个样本的三次重复提取规范化 JSON 哈希 100% 确定性稳定；真实样本源 PDF 与 native library 完整入账；严格文本 Snapshot 等价门禁彻底失败（合格率仅 0.4%）；验收判定为不通过；严禁合并到 `feature-dev`，严禁接入生产表格恢复算法；本分支就地封存。**

---

## 一、生产环境与代码红线核验（100% 达标）

1. **生产构建零污染**：
   - 根目录 `Cargo.toml` 保持纯净，未引入任何 PDFium 依赖，未注册 `tools/pdfium_probe` 成员；
   - 根目录执行 `cargo check` 正常通过（耗时 0.12s），零编译阻断。
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

## 二、来源凭证 (Provenance) 与契约诚实性加固

### 1. 彻底消除伪造三元组，重构 `ProvenanceSidecar`
- **历史问题**：此前代码将探针提取的每个 Span 的 `source_position` 伪造为 `[0, 0, order]`，且缺乏字符级范围信息。
- **重构方案**：在 [`main.rs`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/src/main.rs) 中重构为独立凭据结构：
  ```rust
  #[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
  pub struct ProvenanceSidecar {
      pub page_index: usize,
      pub pdfium_object_index: usize, // 在 page.objects() 中的真实原始序号
      pub character_count: usize,
      pub char_start_index: usize,    // TextObject 内部起始字符偏移
      pub char_end_index: usize,      // TextObject 内部结束字符偏移
      pub char_indices: Vec<usize>,   // 每个字符在 TextObject 内的局部序号序列
      pub is_derived: bool,           // 原生探针输出固定为 false
      pub derived_block: Option<i64>, // 未做 block 聚类，诚实标记为 None
      pub derived_line: Option<i64>,  // 未做 line 聚类，诚实标记为 None
  }
  ```
  在 `CharInfo` 中补充 `char_index: usize`，记录字符在原子 TextObject 内的局部位置。
- **诚实范围限定**：当前探针记录的是原子 TextObject 内部的字符偏移与对象索引，尚未构建跨 TextObject 全局统一的页面级字符流水号（该工作需在后续的只读聚合实验中推进）。

### 2. 移除人为伪造的 `flags` 掩码
- 针对此前代码将不可见文本的人为硬编码 `let flags: i64 = if is_invisible { 1 << 6 } else { 0 };`（64），现已将 `SpanInfo.flags` 类型定义为 `Option<i64>`，在 PDFium raw snapshot 中诚实赋值为 `None`，绝不虚构 PyMuPDF 风格的位标志。

### 3. 输出结构命名重构与 Schema 版本标注（拒绝冒充）
- 探针数据结构明确命名为 `PdfiumRawSnapshot`、`PdfiumRawPage`、`PdfiumRawSpan` 及 `PdfiumRawDrawing`；
- 输出 JSON 顶部显式标注：
  ```json
  "schema_version": "pdfium_raw_snapshot_v1.0",
  "generator": "pdfium_probe_0.1.0"
  ```
- 严格杜绝冒充生产环境的 `PageSnapshotDto`，防止未经聚合验证的裸图元被下游错误反序列化接入。

---

## 三、旋转与坐标契约：PyMuPDF 未旋转坐标系科学实测

### 1. 坐标系真相推导与实测证据
在对包含 0°、90°、180°、270° 旋转的合成样本（`synth_rotations.pdf`）以及财报横版表格（`test_p27_table.pdf`，页面自身包含 90° 旋转）进行深度调试后，确立了以下科学事实：
1. **PyMuPDF `rawdict` 的几何坐标本质**：
   - 实测证明：PyMuPDF 的 `page.get_text("rawdict")` 与 `page.get_drawings()` 返回的所有图元 BBox 与点坐标，**默认全部处于未旋转的页面局部坐标系（Unrotated Page Space）**，根本不会随着 `page.rotation` 旋转轴向；
   - 现有的生产端 Rust 算法库 `collect_native_spans_from_rawdict` 在消费 `rawdict` 时，直接处理的就是该未旋转局部坐标系。
2. **探针坐标契约对齐**：
   - 探针 `transform_point_to_page_coords` 将 PDF 原始左下角原点（Bottom-Left）正确翻转为左上角原点（Top-Left）：`[x, page_height - y]`；
   - 探针同时实现了视口仿射变换 `transform_point_to_viewport`（供旋转渲染场景使用），并在自动化单元测试中验证了 0°/90°/180°/270° 四角映射的数学一致性；
   - 当探针保持未旋转局部坐标系契约时，`synth_rotations.pdf` 的 4 个页面（0°、90°、180°、270°）与基准的 BBox Delta **完全恒定为 4.984 pt**，彻底排除了坐标系轴向错乱的假象。

---

## 四、矢量线段（Drawings）容差体系与真实样本实测范围限定

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

### 3. Drawing 结论范围的严格限定（绝不说满）
> **重要声明**：上述 `888 / 888` 匹配结论**仅代表当前 5 个代表页在当前几何与线宽拓扑模型下匹配**。
> **它不代表完整 Drawing 契约等效**，具体边界如下：
> 1. 探针中 Drawing 的 `color` 与 `fill` 字段目前为 `None`，比较器尚未比对颜色和填充；
> 2. 当前比较器尚未覆盖三次贝塞尔曲线（Bezier）、剪裁蒙版（Clip Path）、复合 Path 剪切或混合透明度（Alpha/Blending）；
> 3. 不能仅凭几何线段匹配推断出复杂视觉设计和阴影背景等特性已经等效。

---

## 五、三次独立运行确定性哈希台账（真实输入与 Native Library 全量入账）

运行 [`verify_deterministic_hashes.py`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/scripts/verify_deterministic_hashes.py)，全面落实了白名单校验与 stale JSON 清理机制，对 5 个合成样本与 5 个真实代表页（共 10 个样本）执行了 3 次端到端独立的探针二进制提取，并对紧凑规范化 JSON（键排序、紧凑分隔符、排除时间戳）计算 SHA-256。

- **核验台账文件**: [`DETERMINISTIC_HASH_LEDGER.json`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/DETERMINISTIC_HASH_LEDGER.json)
- **环境与依赖 Provenance**:
  - `native_library_path`: `native/win-x64/pdfium.dll`
  - `native_library_sha256`: `d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b`
  - `pdfium_release_tag`: `chromium/8066`
- **输入源 PDF 真实 SHA-256 完整录入**（彻底清零 `external_source`）：
  - `test.pdf` (p0, p1, p27): `9d910b7b6a78fe2ccae1345c8651ca2e592d83b04bc2705f51d611ec0e1545a8`
  - `征信解析样例.pdf` (p0, p1): `c5ca492db2158913cde305efd8b4e9f41ba27d26c7b13bc9a9ae1acedda81a60`
- **核验结论**: **全部 10 个样本在 3 次提取运行中产生的规范化 JSON 哈希 100% 相同，没有任何漂移**。

```text
================================================================================
           Sprint 1 Deterministic Triple-Run Hash Verification Summary
================================================================================
  [real] credit_p0_header (p0)  : PASS (100% Identical) -> 6848948d2dcbd0471fab5dc391bb...
  [real] credit_p1_detail (p1)  : PASS (100% Identical) -> 4539c584542aa682d8853a956b96...
  [real] test_p0_cover (p0)     : PASS (100% Identical) -> fee3c1157e6e27f7d3faa974451d...
  [real] test_p1_toc (p1)       : PASS (100% Identical) -> 7e2bb120f8a1e71c30dd73eb8df7...
  [real] test_p27_table (p27)   : PASS (100% Identical) -> 5a670557c712d56c4505bb1d06f1...
  [synthetic] synth_crop_offset : PASS (100% Identical) -> 200899b7ac72a1774237a359b6d7...
  [synthetic] synth_invisible   : PASS (100% Identical) -> 13159cbcb5a8708a8bdc2eaa44dd...
  [synthetic] synth_mixed_fonts : PASS (100% Identical) -> 33556724db756f0a2be09551e88d...
  [synthetic] synth_rotations   : PASS (100% Identical) -> 2b8a2b9b9eae70c65eae10533f5a...
  [synthetic] synth_segmented   : PASS (100% Identical) -> ba291fdecc5d83a45695af9e0ad5...
STATUS: PASSED (All 10 sample outputs exhibit 100% identical SHA-256 hashes across 3 runs)
```

---

## 六、比较器严格门禁落地（包含 Schema、页索引、隐藏文本与 Provenance）

比较器经过全面加固，将此前仅作报告记录的字段真正列为**门禁阻断违例条件**：
1. **Schema 版本检查**：`probe_schema` 必须严格等于 `"pdfium_raw_snapshot_v1.0"`；
2. **物理页码对齐**：基准导出脚本修复了硬编码 `0` 的缺陷，如实输出真实物理页码；比较器严格校验 `bp["page_index"] == pp["page_index"]`；
3. **页面级隐藏标记**：严格校验 `bp["has_invisible_text"] == pp["has_invisible_text"]`；
4. **Span 级隐藏文本与渲染模式**：匹配候选对象的 `is_invisible` 状态必须一致，若不一致直接判定为 `INVISIBLE_MISMATCH` 并记入门禁违约；
5. **来源凭证完整性**：匹配候选对象的 `provenance` 必须包含合法的 `pdfium_object_index`、`character_count`、`char_start_index`、`char_end_index` 且 `is_derived == False`，否则判定为 `PROVENANCE_INVALID`；
6. **多余图元惩罚**：将多余未映射图元 `BASE_MISSING` 纳入质量门禁失败判定。

### 靶向合成测试实测表现 (Exit Code: 1，检出 21 项门禁违规)

```text
STATUS: FAILED (21 gate violations found)
  1. synth_crop_offset.pdf p0: Max BBox Delta 4.858 pt > threshold 0.5 pt
  2. synth_invisible_text.pdf p0: Page has_invisible_text mismatch (Base=False vs Probe=True)
  3. synth_invisible_text.pdf p0: Invisible status mismatch in span 'Invisible OCR Text Layer' (Base=False vs Probe=True)
  4. synth_invisible_text.pdf p0: Non-empty span missing in probe: 'Overlapped Text Base'
  5. synth_invisible_text.pdf p0: Extra unmapped probe span/TextObject: 'Overlapped Text Base '
  6. synth_invisible_text.pdf p0: Max BBox Delta 5.744 pt > threshold 0.5 pt
  7. synth_mixed_fonts.pdf p0: Non-empty span missing in probe: 'Project Revenue:'
  8. synth_mixed_fonts.pdf p0: Non-empty span missing in probe: '1'
  9. synth_mixed_fonts.pdf p0: Whitespace span missing in probe: ' ' (Base span count=5 vs Probe=4)
  10. synth_mixed_fonts.pdf p0: Non-empty span missing in probe: '主要业务'
  11. synth_mixed_fonts.pdf p0: Extra unmapped probe span/TextObject: 'Project Revenue: '
  12. synth_mixed_fonts.pdf p0: Extra unmapped probe span/TextObject: '1 '
  13. synth_mixed_fonts.pdf p0: Extra unmapped probe span/TextObject: '主要业务 '
  14. synth_mixed_fonts.pdf p0: Max BBox Delta 3.949 pt > threshold 0.5 pt
  15. synth_rotations.pdf p0: Max BBox Delta 4.984 pt > threshold 0.5 pt
  16. synth_rotations.pdf p1: Max BBox Delta 4.984 pt > threshold 0.5 pt
  17. synth_rotations.pdf p2: Max BBox Delta 4.984 pt > threshold 0.5 pt
  18. synth_rotations.pdf p3: Max BBox Delta 4.984 pt > threshold 0.5 pt
  19. synth_segmented_lines.pdf p0: Non-empty span missing in probe: 'Table Cell 1'
  20. synth_segmented_lines.pdf p0: Extra unmapped probe span/TextObject: 'Table Cell 1 '
  21. synth_segmented_lines.pdf p0: Max BBox Delta 4.164 pt > threshold 0.5 pt
```

门禁已真正捕捉到不可见文本标记与行为的不一致，以非零退出码严格拦截。

---

## 七、真实代表页差分实测数据与深层归因

```text
┌───────────────────────────────── 5 个真实样本分层指标汇总 ───────────────────────────────┐
│                                                                                       │
│  1. 页面几何 (Geometry): 宽高、旋转及物理页索引全部 100% 严丝合缝                      │
│                                                                                       │
│  2. 矢量图元 (Drawings) 拓扑: 888 / 888 满足 (rect_tol=0.5, point_tol=0.5, width_tol=0.95)│
│     - credit_p0_header (征信报告头) : 429 / 429 匹配 (Max Rect: 0.0001 pt, Width: 0.0 pt)│
│     - credit_p1_detail (征信明细表) : 436 / 436 匹配 (Max Rect: 0.0 pt, Width: 0.0 pt)    │
│     - test_p27_table   (财报横版表) :  21 /  21 匹配 (Max Rect: 0.0 pt, Width: 0.95 pt)   │
│     - test_p0_cover    (财报封面页) :   1 /   1 匹配 (Max Rect: 0.0 pt, Width: 0.95 pt)   │
│     - test_p1_toc      (财报目录页) :   1 /   1 匹配 (Max Rect: 0.0 pt, Width: 0.95 pt)   │
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

### 真实文本差异深层归因（纠正片面归因）
实测中观察到：
- `credit_p1_detail` 最大 BBox 误差高达 **760.36 pt**；
- `credit_p0_header` 最大 BBox 误差高达 **415.06 pt**。

**科学归因**：
1. **绝非单一的 5 pt 字盒差异**：合成样本中字符 1:1 对应的 BBox 差异确实稳定在 4~5 pt（字形边界 GlyphBox 与行边界 LineBox 的差），但真实样本中高达数百 pt 的偏差有着截然不同的原因；
2. **贪心匹配与跨行错配**：由于 TextObject 严重碎裂（2867 个裸图元 vs 518 个基准 Span，膨胀比达 5.53x），大量孤立的短文本（如标点、单个数字、日期片段如 `'/'`、`'-'`、`'2025'`）在全页多次出现；当前 1:1 贪心匹配算法将不同物理行、不同表格单元格中的同名文本误配在了一起，产生了数百 pt 的垂直几何跨度；
3. **Sprint 2 实施建议**：在开展只读 Span 聚合实验前，必须先改进匹配诊断工具（基于位置局部性或多对一连续性配对），避免将算法错配假象误判为几何漂移。

---

## 八、Sprint 1 终局闭环与分支封存操作

1. **Sprint 1 终局定性**：
   - 探针工程与差分基础设施建设完成；
   - 严格文本输入等价门禁彻底失败；
   - 绘图匹配结论严格限定于当前 5 个样本与几何模型；
   - 验收判定为不通过；
   - **严禁接入 `wireless_structure`、`wired`、`native_span` 等任何生产表格恢复算法**。
2. **分支封存操作**：
   - 当前工作区 `feat/pdfium-probe-sprint1` 分支就地封存，保留完整的差分台账、测试用例与验证报告作为审计证据；
   - **绝对不合并至 `feature-dev` 或主干分支**；
   - 后续任何 Span 聚合实验均在新的独立实验分支中开展。
