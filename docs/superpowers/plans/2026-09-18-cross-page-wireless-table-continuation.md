# 跨页无线表格续写候选切分修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复中文无线表格候选生成把机构名称续写误切成标题的问题，使目标 PDF 第 1 页（0-based）的机构查询记录恢复为一个 `12x4` 表并保留编号 8--19。

**Architecture:** 在 `merge_wrapped_rows()` 中保留现有几何和文本约束；当单字段行既与上一行唯一字段列带重叠、又被判定为居中时，将其文本、Span 来源和 bbox 并入上一行对应的 `TextStrip`，不制造第五列。候选表格、native-span 网格恢复、页面级表格 API 和跨页数据模型均保持不变。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、项目现有 native-span wireless recovery、PowerShell 页面级验证脚本。

## Global Constraints

- `zh`/`mixed` 无线表格继续使用 native-span 结构路径；不得回退到 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或基于 `page.get_text("words")` 的二次表格重建。
- 只修改候选行归类逻辑；不得修改 `src/hexai_pdf_parser/tables/wireless_structure/` 下的 atom、列带、逻辑网格、跨度和空槽位实现。
- 普通同列续行仍保留为同一视觉行中的独立 `TextStrip`；只有“单字段、唯一列带重叠、几何上居中”的特殊续写并入已有字段条。
- 真正位于上一行列带之间且没有水平重叠的居中标题必须保持独立。
- 目标 PDF 的页面级 `Table` bbox 不跨页；本次不新增 `logical_table_id`。
- 生产代码必须在对应失败测试之后编写；每次修改都要先运行针对性测试，再运行相关回归测试。
- 新页面输出必须写入独立目录 `output/cross_page_wireless_table_continuation_20260918/`，不得覆盖旧输出。
- 说明文档和 `changes.md` 使用中文；工作区已有无关改动必须保留。

---

### Task 1: 添加可重复的失败回归测试

**Files:**
- Modify: `tests/test_wireless_table_recovery.py:10-35`（增加 `pytest` 导入无需新增文件）
- Modify: `tests/test_wireless_table_recovery.py:304` 附近（增加单字段居中续写测试）
- Modify: `tests/test_wireless_table_recovery.py` 文件末尾（增加目标 PDF 集成测试）

**Interfaces:**
- Consumes: 现有 `NativeSpan`、`TextStrip`、`merge_wrapped_rows()`、`TableExtractor`。
- Produces: 能证明当前实现错误的两个测试；第一个测试验证字段条合并，第二个测试验证真实 PDF 的 `12x4` 机构表和独立本人查询表。现有的居中标题反例测试继续作为回归保护。

- [ ] **Step 1: 在测试文件中增加 `pytest` 导入和单元失败用例**

在 `tests/test_wireless_table_recovery.py` 的 `from pathlib import Path` 后增加 `import pytest`，并在已有 `test_merge_wrapped_rows_keeps_a_sparse_same_column_continuation` 后增加：

```python
def test_merge_wrapped_rows_appends_a_centered_continuation_to_the_overlapping_field():
    institution = NativeSpan("机构名称", BBox(40, 20, 180, 30), "Helvetica", 10, 0)
    number = NativeSpan("8", BBox(260, 20, 268, 30), "Helvetica", 10, 1)
    continuation = NativeSpan("司", BBox(135, 33, 145, 43), "Helvetica", 10, 2)
    rows = [
        [
            TextStrip(institution.text, institution.bbox, [institution]),
            TextStrip(number.text, number.bbox, [number]),
        ],
        [TextStrip(continuation.text, continuation.bbox, [continuation])],
    ]

    merged = merge_wrapped_rows(rows)

    assert len(merged) == 1
    assert len(merged[0]) == 2
    merged_institution = merged[0][0]
    assert merged_institution.text == "机构名称司"
    assert merged_institution.bbox == BBox(40, 20, 180, 43)
    assert [span.order for span in merged_institution.spans] == [0, 2]
    assert merged[0][1].text == "8"


```

