# Task 1 报告

日期：2026-09-03

## 目标

实现 `scripts/markdown_golden_testset.py` 中的输出扫描、页码映射、Markdown 规范化和统一 diff 基础脚本，并提供可执行的纯函数自测。

## 变更文件

- `scripts/markdown_golden_testset.py`

## 实现内容

- 新增 `normalize_markdown(text: str) -> str`
  - 将 `CRLF` / `CR` 统一转成 `LF`
  - 删除整行图片引用
  - 去掉每行尾部空白
  - 连续空行压缩为一个
  - 去掉文件首尾多余空行
- 新增 `source_page_index(path: Path, local_page_index: int) -> int`
  - 支持 `file_page_024.json`、`page-024.json`、`page_024.json` 这类文件名
  - 优先识别直接父目录 `page_0405`
  - 支持向上查找最近的 `*_pages_START_END` 范围目录
  - 对局部页码与目录范围做校验，解析失败时抛出包含完整路径的 `ValueError`
- 新增 `scan_page_outputs(output_root: Path) -> dict[int, dict]`
  - 只扫描父目录名为 `pages` 的 JSON 文件
  - 同步查找同 stem 的 Markdown 文件和相邻 `tables` 目录里的 PNG
  - 读取 JSON 的 `index` 与 `page_type` 做校验
  - 同一原始页索引出现重复时抛出冲突错误
  - 返回 `page_index`、`page_type`、`json_path`、`markdown_path`、`visual_path` 和 `relative_path`
- 新增 `write_diff(expected: str, actual: str, path: Path) -> None`
  - 生成 UTF-8 unified diff
  - 自动创建父目录
- 新增脚本内 `unittest` 自测入口
  - `self-test` 命令可直接运行

## TDD 过程

### RED

首次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

首次结果：

- 4 个测试全部报 `NotImplementedError`
- 失败点分别落在 `normalize_markdown`、`source_page_index`、`scan_page_outputs`、`write_diff`

随后补入 `scan_page_outputs` 和 `write_diff` 的最小行为测试后，再次运行同一命令，仍然是预期失败，且失败原因仍然是未实现函数。

### GREEN

实现后再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

结果：

- `6` 个测试全部通过
- `OK`

## 自审

- `git diff --check` 通过，没有空白或行尾问题
- 自测覆盖了：
  - 目标页码映射的 3 个样例
  - Markdown 规范化样例
  - 输出扫描的目录配对样例
  - unified diff 写入样例
- 修改范围保持在单个新脚本内，没有碰 PDF 解析主流程

## 疑虑

- `scan_page_outputs` 当前对缺失 Markdown 或 PNG 采取直接报错，属于偏严格实现，但与 brief 中“找到同 stem 的文件”一致
- `source_page_index` 目前按路径上下文推断页数范围；更高层的 PDF 总页数校验仍需要在后续扫描入口或调用方完成
- 当前没有补充冲突页、缺失伴随文件和异常目录名的额外回归测试，后续如果扫描格式扩展，可能还需要加覆盖

## 提交

- `bd273cf` - `fix: add markdown golden testset helpers`

## Task 1 审查修复补充

日期：2026-09-03

### 目标

补上审查反馈要求的真实行为回归测试，只在 `D:\codes\PDFLayoutParser\.worktrees\markdown-golden-testset` 内修改 `scripts/markdown_golden_testset.py` 和本报告，不改 PDF 解析主流程。

### 变更文件

- `scripts/markdown_golden_testset.py`
- `.superpowers/sdd/task-1-report.md`

### 测试前失败

- 这次补测前先跑了现有自测：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
```

- 结果为 `10` 个测试全部通过，说明审查指出的边界在当前实现里已经满足。
- 因此这次没有出现“先红后绿”的生产代码失败，也没有改动生产逻辑。

### 新增回归测试

- `test_source_page_index_rejects_local_index_out_of_range`
  - 固定 `Path("page_0405/pages/file_page_001.json"), 1`，确认必须抛 `ValueError`
- `test_scan_page_outputs_rejects_conflicting_same_source_page`
  - 用两个不同来源目录但同一原始页索引 `405` 的输出，确认冲突抛 `ValueError`
- `test_scan_page_outputs_rejects_missing_markdown`
  - 当前 Task1 扫描契约下，缺 Markdown 必须抛 `ValueError`
- `test_scan_page_outputs_rejects_missing_png`
  - 当前 Task1 扫描契约下，缺 PNG 必须抛 `ValueError`

### 修复后结果

再次运行：

```powershell
conda run -n base python scripts/markdown_golden_testset.py self-test
git diff --check
```

结果：

- `10` 个自测全部通过
- `git diff --check` 通过
- 未修改生产代码，只补了回归测试

### 自审

- `source_page_index` 的越界测试覆盖了审查者担心的 `page_0405` 场景，确认现有实现已经会抛 `ValueError`
- `scan_page_outputs` 的冲突、缺 Markdown、缺 PNG 三个边界都被真实文件结构驱动，不依赖 mock
- 没有碰其他 agent 的改动，也没有回退既有提交

### 提交

- 待生成
