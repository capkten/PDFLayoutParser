# 页 591 跨行前置表头下的叶子列恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不放宽普通列带和冲突保护的前提下，将页索引 591 的中文无线表格恢复为 `29x11`。

**Architecture:** 扩展 `rescue_header_only_leaf_bands()`：保留既有完整覆盖分支，新增“上一层唯一覆盖前置稳定列、最低层完整覆盖连续稳定后缀”的事务性候选分支。后续列标注、物理/逻辑网格、跨度恢复和空槽物化顺序不变。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、现有 native-span wireless structure pipeline。

## Global Constraints

- `zh`/`mixed` 无线恢复不回读 `page.get_text("words")`，不进入 zebra 或 legacy 路径。
- 不使用页码或业务文字特判。
- 候选必须整组通过，最终 occupancy conflict 检查保持不变。
- 空槽位继续逐格物化为独立 `text=""`、`1x1` Cell。
- 保留工作区现有无关改动。

---

### Task 1: 用最小测试锁定跨行前置表头拓扑

**Files:**
- Modify: `tests/test_wireless_structure_header_topology.py`

**Interfaces:**
- Consumes: `rescue_header_only_leaf_bands(atoms, bands, header_cutoff)`
- Produces: 跨行前置结构列的正例和中间缺列/上层证据不足反例

- [ ] **Step 1: 写 page-591 形态正例**

构造上一层“项目”覆盖最左稳定列、最低层覆盖连续稳定后缀并含两个未匹配叶子标题的数据，断言两个候选按 x 顺序补为 `header_only_leaf`。

- [ ] **Step 2: 写两个拒绝反例**

分别构造最低层遗漏中间稳定列、上一层没有唯一覆盖缺席前置列，断言列带保持不变。

- [ ] **Step 3: 运行新增测试确认 RED**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_header_topology.py -k 'rowspan_prefix'
```

Expected: 正例因当前完整覆盖条件拒绝补列而失败；两个反例通过。

### Task 2: 实现最小拓扑扩展

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py`

**Interfaces:**
- Consumes: 当前层覆盖集合、稳定列顺序和上一表头层 atom
- Produces: 符合前置跨行结构证据时的整组 `header_only_leaf` 列带

- [ ] **Step 1: 识别连续稳定后缀与前置覆盖证据**

仅当最低候选层覆盖至少两个稳定列且构成连续后缀，并且上层 atom 对每个缺席前置稳定列提供唯一覆盖时，将该层加入既有 eligible levels。

- [ ] **Step 2: 复用既有候选过滤和整组提交**

继续使用 `_is_structural_header_atom()`、水平重叠和字段间距检查；任一候选失败时返回输入列带，不允许部分补列。

- [ ] **Step 3: 运行聚焦测试确认 GREEN**

执行 Task 1 的命令，Expected: 新增正反例全部通过。

### Task 3: 回归与真实页面验证

**Files:**
- Modify: `changes.md`
- Create output: `output/page_591_rowspan_prefix_leaf_recovery_20260903/`

**Interfaces:**
- Consumes: 完成后的恢复器和 `fix/zh_all_table_pages.pdf` 页索引 591
- Produces: JSON、Markdown、最终 PNG 和中文变更记录

- [ ] **Step 1: 运行相关结构测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_merges.py tests/test_wireless_output_order.py
```

- [ ] **Step 2: 独立重跑 page 591**

调用 `test_single.run_single_test()`，输入 `fix/zh_all_table_pages.pdf`、`page_index=591`，输出到 `output/page_591_rowspan_prefix_leaf_recovery_20260903/`。

- [ ] **Step 3: 核对结构和 PNG**

确认唯一表格为 `wireless_span_recovery 29x11`，319 个逻辑槽位恰好占用一次，表格 bbox、表头组和底部余额行合理，未吸收标题、签字栏或页码。

- [ ] **Step 4: 更新 changes.md 并最终检查**

记录根因、判定条件、调用位置、不回读 words、测试结果和输出路径；运行 `git diff --check` 并检查仅包含任务相关改动。

## 计划自审

- 规格中的正例、两类反例、公共路径约束、页面结构与视觉验收均有对应步骤。
- 没有待定接口或未定义实现步骤。
- 修改限制在已有叶子表头救援函数、对应测试和中文记录。
