# 回归测试 PDF Fixture

这些单页 PDF 从本地调试样本 `fix/zh_all_table_pages.pdf` 抽取，保留原页面的 native text、字体、drawing 和坐标信息，用于不依赖 295 MB 原始文件的回归测试。

- `page_000_vector.pdf`：原始文件 0-based page index 0，验证正常中文 vector 页面分类。
- `page_437_wireless.pdf`：原始文件 0-based page index 437，验证底部无线表格的首列文本和记录行恢复。
- `page_705_scanned.pdf`：原始文件 0-based page index 705，验证扫描页分类。

测试打开 fixture 后统一使用单页 PDF 的 page index 0。原始调试 PDF 不纳入版本库。
