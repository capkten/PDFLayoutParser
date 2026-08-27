# Span Table Document-Tree Recovery Demo: Status and Handoff

Updated: 2026-08-27

This document records the current wireless-table structure-recovery demo. Read it before continuing work in a new conversation.

## 1. Goal and scope

The demo validates a document-tree approach for wireless PDF tables:

- The table region is supplied by the model. The demo does not redetect or resplit it.
- Native PDF content-stream order, stored as NativeSpan.order, is the primary sequence evidence.
- A document tree expresses nested headers, leaf columns, rowspan, and colspan.
- Coordinates provide geometric constraints, row/column assignment, and visualization only.
- Separator lines are retained as text nodes; they are not removed from extraction.
- The demo outputs JSON and PNG only.
- The production extractor is not modified by this experiment.

## 2. Input and tested region

Input PDF:

```text
fix/zh_all_table_pages.pdf
```

Test page:

```text
page_index = 184
```

The index is zero-based.

Tested aging-analysis table region:

```text
BBox(90, 515, 498, 685)
```

The page visually contains three table regions, but this demo currently runs only the aging-analysis region. The region is already supplied by the model.

Run:

```powershell
python scripts/span_table_tree_demo.py `
  --pdf fix/zh_all_table_pages.pdf `
  --page 184 `
  --bbox 90 515 498 685 `
  --output tmp/span_table_tree_page_184
```

Outputs:

```text
tmp/span_table_tree_page_184/tree.json
tmp/span_table_tree_page_184/tree.png
```

## 3. Native span evidence

Important native orders on page 184:

```text
order 75: 年末数
order 76: 年初数
order 79: 项目
order 80..85: six leaf headers
order 90..97: first body row
order 103..109: total row
```

The demo recovers seven leaf columns:

```text
项目
年末数 / 账面余额
年末数 / 比例
年末数 / 坏账准备
年初数 / 账面余额
年初数 / 比例
年初数 / 坏账准备
```

Target tree:

```text
Table
├── 项目
├── 年末数
│   ├── 账面余额
│   ├── 比例
│   └── 坏账准备
└── 年初数
    ├── 账面余额
    ├── 比例
    └── 坏账准备
```

## 4. Why native order matters

A PDF may emit a merged left-side label as several text blocks before emitting the right-side cells:

```text
left text 1
left text 2
left text 3
right content 1
right content 2
right content 3
```

Geometrically, the three left blocks may occupy three visual rows. If they are first forced into coordinate-aligned pairs, the evidence for a vertical merged cell is lost.

The intended rule is:

```text
Native order determines sequence and precedence.
Coordinates determine geometric row/column constraints.
The document tree expresses the structural relationship.
```

The current demo keeps order_start/order_end on every node. It does not use a globally y/x-sorted text list as the structure input.

## 5. Current implementation

Implementation:

```text
scripts/span_table_tree_demo.py
```

Tests:

```text
tests/test_span_table_tree_demo.py
tests/test_span_table_tree_demo_integration.py
```

### 5.1 build_text_nodes

Converts NativeSpan to TreeNode(kind="text") and preserves:

- text;
- bbox;
- order_start/order_end;
- character boxes for wide-span expansion.

No order is changed at this stage.

### 5.2 expand_wide_node

Some PDFs emit a complete header row as one wide span:

```text
账面余额    比例    坏账准备
```

Character bboxes and horizontal gaps are used to split it into phrases. Each phrase inherits the parent span order. This changes geometric granularity, not native output order.

### 5.3 _rows

Nodes are traversed in native order. Their y-center and height tolerance determine whether they belong to the same visual row.

The current behavior is:

- native order controls traversal;
- y geometry identifies visual-row membership;
- within a row, the incoming native order is retained.

This is not a complete document-tree parser yet; it is the row grouping layer for the demo.

### 5.4 Header tree

build_table_tree performs these steps:

1. Build visual rows.
2. Keep separator nodes in the row data.
3. Exclude separator-only nodes only when selecting header candidates, so separator rows cannot masquerade as leaf headers.
4. Select the header candidate with the largest number of non-separator phrases.
5. Find the preceding effective header row and use its left-side label as the stub column (项目).
6. Create leaf-column nodes from the leaf header row.
7. For this page, split six numeric leaf columns into two groups of three: 年末数 and 年初数.
8. Keep all body nodes, including separator text.

The 3+3 grouping is a page-specific demo simplification. It is not yet a general header-group algorithm.

### 5.5 Body column assignment

A body phrase is assigned to the leaf column whose x-center is nearest to the phrase x-center.

A leaf column is not deleted just because it has no numeric value. This preserves sparse columns that may contain only separators or blanks.

### 5.6 Ordered rowspan experiment

_apply_ordered_rowspans tests the pattern:

```text
left text 1, order 7
left text 2, order 8
left text 3, order 9
right content 1, order 10
right content 2, order 11
right content 3, order 12
```