新增测试在生产代码修改前必须失败，原因应是旧实现把 `"司"` 保留为第二条视觉行。现有 `test_merge_wrapped_rows_does_not_absorb_a_centered_section_title` 测试继续保护无列带重叠标题的行为，并且必须保持通过。

- [ ] **Step 2: 在测试文件末尾增加目标 PDF 回归用例**

增加以下测试。它使用页面级 `TableExtractor`，因此会覆盖 `merge_wrapped_rows()`、候选去重和现有 native-span 表格输出；目标文件不存在时只在其他机器上跳过，当前工作区必须实际执行：

```python
def test_personal_credit_continuation_page_keeps_institution_query_table_together():
    pdf_path = Path(
        r"D:\codes\PDFLayoutParser\个人信用报告\test\test\2_PDFsam_a1e4baf2-5f46-4f6b-865d-2d9240362880.pdf"
    )
    if not pdf_path.exists():
        pytest.skip(f"target PDF not found: {pdf_path}")

    with fitz.open(pdf_path) as document:
        tables = TableExtractor(use_ml_table_detector=False).extract(document[1])

    institution_tables = []
    for table in tables:
        texts = {cell.text.strip() for cell in table.cells}
        if table.source == "wireless_span_recovery" and all(
            str(number) in texts for number in range(8, 20)
        ):
            institution_tables.append(table)

    assert len(institution_tables) == 1
    institution = institution_tables[0]
    assert (institution.rows, institution.cols) == (12, 4)
    assert institution.source == "wireless_span_recovery"
    assert len(institution.cells) == 48

    occupied = set()
    for cell in institution.cells:
        for row_index in range(cell.row_index, cell.row_index + cell.rowspan):
            for col_index in range(cell.col_index, cell.col_index + cell.colspan):
                assert (row_index, col_index) not in occupied
                occupied.add((row_index, col_index))
    assert occupied == {
        (row_index, col_index)
        for row_index in range(12)
        for col_index in range(4)
    }

    personal_tables = [table for table in tables if table is not institution]
    assert len(personal_tables) == 1
    personal = personal_tables[0]
    assert (personal.rows, personal.cols) == (4, 4)
    assert personal.source == "wireless_span_recovery"
    assert institution.bbox.y1 < personal.bbox.y0
```

- [ ] **Step 3: 运行新增测试，确认它们按预期失败**

运行：

```powershell
$env:PYTHONPATH='src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest tests/test_wireless_table_recovery.py -q
```

预期：基线的 23 个既有测试仍通过；新的字段合并测试失败，错误显示 `"司"` 仍是独立行；目标 PDF 测试失败，因为当前结果没有一个同时包含编号 8--19 的候选表。若测试不是因预期行为失败，先修正测试输入和断言，不修改生产代码。

- [ ] **Step 4: 提交只包含测试的 RED 提交**

```powershell
git add tests/test_wireless_table_recovery.py
git commit -m "test: reproduce cross-page wireless table split"
```

---

