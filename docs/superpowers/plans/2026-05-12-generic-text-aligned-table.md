# Generic Text-Aligned Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a robust text-aligned table extraction capability that can support three-line tables, horizontal-only tables, and borderless aligned tables, while avoiding premature integration into the main extraction path before matrix reconstruction and header recovery are ready.

**Architecture:** Build the text-aligned extraction flow in two phases. Phase 1 adds internal helpers and a directly testable internal extraction path without wiring it into `TableExtractor.extract()`. Phase 2 adds matrix-first cell reconstruction, bottom-up header recovery, mixed-page merge rules, and only then integrates the new branch into the production entrypoint.

**Tech Stack:** Python 3.10+, PyMuPDF (`fitz`), pytest

---

## Execution Adjustment

This plan intentionally avoids exposing a partial text-aligned branch through `extract()` too early.

Reason:

- Candidate-region heuristics alone are not stable enough to own production behavior.
- Before matrix reconstruction and header recovery exist, the text-aligned path tends to overfit simple cases and misclassify list/prose layouts.
- Mixed pages need final merge rules, not temporary shortcut logic.

Therefore the execution order is:

1. Build internal helpers and test them directly.
2. Build matrix reconstruction and header recovery.
3. Build mixed-page merge logic.
4. Only after those are in place, connect the new branch to `extract()`.

This is the main adjustment from the previous plan.

### Task 1: Add token classification and visual row collection helpers

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Write failing helper tests**

```python
def test_collect_text_rows_groups_words_by_visual_row():
    extractor = TableExtractor()
    words = [
        (52.0, 40.0, 60.0, 50.0, "B2"),
        (10.0, 10.0, 18.0, 20.0, "A1"),
        (12.0, 41.0, 20.0, 51.0, "A2"),
        (50.0, 11.0, 58.0, 21.0, "B1"),
    ]

    rows = extractor._collect_text_rows(words)

    assert len(rows) == 2
    assert [token["text"] for token in rows[0]["tokens"]] == ["A1", "B1"]
    assert [token["text"] for token in rows[1]["tokens"]] == ["A2", "B2"]


def test_classify_token_text_marks_numeric_separators():
    extractor = TableExtractor()

    grouped = extractor._classify_token_text("1,234.50")

    assert grouped["is_numeric"] is True
    assert grouped["has_decimal"] is True
    assert grouped["has_group_separator"] is True
```

- [x] **Step 2: Run focused tests to confirm failure**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "collect_text_rows or classify_token_text" -v`
Expected: FAIL with missing helper methods.

- [x] **Step 3: Implement `_classify_token_text()` and `_collect_text_rows()`**

Requirements:

- `_classify_token_text()` must classify numeric vs non-numeric tokens.
- It must flag decimal and grouped-number patterns.
- `_collect_text_rows()` must cluster word tuples into visual rows, sort by x, and return row dictionaries containing `tokens`, `x0`, `x1`, `y0`, `y1`.
- Do not wire anything into `extract()` yet.

- [x] **Step 4: Re-run focused tests**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "collect_text_rows or classify_token_text" -v`
Expected: PASS

### Task 2: Add candidate-region helpers with hard gates, but keep them internal

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Write failing tests for candidate-region acceptance and rejection**

```python
def test_collect_text_candidate_regions_accepts_repeated_columns():
    extractor = TableExtractor()
    words = [
        (10.0, 10.0, 20.0, 20.0, "A1"),
        (60.0, 10.0, 70.0, 20.0, "B1"),
        (10.0, 30.0, 20.0, 40.0, "A2"),
        (60.0, 30.0, 70.0, 40.0, "B2"),
        (10.0, 50.0, 20.0, 60.0, "A3"),
        (60.0, 50.0, 70.0, 60.0, "B3"),
    ]

    rows = extractor._collect_text_rows(words)
    regions = extractor._collect_text_candidate_regions(rows)

    assert len(regions) == 1


def test_collect_text_candidate_regions_rejects_paragraph_like_rows():
    extractor = TableExtractor()
    words = [
        (10.0, 10.0, 18.0, 20.0, "This"),
        (24.0, 10.0, 40.0, 20.0, "is"),
        (46.0, 10.0, 70.0, 20.0, "a"),
        (76.0, 10.0, 110.0, 20.0, "paragraph"),
        (10.0, 28.0, 18.0, 38.0, "with"),
        (24.0, 28.0, 40.0, 38.0, "wrapped"),
        (46.0, 28.0, 70.0, 38.0, "lines"),
    ]

    rows = extractor._collect_text_rows(words)
    regions = extractor._collect_text_candidate_regions(rows)

    assert regions == []
```

