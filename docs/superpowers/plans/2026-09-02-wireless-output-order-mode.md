# 无线表格输出顺序模式实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 识别无线表格区域的 native 输出顺序，并让按列连续输出的页面使用单文本块几何对齐，避免跨 native block 的顺序误合并。

**Architecture:** `collect_native_spans()` 保存 rawdict 的 block/line/span 来源，`text_runs.py` 根据 native 顺序与 bbox 轨迹判定 `row_interleaved` 或 `columnar`。两种模式共享同一行文本组合、列带、网格和逻辑结构恢复；只有 atom 和 Cell 的跨 block 跨行合并根据模式切换。591 页使用 `columnar`，同一 native block 的真实多行在 atom 阶段合并，独立 block 保持为独立文本块。

**Tech Stack:** Python 3.12、PyMuPDF/rawdict、pytest、项目现有 native-span wireless structure pipeline。

## Global Constraints

- 中文/混合页面继续只走 native span，不回读 `page.get_text("words")`，不回退 legacy 或 zebra 路径。
- Span 到 atom 阶段完成同一字段的文本组合；进入 atom、列带、物理 Cell 和逻辑 Cell 后不得再次读取表格 words。
- 不得仅因 atom 位于同一候选槽位就合并独立字段。
- `rowspan/colspan`、空槽位和 occupancy 每次跨度调整后都要重新校验。
- 新结构恢复只消费 native span、atom、列带、物理 Cell 和逻辑 Cell。
- 修改前先写最小失败测试并确认失败，再写生产代码。
- 页面级验证写入新的独立输出目录，并同时核对结构化结果和 PNG。
- 中文说明文档和 `changes.md` 记录根因、判定条件、调用位置、不回读 words 约束、测试结果和输出路径。
- 保留工作区中与本任务无关的已有修改，不清理、不覆盖、不回退。

---

### Task 1: 保存 native 来源并增加输出模式判定

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_table_recovery.py:44-54,100-141`
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/span_chain.py:24-52,93-112`
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py:1-18,278-319`
- Create: `tests/test_wireless_output_order.py`

**Interfaces:**
- `NativeSpan.source_position: tuple[int, int, int] | None` 保存 `(block_index, line_index, span_index)`；旧 positional 构造保持可用。
- `infer_output_order_mode(spans: Sequence[dict[str, Any]]) -> Literal["row_interleaved", "columnar"]` 根据 normalized native span 顺序和 bbox 返回区域模式。
- `build_text_runs(spans, *, output_mode: str = "row_interleaved")` 保留默认行为，后续任务使用模式参数。

- [ ] **Step 1: Write the failing test**

在 `tests/test_wireless_output_order.py` 写入最小测试数据和以下测试：

```python
from hexai_pdf_parser.tables.wireless_structure.text_runs import infer_output_order_mode


def _span(text, x0, x1, y, flow, block, line=0):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 10],
        "flow": flow,
        "source_position": [block, line, 0],
        "source_position_known": True,
        "font_size": 10,
    }


def test_infer_output_order_mode_detects_columnar_left_column_stream():
    spans = [
        _span("左一", 10, 50, 10, 1, 1),
        _span("左二", 10, 50, 24, 2, 2),
        _span("左三", 10, 50, 38, 3, 3),
        _span("右一", 120, 160, 10, 4, 4),
        _span("右二", 120, 160, 24, 5, 5),
        _span("右三", 120, 160, 38, 6, 6),
    ]

    assert infer_output_order_mode(spans) == "columnar"


def test_infer_output_order_mode_keeps_interleaved_rows():
    spans = [
        _span("左一", 10, 50, 10, 1, 1),
        _span("右一", 120, 160, 10, 2, 1),
        _span("左二", 10, 50, 24, 3, 2),
        _span("右二", 120, 160, 24, 4, 2),
    ]

    assert infer_output_order_mode(spans) == "row_interleaved"


