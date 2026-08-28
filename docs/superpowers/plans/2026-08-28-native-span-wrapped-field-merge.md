# 中文无线表格换行字段合并实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 native span 到 atom 阶段合并具有完整来源、几何和交错行证据的上下换行字段，使 `fix/zh_all_table_pages.pdf` 页面索引 191 的下方表格从错误的 `7x7` 恢复为 `3x7`。

**Architecture:** 保留现有同视觉行组合逻辑，在 `build_text_runs()` 返回前增加一次保守的 wrapped-field 合并。判定只使用 atom 已携带的 native source、flow、字体、脚本和 bbox；列带、物理网格、逻辑网格及后置 multiline 合并均不改变。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、项目现有 `wireless_structure` 模块。

## Global Constraints

- `zh`/`mixed` 页面继续使用 native-span 新结构恢复，不进入 `extract_zebra()` 或 legacy `_rebuild_text_aligned_table()`。
- span 到 atom 阶段完成同一字段的文本组合；后续阶段不得回读 `page.get_text("words")`。
- 不根据“注册”“与本公司”“法定代表人”等业务文字判定。
- 独立字段默认保持独立；只有来源连续、几何连续、交错行和唯一性证据全部成立时才合并。
- 最终逻辑槽位必须恰好由一个 Cell 占用，未覆盖槽位仍物化为独立空 `1x1` Cell。
- 设计和变更记录使用中文。

---

### Task 1: 用失败测试固定换行字段边界

**Files:**
- Modify: `tests/test_wireless_structure_text_runs.py`
- Modify: `tests/test_wireless_structure_recoverer.py`

**Interfaces:**
- Consumes: `build_text_runs(spans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]`
- Consumes: `recover_cells_from_region(page, region_bbox: BBox) -> tuple[int, int, list[Cell]]`
- Produces: wrapped-field 的正例、拒绝误合并反例和页面形状回归约束。

- [ ] **Step 1: 扩展 text-run 测试构造器以支持不同 y 坐标**

将 `tests/test_wireless_structure_text_runs.py` 的 `_atom` 改为保持现有调用兼容、额外接收 `y`：

```python
def _atom(
    text,
    x0,
    x1,
    order,
    source_position=(1, 1, 0),
    *,
    font_size=10,
    y=10,
):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 10],
        "order": order,
        "flow": order + 1,
        "source_position": list(source_position),
        "font": "SimSun",
        "font_size": font_size,
        "bold": False,
        "span_ref": f"S{order}",
        "char_boxes": [],
    }
```

- [ ] **Step 2: 添加五组交错换行字段的 atom 正例**

新增测试。source position 的前两项保持相同，第三项和 flow 连续；单行字段位于上下 span 中间，提供交错行证据：

```python
def test_build_text_runs_merges_native_continuous_wrapped_fields_before_grid():
    atoms = [
        _atom("企业名称", 100, 142, 0, (0, 0, 80), y=18.5),
        _atom("注册", 168, 189, 1, (0, 0, 81), y=10),
        _atom("地址", 168, 189, 2, (0, 0, 82), y=27),
        _atom("主营业务", 220, 262, 3, (0, 0, 83), y=18.5),
        _atom("与本公司", 289, 331, 4, (0, 0, 84), y=10),
        _atom("关系", 299.5, 320.5, 5, (0, 0, 85), y=27),
        _atom("业务", 339, 360, 6, (0, 0, 86), y=10),
        _atom("性质", 339, 360, 7, (0, 0, 87), y=27),
        _atom("法定", 379, 400, 8, (0, 0, 88), y=10),
        _atom("代表人", 374, 405.5, 9, (0, 0, 89), y=27),
        _atom("组织机构代码", 422, 485, 10, (0, 0, 90), y=18.5),
        _atom("杨志茂", 92, 124, 11, (0, 0, 91), y=70),
        _atom("本公司实", 289, 331, 12, (0, 0, 92), y=61.5),
        _atom("际控制人", 289, 331, 13, (0, 0, 93), y=78.5),
        _atom("---", 382, 403, 14, (0, 0, 94), y=70),
    ]

    result = build_text_runs(atoms)
    by_text = {item["text"]: item for item in result}

    assert {
        "注册\n地址",
        "与本公司\n关系",
        "业务\n性质",
        "法定\n代表人",
        "本公司实\n际控制人",
    } <= set(by_text)
    assert by_text["注册\n地址"]["bbox"] == [168, 10, 189, 37]
    assert by_text["注册\n地址"]["flow_start"] == 2
    assert by_text["注册\n地址"]["flow_end"] == 3
    assert by_text["注册\n地址"]["span_refs"] == ["S1", "S2"]
    assert by_text["注册\n地址"]["merge_kind"] == "wrapped_field"
```

