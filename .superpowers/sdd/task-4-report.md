# Task 4 真实审阅运行报告

## 状态

运行入口和中文变更记录已完成。真实生成命令成功执行，但本次输入快照得到的 `diff_count=784`，没有达到简报预期的 `121`；因此本报告保留真实结果，不修改原始 PDF、标签或真实 E2E 输出。

## 改动

- 新增 `scripts/run_pdf_diff_review.ps1`。
  - 默认使用实际输出 `output/fix_zh_all_table_pages_review_20260914`、测试集 `output/fix_zh_all_table_pages_rerun_20260903/testset_markdown` 和 review 子目录。
  - 支持 `-ActualRoot`、`-TestsetRoot`、`-ReviewDir` 覆盖。
  - 在 worktree 默认输入不存在时解析到同项目主目录的 `output`，适配当前 worktree 布局。
  - 使用实际执行的主项目解释器 `D:\soft\miniconda\python.exe` 调用 `build_review()`。
- 仅在 `changes.md` 文件末尾追加 2026-09-14 中文记录。
- 报告文件为本文件；未暂存其他并行 worktree 材料。

## 真实生成

命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_pdf_diff_review.ps1
```

生成结果：

- 输出目录：`D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_review_20260914\review`
- `page_count=1023`
- `diff_count=784`（预期 121，未匹配）
- 分类：`same=239`、`formatting=495`、`body_text=264`、`table_count=4`、`mixed=17`、`missing_resource=2`、`table_structure=1`、`table_text=1`；总和 1023。
- 页面索引为 0 至 1022，共 1023 个且无重复、缺失。
- `scan_errors=[]`。
- 资源缺失仅为标签 PNG：页面索引 408、410；实际页面资源仍已生成，合成页图片为 1023 张。

简报要求记录的 E2E `901/121/1` 未在本次 review 输入中重现；本次 review 实际统计为 `239/784/2`（same/diff/missing_resource）。未为追求预期数字重跑或改写 E2E 输出。

## 验证

- 定向测试：`18 passed, 5 warnings`，警告为既有 PyMuPDF/SWIG 弃用警告。
- Python 语法检查：`D:\soft\miniconda\python.exe -m py_compile scripts/pdf_diff_review.py` 通过。
- `git diff --check` 通过。
- JSON 检查：`summary.json` 与 `classification.json` 可解析，分类和页面索引完整。
- HTML 检查：`index.html` 存在；检查到 3067 个图片引用，缺失引用为 0。
- 图片资源检查：合成审阅图 1023 张，来源图 2044 张；每条记录引用的资源路径均可解析，资源缺失由 summary 中两页标签 PNG 明确记录。

## 代表图视觉事实

已检查合成图 `page-008`、`page-193`、`page-335`、`page-338`、`page-341`、`page-342`：

- `page-008` 标签与当前表格边界、行列框和正文图像位置基本对齐，差异主要是文本尾随空白等非视觉差异。
- `page-193` 底部 4x10 有线表格边界和单元格网格在两侧对齐，页面上方表单内容未被表格框吸收。
- `page-335` 两侧 5x4 无线表格位置、列线和印章区域均保持一致。
- `page-338` 两侧页眉、正文双栏和柱状图布局一致，未见表格误框。
- `page-341` 两侧圆环图、柱状图、提示框和页脚布局一致。
- `page-342` 两侧流程图和下方双栏正文结构一致，未见边界扩张。

## 范围确认

本 worktree 中仅本任务的 `scripts/run_pdf_diff_review.ps1`、`changes.md` 和本报告作为提交候选；已有 `.superpowers/sdd` 并行材料保持未跟踪、未修改。`output/` 未加入提交。
