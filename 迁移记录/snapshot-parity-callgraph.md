# Snapshot parity 页面读取边界

## 起始证据

- branch `codex/rust-full-migration`
- HEAD `4f865fcf9552356e815964730924c81d5420adfb`
- 审计目录 `output/snapshot-parity-worktree-20260919`
- `pymupdf-read-scan.txt` 112 行，`pymupdf-page-read-scan.txt` 123 行
- 起始 patch SHA256 `46F3342B930F5A45062533463B1980ECDD0C475F86690927540AB44B80EA1F8A`
- 未提交用户/其他代理改动必须保留，未执行 reset/checkout/clean

## 生产入口与读取分类

以下入口均已在审计扫描范围内：page_classifier、language_detector、text/image extractor、ML table detector、wired_table_extractor、wireless_table_recovery、wireless_structure.recoverer、english_table_extractor、table_extractor、header normalizer、template engine。

读取分类如下：

- `get_text` 的 `text/rawdict/dict/blocks/words/clip`
- `get_drawings`
- `page.rect/rotation/number`
- `get_fonts/get_images/get_pixmap/find_tables` 等需要后续决定是否进入 Snapshot 的读取

## Snapshot 必须承载

Snapshot 必须承载以下信息：

- `page_index`
- PageDto 几何
- raw text block/line/span 层级和 `raw_source_position`
- span 字段
- 字符文本/bbox
- words 及 block/line/word 索引
- drawings 的 source order 和 line/rect/style/extended 字段
- allowed/excluded regions
- 精确 extraction options
- schema/version
- snapshot digest

`raw_source_position` 与 `filtered_order` 分开。

## 读取门禁

`capture_page_snapshot` 之后，算法、adapter、normalizer、候选循环和比较器禁止访问 `fitz.Page` 或再次调用 `get_text/get_drawings`；同一 page 的 python/shadow/rust、wired、Chinese/mixed wireless、English wireless、text alignment 共享同一 Snapshot。PNG/HTML 渲染可在算法完成后单独读取原页面。

## 当前限制

CodeGraph 未初始化；调用图来自源码扫描。当前没有 `capture_page_snapshot`，读取门禁将在 Task 2/Task 7 实现。不得把此文档的创建标记为生产代码完成。

## Fix follow-up 2：审计证据与 Snapshot 契约

### 审计证据

审计目录绝对路径：`D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\`

| 文件 | SHA256 |
| --- | --- |
| `status.txt` | `66D3B2CCF6A73F0B4881E99A8EE437163D5FE3BB4D19FD554957EB088C227BC3` |
| `head.txt` | `AAC838001342D372B11D6AEB81287968F56B21B382B70F6014F7FFDB9391C033` |
| `untracked.txt` | `68E3F86A28B112E1A2C249157B4190EB4E3DE780953CAC4A9EA819B89C4964E4` |
| `preexisting-working-tree.patch` | `46F3342B930F5A45062533463B1980ECDD0C475F86690927540AB44B80EA1F8A` |

已读取的审计文件：

- `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\status.txt`
- `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\head.txt`
- `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\untracked.txt`
- `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\preexisting-working-tree.patch`（155698 字符、4216 行）
- `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\pymupdf-read-scan.txt`（112 行）
- `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\pymupdf-page-read-scan.txt`（123 行）

起始状态审计命令（Task 0 brief 中记录的已执行命令）如下：

```powershell
$worktree = 'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration'
$audit = 'D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919'
New-Item -ItemType Directory -Force -Path $audit | Out-Null
git -C $worktree status --short --branch | Set-Content -Encoding utf8 "$audit\status.txt"
git -C $worktree rev-parse HEAD | Set-Content -Encoding utf8 "$audit\head.txt"
git -C $worktree diff --binary --no-ext-diff | Set-Content -Encoding utf8 "$audit\preexisting-working-tree.patch"
git -C $worktree ls-files --others --exclude-standard | Set-Content -Encoding utf8 "$audit\untracked.txt"
```

首轮 PyMuPDF 扫描命令：

```powershell
rg -n "page\.(get_text|get_drawings|rect|rotation|number)|get_text\(|get_drawings\(" `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\core' `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\extractors' `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\ml' `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\tables'
```

输出分别为 `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\pymupdf-read-scan.txt` 和扩展扫描文件 `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\pymupdf-page-read-scan.txt`。Task 0 报告只保留了扩展扫描的用途和 123 行结果，没有保留其完整命令文本。本次哈希复核命令为：

```powershell
Get-FileHash -Algorithm SHA256 `
  'D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\status.txt', `
  'D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\head.txt', `
  'D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\untracked.txt', `
  'D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\preexisting-working-tree.patch'
```

### Snapshot 共享与不可变语义

`capture_page_snapshot(page)` 是每个页面唯一的生产读取入口。Snapshot 必须包含 `page_index`、PageDto 几何（rect/width/height/rotation/number）、raw text 的 block/line/span 层级及 `raw_source_position`、span 字段、字符文本/bbox、words 及 block/line/word 索引、drawings 的 source order 和 line/rect/style/extended 字段、allowed/excluded regions、精确 extraction options、schema/version、snapshot digest，以及页面分类和资源特征（fonts、images、image_info、image_rects、font xref/object 探测结果）和 ML 所需的确定性 raster/预计算特征。`raw_source_position` 与 `filtered_order` 分开保存。

Snapshot 必须递归不可变：顶层及所有嵌套容器使用 frozen dataclass、`tuple`、只读 `MappingProxyType` 或等价结构；不得只冻结外层。对嵌套 block、span、drawing、region、options 或资源元数据执行 mutation 必须失败或产生新值，绝不能改变原 Snapshot 或其 digest。

同一页面只捕获一个 Snapshot，并由 `python`、`shadow`、`rust` 三种模式共同使用；`wired`、Chinese/mixed wireless、English wireless 和 text alignment 四条入口共同消费同一 Snapshot。算法、adapter、normalizer、候选循环和比较器只能接收 Snapshot 或其不可变派生视图。

### 可执行读取门禁契约

`capture_page_snapshot()` 返回后，严格 spy page 对以下任一访问必须抛异常：`get_text`、`get_drawings`、`get_fonts`、`get_images`、`get_image_info`、`get_image_rects`、`get_pixmap`、`get_bboxlog`、`find_tables`；`page.parent`、`page.parent.xref_object`；内容对象透传（原始 page、document、page handle 或 content object）；页面几何读取（`page.rect`、`page.width`、`page.height`、`page.rotation`、`page.number`、`page.size` 及等价属性）。spy 必须覆盖经 adapter、缓存、闭包、候选对象或结果对象保留的原始 page 引用。

只有算法完成后的 PNG/HTML renderer 可以读取原 page，renderer 的结果不得反向影响算法。当前代码尚未实现 `capture_page_snapshot()` 和该 spy；本节是迁移契约，不表示生产代码已完成。

## 已保存的审查增量（2026-09-19）

本轮在逐调用点清单写入前被中断；以下内容是已经核对并保存的证据与分类，不表示逐调用点清单已经完成。

### 扩展扫描证据

扫描范围与首轮一致，覆盖以下生产目录：

```text
D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\core
D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\extractors
D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\ml
D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\tables
```

扩展扫描完整命令文本如下；本轮没有重跑该命令，命令仅用于复原已有结果文件的审计记录：

```powershell
rg -n --glob '*.py' "page\.(get_text|get_drawings|rect|rotation|number|get_fonts|get_images|get_image_info|get_image_rects|get_pixmap|get_bboxlog|find_tables|parent)|xref_object|get_text\(|get_drawings\(|get_fonts\(|get_images\(|get_image_info\(|get_image_rects\(|get_pixmap\(|get_bboxlog\(|find_tables\(" `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\core' `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\extractors' `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\ml' `
  'D:\codes\PDFLayoutParser-Fast\.worktrees\rust-full-migration\src\hexai_pdf_parser\tables'