- [ ] **Step 3: 添加没有交错行证据时拒绝合并的反例**

```python
def test_build_text_runs_keeps_close_native_continuous_rows_without_interleaving_evidence():
    atoms = [
        _atom("第一条", 100, 142, 0, (0, 0, 10), y=10),
        _atom("第二条", 100, 142, 1, (0, 0, 11), y=27),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["第一条", "第二条"]
```

- [ ] **Step 4: 添加 recoverer 的 `3x7` 集成回归测试**

在 `tests/test_wireless_structure_recoverer.py` 中用 `NativeSpan` 构造页面 191 下方表格的几何缩小样本。native 顺序保持“单行字段、上下 pair、单行字段”的来源顺序；包含 7 个稳定列、一个换行数据字段和第二条完整记录：

```python
def test_recover_cells_merges_wrapped_fields_before_physical_rows(monkeypatch):
    region = BBox(90, 0, 490, 120)
    raw = [
        (18.5, 103, 145, "企业名称"),
        (10, 168, 189, "注册"),
        (27, 168, 189, "地址"),
        (18.5, 220, 262, "主营业务"),
        (10, 289, 331, "与本公司"),
        (27, 299.5, 320.5, "关系"),
        (10, 339, 360, "业务"),
        (27, 339, 360, "性质"),
        (10, 379, 400, "法定"),
        (27, 374, 405.5, "代表人"),
        (18.5, 422, 485, "组织机构代码"),
        (61.5, 92, 124, "杨志茂"),
        (70, 160, 181, "---"),
        (70, 233, 254, "---"),
        (61.5, 289, 331, "本公司实"),
        (78.5, 289, 331, "际控制人"),
        (70, 342, 358, "---"),
        (70, 382, 403, "---"),
        (70, 446, 467, "---"),
        (100, 92, 157, "广东锦龙发展"),
        (100, 168, 189, "清远"),
        (100, 198, 285, "实业投资、房地产"),
        (100, 294, 326, "母公司"),
        (100, 339, 360, "上市"),
        (100, 379, 401, "杨志茂"),
        (100, 427, 485, "61797180-0"),
    ]
    spans = [
        NativeSpan(text, BBox(x0, y, x1, y + 10), "SimSun", 10.5, order)
        for order, (y, x0, x1, text) in enumerate(raw)
    ]
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.collect_native_spans",
        lambda page, allowed_regions: spans,
    )

    rows, columns, cells = recover_cells_from_region(object(), region)

    assert (rows, columns, len(cells)) == (3, 7, 21)
    occupied = {
        (row, column)
        for cell in cells
        for row in range(cell.row_index, cell.row_index + cell.rowspan)
        for column in range(cell.col_index, cell.col_index + cell.colspan)
    }
    assert len(occupied) == rows * columns
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 1).text == "注册\n地址"
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 3).text == "与本公司\n关系"
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 4).text == "业务\n性质"
    assert next(cell for cell in cells if cell.row_index == 0 and cell.col_index == 5).text == "法定\n代表人"
    assert next(cell for cell in cells if cell.row_index == 1 and cell.col_index == 3).text == "本公司实\n际控制人"
```

- [ ] **Step 5: 运行新增测试并确认 RED**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q `
  tests/test_wireless_structure_text_runs.py::test_build_text_runs_merges_native_continuous_wrapped_fields_before_grid `
  tests/test_wireless_structure_text_runs.py::test_build_text_runs_keeps_close_native_continuous_rows_without_interleaving_evidence `
  tests/test_wireless_structure_recoverer.py::test_recover_cells_merges_wrapped_fields_before_physical_rows
```

Expected: 正例和 `3x7` 集成测试失败，失败原因是 wrapped-field 尚未组合；反例通过。

- [ ] **Step 6: 提交测试**

```powershell
git add -- tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_recoverer.py
git commit -m "test: cover wrapped native span fields"
```

---