def test_collect_native_spans_preserves_block_line_span_position():
    from hexai_pdf_parser.tables.wireless_table_recovery import collect_native_spans

    class Page:
        def get_text(self, kind, flags):
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {"spans": [{"text": "", "chars": [{"c": "甲", "bbox": [0, 0, 5, 10]},], "bbox": [0, 0, 5, 10], "font": "SimSun", "size": 10}]},
                            {"spans": [{"text": "", "chars": [{"c": "乙", "bbox": [0, 12, 5, 22]},], "bbox": [0, 12, 5, 22], "font": "SimSun", "size": 10}]},
                        ],
                    }
                ]
            }

    spans = collect_native_spans(Page())

    assert [span.source_position for span in spans] == [(0, 0, 0), (0, 1, 0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py
```

Expected: FAIL because `infer_output_order_mode` is not defined and `NativeSpan` does not yet expose `source_position`.

- [ ] **Step 3: Write minimal implementation**

Add the optional field after `NativeSpan.characters` so existing positional constructors remain valid:

```python
source_position: Tuple[int, int, int] | None = None
```

In `collect_native_spans()`, enumerate blocks, lines, and spans and pass:

```python
source_position=(block_index, line_index, span_index)
```

In `_native_dict()` use the real position when present and expose a reliability flag:

```python
source_position = getattr(span, "source_position", None)
source_position_known = source_position is not None
if source_position is None:
    source_position = (0, 0, span.order)
return {
    # existing fields
    "source_position": list(source_position),
    "source_position_known": source_position_known,
}
```

Implement `infer_output_order_mode()` in `text_runs.py` using only normalized spans:

```python
def infer_output_order_mode(spans: Sequence[dict[str, Any]]) -> Literal["row_interleaved", "columnar"]:
    filtered = _filter_separator_spans(spans)
    if len(filtered) < 4:
        return "row_interleaved"
    ordered = sorted(filtered, key=lambda item: item["flow"])
    sizes = [float(item.get("font_size", 10.0)) for item in ordered if item.get("font_size")]
    tolerance = max(2.4, (statistics.median(sizes) if sizes else 10.0) * 0.38)
    widths = [item["bbox"][2] - item["bbox"][0] for item in ordered]
    horizontal_gap = max(8.0, (statistics.median(widths) if widths else 10.0) * 0.35)

    separated_tracks = 0
    track_ends = []
    for item in sorted(ordered, key=lambda value: value["bbox"][0]):
        if track_ends and item["bbox"][0] <= track_ends[-1] + horizontal_gap:
            track_ends[-1] = max(track_ends[-1], item["bbox"][2])
        else:
            track_ends.append(item["bbox"][2])
            separated_tracks += 1

    same_row_steps = 0
    vertical_steps = 0
    vertical_chain = 0
    longest_vertical_chain = 0
    for previous, current in zip(ordered, ordered[1:]):
        previous_center = _center_y(previous)
        current_center = _center_y(current)
        if abs(current_center - previous_center) <= tolerance:
            same_row_steps += 1
            vertical_chain = 0
            continue
        overlap = _horizontal_overlap(previous["bbox"], current["bbox"])
        minimum_width = min(
            previous["bbox"][2] - previous["bbox"][0],
            current["bbox"][2] - current["bbox"][0],
        )
        if current_center > previous_center and overlap >= max(2.0, minimum_width * 0.45):
            vertical_steps += 1
            vertical_chain += 1
            longest_vertical_chain = max(longest_vertical_chain, vertical_chain)
        else:
            vertical_chain = 0

    if (
        separated_tracks >= 2
        and longest_vertical_chain >= 3
        and vertical_steps >= max(3, same_row_steps * 2 + 1)
    ):
        return "columnar"
    return "row_interleaved"
```

在 `text_runs.py` 顶部导入 `Literal` 和 `statistics`。保留现有 `build_text_runs()` 默认行为，直到 Task 2 增加模式分支。

- [ ] **Step 4: Run test to verify it passes**

Run the same command from Step 2. Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/hexai_pdf_parser/tables/wireless_table_recovery.py src/hexai_pdf_parser/tables/wireless_structure/span_chain.py src/hexai_pdf_parser/tables/wireless_structure/text_runs.py tests/test_wireless_output_order.py
git commit -m "fix: 保留无线表格原生输出顺序证据"
```

### Task 2: 按模式构造 atom，隔离跨 block 顺序合并

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py:240-319`
- Modify: `tests/test_wireless_output_order.py`

**Interfaces:**
- `build_text_runs(..., output_mode="row_interleaved")` 在 `columnar` 下跳过 `_merge_wrapped_field_runs()`。
- `columnar` 下新增的同 block 合并标记为 `merge_kind="same_native_block_lines"`。

- [ ] **Step 1: Write the failing test**

追加以下测试，验证同一 block 可合并，不同 block 不合并：

```python
from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs


def _atom(text, x0, x1, y, flow, block, line=0):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 10],
        "flow": flow,
        "source_position": [block, line, 0],
        "source_position_known": True,
        "font": "SimSun",
        "font_size": 10,
        "bold": False,
        "span_ref": f"S{flow}",
        "char_boxes": [],
    }