```

结果文件与 SHA256：

| 结果文件 | 行数 | SHA256 |
| --- | ---: | --- |
| `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\pymupdf-read-scan.txt` | 112 | `5D8B75F1F7E7358EC537E4BD6119CB18B4A76793239744C57A528EAC6726507C` |
| `D:\codes\PDFLayoutParser-Fast\output\snapshot-parity-worktree-20260919\pymupdf-page-read-scan.txt` | 123 | `D5E3BC4EF4178A3A8D51F9CFB3273A32E1C73B46A481B63F3367F8CCDC3C3C6E` |

### 特殊 API 的确定分类

以下分类取决于当前调用点的用途，而不是 API 名称本身；未知参数必须在逐调用点表中写成 `unknown`。

| API/访问 | 当前已核对用途 | Snapshot 归属 | 允许层级 | strict spy |
| --- | --- | --- | --- | --- |
| `get_fonts(full=True)` | Type3/ToUnicode 判定、Type3 字符区域恢复 | `resources.fonts`、font xref/object 元数据 | 算法 | 必须拦截 |
| `get_images()` / `get_images(full=True)` | 整页栅格判定、图片抽取 | `resources.images` | 算法 | 必须拦截 |
| `get_image_info(xrefs=True)` / `get_image_rects(xref)` | 图片 bbox、平铺线段恢复 | `resources.image_info`、`resources.image_rects` | 算法 | 必须拦截 |
| `page.parent` / `page.parent.xref_object(xref)` | Type3 字体 ToUnicode 资源检查 | `resources.font_xref_objects` | 算法 | 必须拦截；包括 `parent` 本身 |
| `get_pixmap(matrix=..., alpha=False[, colorspace=...])` | ML 栅格预处理、平铺/背景分析 | ML 确定性 raster/预计算特征 | 算法；最终 overlay 的同名调用属于渲染 | 必须拦截算法调用；渲染调用只能在算法完成后 |
| `get_bboxlog()` | 绘制顺序与遮挡判定 | `drawings.bboxlog` | 算法 | 必须拦截 |
| `find_tables()` | PyMuPDF 表格 fallback | `table_fallback.find_tables` 或等价 Snapshot 字段 | 算法 | 必须拦截 |
| `page.rect` / `page.rotation` / `page.number` | 页面几何、页号、输出文件名和 overlay | `page.geometry`、`page_index` | 算法读取必须来自 Snapshot；PNG/HTML 输出可渲染层读取 | 算法访问必须拦截；渲染访问受后置规则约束 |
| `overlay_page.show_pdf_page(..., page.parent, page.number)` | wireless debug PNG overlay | 不进入算法 Snapshot | 渲染 | 不作为算法 spy 豁免；只允许后置 renderer |

### 当前已核对的调用点范围

已有 112 行首轮结果和 123 行扩展结果，已确认涉及 `text_extractor`、`language_detector`、`page_classifier`、`image_extractor`、`personal_credit_report`、`pdf_parser`、`loader`、`pipeline`、`ml_table_detector`、`table_extractor`、`wireless_table_recovery`、`table_template_engine`、`wired_table_extractor`、`english_table_extractor` 和 `table_header_normalizer`。完整的逐调用点（文件、1-based 行号、调用者、API、参数、用途、Snapshot 字段/阶段、允许层级）仍需从 123 行结果逐项转录；本轮未将其误标为已完成。


## 临时表完整追加：逐调用点清单

以下内容按临时表原文逐行追加，保留逐行字段，不以摘要替代。

# PyMuPDF page-read 调用点审计（扫描行 1–60）

| 扫描行号 | 源文件相对路径 | 1-based 源码行号 | enclosing function/class | API/属性 | 实际 mode/flags/clip/kwargs | 用途 | Snapshot 字段/阶段归属 | 允许层级 | strict spy 规则 |
| ---: | --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | `src/hexai_pdf_parser/extractors/text_extractor.py` | 26 | `TextExtractor.extract_blocks` | `page.get_text("dict")` | mode=`"dict"`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`{flags=fitz.TEXT_PRESERVE_WHITESPACE}` | 读取原始 block/line/span/char 层级，组装公开文字对象。 | `text.raw.blocks/lines/spans/chars`、`raw_source_position`；文字采集阶段 | 算法 | 必须拦截：`capture_page_snapshot` 返回后不得访问原 page；算法只能读 Snapshot。 |
| 2 | `src/hexai_pdf_parser/extractors/text_extractor.py` | 123 | `TextExtractor.extract_layout_blocks` | `page.get_text("dict")` | mode=`"dict"`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`{flags=fitz.TEXT_PRESERVE_WHITESPACE}` | 按 native line 重建页面布局文字，并排除落入表格的 words。 | `text.raw.blocks/lines/spans`；布局文字阶段 | 算法 | 必须拦截：`capture_page_snapshot` 返回后不得访问原 page；算法只能读 Snapshot。 |
| 3 | `src/hexai_pdf_parser/extractors/text_extractor.py` | 297 | `TextExtractor.refine_blocks_for_tables` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 对跨表格边界的 native block 取得 word 坐标并拆分。 | `text.words`（含 block/line/word 索引）；表格边界细化阶段 | 算法 | 必须拦截：`capture_page_snapshot` 返回后不得访问原 page；算法只能读 Snapshot。 |
| 4 | `src/hexai_pdf_parser/ml/ml_table_detector.py` | 162 | `MLTableDetector.detect_with_scores` | `page.rect.width`, `page.rect.height` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 计算页面面积，过滤低置信度的整页误检框。 | `page.geometry.width/height`；ML 检测后处理阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot；不得在算法阶段读取原 page。 |
| 5 | `src/hexai_pdf_parser/ml/ml_table_detector.py` | 173 | `MLTableDetector.detect_with_scores` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 让检测框向相交或接触的文字 words 扩展。 | `text.words`；ML bbox 扩展阶段 | 算法 | 必须拦截：`capture_page_snapshot` 返回后不得调用 `get_text`；扩展逻辑只能消费 Snapshot words。 |
| 6 | `src/hexai_pdf_parser/ml/ml_table_detector.py` | 200 | `MLTableDetector._expand_bbox_to_touching_words` | `page.rect.x0`, `page.rect.y0`, `page.rect.x1`, `page.rect.y1` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 将由 words 扩展后的检测框裁回页面边界。 | `page.geometry.rect`；ML bbox 扩展/边界裁剪阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot；不得在算法阶段读取原 page。 |
| 7 | `src/hexai_pdf_parser/ml/ml_table_detector.py` | 256 | `MLTableDetector._preprocess_page` | `page.get_pixmap` | mode=unknown; flags=unknown; clip=none; kwargs=`{matrix=mat, alpha=False}` | 将页面栅格化为 RGB 图像，供 YOLO 表格检测。 | ML 确定性 raster/预计算特征；ML 输入预处理阶段 | 算法 | 算法调用必须拦截；raster 必须在唯一 Snapshot capture 阶段预计算，不能读取原 page。 |
| 8 | `src/hexai_pdf_parser/ml/ml_table_detector.py` | 262 | `MLTableDetector._preprocess_page` | `page.rect.width`, `pix.width` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 计算 PDF 页面宽度到 pixmap 像素宽度的缩放因子。 | `page.geometry.width` + ML raster `pix.width`；ML 坐标回映阶段 | 算法 | 必须拦截：页面几何读取必须来自 Snapshot；不得在算法阶段读取原 page。 |
| 9 | `src/hexai_pdf_parser/ml/ml_table_detector.py` | 263 | `MLTableDetector._preprocess_page` | `page.rect.height`, `pix.height` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 计算 PDF 页面高度到 pixmap 像素高度的缩放因子。 | `page.geometry.height` + ML raster `pix.height`；ML 坐标回映阶段 | 算法 | 必须拦截：页面几何读取必须来自 Snapshot；不得在算法阶段读取原 page。 |
| 10 | `src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py` | 437 | `_collect_words_in_bbox` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 收集与表头 bbox 相交且非空的 words，形成规范化 token。 | `text.words`；表头候选收集阶段 | 算法 | 必须拦截：`get_text` 只能在 Snapshot capture 阶段调用；normalizer 只能读 Snapshot。 |
| 11 | `src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py` | 1005 | `_find_group_header_band` | `page.get_text("dict")` | mode=`"dict"`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`{flags=fitz.TEXT_PRESERVE_WHITESPACE}` | 在表体上方的 raw span 中查找分组表头文字及 bbox。 | `text.raw.blocks/lines/spans`；分组表头探测阶段 | 算法 | 必须拦截：normalizer 不得在 Snapshot 后回读原 page。 |
| 12 | `src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py` | 1088 | `_merge_header_fragment_with_lower_line` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 查找表头下方 continuation words，合并拆行表头文本和 bbox。 | `text.words`；表头碎片合并阶段 | 算法 | 必须拦截：`get_text` 只能由 Snapshot capture 提供；算法阶段不得回读原 page。 |
| 13 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 26 | `_find_text_line_bboxes` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 按 block/line 索引分组 words，定位个人征信章节标题 anchors。 | `text.words`；个人查询 anchor 定位阶段 | 算法 | 必须拦截：anchor 定位只能消费 Snapshot words。 |
| 14 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 67 | `_query_regions` | `page.rect.width` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 按页面宽度计算左右查询区域的最小横向边距。 | `page.geometry.width`；个人查询区域推断阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 15 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 68 | `_query_regions` | `page.rect.y1`, `page.rect.height` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 按页面高度计算查询区域底边安全边距。 | `page.geometry.y1/height`；个人查询区域推断阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 16 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 70 | `_query_regions` | `page.rect.x1` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 构造机构查询明细区域的右边界。 | `page.geometry.x1`；个人查询区域 bbox 物化阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 17 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 71 | `_query_regions` | `page.rect.x1` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 构造个人查询明细区域的右边界。 | `page.geometry.x1`；个人查询区域 bbox 物化阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 18 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 126 | `_query_rows` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 未启用 merged span 时直接读取 words 并按 y 聚类查询记录行。 | `text.words`；个人查询表行聚类阶段 | 算法 | 必须拦截：`get_text` 只能由 Snapshot capture 提供。 |
| 19 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 208 | `_make_query_table` | `page.rect.width`（位于 `BBox` 参数） | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 为 merged 查询行构造覆盖整页宽度的筛选 bbox。 | `page.geometry.width`；个人查询表 merged 行筛选阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 20 | `src/hexai_pdf_parser/extractors/personal_credit_report.py` | 276 | `_make_query_table` | `page.rect.width` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 物化缺失查询单元格时确定最后一列的右边界。 | `page.geometry.width`；个人查询逻辑 Cell 物化阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 21 | `src/hexai_pdf_parser/core/pipeline.py` | 792 | `Pipeline.run` | `page.rotation` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问，作为 `process_pool.submit` 实参） | 将页面旋转值传给进程 worker，使 worker 在规范化/解析前保持页面方向语义。 | `page.geometry.rotation`；并行页面任务 dispatch 阶段 | 算法 | 必须拦截：worker dispatch 只能使用 Snapshot/page DTO；不得保留并透传原 page。 |
| 22 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 32 | `is_scanned_page` | `page.get_text("text")` | mode=`"text"`; flags=default; clip=none; kwargs=none | 判断页面是否有可提取文字，并检测空文本/乱码分类条件。 | `text.plain` 或由 raw text 派生的分类特征；页面分类阶段 | 算法 | 必须拦截：页面分类只能消费 Snapshot 文字与资源特征。 |
| 23 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 80 | `_check_type3_missing_tounicode` | `page.get_fonts` | mode=unknown; flags=unknown; clip=none; kwargs=`{full=True}` | 枚举字体，检查 Type3 字体及其 ToUnicode 资源。 | `resources.fonts`；字体资源分类阶段 | 算法 | 必须拦截：资源读取必须由 Snapshot capture 完成。 |
| 24 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 89 | `_check_type3_missing_tounicode` | `page.parent` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 判断是否存在可用于读取字体对象的父文档；缺失则判为 scanned。 | `resources.font_xref_objects` 的可用性/父文档探测结果；Type3 资源检查阶段 | 算法 | 必须拦截：`page.parent` 本身也必须被 spy 拦截；不得透传原 document。 |
| 25 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 92 | `_check_type3_missing_tounicode` | `page.parent.xref_object(xref)` | mode=unknown; flags=unknown; clip=none; kwargs=none；positional=`xref` | 读取 Type3 字体 PDF 对象，确认是否含 `/ToUnicode`。 | `resources.font_xref_objects`；字体 ToUnicode 检查阶段 | 算法 | 必须拦截：`page.parent.xref_object` 及父文档透传均不得在 Snapshot 后发生。 |
| 26 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 104 | `_check_bbox_distortion` | `page.get_text("blocks")` | mode=`"blocks"`; flags=default; clip=none; kwargs=none | 以 block bbox 和文本行数检测严重文字 bbox 变形。 | `text.blocks`；页面 bbox 畸变分类阶段 | 算法 | 必须拦截：页面分类只能消费 Snapshot 的 block 几何与文本。 |
| 27 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 108 | `_check_bbox_distortion` | `getattr(page, "rect", None)`、`page.rect.height` | mode=unknown; flags=unknown; clip=unknown; kwargs=`{name="rect", default=None}`（属性探测及访问） | 取得页面高度，作为异常 block 高度的比例阈值。 | `page.geometry.height`；页面 bbox 畸变分类阶段 | 算法 | 必须拦截：等价的 `rect` 探测/属性访问也必须走 Snapshot，不得读取原 page。 |
| 28 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 132 | `_check_vector_outlined_drawings` | `page.get_drawings()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 统计矢量路径/小 glyph drawing，判定文字是否已转曲。 | `drawings`（source order、items、rect/style）；页面分类阶段 | 算法 | 必须拦截：`get_drawings` 只能在 Snapshot capture 阶段调用。 |
| 29 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 169 | `_has_fullpage_raster_image` | `page.get_images()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 枚举页面图片资源，判断是否存在整页栅格背景。 | `resources.images`；页面栅格分类阶段 | 算法 | 必须拦截：图片资源必须由 Snapshot capture 提供。 |
| 30 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 172 | `_has_fullpage_raster_image` | `page.rect.width`, `page.rect.height` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 计算页面面积以比较图片覆盖比例。 | `page.geometry.width/height`；整页图片覆盖判定阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 31 | `src/hexai_pdf_parser/extractors/page_classifier.py` | 175 | `_has_fullpage_raster_image` | `page.get_image_rects(xref)` | mode=unknown; flags=unknown; clip=none; kwargs=none；positional=`xref` | 取得图片在页面上的 bbox，判定覆盖页面面积是否达到 60%。 | `resources.image_rects`；整页图片覆盖判定阶段 | 算法 | 必须拦截：图片 bbox 必须由 Snapshot capture；不得调用原 page。 |
| 32 | `src/hexai_pdf_parser/tables/table_template_engine.py` | 308 | `TemplateEngine._collect_header_rows` | `page.get_text("words", clip=clip)` | mode=`"words"`; flags=default; clip=`fitz.Rect(table_bbox.x0 - 10.0, max(0.0, region_rows[0]["y0"] - 40.0), table_bbox.x1 + 10.0, header_bottom + 2.0)`；kwargs=`{clip=clip}` | 在表格上方裁剪带内提取 words，收集模板表头行并校验 zone。 | `text.words` + extraction option `clip`；模板表头收集阶段 | 算法 | 必须拦截：Snapshot 必须保存带 clip 的确定性 words 结果；normalizer/模板算法不得回读原 page。 |
| 33 | `src/hexai_pdf_parser/core/pdf_parser.py` | 402 | `PDFParser._get_page_sizes` | `doc[i].rect.width`, `doc[i].rect.height` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（页面几何属性访问） | 在无缓存文档时为所有页面建立归一化区域所需的尺寸表。 | 各页 `page.geometry.width/height`；区域归一化前置阶段 | 算法 | 必须拦截：等价 page/document content object 访问不得进入 Snapshot 后算法；尺寸应来自 Snapshot。 |
| 34 | `src/hexai_pdf_parser/core/pdf_parser.py` | 443 | `PDFParser.extract_text_in_region._do` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 对每个区域读取 words，按 bbox 相交匹配并保留 block/line 结构。 | `text.words`；区域文字提取阶段 | 算法 | 必须拦截：区域提取只能消费 Snapshot words；不得在算法阶段打开/读取原 page。 |
| 35 | `src/hexai_pdf_parser/core/pdf_parser.py` | 666 | `PDFParser.render_region._do` | `page_handle.get_pixmap` | mode=unknown; flags=unknown; clip=`clip=_fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])`; kwargs=`{matrix=mat, clip=clip}` | 将指定区域渲染为 PNG，并保存渲染结果。 | 不进入算法 Snapshot；后置 PNG renderer 阶段 | 渲染 | 算法阶段必须拦截；仅算法完成后的 renderer 可读取原 page/page handle。 |
| 36 | `src/hexai_pdf_parser/tables/table_extractor.py` | 230 | `TableExtractor._refine_overlapping_model_bboxes` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 在相邻模型框的垂直重叠带内找 words，决定切分 y。 | `text.words`；模型框重叠细化阶段 | 算法 | 必须拦截：重叠细化只能消费 Snapshot words。 |
| 37 | `src/hexai_pdf_parser/tables/table_extractor.py` | 232 | `TableExtractor._refine_overlapping_model_bboxes` | `page.get_drawings()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 在模型框重叠带内找线/矩形 drawing，辅助决定切分 y。 | `drawings.items`（line/rect）；模型框重叠细化阶段 | 算法 | 必须拦截：重叠细化只能消费 Snapshot drawings。 |
| 38 | `src/hexai_pdf_parser/tables/table_extractor.py` | 722 | `TableExtractor.extract` | `page.number` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 在 debug pipeline payload 中记录页号。 | `page_index`；pipeline debug payload 初始化阶段 | 调试 | 必须拦截算法后的原 page 访问；调试字段应从 Snapshot 派生，后置 renderer 才可例外读取原 page。 |
| 39 | `src/hexai_pdf_parser/tables/table_extractor.py` | 723 | `TableExtractor.extract` | `page.rect`（传给 `_rect_to_dict`） | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 在 debug pipeline payload 中记录页面 bbox。 | `page.geometry.rect`；pipeline debug payload 初始化阶段 | 调试 | 必须拦截算法后的原 page 访问；调试字段应从 Snapshot 派生，后置 renderer 才可例外读取原 page。 |
| 40 | `src/hexai_pdf_parser/tables/table_extractor.py` | 774 | `TableExtractor._clamp_table_to_page` | `page.rect.x0` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 取得页面左边界，裁剪表格及 Cell bbox。 | `page.geometry.x0`；表格/Cell 边界裁剪阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 41 | `src/hexai_pdf_parser/tables/table_extractor.py` | 775 | `TableExtractor._clamp_table_to_page` | `page.rect.y0` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 取得页面上边界，裁剪表格及 Cell bbox。 | `page.geometry.y0`；表格/Cell 边界裁剪阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 42 | `src/hexai_pdf_parser/tables/table_extractor.py` | 776 | `TableExtractor._clamp_table_to_page` | `page.rect.x1` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 取得页面右边界，裁剪表格及 Cell bbox。 | `page.geometry.x1`；表格/Cell 边界裁剪阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 43 | `src/hexai_pdf_parser/tables/table_extractor.py` | 777 | `TableExtractor._clamp_table_to_page` | `page.rect.y1` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 取得页面下边界，裁剪表格及 Cell bbox。 | `page.geometry.y1`；表格/Cell 边界裁剪阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 44 | `src/hexai_pdf_parser/tables/table_extractor.py` | 825 | `TableExtractor._capture_drawings` | `page.get_drawings()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 把 drawing 的类型、颜色、填充、线宽、dashes 及 line/rect items 序列化到 debug payload。 | `drawings.source_order/items/style/extended`；debug drawing capture 阶段 | 调试 | 必须拦截原 page 读取；该调试 payload 应从唯一 Snapshot drawings 生成，不能以 debug 名义绕过 spy。 |
| 45 | `src/hexai_pdf_parser/tables/table_extractor.py` | 891 | `TableExtractor.extract_table_structure` | `page.get_text("dict")` | mode=`"dict"`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`{flags=fitz.TEXT_PRESERVE_WHITESPACE}` | 为每个表格 Cell 提供字符级 text block，用于结构化结果。 | `text.raw.blocks/lines/spans/chars`；表格结构输出阶段 | 算法 | 必须拦截：结构化算法只能消费 Snapshot raw text。 |
| 46 | `src/hexai_pdf_parser/tables/table_extractor.py` | 944 | `TableExtractor._collect_page_text_lines` | `page.get_text("dict")` | mode=`"dict"`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`{flags=fitz.TEXT_PRESERVE_WHITESPACE}` | 汇总页面每个 native line 文本，生成 profile matching 特征。 | `text.raw.blocks/lines/spans` 派生的 `text_lines`；profile 匹配阶段 | 算法 | 必须拦截：profile/布局算法不得回读原 page。 |
| 47 | `src/hexai_pdf_parser/tables/table_extractor.py` | 971 | `TableExtractor._apply_layout_rules` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 启用 profile region rules 时，按 words 构造候选区域并应用布局规则。 | `text.words`；layout rule/region candidate 阶段 | 算法 | 必须拦截：候选循环只能消费 Snapshot words。 |
| 48 | `src/hexai_pdf_parser/tables/table_extractor.py` | 1161 | `TableExtractor._get_bboxlog` | `page.get_bboxlog()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 取得绘制顺序 bbox log，用于识别后续覆盖的填充矩形。 | `drawings.bboxlog`；drawing 遮挡预过滤阶段 | 算法 | 必须拦截：`get_bboxlog` 只能在 Snapshot capture 阶段读取。 |
| 49 | `src/hexai_pdf_parser/tables/table_extractor.py` | 1234 | `TableExtractor._iter_effective_drawing_rects` | `page.get_drawings()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 枚举未被后续遮挡且可见的矩形 drawing，供线框提取。 | `drawings.items/rect/style` + `drawings.bboxlog`；有效 drawing 过滤阶段 | 算法 | 必须拦截：drawing 过滤只能消费 Snapshot。 |
| 50 | `src/hexai_pdf_parser/tables/table_extractor.py` | 1271 | `TableExtractor._extract_lines_from_drawings` | `page.rect.width`, `page.rect.height` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 以页面面积限制普通矩形的线框分解，避免整页背景产生表格线。 | `page.geometry.width/height`；有线几何 drawing 过滤阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 51 | `src/hexai_pdf_parser/tables/table_extractor.py` | 1296 | `TableExtractor._extract_lines_from_drawings` | `page.get_drawings()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 提取 drawing 中的可见 line item，并生成水平/垂直候选线。 | `drawings.items/line/style`；有线候选线提取阶段 | 算法 | 必须拦截：`get_drawings` 只能在 Snapshot capture 阶段调用。 |
| 52 | `src/hexai_pdf_parser/tables/table_extractor.py` | 1493 | `TableExtractor._get_character_bboxes_and_height_mode` | `page.get_text("rawdict")` | mode=`"rawdict"`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`{flags=fitz.TEXT_PRESERVE_WHITESPACE}`（调用延续至 1495 行） | 收集非空字符 bbox 并计算字符高度众数，辅助文本对齐/切分。 | `text.raw.blocks/lines/spans/chars`；字符 bbox 与高度模式阶段 | 算法 | 必须拦截：字符级算法只能消费 Snapshot raw text/chars。 |
| 53 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3013 | `TableExtractor._extract_text_based_separators` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | 识别由短横线、下划线等文字字符形成的水平分隔线。 | `text.words`；文本分隔线检测阶段 | 算法 | 必须拦截：分隔线算法只能消费 Snapshot words。 |
| 54 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3029 | `TableExtractor._extract_text_based_separators` | `page.rect.width` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 取得页面宽度（当前逻辑用于 separator 检测上下文）。 | `page.geometry.width`；文本分隔线检测阶段 | 算法 | 必须拦截：页面几何只能来自 Snapshot。 |
| 55 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3062 | `TableExtractor._extract_drawing_separators` | `page.get_drawings()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 从矩形/line drawing 中识别水平分隔线。 | `drawings.items/rect/line/style`；drawing 分隔线检测阶段 | 算法 | 必须拦截：分隔线算法只能消费 Snapshot drawings。 |
| 56 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3176 | `TableExtractor._detect_text_regions` | `page.rect.width`（`detect_separator_driven_regions` 实参） | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 在 separator 驱动的候选区域推断中传入页面宽度。 | `page.geometry.width`；文本区域候选/分隔线驱动阶段 | 算法 | 必须拦截：候选区域算法只能从 Snapshot 取得页面宽度。 |
| 57 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3362 | `TableExtractor._extract_legacy_text_alignment` | `page.get_text("words")` | mode=`"words"`; flags=default; clip=none; kwargs=none | legacy text-alignment fallback 读取 words，构造行、列 guide 和候选区域。 | `text.words`；legacy text alignment 阶段 | 算法 | 必须拦截：算法不得回读 words；应消费 Snapshot words（并遵守 native-span 新路径门禁）。 |
| 58 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3600 | `TableExtractor._extract_legacy_text_alignment` | `page.number` | mode=unknown; flags=unknown; clip=unknown; kwargs=unknown（属性访问） | 在有 debug region 时记录 text-alignment 调试结果所属页号。 | `page_index`；text-alignment debug payload 阶段 | 调试 | 必须拦截原 page 访问；debug payload 应从 Snapshot 的 `page_index` 派生。 |
| 59 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3645 | `TableExtractor.capture_text_alignment_snapshot` | `page.get_text("words", clip=fitz.Rect(...))` | mode=`"words"`; flags=default; clip=`fitz.Rect(region_bbox.x0, region_bbox.y0, region_bbox.x1, region_bbox.y1)`；kwargs=`{clip=fitz.Rect(...)}`（调用延续至 3653 行） | 捕获可信 text region 的 rows 与 column guides，生成可重放的 JSON 结构阶段输入。 | `text.words` 的 region 派生视图、`allowed_regions`/region bbox；结构阶段输入 snapshot capture | 调试 | 该函数本身只能作为唯一 capture 阶段读取；返回后算法必须被 spy 拦截，且同页不得再次读取原 page。 |
| 60 | `src/hexai_pdf_parser/tables/table_extractor.py` | 3790 | `TableExtractor._text_alignment_postprocess_input` | `page.get_drawings()` | mode=unknown; flags=unknown; clip=none; kwargs=none | 为 page-free Rust postprocess DTO 提取水平 line/rect y 坐标。 | `drawings.items` 的水平线派生视图；text-alignment postprocess DTO 构造阶段 | 算法 | 必须拦截：postprocess DTO 构造只能消费 Snapshot drawings；不得因 `page` 可选而绕过 spy。 |

# 页面读取调用点审计：扫描行 61-123

| 扫描行号 | 源文件相对路径 | 1-based 源码行号 | enclosing function/class | API/属性 | 实际 mode/flags/clip/kwargs | 用途 | Snapshot 字段/阶段归属 | 允许层级（算法/渲染/调试） | strict spy 规则 |
| ---: | --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| 61 | `src/hexai_pdf_parser/tables/table_extractor.py` | 4246 | `TableExtractor._detect_columns_from_header_lines` | `page.get_drawings()` | mode=unknown; flags=none; clip=none; kwargs=none | 读取绘图项，从物理横线推断列边界和表头列结构 | `drawings.source_order/items`；text-alignment 的 header-line column inference 阶段 | 算法 | `capture_page_snapshot` 后必须拦截；算法只能消费 Snapshot 的 drawing DTO |
| 62 | `src/hexai_pdf_parser/tables/table_extractor.py` | 4586 | `TableExtractor._infer_sparse_rowspans` | `page.get_drawings()` | mode=unknown; flags=none; clip=none; kwargs=none | 读取线段以辅助稀疏行的 rowspan 推断 | `drawings.items` 的 line 几何；text-alignment rowspan 阶段 | 算法 | 必须拦截；不得在 rowspan 候选循环中回读原 page |
| 63 | `src/hexai_pdf_parser/tables/table_extractor.py` | 4869 | `TableExtractor._merge_continuation_rows` | `page.get_drawings()` | mode=unknown; flags=none; clip=none; kwargs=none | 读取线段以判断续行边界并合并 continuation rows | `drawings.items`；text-alignment continuation-row 阶段 | 算法 | 必须拦截；续行算法只能接收 Snapshot/不可变派生视图 |
| 64 | `src/hexai_pdf_parser/tables/table_extractor.py` | 5076 | `TableExtractor._collect_header_rows_via_spans` | `page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)` | mode=`dict`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`flags=...` | 收集分隔线以上的 block/line/span 文本，识别最多三层表头 | `raw_text.blocks/lines/spans`、字符与 `raw_source_position`；span-header 阶段 | 算法 | 必须拦截；Snapshot 必须保留等价 dict 层级和精确 flags |
| 65 | `src/hexai_pdf_parser/tables/table_extractor.py` | 5189 | `TableExtractor._assign_text_to_cells` | `page.get_text("words", clip=rect)` | mode=`words`; flags=default/unknown; clip=`rect = fitz.Rect(x0 - 5, y0 - 5, x1 + 5, y1 + 5)`; kwargs=`clip=rect` | 在 cell 联合 bbox 周边读取 words，并按视觉行把文本分配到 Cell | `words` 及 block/line/word 索引；cell text assignment 阶段 | 算法 | 必须拦截；Snapshot words 查询必须保留等价 clip 语义 |
| 66 | `src/hexai_pdf_parser/tables/table_extractor.py` | 5666 | `TableExtractor._extract_via_pymupdf` | `page.find_tables()` | mode=unknown; flags=none; clip=none; kwargs=none | PyMuPDF 表格识别 fallback，转换其 table/cell 结果 | `table_fallback.find_tables`；fallback extraction 阶段 | 算法 | 必须拦截；结果应来自 Snapshot 的 table-fallback 字段，不得透传 page |
| 67 | `src/hexai_pdf_parser/core/loader.py` | 41 | `Loader.load` / `Loader` | `page.rect` | mode=属性访问; flags=none; clip=none; kwargs=none | 读取页面尺寸，构造公开 `Page.size` | `page.geometry.rect/width/height`；document loading 阶段 | 算法 | 算法访问必须拦截；Loader 只能读取已捕获 PageDto geometry |
| 68 | `src/hexai_pdf_parser/core/loader.py` | 48 | `Loader.load` / `Loader` | `page.rotation` | mode=属性访问; flags=none; clip=none; kwargs=none | 保存页面旋转角到公开 `Page` 模型 | `page.geometry.rotation`；document loading 阶段 | 算法 | 必须拦截；只能从 Snapshot PageDto 读取 rotation |
| 69 | `src/hexai_pdf_parser/extractors/language_detector.py` | 24 | `detect_page_language` | `page.get_text("text")` | mode=`text`; flags=default/unknown; clip=none; kwargs=none | 统计单页中文字符与总字符，判定 zh/en/mixed | `raw_text.full_text` 或等价 language-text 派生字段；page language classification 阶段 | 算法 | 必须拦截；语言分类不得在 Snapshot 后调用 page.get_text |
| 70 | `src/hexai_pdf_parser/extractors/language_detector.py` | 68 | `detect_document_language` | `doc[i].get_text("text")` | mode=`text`; flags=default/unknown; clip=none; kwargs=none; receiver=`doc[i]` | 读取采样页全文，汇总文档级语言比例 | 每个采样页的 `raw_text.full_text`、`page_index=i`；document language sampling 阶段 | 算法 | 必须拦截同等 page/document 读取；采样应遍历已有 Snapshot，而不是 doc page |
| 71 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 239 | `collect_native_spans` | `page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)` | mode=`rawdict`; flags=`fitz.TEXT_PRESERVE_WHITESPACE`; clip=none; kwargs=`flags=...` | 保留 native span 顺序、block/line/span 层级、字符 bbox，过滤 footer 并构造 NativeSpan | `raw_text.blocks/lines/spans/chars`、`raw_source_position`、精确 extraction options；native-span collection 阶段 | 算法 | 必须拦截；这是 native-span 唯一页面文字入口，后续结构恢复不得回读 words |
| 72 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 253 | `collect_native_spans` | `page.rect.y0`, `page.rect.height` | mode=属性访问; flags=none; clip=none; kwargs=none | 用页面底部 85% 几何阈值过滤页码 footer | `page.geometry.y0/height`；native-span filtering 阶段 | 算法 | 必须拦截；footer 判定只读 Snapshot geometry |
| 73 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1155 | `_recover_wireless_tables_python` | `page.number` | mode=属性访问; flags=none; clip=none; kwargs=none | 写入 wireless diagnostics 的 `page_index` | `page_index`；Python wireless recovery diagnostics 阶段 | 算法 | 必须拦截；诊断页号来自 Snapshot，不能保留原 page 引用 |
| 74 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1220 | `recover_wireless_tables._recover_wireless_tables_rust` | `page.rect.width` | mode=属性访问; flags=none; clip=none; kwargs=none | 构造 page-free Rust DTO 的页面宽度 | `page.geometry.width` / `PageDto.width`；Rust wireless input adaptation 阶段 | 算法 | 必须拦截；Rust input 只能从 Snapshot PageDto 构造 |
| 75 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1221 | `recover_wireless_tables._recover_wireless_tables_rust` | `page.rect.height` | mode=属性访问; flags=none; clip=none; kwargs=none | 构造 page-free Rust DTO 的页面高度 | `page.geometry.height` / `PageDto.height`；Rust wireless input adaptation 阶段 | 算法 | 必须拦截；不得从原 page 读取高度 |
| 76 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1227 | `recover_wireless_tables._recover_wireless_tables_rust` | `page.rect.width` | mode=属性访问; flags=none; clip=none; kwargs=none | 创建 full-page `BBox.x1` | `page.geometry.width`；full-page region DTO 构造阶段 | 算法 | 必须拦截；full-page region 必须由 Snapshot geometry 生成 |
| 77 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1228 | `recover_wireless_tables._recover_wireless_tables_rust` | `page.rect.height` | mode=属性访问; flags=none; clip=none; kwargs=none | 创建 full-page `BBox.y1` | `page.geometry.height`；full-page region DTO 构造阶段 | 算法 | 必须拦截；不得把 page.rect 传入 Rust 或候选对象 |
| 78 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1321 | `export_wireless_debug` | `page.number` | mode=属性访问; flags=none; clip=none; kwargs=none; format=`03d` | 生成 debug JSON/HTML/PNG 的 `page-XXX-wireless` 文件名 | 不进入算法 Snapshot；debug artifact naming 的 page index | 调试 | 算法 spy 必须拦截；仅算法完成后的 debug renderer 可按后置规则读取 |
| 79 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1333 | `export_wireless_debug` | `page.rect.width`, `page.rect.height` | mode=属性访问; flags=none; clip=none; kwargs=`overlay.new_page(width=..., height=...)` | 创建与原页面同尺寸的 overlay PDF 页 | 不进入算法 Snapshot；debug PNG renderer geometry | 渲染/调试 | 不得成为算法 spy 豁免；仅允许算法完成后的后置 renderer 读取 |
| 80 | `src/hexai_pdf_parser/tables/wireless_table_recovery.py` | 1334 | `export_wireless_debug` | `overlay_page.rect`, `page.parent`, `page.number` via `overlay_page.show_pdf_page(...)` | mode=renderer call; flags=none; clip=`overlay_page.rect`; kwargs=`page.parent`, `page.number` | 将原 PDF 页铺到 overlay，供 debug PNG 覆盖绘制 | 不进入算法 Snapshot；debug overlay renderer content/page handle | 渲染/调试 | 算法阶段 strict spy 仍必须拦截 `page.parent`/`page.number`；只允许后置 renderer |
| 81 | `src/hexai_pdf_parser/extractors/image_extractor.py` | 51 | `ImageExtractor.extract_page` / `ImageExtractor` | `page.get_images(full=True)` | mode=images; flags=none; clip=none; kwargs=`full=True` | 枚举页面图片及 xref，配合 image info 抽取图片 | `resources.images`；image extraction resource enumeration 阶段 | 算法 | 必须拦截；算法消费 Snapshot images DTO |
| 82 | `src/hexai_pdf_parser/extractors/image_extractor.py` | 52 | `ImageExtractor.extract_page` / `ImageExtractor` | `page.get_image_info(xrefs=True)` | mode=image_info; flags=none; clip=none; kwargs=`xrefs=True` | 获取图片 bbox/xref 元数据并建立 `bbox_by_xref` | `resources.image_info` 与 image bbox；image extraction stage | 算法 | 必须拦截；Snapshot 必须保留 xrefs 选项及 bbox |
| 83 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 124 | `WiredTableExtractor.extract` / `WiredTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | 页面级缓存 words，避免每个 wired table region 重复读取 | `words`、block/line/word 索引；wired extraction page cache stage | 算法 | 必须拦截；后续 region 算法只能消费共享 Snapshot words |
| 84 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 130 | `WiredTableExtractor.extract` / `WiredTableExtractor` | `page.get_text("rawdict")` | mode=`rawdict`; flags=default/unknown; clip=none; kwargs=none | 页面级缓存 raw chars 的 bbox 与字符文本 | `raw_text.blocks/lines/spans/chars`；wired raw-character cache stage | 算法 | 必须拦截；Snapshot 需保留 rawdict 层级和默认选项 |
| 85 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 372 | `WiredTableExtractor.extract.add_v_line` / `WiredTableExtractor` | `page.rect.width * page.rect.height` | mode=属性访问; flags=none; clip=none; kwargs=none | 计算页面面积，区分封闭描边矩形/图形 mask 与真实表格线 | `page.geometry.width/height`；wired line candidate filtering stage | 算法 | 必须拦截；面积判断必须使用 Snapshot geometry |
| 86 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 373 | `WiredTableExtractor.extract.add_v_line` / `WiredTableExtractor` | `hasattr(page, "rect")`, `page.rect` | mode=属性探测+属性访问; flags=none; clip=none; kwargs=none | 检查并读取页面面积的可用性，失败时使用 `1e9` fallback | `page.geometry`；wired line candidate filtering stage | 算法 | strict spy 对 `hasattr`/实际 rect 读取均不得提供算法豁免；改由 Snapshot 存在性和值表达 |
| 87 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 787 | `WiredTableExtractor._get_drawings_with_clips` / `WiredTableExtractor` | `page.get_drawings(extended=True)` | mode=drawings; flags=none; clip=none; kwargs=`extended=True` | 读取带 clip 层级的绘图，恢复 active PDF clip rectangles | `drawings.source_order/items/extended/clip metadata`；wired drawing collection stage | 算法 | 必须拦截；Snapshot drawing DTO 必须保留 extended 与 clip 信息 |
| 88 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 790 | `WiredTableExtractor._get_drawings_with_clips` / `WiredTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | extended 参数不可用时的兼容 fallback 绘图读取 | `drawings.source_order/items`；wired drawing collection fallback stage | 算法 | 必须拦截；strict spy 不能因 fallback 而允许二次 page read |
| 89 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 839 | `WiredTableExtractor._get_active_clip_rect` / `WiredTableExtractor` | `page.rect` | mode=属性访问并传入`fitz.Rect`; flags=none; clip=none; kwargs=none | 以页面 rect 初始化可见区域，再与父 clip 相交 | `page.geometry.rect`；wired active-clip reconstruction stage | 算法 | 必须拦截；clip 相交只能消费 Snapshot geometry/drawing clip DTO |
| 90 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 855 | `WiredTableExtractor._get_type3_character_regions` / `WiredTableExtractor` | `page.get_fonts(full=True)` | mode=fonts; flags=none; clip=none; kwargs=`full=True` | 找出 Type3 字体资源，定位需要特殊字符区域的字体名 | `resources.fonts`、font xref/object metadata；wired Type3 detection stage | 算法 | 必须拦截；Snapshot 需保留 full font tuples 或等价资源 DTO |
| 91 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 860 | `WiredTableExtractor._get_type3_character_regions` / `WiredTableExtractor` | `page.get_text("rawdict")` | mode=`rawdict`; flags=default/unknown; clip=none; kwargs=none | 读取字符 bbox，恢复 Type3 字符区域 | `raw_text.blocks/lines/spans/chars`；wired Type3 character-region stage | 算法 | 必须拦截；rawdict 必须由同一 Snapshot 提供 |
| 92 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 936 | `WiredTableExtractor._extract_lines_from_tiled_images` / `WiredTableExtractor` | `page.get_image_info(xrefs=True)` | mode=image_info; flags=none; clip=none; kwargs=`xrefs=True` | 从连续一/二像素图片 tile 恢复水平、垂直规则线 | `resources.image_info`、image bbox；wired tiled-image line recovery stage | 算法 | 必须拦截；只能消费 Snapshot image_info，不得重新取图像信息 |
| 93 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 997 | `WiredTableExtractor._estimate_page_background_color` / `WiredTableExtractor` | `page.get_pixmap(...)` | mode=pixmap; flags=none; clip=none; kwargs=`matrix=fitz.Matrix(0.1, 0.1), colorspace=fitz.csRGB, alpha=False` | 低分辨率栅格采样页面背景色 | `ml.raster`/deterministic raster preprocessing feature；wired background analysis stage | 算法 | 算法调用必须拦截；预计算 raster 进入 Snapshot，只有后置 renderer 可读取原 page |
| 94 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 2227 | `WiredTableExtractor._assign_text_to_line_cells` / `WiredTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | words 未由调用者传入时读取并分配到 wired line cells | `words`；wired cell text assignment stage | 算法 | 必须拦截；优先消费 extract 阶段共享 Snapshot words |
| 95 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 2233 | `WiredTableExtractor._assign_text_to_line_cells` / `WiredTableExtractor` | `page.get_text("rawdict")` | mode=`rawdict`; flags=default/unknown; clip=none; kwargs=none | raw chars 未由调用者传入时读取，补充字符级文本/坐标 | `raw_text.blocks/lines/spans/chars`；wired cell text assignment stage | 算法 | 必须拦截；不得在 cell 分配过程中回读 rawdict |
| 96 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 2318 | `WiredTableExtractor._assign_text_to_line_cells_python` / `WiredTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | Python fallback 的 wired words 读取与 cell 分配 | `words`；wired Python fallback cell assignment stage | 算法 | 必须拦截；fallback 也只能读取 Snapshot |
| 97 | `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` | 2325 | `WiredTableExtractor._assign_text_to_line_cells_python` / `WiredTableExtractor` | `page.get_text("rawdict")` | mode=`rawdict`; flags=default/unknown; clip=none; kwargs=none | Python fallback 构造 raw character cache | `raw_text.blocks/lines/spans/chars`；wired Python fallback stage | 算法 | 必须拦截；同一页面不能因 Python fallback 二次读取 |
| 98 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 142 | `EnglishTableExtractor._english_horizontal_lines` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 读取英文无线/斑马表格的水平线 | `drawings.items`；English horizontal-line detection stage | 算法 | 必须拦截；消费 Snapshot drawings |
| 99 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 423 | `EnglishTableExtractor._has_physical_row_span` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 检查跨行物理线证据 | `drawings.items`；English physical-rowspan detection stage | 算法 | 必须拦截；rowspan 判断不能回读原 page |
| 100 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 595 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | 扩展给定 table bbox，吸收其内 words 的实际几何边界 | `words`；English general-wireless bbox expansion stage | 算法 | 必须拦截；Snapshot words 查询需支持同等区域过滤 |
| 101 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 605 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.rect.x0` | mode=属性访问; flags=none; clip=none; kwargs=none | 将扩展 bbox 的 x0 裁剪到页面左边界 | `page.geometry.x0`；English bbox normalization stage | 算法 | 必须拦截；只读 Snapshot geometry |
| 102 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 606 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.rect.y0` | mode=属性访问; flags=none; clip=none; kwargs=none | 将扩展 bbox 的 y0 裁剪到页面上边界 | `page.geometry.y0`；English bbox normalization stage | 算法 | 必须拦截；只读 Snapshot geometry |
| 103 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 607 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.rect.x1` | mode=属性访问; flags=none; clip=none; kwargs=none | 将扩展 bbox 的 x1 裁剪到页面右边界 | `page.geometry.x1`；English bbox normalization stage | 算法 | 必须拦截；只读 Snapshot geometry |
| 104 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 608 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.rect.y1` | mode=属性访问; flags=none; clip=none; kwargs=none | 将扩展 bbox 的 y1 裁剪到页面下边界 | `page.geometry.y1`；English bbox normalization stage | 算法 | 必须拦截；只读 Snapshot geometry |
| 105 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 614 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | 读取英文无线表格候选 words，随后按 table bbox 过滤 | `words`；English general-wireless word collection stage | 算法 | 必须拦截；不得因与 line 100 分属不同阶段而重复 page read |
| 106 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 631 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.get_drawings() if page else []` | mode=drawings; flags=none; clip=none; kwargs=none; null fallback=`[]` | 提取水平线段与 zebra 背景色块，辅助行/子表/表头划分 | `drawings.items` 的 line/rect/style；English general-wireless geometry stage | 算法 | page 存在时必须拦截；`page is None` 分支只允许空值，不构造 spy 豁免 |
| 107 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 730 | `EnglishTableExtractor.extract_general_wireless` / `EnglishTableExtractor` | `page.get_text("blocks") if page else []` | mode=`blocks`; flags=default/unknown; clip=none; kwargs=none; null fallback=`[]` | 读取文本块以辅助多条表头下划线的分段 | `raw_text.blocks`；English header separator split stage | 算法 | page 存在时必须拦截；Snapshot block 索引替代读取 |
| 108 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1046 | `EnglishTableExtractor.extract_zebra` / `EnglishTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | zebra 路径中获取页面 words，用于背景带和文本行处理 | `words`；English zebra extraction stage | 算法 | 必须拦截；算法只能消费 Snapshot words |
| 109 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1066 | `EnglishTableExtractor.extract_zebra` / `EnglishTableExtractor` | `page.get_text("blocks")` | mode=`blocks`; flags=default/unknown; clip=none; kwargs=none | zebra 路径中过滤非空文本块，确定背景组/表格范围 | `raw_text.blocks`；English zebra block analysis stage | 算法 | 必须拦截；不得回读 blocks |
| 110 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1135 | `EnglishTableExtractor.extract_zebra` / `EnglishTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | 在两条背景带之间找 gap words，判断是否存在正文/续行 | `words`；English zebra gap analysis stage | 算法 | 必须拦截；gap 分析消费 Snapshot words |
| 111 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1166 | `EnglishTableExtractor.extract_zebra` / `EnglishTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | 检查最后填充背景后 table bbox 内是否有底部文字，补充白色背景行 | `words`；English zebra bottom-band completion stage | 算法 | 必须拦截；不得因仅用于补背景而绕过读取门禁 |
| 112 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1188 | `EnglishTableExtractor._process_zebra_group` / `EnglishTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | 处理 zebra group 前重新获取页面 words | `words`；English zebra group processing stage | 算法 | 必须拦截；应复用同一 Snapshot words |
| 113 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1231 | `EnglishTableExtractor._process_zebra_group` / `EnglishTableExtractor` | `page.get_text("words")` | mode=`words`; flags=default/unknown; clip=none; kwargs=none | 读取 zebra group words，构造行/列和 cell 文本 | `words`；English zebra group cell-building stage | 算法 | 必须拦截；不得在组处理阶段重复读取 page |
| 114 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1301 | `EnglishTableExtractor._merge_wrapped_label_rows` / `EnglishTableExtractor` | `page.get_text("blocks")` | mode=`blocks`; flags=default/unknown; clip=none; kwargs=none | 获取 text blocks，合并包裹的 label rows | `raw_text.blocks`；English wrapped-label row merge stage | 算法 | 必须拦截；只能接收 Snapshot block 视图 |
| 115 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1319 | `EnglishTableExtractor._merge_wrapped_label_rows` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 获取物理横线 y 坐标，辅助包裹行合并 | `drawings.items`；English wrapped-label physical-line stage | 算法 | 必须拦截；不能从候选处理中重新取 drawings |
| 116 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1385 | `EnglishTableExtractor._detect_row_backgrounds` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 检测填充色背景矩形/带并生成 row backgrounds | `drawings.items` 的 rect/fill/style；English row-background stage | 算法 | 必须拦截；Snapshot drawings 要保留 fill/style |
| 117 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 1538 | `EnglishTableExtractor._detect_header_rows` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 读取横线和背景绘图，识别表头行层级 | `drawings.items`；English header-row detection stage | 算法 | 必须拦截；不得让 header candidate 保存原 page |
| 118 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 2334 | `EnglishTableExtractor._detect_columns_from_header_underlines` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 从表头下划线绘图推断英文表格列边界 | `drawings.items` 的 line 几何；English underline column inference stage | 算法 | 必须拦截；只消费 Snapshot drawings |
| 119 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 3025 | `EnglishTableExtractor._normalize_headers` / `EnglishTableExtractor` | `page.get_drawings() if page else []` | mode=drawings; flags=none; clip=none; kwargs=none; null fallback=`[]` | 用绘图横线辅助表头归一化及列/分隔判断 | `drawings.items`；English header normalization stage | 算法 | page 存在时必须拦截；空 page 分支不能豁免后续访问 |
| 120 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 3710 | `EnglishTableExtractor._build_wireless_table_python` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 构造英文无线表时读取物理横线，补 row/section 边界 | `drawings.items`；English wireless table assembly stage | 算法 | 必须拦截；表格装配不得读取原 page |
| 121 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 4325 | `EnglishTableExtractor.extract_cells_from_region` / `EnglishTableExtractor` | `page.get_text("words", clip=fitz.Rect(region_bbox.x0, region_bbox.y0, region_bbox.x1, region_bbox.y1))` | mode=`words`; flags=default/unknown; clip=`fitz.Rect(region_bbox.x0, region_bbox.y0, region_bbox.x1, region_bbox.y1)`; kwargs=`clip=...` | 从可信 region 读取 words，再按中心点做 ±2 的二次区域过滤并恢复网格 | `words`、region clip/options；English region cell extraction stage | 算法 | 必须拦截；Snapshot words 查询必须保留 region clip 及后续过滤语义 |
| 122 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 4351 | `EnglishTableExtractor.extract_cells_from_region` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 读取可信区域内物理横线，恢复行边界 | `drawings.items`；English region cell extraction line stage | 算法 | 必须拦截；恢复网格只能消费 Snapshot drawings |
| 123 | `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` | 4635 | `EnglishTableExtractor._detect_columns_from_header_lines` / `EnglishTableExtractor` | `page.get_drawings()` | mode=drawings; flags=none; clip=none; kwargs=none | 读取 header line drawings，推断英文表格列边界 | `drawings.items`；English header-line column inference stage | 算法 | 必须拦截；Snapshot 后不得再次调用 get_drawings |