### Task 2: 在 atom 构造阶段实现保守合并

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py`

**Interfaces:**
- Consumes: `build_text_runs()` 已生成的同视觉行 run 列表。
- Produces: `_merge_wrapped_field_runs(runs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]`。
- Preserves: `span_refs`、`flow_start/flow_end`、bbox、source block/line、字符框、字体、粗体和脚本元数据。

- [ ] **Step 1: 增加纯几何和来源判定 helper**

在 `build_text_runs()` 之前增加：

```python
def _horizontal_overlap(left: Sequence[float], right: Sequence[float]) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0]))


def _same_source_line(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left["source_blocks"] == right["source_blocks"]
        and left["source_line_start"] == left["source_line_end"]
        and right["source_line_start"] == right["source_line_end"]
        and left["source_line_start"] == right["source_line_start"]
        and right["flow_start"] == left["flow_end"] + 1
    )
```

- [ ] **Step 2: 实现 wrapped-field 候选判定**

判定函数必须依次拒绝来源不连续、字体/粗体/脚本不兼容、纯数字或占位符、非向下布局、横向重叠不足、垂直间距过大，以及缺少交错行证据的 pair：

```python
def _is_wrapped_field_pair(
    left: dict[str, Any],
    right: dict[str, Any],
    runs: Sequence[dict[str, Any]],
) -> bool:
    if not _same_source_line(left, right):
        return False
    if (
        left["font"] != right["font"]
        or left["bold"] != right["bold"]
        or left["script"] != right["script"]
    ):
        return False
    if (
        _NUMERIC.fullmatch(left["text"].strip())
        or _NUMERIC.fullmatch(right["text"].strip())
        or _is_placeholder(left)
        or _is_placeholder(right)
    ):
        return False
    left_center = _center_y(left)
    right_center = _center_y(right)
    if right_center <= left_center:
        return False
    minimum_width = min(
        left["bbox"][2] - left["bbox"][0],
        right["bbox"][2] - right["bbox"][0],
    )
    if _horizontal_overlap(left["bbox"], right["bbox"]) < minimum_width * 0.45:
        return False
    if right["bbox"][1] - left["bbox"][3] > max(
        6.0, min(left["font_size"], right["font_size"])
    ):
        return False

    between = [
        item
        for item in runs
        if item is not left
        and item is not right
        and left_center < _center_y(item) < right_center
    ]
    if not between:
        return False
    return all(
        _horizontal_overlap(left["bbox"], item["bbox"])
        < min(minimum_width, item["bbox"][2] - item["bbox"][0]) * 0.45
        and _horizontal_overlap(right["bbox"], item["bbox"])
        < min(minimum_width, item["bbox"][2] - item["bbox"][0]) * 0.45
        for item in between
    )
```

- [ ] **Step 3: 实现唯一候选组合并保留来源信息**

只考察 native-flow 相邻 run。先收集候选 pair，再统计每个 run 出现次数；只有两端都只属于一个候选时才组合：

```python
def _merge_wrapped_field_runs(
    runs: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted((dict(item) for item in runs), key=lambda item: item["flow_start"])
    candidates = [
        (index, index + 1)
        for index in range(len(ordered) - 1)
        if _is_wrapped_field_pair(ordered[index], ordered[index + 1], ordered)
    ]
    use_count = Counter(index for pair in candidates for index in pair)
    pair_by_start = {
        left: right
        for left, right in candidates
        if use_count[left] == 1 and use_count[right] == 1
    }

    result: list[dict[str, Any]] = []
    index = 0
    while index < len(ordered):
        right_index = pair_by_start.get(index)
        if right_index is None:
            result.append(ordered[index])
            index += 1
            continue
        left = ordered[index]
        right = ordered[right_index]
        merged = dict(left)
        merged.update(
            text=left["text"] + "\n" + right["text"],
            bbox=_union([left, right]),
            span_refs=[*left["span_refs"], *right["span_refs"]],
            flow_start=left["flow_start"],
            flow_end=right["flow_end"],
            char_boxes=[*left.get("char_boxes", []), *right.get("char_boxes", [])],
            source_blocks=sorted(set(left["source_blocks"]) | set(right["source_blocks"])),
            source_line_start=min(left["source_line_start"], right["source_line_start"]),
            source_line_end=max(left["source_line_end"], right["source_line_end"]),
            merge_kind="wrapped_field",
        )
        result.append(merged)
        index = right_index + 1
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))
```

- [ ] **Step 4: 从 `build_text_runs()` 的唯一出口调用新步骤**

将最后一行：

```python
return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))
```

改为：

```python
return _merge_wrapped_field_runs(result)
```

- [ ] **Step 5: 运行新增测试并确认 GREEN**

运行 Task 1 Step 5 的同一命令。

Expected: `3 passed`。

- [ ] **Step 6: 运行无线结构相关测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q `
  tests/test_wireless_structure_text_runs.py `
  tests/test_wireless_structure_merges.py `
  tests/test_wireless_structure_grid.py `
  tests/test_wireless_structure_columns.py `
  tests/test_wireless_structure_recoverer.py