### Task 2: 实现唯一列带重叠的居中续写合并

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_table_recovery.py:425-471`
- Test: `tests/test_wireless_table_recovery.py` 中 Task 1 的两个测试

**Interfaces:**
- Consumes: `merge_wrapped_rows(rows)` 的现有 `TextStrip` 序列和 `_union()`、`_is_number()`、`_looks_like_field()` 约束。
- Produces: 原函数签名不变；特殊续写并入上一行唯一重叠字段，普通续行和无重叠标题行为不变。

- [ ] **Step 1: 在 `merge_wrapped_rows()` 中加入唯一重叠目标和字段条内合并**

保留函数其他行为，将函数体替换为以下实现：

```python
def merge_wrapped_rows(rows: Sequence[Sequence[TextStrip]]) -> List[List[TextStrip]]:
    """Merge sparse, close continuation lines back into their visual row.

    Only a row that is sparser than a preceding multi-column row may be a
    continuation. Each strip must horizontally fall in an occupied preceding
    column. A centered single-strip continuation that overlaps exactly one
    preceding field is appended to that field instead of creating a new column.
    """

    if len(rows) < 2:
        return [list(row) for row in rows]
    heights = [strip.bbox.y1 - strip.bbox.y0 for row in rows for strip in row]
    gap_limit = max(12.0, (statistics.median(heights) if heights else 10.0) * 1.45)
    merged: List[List[TextStrip]] = [list(rows[0])]
    for row in rows[1:]:
        current = merged[-1]
        previous_box = _union(strip.bbox for strip in current)
        row_box = _union(strip.bbox for strip in row)
        close = 0 <= row_box.y0 - previous_box.y1 <= gap_limit
        sparse = len(current) >= 2 and len(row) < len(current)
        centered_section_title = (
            len(row) == 1
            and abs((row_box.x0 + row_box.x1 - previous_box.x0 - previous_box.x1) / 2.0)
            <= max(18.0, (previous_box.x1 - previous_box.x0) * 0.12)
        )
        aligned = all(
            any(
                strip.bbox.x1 >= existing.bbox.x0 - 8.0
                and strip.bbox.x0 <= existing.bbox.x1 + 8.0
                for existing in current
            )
            for strip in row
        )
        overlapping_fields = []
        if len(row) == 1:
            overlapping_fields = [
                existing
                for existing in current
                if row[0].bbox.x1 >= existing.bbox.x0 - 8.0
                and row[0].bbox.x0 <= existing.bbox.x1 + 8.0
            ]
        centered_continuation_target = (
            overlapping_fields[0]
            if centered_section_title and aligned and len(overlapping_fields) == 1
            else None
        )
        continuation = (
            close
            and sparse
            and aligned
            and (not centered_section_title or centered_continuation_target is not None)
            and not any(_is_number(strip.text) for strip in row)
            and not any(_looks_like_field(strip.text) for strip in row)
        )
        if continuation:
            if centered_continuation_target is not None:
                centered_continuation_target.text += row[0].text
                centered_continuation_target.bbox = _union(
                    (centered_continuation_target.bbox, row[0].bbox)
                )
                centered_continuation_target.spans.extend(row[0].spans)
                centered_continuation_target.spans.sort(key=lambda span: span.order)
            else:
                current.extend(row)
            current.sort(key=lambda item: (item.bbox.x0, item.order))
        else:
            merged.append(list(row))
    return merged
```

不得修改 `_table_runs()`、`_prepend_headers()`、`_build_table()` 或 native-span 结构恢复包。唯一重叠保护用于避免横跨列边界的标题被分配到不明确的字段。

- [ ] **Step 2: 运行新增单元测试并确认 GREEN**

运行：

```powershell
$env:PYTHONPATH='src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest tests/test_wireless_table_recovery.py::test_merge_wrapped_rows_appends_a_centered_continuation_to_the_overlapping_field tests/test_wireless_table_recovery.py::test_merge_wrapped_rows_does_not_absorb_a_centered_section_title -q
```

预期：2 passed。随后运行整文件：

```powershell
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest tests/test_wireless_table_recovery.py -q
```

预期：25 passed，输出无新增错误或警告。若目标 PDF 测试仍失败，只修改生产代码，不放宽测试断言。

- [ ] **Step 3: 提交最小生产修复**

```powershell
git add src/hexai_pdf_parser/tables/wireless_table_recovery.py
git commit -m "fix: merge centered wireless continuations into fields"
```

---

### Task 3: 运行相关回归测试并检查数据流约束

**Files:**
- Test: `tests/test_wireless_table_recovery.py`
- Test: `tests/test_wireless_structure_recoverer.py`
- Test: `tests/test_wireless_structure_grid.py`
- Test: `tests/test_wireless_structure_columns.py`
- Test: `tests/test_wireless_structure_merges.py`
- Test: `tests/test_unify_wireless_recovery.py`

**Interfaces:**
- Consumes: Task 2 的原生产修复。
- Produces: 专项回归结果；确认 native-span 结构路径、跨度、空槽位和相邻表格行为未被改动。

- [ ] **Step 1: 运行无线恢复和 native-span 结构专项测试**

运行：

```powershell
$env:PYTHONPATH='src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest `
  tests/test_wireless_table_recovery.py `
  tests/test_wireless_structure_recoverer.py `
  tests/test_wireless_structure_grid.py `
  tests/test_wireless_structure_columns.py `
  tests/test_wireless_structure_merges.py `
  tests/test_unify_wireless_recovery.py -q
```