## 首轮扫描独有调用点

以下 4 行只出现在首轮结果 `pymupdf-read-scan.txt`，不出现在 `pymupdf-page-read-scan.txt`。它们是 `CachedPage` 对 `self._page` 的透传/缓存边界；调用方实际传入的 mode、flags、clip 未知。

| 源文件相对路径 | 1-based 源码行号 | enclosing function/class | API/属性 | 实际 mode/flags/clip/kwargs | 用途 | Snapshot 字段/阶段归属 | 允许层级 | strict spy 规则 |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| `src/hexai_pdf_parser/core\\page_cache.py` | 40 | `CachedPage.get_text` | `self._page.get_text(*args, **kwargs)` | mode/flags/clip=调用方未知；kwargs=调用方未知 | `get_text` 缓存未命中时向 `self._page` 透传调用，并缓存返回值。 | 读取缓存边界；对应 Snapshot 的 `text` 字段 | 算法适配层 | capture 后必须禁止通过 `self._page` 读取底层 page；strict spy 必须拦截。 |
| `src/hexai_pdf_parser/core\\page_cache.py` | 43 | `CachedPage.get_text` | `self._text_cache[key] = self._page.get_text(*args, **kwargs)` | mode/flags/clip=调用方未知；kwargs=调用方未知 | 按 args/kwargs 缓存键保存底层 `get_text` 结果，供相同参数复用。 | 读取缓存边界；对应 Snapshot 的 `text`/raw text 字段 | 算法适配层 | capture 后禁止触发底层 page 读取；strict spy 必须拦截 `self._page.get_text`。 |
| `src/hexai_pdf_parser/core\\page_cache.py` | 46 | `CachedPage.get_drawings` | `self._page.get_drawings(*args, **kwargs)` | mode/flags/clip=调用方未知；kwargs=调用方未知 | `get_drawings` 缓存未命中时向 `self._page` 透传调用，并缓存返回值。 | 读取缓存边界；对应 Snapshot 的 `drawings` 字段 | 算法适配层 | capture 后必须禁止通过 `self._page` 读取底层 page；strict spy 必须拦截。 |
| `src/hexai_pdf_parser/core\\page_cache.py` | 49 | `CachedPage.get_drawings` | `self._drawings_cache[key] = self._page.get_drawings(*args, **kwargs)` | mode/flags/clip=调用方未知；kwargs=调用方未知 | 按 args/kwargs 缓存键保存底层 `get_drawings` 结果，供相同参数复用。 | 读取缓存边界；对应 Snapshot 的 `drawings` 字段 | 算法适配层 | capture 后禁止触发底层 page 读取；strict spy 必须拦截 `self._page.get_drawings`。 |

