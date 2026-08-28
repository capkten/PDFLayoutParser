# 中文财务表 native-span 冲突恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复模型已检测但 native-span 结构恢复失败的 `page-439` 上方表格和 `page-440` 宽表，并保证最终逻辑网格无槽位冲突。

**Architecture:** 在 `text_runs` 的 atom 构造阶段增加“严格连续输出 + 右侧见证”的多行字段组合。表头跨度在副本上整层推断并重新检查 occupancy，冲突时回退已验证的基础逻辑网格。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、项目现有 native-span wireless structure pipeline。

## Global Constraints

- 中文/混合页面只使用 native-span 新结构恢复，不回退 legacy page-words 路径。
- 多行字段在 atom 阶段组合，后续不得仅因落入同一槽位而合并。
- 组合保留 flow、span、block 和 line 来源证据；不得调用 `page.get_text("words")`。
- 两段独立金额或占位符默认不合并。
- 表头跨度按整层提交；冲突则放弃整层，不保留部分跨度。
- 空槽物化为独立 `text=""`、`1x1` Cell；最终每个槽位恰好被一个 Cell 占用。
- 不硬编码财务表业务文字。

---

### Task 1: 使用输出顺序和右侧见证组合多行 atom

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py:176-280`
- Test: `tests/test_wireless_structure_text_runs.py`

**Interfaces:**
- Consumes: `build_text_runs(spans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]`。
- Produces: `_is_wrapped_field_pair(left, right, runs) -> bool` 使用 flow 连续性、上下几何和右侧见证；结果保留 `span_refs`、`source_blocks`、`source_line_start/end`。

- [ ] **Step 1: 写入连续输出且存在右侧见证的失败测试**

```python
def test_build_text_runs_merges_consecutive_vertical_blocks_with_right_witness():
    atoms = [
        _atom("上半字段", 100, 160, 0, (1, 2, 0), y=10),
        _atom("下半字段", 100, 160, 1, (2, 0, 0), y=24),
        _atom("右侧字段", 240, 300, 2, (3, 0, 0), y=17),
    ]
    result = build_text_runs(atoms)
    assert [item["text"] for item in result] == ["上半字段\n下半字段", "右侧字段"]
    assert result[0]["flow_start"] == 1
    assert result[0]["flow_end"] == 2
    assert result[0]["span_refs"] == ["S0", "S1"]
    assert result[0]["source_blocks"] == [1, 2]
    assert result[0]["merge_kind"] == "wrapped_field"
```

- [ ] **Step 2: 写入金额、flow 跳跃和独立右侧行三个反例**

```python
def test_build_text_runs_keeps_consecutive_amount_rows_separate_with_right_witness():
    atoms = [
        _atom("100.00", 100, 150, 0, (1, 0, 0), y=10),
        _atom("200.00", 100, 150, 1, (2, 0, 0), y=24),
        _atom("右侧", 240, 280, 2, (3, 0, 0), y=17),
    ]
    assert [item["text"] for item in build_text_runs(atoms)] == ["100.00", "200.00", "右侧"]


def test_build_text_runs_requires_strict_flow_continuity_for_wrapped_blocks():
    atoms = [
        _atom("上半字段", 100, 160, 0, (1, 0, 0), y=10),
        _atom("跳过字段", 20, 70, 1, (2, 0, 0), y=50),
        _atom("下半字段", 100, 160, 2, (3, 0, 0), y=24),
        _atom("右侧字段", 240, 300, 3, (4, 0, 0), y=17),
    ]
    assert "上半字段\n下半字段" not in {item["text"] for item in build_text_runs(atoms)}


def test_build_text_runs_keeps_two_rows_when_right_side_has_independent_peers():
    atoms = [
        _atom("左一", 100, 140, 0, (1, 0, 0), y=10),
        _atom("左二", 100, 140, 1, (2, 0, 0), y=24),
        _atom("右一", 240, 280, 2, (3, 0, 0), y=10),
        _atom("右二", 240, 280, 3, (4, 0, 0), y=24),
    ]
    assert [item["text"] for item in build_text_runs(atoms)] == ["左一", "左二", "右一", "右二"]
```

- [ ] **Step 3: 运行新增测试并确认正例失败**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py
```

Expected: 新正例 FAIL，因为现有 `_same_source_line()` 拒绝跨 native line/block；既有用例继续通过。

- [ ] **Step 4: 最小实现连续 flow 和右侧见证**

```python
def _strictly_flow_continuous(left, right):
    return right["flow_start"] == left["flow_end"] + 1


def _right_witnesses(left, right, runs):
    y0 = min(left["bbox"][1], right["bbox"][1])
    y1 = max(left["bbox"][3], right["bbox"][3])
    x1 = max(left["bbox"][2], right["bbox"][2])
    return [
        item for item in runs
        if item is not left and item is not right
        and item["flow_start"] > right["flow_end"]
        and item["bbox"][0] >= x1 + 8.0
        and min(y1, item["bbox"][3]) > max(y0, item["bbox"][1])
    ]
```

