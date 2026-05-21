# Borderless Table Region Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone borderless-table region detection prototype that converts `words -> fragments -> rows -> candidate regions`, outputs visual overlays, and can be audited page-by-page on the sample PDF before any integration into the main pipeline.

**Architecture:** Keep the prototype isolated from `Pipeline` and `TableExtractor`. Reuse the existing `text_visual_debug.py` layer for `words/fragments/rows`, then add `CandidateRegion` modeling, row-level feature extraction, region scoring, and overlay/JSON export. Treat region detection and structure reconstruction as separate systems: this plan only builds the former.

**Tech Stack:** Python 3.10+, PyMuPDF, pytest, existing `pdflayoutparser` models/utilities.

---

## File Map

**Create**
- `src/pdflayoutparser/text_region_detector.py`
- `tests/test_text_region_detector.py`

**Modify**
- `src/pdflayoutparser/text_visual_debug.py`
- `debug_text_visual.py`

**Reference Only**
- `docs/superpowers/specs/2026-05-14-borderless-table-region-detection-design.md`
- `152590_20230428_N7ZK_0.pdf`

## Delivery Rules

- The prototype must stay outside the main pipeline.
- All text files must be UTF-8.
- Every behavior change must start with a failing test.
- Each task must produce audit evidence, not just code.
- “Done” for this prototype means: the requested pages render overlays and the JSON clearly shows candidate region boundaries.

## Audit Rules

These audit rules exist to avoid non-code ambiguity:

1. **Scope audit:** No task may modify `src/pdflayoutparser/table_extractor.py`, `pipeline.py`, or CLI behavior.
2. **Behavior audit:** Candidate regions are allowed to be imperfect, but they must be inspectable via JSON and PNG without reading code.
3. **Page audit:** The sample pages `27, 34, 46, 47, 51, 52, 58` are the required review set.
4. **Failure audit:** If the prototype finds zero candidate regions on all review pages, stop and report instead of continuing refinement blindly.
5. **Acceptance audit:** Each task must name its concrete pass/fail command and expected evidence.

### Task 1: Define CandidateRegion data and row-level test fixtures

**Files:**
- Create: `tests/test_text_region_detector.py`
- Create: `src/pdflayoutparser/text_region_detector.py`

- [ ] **Step 1: Write the failing test**

Add tests that define the minimum standalone API and expected behavior:

```python
from pdflayoutparser.text_region_detector import (
    CandidateRegion,
    detect_candidate_regions,
    score_row_structure,
)
from pdflayoutparser.text_visual_debug import TextFragment, VisualRow


def _row(*items):
    fragments = [
        TextFragment(text=text, bbox=(x0, y0, x1, y1))
        for text, x0, y0, x1, y1 in items
    ]
    return VisualRow(
        fragments=fragments,
        bbox=CandidateRegion.bbox_union([fragment.bbox for fragment in fragments]),
    )


def test_score_row_structure_flags_sparse_multi_field_row():
    row = _row(
        ("项目", 20, 30, 70, 42),
        ("123", 180, 30, 220, 42),
        ("456", 300, 30, 340, 42),
    )
    score = score_row_structure(row)
    assert score["fragment_count"] == 3
    assert score["looks_sparse"] is True


def test_detect_candidate_regions_groups_repeated_table_like_rows():
    rows = [
        _row(("项目A", 20, 30, 80, 42), ("10", 180, 30, 205, 42), ("20", 300, 30, 325, 42)),
        _row(("项目B", 20, 50, 80, 62), ("11", 180, 50, 205, 62), ("21", 300, 50, 325, 62)),
        _row(("项目C", 20, 70, 80, 82), ("12", 180, 70, 205, 82), ("22", 300, 70, 325, 82)),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert len(regions[0].rows) == 3


def test_detect_candidate_regions_rejects_dense_prose_rows():
    rows = [
        _row(("这是一段说明文字", 20, 30, 200, 42)),
        _row(("继续说明前述事项", 20, 48, 200, 60)),
        _row(("不会形成表格区域", 20, 66, 200, 78)),
    ]
    assert detect_candidate_regions(rows) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_text_region_detector.py -q`

Expected: FAIL with import or missing symbol errors for `CandidateRegion`, `score_row_structure`, or `detect_candidate_regions`.

- [ ] **Step 3: Write minimal implementation**