- [x] **Step 2: Run focused tests to confirm failure**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "candidate_regions" -v`
Expected: FAIL with missing candidate-region helpers.

- [x] **Step 3: Implement internal candidate-region helpers**

Requirements:

- Add row-span splitting.
- Add repeated-column checks.
- Add paragraph/list rejection heuristics.
- Keep this as internal capability only; do not change `extract()` yet.

- [x] **Step 4: Re-run focused tests**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "candidate_regions" -v`
Expected: PASS

### Task 3: Add weighted column-guide inference with numeric anchor weighting

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Write failing tests for guide inference**

```python
def test_infer_column_guides_weights_numeric_anchors_more_heavily():
    extractor = TableExtractor()
    rows = [
        {
            "tokens": [
                extractor._classify_token_text("1,234.50")
                | {"x0": 90.0, "x1": 120.0, "y0": 10.0, "y1": 20.0},
            ],
            "x0": 90.0,
            "x1": 120.0,
            "y0": 10.0,
            "y1": 20.0,
        },
        {
            "tokens": [
                extractor._classify_token_text("1,250.75")
                | {"x0": 91.0, "x1": 121.0, "y0": 30.0, "y1": 40.0},
            ],
            "x0": 91.0,
            "x1": 121.0,
            "y0": 30.0,
            "y1": 40.0,
        },
    ]

    guides = extractor._infer_column_guides(rows)

    assert len(guides) == 1
    assert guides[0] > 118.0
```

- [x] **Step 2: Run focused tests to confirm failure**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "infer_column_guides" -v`
Expected: FAIL with missing guide inference helper.

- [x] **Step 3: Implement `_infer_column_guides()`**

Requirements:

- Weight numeric `right_anchor` more strongly.
- Boost rows showing decimal or grouped-number cues.
- Avoid exploding multi-word label clusters into unnecessary text-side guides.
- Keep this internal; do not wire into `extract()` yet.

- [x] **Step 4: Re-run focused tests**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "infer_column_guides" -v`
Expected: PASS

### Task 4: Add an internal `_extract_via_text_alignment()` and test it directly

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Write failing direct tests for the internal path**

```python
def test_extract_via_text_alignment_returns_simple_text_table():
    extractor = TableExtractor()
    page = SimpleNamespace(
        rect=fitz.Rect(0, 0, 200, 200),
        get_text=lambda kind, clip=None: [
            (10.0, 10.0, 20.0, 20.0, "R1C1"),
            (80.0, 10.0, 95.0, 20.0, "R1C2"),
            (10.0, 30.0, 20.0, 40.0, "R2C1"),
            (80.0, 30.0, 95.0, 40.0, "R2C2"),
            (10.0, 50.0, 20.0, 60.0, "R3C1"),
            (80.0, 50.0, 95.0, 60.0, "R3C2"),
        ],
    )

    tables = extractor._extract_via_text_alignment(page)

    assert len(tables) == 1
    assert tables[0].source == "text_alignment"
```

- [x] **Step 2: Run focused tests to confirm failure**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "extract_via_text_alignment" -v`
Expected: FAIL with missing internal path.

- [x] **Step 3: Implement the internal text-aligned path**

Requirements:

- Use the new row, candidate-region, and guide helpers.
- Build a simple row/column assignment path sufficient for direct tests.
- Keep it internal only.
- Do not change `extract()` yet.

- [x] **Step 4: Re-run focused tests**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "extract_via_text_alignment" -v`
Expected: PASS

### Task 5: Add matrix skeleton generation

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Write failing tests for matrix skeleton**

```python
def test_build_matrix_skeleton_from_rows_and_guides():
    extractor = TableExtractor()
    rows = [
        {"y0": 10.0, "y1": 20.0, "tokens": []},
        {"y0": 30.0, "y1": 40.0, "tokens": []},
    ]
    guides = [10.0, 100.0, 180.0]

    matrix = extractor._build_matrix_skeleton(rows, guides, BBox(0.0, 10.0, 200.0, 40.0))

    assert len(matrix) == 2
    assert len(matrix[0]) == 2
```

