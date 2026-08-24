# 机构查询记录表恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or superpowers:subagent-driven-development) to implement this plan task-by-task.

**Goal:** Restore personal-credit institution query records into one four-column logical table per contiguous report section, including wrapped institution names and page continuation.

**Architecture:** Keep generic table detection unchanged. Add a personal-credit post-processing pass that recognizes query-table candidates, rebuilds rows against a stable four-column skeleton, merges continuation fragments, and exposes a page-independent logical table result through the existing document output path.

**Tech Stack:** Python, PyMuPDF, pytest, existing `Table`/`Cell`/`BBox` models.

## Global Constraints

- Only personal-credit query-record handling may change.
- No new dependency.
- Preserve existing behavior for non-query tables and prose.
- Tests must fail before production implementation and pass afterward.

---

### Task 1: Add failing query-record regression tests

**Files:**
- Modify: `tests/test_table_extractor.py`
- Test fixtures: `PDFsam_merge1.pdf`, `PDFsam_merge3.pdf`

- [ ] Add tests that parse each fixture and assert one logical query table, expected record count, and wrapped institution text.
- [ ] Run the focused tests and confirm they fail against the current split output.

### Task 2: Implement page-local query-table recovery

**Files:**
- Modify: `src/hexai_pdf_parser/personal_credit_report.py`

- [ ] Add helpers to recognize the four query headers and classify numeric record starts.
- [ ] Merge adjacent query candidates with compatible column positions.
- [ ] Fold no-number institution continuation cells into the preceding record.
- [ ] Preserve table coordinates and row/column indices.
- [ ] Run the focused tests.

### Task 3: Implement cross-page query-table merge

**Files:**
- Modify: `src/hexai_pdf_parser/personal_credit_report.py`
- Modify: `src/hexai_pdf_parser/pipeline.py` only if the existing page model requires document-level merge

- [ ] Merge a page-start query continuation into the previous logical query table when column geometry and numbering are compatible.
- [ ] Keep one header and append rows with stable indices.
- [ ] Run both fixture tests and the existing table test module.

### Task 4: Verify and review

- [ ] Run focused fixture tests.
- [ ] Run `pytest tests/test_table_extractor.py`.
- [ ] Re-run the demo parser and inspect resulting table block counts and record numbers.
- [ ] Review the diff for unrelated changes.
