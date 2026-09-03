# Language-Aware Wireless Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route wireless table extraction by page language so zebra-background extraction is English-only.

**Architecture:** `TableExtractor.extract()` detects the page language once and passes it through `_extract_model_tables()` to `WirelessTableExtractor.extract()`. English pages retain the zebra-first fallback chain; Chinese and mixed pages go directly to text alignment. Wired extraction remains unchanged.

**Tech Stack:** Python, PyMuPDF, pytest.

## Global Constraints

- Keep wired table extraction behavior unchanged.
- Do not use zebra-background extraction for `zh` or `mixed` pages.
- Preserve English zebra extraction and text-alignment fallback.
- Add regression tests before production changes.

---

### Task 1: Add language-routing regression tests

**Files:**
- Modify: `tests/test_table_extractor.py`
- Modify: `src/hexai_pdf_parser/tables/table_extractor.py`
- Modify: `src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py`

**Interfaces:**
- `TableExtractor._extract_model_tables(page, wired_tables=None, page_language=None)` passes the detected language to wireless extraction.
- `WirelessTableExtractor.extract(page, table_bbox=None, confidence=None, page_language=None)` selects zebra or text alignment based on language.

- [ ] **Step 1: Write a failing test** asserting a Chinese ML region calls text alignment and does not call zebra.
- [ ] **Step 2: Write a failing test** asserting an English ML region still calls zebra first.
- [ ] **Step 3: Run the focused tests and confirm they fail because language is not routed.
- [ ] **Step 4: Implement the smallest signature and branch changes.
- [ ] **Step 5: Run both tests and confirm they pass.
- [ ] **Step 6: Run existing table and wired extractor tests.
- [ ] **Step 7: Update `changes.md` with the language-routing behavior.
- [ ] **Step 8: Run `git diff --check` and commit only the feature files and tests.
