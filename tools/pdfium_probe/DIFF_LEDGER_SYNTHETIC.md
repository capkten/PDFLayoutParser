# Sprint 1 靶向合成测试双解析器差分台账 (Synthetic Diff Ledger)

- **生成时间**: 2026-09-28T17:25:00+08:00
- **基线提交**: `9181024`
- **实施提交**: `8a958e2`（以及当前加固提交）
- **PDFium Native Library**:
  - Release Tag: `chromium/8066`
  - Version: `156.0.8066.0`
  - SHA-256: `d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b` (Windows x64 本地实测)
- **PyMuPDF 运行时基准**: `PyMuPDF 1.28.2 (MuPDF 1.28.2)`
- **比对结果存储**: `tools/pdfium_probe/diff_report_synthetic.json`
- **差分门禁判定**: **门禁未通过 (FAILED)**
  - 门禁失败项 1：`synth_mixed_fonts.pdf` 存在 Span 数量不一致（PyMuPDF=5 vs PDFium=4，丢失纯空白 Span `' '`）；
  - 门禁失败项 2：全量合成样本 Max BBox Delta 在 4.164 ~ 5.744 pt，超出 0.5 pt 严格门禁要求。

---

## 一、合成测试全景差分明细表 (1-to-1 匹配、字符级与逆序数验证)

| 靶向样本文件 | 验证机制 | Base Spans | Probe Spans | 1:1 匹配数 | 逆序数 | 丢失/多出明细 | Max BBox Delta | Drawings 匹配 | 门禁判定 | 根因与差异归类 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :--- |
| `synth_crop_offset.pdf` | CropBox 视口平移 | 3 | 3 | 3 | 0 | 无 | 4.858 pt | 0 / 0 | **未达标** (超差) | 消除 50pt 视口偏移；X 轴 0 偏差，垂直存在 4.858 pt 字盒差 |
| `synth_invisible_text.pdf` | 不可见/重叠文字 | 4 | 4 | 4 | 0 | 无 | 5.744 pt | 0 / 0 | **未达标** (超差) | `render_mode==3` 隐藏层图元全部提取；垂直 BBox 超差 5.744 pt |
| `synth_mixed_fonts.pdf` | 混排与字号突变 | **5** | **4** | **4** | 0 | **丢失 1 个空白 Span**<br>`PROBE_MISSING: ' '` | 5.026 pt | 0 / 0 | **未达标** (缺Span+超差) | PyMuPDF 将纯空格独立作为一个 Span 导出，PDFium 无对应独立原子 TextObject |
| `synth_rotations.pdf` | 0°/90°/180°/270° 旋转 | 4 | 4 | 4 | 0 | 无 | 4.984 pt | 0 / 0 | **未达标** (超差) | 局部坐标系旋转表现完全一致，垂直误差稳定在 4.984 pt |
| `synth_segmented_lines.pdf` | 连续/断续线段网格 | 2 | 2 | 2 | 0 | 无 | 4.164 pt | **6 / 6 (100% 吻合)**<br>Rect Delta: **0.000 pt**<br>Point Delta: **0.000 pt** | **未达标** (文本超差) | 提取 `path_obj.segments().transform(matrix)` 后，矢量端点拓扑与 BBox 0 差分吻合；文本垂直超差 4.164 pt |

---

## 二、几何、字符级与矢量线容差实测证据

### 1. 水平坐标（X0, X1）高保真证据
通过在探针中接入 `text_obj.chars()` 并在比较器中逐字符对比，证实：
- 在 `synth_crop_offset.pdf` 中，对于首个 Span `"Header in CropBox"`：
  - 字符 `'H'`: PyMuPDF `X = [100.0, 110.108]`，PDFium `X = [100.0, 110.108]`（**水平偏差严格为 0.0000 pt**）；
  - 字符 `'e'`: PyMuPDF `X = [110.108, 117.892]`，PDFium `X = [110.108, 117.892]`（**水平偏差严格为 0.0000 pt**）；
- **结论**：PDFium 在 X 轴方向的文字起点和字宽几何与 PyMuPDF 完全等价。

### 2. 矢量线段（Drawings）容差定义与拓扑等价判定
提取线在不同解析引擎间存在微小的浮点尾差与指令表示差异：
- **Rect 容差与端点容差**: 设定 $0.5 \text{ pt}$ 阈值（支持端点方向翻转）足以保证表格框线网格划分 100% 严密对齐；
- **指令语义等价**: PyMuPDF `'re'` 指令与 PDFium 4 段 `'l'` 封闭路径在包围盒相符时判定为语义等价；
- **实测成果**: 接入 `path_obj.matrix()?` 后，真实代表页（`credit_p0` 429 条、`test_p27` 21 条、`test_p0` 1 条、`test_p1` 1 条）全部 452 条线段**100% 匹配**，最大误差 $\le 0.0001 \text{ pt}$。

### 3. 垂直坐标（Y0, Y1）系统性漂移根因
- PyMuPDF 返回的 Span 和 Char BBox 来源于字体排版行度规（Line Bounding Box）；
- PDFium `bounds()` 返回紧凑字形墨迹盒，`loose_bounds()` 返回松弛字符边界盒；
- 垂直方向存在 2.3 ~ 5.7 pt 的确定性几何差异，该差异属于两款引擎字盒（Font Line Box vs Glyph Box）的模型固有差异，非坐标投影错误。在 Sprint 2 中应先评估此差异对现有 Rust 行聚类算法的真实影响，而非盲目强行扩展。

---

## 三、台账审计总结

| 审计维度 | 实际状态 | 是否达到 Sprint 1 门禁 |
| :--- | :--- | :---: |
| 几何尺寸与旋转（Width/Height/Rotation） | 100% 一致 | 是 |
| 矢量线段（Drawings Points/Segments） | 100% 拓扑与端点一致（452/452 真实线段差分 $\le 0.0001 \text{ pt}$） | 是 |
| 文本读取顺序（Order Inversions） | 0 逆序（合成测试） | 是 |
| 文本图元覆盖率 | 汉字、英文字符全部覆盖；丢失纯空白 Span 1 个 | **否** |
| 文本 BBox 精度 | Max Delta: 5.744 pt（门禁要求 < 0.5 pt） | **否** |
| 真实代表页文本粒度 | 8.25x 粒度碎片化，未匹配率 69.5% | **否** |
| **最终台账判定** | **探针提取与差异排查完成；Sprint 1 门禁未通过** | **未通过** |
