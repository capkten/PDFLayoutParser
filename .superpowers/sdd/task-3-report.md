# Task 3 报告：实现自动 Markdown 比较器

## 基本信息

- 日期：2026-09-03
- 工作目录：`D:\codes\PDFLayoutParser\.worktrees\markdown-golden-testset`
- 任务：实现 `compare_testset(testset_root, actual_root, diff_root)` 和 `compare` CLI，并完成正式 build / compare / 负向验证 / 恢复验证

## RED / GREEN 过程

### RED 1：Task 3 基线

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- 16 个既有测试通过。
- 说明 Task 1/2 基线稳定，但 compare 能力尚未覆盖。

### RED 2：先补 compare 核心测试

新增以下临时目录测试后先运行：

- 相同 expected / actual 通过，并清理旧 `diff_root`
- Markdown 内容变化失败，并生成 `.diff.md` 与 `.actual.md`
- expected 缺 actual、actual 多页、`absent_expected` 意外生成 Markdown 失败

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- 3 个新增 compare 测试全部报错；
- 共同根因：`compare_testset` 尚未定义。

### GREEN 1：实现 compare 核心逻辑与 compare CLI

完成最小实现后再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- 19 个测试通过。

实现内容：

- 新增 `compare_testset()`；
- 新增 manifest 校验、diff 目录清理、状态差异报告、内容 diff 与 actual Markdown 副本；
- 新增 CLI：`compare --testset-root --actual-root --diff-root`；
- `README` 生成逻辑改为写入真实 compare 命令。

### RED 3：补足 Task 3 brief 里的遗漏测试

根据补充要求，再新增两类测试并先验证：

- `rowspan` 结构变化必须失败；
- 仅图片引用路径变化与 JSON bbox / render_path 变化不应失败；
- 测试 helper 必须生成 root-level `visualized_images/*.png`，保持与 scanner 契约一致。

说明：

- 这一步先发现测试 helper 还没生成 root-level flat PNG，不满足 scanner 契约。

### GREEN 2：修正测试 helper 并补齐覆盖

调整 helper 后再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- 21 个测试通过。

本轮新增覆盖：

- `rowspan` 变化失败；
- 文本/colspan 变化失败；
- 空 `<td></td>` 差异已由现有内容 diff 用例覆盖；
- 图片引用路径变化不失败；
- JSON bbox / render_path 变化不失败；
- helper 会同步生成 `output_root/visualized_images/<context>__tables__<stem>.png`。

## 正式验证

### 1. fresh self-test

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- `Ran 21 tests`
- `OK`

### 2. 正式 build

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py build --pdf D:/codes/PDFLayoutParser/fix/zh_all_table_pages.pdf --output-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903 --testset-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown
```

结果：

```json
{
  "page_count": 1023,
  "label_count": 941,
  "absent_expected_count": 79,
  "excluded_count": 1,
  "failed_count": 2,
  "manifest_path": "D:\\codes\\PDFLayoutParser\\output\\fix_zh_all_table_pages_rerun_20260903\\testset_markdown\\manifest.json",
  "readme_path": "D:\\codes\\PDFLayoutParser\\output\\fix_zh_all_table_pages_rerun_20260903\\testset_markdown\\README.md",
  "testset_root": "D:\\codes\\PDFLayoutParser\\output\\fix_zh_all_table_pages_rerun_20260903\\testset_markdown"
}
```

### 3. 正式 compare

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py compare --testset-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown --actual-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903 --diff-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown/diffs
```

结果：

```text
compare summary: passed=1021 failed=0 missing=0 extra=0 diff_root=D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\diffs
```

说明：

- 当前同一批输出与刚生成的标签集完全一致；
- compare 返回 0；
- 没有失败页、缺页、额外页。

## 负向验证与恢复

### 负向验证

操作：

- 复制正式 `testset_markdown` 到 `D:\codes\PDFLayoutParser\output\_tmp_compare_negative_20260903\testset_markdown`
- 仅修改临时副本中的 `labels/page-000.md`
- 将首个单元格文本 `1.` 改成 `__TEST_DIFF__`

替换确认：

```text
D:\codes\PDFLayoutParser\output\_tmp_compare_negative_20260903\testset_markdown\labels\page-000.md:8:      <td>__TEST_DIFF__</td>
```

比较命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py compare --testset-root D:/codes/PDFLayoutParser/output/_tmp_compare_negative_20260903/testset_markdown --actual-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903 --diff-root D:/codes/PDFLayoutParser/output/_tmp_compare_negative_20260903/testset_markdown/diffs-negative
```

结果：

```text
compare summary: passed=1020 failed=1 missing=0 extra=0 diff_root=D:\codes\PDFLayoutParser\output\_tmp_compare_negative_20260903\testset_markdown\diffs-negative
```

差异文件：

- `page-000.diff.md`
- `page-000.actual.md`

`page-000.diff.md` 摘要：

```diff
--- expected
+++ actual
@@ -5,7 +5,7 @@
 <table>
   <tbody>
     <tr>
-      <td>__TEST_DIFF__</td>
+      <td>1.</td>
       <td>Who needs to have access to ESS?</td>
```

`page-000.actual.md` 证据：

- 保留了实际页完整 Markdown；
- 其中首个单元格仍为 `1.`，说明 compare 同时输出了人类可读 diff 和 actual 副本。

### 恢复验证

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py compare --testset-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown --actual-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903 --diff-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown/diffs
```

结果：

