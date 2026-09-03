# Native Span Alignment Corridor Veto Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在中文无线表格的 span 到 atom 阶段，用“稳定成对对齐轨迹 AND 多行共同空白走廊”否决跨列可疑合并，恢复 Page 960 的两张 5 列表格。

**Architecture:** 保留 `_can_join()` 作为唯一正向合并判定，在它返回真后调用一个只读、纯几何的 veto 私有函数。veto 从当前 region 已有的未合并 native spans 中寻找至少两个外部见证行，验证两侧对齐锚点、宽度变化和共同空白走廊；证据不足时不改变现有结果。

**Tech Stack:** Python 3.12、PyMuPDF native spans、pytest、现有 `wireless_structure` 管线。

## Global Constraints

- 对齐关系只有 veto 权，不主动触发任何合并。
- 对齐轨迹与空白走廊必须同时成立。
- 总计至少 3 个视觉行支持，包含当前行时仍须至少 2 个外部见证行。
- bbox 抖动容差为 `max(1.0, min_font_size * 0.12)`。
- 不读取 `page.get_text("words")`，不进入 zebra 或 legacy 重建路径。
- 不覆盖 `text_runs.py` 和测试文件中现有未提交的 wrapped-CJK 修改。

---

### Task 1: 用测试锁定对齐与走廊 veto

**Files:**
- Modify: `tests/test_wireless_structure_text_runs.py`
- Test: `tests/test_wireless_structure_text_runs.py`

**Interfaces:**
- Consumes: `build_text_runs(spans, output_mode="row_interleaved") -> list[dict[str, Any]]`
- Produces: Page 960 形态正例、少于三行反例、无共同走廊反例、真实同行碎片保护测试。

- [ ] **Step 1: 添加 Page 960 风格失败测试**

  构造三行右对齐金额和左对齐中文字段。金额 `x1` 固定、`x0` 随位数变化；中文字段 `x0` 固定、`x1` 随文字长度变化；每对间隔约 `3.2pt`，且现有 `_can_join()` 会允许合并。断言输出保持六个独立 atom：

  ```python
  def test_build_text_runs_vetoes_repeated_right_left_aligned_column_join():
      spans = [
          _atom("1,734,597.85", 298.4, 351.1, 0, (1, 0, 0), y=10),
          _atom("诉讼冻结", 354.3, 396.4, 1, (1, 0, 1), y=10),
          _atom("4,020,986.29", 298.4, 351.1, 2, (2, 0, 0), y=28),
          _atom("商铺按揭保证金", 354.3, 428.0, 3, (2, 0, 1), y=28),
          _atom("2,660,785,019.27", 281.6, 351.1, 4, (3, 0, 0), y=46),
          _atom("借款抵押", 354.3, 396.4, 5, (3, 0, 1), y=46),
      ]
      assert [item["text"] for item in build_text_runs(spans)] == [
          "1,734,597.85", "诉讼冻结",
          "4,020,986.29", "商铺按揭保证金",
          "2,660,785,019.27", "借款抵押",
      ]
  ```

- [ ] **Step 2: 添加拒绝误 veto 的反例**

  增加三个独立测试：只有两行时仍按现有规则合并；三行间隙没有共同交集时仍按现有规则处理；同行中文/数字/CJK 碎片没有成对轨迹时继续组合。

- [ ] **Step 3: 运行新增测试并确认 RED**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py -k 'alignment or corridor or repeated_right_left'
  ```

  Expected: Page 960 风格正例失败，金额与中文仍被拼接；保护反例通过。

### Task 2: 实现纯几何 veto 并接入现有合并入口

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py`
- Test: `tests/test_wireless_structure_text_runs.py`

**Interfaces:**
- Consumes: 当前 group、candidate、当前 region 的视觉行 `Sequence[Sequence[dict[str, Any]]]`。
- Produces: `_has_alignment_corridor_veto(group, candidate, visual_rows) -> bool`，仅返回是否否决。