`_is_wrapped_field_pair()` 继续检查字体兼容、非金额/占位符、垂直顺序、水平重叠和换行距离。只有存在右侧见证，且见证没有分别贴合上下中心形成两个独立物理行时才合并。不得修改 `merge_same_slot_fragments()`。

- [ ] **Step 5: 运行 `tests/test_wireless_structure_text_runs.py`，预期全部 PASS**

- [ ] **Step 6: 提交 Task 1**

```powershell
git add src/hexai_pdf_parser/tables/wireless_structure/text_runs.py tests/test_wireless_structure_text_runs.py
git commit -m "fix: 按输出顺序组合多行字段"
```

---

### Task 2: 表头跨度冲突时整层回退基础逻辑网格

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py:102-119`
- Test: `tests/test_wireless_structure_recoverer.py`
- Test: `tests/test_wireless_structure_grid.py`

**Interfaces:**
- Consumes: `merge_header_spans(cells, header_cutoff)` 和 `_has_occupancy_conflict(cells)`。
- Produces: `_commit_header_spans_or_keep_base(cells, header_cutoff) -> list[dict[str, Any]]`。

- [ ] **Step 1: 写入冲突回退失败测试**

```python
def test_header_span_conflict_keeps_conflict_free_base_grid(monkeypatch):
    base = [
        {"cell_id": "A", "text": "左", "bbox": [0, 0, 10, 10], "row_start": 1, "row_end": 1, "col_start": 1, "col_end": 1, "rowspan": 1, "colspan": 1},
        {"cell_id": "B", "text": "右", "bbox": [10, 0, 20, 10], "row_start": 1, "row_end": 1, "col_start": 2, "col_end": 2, "rowspan": 1, "colspan": 1},
    ]
    conflicting = [dict(item) for item in base]
    conflicting[0].update(col_end=2, colspan=2)
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.wireless_structure.recoverer.merge_header_spans",
        lambda cells, cutoff: conflicting,
    )
    result = _commit_header_spans_or_keep_base(base, header_cutoff=20)
    assert result == base
    assert _has_occupancy_conflict(result) is False
```

- [ ] **Step 2: 运行单测，预期因 helper 尚未定义而 FAIL**

- [ ] **Step 3: 实现事务 helper 并替换直接表头合并**

```python
def _commit_header_spans_or_keep_base(cells, header_cutoff):
    base = [dict(cell) for cell in cells]
    proposed = merge_header_spans(base, header_cutoff)
    if _has_occupancy_conflict(proposed):
        return [dict(cell) for cell in cells]
    return proposed
```

基础逻辑网格本身有冲突时仍拒绝整表；只有表头跨度新增的冲突允许回退。

- [ ] **Step 4: 增加无冲突跨度仍提交的正例，并运行 grid/recoverer 全部测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_grid.py tests/test_wireless_structure_recoverer.py
```

Expected: 全部 PASS，既有 `rowspan/colspan` 正例不回退。

- [ ] **Step 5: 提交 Task 2**

```powershell
git add src/hexai_pdf_parser/tables/wireless_structure/recoverer.py tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_grid.py
git commit -m "fix: 表头跨度冲突时回退基础网格"
```

---

### Task 3: 页面级回归、可视化和变更记录

**Files:**
- Modify: `changes.md`
- Verify: `D:/codes/PDFLayoutParser/fix/zh_all_table_pages.pdf`
- Create output: `output/page_439_440_native_span_conflict_20260828/`

**Interfaces:**
- Consumes: 当前 `PDFParser` 指定页解析入口。
- Produces: 页索引 `439`、`440` 的 JSON、Markdown、整页 PNG 和表格 PNG。

- [ ] **Step 1: 运行 native-span 相关回归测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_recoverer.py tests/test_wireless_table_recovery.py
```

- [ ] **Step 2: 将页索引 `[439, 440]` 重跑到新的独立目录**

输入：`D:/codes/PDFLayoutParser/fix/zh_all_table_pages.pdf`

输出：`D:/codes/PDFLayoutParser/output/page_439_440_native_span_conflict_20260828`

- [ ] **Step 3: 核对结构化输出**

```text
page-439：上下两张表均存在；上表三列多行字段不冲突，相邻表格不误并。
page-440：宽表存在；叶子列、金额和 -- 占位符保留。
两页：最终 occupancy conflict=false；空槽都是独立 1x1 Cell。
```

- [ ] **Step 4: 视觉核对表格 PNG**

```text
output/page_439_440_native_span_conflict_20260828/tables/page-439.png
output/page_439_440_native_span_conflict_20260828/tables/page-440.png
```

- [ ] **Step 5: 更新中文 `changes.md`**

记录根因、连续输出与右侧见证、三个否决条件、事务式表头回退、不回读 words、测试结果和页面输出路径。

- [ ] **Step 6: 运行最终检查并提交**

```powershell
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe' -m py_compile src/hexai_pdf_parser/tables/wireless_structure/text_runs.py src/hexai_pdf_parser/tables/wireless_structure/recoverer.py
git diff --check
git add changes.md
git commit -m "docs: 记录中文表格冲突恢复"
```