A vertical merge is considered when:

1. Candidate rows contain exactly one left-column cell each.
2. Those left cells form a continuous vertical run.
3. Right-side cells exist in the same vertical range.
4. Every relevant right-side order is after the maximum left-side order.

Then:

- the first left cell receives newline-joined text;
- its rowspan becomes the run length;
- duplicate left cells in later rows are removed.

The exactly-one-left-cell constraint prevents a false merge when character expansion produces multiple phrases in one visual row, such as:

```text
same visual row: 1 + 年以内
next visual row: 合计
```

The previous implementation took only the first left cell per row and incorrectly merged 合计. The constraint fixed that regression.

## 6. PNG visualization

tree.png now overlays:

- red outer rectangle: supplied table bbox;
- orange rectangles: native spans or character-expanded phrases;
- red numbers: NativeSpan.order;
- purple rectangles: header groups;
- blue rectangles: leaf columns;
- green horizontal/vertical grid: recovered body rows and columns;
- green R0 C1 labels: logical cell row/column coordinates;
- rs=N and cs=N: rowspan and colspan markers.

The green grid is the structure result. The orange boxes and red order numbers are native-PDF evidence.

The visualization is intended to answer:

```text
Which logical row/column receives each native phrase?
Are sparse columns retained?
Do separator texts stay in their columns?
Are rowspan/colspan relations plausible?
```

## 7. Current verification

The unified logical grid now includes both header rows. `年末数` and `年初数` are serialized as header cells with `colspan=3`; `项目` and all six leaf headers occupy the second header row. The PNG green grid begins at the top group-header row and continues through the body.

Command:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_span_table_tree_demo.py tests/test_span_table_tree_demo_integration.py
```

Latest result:

```text
5 passed
```

Additional checks:

```text
leaf_columns = 7
tree.json parses successfully
tree.png is generated
git diff --check passes
```

Current files:

```text
tmp/span_table_tree_page_184/tree.json
tmp/span_table_tree_page_184/tree.png
```

## 8. Known limitations

### 8.1 Header grouping is still page-specific

The current code uses a fixed 3+3 split for the six numeric leaves. A general implementation should infer group coverage from:

- parent header bbox;
- native order;
- horizontal separator coverage;
- leaf-column x ranges;
- parent-to-child containment.

### 8.2 Row recovery is still geometry-first

_ordered row evidence is used mainly for rowspan. Complex PDFs may contain:

- one logical row split into multiple y layers;
- one wide span containing multiple logical cells;
- interleaved left/right native output;
- separator lines forming independent visual rows.

A later version should make sequence segmentation, spatial coverage, and candidate-cell association explicit parts of the document-tree construction.

### 8.3 Real rowspan coverage is incomplete

The synthetic test verifies a three-row left-side rowspan. The tested aging table does not contain the exact three-text-block vertical merge case.

Add fixtures for:

- multiple populated right-side columns;
- left rowspan with ordinary right-side rows;
- blank left cells after a rowspan;
- rowspan and colspan together.

### 8.4 Phrase-to-cell aggregation is incomplete

字符级 expansion may split 1 年以内 into multiple phrases. The demo now avoids a false rowspan, but it does not yet re-aggregate those phrases into one semantic cell.

The next aggregation layer should:

- merge same-span, same-visual-row, same-column phrases first;
- consider rowspan only across visual rows with order evidence;
- preserve all source span/order metadata.

### 8.5 Text encoding needs a separate check

PowerShell output previously displayed mojibake for some JSON text while the rendered PDF image displayed Chinese correctly. Confirm separately whether:

- NativeSpan.text is already corrupted;
- only terminal display encoding is wrong;
- JSON is consistently written and read as UTF-8.

This is a text-content issue, separate from row/column structure.

## 9. Recommended next steps

1. Keep the page-184 PNG as the baseline sample, including the unified header grid.
2. Add phrase-to-cell aggregation tests for 1 年以内-like same-row phrases.
3. Replace fixed 3+3 header grouping with bbox/order/coverage-based grouping.
4. Run the demo on the other应收款构成 region.
5. Add synthetic rowspan/colspan combination fixtures.
6. Keep the production extractor unchanged while validating the tree algorithm.
7. Integrate into production only after the demo is stable across representative pages.

## 10. Related files

- Design: docs/superpowers/specs/2026-08-27-span-table-document-tree-demo-design.md
- Plan: docs/superpowers/plans/2026-08-27-span-table-document-tree-demo.md
- Demo: scripts/span_table_tree_demo.py
- Unit tests: tests/test_span_table_tree_demo.py
- Integration test: tests/test_span_table_tree_demo_integration.py
- Current JSON: tmp/span_table_tree_page_184/tree.json
- Current PNG: tmp/span_table_tree_page_184/tree.png