- [ ] **Step 1: 增加几何辅助函数**

  实现以下私有函数，不访问 page：

  ```python
  def _alignment_anchor(item: dict[str, Any], mode: str) -> float:
      x0, _, x1, _ = item["bbox"]
      return {"left": x0, "center": (x0 + x1) / 2.0, "right": x1}[mode]

  def _alignment_tolerance(items: Sequence[dict[str, Any]]) -> float:
      return max(1.0, min(item["font_size"] for item in items) * 0.12)

  def _alignment_modes(item: dict[str, Any]) -> Sequence[str]:
      if _NUMERIC.fullmatch(str(item.get("text", "")).strip()):
          return ("right",)
      return ("left", "right", "center")

  def _opposite_edges_vary(
      items: Sequence[dict[str, Any]], mode: str, tolerance: float
  ) -> bool:
      x0_spread = max(item["bbox"][0] for item in items) - min(
          item["bbox"][0] for item in items
      )
      x1_spread = max(item["bbox"][2] for item in items) - min(
          item["bbox"][2] for item in items
      )
      if mode == "left":
          return x1_spread > tolerance
      if mode == "right":
          return x0_spread > tolerance
      return x0_spread > tolerance and x1_spread > tolerance

  def _has_alignment_corridor_veto(
      group: Sequence[dict[str, Any]],
      candidate: dict[str, Any],
      visual_rows: Sequence[Sequence[dict[str, Any]]],
  ) -> bool:
      left = {
          "text": _join_text(group),
          "bbox": _union(group),
          "font_size": min(item["font_size"] for item in group),
      }
      tolerance = _alignment_tolerance([left, candidate])
      if candidate["bbox"][0] - left["bbox"][2] <= tolerance:
          return False

      current_flows = {item["flow"] for item in group} | {candidate["flow"]}
      for left_mode in _alignment_modes(left):
          for right_mode in _alignment_modes(candidate):
              if left_mode == right_mode == "center":
                  continue
              support = [(left, candidate)]
              for row in visual_rows:
                  if current_flows.intersection(item["flow"] for item in row):
                      continue
                  matches = []
                  ordered = sorted(row, key=lambda item: item["bbox"][0])
                  for witness_left, witness_right in zip(ordered, ordered[1:]):
                      if witness_right["bbox"][0] - witness_left["bbox"][2] <= tolerance:
                          continue
                      if (
                          abs(
                              _alignment_anchor(witness_left, left_mode)
                              - _alignment_anchor(left, left_mode)
                          )
                          <= tolerance
                          and abs(
                              _alignment_anchor(witness_right, right_mode)
                              - _alignment_anchor(candidate, right_mode)
                          )
                          <= tolerance
                      ):
                          matches.append((witness_left, witness_right))
                  if len(matches) == 1:
                      support.append(matches[0])
              if len(support) < 3:
                  continue
              left_items = [item for item, _ in support]
              right_items = [item for _, item in support]
              if not _opposite_edges_vary(left_items, left_mode, tolerance):
                  continue
              if not _opposite_edges_vary(right_items, right_mode, tolerance):
                  continue
              if (
                  max(_alignment_anchor(item, left_mode) for item in left_items)
                  - min(_alignment_anchor(item, left_mode) for item in left_items)
                  > tolerance
              ):
                  continue
              if (
                  max(_alignment_anchor(item, right_mode) for item in right_items)
                  - min(_alignment_anchor(item, right_mode) for item in right_items)
                  > tolerance
              ):
                  continue
              corridor_x0 = max(item["bbox"][2] for item in left_items)
              corridor_x1 = min(item["bbox"][0] for item in right_items)
              if corridor_x1 - corridor_x0 > tolerance:
                  return True
      return False
  ```

  veto 必须：排除当前行；逐行只接受唯一相邻 span 对；总计至少两个外部见证；验证数字优先右锚、文本优先左锚，居中只能配合稳定边界；验证锚点跨度不超过容差；验证非锚边存在超过容差的宽度变化；最后按所有支持行的 `max(left.x1)` 与 `min(right.x0)` 验证共同走廊宽度大于容差。

- [ ] **Step 2: 在 `_can_join()` 之后接入 veto**

  `build_text_runs()` 继续先调用现有 `_can_join()`。仅当它返回真且 `_has_alignment_corridor_veto()` 返回假时，才把 span 加入当前 group：

  ```python
  can_join = groups and _can_join(
      groups[-1],
      span,
      normal_gap,
      row_spans=sorted_row,
      all_spans=spans,
  )
  if can_join and not _has_alignment_corridor_veto(groups[-1], span, rows):
      groups[-1].append(span)
  else:
      groups.append([span])
  ```

- [ ] **Step 3: 运行定向测试并确认 GREEN**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py
  ```

  Expected: 文件内所有测试通过，包括现有 wrapped-CJK 未提交测试。

### Task 3: 验证结构恢复、回归和真实页面

**Files:**
- Modify: `tests/test_wireless_structure_recoverer.py`（仅在单元测试不足以覆盖 5 列恢复时）
- Modify: `changes.md`
- Output: `output/page_960_alignment_corridor_veto_20260903/`

**Interfaces:**
- Consumes: 更新后的 `build_text_runs()`。
- Produces: 两张无冲突 `wireless_span_recovery` 表及中文交付记录。

- [ ] **Step 1: 运行无线结构相关回归**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_columns.py tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_header_topology.py
  ```

  Expected: 所有相关测试通过；如遇工作区既有失败，记录准确测试名并确认与本次改动关系。

- [ ] **Step 2: 独立重跑 Page 960**

  使用 `test_single.run_single_test()`，输入 `fix/zh_all_table_pages.pdf`、页索引 `960`、新输出目录 `output/page_960_alignment_corridor_veto_20260903/`。不得覆盖现有全量输出。

- [ ] **Step 3: 核对结构化结果**

  验证语言为 `zh`；表格数量为 2；source 均为 `wireless_span_recovery`；上下表均为 5 列；逐槽位 occupancy 唯一；金额与受限类型文本位于不同列。

- [ ] **Step 4: 核对最终 PNG**

  检查 `output/page_960_alignment_corridor_veto_20260903/tables/page-960.png`：上下表独立，表格框不吸收标题、`续：` 或说明正文，5 列边界连续，换行内容不跨列。

- [ ] **Step 5: 更新中文变更记录并检查差异**

  在 `changes.md` 记录根因、组合 veto 条件、`build_text_runs()` 调用位置、不回读 words、测试结果和页面输出绝对路径。运行：

  ```powershell
  git diff --check
  git diff -- src/hexai_pdf_parser/tables/wireless_structure/text_runs.py tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_recoverer.py changes.md
  ```

  Expected: 无空白错误；每一处改动均对应本设计。由于目标文件已有用户未提交修改，未经单独确认不得把整文件作为本次提交提交。