预期：全部通过；若出现既有环境失败，记录完整失败测试名和原因，不把它们标记为本次修复通过。

- [ ] **Step 2: 检查修改只停留在候选切分和测试**

运行：

```powershell
git diff --stat HEAD~2..HEAD
git diff --check HEAD~2..HEAD
rg -n "page\.get_text\(\s*[\"']words|extract_zebra|_rebuild_text_aligned_table" src/hexai_pdf_parser/tables/wireless_table_recovery.py
```

预期：本次提交只涉及设计文档、无线候选恢复函数和回归测试；生产函数中没有新增 `page.get_text("words")`、斑马纹或 legacy 重建调用。

---

### Task 4: 对目标 PDF 做独立页面级验证并检查 PNG

**Files:**
- Create: `output/cross_page_wireless_table_continuation_20260918/`（忽略目录中的新验证输出）
- Inspect: 该目录下的页面 JSON、PNG 和渲染结果

**Interfaces:**
- Consumes: 目标 PDF、项目现有 `test_single.py`/`PDFParser`、Task 2 的修复。
- Produces: 0-based 页面 0 和 1 的独立输出；问题页机构查询表 `12x4`、编号 8--19 完整、本人查询表独立。

- [ ] **Step 1: 运行 2 页全链路解析到新目录**

运行：

```powershell
$target = 'D:\codes\PDFLayoutParser\个人信用报告\test\test\2_PDFsam_a1e4baf2-5f46-4f6b-865d-2d9240362880.pdf'
$output = 'D:\codes\PDFLayoutParser\.worktrees\fix-cross-page-wireless-table-20260918\output\cross_page_wireless_table_continuation_20260918'
$model = 'D:\codes\PDFLayoutParser\.worktrees\fix-cross-page-wireless-table-20260918\src\hexai_pdf_parser\ml\table_detector_model\best.onnx'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' test_single.py `
  --pdf $target --pages 0,1 --output-dir $output --model-path $model --dpi 200
```

预期：两个页面均完成解析，输出目录为上述新路径；旧的 `output/demo_personal_credit_test_20260918` 不被覆盖。

- [ ] **Step 2: 用结构化输出核对问题页**

运行：

```powershell
$output = 'D:\codes\PDFLayoutParser\.worktrees\fix-cross-page-wireless-table-20260918\output\cross_page_wireless_table_continuation_20260918'
Get-ChildItem -LiteralPath $output -Recurse -File | Sort-Object FullName | Select-Object FullName
```

再用 `pages/page-001.json` 检查 page index 1，确认：

```text
机构查询表：source=wireless_span_recovery，rows=12，cols=4，编号集合={8,...,19}
机构查询表：48 个 Cell，所有 12*4 槽位恰好占用一次，occupancy conflict=0
本人查询记录明细：仍为独立表格，bbox.y0 大于机构查询表 bbox.y1
```

可复用下列只读检查脚本从页面结果中打印 table 摘要：

```powershell
$json = Join-Path $output 'pages\page-001.json'
if (-not (Test-Path -LiteralPath $json)) { throw "page 1 JSON output was not found: $json" }
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' - $json @'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
page = payload.get("page", payload)
tables = page.get("tables", [])
print("table_count", len(tables))
institution = None
for table in tables:
    texts = {cell.get("text", "").strip() for cell in table.get("cells", [])}
    if all(str(number) in texts for number in range(8, 20)):
        institution = table
        print("institution", table["source"], table["rows"], table["cols"], len(table["cells"]))
        print("numbers", sorted(int(text) for text in texts if text.isdigit()))
