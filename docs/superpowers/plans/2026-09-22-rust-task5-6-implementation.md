# Task 5–6 Shadow Page Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在五个代表性真实 PDF 页面上完成两条无线结构高层入口的 Python/shadow/Rust 字段级验收，并完成 Task 6 的最终迁移审计。

**Architecture:** 新增纯 Python acceptance normalizer，统一把 `WirelessRecovery`、`Table`、`Cell`、region recovery 和 routing diagnostics 转成稳定的 owned JSON。新增一次性 CLI 在同一 PDF、同一 0-based 页集合上分别运行 `python`、`shadow`、`rust`，写入独立 JSON/manifest/overlay PNG，并由 normalizer 比较 page/table/cell/span/empty-slot/occupancy/diagnostic 字段。默认 Python 路由与现有 fallback 不变；只有差异报告明确指向 bounded defect 时才修改生产适配器。

**Tech Stack:** Python 3.12、PyMuPDF、pytest、现有 `hexai_pdf_parser` recovery APIs、Rust PyO3 extension、PowerShell、PNG overlay inspection。

## Global Constraints

- 输入 PDF：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`。
- 页面索引固定为 0-based：`184,188,189,191,192`。
- 三种 mode 必须是 `python`、`shadow`、`rust`；shadow 始终返回 Python 结果。
- 两条入口必须覆盖：`recover_cells_from_region()` 与 `recover_wireless_tables()`。
- 默认 Python route、Rust fallback、已有用户 dirty 文件不改变。
- 中文/混合无线结构只消费 PageSnapshot/native span/atom/grid/Cell，不回读 `page.get_text("words")`，不调用 `extract_zebra()` 或 legacy `_rebuild_text_aligned_table()`。
- 所有未解释差异必须记录为 `accepted`、`requires_adaptation`、`defect` 或 `unsupported`，禁止 broad ignore 或 wildcard。
- 输出根目录固定为 `D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`，不得复用旧输出目录。

---

### Task 5A: Field-level acceptance normalizer

**Files:**
- Create: `src/hexai_pdf_parser/debug/rust_task5_acceptance.py`
- Create: `tests/test_rust_wireless_shadow_differential.py`
- Read: `src/hexai_pdf_parser/core/models.py`, `src/hexai_pdf_parser/tables/wireless_table_recovery.py`, `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py`

**Interfaces:**
- Consumes: `WirelessRecovery`, `Table`, `Cell`, `(rows, cols, list[Cell])`, routing diagnostics and page index.
- Produces: JSON-safe `normalize_recovery()` / `normalize_region_result()` mappings and deterministic `compare_normalized()` mismatch records.

- [ ] **Step 1: Write the failing normalizer tests.** Add synthetic `BBox`, `Cell`, `Table`, and `WirelessRecovery` values proving that normalization preserves cell text, bbox, coordinates, spans, empty slots, occupancy coverage and diagnostics. Add a mismatch test whose expected record identifies `layer="tables"`, `field="rows"`, Python value and Rust value. Add a mode contract test proving `shadow` returns the Python value while a mismatch diagnostic remains observable.

- [ ] **Step 2: Run the tests and confirm RED.**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.12 -m pytest -q tests/test_rust_wireless_shadow_differential.py
```

Expected: collection or import failure because `rust_task5_acceptance` and its normalizer interfaces do not exist yet.

- [ ] **Step 3: Implement the smallest pure normalizer.** Define these exact functions:

```python
def normalize_recovery(recovery: WirelessRecovery, page_index: int, mode: str) -> dict[str, Any]: ...
def normalize_region_result(result: tuple[int, int, list[Cell]], region: BBox, page_index: int, mode: str) -> dict[str, Any]: ...
def compare_normalized(python_value: Any, candidate_value: Any, *, entry: str) -> list[dict[str, Any]]: ...
```

Each table record must contain `source`, `rows`, `cols`, `bbox`, ordered cells and occupancy summary. Each Cell record must contain `row`, `col`, `rowspan`, `colspan`, `text`, and `bbox`. Occupancy summary must contain `covered_slots`, `missing_slots`, `duplicate_slots`, `conflicts`, and per-slot owner IDs. Diagnostics must be normalized by `status`, `path`, `field`, `classification`, `error_type`, and `message`, while traceback IDs and nondeterministic values are excluded explicitly.

- [ ] **Step 4: Run the normalizer tests GREEN.**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.12 -m pytest -q tests/test_rust_wireless_shadow_differential.py
```

Expected: all normalizer and mode-contract tests pass.

### Task 5B: Three-mode real-page runner

**Files:**
- Create: `scripts/run_task5_shadow_acceptance.py`
- Modify: `tests/test_rust_wireless_shadow_differential.py`
- Read: `src/hexai_pdf_parser/tables/wireless_table_recovery.py::export_wireless_debug`

**Interfaces:**
- Consumes: `--pdf`, `--pages`, `--output`, `--dpi`; existing page recovery functions.
- Produces: `<output>/<mode>/page-<index>.json`, `<output>/<mode>/page-<index>-wireless.png`, `<output>/<mode>/manifest.json`, and `<output>/comparison/comparison.json`.

- [ ] **Step 1: Add runner contract tests before implementation.** Test the runner’s pure page payload builder with a synthetic recovery and assert that manifest records mode, page index, input path/hash fields, table count, source, rows, cols, bbox, region results, occupancy conflicts and diagnostics. Test that page-specific `PDF_RUST_MODE_*` variables are removed before setting the requested global mode, so all three modes are actually exercised.

- [ ] **Step 2: Run runner contract tests and confirm RED.**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.12 -m pytest -q tests/test_rust_wireless_shadow_differential.py
```

