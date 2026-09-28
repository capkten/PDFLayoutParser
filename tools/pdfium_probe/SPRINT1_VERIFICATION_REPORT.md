# Sprint 1 实施与实测验证报告 (PDFium Probe Verification Report)

- **实施周期**: Sprint 1 (2026-09-28)
- **基线起点**: Commit `9181024`
- **实施提交**: Commit `8a958e2`、`b1cba5c`、`efd5d58`、`88d68e0`、`b53e89f`、`4cc3432` 及终局闭环提交
- **隔离分支**: `feat/pdfium-probe-sprint1`
- **隔离路径**: `d:\codes\PDFLayoutParser\.worktrees\feat-pdfium-probe-sprint1`
- **探针工程**: `tools/pdfium_probe/` (完全独立 Cargo.toml，不污染根工作区)
- **终局验收结论**: **PDFium raw probe 与差分基础设施加固完成；5 个真实代表页面的几何线段（888 / 888）在当前几何拓扑比较模型下全部匹配；10 个样本的三次重复提取规范化 JSON 哈希 100% 确定性稳定；真实样本源 PDF 与 Windows native library 真实 SHA-256 完整入账；严格文本 Snapshot 等价门禁彻底失败（合格率仅 0.4%）；验收判定为不通过；严禁合并到 `feature-dev`，严禁接入生产表格恢复算法；本分支就地封存。**

---

## 一、生产环境与代码红线核验（100% 达标）

1. **生产构建零污染**：
   - 根目录 `Cargo.toml` 保持纯净，未引入任何 PDFium 依赖，未注册 `tools/pdfium_probe` 成员；
   - 根目录执行 `cargo check` 正常通过（耗时 0.10s），零编译阻断。
2. **生产算法文件零修改**：
   - `rust/wireless_structure.rs`、`rust/wired.rs`、`rust/native_span.rs`、`rust/types.rs` 等所有生产核心算法文件代码修改量严格为 **0**。
3. **探针工程独立与质量保障**：
   - 探针工程位于 `tools/pdfium_probe/`，拥有独立工作区配置与独立 Cargo.toml；
   - `cargo check` 实现 **0 警告、0 错误**；
    - `cargo test` 自动化单元测试 5 项全部通过（100% PASS）；
    - 比较器负例自动化单元测试 12 项全部通过（100% PASS，含两字符基线 vs 单字符探针拦截、字符 BBox 误差超差拦截、文本长度与字符数不一致拦截等假绿封堵测试）；
    - 探针启动前自动核验动态库 SHA-256，杜绝静默版本漂移。
4. **跨平台验证实测状态说明（严谨诚实声明）**：
   - **Windows x64**：本地完成官方发布包与解压动态库的双重 SHA-256 实测验证，并在实机上完成端到端加载提取与哈希核验；
   - **Linux x64 / macOS arm64 / macOS x64**：已在 `manifest.json` 中锁定官方发布包下载源与压缩包 SHA-256，但**解压后动态库 SHA-256 与动态库加载行为目前仅为元数据配置，尚待在对应物理操作系统上完成实机实测验证**。

---

## 二、来源凭证 (Provenance) 与数学不变量深度核验

### 1. 消除伪造三元组，重构 `ProvenanceSidecar`
- **重构方案**：在 [`main.rs`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/src/main.rs) 中重构为独立凭据结构：
  ```rust
  #[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
  pub struct ProvenanceSidecar {
      pub page_index: usize,
      pub pdfium_object_index: usize, // 在 page.objects() 中的真实原始序号
      pub character_count: usize,     // TextObject 内实际 Unicode 字符总数
      pub char_start_index: usize,    // TextObject 内部起始字符偏移 (0)
      pub char_end_index: usize,      // TextObject 内部结束字符偏移 (len)
      pub char_indices: Vec<usize>,   // 每个字符的局部序号序列 [0, 1, ..., n-1]
      pub is_derived: bool,           // 原生探针输出固定为 false
      pub derived_block: Option<i64>, // 未做 block 聚类，诚实标记为 None
      pub derived_line: Option<i64>,  // 未做 line 聚类，诚实标记为 None
  }
  ```
- **字符范围保真**：基于 `total_chars_in_obj = chars.len()` 计算完整字符跨度；针对 PDFium `chars()` 遗漏的尾随空白字符，显式物化为 `CharInfo` 补齐，确保 `chars_list.len() == text.chars().count() == provenance.character_count == provenance.char_indices.len()`，彻底消除字符数量失配；在 `CharInfo` 中记录其在字符流中的实际局部位置 `char_index`。
- **范围诚实限定**：当前探针记录的是原子 TextObject 内部的局部字符偏移与对象索引，尚未构建跨 TextObject 全局统一的页面级字符流水号（该工作需在后续的只读聚合实验中推进）。

