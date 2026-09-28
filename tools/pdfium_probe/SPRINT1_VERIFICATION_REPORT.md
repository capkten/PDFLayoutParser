# Sprint 1 实施与实测验证报告 (PDFium Probe Verification Report)

- **实施周期**: Sprint 1 (2026-09-28)
- **基线起点**: Commit `9181024`
- **实施提交**: Commit `8a958e2`（以及当前加固提交）
- **隔离分支**: `feat/pdfium-probe-sprint1`
- **隔离路径**: `d:\codes\PDFLayoutParser\.worktrees\feat-pdfium-probe-sprint1`
- **探针工程**: `tools/pdfium_probe/` (完全独立 Cargo.toml，不污染根工作区)
- **最终验收结论**: **探针工程建设完成；差分工具健全严密；输入等价门禁未通过 (GATE FAILED)；严禁直接接入现有表格恢复算法。**

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
   - 新增 `scripts/download_pdfium.py` 实现多平台自动下载与确定性哈希核验。

---

## 二、矢量线段（Drawings）容差定义与拓扑验证突破

### 1. 为什么矢量线在不同引擎间天然存在微差？
*   **坐标与浮点精度微差**：MuPDF 与 PDFium 在解析 CTM 变换矩阵时，浮点矩阵乘法和舍入规则存在微小浮点尾差（一般在 $0.0001 \sim 0.2 \text{ pt}$）；
*   **线宽与细线（Hairline）表示**：PDFium 对零线宽或发丝线严格提取原始定义（如 $0.05 \text{ pt}$），而 MuPDF 常归一化为默认值 $1.0 \text{ pt}$；
*   **图元指令表达形式（Command Equivalence）**：PyMuPDF 针对矩形使用紧凑的 `'re'` 指令（`points` 为空，几何存于 `rect`），而 PDFium 底层通过 `MoveTo -> LineTo -> LineTo -> LineTo -> Close` 4 段线段导出；
*   **线段端点反向（Direction Invariance）**：线段从 $(A \to B)$ 绘制与从 $(B \to A)$ 绘制在几何拓扑上等价。

### 2. 线段等价性判定准则（Tolerance Rules）
经实测证明，设定以下几何容差可严格保证**下游表格线网格划分完全一致**：
*   **包围盒容差 (`rect_tol`)**: $\le 0.5 \text{ pt}$
*   **端点坐标容差 (`point_tol`)**: $\le 0.5 \text{ pt}$（支持端点方向翻转）
*   **矩形语义等价判定**: 当一方为 `'re'` 且另一方为 4 段闭合 `'l'`，若包围盒误差 $\le \text{rect\_tol}$，判定为语义完全等价 (`MATCHED_SEMANTIC_RECT`)。

### 3. 真实代表页 Drawings 拓扑验证重大突破
在探针中为 `path_obj.segments()` 接入 `path_obj.matrix()?` 矩阵变换，并重构比较器容差判定后，真实代表页全部 452 条线段实现 **100% 拓扑对应**：
*   **个人征信报告页 (`credit_p0_header`)**: Base 429 条线 vs Probe 429 条线，**1:1 匹配数: 429 / 429 (100%)**，Max Rect Delta = **0.0001 pt**！
*   **财报横版表格页 (`test_p27_table`)**: Base 21 条线 vs Probe 21 条线，**1:1 匹配数: 21 / 21 (100%)**，Max Rect Delta = **0.0000 pt**！
*   **财报封面 (`test_p0_cover`)**: Base 1 条线 vs Probe 1 条线，**1:1 匹配数: 1 / 1 (100%)**，Max Rect Delta = **0.0000 pt**！
*   **财报目录 (`test_p1_toc`)**: Base 1 条线 vs Probe 1 条线，**1:1 匹配数: 1 / 1 (100%)**，Max Rect Delta = **0.0000 pt**！

---

## 三、比较器四项严密门禁加固成果

针对复核发现的比较器缺陷，已完成彻底修复：
1. **字符级不匹配阻断**：`compare_characters()` 发现文本不一致时，外层 Span 标记为 `CHAR_MISMATCH`，门禁直接抛出违规并以退出码 `1` 拦截；
2. **读取顺序与逆序数检测 (Order Inversions)**：收集所有 1:1 匹配 Span 的 `(base_order, probe_order)`，计算逆序对总数及逆序比率，检测行内与跨行顺序漂移；
3. **端点级容差门禁**：`compare_drawings()` 对线段逐段比对端点，端点超差记为 `POINT_DELTA_EXCEEDED` 并触发门禁拦截；
4. **真实样本全量拓扑核验**：消除了“数量相同但 matched 为 0”的假象，在真实样本上实现了真实几何拓扑核验。

---

## 四、靶向合成测试实测表现（未通过门禁）

在合成样本上执行严格门禁比较，检出 9 项门禁违规，门禁以退出码 `1` 拦截：

