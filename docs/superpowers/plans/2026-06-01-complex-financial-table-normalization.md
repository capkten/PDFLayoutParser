# Complex Financial Table Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep baseline table extraction conservative, then post-process extracted tables so grouped financial headers such as `本年金额` are absorbed into the table structure without disturbing ordinary tables.

**Architecture:** `TableExtractor` continues to find a core table region first. A new post-processing module normalizes each extracted `Table` in two passes: a generic cleanup pass for all tables, then a financial grouped-header promotion pass that can expand `Table.bbox` upward and assign `rowspan` / `colspan` when the geometry and text strongly indicate a two-level financial header. The default pipeline keeps the current behavior for plain tables; the special path only fires when the table layout matches the grouped-header pattern.

**Tech Stack:** Python 3.10, PyMuPDF (`fitz`), `pytest`, existing `BBox` / `Cell` / `Table` dataclasses, existing HTML-table Markdown rendering.

---

### Task 1: Lock the expected behavior with regression tests

**Files:**
- Modify: `tests/test_table_extractor.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_financial_grouped_header_is_promoted_on_page_046():
    pdf_path = Path(r"D:\codes\PDFLayoutParser\152590_20230428_N7ZK_0.pdf")

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[46])

    financial = next(
        t for t in tables
        if any("本年金额" in cell.text for cell in t.cells)
        or (t.rows >= 3 and t.cols >= 8)
    )

    assert financial.bbox.y0 < 310.0
    assert any(
        cell.text == "本年金额" and cell.colspan == 7
        for cell in financial.cells
    )
    assert any(
        cell.text == "项目" and cell.rowspan == 2
        for cell in financial.cells
    )


def test_plain_grid_table_is_not_changed_by_header_normalization(tmp_dir):
    pdf_path = Path(tmp_dir) / "plain_grid.pdf"
    make_pdf_with_table(pdf_path)

    with fitz.open(str(pdf_path)) as doc:
        extractor = TableExtractor()
        tables = extractor.extract(doc[0])

    assert len(tables) == 1
    table = tables[0]
    assert table.rows == 2
    assert table.cols == 2
    assert all(cell.rowspan == 1 for cell in table.cells)
    assert all(cell.colspan == 1 for cell in table.cells)
```

- [ ] **Step 2: Run the tests to verify they fail on the current code**

Run:
```bash
pytest tests/test_table_extractor.py -k "financial_grouped_header or plain_grid_table" -v
```

Expected:
- `test_financial_grouped_header_is_promoted_on_page_046` fails because the current table bbox does not absorb `本年金额` and does not assign the grouped-header spans.
- `test_plain_grid_table_is_not_changed_by_header_normalization` passes or stays stable.

- [ ] **Step 3: Keep the test shape minimal**

If the page-046 regression is too expensive to run in every test iteration, keep one narrow assertion that directly checks the second table's header band:

```python
assert any("本年金额" in cell.text for table in tables for cell in table.cells)
assert min(t.bbox.y0 for t in tables if t.source) < 310.0
```

- [ ] **Step 4: Re-run the same test command after the implementation lands**

Run:
```bash
pytest tests/test_table_extractor.py -k "financial_grouped_header or plain_grid_table" -v
```

Expected:
- Both tests pass.

- [ ] **Step 5: Commit the test-only baseline**

```bash
git add tests/test_table_extractor.py
git commit -m "test: lock financial grouped-header regression"
```

---

### Task 2: Add a table header normalizer for generic and financial tables

**Files:**
- Create: `src/hexai_pdf_parser/table_header_normalizer.py`
- Modify: `src/hexai_pdf_parser/models.py` only if the implementation needs a small helper type or copy helper; otherwise leave it unchanged

- [ ] **Step 1: Write the failing implementation-facing tests**

The new module should expose a small, testable surface:

```python
def normalize_table_headers(table: Table, page: fitz.Page) -> Table:
    ...


def _looks_like_grouped_financial_header(table: Table, page: fitz.Page) -> bool:
    ...


def _promote_grouped_header(table: Table, page: fitz.Page) -> Table:
    ...
```

Add a unit test that builds a table object directly and verifies the transformation:

```python
def test_promote_grouped_financial_header_sets_rowspan_and_colspan():
    table = Table(
        bbox=BBox(40.0, 320.0, 804.0, 408.0),
        rows=3,
        cols=8,
        cells=[
            Cell(text="项目", row_index=0, col_index=0, bbox=BBox(40.0, 320.0, 90.0, 340.0)),
            Cell(text="本年金额", row_index=0, col_index=1, bbox=BBox(350.0, 300.0, 760.0, 315.0)),
            Cell(text="年初资产总额", row_index=1, col_index=1, bbox=BBox(120.0, 340.0, 200.0, 360.0)),
            Cell(text="年初负债总额", row_index=1, col_index=2, bbox=BBox(200.0, 340.0, 280.0, 360.0)),
        ],
    )

    normalized = normalize_table_headers(table, page)

    assert normalized.bbox.y0 <= 300.0
    assert any(c.text == "项目" and c.rowspan == 2 for c in normalized.cells)
    assert any(c.text == "本年金额" and c.colspan == 7 for c in normalized.cells)
```

- [ ] **Step 2: Run the unit test to verify it fails initially**

Run:
```bash
pytest tests/test_table_extractor.py -k "promote_grouped_financial_header" -v
```

Expected:
- Fails because the module does not exist yet or the normalizer returns the input unchanged.

- [ ] **Step 3: Implement the minimal normalizer**

Implement the module so that it behaves in two clear layers:

```python
def normalize_table_headers(table: Table, page: fitz.Page) -> Table:
    table = _normalize_generic_table(table)
    if _looks_like_grouped_financial_header(table, page):
        return _promote_grouped_header(table, page)
    return table
```

Generic pass requirements:
- Leave ordinary two-column and simple grid tables unchanged.
- Preserve existing `rowspan` / `colspan` values.
- Do not shrink a table that already looks correct.

Financial grouped-header pass requirements:
- Detect a short top header band such as `本年金额`, `本年金额` variants, or equivalent grouped header phrases.
- Require a left-side anchor such as `项目` in the first column.
- Require a second header row with the detailed column labels.
- Extend `Table.bbox.y0` upward so the grouped header becomes part of the table.
- Set the left anchor cell to `rowspan=2`.
- Set the grouped header cell to `colspan=7` for this page pattern.
- Leave all body cells in place.

- [ ] **Step 4: Run the unit test again**

Run:
```bash
pytest tests/test_table_extractor.py -k "promote_grouped_financial_header" -v
```

Expected:
- The direct normalizer test passes.

- [ ] **Step 5: Commit the new module**

```bash
git add src/hexai_pdf_parser/table_header_normalizer.py tests/test_table_extractor.py
git commit -m "feat: normalize grouped financial table headers"
```

---

### Task 3: Wire the normalizer into table extraction

**Files:**
- Modify: `src/hexai_pdf_parser/table_extractor.py`

- [ ] **Step 1: Add a failing integration check for the extractor path**

The extractor should call the normalizer for every extracted table, after baseline extraction and any existing structure rules:

```python
from hexai_pdf_parser.table_header_normalizer import normalize_table_headers

# after line / text / fallback / config structure work
tables = [normalize_table_headers(table, page) for table in tables]
```

Add an integration assertion that confirms the second table on page 46 now contains the absorbed header band:

```python
with fitz.open(str(pdf_path)) as doc:
    tables = TableExtractor().extract(doc[46])

financial = next(t for t in tables if any(c.text == "本年金额" for c in t.cells))
assert financial.bbox.y0 <= 310.0
```

- [ ] **Step 2: Run the extractor test to see the current failure**

