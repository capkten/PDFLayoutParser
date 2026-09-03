# Page 988/989 短横线占位符伪列修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让窄短横线占位符按水平覆盖比例归入对应金额列，消除 Page 988/989 的 5 条伪空列，同时保留 Page 944 的跨列擦碰拒绝行为。

**Architecture:** 仅修改列带连通组件的来源判定 `_compatible()`。占位符与数值采用占位符 bbox 覆盖比例，其他 atom 的列带兼容、叶子列细化、逻辑网格和空槽物化流程保持不变。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、native-span 无线表格恢复。

## Global Constraints

- 中文和 mixed 页面继续使用 native-span 新结构恢复，不回退到 zebra 或 legacy words 重建。
- atom 阶段之后不得调用 `page.get_text("words")`。
- 空槽继续物化为独立 `1x1` Cell，最终逻辑槽位必须恰好被一个 Cell 占用。
- 只修改本问题直接涉及的测试、列带兼容条件和中文变更记录。

---

### Task 1: 用覆盖比例连接窄占位符与金额列

**Files:**
- Modify: `tests/test_wireless_structure_columns.py`
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/columns.py:46-61`

**Interfaces:**
- Consumes: `_compatible(left: dict[str, Any], right: dict[str, Any]) -> bool`
- Produces: `infer_column_bands()` 可将与金额 bbox 高比例重叠的窄占位符纳入同一水平组件。

- [ ] **Step 1: 写入最小失败测试**

```python
def test_infer_column_bands_merges_narrow_placeholder_with_right_aligned_amounts():
    atoms = [
        _atom("100.00", 180.0, 10.0, 225.9),
        _atom("200.00", 180.0, 30.0, 225.9),
        _atom("-", 222.14, 50.0, 225.904),
        _atom("-", 222.14, 70.0, 225.904),
    ]

    bands = infer_column_bands(atoms, BBox(0.0, 0.0, 400.0, 90.0))

    assert len(bands) == 1
    assert bands[0]["x0"] == 180.0
    assert bands[0]["x1"] == 225.904
```

- [ ] **Step 2: 运行测试并确认因固定 4pt 下限失败**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='D:\codes\PDFLayoutParser\.worktrees\fix-page-988-989-empty-columns\src'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests\test_wireless_structure_columns.py::test_infer_column_bands_merges_narrow_placeholder_with_right_aligned_amounts`

Expected: FAIL，实际得到两个列带而不是一个。

- [ ] **Step 3: 写入最小生产修改**

```python
if (left_ph and right_num) or (right_ph and left_num):
    ph = left if left_ph else right
    ph_w = max(1.0, ph["bbox"][2] - ph["bbox"][0])
    return overlap >= ph_w * 0.75
```

- [ ] **Step 4: 运行正例、反例和相关模块测试**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='D:\codes\PDFLayoutParser\.worktrees\fix-page-988-989-empty-columns\src'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests\test_wireless_structure_columns.py tests\test_page_944_table_recovery.py tests\test_wireless_structure_header_topology.py tests\test_wireless_structure_recoverer.py`

Expected: 全部通过；本地 PDF 缺失导致的集成测试只允许显示为 skip，不允许失败。

- [ ] **Step 5: 提交测试和实现**

```powershell
git add tests/test_wireless_structure_columns.py src/hexai_pdf_parser/tables/wireless_structure/columns.py
git commit -m "fix(wireless): 合并窄短横线金额列带"
```

### Task 2: 页面验证与变更记录

**Files:**
- Modify: `changes.md`
- Create ignored outputs: `D:\codes\PDFLayoutParser\output\fix_page_988_989_placeholder_columns_20260903\page-988\`
- Create ignored outputs: `D:\codes\PDFLayoutParser\output\fix_page_988_989_placeholder_columns_20260903\page-989\`

**Interfaces:**
- Consumes: `test_single.run_single_test(pdf_path, output_dir, dpi, ml_model_path, page_index)`
- Produces: 每页独立的 JSON、Markdown、页面 PNG 和表格 PNG。

- [ ] **Step 1: 对 Page 944/988/989 做结构级恢复检查**

使用 `fix/zh_all_table_pages.pdf` 和三个已知 table bbox 调用 `recover_cells_from_region()`。断言三页均为 13 列，Page 988/989 不存在整列为空，并检查每个逻辑槽位占用次数均为 1。

```python
import fitz
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region

regions = {
    944: BBox(76.0, 86.8, 746.5, 413.5),
    988: BBox(33.5, 117.2, 807.8, 457.6),
    989: BBox(41.5, 117.6, 794.2, 261.1),
}
with fitz.open(r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf") as document:
    for page_index, bbox in regions.items():
        rows, cols, cells = recover_cells_from_region(document[page_index], bbox)
        assert cols == 13
        assert not [
            col for col in range(cols)
            if not any(cell.col_index == col and cell.text for cell in cells)
        ]
        occupied = {}
        for cell in cells:
            for row in range(cell.row_index, cell.row_index + cell.rowspan):
                for col in range(cell.col_index, cell.col_index + cell.colspan):
                    occupied[(row, col)] = occupied.get((row, col), 0) + 1
        assert set(occupied.values()) == {1}
        assert len(occupied) == rows * cols
```

- [ ] **Step 2: 生成 Page 988/989 独立页面输出**

```python
from test_single import run_single_test

for page_index in (988, 989):
    run_single_test(
        pdf_path=r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf",
        output_dir=rf"D:\codes\PDFLayoutParser\output\fix_page_988_989_placeholder_columns_20260903\page-{page_index}",
        page_index=page_index,
    )
```

Expected: 两页均识别 1 张 `wireless_span_recovery` 表格，列数为 13，并生成 `tables/page-988.png`、`tables/page-989.png`。

- [ ] **Step 3: 更新中文变更记录**

在 `changes.md` 记录根因、75% 覆盖判定、调用位置、不回读 words、测试结果和页面输出绝对路径。

- [ ] **Step 4: 完成最终检查并提交**

Run: `git diff --check`

Run: 重新执行 Task 1 的完整相关测试，并核对 Page 988/989 JSON 的表格数量、source、行列数、跨度、空列和占位冲突。

```powershell
git add changes.md
git commit -m "docs: 记录 Page 988 和 989 空列修复"
```

### Task 3: 合并并复验

**Files:**
- No source file changes.

**Interfaces:**
- Consumes: 已验证的 `codex/fix-page-988-989-empty-columns` 分支提交。
- Produces: 合并到 `feature-dev` 的修复。

- [ ] **Step 1: 合并前确认 feature-dev 的并发更新并处理冲突**

Run: `git log --oneline --decorate -5 feature-dev`

在主工作区执行 `git merge codex/fix-page-988-989-empty-columns`，保留用户现有未提交文件和其他 agent 的提交。

- [ ] **Step 2: 在合并结果上重新运行相关测试**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='D:\codes\PDFLayoutParser\src'; pytest -q tests/test_wireless_structure_columns.py tests/test_page_944_table_recovery.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_recoverer.py`

Expected: 全部通过。

- [ ] **Step 3: 清理本次创建的 worktree 和已合并分支**

从主工作区移除 `.worktrees/fix-page-988-989-empty-columns`，执行 `git worktree prune`，再安全删除已合并分支。
