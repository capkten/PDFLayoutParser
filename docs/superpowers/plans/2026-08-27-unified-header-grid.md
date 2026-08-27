# Unified Header Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the span-table demo emit and draw one logical grid that includes its two header rows and all body rows.

**Architecture:** Keep `header_group` and `leaf_column` as column semantics beneath the table root. Add a `grid` child containing header and body `row` nodes; header group cells use `colspan`, leaf/stub cells occupy the next header row, and body rows retain their original order after those two rows.

**Tech Stack:** Python 3.12, PyMuPDF, pytest.

## Global Constraints

- Modify only the demo, its tests, its status document, and its design/plan documentation.
- Preserve native span order and retain separator text; do not modify the production extractor.
- The page 184 table region is supplied by the caller; do not redetect or resplit it.

---

### Task 1: Define header cells in the unified grid

**Files:**
- Modify: `tests/test_span_table_tree_demo.py`
- Modify: `scripts/span_table_tree_demo.py`

**Interfaces:**
- Consumes: `build_table_tree(nodes, table_bbox) -> TreeNode`.
- Produces: `root.children` containing semantic leaf/group nodes plus one `TreeNode(kind="grid")` with `row` and `cell` descendants.

- [ ] **Step 1: Write the failing test**

```python
grid = next(child for child in root.children if child.kind == "grid")
header_rows = grid.children[:2]
assert [cell.text for cell in header_rows[0].children] == ["period end", "period start"]
assert [(cell.col_index, cell.colspan) for cell in header_rows[0].children] == [(1, 3), (4, 3)]
assert [cell.col_index for cell in header_rows[1].children] == list(range(7))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_span_table_tree_demo.py::test_table_tree_includes_header_cells_in_logical_grid`

Expected: FAIL because the current tree has only a `body` child and has no `grid` header rows.

- [ ] **Step 3: Write minimal implementation**

```python
grid = TreeNode("grid", bbox=table_bbox)
grid.children.extend([group_header_row, leaf_header_row])
grid.children.extend(body_rows)
root.children.append(grid)
root._grid = grid
```

Build group header cells from the native group-header row when available, assign their leaf-range `col_index` and `colspan`, then assign the stub and every leaf column to the second header row. Offset existing body row indexes by two and retain their existing node order.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_span_table_tree_demo.py::test_table_tree_includes_header_cells_in_logical_grid`

Expected: PASS.

### Task 2: Draw and serialize the full grid

**Files:**
- Modify: `scripts/span_table_tree_demo.py`
- Modify: `tests/test_span_table_tree_demo.py`
- Modify: `tests/test_span_table_tree_demo_integration.py`

**Interfaces:**
- Consumes: `TreeNode(kind="grid")` created by Task 1.
- Produces: `flatten_tree_cells(root)` returns all grid cells; `_draw_logical_grid` bounds and labels all header/body rows.

- [ ] **Step 1: Write the failing test**

```python
cells = flatten_tree_cells(root)
assert any(cell.text == "period end" and cell.colspan == 3 for cell in cells)
assert max(cell.row_index for cell in cells if cell.row_index is not None) >= 3
```

Add an integration assertion that the serialized page-184 tree contains a `grid` child whose first row has two `colspan == 3` cells.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_span_table_tree_demo.py tests/test_span_table_tree_demo_integration.py`

Expected: FAIL because flattening/drawing still only reads the `body` node.

- [ ] **Step 3: Write minimal implementation**

```python
def flatten_tree_cells(root):
    grid = next(node for node in root.children if node.kind == "grid")
    return [cell for row in grid.children for cell in row.children]
```

Make `_grid_boundaries` and `_draw_logical_grid` operate on the `grid` child, including header rows. Keep `_apply_ordered_rowspans` restricted to body rows so headers cannot become rowspan candidates.

- [ ] **Step 4: Run tests and the page-184 demo**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_span_table_tree_demo.py tests/test_span_table_tree_demo_integration.py
python scripts/span_table_tree_demo.py --pdf fix/zh_all_table_pages.pdf --page 184 --bbox 90 515 498 685 --output tmp/span_table_tree_page_184_header_grid
python -m json.tool tmp/span_table_tree_page_184_header_grid/tree.json > $null
git diff --check
```

Expected: all demo tests pass; JSON parses; PNG exists and its green grid covers both header rows and body rows.

### Task 3: Record the verified behavior

**Files:**
- Modify: `docs/span-table-document-tree-demo-status.md`
- Modify: `changes.md`

**Interfaces:**
- Consumes: page-184 test and rendered-output results from Task 2.
- Produces: handoff documentation that distinguishes completed header-grid work from the remaining phrase-aggregation and general header-inference work.

- [ ] **Step 1: Update the handoff status**

Record that header cells are now inside the logical grid, list the two group `colspan=3` cells, and retain phrase aggregation and general grouping as limitations.

- [ ] **Step 2: Update `changes.md`**

Add the date, the header-grid issue, the minimal demo-only fix, and the verification command/result.

- [ ] **Step 3: Verify documentation diff**

Run: `git diff --check`

Expected: no whitespace errors.
