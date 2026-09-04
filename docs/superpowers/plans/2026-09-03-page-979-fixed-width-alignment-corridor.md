# Page 979 Fixed-Width Alignment Corridor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 native span 到 atom 阶段阻止 Page 979 中金额列与等宽地点列跨列误合并，同时保留数字与固定单位的合法组合。

**Architecture:** 扩展 `text_runs.py` 现有 `_has_alignment_corridor_veto()`，不改变 `_can_join()`、列带或网格职责。当一侧非对齐边缘固定时，用至少 3 个不同规范化文本值作为补充证据，但仍要求另一侧边缘变化、稳定对齐锚点和重复共同空白走廊。

**Tech Stack:** Python 3.12、PyMuPDF、pytest。

## Global Constraints

- 修复只在 `build_text_runs()` 合并前产生 veto，不做后续拆分。
- 只消费 native span、visual row、bbox、字体和 flow 信息，不调用 `page.get_text("words")`。
- 不依赖“深圳”“注册资本”“万元”等业务文字。
- 不修改 `extract_zebra()`、legacy `_rebuild_text_aligned_table()`、列带、物理 Cell 或逻辑 Cell 路径。
- 页面级验证写入新的独立输出目录，并核对结构化结果和最终 PNG。

---

### Task 1: 等宽多样文本列的合并否决

**Files:**
- Modify: `tests/test_wireless_structure_text_runs.py`
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py:303-390`

**Interfaces:**
- Consumes: `_has_alignment_corridor_veto(group, candidate, visual_rows) -> bool` 已收集的支持行。
- Produces: `_has_diverse_text_values(items: Sequence[dict[str, Any]]) -> bool`，仅用于对齐走廊 veto。

- [ ] **Step 1: 添加 Page 979 形态的失败测试**

在现有 corridor 测试旁添加三个金额右对齐、三个不同双字 CJK 值左对齐的用例：

```python
def test_build_text_runs_vetoes_fixed_width_diverse_aligned_column_join():
    atoms = [
        _atom("1,000.00", 184.0, 219.9, 0, (1, 0, 0), y=10),
        _atom("深圳", 223.13, 244.25, 1, (1, 0, 1), y=10),
        _atom("15,000.00", 179.2, 219.9, 2, (2, 0, 0), y=28),
        _atom("上海", 223.13, 244.25, 3, (2, 0, 1), y=28),
        _atom("500.00", 188.8, 219.9, 4, (3, 0, 0), y=46),
        _atom("南宁", 223.13, 244.25, 5, (3, 0, 1), y=46),
    ]

    assert [item["text"] for item in build_text_runs(atoms)] == [
        "1,000.00", "深圳", "15,000.00", "上海", "500.00", "南宁"
    ]
```

- [ ] **Step 2: 添加固定单位拒绝误伤测试**

使用同样的金额右对齐和通道，但右侧三行文本固定为“万元”；断言每行仍按现有规则组合为一个 atom：

```python
def test_build_text_runs_keeps_varying_amounts_with_fixed_unit_joined():
    atoms = [
        _atom("100.00", 188.8, 219.9, 0, (1, 0, 0), y=10),
        _atom("万元", 223.13, 244.25, 1, (1, 0, 1), y=10),
        _atom("1,000.00", 184.0, 219.9, 2, (2, 0, 0), y=28),
        _atom("万元", 223.13, 244.25, 3, (2, 0, 1), y=28),
        _atom("10,000.00", 179.2, 219.9, 4, (3, 0, 0), y=46),
        _atom("万元", 223.13, 244.25, 5, (3, 0, 1), y=46),
    ]

    assert [item["text"] for item in build_text_runs(atoms)] == [
        "100.00万元", "1,000.00万元", "10,000.00万元"
    ]
```

- [ ] **Step 3: 运行新增测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py -k 'fixed_width_diverse or varying_amounts_with_fixed_unit'
```

Expected: Page 979 正例失败，实际结果为三个 `金额+地点` atom；固定单位反例通过。

- [ ] **Step 4: 实现最小文本多样性证据**

在 `_opposite_edges_vary()` 附近新增：

```python
def _has_diverse_text_values(items: Sequence[dict[str, Any]]) -> bool:
    values = {
        "".join(str(item.get("text", "")).split())
        for item in items
    }
    values.discard("")
    return len(values) >= 3
```

在 `_has_alignment_corridor_veto()` 中先计算左右边缘变化，再用以下条件替换“双侧必须变化”的提前退出：

```python
left_varies = _opposite_edges_vary(left_items, left_mode, support_tolerance)
right_varies = _opposite_edges_vary(right_items, right_mode, support_tolerance)
if not (left_varies or right_varies):
    continue
if not left_varies and not _has_diverse_text_values(left_items):
    continue
if not right_varies and not _has_diverse_text_values(right_items):
    continue
```

- [ ] **Step 5: 运行新增测试并确认 GREEN**

运行 Step 3 的命令。Expected: `2 passed`。

- [ ] **Step 6: 运行相关回归**

Run:

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_recoverer.py
```

Expected: 全部通过，仅允许既有 PyMuPDF/SWIG 弃用警告。

- [ ] **Step 7: 提交测试与最小实现**

```powershell
git add -- tests/test_wireless_structure_text_runs.py src/hexai_pdf_parser/tables/wireless_structure/text_runs.py
git commit -m "fix(wireless): 阻止等宽多样文本列跨列合并"
```

### Task 2: Page 979 页面级验收与说明

**Files:**
- Modify: `changes.md`
- Output: `output/page_979_fixed_width_alignment_corridor_20260903/`

**Interfaces:**
- Consumes: Task 1 中扩展后的 `_has_alignment_corridor_veto()`。
- Produces: Page 979 结构化 JSON、Markdown、最终 PNG 和中文变更记录。

- [ ] **Step 1: 使用真实模型重跑 Page 979**

通过 `PDFParser.parse(page_indices=[979], output_dir=...)` 读取 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`，模型使用 `src/hexai_pdf_parser/ml/table_detector_model/best.onnx`，输出写入当前 worktree 的 `output/page_979_fixed_width_alignment_corridor_20260903/`。

Expected: 1 张 `wireless_span_recovery` 表，8 个叶子列，模型 bbox 不吸收页眉或页脚。

- [ ] **Step 2: 核对结构不变量**

检查表格数量、source、行列数、bbox、`rowspan/colspan`、空槽位以及每个逻辑槽位恰好由一个 Cell 占用；不得出现 `R2C2 conflict` 或其他 occupancy conflict。

- [ ] **Step 3: 核对最终 PNG**

检查“注册资本”和“主要经营地”列线分立，“持股比例%”父表头只覆盖“直接/间接”两列，正文换行、空值、表格边界及页外文字归属正确。

- [ ] **Step 4: 更新中文 changes.md**

记录根因、等宽侧内容多样性条件、`build_text_runs()` 调用位置、veto-only 语义、不回读 words 约束、测试结果和独立页面输出路径。

- [ ] **Step 5: 最终验证并提交**

运行相关回归、`git diff --check` 和 `git status --short`，确认只包含本任务文件；随后提交：

```powershell
git add -- changes.md
git commit -m "docs: 记录 Page 979 表格恢复验证"
```