```

Expected: 全部通过，无 warning/error。

- [ ] **Step 7: 提交最小生产改动**

```powershell
git add -- src/hexai_pdf_parser/tables/wireless_structure/text_runs.py
git commit -m "fix: merge wrapped native span fields"
```

---

### Task 3: 页面级重跑、视觉核验和变更记录

**Files:**
- Modify: `changes.md`
- Create output: `output/page_191_wrapped_field_merge_20260828/`

**Interfaces:**
- Consumes: `PDFParser.parse(page_indices=[191])` 和 `draw_tables_on_page()`。
- Produces: 独立 JSON/Markdown/PNG 页面结果及中文交付记录。

- [ ] **Step 1: 重跑页面索引 191 到独立输出目录**

使用一次性 Python 调试片段打开 `fix/zh_all_table_pages.pdf`，调用：

```python
with PDFParser(pdf_path, ml_model_path=model_path) as parser:
    result = parser.parse(
        page_indices=[191],
        output_dir="output/page_191_wrapped_field_merge_20260828",
    )
```

然后用原 PDF 的 `doc[191]` 和结果页面 tables 调用 `draw_tables_on_page(..., draw_text_boxes=True)`，保存：

```text
output/page_191_wrapped_field_merge_20260828/tables/page-191.png
```

Expected: 命令退出码为 0，并生成新的页面 JSON、Markdown 和 PNG。

- [ ] **Step 2: 结构化核对目标表格**

读取新输出中的页面 JSON，验证：

- 页面索引为 `191`。
- 页面表格数量与重跑前一致。
- bbox 约为 `[92.0, 671.5, 488.0, 771.7]` 的目标表格 source 为 `wireless_span_recovery`。
- 目标表格为 `3x7`，共 21 个占位 Cell。
- `注册\n地址`、`与本公司\n关系`、`业务\n性质`、`法定\n代表人` 位于表头行。
- `本公司实\n际控制人` 位于第一条数据行。
- 每个逻辑槽位恰好被一个 Cell 覆盖，没有 occupancy conflict。

- [ ] **Step 3: 视觉核对最终 PNG**

检查新 PNG：目标表格中由上下换行产生的两条伪水平分割线消失；七列边界保留；空槽位线框完整；上下相邻表格没有误并，表格 bbox 未吸收正文或标题。

- [ ] **Step 4: 运行扩展相关测试和差异检查**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q `
  tests/test_wireless_structure_text_runs.py `
  tests/test_wireless_structure_merges.py `
  tests/test_wireless_structure_grid.py `
  tests/test_wireless_structure_columns.py `
  tests/test_wireless_structure_recoverer.py `
  tests/test_wired_table_extractor.py `
  tests/test_financial_header_normalizer.py
git diff --check
```

Expected: 所列测试全部通过；`git diff --check` 无输出且退出码为 0。

- [ ] **Step 5: 用中文更新 `changes.md`**

在 `2026-08-28` 条目记录：

- 页面 191 下方表格的根因是同字段上下 span 在 atom 阶段未组合，网格后因物理行不相邻而被拒绝。
- 新判定要求同 source line、flow 连续、字体/脚本兼容、横向重叠、紧密垂直间距、交错行和唯一候选证据。
- 调用位置为 `build_text_runs()` 返回前，不回读 page words，不修改 legacy 路径。
- 新增正例、拒绝误合并反例、相关测试数量及通过结果。
- 页面输出绝对路径和最终 `3x7`、source、occupancy、PNG 核验结果。

- [ ] **Step 6: 提交验证记录**

```powershell
git add -- changes.md
git commit -m "docs: record page 191 wrapped field recovery"
```

不要提交 `output/` 生成物，也不要暂存或清理本任务之外的现有工作区修改。