def test_columnar_mode_keeps_independent_left_blocks_separate():
    atoms = [
        _atom("左一", 10, 50, 10, 1, 1),
        _atom("左二", 10, 50, 24, 2, 2),
        _atom("左三", 10, 50, 38, 3, 3),
        _atom("右侧", 120, 160, 24, 4, 4),
    ]

    result = build_text_runs(atoms, output_mode="columnar")

    assert [item["text"] for item in result] == ["左一", "左二", "左三", "右侧"]


def test_columnar_mode_merges_only_adjacent_lines_from_one_native_block():
    atoms = [
        _atom("第一行", 10, 50, 10, 1, 1, line=0),
        _atom("第二行", 10, 50, 24, 2, 1, line=1),
        _atom("右侧", 120, 160, 17, 3, 2),
    ]

    result = build_text_runs(atoms, output_mode="columnar")

    assert [item["text"] for item in result] == ["第一行\n第二行", "右侧"]
    assert result[0]["merge_kind"] == "same_native_block_lines"
    assert result[0]["source_blocks"] == [1]
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py
```

Expected: FAIL because `build_text_runs()` rejects `output_mode` and has no same-block branch.

- [ ] **Step 3: Write minimal implementation**

Add `source_position_known` to each atom as the conjunction of its source spans. Extract the common metadata-preserving merge into:

```python
def _merge_run_chain(chain, joiner, merge_kind):
    merged = dict(chain[0])
    merged.update(
        text=joiner.join(item["text"] for item in chain),
        bbox=_union(chain),
        span_refs=[span for item in chain for span in item["span_refs"]],
        flow_start=chain[0]["flow_start"],
        flow_end=chain[-1]["flow_end"],
        char_boxes=[char for item in chain for char in item.get("char_boxes", [])],
        source_blocks=sorted({block for item in chain for block in item["source_blocks"]}),
        source_line_start=min(item["source_line_start"] for item in chain),
        source_line_end=max(item["source_line_end"] for item in chain),
        source_position_known=all(item.get("source_position_known", True) for item in chain),
        merge_kind=merge_kind,
    )
    return merged
```

Use that helper from `_merge_wrapped_field_runs()`. Add the columnar-only predicate and merge:

```python
def _same_native_block_line_pair(left, candidate):
    if not left.get("source_position_known", False) or not candidate.get("source_position_known", False):
        return False
    if left["source_blocks"] != candidate["source_blocks"] or len(left["source_blocks"]) != 1:
        return False
    if candidate["source_line_start"] != left["source_line_end"] + 1:
        return False
    if candidate["bbox"][1] < left["bbox"][3] or _center_y(candidate) <= _center_y(left):
        return False
    if left.get("bold") != candidate.get("bold"):
        return False
    if abs(left.get("font_size", 10.0) - candidate.get("font_size", 10.0)) > 1.0:
        return False
    if _NUMERIC.fullmatch(left["text"].strip()) or _NUMERIC.fullmatch(candidate["text"].strip()):
        return False
    if _is_placeholder(left) or _is_placeholder(candidate):
        return False
    minimum_width = min(
        left["bbox"][2] - left["bbox"][0],
        candidate["bbox"][2] - candidate["bbox"][0],
    )
    if _horizontal_overlap(left["bbox"], candidate["bbox"]) < minimum_width * 0.45:
        return False
    return candidate["bbox"][1] - left["bbox"][3] <= max(
        6.0, min(left["font_size"], candidate["font_size"])
    )


