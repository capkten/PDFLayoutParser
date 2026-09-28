# Sprint 1 实施与实测验证报告 (PDFium Probe Verification Report)

- **实施周期**: Sprint 1 (2026-09-28)
- **隔离分支**: `feat/pdfium-probe-sprint1` (Commit: `9181024` 基线)
- **隔离路径**: `d:\codes\PDFLayoutParser\.worktrees\feat-pdfium-probe-sprint1`
- **探针工程**: `tools/pdfium_probe/` (完全独立 Cargo.toml，不加入根 workspace)
- **最终验收结论**: **探针工程建设完成，差异摸底部分完成；Sprint 1 门禁未通过 (GATE FAILED)**。
  - **核心依据**：真实样本存在 8.25 倍图元粒度差异（Base 302 spans vs Probe 2493 objects，未匹配率高达 69.5%）；合成样本存在空格 Span 丢失且垂直 BBox 误差（~5.0 pt）超出 0.5 pt 门禁。
  - **红线遵循**：未修改任何生产算法文件，未切换任何生产路由，未污染主构建。

---

## 一、工程隔离与代码红线核验（达标）

1. **生产构建零污染**：
   - 根目录 `Cargo.toml` 保持干净，未引入 PDFium 依赖，未注册 `tools/pdfium_probe` 成员；
   - 根目录执行 `cargo check` 正常通过，未产生任何新增编译阻断。
2. **生产算法文件零修改**：
   - `rust/wireless_structure.rs`、`rust/wired.rs`、`rust/native_span.rs`、`rust/types.rs` 等所有算法文件代码修改量严格为 **0**。
3. **探针工程独立与警告清理**：
   - 探针工程位于 `tools/pdfium_probe/`，拥有独立的 Cargo.toml；
   - 修复了 `main.rs` 中 2 处未使用变量警告，`cargo check` 实现 **0 警告、0 错误**；
   - 探针启动前自动核验动态库 SHA-256，杜绝静默版本漂移。
4. **多平台元数据实测核验 (`manifest.json`)**：
   - 锁定官方 `bblanchon/pdfium-binaries` Release `chromium/8066`；
   - Windows x64：本地完成压缩包与解压动态库的双重 SHA-256 实测验证；
   - Linux x64 / macOS arm64 / macOS x64：完成官方发布源压缩包流式 SHA-256 核验并在 manifest 中明确标注验证状态。

---

## 二、靶向合成测试实测表现（未通过门禁）

比较器采用严格的 1-to-1 匹配与字符级几何比对，实测表现如下：

| 合成测试用例 | 靶向机制 | Base Spans | Probe Spans | 1:1 匹配数 | 异常与未匹配明细 | Max BBox Delta | Drawings 匹配 | 门禁判定 |
| :--- | :--- | :---: | :---: | :---: | :--- | :---: | :---: | :---: |
| `synth_crop_offset.pdf` | CropBox 视口平移 | 3 | 3 | 3 | 无 | 4.858 pt | 0 / 0 | **FAIL** (超差) |
| `synth_invisible_text.pdf` | 不可见/重叠文字 | 4 | 4 | 4 | 无 | 5.744 pt | 0 / 0 | **FAIL** (超差) |
| `synth_mixed_fonts.pdf` | 混排与字号突变 | **5** | **4** | **4** | **丢失 1 个空白 Span** (`PROBE_MISSING: ' '`) | 5.026 pt | 0 / 0 | **FAIL** (缺Span+超差) |
| `synth_rotations.pdf` | 0°/90°/180°/270° 旋转 | 4 | 4 | 4 | 无 | 4.984 pt | 0 / 0 | **FAIL** (超差) |
| `synth_segmented_lines.pdf` | 连续/断续线段网格 | 2 | 2 | 2 | 无 | 4.164 pt | **6 / 6 (100% 吻合)**<br>Rect Delta: 0.000 pt | **FAIL** (文本超差) |

### 合成测试核心技术发现
1. **水平字符位置 0.0000 pt 吻合**：
   - 探针深入提取字符级别 `text_obj.chars()`，字符 `'H'` 与 `'e'` 在 X 轴方向的起止位置与 PyMuPDF 完全重合（偏差为 0.0000 pt），证明水平投影与 CropBox 平移算法完全正确。
2. **垂直 ~5 pt 差异根因锁定**：
   - 垂直方向的 4.16 ~ 5.74 pt 偏差并非计算错误，而是 PyMuPDF Line BBox（包含字号行度规）与 PDFium Glyph/Loose Box（基于字形墨迹）的模型固有差异。
   - 在未实现排版盒归一化前，无法满足 `< 0.5 pt` 的硬性门禁。