Create a first-pass API in `src/pdflayoutparser/text_region_detector.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from pdflayoutparser.models import BBox


@dataclass
class CandidateRegion:
    rows: list
    bbox: BBox
    features: dict
    score: float

    @staticmethod
    def bbox_union(boxes: list[BBox]) -> BBox:
        return BBox(
            min(box.x0 for box in boxes),
            min(box.y0 for box in boxes),
            max(box.x1 for box in boxes),
            max(box.y1 for box in boxes),
        )


def score_row_structure(row) -> dict:
    fragment_count = len(row.fragments)
    widths = [fragment.bbox.x1 - fragment.bbox.x0 for fragment in row.fragments]
    row_width = max(row.bbox.x1 - row.bbox.x0, 1.0)
    coverage = sum(widths) / row_width if row_width else 0.0
    return {
        "fragment_count": fragment_count,
        "coverage": coverage,
        "looks_sparse": fragment_count >= 2 and coverage < 0.75,
    }


def detect_candidate_regions(rows: list) -> list[CandidateRegion]:
    if len(rows) < 2:
        return []
    scores = [score_row_structure(row) for row in rows]
    if sum(1 for score in scores if score["looks_sparse"]) < 2:
        return []
    return [
        CandidateRegion(
            rows=rows,
            bbox=CandidateRegion.bbox_union([row.bbox for row in rows]),
            features={"row_scores": scores},
            score=1.0,
        )
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_text_region_detector.py -q`

Expected: PASS.

- [ ] **Step 5: Audit checkpoint**

Evidence required:
- Test output shows row scoring and candidate grouping API exists.
- No main pipeline files were modified.

- [ ] **Step 6: Commit**

```bash
git add tests/test_text_region_detector.py src/pdflayoutparser/text_region_detector.py
git commit -m "feat: add borderless table region detector skeleton"
```

### Task 2: Add row-pattern features that distinguish prose from table-like runs

**Files:**
- Modify: `tests/test_text_region_detector.py`
- Modify: `src/pdflayoutparser/text_region_detector.py`

- [ ] **Step 1: Write the failing test**

Extend the tests with repeated-column and numeric-column expectations:

```python
def test_detect_candidate_regions_requires_repeated_alignment_pattern():
    rows = [
        _row(("事项说明", 20, 30, 140, 42), ("2021", 260, 30, 300, 42)),
        _row(("更多说明文字", 20, 48, 180, 60), ("2022", 300, 48, 340, 60)),
        _row(("继续段落文本", 20, 66, 170, 78), ("15", 210, 66, 230, 78)),
    ]
    assert detect_candidate_regions(rows) == []


def test_detect_candidate_regions_prefers_rows_with_stable_numeric_columns():
    rows = [
        _row(("项目A", 20, 30, 80, 42), ("10", 180, 30, 205, 42), ("20", 300, 30, 325, 42)),
        _row(("项目B", 20, 50, 80, 62), ("11", 180, 50, 205, 62), ("21", 300, 50, 325, 62)),
        _row(("项目C", 20, 70, 80, 82), ("12", 180, 70, 205, 82), ("22", 300, 70, 325, 82)),
    ]
    region = detect_candidate_regions(rows)[0]
    assert region.features["repeated_alignment_count"] >= 2
    assert region.features["numeric_column_count"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_text_region_detector.py -q`

Expected: FAIL because repeated alignment and numeric-column features are missing or too permissive.

- [ ] **Step 3: Write minimal implementation**

Add feature helpers and tighten grouping:

```python
def _is_numeric_text(text: str) -> bool:
    stripped = text.replace(",", "").replace("%", "").replace(".", "").replace("-", "")
    return bool(stripped) and stripped.isdigit()


def _row_anchor_signature(row) -> list[float]:
    return [round(fragment.bbox.x0 / 10.0) * 10.0 for fragment in row.fragments]


def _count_repeated_alignments(rows: list) -> int:
    guide_hits: dict[float, int] = {}
    for row in rows:
        for anchor in _row_anchor_signature(row):
            guide_hits[anchor] = guide_hits.get(anchor, 0) + 1
    return sum(1 for count in guide_hits.values() if count >= 2)


def _count_numeric_columns(rows: list) -> int:
    column_hits: dict[int, int] = {}
    for row in rows:
        for idx, fragment in enumerate(row.fragments):
            if _is_numeric_text(fragment.text):
                column_hits[idx] = column_hits.get(idx, 0) + 1
    return sum(1 for count in column_hits.values() if count >= 2)


def detect_candidate_regions(rows: list) -> list[CandidateRegion]:
    if len(rows) < 2:
        return []
    scores = [score_row_structure(row) for row in rows]
    sparse_rows = [score for score in scores if score["looks_sparse"]]
    repeated_alignment_count = _count_repeated_alignments(rows)
    numeric_column_count = _count_numeric_columns(rows)
    if len(sparse_rows) < 2:
        return []
    if repeated_alignment_count < 2:
        return []
    region_score = len(sparse_rows) + repeated_alignment_count + numeric_column_count
    return [
        CandidateRegion(
            rows=rows,
            bbox=CandidateRegion.bbox_union([row.bbox for row in rows]),
            features={
                "row_scores": scores,
                "repeated_alignment_count": repeated_alignment_count,
                "numeric_column_count": numeric_column_count,
            },
            score=float(region_score),
        )
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_text_region_detector.py -q`