```text
compare summary: passed=1021 failed=0 missing=0 extra=0 diff_root=D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\diffs
```

清理：

- 临时负向目录已删除；
- 使用短 Python 命令清理，删除后 `exists() -> False`。

## 实际统计

- self-test：21 个测试
- 正式 build：`941 markdown + 79 absent_expected + 1 excluded + 2 failed_no_output`
- 正式 compare：`passed=1021 failed=0 missing=0 extra=0`
- 负向 compare：`passed=1020 failed=1 missing=0 extra=0`
- 恢复 compare：`passed=1021 failed=0 missing=0 extra=0`

## 变更文件

- 修改：`D:\codes\PDFLayoutParser\.worktrees\markdown-golden-testset\scripts\markdown_golden_testset.py`
- 新增：`D:\codes\PDFLayoutParser\.worktrees\markdown-golden-testset\.superpowers\sdd\task-3-report.md`

本地生成但不提交：

- `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\`
- `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\diffs\`
- 临时负向目录已删除

## 自审

- compare 主比较只看规范化 Markdown，不比较 JSON 字段、bbox、置信度、图片路径或像素。
- status 语义符合 brief：
  - `markdown` 必须存在并逐字比较规范化结果；
  - `absent_expected` 必须存在且无 Markdown；
  - `excluded` / `failed_no_output` 只作为已记录页豁免，不算额外页。
- diff 目录会在比较开始前清空并重建，避免旧差异残留。
- 实际扫描失败会写 `scan_error.diff.md` 并返回非 0。
- 没有修改 PDF 主流程，也没有回退其他 agent / 用户改动。

## 疑虑

- `compare summary` 当前会把 `excluded` 也计入 `passed`，这对返回码没有影响，但“通过页数”语义更接近“已处理且未失败的记录页数”，不是“实际比较了 Markdown 的页数”。
- 正式 build / compare 仍依赖主仓库下被 Git 忽略的 `fix/` 和 `output/` 绝对路径，因为当前 worktree 内没有同名输入输出目录。

## 追加修复（Final Review）

### RED 4：manifest 严格校验与 diff_root 安全门

根据 final review，新增以下失败测试后先运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

新增覆盖：

- Manifest `pages` 的 `markdown_status` 只能是 `markdown / absent_expected / excluded`
- `failed_pages` 每条必须是 `failed_no_output`
- `page_index` 必须是合法整数且位于 `0..page_count-1`
- `pages` 与 `failed_pages` 合起来必须完整覆盖 `0..page_count-1`
- 非 `markdown` 页不允许设置 `label_path`
- 外部 `diff_root` 必须被拒绝，且不能清理 sentinel

首次结果：

- 新增 manifest 校验测试失败；
- 外部 `diff_root` sentinel 被提前清掉；
- 说明原实现先清空任意 `diff_root`，且 `_load_manifest()` 只做了最少校验。

### GREEN 3：补严格校验与安全清理

最小修复后再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- `Ran 25 tests`
- `OK`

本轮修改：

- 新增 `VALID_MARKDOWN_STATUSES`
- `_load_manifest()` 现在校验：
  - `page_count` 必须是非负整数
  - `pages.markdown_status` 只能是 `markdown / absent_expected / excluded`
  - `failed_pages.markdown_status` 必须是 `failed_no_output`
  - 所有 `page_index` 必须为整数且在范围内
  - `pages` 与 `failed_pages` 不允许重复
  - Manifest 记录页集合必须完整覆盖 `0..page_count-1`
  - `markdown` 页必须有位于 `testset_root` 内且存在的 `label_path`
  - 其他状态的 `label_path` 必须为 `None` 或空
- `compare_testset()` 在清理前先校验 `diff_root`
  - 仅允许 `testset_root` 或 `actual_root` 的严格后代目录
  - 若 `diff_root` 等于根目录或在根目录外，直接返回非 0
  - 拒绝时不会清理外部目录内容
- compare summary 改成 `passed / skipped / failed / missing / extra`
  - `excluded` 不再计入 `passed`

### 本轮正式验证

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
conda run -n base python scripts/markdown_golden_testset.py build --pdf D:/codes/PDFLayoutParser/fix/zh_all_table_pages.pdf --output-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903 --testset-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown
conda run -n base python scripts/markdown_golden_testset.py compare --testset-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown --actual-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903 --diff-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown/diffs
git diff --check
```

结果：

- self-test：`25 tests OK`
- 正式 build：`941 markdown / 79 absent_expected / 1 excluded / 2 failed_no_output`
- 正式 compare：`passed=1020 skipped=1 failed=0 missing=0 extra=0`
- `git diff --check`：通过

### 本轮负向与恢复

负向验证：

- 临时复制正式 `testset_markdown`
- 仅将 `labels/page-000.md` 中一个 `<td>1.</td>` 替换为 `<td>__TEST_DIFF__</td>`
- compare 结果：

```text
compare summary: passed=1019 skipped=1 failed=1 missing=0 extra=0 diff_root=D:\codes\PDFLayoutParser\output\_tmp_compare_negative_20260903_review\testset_markdown\diffs-negative
```

差异证据：

- `page-000.diff.md`
- `page-000.actual.md`

恢复验证：

```text
compare summary: passed=1020 skipped=1 failed=0 missing=0 extra=0 diff_root=D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\diffs
```

清理：

- 临时负向目录 `D:\codes\PDFLayoutParser\output\_tmp_compare_negative_20260903_review` 已删除，删除后 `exists() -> False`