Expected: failures for missing runner payload helpers or missing manifest fields.

- [ ] **Step 3: Implement the runner.** For each requested page, open the same PDF page once, clear routing diagnostics, run `recover_wireless_tables(page)` in each mode, and serialize the normalized page result. Use Python mode’s accepted table bboxes as the stable region set, then run `recover_cells_from_region(page, bbox)` for every mode on those same regions. Call `export_wireless_debug()` into the mode directory to produce the non-mutating overlay PNG. Write input SHA256, git commit, page language from `detect_page_language(page)`, page index, mode, table records, region records, routing diagnostics and absolute artifact paths to each manifest. Compare shadow and rust payloads against Python with `compare_normalized()` and write deterministic `comparison/comparison.json` plus a summary count.

- [ ] **Step 4: Run runner contract tests GREEN.**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.12 -m pytest -q tests/test_rust_wireless_shadow_differential.py
```

Expected: all normalizer, runner contract and mode-isolation tests pass.

### Task 5C: Representative page export and structural verification

**Files:**
- Create: `docs/superpowers/rust-migration/sprints/sprint-007.md`
- Create: `docs/superpowers/rust-migration/evaluations/sprint-007.md`
- Modify: `changes.md`
- Modify: `docs/superpowers/rust-migration/current-status.md`
- Modify: `.superpowers/sdd/progress.md`
- Output only: `D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`

- [ ] **Step 1: Run the five-page three-mode export.**

```powershell
$env:PYTHONPATH='D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan\src'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.12 scripts/run_task5_shadow_acceptance.py `
  --pdf 'D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf' `
  --pages 184,188,189,191,192 `
  --output 'D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922' `
  --dpi 160
```

Expected: 15 page-mode payloads plus 15 mode/page overlay PNGs and a comparison report. Any Rust fallback, root mismatch or unclassified field difference is a repair item, not a pass.

- [ ] **Step 2: Verify the generated JSON/manifest structurally.** Assert five page indexes in every mode, one manifest per mode, matching input SHA256, matching page language, table and region records, valid absolute paths, zero unexplained occupancy conflicts, and identical shadow-return payloads to Python. Record every remaining Rust difference with an explicit classification in `comparison/comparison.json`.

- [ ] **Step 3: Inspect PNGs visually.** Use `view_image` on representative Python, shadow and Rust overlays for all five pages or on a contact sheet generated only from the new output directory. Check table boundary, adjacent-table separation, group/leaf header lines, empty-slot boxes, row/column count and wrapped-field placement. If a PNG shows a bounded Rust defect, add the smallest regression test before touching production code.

- [ ] **Step 4: If a bounded defect exists, repair test-first.** Add a failing fixture/test for the exact page/field, run the focused test RED, modify only `recoverer.py` or `wireless_table_recovery.py` when the defect belongs to that adapter, rerun the focused test GREEN, rebuild the Rust extension if needed, rerun all five pages, and update the mismatch classification. If the difference is not a confirmed defect, preserve it as a decision-needed record and do not weaken the comparator.

### Task 6: Final completion audit and handoff

**Files:**
- Modify: `docs/superpowers/rust-migration/evaluations/sprint-007.md`
- Modify: `docs/superpowers/rust-migration/current-status.md`
- Modify: `.superpowers/sdd/progress.md`
- Modify: `changes.md`

- [ ] **Step 1: Run the final verification matrix.**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
py -3.12 -m pytest -q tests/test_rust_wireless_shadow_differential.py tests/test_rust_wireless_structure_differential.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_recoverer.py tests/test_rust_migration_routing.py
cargo test --lib
cargo check
git diff --check
```

- [ ] **Step 2: Audit all requirements against evidence.** Confirm the five pages have JSON/PNG paths, both high-level entrances were exercised, shadow returned Python, Rust diagnostics are preserved, no unclassified differences remain, default mode is Python, fallback behavior remains, and occupancy is exact. Confirm the two pre-existing dirty test files remain uncommitted and no unrelated file is staged.

- [ ] **Step 3: Write the Chinese Task 5/6 evaluation.** Include input PDF, 0-based pages, language, table count/source/rows/cols/bbox summary, artifact paths, comparison counts/classifications, visual checks, commands and any known limitation. Mark Task 5/6 complete only if the evidence satisfies every acceptance item; otherwise record the exact remaining decision or repair item.

- [ ] **Step 4: Commit only Task 5/6 implementation and records.** Do not stage `tests/test_wireless_extractor_split.py` or `tests/test_wireless_structure_recoverer.py` unless a new change is explicitly required and separately attributable.