Expected: PASS.

- [ ] **Step 5: Audit checkpoint**

Evidence required:
- Dense prose-like rows with incidental right-side numbers are rejected.
- Stable repeated table-like rows still produce one region.

- [ ] **Step 6: Commit**

```bash
git add tests/test_text_region_detector.py src/pdflayoutparser/text_region_detector.py
git commit -m "feat: score repeated row alignment for region detection"
```

### Task 3: Split rows into contiguous candidate regions instead of treating the whole page as one block

**Files:**
- Modify: `tests/test_text_region_detector.py`
- Modify: `src/pdflayoutparser/text_region_detector.py`

- [ ] **Step 1: Write the failing test**

Add a test that mixes prose and table rows on one page:

```python
def test_detect_candidate_regions_keeps_only_contiguous_table_run():
    rows = [
        _row(("正文说明", 20, 20, 120, 32)),
        _row(("继续正文", 20, 38, 120, 50)),
        _row(("项目A", 20, 80, 80, 92), ("10", 180, 80, 205, 92), ("20", 300, 80, 325, 92)),
        _row(("项目B", 20, 98, 80, 110), ("11", 180, 98, 205, 110), ("21", 300, 98, 325, 110)),
        _row(("项目C", 20, 116, 80, 128), ("12", 180, 116, 205, 128), ("22", 300, 116, 325, 128)),
        _row(("结尾说明", 20, 170, 120, 182)),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert len(regions[0].rows) == 3
    assert regions[0].bbox.y0 >= 80
    assert regions[0].bbox.y1 <= 128
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_text_region_detector.py -q`

Expected: FAIL because the current implementation treats the entire row list as one region.

- [ ] **Step 3: Write minimal implementation**

Change detection from whole-page scoring to contiguous-run scoring:

```python
def _row_is_candidate(row) -> bool:
    score = score_row_structure(row)
    return score["looks_sparse"]


def _group_contiguous_runs(rows: list) -> list[list]:
    runs: list[list] = []
    current: list = []
    for row in rows:
        if _row_is_candidate(row):
            current.append(row)
            continue
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return [run for run in runs if len(run) >= 2]


def detect_candidate_regions(rows: list) -> list[CandidateRegion]:
    regions: list[CandidateRegion] = []
    for run in _group_contiguous_runs(rows):
        repeated_alignment_count = _count_repeated_alignments(run)
        numeric_column_count = _count_numeric_columns(run)
        if repeated_alignment_count < 2:
            continue
        scores = [score_row_structure(row) for row in run]
        regions.append(
            CandidateRegion(
                rows=run,
                bbox=CandidateRegion.bbox_union([row.bbox for row in run]),
                features={
                    "row_scores": scores,
                    "repeated_alignment_count": repeated_alignment_count,
                    "numeric_column_count": numeric_column_count,
                },
                score=float(len(run) + repeated_alignment_count + numeric_column_count),
            )
        )
    return regions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_text_region_detector.py -q`

Expected: PASS.

- [ ] **Step 5: Audit checkpoint**

Evidence required:
- The detector returns region-local bboxes, not page-wide bboxes.
- Prose rows before and after the table-like run are excluded.

- [ ] **Step 6: Commit**

```bash
git add tests/test_text_region_detector.py src/pdflayoutparser/text_region_detector.py
git commit -m "feat: detect contiguous borderless table regions"
```

### Task 4: Connect region detection to the existing debug visualization layer

**Files:**
- Modify: `tests/test_text_visual_debug.py`
- Modify: `src/pdflayoutparser/text_visual_debug.py`
- Modify: `src/pdflayoutparser/text_region_detector.py`

- [ ] **Step 1: Write the failing test**

Extend the existing debug rendering test:

```python
def test_render_text_debug_pages_exports_candidate_regions(tmp_dir):
    pdf_path = Path(tmp_dir) / "text_region_demo.pdf"
    output_dir = Path(tmp_dir) / "out"

    doc = fitz.open()
    try:
        page = doc.new_page(width=360, height=220)
        page.insert_text((20, 40), "项目A")
        page.insert_text((180, 40), "10")
        page.insert_text((300, 40), "20")
        page.insert_text((20, 58), "项目B")
        page.insert_text((180, 58), "11")
        page.insert_text((300, 58), "21")
        doc.save(str(pdf_path))
    finally:
        doc.close()

    outputs = render_text_debug_pages(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        page_numbers=[1],
        dpi=120,
    )

    payload = json.loads(Path(outputs[0]["json_path"]).read_text(encoding="utf-8"))
    assert "candidate_regions" in payload
    assert len(payload["candidate_regions"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_text_visual_debug.py::test_render_text_debug_pages_exports_candidate_regions -q`