def _merge_same_native_block_lines(runs):
    ordered = sorted((dict(item) for item in runs), key=lambda item: item["flow_start"])
    result = []
    index = 0
    while index < len(ordered):
        chain = [ordered[index]]
        cursor = index + 1
        while cursor < len(ordered) and _same_native_block_line_pair(chain[-1], ordered[cursor]):
            chain.append(ordered[cursor])
            cursor += 1
        result.append(
            _merge_run_chain(chain, "\n", "same_native_block_lines")
            if len(chain) > 1
            else chain[0]
        )
        index = cursor
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))
```

Change the public function to:

```python
def build_text_runs(
    spans: Sequence[dict[str, Any]], *, output_mode: str = "row_interleaved"
) -> list[dict[str, Any]]:
```

After same-visual-line groups are built, return `_merge_same_native_block_lines(result)` for `columnar`; otherwise return `_merge_wrapped_field_runs(result)`.

- [ ] **Step 4: Run test to verify it passes**

Run the new file and the existing atom tests:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py tests/test_wireless_structure_text_runs.py tests/test_wrapped_field_font_and_witness.py
```

Expected: all tests PASS. Existing row-interleaved wrapped-field tests must still observe `merge_kind="wrapped_field"`.

- [ ] **Step 5: Commit**

```powershell
git add src/hexai_pdf_parser/tables/wireless_structure/text_runs.py tests/test_wireless_output_order.py
git commit -m "fix: 按 native 输出模式隔离文本块合并"
```

### Task 3: 把模式传入 Cell 合并和 native-span 调用方

**Files:**
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py:104-157`
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py:24-130`
- Modify: `src/hexai_pdf_parser/tables/wireless_structure/hybrid_body.py:17-163`
- Modify: `tests/test_wireless_output_order.py`

**Interfaces:**
- `merge_multiline_cells(cells, header_cutoff, *, output_mode="row_interleaved")`。
- `recover_cells_from_region()` 和 `recover_hybrid_body_cells()` 对同一 native 区域使用同一个 `output_mode`，并把它传给 atom 与 Cell 阶段。

- [ ] **Step 1: Write the failing test**

追加 Cell 合并边界测试：

```python
from hexai_pdf_parser.tables.wireless_structure.merged_cells import merge_multiline_cells


def _cell(text, flow, row, block, line, x0=10, x1=50, y0=10):
    return {
        "candidate_label": f"T{flow}",
        "cell_id": f"T{flow}",
        "text": text,
        "bbox": [x0, y0, x1, y0 + 10],
        "flow_start": flow,
        "flow_end": flow,
        "span_refs": [f"S{flow}"],
        "source_blocks": [block],
        "source_line_start": line,
        "source_line_end": line,
        "source_position_known": True,
        "font_size": 10,
        "bold": False,
        "script": "cjk",
        "row_start": row,
        "row_end": row,
        "col_start": 1,
        "col_end": 1,
        "rowspan": 1,
        "colspan": 1,
    }


def test_columnar_mode_does_not_merge_adjacent_cells_from_different_blocks():
    result = merge_multiline_cells(
        [
            _cell("项目一", 1, 1, block=1, line=0, y0=10),
            _cell("项目二", 2, 2, block=2, line=0, y0=24),
        ],
        header_cutoff=None,
        output_mode="columnar",
    )

    assert [item["text"] for item in result] == ["项目一", "项目二"]


def test_columnar_mode_can_merge_adjacent_lines_from_one_native_block():
    result = merge_multiline_cells(
        [
            _cell("第一行", 1, 1, block=1, line=0, y0=10),
            _cell("第二行", 2, 2, block=1, line=1, y0=24),
        ],
        header_cutoff=None,
        output_mode="columnar",
    )

    assert [item["text"] for item in result] == ["第一行\n第二行"]
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py
```

Expected: FAIL because `merge_multiline_cells()` does not accept `output_mode` and currently merges both pairs.

- [ ] **Step 3: Write minimal implementation**

Add a source guard:

```python
def _same_native_block(left, right):
    return (
        left.get("source_position_known", False)
        and right.get("source_position_known", False)
        and left.get("source_blocks") == right.get("source_blocks")
        and len(left.get("source_blocks", [])) == 1
    )
```

Extend `_can_merge_multiline()` with `output_mode` and reject cross-block pairs when it is `columnar`:

```python
def _can_merge_multiline(previous, candidate, row_columns, output_mode):
    if output_mode == "columnar" and not _same_native_block(previous, candidate):
        return False
    # existing same-column, row, native-flow, script, value, style, overlap and gap checks
```

Extend `merge_multiline_cells()` with the keyword-only default and pass it through the loop:

