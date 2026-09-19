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