Expected: FAIL because the debug JSON does not yet include candidate region data.

- [ ] **Step 3: Write minimal implementation**

Import the detector and include region export/drawing:

```python
from pdflayoutparser.text_region_detector import detect_candidate_regions


def render_text_debug_pages(...):
    ...
    rows = build_visual_rows(fragments)
    candidate_regions = detect_candidate_regions(rows)
    _draw_debug_boxes(page, word_items, fragments, rows, candidate_regions)
    _write_debug_json(
        json_path,
        word_items,
        fragments,
        rows,
        candidate_regions,
        page_number,
    )
```

Use a fourth color only for candidate-region outlines:

```python
for region in candidate_regions:
    page.draw_rect(
        fitz.Rect(region.bbox.x0, region.bbox.y0, region.bbox.x1, region.bbox.y1),
        color=(0.62, 0.20, 0.89),
        width=2.2,
        overlay=True,
    )
```

And export:

```python
"candidate_regions": [
    {
        "bbox": _bbox_to_dict(region.bbox),
        "score": region.score,
        "features": region.features,
        "row_count": len(region.rows),
    }
    for region in candidate_regions
],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_text_visual_debug.py -q`

Expected: PASS.

- [ ] **Step 5: Audit checkpoint**

Evidence required:
- PNG overlays show row boxes and region boxes separately.
- JSON contains candidate region scores/features without opening source code.

- [ ] **Step 6: Commit**

```bash
git add tests/test_text_visual_debug.py src/pdflayoutparser/text_visual_debug.py src/pdflayoutparser/text_region_detector.py
git commit -m "feat: visualize candidate table regions"
```

### Task 5: Run the sample-page prototype and capture review evidence

**Files:**
- Modify: `debug_text_visual.py`

- [ ] **Step 1: Write the failing test**

No unit test for the script entrypoint is needed. Instead, define an explicit manual audit target inside the script:

```python
page_numbers = [27, 34, 46, 47, 51, 52, 58]
```

This task is considered failing until the script exports candidate-region data for all required pages.

- [ ] **Step 2: Run script to verify current behavior is incomplete**

Run: `python debug_text_visual.py`

Expected: the output may exist, but there is no region-level summary yet or no candidate-region count in the summary JSON.

- [ ] **Step 3: Write minimal implementation**

Update the script summary and terminal output:

```python
outputs = render_text_debug_pages(...)

summary = {
    "pdf_path": str(pdf_path),
    "page_numbers": page_numbers,
    "pages": outputs,
}

with open(summary_path, "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=2)

for item in outputs:
    print(
        f"page {item['page_number']}: "
        f"words={item['word_count']} "
        f"fragments={item['fragment_count']} "
        f"rows={item['row_count']} "
        f"regions={item['candidate_region_count']}"
    )
```

- [ ] **Step 4: Run script to verify review evidence exists**

Run: `python debug_text_visual.py`

Expected: terminal output prints region counts for pages `27, 34, 46, 47, 51, 52, 58`, and `vis_text_debug/summary.json` contains a per-page `candidate_region_count`.

- [ ] **Step 5: Audit checkpoint**

Required manual audit artifacts:
- `vis_text_debug/text-debug-page-027.png`
- `vis_text_debug/text-debug-page-034.png`
- `vis_text_debug/text-debug-page-046.png`
- `vis_text_debug/text-debug-page-047.png`
- `vis_text_debug/text-debug-page-051.png`
- `vis_text_debug/text-debug-page-052.png`
- `vis_text_debug/text-debug-page-058.png`
- `vis_text_debug/summary.json`

Review questions:
- Does page `47` produce a region around the two main borderless tables?
- Does page `52` produce a region covering the large wide table body?
- Does page `46` avoid large false-positive region boxes over prose?

Stop condition:
- If all pages produce zero candidate regions, stop and report instead of tuning blindly.

- [ ] **Step 6: Commit**

```bash
git add debug_text_visual.py vis_text_debug/summary.json
git commit -m "feat: export borderless table region prototype review outputs"
```

## Self-Review

### Spec coverage

- `words -> fragments -> rows` is already in place and reused in Tasks 1-5.
- `rows -> candidate regions` is implemented and tightened in Tasks 1-3.
- Overlay PNG and JSON review workflow is covered in Tasks 4-5.
- “No pipeline integration yet” is enforced by scope audit rules.

### Placeholder scan

- No `TODO` / `TBD` placeholders remain.
- Every executable step includes a concrete command or code target.
- Manual audit items name exact output files and exact review questions.

### Type consistency

- `CandidateRegion`, `score_row_structure`, and `detect_candidate_regions` are introduced first and reused consistently.
- `render_text_debug_pages()` remains the single export surface for debug rendering.

## Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-14-borderless-table-region-prototype.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