| 合成测试用例 | 靶向机制 | Base Spans | Probe Spans | 1:1 匹配数 | 逆序数 | 异常与未匹配明细 | Max BBox Delta | Drawings 匹配 | 门禁判定 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: |
| `synth_crop_offset.pdf` | CropBox 视口平移 | 3 | 3 | 3 | 0 | 无 | 4.858 pt | 0 / 0 | **FAIL** (超差) |
| `synth_invisible_text.pdf` | 不可见/重叠文字 | 4 | 4 | 4 | 0 | 无 | 5.744 pt | 0 / 0 | **FAIL** (超差) |
| `synth_mixed_fonts.pdf` | 混排与字号突变 | **5** | **4** | **4** | 0 | **丢失 1 个空白 Span** (`PROBE_MISSING: ' '`) | 5.026 pt | 0 / 0 | **FAIL** (缺Span+超差) |
| `synth_rotations.pdf` | 0°/90°/180°/270° 旋转 | 4 | 4 | 4 | 0 | 无 | 4.984 pt | 0 / 0 | **FAIL** (超差) |
| `synth_segmented_lines.pdf` | 连续/断续线段网格 | 2 | 2 | 2 | 0 | 无 | 4.164 pt | **6 / 6 (100%)**<br>Delta: 0.000 pt | **FAIL** (文本超差) |

---

## 五、真实代表页差分实测数据（图元粒度鸿沟）

```text
┌───────────────────────────────── 真实样本实测对比数据 ─────────────────────────────────┐
│                                                                                       │
│  1. 页面几何 (Geometry): 宽高与旋转全部 100% 严丝合缝                                  │
│     - 财报横版表格页 (test.pdf p27) : 841.9 x 595.3 pt (100% 匹配)                     │
│     - 个人征信报告页 (征信样例 p0)   : 594.96 x 841.92 pt (100% 匹配)                   │
│                                                                                       │
│  2. 矢量图元 (Drawings) 拓扑几何: 全部 452 条线段 100% 严密对齐 (Max Delta <= 0.0001pt)  │
│     - 个人征信报告页 (credit_p0): 429 / 429 匹配 (Max Rect Delta = 0.0001 pt)         │
│     - 财报横版表格页 (test_p27) :  21 /  21 匹配 (Max Rect Delta = 0.0000 pt)         │
│     - 财报封面/目录  (p0 / p1)  :   1 /   1 匹配 (Max Rect Delta = 0.0000 pt)         │
│                                                                                       │
│  3. 文本图元粒度鸿沟 (TextObject vs NativeSpan Mismatch - 核心阻塞项):                 │
│     - test_p0_cover: Base=8 spans  vs Probe=63 objs  (匹配=0,  未匹配=71)             │
│     - test_p1_toc  : Base=31 spans vs Probe=842 objs (匹配=1,  未匹配=870)            │
│     - test_p27_table: Base=85 spans vs Probe=1049 objs(匹配=10, 未匹配=1102)           │
│     - credit_p0_header: Base=178 spans vs Probe=539 objs(匹配=81, 未匹配=552)          │
│     --------------------------------------------------------------------------------  │
│     * 总基准 Span 数量 : 302                                                          │
│     * 总探针对象数量   : 2493 (膨胀比: 8.25x)                                         │
│     * 1:1 文本完全匹配 : 仅 92 (占基准的 30.5%)                                       │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 六、交付治理与 Sprint 2 路线规范

### 1. 交付文件治理说明
*   **二进制文件与大体积 JSON**：
    - `pdfium.dll`（7.0MB）与生成 JSON（`diff_report_real.json` 1.2MB）当前仅暂存于隔离实验分支 `feat/pdfium-probe-sprint1` 中，用于保障任何人检出后即可一键复现实验；
    - **严禁**合并进 `feature-dev` 或主分支；
    - 后续如果团队策略要求彻底剥离大文件，可通过 `download_pdfium.py` 实现“零 binary 提交，按需下载缓存”。
*   **多平台动态库实测说明**：
    - Linux 与 macOS 的压缩包已实测官方 SHA-256；
    - 解压后的 `.so` / `.dylib` 二进制哈希与动态绑定待对应操作系统运行环境中实机校验。

### 2. Sprint 2 实施要点纠偏
1. **拒绝死板的全局规则**：
   - 严禁将 `dx <= font_size * 0.2` 作为全局硬性聚合规则；
   - 必须针对 **CJK 汉字连续性**、**西文单词/空格间距**、**数字连续性**、**标点符号悬挂** 制定差异化聚合状态机；
2. **明确 Source Provenance 契约**：
   - 聚合后的 `NativeSpanDto` 必须完整保留其来源的所有原子图元坐标索引与字符级 BBox，供下游溯源；
3. **理性看待 5 pt 垂直字盒差异**：
   - 不为了盲目迎合 0.5 pt 门禁去强行硬凑 bbox；
   - 先验证此差异对 Rust 行聚类容差 `tol = max(2.4, size * 0.38)` 是否产生实质性越界或串行影响。
