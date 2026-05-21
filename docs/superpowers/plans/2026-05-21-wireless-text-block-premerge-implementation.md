# Wireless Text Block Premerge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative premerge layer for fragmented PDF text blocks so the wireless table path can merge near-touching or overlapping fragments before row clustering and column inference.

**Architecture:** Keep the change scoped to the wireless table text-alignment path inside `TableExtractor`. Normalize raw `page.get_text("words")` output into token dicts, run a conservative premerge pass that only merges clearly adjacent fragments, and then feed the merged tokens into the existing row-band and column-guide logic. The main line-based table path remains unchanged.

**Tech Stack:** Python 3.10+, PyMuPDF, pytest, existing `pdflayoutparser` dataclasses and table extraction helpers.

---

### Task 1: Lock the premerge contract with failing tests

**Files:**
- Modify: `tests/test_table_extractor.py`

- [ ] **Step 1: Write the failing test**

Add unit coverage for two behaviors:
- close fragments inside the same visual row merge into a single token
- fragments from different rows do not merge, even if their x positions overlap

```python
from pdflayoutparser.table_extractor import TableExtractor


def test_collect_text_rows_merges_close_fragments_into_one_token():
    extractor = TableExtractor()
    rows = extractor._collect_text_rows(
        [
            (10.0, 10.0, 24.0, 22.0, "人民"),
            (24.2, 10.0, 31.0, 22.0, "币"),
        ]
    )

    assert len(rows) == 1
    assert [token["text"] for token in rows[0]["tokens"]] == ["人民币"]


def test_collect_text_rows_keeps_tokens_on_different_rows_separate():
    extractor = TableExtractor()
    rows = extractor._collect_text_rows(
        [
            (10.0, 10.0, 24.0, 22.0, "A"),
            (24.2, 10.0, 31.0, 22.0, "B"),
            (10.0, 40.0, 24.0, 52.0, "C"),
        ]
    )

    assert len(rows) == 2
    assert [token["text"] for token in rows[0]["tokens"]] == ["AB"]
    assert [token["text"] for token in rows[1]["tokens"]] == ["C"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_table_extractor.py -k "collect_text_rows_merges_close_fragments or keeps_tokens_on_different_rows_separate" -v
```

Expected: both tests fail because `_collect_text_rows()` still returns raw fragments as separate tokens.

- [ ] **Step 3: Do not implement yet**

Stop after confirming the failure shape. If the tests already pass, adjust them so they exercise a real missing behavior, not the current implementation.

- [ ] **Step 4: Commit the red tests**

```bash
git add tests/test_table_extractor.py
git commit -m "test: lock wireless text block premerge behavior"
```

### Task 2: Implement conservative premerge inside the wireless text row collector

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py:2431-2495`
- Modify: `src/pdflayoutparser/table_extractor.py:1677-1872`

- [ ] **Step 1: Write the minimal implementation**

Add a private merge helper that only joins fragments when the row distance is tiny and the horizontal gap is tiny or negative. Recompute the merged token classification from the merged text so the downstream numeric heuristics stay consistent.

```python
def _merge_text_tokens(self, tokens: list[dict]) -> list[dict]:
    if len(tokens) < 2:
        return tokens

    ordered = sorted(tokens, key=lambda token: (token["y_center"], token["x0"]))
    merged: list[dict] = []
    current = dict(ordered[0])

    for token in ordered[1:]:
        same_row = abs(token["y_center"] - current["y_center"]) <= 3.0
        x_gap = token["x0"] - current["x1"]
        close_horizontally = x_gap <= 1.5
        overlaps_horizontally = token["x0"] <= current["x1"] + 0.5

        if same_row and (close_horizontally or overlaps_horizontally):
            merged_text = f'{current["text"]}{token["text"]}'
            merged_x0 = min(current["x0"], token["x0"])
            merged_y0 = min(current["y0"], token["y0"])
            merged_x1 = max(current["x1"], token["x1"])
            merged_y1 = max(current["y1"], token["y1"])
            current = self._classify_token_text(merged_text)
            current["x0"] = merged_x0
            current["y0"] = merged_y0
            current["x1"] = merged_x1
            current["y1"] = merged_y1
            current["y_center"] = (merged_y0 + merged_y1) / 2
            continue

        merged.append(current)
        current = dict(token)

    merged.append(current)
    return merged
```

Then call that helper from `_collect_text_rows()` after token normalization and before row clustering:

```python
normalized.sort(key=lambda token: (token["y_center"], token["x0"]))
normalized = self._merge_text_tokens(normalized)
normalized.sort(key=lambda token: (token["y_center"], token["x0"]))
```

Keep the existing row tolerance and row output format unchanged so the rest of the wireless table pipeline keeps working.

- [ ] **Step 2: Run test to verify it passes**

Run:

```bash
pytest tests/test_table_extractor.py -k "collect_text_rows_merges_close_fragments or keeps_tokens_on_different_rows_separate" -v
```

Expected: both tests pass, and the merged token text becomes `人民币` in the first case while the second case remains split by rows.

- [ ] **Step 3: Commit the implementation**

```bash
git add src/pdflayoutparser/table_extractor.py tests/test_table_extractor.py
git commit -m "feat: premerge fragmented wireless text blocks"
```

### Task 3: Document the new preprocessing stage

**Files:**
- Modify: `docs/wireless_table_structure_algorithm.md`

- [ ] **Step 1: Add a premerge stage section**

Add a short section before the row-band clustering step that explains:
- raw PDF words may be fragmented by the renderer
- the pipeline now merges near-touching or overlapping fragments first
- the premerge step is conservative and row-local
- the goal is to stabilize row clustering and column inference, not to perform semantic tokenization

The added text should fit the existing style of the document and reuse the current terminology (`text_alignment`, `row band`, `column guide`).

- [ ] **Step 2: Run a doc sanity check**

Run:

```bash
python - <<'PY'
from pathlib import Path
path = Path(r"D:\\codes\\PDFLayoutParser\\docs\\wireless_table_structure_algorithm.md")
text = path.read_text(encoding="utf-8")
assert "预合并" in text or "premerge" in text
print("doc ok")
PY
```

Expected: `doc ok`

- [ ] **Step 3: Commit the doc update**

```bash
git add docs/wireless_table_structure_algorithm.md
git commit -m "docs: describe wireless text block premerge"
```

### Task 4: Run the focused regression suite

**Files:**
- Test-only verification, no source changes

- [ ] **Step 1: Run the focused table extractor tests**

Run:

```bash
pytest tests/test_table_extractor.py -v
```

Expected:
- the new premerge tests pass
- existing `text_alignment` snapshot and numeric-fragment tests still pass
- no new failures appear in the table extractor suite

- [ ] **Step 2: Run the pipeline regression tests**

Run:

```bash
pytest tests/test_pipeline.py -v
```

Expected:
- pipeline behavior is unchanged for line-based tables
- no regressions in text-alignment debug output or page-level serialization

- [ ] **Step 3: Report the actual outcome**

If any test fails, record the exact failing assertion and revisit the merge threshold or call site before expanding scope.
