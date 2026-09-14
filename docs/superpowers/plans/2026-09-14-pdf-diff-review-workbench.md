# PDF 差异分类与审阅工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 1023 页新鲜 E2E 输出中识别 121 页 Markdown 差异，生成带证据的分类 JSON、标签/当前结果并排 PNG 和可离线审阅的中文网页。

**Architecture:** 在 `scripts/pdf_diff_review.py` 中用 Python 标准库 `HTMLParser` 将标签和当前 Markdown 分成正文、表格、单元格文本和结构签名，纯函数完成分类；同一生成器读取 manifest 和实际输出，生成资源目录与内嵌数据的静态 HTML。图片拼接只依赖项目已有的 PyMuPDF，不引入前端构建系统或运行时服务。

**Tech Stack:** Python 3.7+、标准库 `html.parser`/`difflib`/`json`、项目既有 `scripts.markdown_golden_testset.normalize_markdown`、PyMuPDF、原生 HTML/CSS/JavaScript。

## Global Constraints

- 以 `output/fix_zh_all_table_pages_review_20260914/` 的新鲜结果为当前侧，不能引用已消失的旧 `compare_current_20260913`。
- 以 `output/fix_zh_all_table_pages_rerun_20260903/testset_markdown/manifest.json` 为标签基线，严格按 `page_index` 配对。
- 不修改原始 PDF、标签 Markdown、E2E JSON/Markdown/PNG 或用户现有脏工作区文件。
- 生成器不发起网络请求；HTML 内容必须转义，资源使用审阅目录内相对路径。
- 默认决策为“待确认”，浏览器决策保存到 localStorage，并支持导出 JSON；不自动修改标签。
- 代码、测试和中文说明保持当前仓库风格；不添加非必要运行时依赖。

---

### Task 1: 固定差异分类契约

**Files:**
- Create: `tests/test_pdf_diff_review.py`
- Create: `scripts/pdf_diff_review.py`

**Interfaces:**
- Consumes: 两段 Markdown 字符串。
- Produces: `classify_markdown(expected: str, actual: str) -> dict`，返回 `primary_category`、`categories`、`signals` 和 `evidence`。

- [x] **Step 1: Write the failing tests**

已在 `tests/test_pdf_diff_review.py` 写入七类最小用例：阅读顺序、表格结构、表格文本、表格数量、正文、混合和纯格式，并固定表格计数/结构证据字段。

- [x] **Step 2: Run tests to verify they fail**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.pdf_diff_review'`。

- [ ] **Step 3: Implement the minimal parser and classifier**

实现以下最小接口和内部结构：

```python
def classify_markdown(expected: str, actual: str) -> dict:
    expected_snapshot = parse_markdown(expected)
    actual_snapshot = parse_markdown(actual)
    signals = detect_signals(expected_snapshot, actual_snapshot)
    return build_classification(expected, actual, signals)
```

`parse_markdown` 记录 `table_count`、每个表的行数/每行单元格数/`rowspan`/`colspan`、按 DOM 顺序的单元格文本、表格外正文单元和全部可见文本单元。分类信号按以下条件计算：表数量不同为 `table_count`；数量相同但结构签名不同为 `table_structure`；结构相同且单元格文本内容不同为 `table_text`；正文文本集合不同为 `body_text`；全部可见文本集合相同但顺序不同为 `reading_order`；只有标准化 Markdown 表示不同且上述语义均相同为 `formatting`。多个信号统一输出 `primary_category="mixed"`，具体信号放入 `signals`。

- [ ] **Step 4: Run focused tests**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q`

Expected: 分类相关测试全部通过；生成器测试暂时可因 `build_review` 尚未实现而失败。

- [ ] **Step 5: Commit**

```powershell
git add tests/test_pdf_diff_review.py
git add -f scripts/pdf_diff_review.py
git commit -m "feat: classify PDF markdown differences"
```

### Task 2: 生成审阅资源

**Files:**
- Modify: `scripts/pdf_diff_review.py`
- Test: `tests/test_pdf_diff_review.py`

**Interfaces:**
- Consumes: `actual_root: Path`、`testset_root: Path`、`review_dir: Path`。
- Produces: `build_review(actual_root, testset_root, review_dir) -> dict` 以及 `classification.json`、`summary.json`、`images/page-XXX.png`。

- [ ] **Step 1: Extend the failing fixture assertions**

使用测试临时目录建立一个带 manifest、label、实际 `pages/page-000.json`、Markdown 和 `tables/page-000.png` 的最小页面，断言生成器输出 JSON、摘要、并排图和 HTML 数据链接。

- [ ] **Step 2: Implement page pairing and validation**

使用 `scripts.markdown_golden_testset.scan_page_outputs` 读取实际 JSON，按 manifest 的 `page_index` 找到当前 Markdown/PNG；标签图依次尝试 `testset_root/source_visual_path`、`testset_root.parent/source_visual_path` 和 `testset_root.parent/source_table_png`。对缺失的实际 Markdown 或图片保留页面记录和明确错误，不静默丢页。

- [ ] **Step 3: Implement diff and JSON output**

用 `difflib.unified_diff` 生成标签到当前的 diff，页面记录至少包含 `page_index`、`primary_category`、`signals`、`evidence`、diff 文本、标签/当前资源相对路径和原始来源路径；统计页面分类数量，写入 UTF-8 `classification.json` 和 `summary.json`。

- [ ] **Step 4: Implement PyMuPDF-only side-by-side rendering**

实现：

```python
    def make_side_by_side(expected_png: Optional[Path], actual_png: Optional[Path],
                      output_png: Path, page_index: int) -> None:
    # 按最大高度缩放，顶部绘制 LABEL/CURRENT/PAGE 标识，再输出 PNG。
