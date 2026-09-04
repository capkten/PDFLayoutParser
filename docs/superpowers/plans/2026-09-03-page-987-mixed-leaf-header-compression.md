# Page 987 混合叶表头压缩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不放宽物理行聚类规则的前提下，将完整二叶子父表头下的单行与折行叶标题压缩到同一逻辑表头层，使 Page 987 恢复为正确的 `6x7`。

**Architecture:** 在 `logical_grid.py` 增加一个只消费既有物理 Cell 的私有拓扑判定。它仅在唯一 `colspan=2` 父表头、两个连续子列、每列唯一叶标题、区间内无竞争占位时返回压缩区间；`_row_components()` 复用现有分组机制，跨度恢复、冲突检查和空槽物化保持不变。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、现有 native-span 无线表格恢复管线。

## Global Constraints

- 不修改 `grid.py` 的物理行聚类阈值和同列互斥规则。
- 不硬编码“持股比例”“直接”“间接”等业务文字。
- 只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不调用 `page.get_text("words")`。
- 不进入 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或其他 page words 二次重建。
- 压缩和跨度调整后必须保持每个逻辑槽位恰好由一个 Cell 占用。
- 任一父子拓扑条件不成立时保持现有结果，不做推测性压缩。

---

### Task 1: 用失败测试锁定 Page 987 拓扑和拒绝条件

**Files:**
- Modify: `tests/test_wireless_structure_grid.py`
- Create: `tests/test_page_987_table_recovery.py`

**Interfaces:**
- Consumes: `build_logical_grid(...)`、`merge_header_spans(...)`、`materialize_empty_cells(...)`、`recover_cells_from_region(page, bbox)`。
- Produces: Page 987 形态单元测试、缺失完整 `1:2` 子列证明的反例、真实页面 no-words 集成测试。

- [ ] **Step 1: 添加最小 Page 987 形态正例**

在 `tests/test_wireless_structure_grid.py` 新增 `test_build_logical_grid_collapses_mixed_leaf_headers_under_proven_two_column_parent()`：构造 6 条物理行、7 列，父表头位于 row 1/cols 5-6，“间\n接”位于 rows 3-4/col 6，“直接”位于 row 4/col 5，前四个 stub 位于 row 3，第 7 列跨 rows 1-4，正文位于 row 6。断言逻辑行来源为 `[[1, 2], [3, 4, 5], [6]]`；调用 `merge_header_spans()` 后断言父表头 `colspan=2`、两个叶标题位于 row 2、前四个 stub 和第 7 列均覆盖逻辑 rows 1-2；物化后无空表头 Cell，且 `_has_occupancy_conflict()` 为 `False`。

- [ ] **Step 2: 添加不完整父子关系反例**

新增 `test_build_logical_grid_keeps_mixed_leaf_rows_when_two_column_parent_is_incomplete()`：保留同样的折行候选和一个 `colspan=2` 父表头，但父表头覆盖列中缺少另一叶标题，同时在候选结束行放置父表头范围外的独立 Cell 以保持该物理行为结构行。断言 rows 3、4 不被新规则压缩。

- [ ] **Step 3: 添加真实 Page 987 集成测试**

创建 `tests/test_page_987_table_recovery.py`，用 `NoWordsPage` 包装 `fix/zh_all_table_pages.pdf` 的 page index 987，禁止 `get_text("words")`；对 `BBox(84.2, 91.1, 506.2, 362.5)` 调用 `recover_cells_from_region()`。断言 `(rows, cols) == (6, 7)`、36 个 Cell、42 个槽位唯一覆盖；按坐标断言父表头 `colspan=2`、前四列和末列 `rowspan=2`、两个子标题都在 row 1，且表头无空 Cell。

- [ ] **Step 4: 运行新增测试并确认 RED**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n base python -m pytest -q `
  tests/test_wireless_structure_grid.py::test_build_logical_grid_collapses_mixed_leaf_headers_under_proven_two_column_parent `
  tests/test_wireless_structure_grid.py::test_build_logical_grid_keeps_mixed_leaf_rows_when_two_column_parent_is_incomplete `
  tests/test_page_987_table_recovery.py
```

Expected: 正例和真实页面测试因仍产生三层表头而失败；反例保持通过。失败必须是行数/逻辑行分组断言，不得是导入或 fixture 错误。

---

