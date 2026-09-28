# Sprint 1 靶向合成测试双解析器差分台账 (Synthetic Diff Ledger)

- **生成时间**: 2026-09-28T17:10:00+08:00
- **PDFium Native Library**:
  - Release Tag: `chromium/8066`
  - Version: `156.0.8066.0`
  - SHA-256: `d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b` (本地实测)
- **PyMuPDF 运行时基准**: `PyMuPDF 1.28.2 (MuPDF 1.28.2)`
- **比对结果存储**: `tools/pdfium_probe/diff_report_synthetic.json`
- **差分门禁判定**: **门禁未通过 (FAILED)**
  - 门禁失败项 1：`synth_mixed_fonts.pdf` 存在 Span 数量不一致（PyMuPDF=5 vs PDFium=4，丢失纯空白 Span `' '`）；
  - 门禁失败项 2：全量合成样本 Max BBox Delta 在 4.164 ~ 5.744 pt，超出 0.5 pt 严格门禁要求。

---

## 一、合成测试全景差分明细表 (1-to-1 匹配与字符级验证)

| 靶向样本文件 | 验证机制 | Base Spans | Probe Spans | 1:1 匹配数 | 丢失/多出明细 | Max BBox Delta | Drawings 匹配 | 门禁判定 | 根因与差异归类 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `synth_crop_offset.pdf` | CropBox 视口平移 | 3 | 3 | 3 | 无 | 4.858 pt | 0 / 0 | **未达标** (超差) | 消除 50pt 视口偏移；X 轴无偏差，垂直方向存在 4.858 pt 字形盒排版差 |
| `synth_invisible_text.pdf` | 不可见/重叠文字 | 4 | 4 | 4 | 无 | 5.744 pt | 0 / 0 | **未达标** (超差) | `render_mode==3` 隐藏层图元全部提取；垂直 BBox 超差 5.744 pt |
| `synth_mixed_fonts.pdf` | 混排与字号突变 | **5** | **4** | **4** | **丢失 1 个空白 Span**<br>`PROBE_MISSING: ' '` | 5.026 pt | 0 / 0 | **未达标** (缺Span+超差) | PyMuPDF 将纯空格独立作为一个 Span 导出，PDFium 无对应独立原子 TextObject |
| `synth_rotations.pdf` | 0°/90°/180°/270° 旋转 | 4 | 4 | 4 | 无 | 4.984 pt | 0 / 0 | **未达标** (超差) | 局部坐标系旋转表现完全一致，垂直误差稳定在 4.984 pt |
| `synth_segmented_lines.pdf` | 连续/断续线段网格 | 2 | 2 | 2 | 无 | 4.164 pt | **6 / 6 (100% 吻合)**<br>Rect Delta: **0.000 pt** | **未达标** (文本超差) | 提取 `path_obj.segments()` 后，矢量端点拓扑与 BBox 0 差分吻合；文本垂直超差 4.164 pt |

---

## 二、几何与字符级深层实测证据

### 1. 水平坐标（X0, X1）高保真证据
通过在探针中接入 `text_obj.chars()` 并在比较器中逐字符对比，证实：
- 在 `synth_crop_offset.pdf` 中，对于首个 Span `"Header in CropBox"`：
  - 字符 `'H'`: PyMuPDF `X = [100.0, 110.108]`，PDFium `X = [100.0, 110.108]`（**水平偏差严格为 0.0000 pt**）；
  - 字符 `'e'`: PyMuPDF `X = [110.108, 117.892]`，PDFium `X = [110.108, 117.892]`（**水平偏差严格为 0.0000 pt**）；
- **结论**：PDFium 在 X 轴方向的文字起点和字宽几何与 PyMuPDF 完全等价。

### 2. 垂直坐标（Y0, Y1）系统性漂移根因
- PyMuPDF 返回的 Span 和 Char BBox 来源于字体排版行度规（Ascender/Descender 计算的 Line BBox）；
- PDFium `bounds()` 返回紧凑字形墨迹盒，`loose_bounds()` 返回松弛字符边界盒；
- 垂直方向存在 2.3 ~ 5.7 pt 的确定性几何差异，该差异属于两款引擎字盒（Font Metric Box vs Glyph Box）的模型固有差异，非坐标投影错误。在没有做字盒归一化前，无法满足 `< 0.5 pt` 的硬性门禁。

### 3. 空格图元（Whitespace Handling）差异
- `synth_mixed_fonts.pdf` 中 PyMuPDF 输出了 5 个 Span，其中第 3 个 Span 是单独的字符 `' '`；
- PDFium 底层仅针对具有字形或排版指令的图元创建 TextObject，不产生独立的空字符 TextObject；
- 适配器在构建 Span 时，若需要对齐 PyMuPDF，必须基于水平字符间距推断词间空格，不能指望 PDFium 直接吐出空格 Span。

---

## 三、台账审计总结

| 审计维度 | 实际状态 | 是否达到 Sprint 1 门禁 |
| :--- | :--- | :---: |
| 几何尺寸与旋转（Width/Height/Rotation） | 100% 一致 | 是 |
| 矢量线段（Drawings Points/Segments） | 100% 拓扑与端点一致（Rect Delta = 0.0 pt） | 是 |
| 文本图元覆盖率 | 汉字、英文字符全部覆盖；丢失纯空白 Span 1 个 | **否** |
| 文本 BBox 精度 | Max Delta: 5.744 pt（门禁要求 < 0.5 pt） | **否** |
| **最终台账判定** | **探针提取与差异排查完成；Sprint 1 门禁未通过** | **未通过** |