## 覆盖声明与结果文件 SHA256

- `pymupdf-page-read-scan.txt` 123/123 行已逐条覆盖。
- `pymupdf-read-scan.txt` 112/112 行已逐条覆盖，其中 108 行与 page-read-scan 内容相同，4 行由上表覆盖。

| 结果文件 | 覆盖行数 | SHA256 |
| --- | ---: | --- |
| `D:\\codes\\PDFLayoutParser-Fast\\output\\snapshot-parity-worktree-20260919\\pymupdf-read-scan.txt` | 112 | `5D8B75F1F7E7358EC537E4BD6119CB18B4A76793239744C57A528EAC6726507C` |
| `D:\\codes\\PDFLayoutParser-Fast\\output\\snapshot-parity-worktree-20260919\\pymupdf-page-read-scan.txt` | 123 | `D5E3BC4EF4178A3A8D51F9CFB3273A32E1C73B46A481B63F3367F8CCDC3C3C6E` |

## Task 0 修复完成条件

- 本轮实际完成的是文档审计整合：两份临时表已逐行追加，4 个独有调用点已单列，覆盖计数和 SHA256 已记录。
- 仅完成文档审计，不代表生产 Snapshot、`capture_page_snapshot()` 或 strict spy 已实现；生产代码、测试和计划文件未修改。
- 未运行测试、pytest、cargo、页面重跑、扫描重跑或任何 Git 命令。
- 较早的“尚未完成”/“中断前”表述属于历史中断记录；当前文档整合清单已完成。