### Task 2: 实现父表头证明下的混合叶表头压缩

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py`
- Test: `tests/test_wireless_structure_grid.py`
- Test: `tests/test_page_987_table_recovery.py`

**Interfaces:**
- Consumes: `cells: Sequence[dict[str, Any]]`、一个已通过基本折行条件的 `candidate`、`header_cutoff: float | None`。
- Produces: `_grouped_mixed_leaf_header_span(...) -> tuple[int, int] | None`，供 `_row_components()` 收集压缩区间。

- [ ] **Step 1: 新增私有纯函数**

在 `_wrapped_leaf_header_span()` 后新增：

```python
def _grouped_mixed_leaf_header_span(
    cells: Sequence[dict[str, Any]],
    candidate: dict[str, Any],
    header_cutoff: float | None,
) -> tuple[int, int] | None:
    """Find mixed single/wrapped leaves proven by one two-column parent."""
```

函数先复用与 `_wrapped_leaf_header_span()` 等价的候选基本条件：表头内、单列、`multiline_cell`、包含换行、跨至少两个物理行。随后筛选位于候选上方且恰好覆盖两个连续列的父 Cell；只有恰好一个父 Cell 覆盖候选列时继续。

收集候选区间内落在父列范围的单列非空 Cell，要求恰好两个、列集合与父列集合完全一致、每列恰好一个且包含候选。拒绝区间内额外跨列 Cell、父列内额外竞争 Cell，以及父列外同一列出现多个非空 Cell。通过时返回 `(candidate.row_start, candidate.row_end)`，否则返回 `None`。

- [ ] **Step 2: 接入逻辑行分组**

在 `_row_components()` 中保留现有 `wrapped_header_spans`，新增：

```python
grouped_mixed_header_spans = [
    span
    for cell in cells
    for span in [_grouped_mixed_leaf_header_span(cells, cell, header_cutoff)]
    if span is not None
]
```

将循环输入改为 `body_prefix_spans + wrapped_header_spans + grouped_mixed_header_spans`。不修改 `build_logical_grid()`、`merge_header_spans()` 或 `materialize_empty_cells()`。

- [ ] **Step 3: 运行新增测试并确认 GREEN**

Run: Task 1 Step 4 的同一命令。

Expected: `3 passed`。

- [ ] **Step 4: 运行逻辑网格和折行表头回归**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n base python -m pytest -q `
  tests/test_wireless_structure_grid.py `
  tests/test_wrapped_leaf_headers.py `
  tests/test_wireless_structure_merges.py `
  tests/test_wireless_structure_header_topology.py
```

Expected: 全部通过；既有“真实父表头启动行”和“普通单行标题启动行”反例继续通过。

- [ ] **Step 5: 提交测试与实现**

```powershell
git add src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py tests/test_wireless_structure_grid.py tests/test_page_987_table_recovery.py
git commit -m "fix(wireless): 修复混合叶表头逻辑行压缩"
```

---

### Task 3: 页面级验证、扩展回归和交付记录

**Files:**
- Modify: `changes.md`
- Generate: `output/page_987_mixed_leaf_header_fix_20260903/pages/page-987.json`
- Generate: `output/page_987_mixed_leaf_header_fix_20260903/tables/page-987.png`

**Interfaces:**
- Consumes: 修复后的完整 `PDFParser` 页面解析流程。
- Produces: 独立页面输出、结构化验收数据、最终视觉结果和中文变更记录。

- [ ] **Step 1: 运行相关页面集成回归**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n base python -m pytest -q `
  tests/test_page_435_table_recovery.py `
  tests/test_page_1014_table_recovery.py `
  tests/test_page_987_table_recovery.py
```

Expected: 全部通过；Page 435、436、1014 的结构保持不变。

- [ ] **Step 2: 独立重跑 Page 987**

使用 `PDFParser.parse(page_indices=[987])`，输入 `fix/zh_all_table_pages.pdf`，输出到 `output/page_987_mixed_leaf_header_fix_20260903/`，开启 JSON、Markdown 和表格 PNG 可视化。不得复用已有全量输出目录。

- [ ] **Step 3: 核对结构化结果**

检查 `pages/page-987.json`：一张 `wireless_span_recovery` 表、bbox 约 `[84.2, 91.1, 506.2, 362.5]`、`6x7`、36 个 Cell；42 个逻辑槽位完整且唯一占用；表头跨度和空槽位符合设计。

- [ ] **Step 4: 核对最终 PNG**

检查 `tables/page-987.png`：两层表头、父表头组内无竖线、组间边界保留、前四列和末列无穿越标题的伪横线，四行正文与相邻文本未误并。

- [ ] **Step 5: 更新中文变更记录**

在 `changes.md` 顶部记录：Page 987 根因、`1:2` 完整父子证明条件、调用位置、不回读 words 约束、测试结果和独立页面输出绝对路径。

- [ ] **Step 6: 最终验证并提交**

Run:

```powershell
git diff --check
git status --short
```

确认只包含本任务文件后：

```powershell
git add changes.md
git commit -m "docs: 记录 Page 987 表头修复验证"
```

Expected: 工作树干净，页面与测试结果完整记录。
