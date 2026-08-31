# 二叶子列表头合并实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 依据多级表头拓扑恢复二叶子列父标题的 `colspan=2`，并在逻辑网格后让独立首列表头及父标题覆盖正确的表头行高。

**架构：** 在 `header_topology.py` 中以同层父标题和紧邻下层叶子标题的 1:2 完整配对推断横向跨度；在 `logical_grid.py` 中于逻辑行生成后、空单元格物化前扩展已确认表头单元格的 rowspan。两层均只消费 NativeSpan/atom、列带和逻辑 Cell，不回读 page words。

**技术栈：** Python 3.12、pytest、现有 wireless structure recovery。

## 全局约束

- 不依赖“年初数”“金额”“比例”“坏账准备”等具体文本。
- 中文和 mixed 页面只使用 native-span 结构恢复，不回读 page words。
- 中表保持 9 个叶子列，下表保持 5 个叶子列。
- colspan/rowspan 整理后每个逻辑槽位最多被一个 Cell 占用。
- 保留工作区中与本任务无关的已有修改。

---

### 任务 1：同层二叶子列父标题配对

**文件：**
- 修改：`tests/test_wireless_structure_header_topology.py`
- 修改：`src/hexai_pdf_parser/tables/wireless_structure/header_topology.py`

**接口：**
- 消费：`atoms: Sequence[dict[str, Any]]`、`bands: Sequence[dict[str, Any]]`、`header_cutoff: float`
- 产出：`_infer_two_leaf_parent_spans(...) -> dict[int, list[int]]`，键为 `id(parent_atom)`，值为两个连续叶子列 id。
- 集成：`annotate_columns()` 优先使用二叶子层级配对，再回退到现有 `_infer_centered_parent_span()`。

- [ ] **步骤 1：增加中表式四组二列失败测试**

在 `tests/test_wireless_structure_header_topology.py` 构造 1 个标签列、4 个同层父标题和 8 个同层叶子标题。父标题文字 bbox 仅覆盖单列，叶子列宽可不同，断言：

```python
annotate_columns(atoms, bands, header_cutoff=40)

assert [
    (atom["column_start"], atom["column_end"], atom["colspan"])
    for atom in parents
] == [
    (2, 3, 2),
    (4, 5, 2),
    (6, 7, 2),
    (8, 9, 2),
]
```

- [ ] **步骤 2：增加下表式不等宽二列失败测试和反例**

构造 2 个父标题、4 个叶子标题，其中每组两个 band 宽度显著不同，断言分别映射到 `C2:C3`、`C4:C5`。另构造只有 3 个叶子标题或一个父标题中心明显偏离的场景，断言不生成新的 `colspan=2`。

- [ ] **步骤 3：运行测试确认 RED**

运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_header_topology.py
```

预期：新增正例失败，父标题仍为 `colspan=1`；既有直接 bbox 跨列和三列以上父跨度测试通过。

- [ ] **步骤 4：实现同层整体配对**

在 `header_topology.py` 增加 `_infer_two_leaf_parent_spans()`：

```python
def _infer_two_leaf_parent_spans(
    atoms: Sequence[dict[str, Any]],
    bands: Sequence[dict[str, Any]],
    header_cutoff: float,
) -> dict[int, list[int]]:
    """Map a complete parent tier to non-overlapping two-leaf groups."""
```

实现约束：

1. 按 `_levels()` 分组表头 y 层；
2. 对每个候选父层，选择其下方最近的、能一对一归属叶子 band 的标题层；
3. 仅当叶子标题数恰好是父标题数的两倍，且叶子列 id 连续时继续；
4. 将排序后的叶子 id 每两个分组，与排序后的父标题按 x 顺序配对；
5. 每组必须包含父标题当前 `assign_column()` 的列；
6. 父标题中心与 band 组物理中心误差不超过 `max(4.0, group_width * 0.08)`；若父标题已经直接实质覆盖该二列，则保留该组；
7. 任一组不满足条件则放弃整个父层，防止产生局部重叠跨度。

在 `annotate_columns()` 循环前计算映射：

```python
two_leaf_parent_spans = (
    _infer_two_leaf_parent_spans(atoms, bands, header_cutoff)
    if header_cutoff is not None
    else {}
)
```

循环内先取 `two_leaf_parent_spans.get(id(atom), [])`，无结果时再调用现有 `_infer_centered_parent_span()`。

- [ ] **步骤 5：运行表头拓扑测试确认 GREEN**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_header_topology.py
```

预期：新增二列正例、反例及所有既有测试通过。

- [ ] **步骤 6：提交横向跨度任务**

```powershell
git add src/hexai_pdf_parser/tables/wireless_structure/header_topology.py tests/test_wireless_structure_header_topology.py
git commit -m "fix: infer two-leaf group headers"
```

### 任务 2：逻辑网格后的表头 rowspan

**文件：**
- 修改：`tests/test_wireless_structure_grid.py`
- 修改：`tests/test_wireless_structure_recoverer.py`
- 修改：`src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py`
- 修改：`src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`

**接口：**
- 消费：`cells: Sequence[dict[str, Any]]`、`header_cutoff: float | None`
- 产出：`merge_header_spans(cells, header_cutoff) -> list[dict[str, Any]]`
- 调用位置：`build_logical_grid()` 之后、第二次 `_has_occupancy_conflict()` 和 `materialize_empty_cells()` 之前。