### 2. 比较器 7 项数学不变量严格校验与负例测试
比较器在 [`compare_synthetic_diff.py`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/scripts/compare_synthetic_diff.py) 中落地了针对 Provenance 的深度数学不变量校验：
1. `char_end_index >= char_start_index`；
2. `char_end_index - char_start_index == character_count`；
3. `char_indices == list(range(char_start_index, char_end_index))`（连续性检查）；
4. `char_indices == [c["char_index"] for c in characters]`（与字符数组一致性检查）；
5. `provenance.page_index == current_page_index`（物理页对齐检查）；
6. `provenance.is_derived == False`（严禁裸探针冒充派生对象）；
7. 字段完整非空检查。

编写了专门的负例单元测试 [`test_comparator_negative_cases.py`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/scripts/test_comparator_negative_cases.py)，覆盖 12 项针对非法 Provenance、倒置范围、非连续索引、页码错位、冒充派生以及假绿防范的反例，实测 **12 项全部 PASS**。

---

## 三、隐藏文本语义与渲染模式（真实双解析器行为审计）

### 1. 基准端与探针端语义对齐
- **PyMuPDF 基线**：在 `export_pymupdf_baseline.py` 中，通过 `flags & 64` 提取真实 `is_invisible: bool`，在页面级提取 `has_invisible_text: bool`；由于 PyMuPDF rawdict 没有原生 render mode，显式导出 `render_mode: None`；
- **PDFium 探针**：调用 `text_obj.render_mode()`，识别 `Invisible`（模式 3）及其他模式，显式导出 `render_mode: i32`、`is_invisible: bool`，移除此前人为硬编码的 `flags = 64`（显式为 `flags: None`）。

### 2. 比较器真实门禁判定
- `is_invisible`：当双方均具备明确布尔值时进行严格比较，若不符判定为 `INVISIBLE_MISMATCH` 并记入门禁违约；
- `render_mode`：双方均具备非空整数时严格比对数值；若一侧为 `None`，记录为 `render_mode_comparable: False`，不伪装成匹配；
- 页面级 `has_invisible_text`：双方均具备时严格校验一致性。

### 3. 门禁实测结论（32 项门禁违约拦截）
合成门禁执行检出 **32 项门禁违规**，以退出码 `1` 严格阻断：
```text
STATUS: FAILED (32 gate violations found)
  1. synth_crop_offset.pdf p0: Character text mismatch in span 'Header in CropBox'
  2. synth_crop_offset.pdf p0: Character text mismatch in span 'Normal Body Text'
  3. synth_crop_offset.pdf p0: Character text mismatch in span 'Outside of CropBox'
  4. synth_crop_offset.pdf p0: Max BBox Delta 4.858 pt > threshold 0.5 pt
  5. synth_invisible_text.pdf p0: Page has_invisible_text mismatch (Base=False vs Probe=True)
  ...
```
这真实证明了两引擎行为的当前差异：针对不可见文字层，PDFium 明确识别出 `RenderMode::Invisible` 并将页面标记为有隐藏文字，而 PyMuPDF 将其作为普通文字提取且未标记不可见，门禁据此准确拦截。

---

## 四、矢量线段（Drawings）容差体系与实测范围限定

### 1. 矢量线段判定容差体系
*   **外包围盒容差 (`rect_tol`)**: $\le 0.5 \text{ pt}$
*   **线段端点容差 (`point_tol`)**: $\le 0.5 \text{ pt}$（支持端点正反双向判定）
*   **线宽容差 (`width_tol`)**: $\le 0.95 \text{ pt}$（桥接 PDFium 发丝线 0.05 pt 与 MuPDF 默认 1.0 pt）
*   **未舍入原始浮点门禁原则**：判定严格基于未经舍入的绝对差，`round(..., 4)` 仅用于展示。

### 2. 5 个真实代表页实测表现（888 / 888 拓扑匹配）
在探针为 `path_obj.segments()` 接入 `path_obj.matrix()?` 变换后，全部 5 个真实代表页的 888 条线段在上述容差内全部匹配：
*   **个人征信表头页 (`credit_p0_header`)**: Base 429 条 vs Probe 429 条，**匹配 429 / 429 (100%)**；Max Rect Delta = **0.0001 pt**，Max Width Delta = **0.0 pt**；
*   **个人征信明细表格页 (`credit_p1_detail`)**: Base 436 条 vs Probe 436 条，**匹配 436 / 436 (100%)**；Max Rect Delta = **0.0 pt**，Max Width Delta = **0.0 pt**；
*   **财报横版表格页 (`test_p27_table`)**: Base 21 条 vs Probe 21 条，**匹配 21 / 21 (100%)**；Max Rect Delta = **0.0 pt**；
*   **财报封面 (`test_p0_cover`)**: Base 1 条 vs Probe 1 条，**匹配 1 / 1 (100%)**；
*   **财报目录 (`test_p1_toc`)**: Base 1 条 vs Probe 1 条，**匹配 1 / 1 (100%)**。

### 3. Drawing 结论范围严格限定（绝不说满）
> **重要边界声明**：上述 `888 / 888` 匹配结论**仅代表当前 5 个代表页在当前几何与线宽拓扑模型下匹配**。
> **它不代表完整 Drawing 契约等效**：
> 1. 探针中 Drawing 的 `color` 与 `fill` 字段目前为 `None`，比较器尚未比对颜色和填充；
> 2. 当前比较器尚未覆盖三次贝塞尔曲线（Bezier）、剪裁蒙版（Clip Path）、复合 Path 运算或混合透明度（Alpha/Blending）；
> 3. 不能仅凭几何线段匹配推断出复杂视觉设计和阴影背景等特性已经等效。

