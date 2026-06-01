# Long Horizontal Line Table Region Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect borderless table-like regions that are introduced by a long horizontal separator line, so header rows and body rows on pages like `page-029` are promoted into a table instead of remaining prose.

**Architecture:** Keep the existing line-based table extractor unchanged for true grid tables. Add a new separator-driven text-region path that activates only when a visible horizontal line spans most of the usable page width, is thin enough to behave like a separator, and is followed by a stable multi-row aligned text block. The new path should return a `CandidateRegion` that is then converted through the existing text-alignment table builder, so we reuse the current cell construction and text assignment code.

**Tech Stack:** Python 3.10+, PyMuPDF (`fitz`), `pytest`.

---

### Task 1: Add a failing regression test for long-line-driven text tables

**Files:**
- Modify: `tests/test_text_region_detector.py`
- Modify: `tests/test_table_extractor.py`

- [ ] **Step 1: Write the failing test**

Add a unit test in `tests/test_text_region_detector.py` that constructs a synthetic row set with a long separator between a short header span and a stable multi-row body. Assert that the new separator-driven detector returns one candidate region spanning both sides of the separator.

Add an integration test in `tests/test_table_extractor.py` that creates a synthetic PDF with:
- a thin horizontal line that spans most of the page width,
- a short header block above the line,
- a multi-row aligned text block below the line.

Assert that `TableExtractor._extract_via_text_alignment(page)` returns at least one table with the header text included in the first rows of the detected table.

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
pytest tests/test_text_region_detector.py -v
pytest tests/test_table_extractor.py -k long_horizontal -v
```

Expected: the new tests fail because the separator-driven region detector does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement a small separator-driven region detector in `src/hexai_pdf_parser/text_region_detector.py` that:
- recognizes long, thin horizontal separators by width ratio and maximum stroke thickness,
- finds the aligned text rows immediately below the separator,
- includes a small header span above the separator when it is structurally linked to the body rows,
- returns a `CandidateRegion` only when the combined rows have stable repeated alignment.

Hook this detector into `TableExtractor._detect_text_regions()` in `src/hexai_pdf_parser/table_extractor.py` before the existing `detect_candidate_regions()` call, so separator-driven regions are merged into the same downstream table-building path.

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pytest tests/test_text_region_detector.py -v
pytest tests/test_table_extractor.py -k long_horizontal -v
```

Expected: both tests pass, and the new separator path produces a `text_alignment` table without breaking existing table extraction tests.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-05-28-long-horizontal-line-table-region.md tests/test_text_region_detector.py tests/test_table_extractor.py src/hexai_pdf_parser/text_region_detector.py src/hexai_pdf_parser/table_extractor.py
git commit -m "feat: detect long separator driven text tables"
```