```

当任一 PNG 缺失时绘制占位框并把原因写入页面记录；真实页面不得因单张图失败而中断其余页面生成。

- [ ] **Step 5: Run resource tests**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q`

Expected: 全部测试通过，并能在临时目录中打开生成的 PNG 文件。

- [ ] **Step 6: Commit**

```powershell
git add tests/test_pdf_diff_review.py
git add -f scripts/pdf_diff_review.py
git commit -m "feat: generate PDF diff review assets"
```

### Task 3: 生成离线审阅网页

**Files:**
- Modify: `scripts/pdf_diff_review.py`
- Test: `tests/test_pdf_diff_review.py`

**Interfaces:**
- Consumes: Task 2 页面记录和分类统计。
- Produces: `render_html(payload: dict) -> str` 与 `review_dir/index.html`。

- [ ] **Step 1: Add HTML safety test**

向测试 payload 注入 `<script>bad</script>` 和引号，断言生成 HTML 中的 JSON 不会结束 `<script>` 标签，diff 内容由浏览器端转义后再写入 DOM。

- [ ] **Step 2: Implement the static workbench**

使用“纸张档案 + 墨色标记”的审阅视觉：左侧列表显示页码、分类和信号；顶部显示总数/已决策数/待确认数；中间显示并排 PNG；右侧显示带增删颜色的 diff。提供分类筛选、页码/文本搜索、上一页/下一页、放大原图、三种决策按钮、键盘 `1/2/3` 快捷键和“导出审阅结果”。所有数据内嵌，图片只使用 `images/page-XXX.png` 相对链接。

- [ ] **Step 3: Verify HTML behavior manually and by string checks**

断言 HTML 包含 121 页数据、每种决策文字、`localStorage`、导出按钮和相对 PNG 路径；使用浏览器打开临时 HTML，确认可以切页、筛选、记录和导出。

- [ ] **Step 4: Commit**

```powershell
git add -f scripts/pdf_diff_review.py
git add tests/test_pdf_diff_review.py
git commit -m "feat: add offline PDF diff review workbench"
```

### Task 4: 真实数据生成与验收

**Files:**
- Create: `scripts/run_pdf_diff_review.ps1`
- Modify: `changes.md`（仅追加本次中文记录）

**Interfaces:**
- Consumes: 新鲜 E2E 输出和标签 manifest。
- Produces: `output/fix_zh_all_table_pages_review_20260914/review/` 及分类摘要。

- [ ] **Step 1: Add the reproducible runner**

脚本固定以下参数并允许通过参数覆盖：

```powershell
python scripts/pdf_diff_review.py `
  --actual-root output/fix_zh_all_table_pages_review_20260914 `
  --testset-root output/fix_zh_all_table_pages_rerun_20260903/testset_markdown `
  --review-dir output/fix_zh_all_table_pages_review_20260914/review
```

- [ ] **Step 2: Run real generation**

Expected: `diff_count=121`，页面索引无重复/缺失，分类统计之和为 121，所有真实页面图片成功生成。

- [ ] **Step 3: Run independent image review**

委托 image-reader 审阅至少 6 张代表图（008、193、335、338、341、342；若新鲜结果通过则从 121 页中补充实际差异页），只记录视觉事实，不修改文件。

- [ ] **Step 4: Run final verification**

Run focused tests、生成器命令、JSON 结构检查和 HTML 资源检查；报告 E2E `901/121/1`、分类数量、输出绝对路径和未触碰主工作区的事实。

- [ ] **Step 5: Commit and merge only the worktree changes**

在 worktree 中确认 `git status` 只包含本任务文件后提交；把已验证的分支合并回当前分支时不得覆盖主工作区的未跟踪 PDF、压缩包或其他并行改动。
