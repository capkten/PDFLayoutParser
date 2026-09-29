# PDFium 行为级 Shadow 输入适配器设计

## 目标

在不修改现有表格恢复算法、不切换生产路由的前提下，验证 PDFium 是否能够生成足以驱动现有 Rust 表格处理链的文本层级输入。验收目标是：

1. 可解析页面的阅读顺序一致；
2. 表格数量、单元格文本、行列结构和跨度结果正确；
3. 两条路径经过同一 Markdown writer 后的最终 Markdown 一致；
4. 绝对 bbox、Span 数量、PDFium TextObject 数量和底层来源索引不作为跨引擎硬门禁。

## 背景与边界

当前 PDFium probe 只输出页面几何、文本对象、字符、来源信息和 drawing，尚未提供现有 Rust Snapshot 消费端需要的完整 `blocks -> lines -> spans -> chars` 层级。项目中的 `Line` 是自己的数据模型，表示视觉文本行，不是可直接复用的 PyMuPDF 对象。

本设计参考 PyMuPDF `dict/rawdict/words` 的公开数据形状、字段语义和实际行为样本，但不复制 MuPDF/PyMuPDF 内部实现。PDFium 是 C++ native library；本工作称为 Rust 输入适配和行为验证，不宣称底层库本身为纯 Rust。

以下内容明确不在本阶段范围内：

- 修改 `rust/wireless_structure.rs`、`rust/wired.rs`、`rust/native_span.rs` 等生产算法；
- 修改默认 Cargo workspace、Python Wheel 构建链或生产路由；
- 强制 PyMuPDF 与 PDFium 生成相同数量或相同边界的 blocks、lines、spans、words；
- 为字体映射失败页面添加新的 OCR 实现；
- 直接复制或链接 MuPDF 内部源代码。

## 页面分类契约

页面分类必须先于 PDFium 层级归一化。沿用现有 Python 页面分类的页面级语义：只要页面出现空文本、替换字符、非法控制字符、不可用的 Unicode/CID 映射、缺少必要的 Type 3 字体映射、严重 bbox 异常、文字转曲或主要内容为图片等情况，整页就标记为 `scanned`，不进行文本、表格或布局解析。

PDFium 适配器的流程如下：

```text
PDFium raw page
    -> extraction eligibility / Unicode mapping classification
       -> scanned: render and record diagnostics only
       -> vector: normalize chars -> spans -> lines -> blocks -> words
```

`scanned` 页面不得用残缺或替换字符合成假的 blocks/lines/words。shadow 比较时：

- `scanned/scanned`：两边都不产生文本 Markdown，分类结果通过；
- `vector/scanned` 或 `scanned/vector`：分类差异，失败并进入台账；
- `vector/vector`：进入文本层级、表格和 Markdown 行为比较。

PDFium raw 输出必须补充足以解释分类的证据，例如替换字符数、控制字符数、未映射字符数、字体映射状态和分类原因。若底层 API 无法可靠判断某一类映射问题，状态必须记录为 `unknown`，在获得证据前不能宣称该页面与 Python 分类等价。

## 规范化数据流

### 1. 字符记录

每个 PDFium 字符转换为拥有的数据记录，至少包含：

- Unicode 文本；
- bbox；
- 字体、字号和渲染属性；
- PDFium 对象索引和字符索引；
- 是否为替换/控制/未映射字符。

底层索引、原始字符范围和渲染模式保存在独立 provenance sidecar，不伪装为 PyMuPDF `source_position`。

### 2. 字符到 Span

同一视觉行、方向、字号和字体属性兼容，且字符间距连续的字符可以合成 Span。明显的字段间隔、列边界或来源不连续时必须保留独立 Span。合并依据来自几何关系，但绝对坐标只服务于本引擎内部的分组。

### 3. Span 到 Line

Line 定义为视觉文本行。归一化器根据基线或垂直中心、字符高度、方向和垂直重叠对 Span 聚类，并按该行的阅读方向排序。Line 不是段落、表格行或原始 PDF 对象。

### 4. Line 到 Block

相邻且属于同一文本区域的视觉行按行距、水平投影、列间空白和区域连续性合并为 Block。Block 必须包含 bbox、派生顺序、来源 sidecar 和 nested lines。

### 5. Span/Char 到 Word