```python
def merge_multiline_cells(
    cells, header_cutoff, *, output_mode="row_interleaved"
):
    # existing setup
    while pending:
        current = pending.pop(0)
        current["merged_from"] = list(current.get("merged_from", [current["candidate_label"]]))
        while pending and _can_merge_multiline(current, pending[0], row_columns, output_mode):
            candidate = pending.pop(0)
            current = _merge_pair(current, candidate, "\n", "multiline_cell")
            current["row_end"] = candidate["row_end"]
            current["rowspan"] = current["row_end"] - current["row_start"] + 1
        result.append(current)
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))
```

In both native-span callers, calculate the mode immediately after `region_spans()`:

```python
output_mode = infer_output_order_mode(spans)
atoms = build_text_runs(spans, output_mode=output_mode)
```

Pass the same mode after `merge_same_slot_fragments()`:

```python
cells = merge_multiline_cells(
    cells, header_cutoff, output_mode=output_mode
)
```

Apply this in `recoverer.py` and `hybrid_body.py`; leave the default unchanged for any other direct caller.

- [ ] **Step 4: Run test to verify it passes**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_recoverer.py tests/test_hybrid_body_recovery.py
```

Expected: all tests PASS, including the existing row-interleaved multiline tests.

- [ ] **Step 5: Commit**

```powershell
git add src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py src/hexai_pdf_parser/tables/wireless_structure/recoverer.py src/hexai_pdf_parser/tables/wireless_structure/hybrid_body.py tests/test_wireless_output_order.py
git commit -m "fix: 传递无线表格输出模式到单元格合并"
```

### Task 4: 相关回归、591 页验证和交付记录

**Files:**
- Modify: `changes.md`
- Create: `output/fix_full_rerun_current_20260902_page591_output_order/`（页面级验证产物，不提交代码仓库）
- Test: `tests/test_wireless_output_order.py`、相关无线结构测试和页面级输出

**Interfaces:**
- 页面输入：`fix/zh_all_table_pages.pdf`，页索引 `591`。
- 页面输出：`output/fix_full_rerun_current_20260902_page591_output_order/`。
- 页面目标：`wireless_span_recovery` 表格不再把左列独立项目串为一个 Cell，右侧文本不漏失，空槽位与 occupancy 完整。

- [ ] **Step 1: Run the focused regression suite**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py tests/test_wireless_structure_text_runs.py tests/test_wrapped_field_font_and_witness.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_recoverer.py tests/test_hybrid_body_recovery.py
```

Expected: all focused tests PASS with no new warnings.

- [ ] **Step 2: Run the single-page native-span recovery**

Use the project parser entry point with `page_indices=[591]`, source PDF
`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`, and output directory
`D:\codes\PDFLayoutParser\output\fix_full_rerun_current_20260902_page591_output_order`.
Keep visualization enabled. Do not use `page.get_text("words")` in the Chinese/mixed recovery path.

- [ ] **Step 3: Inspect the structured output and PNG**

Check the generated `pages/page-591.json` and `tables/page-591.png`:

```text
source = wireless_span_recovery
left-column independent records remain separate
right-side headers and values are present
same-block wrapped text is one logical Cell
all logical slots have exactly one occupant
no occupancy conflict, table boundary expansion, or adjacent-table merge
```

- [ ] **Step 4: Run the broader related suite**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_table_extractor.py tests/test_rule_first_table_detection.py tests/test_financial_header_normalizer.py
```

Record any pre-existing environment or fixture failure separately from this change.

- [ ] **Step 5: Update changes.md**

Add a Chinese entry containing:

```text
日期：2026-09-02
问题：591 页左列连续 native 输出触发跨 block 顺序合并，造成结构串行化和文本漏失。
根因：原流程只用 flow 连续与右侧 witness，且未保留 native block/line 来源。
判定：区域级几何轨迹识别 columnar 与 row_interleaved。
修复：columnar 只合并同一 native block 的真实换行，列带/网格/空槽位/occupancy 继续复用。
约束：中文/混合路径只消费 native span，不回读 page words。
验证：列出测试结果、591 页结构化结果和 PNG 绝对路径。
```

- [ ] **Step 6: Verify final diff and status**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only this task's tracked files are staged or committed, and unrelated existing changes remain untouched.

- [ ] **Step 7: Commit the delivery record**

```powershell
git add changes.md
git commit -m "docs: 记录无线输出顺序修复验证"
```