- [x] **Step 2: Run focused tests to confirm failure**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "matrix_skeleton" -v`
Expected: FAIL with missing skeleton helper.

- [x] **Step 3: Implement matrix skeleton creation**

Requirements:

- Build row boundaries from row boxes.
- Build column intervals from global guides.
- Generate a stable matrix of base cells.

- [x] **Step 4: Re-run focused tests**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "matrix_skeleton" -v`
Expected: PASS

### Task 6: Fill matrix cells and recover bottom-up headers

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Write failing tests for matrix fill and bottom-up header recovery**

```python
def test_extract_keeps_multi_word_labels_in_two_column_shape():
    extractor = TableExtractor()
    page = SimpleNamespace(
        rect=fitz.Rect(0, 0, 200, 100),
        get_text=lambda kind, clip=None: [
            (10.0, 10.0, 26.0, 20.0, "Net"),
            (30.0, 10.0, 58.0, 20.0, "sales"),
            (120.0, 10.0, 150.0, 20.0, "120"),
            (10.0, 28.0, 26.0, 38.0, "Operating"),
            (30.0, 28.0, 56.0, 38.0, "income"),
            (120.0, 28.0, 150.0, 38.0, "90"),
        ],
    )

    tables = extractor._extract_via_text_alignment(page)

    assert len(tables) == 1
    assert tables[0].cols == 2
```

- [x] **Step 2: Run focused tests to confirm failure**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "multi_word_labels_in_two_column_shape" -v`
Expected: FAIL until matrix fill and clustering are stable.

- [x] **Step 3: Implement matrix fill and bottom-up header recovery**

Requirements:

- Fill tokens into base matrix cells.
- Merge left-side text clusters correctly.
- Recover `rowspan` / `colspan` bottom-up in the header zone.

- [x] **Step 4: Re-run focused tests**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "multi_word_labels_in_two_column_shape" -v`
Expected: PASS

Implementation note:

- `TableExtractor.extract()` is now wired to use `_extract_via_text_alignment()` as a guarded fallback when line extraction is empty or unreliable.
- The remaining matrix reconstruction, bottom-up header recovery, and mixed-page merge work from Tasks 5 to 7 are still pending.

### Task 7: Add mixed-page merge logic and only then integrate into `extract()`

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Write failing integration tests for mixed pages and fallback preservation**

```python
def test_extract_returns_both_wired_and_text_aligned_tables_on_mixed_page():
    extractor = TableExtractor()
    wired_table = Table(
        bbox=BBox(0, 0, 100, 100),
        rows=2,
        cols=2,
        cells=[Cell(text="wired", row_index=0, col_index=0, bbox=BBox(0, 0, 50, 50))],
        confidence=0.9,
        source="line_projection",
    )
    text_table = Table(
        bbox=BBox(150, 0, 240, 100),
        rows=2,
        cols=2,
        cells=[Cell(text="text", row_index=0, col_index=0, bbox=BBox(150, 0, 190, 40))],
        confidence=0.75,
        source="text_alignment",
    )

    extractor._extract_via_lines = lambda page: [wired_table]
    extractor._extract_via_text_alignment = lambda page: [text_table]
    extractor._should_fallback = lambda tables: False

    result = extractor.extract(SimpleNamespace())

    assert result == [wired_table, text_table]
```

- [x] **Step 2: Run focused tests to confirm failure**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "mixed_page" -v`
Expected: FAIL because `extract()` does not yet merge the branches.

- [x] **Step 3: Integrate the text-aligned path into `extract()`**

Requirements:

- Keep wired-table priority.
- Allow same-page coexistence of wired and text-aligned tables.
- Prevent duplicate bboxes.
- Ensure wired fallback does not erase independent text-aligned tables.

- [x] **Step 4: Re-run focused tests**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -k "mixed_page" -v`
Expected: PASS

### Task 8: Add final negative tests and run full regression

**Files:**
- Modify: `tests/test_table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [x] **Step 1: Add final negative regression cases**

Coverage required:

- 2-row prose with stable x positions must be rejected.
- 3-row prose/list layouts must be rejected.
- Wired-table behavior must remain intact.

- [x] **Step 2: Run focused extractor suite**

Run: `PYTHONPATH=src pytest tests/test_table_extractor.py -v`
Expected: PASS

- [x] **Step 3: Run full project regression**

Run: `PYTHONPATH=src pytest`
Expected: PASS