Run:
```bash
pytest tests/test_table_extractor.py -k "financial_grouped_header_is_promoted_on_page_046" -v
```

Expected:
- The assertion fails before the normalizer is wired in.

- [ ] **Step 3: Make the smallest change in `TableExtractor.extract()`**

Insert the normalizer after the current extraction / profile-rule pipeline, before the return:

```python
from hexai_pdf_parser.table_header_normalizer import normalize_table_headers

def extract(self, page: fitz.Page) -> List[Table]:
    ...
    if self._table_config and self._table_config.profiles:
        tables = self._apply_layout_rules(page, tables)

    tables = [normalize_table_headers(table, page) for table in tables]
    return tables
```

This keeps the new behavior in one place and avoids changing the output schema.

- [ ] **Step 4: Re-run the extractor regression and the plain-table regression**

Run:
```bash
pytest tests/test_table_extractor.py -k "financial_grouped_header or plain_grid_table" -v
```

Expected:
- The financial regression passes.
- The plain grid table stays unchanged.

- [ ] **Step 5: Commit the wiring change**

```bash
git add src/hexai_pdf_parser/table_extractor.py
git commit -m "feat: apply table header normalization during extraction"
```

---

### Task 4: Verify output stability on the writer path and close the loop

**Files:**
- Modify: `tests/test_markdown_writer.py` only if a new writer regression is needed
- Optional: `out_review/152590_20230428_N7ZK_0/pages/page-046.label.html` for manual comparison only; do not change it unless the review artifact itself needs an update

- [ ] **Step 1: Add the writer regression only if the extracted spans are not already covered**

The writer already preserves spans, so this task should only add a regression if the new normalized header cells expose a writer gap:

```python
def test_render_table_keeps_grouped_header_spans():
    table = Table(
        bbox=BBox(0, 0, 200, 100),
        rows=2,
        cols=3,
        cells=[
            Cell(text="项目", row_index=0, col_index=0, bbox=BBox(0, 0, 20, 20), rowspan=2),
            Cell(text="本年金额", row_index=0, col_index=1, bbox=BBox(20, 0, 180, 20), colspan=2),
            Cell(text="年初资产总额", row_index=1, col_index=1, bbox=BBox(20, 20, 100, 40)),
            Cell(text="年初负债总额", row_index=1, col_index=2, bbox=BBox(100, 20, 180, 40)),
        ],
    )

    lines = MarkdownWriter()._render_table(table)
    content = "\n".join(lines)

    assert '<td rowspan="2">项目</td>' in content
    assert '<td colspan="2">本年金额</td>' in content
```

- [ ] **Step 2: Run the writer test**

Run:
```bash
pytest tests/test_markdown_writer.py -k "grouped_header_spans or render_table_uses_html_and_preserves_spans" -v
```

Expected:
- Pass.

- [ ] **Step 3: Run the focused extractor suite**

Run:
```bash
pytest tests/test_table_extractor.py -k "financial_grouped_header or plain_grid_table or line_based_tables_unchanged_without_profile" -v
```

Expected:
- The financial page 46 regression passes.
- Simple tables remain unchanged.
- Existing line-based behavior is preserved.

- [ ] **Step 4: Manually compare the saved review artifact**

Confirm `D:\codes\PDFLayoutParser\out_review\152590_20230428_N7ZK_0\pages\page-046.label.html` still reflects the intended interpretation:
- The first table remains a generic table.
- The second table includes `本年金额` as an in-table grouped header.

- [ ] **Step 5: Commit the verification pass**

```bash
git add tests/test_markdown_writer.py tests/test_table_extractor.py
git commit -m "test: verify grouped financial table rendering"
```

---

### Coverage Map

- Generic table behavior is covered by the plain grid regression.
- The `page-046` second table is covered by the grouped-header regression.
- The new normalizer is isolated in a dedicated module, so `TableExtractor` stays readable.
- The writer path is already span-aware; the verification step only adds a regression if the new span shape reveals a gap.