- [ ] **步骤 1：增加父标题和首列 rowspan 失败测试**

在 `tests/test_wireless_structure_grid.py` 构造三层逻辑表头：

```text
R1: C2:C3 父标题 | C4:C5 父标题
R2: C1 首列表头
R3: C2 C3 C4 C5 四个叶子标题
```

调用 `merge_header_spans()` 后断言：

```python
assert (first_parent["row_start"], first_parent["row_end"], first_parent["rowspan"]) == (1, 2, 2)
assert (stub["row_start"], stub["row_end"], stub["rowspan"]) == (1, 3, 3)
```

并断言父标题覆盖范围之外的叶子单元格位置不变。

- [ ] **步骤 2：增加拒绝合并和占位反例**

增加两个反例：父标题与叶子之间存在非空单元格时不得扩展父标题；首列在其他表头行还有第二个非空标题时不得扩展首列表头。使用 recoverer 的 `_has_occupancy_conflict()` 断言正例合并后仍为 `False`。

- [ ] **步骤 3：运行测试确认 RED**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_grid.py tests/test_wireless_structure_recoverer.py
```

预期：因 `merge_header_spans` 尚不存在而失败，或新增跨度断言失败。

- [ ] **步骤 4：实现逻辑表头跨度整理**

在 `logical_grid.py` 增加：

```python
def merge_header_spans(
    cells: Sequence[dict[str, Any]],
    header_cutoff: float | None,
) -> list[dict[str, Any]]:
    """Extend proven group and stub headers through otherwise empty header slots."""
```

实现顺序：

1. 复制输入 cells；`header_cutoff is None` 时原样返回；
2. 用非空 Cell 的 bbox 中心识别表头 Cell；
3. 找出 `colspan >= 2` 的父标题，并寻找其下方同一行、逐列覆盖父范围的末级叶子标题；
4. 父标题到叶子行之间的覆盖列没有任何非空 Cell 时，将父标题 `row_end` 扩到 `leaf_row - 1`；
5. 汇总父标题列范围，查找范围外仅在一个表头行出现的单列标题；该列其他表头行没有非空 Cell 时，将其扩展为完整表头高度；
6. 每次扩展后同步设置 `rowspan = row_end - row_start + 1`；
7. 不修改 text、flow、列跨度和正文 Cell。

- [ ] **步骤 5：接入 recoverer 并保留冲突校验**

在 `recoverer.py` 中：

```python
logical_rows, logical_columns, logical_cells = build_logical_grid(
    physical_rows, columns, cells
)
logical_cells = merge_header_spans(logical_cells, header_cutoff)
if _has_occupancy_conflict(logical_cells):
    return 0, 0, []
```

不得把该调用移到 `build_logical_grid()` 之前。

- [ ] **步骤 6：运行网格和 recoverer 测试确认 GREEN**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_grid.py tests/test_wireless_structure_recoverer.py
```

预期：新增正反例和既有测试全部通过。

- [ ] **步骤 7：提交纵向跨度任务**

```powershell
git add src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py src/hexai_pdf_parser/tables/wireless_structure/recoverer.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_recoverer.py
git commit -m "fix: merge multi-level header row spans"
```

### 任务 3：page 192 回归验证和中文变更记录

**文件：**
- 修改：`changes.md`
- 生成：`output/page_192_group_header_spans/` 下的结构化输出和可视化 PNG。

**接口：**
- 消费：`fix/zh_all_table_pages.pdf`，0-based page index `192`。
- 产出：中表四个二列父标题、下表两个二列父标题，以及两个完整高度首列表头。

- [ ] **步骤 1：运行全部相关专项测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$taskTestFiles = @(Get-ChildItem tests/test_wireless_structure_*.py | ForEach-Object { $_.FullName })
$taskTestFiles += (Resolve-Path tests/test_financial_header_normalizer.py).Path
pytest -q $taskTestFiles
```

- [ ] **步骤 2：单页重跑到独立目录**

用现有 `PDFParser.parse(page_indices=[192])` 重跑 `fix/zh_all_table_pages.pdf`，输出到 `output/page_192_group_header_spans/`，不得覆盖旧输出。

- [ ] **步骤 3：验证结构化结果**

确认：

- 页面仍有三张 `wireless_span_recovery` 表；
- 中表 `5x9`，四个一级标题依次覆盖 `C2:C3`、`C4:C5`、`C6:C7`、`C8:C9`；
- 下表 `5x5`，两个一级标题依次覆盖 `C2:C3`、`C4:C5`；
- `企业名称`和`项目`分别覆盖本表全部表头行；
- occupancy conflict 为 0。

- [ ] **步骤 4：视觉检查最终 PNG**

检查 `output/page_192_group_header_spans/tables/page-192.png`：组内一级表头竖线消失，组间边界保留；首列表头上下没有独立空格；表框不吸收标题，相邻表不合并。

- [ ] **步骤 5：更新中文 changes.md**

记录根因、拓扑配对条件、rowspan 调用位置、未回读 words、测试数量和 page 192 最终结构。

- [ ] **步骤 6：最终校验并提交**

```powershell
git diff --check
git status --short
```

只暂存本任务相关代码、测试、计划和 `changes.md` 的本次条目，保留其他工作区修改。