if institution is None or len(tables) != 2:
    raise AssertionError("page 1 must contain one institution table and one personal table")
personal = next(table for table in tables if table is not institution)
if personal["bbox"]["y0"] <= institution["bbox"]["y1"]:
    raise AssertionError("personal table must remain below the institution table")
print("personal", personal["source"], personal["rows"], personal["cols"])
'@
```

- [ ] **Step 3: 检查最终 PNG**

读取新输出中 page 1 的最终可视化 PNG，重点确认：

- 机构查询区域只有一个从编号 8 延续到 19 的表格外框；
- 机构名称续写文字在第四列对应的同一 Cell/字段区域内，没有第五条逻辑列；
- 四列边界连续，行间没有三个 `3x4` 碎片的空洞；
- “本人查询记录明细”下方保持独立外框，没有被上表吸收；
- 红色/蓝色网格与原始文字对齐，未出现跨表误并。

---

### Task 5: 更新中文交付记录并完成最终验证

**Files:**
- Modify: `changes.md`（在当前日期段新增条目）
- Inspect: `git diff --check`、相关测试输出、独立页面输出

**Interfaces:**
- Consumes: Task 3 的测试结果和 Task 4 的结构化/视觉证据。
- Produces: 可审计的中文变更记录和最终工作区状态；不提交用户原有无关文件。

- [ ] **Step 1: 在 `changes.md` 增加实际验证记录**

新增中文条目必须包含以下已确认事实：

```text
2026-09-18：修复个人信用报告跨页机构查询无线表格候选切分。根因是 merge_wrapped_rows() 将与上一行机构列带水平重叠、但整体几何居中的单字段续写判为标题，导致 _table_runs() 切断候选、_prepend_headers() 再将残留续写补成伪表头。现在仅当该续写唯一落入已有列带时，将其文本、Span 来源和 bbox 并入原字段条；无重叠的真实居中标题保持独立。修复位于无线候选生成阶段，继续使用 native-span 数据，不回读 page.get_text("words")，不修改 extract_zebra()、legacy 重建、逻辑网格或跨页 bbox。目标 PDF 第 1 页（0-based）机构查询表恢复为 12x4，编号 8--19 完整，本人查询表保持独立。专项测试和页面级验证的实际命令、通过/失败数量，以及独立输出路径为 D:\codes\PDFLayoutParser\.worktrees\fix-cross-page-wireless-table-20260918\output\cross_page_wireless_table_continuation_20260918\。
```

把其中测试通过/失败数量改为 Task 3 实际输出的数字；保留固定根因、判定条件、调用位置和输出绝对路径。

- [ ] **Step 2: 运行最终命令并读取完整结果**

运行：

```powershell
$env:PYTHONPATH='src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m pytest `
  tests/test_wireless_table_recovery.py `
  tests/test_wireless_structure_recoverer.py `
  tests/test_wireless_structure_grid.py `
  tests/test_wireless_structure_columns.py `
  tests/test_wireless_structure_merges.py `
  tests/test_unify_wireless_recovery.py -q
git diff --check
git status --short
```

只有在输出给出明确的通过/失败结果、`git diff --check` 无输出，并确认目标 PNG 已存在后，才能声称修复完成。任何既有失败都要原样列出，不能用“全部通过”概括。

- [ ] **Step 3: 提交中文变更记录**

```powershell
git add -f changes.md
git commit -m "docs: record cross-page wireless table validation"
```