3. **矢量线段拓扑真实对齐**：
   - 探针通过遍历 `path_obj.segments()` 提取真实端点并重算几何外包围盒，成功消除了 PDFium 原生带描边宽度的 bounds 偏差，在 `synth_segmented_lines.pdf` 上实现了 6/6 线段与 Rect 的 **0.000 pt 完美匹配**。

---

## 三、真实代表页差分实测（重大障碍确认）

在 4 个真实商业与征信页面上执行 1-to-1 差分比对，真实数据如下：

```text
┌───────────────────────────────── 真实样本实测对比数据 ─────────────────────────────────┐
│                                                                                       │
│  1. 页面几何 (Geometry): 宽高与旋转全部 100% 严丝合缝 (Dims Match = True)              │
│     - 财报横版表格页 (test.pdf p27) : 841.9 x 595.3 pt (100% 匹配)                     │
│     - 个人征信报告页 (征信样例 p0)   : 594.96 x 841.92 pt (100% 匹配)                   │
│                                                                                       │
│  2. 图元粒度鸿沟 (TextObject vs NativeSpan Mismatch - 核心阻塞项):                    │
│     - test_p0_cover: Base=8 spans  vs Probe=63 objs  (匹配=0,  未匹配=71)             │
│     - test_p1_toc  : Base=31 spans vs Probe=842 objs (匹配=1,  未匹配=870)            │
│     - test_p27_table: Base=85 spans vs Probe=1049 objs(匹配=10, 未匹配=1102)           │
│     - credit_p0_header: Base=178 spans vs Probe=539 objs(匹配=81, 未匹配=552)          │
│     --------------------------------------------------------------------------------  │
│     * 总基准 Span 数量 : 302                                                          │
│     * 总探针对象数量   : 2493 (膨胀比: 8.25x)                                         │
│     * 1:1 文本完全匹配 : 仅 92 (占基准的 30.5%)                                       │
│                                                                                       │
│  3. 矢量图元 (Drawings) 真实表现:                                                     │
│     - 征信 p0: Base 429 条线 vs Probe 429 条线 (总数一致)                              │
│     - 财报 p27: Base 21 条线 vs Probe 21 条线 (总数一致)                               │
│     - 注意：虽然数量一致，但真实 PDF 存在复合路径绘制顺序差异，不能简单按序直接贪心对齐。    │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### 为什么当前不能直接对接下游表格算法？
1. **中文单字打散**：
   - 真实财报中，PyMuPDF 输出的是完整词组（如 `宝山钢铁股份有限公司`），而 PDFium 原生吐出的是单个汉字原子图元（`宝`、`山`、`钢`、`铁`...）。若直接输入现有表格算法，将导致字符碎裂、单元格文本拆解为无数碎片、列带划分彻底崩溃。
2. **英文与数字局部切分**：
   - 真实征信报告中，PyMuPDF 的 `https://ccps-ccs-web.bocsys.cn/#/reportView` 被 PDFium 切成了 `https://ccps-ccs-web.bocsys.cn/#/reportV` 和 `iew` 两段；`1/12` 被切成了 `1` 和 `/`。

---

## 四、Sprint 1 验收结论与后续规划

### 1. 验收结论
- [x] **基础设施搭建**：独立 Crate、动态库哈希门禁、零侵入构建完成；
- [x] **底层输入摸底**：彻底探明了 CropBox 视口映射、水平字符位置精度、矢量线段提取机制；
- [ ] **输入等价门禁**：**未通过 (FAILED)**。原因为：
  - 合成测试中 Max BBox Delta (~5.0 pt) 超出 0.5 pt 门禁，且存在空白 Span 丢失；
  - 真实页面存在 8.25 倍的 TextObject 粒度差异，未匹配率达 69.5%。

### 2. 严守代码红线
- 坚决**不向**现有生产 Rust 表格恢复算法输送任何未经聚合的 PDFium 数据；
- 坚决**不修改**生产算法核心逻辑文件。

### 3. Sprint 2 实施要求（关键攻关点）
在进入表格恢复对接前，必须在输入适配器层（而非算法层）实现：
1. **水平紧邻图元同词成段器 (Span Horizontal Aggregator)**：
   - 依据字号、基线 Y 坐标、水平间隙阈值（$dx \le \text{font\_size} \times 0.2$）将原子汉字与英文碎片聚合为符合排版语义的完整 `NativeSpan`；
2. **垂直排版盒归一化 (Vertical Box Normalization)**：
   - 基于字体 Ascender / Descender 度规将紧凑字形盒向上向外扩展，消除与 PyMuPDF 的 5 pt 固有排版差；
3. **词间空格推断 (Whitespace Inference)**：
   - 当水平相邻图元间隙达到空格宽度时，显式插值空格信息，保证语义连贯性。
