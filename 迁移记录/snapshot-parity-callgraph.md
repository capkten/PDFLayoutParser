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
