# Task 4 真实审阅运行报告

## 状态

运行入口、差异分类和中文变更记录已完成。真实生成结果与新鲜 E2E 的 121 个失败页面对齐；未修改原始 PDF、标签或真实 E2E 输出。

## 改动

- 新增 `scripts/run_pdf_diff_review.ps1`。
  - 默认使用实际输出 `output/fix_zh_all_table_pages_review_20260914`、测试集 `output/fix_zh_all_table_pages_rerun_20260903/testset_markdown` 和 review 子目录。
  - 支持 `-ActualRoot`、`-TestsetRoot`、`-ReviewDir` 覆盖。
  - 在 worktree 默认输入不存在时解析到同项目主目录的 `output`，适配当前 worktree 布局。
  - 使用实际执行的主项目解释器 `D:\soft\miniconda\python.exe` 调用 `build_review()`。
- 仅在 `changes.md` 文件末尾追加 2026-09-14 中文记录。
- `build_review()` 使用 `normalize_markdown()` 后再分类、生成 diff 和建立搜索索引；显式 `excluded` 页面不进入审阅 payload。
- 报告文件为本文件；未暂存其他并行 worktree 材料。

## 真实生成

命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_pdf_diff_review.ps1
```

生成结果：

- 输出目录：`D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_review_20260914\review`
- `page_count=1023`
- `review_page_count=121`
- `diff_count=121`
- 全量状态：`same=901`、`excluded=1`；差异分类：`body_text=97`、`mixed=10`、`table_structure=8`、`table_count=3`、`table_text=1`、`missing_resource=2`，总和 121。
- review payload 页面索引与 E2E `testset_markdown/diffs` 的 121 个索引完全一致，无重复、缺失或额外页。
- `scan_errors=[]`。
- 资源缺失仅为标签 PNG：页面索引 408、410；实际页面资源仍已生成，合成页图片为 1023 张，两侧来源 PNG 共 2044 张。

新鲜 E2E 对比摘要：`passed=901 failed=121 skipped=1 missing=0 extra=0`。review 生成只消费已有真实输出，不为追求统计数字重跑或改写 E2E 结果。

## 验证

- 定向测试：`19 passed, 5 warnings`，警告为既有 PyMuPDF/SWIG 弃用警告。
- Python 语法检查：`D:\soft\miniconda\python.exe -m py_compile scripts/pdf_diff_review.py` 通过。
- `git diff --check` 通过。
- JSON 检查：`summary.json` 与 `classification.json` 可解析；summary 覆盖 1023 页，classification/HTML 仅包含 121 个差异页，分类总和为 121。
- E2E 索引检查：review 页面集合与 `testset_markdown/diffs` 完全相等。
- 图片资源检查：合成审阅图 1023 张、来源图 2044 张；121 条 review 记录的合成图和可用单侧 PNG 均可由 PyMuPDF 解码，408/410 的标签 PNG 缺失被明确记录并在合成图中显示占位。
- HTML 静态检查：`index.html` 存在，包含筛选、搜索、导航、三种决策、localStorage、放大和导出控件；页面数据只包含差异页。
- 浏览器运行时验收：浏览器连接连续返回 `nodeRepl.fetch request failed`，重试和重置后仍无可用浏览器，因此未把点击切页、筛选、导出和 localStorage 运行结果宣称为已验证。

## 代表图视觉事实

独立 image-reader 检查了差异类别代表图 `page-182`、`page-185`、`page-196`、`page-198`、`page-409`、`page-465`：

- `page-182`：CURRENT 在页面下半部账龄/坏账计提比例区域出现表格框、网格和文字标注，LABEL 没有对应检测框；就检测标注而言 CURRENT 更完整。
- `page-185`：三个表格两侧位置、外边界和主要文字基本对应，未见肉眼可确认的实质差异；两侧完整性无法判断。
- `page-196`：外层大表格边界基本一致，CURRENT 内部切分为明显更多行列（约 29x8），LABEL 较粗（约 16x3）；哪侧结构正确仅凭合成图无法确定。
- `page-198`：目录上部 CURRENT 少一条纵向分隔，并将“一、”“二、”显示在表格外侧；LABEL 的列结构更完整，但文字究竟漏提还是归属位置变化不确定。
- `page-409`：正文和底部表格位置、边界、网格和数字基本一致，未见肉眼可确认的实质差异。
- `page-465`：长表格的外边界和四列结构基本一致，未见肉眼可确认的漏行、漏字或错位；最小字号差异不确定。

## 范围确认

本 worktree 中本任务的修改为 `scripts/pdf_diff_review.py`、`tests/test_pdf_diff_review.py`、`scripts/run_pdf_diff_review.ps1`、`changes.md` 及本报告；已有其他 `.superpowers/sdd` 并行材料保持未跟踪、未修改。`output/` 为生成产物，未加入提交。