Words 是由规范化 Span/Char 派生的兼容视图，不重新调用 `page.get_text("words")`。拉丁文、数字、中英文混排和 CJK 的切分策略必须显式记录版本；Words 第一阶段只用于 DTO 完整性、兼容接口和诊断，不作为 PyMuPDF 等价硬门禁。

### 6. PageSnapshotDto

vector 页面最终生成现有契约所需的完整层级：

```text
PageSnapshotDto
  text_blocks[]
    lines[]
      spans[]
        characters[]
  words[]
  drawings[]
```

现有 Rust Snapshot 消费端继续从 `text_blocks -> lines -> spans -> characters` 收集 native spans；不改变其算法和字段定义。

## Drawing 适配

PDFium path 适配到现有 drawing DTO 时保留来源和宽度信息，但不要求底层 Path 分段与 PyMuPDF 相同。行为验证比较合并后的水平/垂直边界、交点、覆盖区域和网格拓扑，最终以表格切分结果为准。

## 行为级验收

### 主门禁

两路都调用现有表格处理和 `MarkdownWriter.to_string(document)`：

```text
PyMuPDF input -> existing recovery -> Markdown
PDFium input  -> existing recovery -> Markdown
```

Markdown 规范化只允许：

- CRLF/CR 转 LF；
- 统一末尾换行；
- 按明确协议替换环境相关资源根路径。

不得折叠文本内部空白、删除图片行、删除 HTML 属性、改写单元格文本或改变表格顺序。

### 辅助门禁

记录并比较：

- 页面顺序；
- `layout_elements` 顺序；
- 普通文本阅读顺序；
- 表格数量；
- 表格行列数；
- 单元格文本；
- `rowspan/colspan`；
- 空槽位和 occupancy 冲突；
- 表格之间的顺序。

以下只进入诊断台账：绝对 bbox、Span/Line/Word 数量、TextObject 数量、PDFium object index、底层 path 分段和具体 render mode 数值。

扫描页还必须验证：没有进入文本/表格恢复，没有残留 Markdown 文件，且分类原因被记录。

## 组件边界

1. **Behavior comparator**：独立比较 Markdown、布局顺序和表格语义，带有顺序、文本、跨度、空槽位和分类差异负例。
2. **PDFium classifier**：在归一化前判定页面是否可解析，输出分类原因和证据。
3. **PDFium normalizer**：仅处理 vector raw page，生成 blocks/lines/spans/words 和 PageSnapshotDto；不修改生产算法。
4. **Shadow runner**：在相同 fixture 上分别运行 PyMuPDF 和 PDFium 输入，写出 Markdown、结构 JSON 和差异台账。

## 迭代与评审

实现按独立任务顺序推进，不允许多个实现 subagent 同时修改共享文件。每个任务采用：

1. `gpt-6-luna` implementer 先写失败测试，再做最小实现；
2. `gpt-6-luna` evaluator 独立检查规范、测试和差异台账；
3. Critical/Important 问题由新的 `gpt-6-luna` 修复 subagent 处理并重新评审；
4. 通过后记录任务报告和 progress ledger，再开始下一任务。

推荐任务顺序：

1. 行为级 Markdown/结构差分器；
2. 页面分类和 Unicode 映射门禁；
3. 字符到 Span/Line 的 PDFium 归一化；
4. Block/Word 派生和完整 PageSnapshotDto；
5. Drawing 适配；
6. Shadow runner 和代表性页面验收。

## 主要风险

- PDFium 对象顺序不等于阅读顺序，必须有独立视觉排序；
- TextObject 过度碎片化，不能把原始对象直接当 Span；
- CJK/CID 映射状态可能无法从当前 probe 充分观察，必须先补证据；
- 页面级 scanned 规则会放弃同页的部分可用文本，这是现有 Python 行为，需要作为明确契约保留；
- 扫描页 Markdown 为空不能被比较器误报为普通文本丢失。

## 设计结论

采用“PDFium raw page -> 页面可解析性分类 -> vector 层级归一化 -> 现有 PageSnapshotDto -> 现有 Rust 表格算法 -> Markdown 行为差分”的路线。该路线复用已有结构和算法，允许 PyMuPDF 与 PDFium 在几何和底层切分上不同，同时把字体映射失败页面安全地归入现有图片页语义。
