# Camelot Stream Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone demo that runs Camelot `stream` mode on selected PDF pages, exports a visual preview, and prints a compact table summary for wireless-table comparison.

**Architecture:** Keep this strictly as a sidecar script under `scripts/` so it does not affect the main PDFLayoutParser pipeline. Add a tiny helper module only if needed for testable Camelot output normalization, and keep the demo focused on one responsibility: run Camelot stream, save an annotated preview image, and print/export the table structure.

**Tech Stack:** Python, `camelot-py`, `PyMuPDF`, `pytest`

---

### Task 1: Add a focused regression test for the Camelot demo contract

**Files:**
- Create: `tests/test_camelot_stream_demo.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

def test_camelot_demo_requires_preview_and_summary(tmp_dir):
    pdf_path = Path(tmp_dir) / "demo.pdf"
    # Build a tiny PDF with a simple text table.
    # The demo should produce a preview PNG and a JSON summary file.
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_camelot_stream_demo.py -v`
Expected: fail because the demo script and helper do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement the smallest reusable entry point needed by the demo, likely in:
`src/hexai_pdf_parser/camelot_stream_demo.py`

The helper should:
```python
def extract_camelot_stream_summary(pdf_path: str, page: int) -> dict:
    ...
```

and return a JSON-serializable structure with:
- `page`
- `table_count`
- `tables` with row/col counts and sample text

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_camelot_stream_demo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_camelot_stream_demo.py src/hexai_pdf_parser/camelot_stream_demo.py
git commit -m "feat: add camelot stream demo helper"
```

### Task 2: Add the standalone Camelot preview script

**Files:**
- Create: `scripts/test_camelot_stream.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing test**

Add a script-level smoke test that imports the demo helper and verifies it can write:
- an annotated preview PNG
- a JSON summary

Test content:
```python
def test_demo_writes_preview_and_summary(tmp_dir):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_camelot_stream_demo.py -v`
Expected: fail until the script entrypoint exists.

- [ ] **Step 3: Write minimal implementation**

Implement the script with:
- CLI args: `pdf_path`, `--page`, `--output`
- Camelot `read_pdf(..., flavor="stream")`
- preview export using Camelot plot or a fallback overlay if available
- JSON summary export next to the preview

Add the optional dependency:
```toml
[project.optional-dependencies]
demo = [
    "camelot-py[cv]>=0.11.0",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_camelot_stream_demo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/test_camelot_stream.py pyproject.toml src/hexai_pdf_parser/camelot_stream_demo.py tests/test_camelot_stream_demo.py
git commit -m "feat: add camelot stream demo script"
```

### Task 3: Verify the demo on a real PDF page

**Files:**
- No code changes expected

- [ ] **Step 1: Run the demo on a representative page**

Run:
```bash
python scripts/test_camelot_stream.py "D:\\codes\\PDFLayoutParser\\152590_20230428_N7ZK_0.pdf" --page 77 --output "D:\\codes\\PDFLayoutParser\\output\\camelot_stream_demo"
```

- [ ] **Step 2: Inspect the output**

Confirm:
- preview PNG is written
- JSON summary is written
- table boundaries look reasonable for a wireless/weak-line table

- [ ] **Step 3: Commit any follow-up fixes**

If the preview or summary shape needs adjustment, patch the helper and re-run the smoke test before finishing.