---

## 五、三次独立运行确定性哈希台账（严格双向白名单）

运行 [`verify_deterministic_hashes.py`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/scripts/verify_deterministic_hashes.py)，全面落实了**严格双向白名单校验**（既不允许样本缺失，也不允许任何意外额外输出），并在提取前清理 stale JSON。

- **核验台账文件**: [`DETERMINISTIC_HASH_LEDGER.json`](file:///d:/codes/PDFLayoutParser/.worktrees/feat-pdfium-probe-sprint1/tools/pdfium_probe/DETERMINISTIC_HASH_LEDGER.json)
- **环境与依赖 Provenance**:
  - `target_os`: `windows-x64` (`windows_x64_verified: true`)
  - `native_library_path`: `native/win-x64/pdfium.dll`
  - `native_library_sha256`: `d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b`
  - `pdfium_release_tag`: `chromium/8066`
  - `linux_macos_status`: `metadata_only_unverified (pending validation on native machines)`
- **输入源 PDF 真实 SHA-256 全量入账**：
  - `test.pdf` (p0, p1, p27): `9d910b7b6a78fe2ccae1345c8651ca2e592d83b04bc2705f51d611ec0e1545a8`
  - `征信解析样例.pdf` (p0, p1): `c5ca492db2158913cde305efd8b4e9f41ba27d26c7b13bc9a9ae1acedda81a60`
- **核验结论**: **全部 10 个样本在 3 次提取运行中产生的规范化 JSON 哈希 100% 相同，没有任何漂移**。

---

## 六、真实代表页差分实测数据与深层归因

```text
┌───────────────────────────────── 5 个真实样本分层指标汇总 ───────────────────────────────┐
│                                                                                       │
│  1. 页面几何 (Geometry): 宽高、旋转及物理页索引全部 100% 严丝合缝                      │
│                                                                                       │
│  2. 矢量图元 (Drawings) 拓扑: 888 / 888 满足 (rect_tol=0.5, point_tol=0.5, width_tol=0.95)│
│                                                                                       │
│  3. 文本图元分层审计 (Text Grain & Quality Gate Breakdown):                            │
│     * 基准 Span 总数 (Total Base Spans)       : 518                                   │
│     * 探针图元总数 (Total Probe Objects)     : 2867 (粒度膨胀比: 5.53x)               │
│     * 候选文本匹配 (Candidate Matches)        : 58  (11.2%)                           │
│     * 字符内容相符 (Chars Verified)           : 28                                    │
│     * BBox 门禁达标 (BBox Gate Passed)        : 2   (0.4%)                            │
│     * 最终完全接收 (Fully Accepted Spans)     : 2   (0.4% - 门禁彻底失败)              │
│     * 缺失基准 Span (Missing Base Spans)      : 460 (88.8%)                           │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### 真实文本差异深层归因
实测中观察到：
- `credit_p1_detail` 最大 BBox 误差高达 **760.36 pt**；
- `credit_p0_header` 最大 BBox 误差高达 **415.06 pt**。

**科学归因**：
1. **绝非单一的 5 pt 字盒差异**：合成样本中字符 1:1 对应的 BBox 差异确实稳定在 4~5 pt（字形边界 GlyphBox 与行边界 LineBox 的差），但真实样本中高达数百 pt 的偏差有着截然不同的原因；
2. **贪心匹配与跨行错配**：由于 TextObject 严重碎裂（2867 个裸图元 vs 518 个基准 Span，膨胀比达 5.53x），大量孤立的短文本（如标点、单个数字、日期片段如 `'/'`、`'-'`、`'2025'`）在全页多次出现；当前 1:1 贪心匹配算法将不同物理行、不同表格单元格中的同名文本误配在了一起，产生了数百 pt 的垂直几何跨度；
3. **Sprint 2 建议**：在开展只读 Span 聚合实验前，必须先改进匹配诊断工具（引入位置局部性或拓扑连续性约束），避免将算法错配假象误判为几何漂移。

---

## 七、Sprint 1 终局定性与分支封存规范

1. **当前定性结论**：
   - 当前输出为 `PdfiumRawSnapshot`，**不包含 `words`、`blocks`、`lines` 等高阶聚合结构，绝不能作为现有 `PageSnapshotDto` 的替代品**；
   - 探针工程与差分基础设施建设加固完成；
   - 严格文本输入等价门禁彻底失败；
   - 绘图匹配结论严格限定于当前 5 个样本与几何模型；
   - 验收判定为不通过；
   - **严禁接入 `wireless_structure`、`wired`、`native_span` 等任何生产表格恢复算法**。
2. **分支封存操作**：
   - 当前工作区 `feat/pdfium-probe-sprint1` 分支就地封存，保留完整的差分台账、测试用例与验证报告作为审计证据；
   - **绝对不合并至 `feature-dev` 或主干分支**；
   - 后续任何 Span 聚合实验均在新的独立实验分支中开展。
