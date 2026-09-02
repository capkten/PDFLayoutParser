# 叶子表头单次支持列恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 允许中文/混合无线表格依据叶子表头几何恢复正文全空的独立列，并让页索引 923 输出 `6x5` 表格。

**Architecture:** 保留普通列带的跨行支持门槛，在 `refine_leaf_bands()` 之后增加 `rescue_header_only_leaf_bands()`。该函数只在一个表头层完整覆盖全部稳定叶子列时，恢复与任何列带不重叠且具有明确字段间距的同层 atom；随后沿用现有列标注、冲突检查和空槽物化。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、现有 native-span wireless structure pipeline。

## Global Constraints

- `zh`/`mixed` 页面只使用 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`。
- 不按“备注”“金额”“比例”等业务文字硬编码。
- 只放宽叶子表头层，父表头、正文孤立说明和同字段近邻片段不得形成新列。
- 空正文槽位逐格物化为 `text=""`、`rowspan=1`、`colspan=1`。
- 所有跨度和补列结果继续执行 occupancy conflict 检查。
- 保留工作区现有无关改动。

---

### Task 1: 叶子表头几何补列

**Files:**
- Modify: `tests/test_wireless_structure_header_topology.py`
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py`

**Interfaces:**
- Consumes: `atoms: Sequence[dict[str, Any]]`、`bands: Sequence[dict[str, Any]]`、`header_cutoff: float | None`
- Produces: `rescue_header_only_leaf_bands(atoms, bands, header_cutoff) -> list[dict[str, Any]]`

- [ ] **Step 1: 增加最右端和中间空正文列失败测试**

在 `tests/test_wireless_structure_header_topology.py` 中构造同层完整覆盖稳定列带的叶子表头，并断言不重叠的中间/尾部 atom 被补为 `kind="header_only_leaf"`，列带按 x 重新编号。

- [ ] **Step 2: 增加拒绝父表头与近邻片段测试**

父表头所在层没有完整覆盖全部稳定列带时保持原列数；候选与相邻表头间距小于 `max(8.0, line_height * 1.25)` 时保持原列数。

- [ ] **Step 3: 运行聚焦测试并确认 RED**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& '.\.venv\Scripts\pytest.exe' -q tests/test_wireless_structure_header_topology.py -k 'header_only_leaf'
```

Expected: 因 `rescue_header_only_leaf_bands` 尚不存在而失败。

- [ ] **Step 4: 实现最小几何恢复函数**

在 `header_topology.py` 中：复制并排序列带；按 `_levels()` 聚类 cutoff 以内的 atom；要求候选层每条稳定列带都恰有叶子 atom 覆盖且没有 atom 跨多带；对不重叠 atom 检查左右最近同层字段间距；排除 `_is_structural_header_atom()`；新增列带后重新编号。

- [ ] **Step 5: 运行聚焦测试并确认 GREEN**

执行 Step 3 命令，Expected: 新增正反例全部通过。

### Task 2: 接入 recoverer 并恢复 page 923

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`
- Modify: `tests/test_wireless_structure_recoverer.py`

**Interfaces:**
- Consumes: Task 1 的 `rescue_header_only_leaf_bands()`
- Produces: `recover_cells_from_region()` 在尾部仅表头列存在时输出完整矩形网格

- [ ] **Step 1: 增加 page 923 形态的 recoverer 失败测试**

用 `NativeSpan` 构造五列表头、五行正文且第五列正文全空的区域，断言结果为 `6x5`，并断言第 2 至第 6 行的第 5 列均为独立空 Cell。

- [ ] **Step 2: 运行集成测试并确认 RED**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& '.\.venv\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py -k 'header_only_leaf'
```

Expected: 当前四列网格发生表头槽位冲突，返回 `(0, 0, [])`。

- [ ] **Step 3: 在列标注前接入补列函数**

在 `recover_cells_from_region()` 的 `rescue_header_only_note_bands()` 之后调用 `rescue_header_only_leaf_bands()`；不改变后续 grid、logical grid、span 和空槽物化顺序。

- [ ] **Step 4: 运行集成与相关结构测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& '.\.venv\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_columns.py
```

Expected: 全部通过。

### Task 3: 页面验证与变更记录

**Files:**
- Modify: `changes.md`
- Create output: `output/fix_page_923_header_only_leaf_20260902/`

**Interfaces:**
- Consumes: 完成后的 `PDFParser.parse(page_indices=[923])`
- Produces: page 923 JSON、Markdown 和表格 PNG

- [ ] **Step 1: 在独立目录重跑页索引 923**

使用 `fix/zh_all_table_pages.pdf` 和 `src/hexai_pdf_parser/ml/table_detector_model/best.onnx`，开启页面可视化并输出到 `output/fix_page_923_header_only_leaf_20260902/`。

- [ ] **Step 2: 核对结构化结果**

断言页面语言为 `zh`，表格数量为 1，source 为 `wireless_span_recovery`，目标结构为 `6x5`，第五列正文五个空槽独立存在，所有逻辑槽位占用恰好一次。

- [ ] **Step 3: 核对最终 PNG**

检查表格 bbox 不吸收上下正文，五列边界与表头对应，首个数据行两行文字仍在同一 Cell，三条原始横线和推断网格关系合理。

- [ ] **Step 4: 更新中文 changes.md**

记录根因、几何判定、recoverer 调用位置、不回读 words 的约束、测试结果和页面输出绝对路径。

- [ ] **Step 5: 最终验证**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& '.\.venv\Scripts\pytest.exe' -q tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_columns.py tests/test_wireless_table_recovery.py tests/test_table_extractor.py
git diff --check
```

Expected: 相关测试全部通过，`git diff --check` 无输出。
