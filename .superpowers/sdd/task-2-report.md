# Task 2 报告：构建本地 Markdown 黄金测试集

## 基本信息

- 日期：2026-09-03
- 工作目录：`D:\codes\PDFLayoutParser\.worktrees\markdown-golden-testset`
- 任务：为 `scripts/markdown_golden_testset.py` 实现 `build` 能力，并在本地生成 `testset_markdown`

## RED / GREEN 过程

### RED 1：现有 self-test 基线

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- 10 个测试通过。
- 说明 Task 1 的辅助函数正常，但尚未覆盖 Task 2 的 scanned 缺 Markdown 和 build 行为。

### RED 2：先补 scanned 缺 Markdown 与 build 临时目录测试

新增测试后再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- `test_scan_page_outputs_allows_scanned_page_without_markdown` 报错；
- `test_build_testset_creates_manifest_and_labels` 报错；
- 根因分别为：
  - `scan_page_outputs()` 仍把 scanned 页缺 Markdown 当错误；
  - `build_testset()` 尚未实现。

### GREEN 1：实现 scanned 缺 Markdown 与 build 基础能力

完成最小实现后运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- 12 个测试通过。

### RED 3：真实 build 暴露 root-level flat visual 索引问题

真实 build 命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py build --pdf D:/codes/PDFLayoutParser/fix/zh_all_table_pages.pdf --output-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903 --testset-root D:/codes/PDFLayoutParser/output/fix_zh_all_table_pages_rerun_20260903/testset_markdown
```

首次结果：

```json
{
  "page_count": 1023,
  "label_count": 942,
  "absent_expected_count": 79,
  "excluded_count": 0,
  "failed_count": 2
}
```

问题：

- 排除页 482 未被排除；
- 所有 `source_visual_name` 为 `null`；
- 根因是我最初错误地从分片目录旁边查 `visualized_images/`，而真实 flat visual 在 `output_root/visualized_images/`。

### RED 4：根据你的反馈补 root-level visualized_images 测试

补充以下回归测试并先观察失败：

- root-level `visualized_images` 索引命中；
- 排除页缺失 flat visual 必须失败；
- `excluded_visual_stems` 必须精确匹配恰好一个页面，否则失败。

失败现象与预期一致，证明测试覆盖到了真实缺口。

### GREEN 2：修正 flat visual 设计并完成严格排除校验

调整后再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- 15 个测试通过。

## 实现调整

本次按 brief 和你中途指出的真实目录结构做了以下调整：

- `scan_page_outputs()` 允许 `page_type=scanned` 缺少同 stem Markdown，并记录 `markdown_path=None`。
- 扫描时建立 `output_root/visualized_images` 的 root-level flat 索引。
- flat visual 通过 `__tables__{visual_path.name}` 后缀索引和唯一性校验匹配。
- 排除判定使用 `page_output["visual_path"].stem` 精确匹配 `excluded_visual_stems`，不使用 flat 文件名 stem。
- 构建时对每个 `excluded_visual_stems` 断言“恰好匹配 1 页”，否则失败。
- 默认排除页 482 若缺失 flat visual，构建失败。
- 确认纳入页 589 若缺失 flat visual，构建失败。
- 构建前完成页数、页索引、已知失败页集合的严格校验；通过后清空并重建 `labels/`。
- 生成 UTF-8 `manifest.json` 与中文 `README.md`。
- CLI 新增 `build --pdf --output-root --testset-root`。

## 验证命令与结果

### self-test

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- `Ran 15 tests`
- `OK`

### 真实 build

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
  "readme_path": "D:\\codes\\PDFLayoutParser\\output\\fix_zh_all_table_pages_rerun_20260903\\testset_markdown\\README.md"
}
```

### Manifest 抽查

检查结果：

- `markdown=941`
- `absent_expected=79`
- `excluded=1`
- `failed_pages=[408, 410]`
- `page_index=482`：
  - `markdown_status=excluded`
  - `source_page_index=482`
  - `source_visual_name=part_002_pages_0342_0512__subpart_004_pages_0458_0486__part_004_pages_0458_0486__tables__part_004_pages_0458_0486_page_024.png`
- `page_index=589`：
  - `markdown_status=markdown`
  - `label_path=labels/page-589.md`
  - `source_visual_name=part_003_pages_0513_0683__part_003_pages_0513_0683__tables__part_003_pages_0513_0683_page_076.png`

### diff 检查

```powershell
git diff --check
```

结果：

- 无输出，表示通过。

## 实际统计

- PDF 总页数：1023
- `pages/*.json`：1021
- 失败页：408、410
- 生成标签：941
- scanned 且预期无 Markdown：79
- excluded：1
- failed_no_output：2

与 brief 当前实际统计一致。

## 变更文件

- 修改：`D:\codes\PDFLayoutParser\.worktrees\markdown-golden-testset\scripts\markdown_golden_testset.py`
- 新增：`D:\codes\PDFLayoutParser\.worktrees\markdown-golden-testset\.superpowers\sdd\task-2-report.md`

本地生成但不提交：

- `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\labels\`
- `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\manifest.json`
- `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_20260903\testset_markdown\README.md`

## 自审

- 改动只集中在目标脚本，没有触碰 PDF 主解析流程。
- TDD 顺序满足：先补失败测试，再实现，再跑 self-test 与真实 build。
- 未回退其他 agent / 用户改动；`git status` 中保留了已有 `.superpowers` 相关未提交文件。
- `output/` 产物保持本地，未进入 Git 状态。

## 疑虑

- 真实 build 使用了主仓库下的绝对 `fix/` 与 `output/` 路径，因为这些 Git 忽略输入/输出目录在当前 worktree 中并不存在；脚本默认相对路径仍按“当前仓库根目录”解析。
- `manifest.pages` 目前额外记录了 `testset_root` 字段，任务要求并未禁止，但它不是最小必需字段；若后续想进一步收紧 manifest，可考虑删除这一项。

## 追加修复（Task 2 审查反馈）

### RED 5：默认排除页必须精确命中 482，manifest 不保留环境字段

根据审查反馈，新增两类回归测试后先运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- `test_build_testset_creates_manifest_and_labels` 失败：manifest 顶层仍包含 `testset_root` / `output_root`，每页记录仍包含 `testset_root`。
- `test_build_testset_rejects_default_excluded_stem_on_wrong_page_index` 失败：默认排除 stem 唯一命中页 481 时未报错。

说明：

- 原实现只校验 `excluded_visual_stems` “恰好命中一页”，没有进一步约束默认排除 stem `part_004_pages_0458_0486_page_024` 必须映射到 `page_index=482`。
- manifest 里保留了不必要的环境路径字段，不符合这轮收紧要求。

### GREEN 3：补默认排除页号断言并删除冗余 manifest 字段

最小修复后再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- `Ran 16 tests`
- `OK`

本轮修改：

- 新增默认排除 stem 到预期页号的映射：`part_004_pages_0458_0486_page_024 -> 482`。
- 对默认排除 stem 增加严格校验：唯一命中的页号若不是 482，直接抛 `ValueError`。
- 保留自定义 `excluded_visual_stems` 的通用能力，仅对默认 stem 应用固定页号约束。
- 删除 manifest 顶层的 `output_root`、`testset_root`。
- 删除每页记录中的 `testset_root`。

### 本轮验证

命令：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
git diff --check
```

结果：

- self-test：16 个测试全部通过。
- `git diff --check`：通过。
