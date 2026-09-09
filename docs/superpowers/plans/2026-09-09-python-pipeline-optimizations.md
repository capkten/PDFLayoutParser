# Python 管线性能优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有 Python API、表格结构语义和输出文件契约的前提下，减少页面级 PyMuPDF 重复调用、重复打开 PDF 和重复初始化表格检测器的开销。

**Architecture:** 页面处理仍由 Python/PyMuPDF 完成。每次页面处理使用一个 worker-local `fitz.Document`、一个可复用的 `TableExtractor` 和一个页面读取缓存代理；Rust 不在本次范围内。解析阶段、页面渲染、图片提取和表格可视化共享同一 worker-local 文档与页面句柄，但公共的按路径 API 保持不变。

**Tech Stack:** Python 3.7+、PyMuPDF、concurrent.futures、pytest。

## Global Constraints

- 保留 `PDFParser`、`Pipeline`、CLI 的现有参数和返回结构。
- 中文/混合无线表格仍只消费 native span/atom/grid，不新增 `page.get_text("words")` 回读路径。
- 不改变 `Table`/`Cell` 的文本、坐标、来源、行列跨度和空槽位语义。
- PyMuPDF 文档不跨线程共享；线程后端继续使用独立文档，进程后端使用进程内文档。
- 每个优化行为必须先有失败测试，再写生产代码。
- 页面级验证必须使用独立输出目录，同时检查 JSON 和 PNG。

---

### Task 1: 页面读取缓存与一次性规范化

**Files:**
- Create: `src/hexai_pdf_parser/core/page_cache.py`
- Modify: `src/hexai_pdf_parser/core/pipeline.py`
- Modify: `src/hexai_pdf_parser/tables/table_extractor.py:607`
- Modify: `src/hexai_pdf_parser/debug/table_visualizer.py:376`
- Test: `tests/test_page_cache.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- `CachedPage(page).get_text(*args, **kwargs)` and `.get_drawings(*args, **kwargs)` cache identical read calls and forward all other attributes/methods to the wrapped page.
- `TableExtractor.extract(page, *, page_already_normalized=False)` skips only its internal normalization when the caller has already normalized the page.
- `render_table_visualization(..., page_already_normalized=False)` preserves the existing path-based behavior and can skip normalization for a supplied, already-normalized page.

- [ ] **Step 1: Write the failing tests**

  Add a `CountingPage` test double that records `get_text` and `get_drawings` calls. Assert that two identical calls through `CachedPage` invoke the wrapped page once and that different arguments remain separate cache entries. Add a test that monkeypatches `table_extractor.normalize_page_rotation`, calls `TableExtractor.extract(page, page_already_normalized=True)`, and verifies the normalizer is not called.

- [ ] **Step 2: Run tests to verify they fail**

  Run:

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_page_cache.py -q
  ```

  Expected: collection or assertion failures because `CachedPage` and the new keyword argument do not exist.

- [ ] **Step 3: Write the minimal implementation**

  Implement a small forwarding proxy with per-page caches keyed by positional and keyword arguments. In `_run_page_pipeline`, normalize the real `fitz.Page` once, pass a `CachedPage` to text/table extraction, and pass `page_already_normalized=True` to `TableExtractor` and page-based visualization. Keep direct calls unchanged by defaulting the new flags to `False`.

- [ ] **Step 4: Run focused tests**

  Run:

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_page_cache.py tests/test_pipeline.py -q
  ```

  Expected: all newly added cache tests and all unrelated pipeline tests pass; the previously known hybrid wired-table failure remains separately identified if present.

- [ ] **Step 5: Commit**

  ```powershell
  git add src/hexai_pdf_parser/core/page_cache.py src/hexai_pdf_parser/core/pipeline.py src/hexai_pdf_parser/tables/table_extractor.py src/hexai_pdf_parser/debug/table_visualizer.py tests/test_page_cache.py tests/test_pipeline.py
  git commit -m "perf: cache repeated page reads"
  ```

### Task 2: 复用 worker-local 页面句柄完成渲染和图片提取

**Files:**
- Modify: `src/hexai_pdf_parser/extractors/image_extractor.py`
- Modify: `src/hexai_pdf_parser/writers/render_engine.py`
- Modify: `src/hexai_pdf_parser/core/pipeline.py`
- Test: `tests/test_image_extractor.py`
- Test: `tests/test_render_engine.py`

**Interfaces:**
- Add `ImageExtractor.extract_page(document, page_index, page=None, *, page_already_normalized=False)`; existing `extract(file_path, page_index)` opens and delegates to it.
- Add `RenderEngine.render_page(document, page_index, page=None, page_type=None, *, page_already_normalized=False)`; existing `render(file_path, page_index, page_type=None)` opens and delegates to it.

- [ ] **Step 1: Write the failing tests**

  Add tests that create an in-memory document, call the new page-based methods, and verify the same image/render results are written. Patch the normalizer in each module and verify `page_already_normalized=True` avoids a second call.

- [ ] **Step 2: Run tests to verify they fail**

  Run:

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_image_extractor.py tests/test_render_engine.py -q
  ```

  Expected: failures because the page-based methods do not exist.

- [ ] **Step 3: Write the minimal implementation**

  Move the existing extraction/render body into the page-based methods, preserve file-path methods as compatibility wrappers, and change `_run_page_pipeline` to pass the current worker-local document/page for image extraction and rendering. Pass the original `fitz.Page` to `render_table_visualization` so its existing `isinstance` branch remains valid.

- [ ] **Step 4: Run focused tests**

  Run:

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_image_extractor.py tests/test_render_engine.py tests/test_pipeline.py -q
  ```

- [ ] **Step 5: Commit**

  ```powershell
  git add src/hexai_pdf_parser/extractors/image_extractor.py src/hexai_pdf_parser/writers/render_engine.py src/hexai_pdf_parser/core/pipeline.py tests/test_image_extractor.py tests/test_render_engine.py tests/test_pipeline.py
  git commit -m "perf: reuse worker-local PDF pages for outputs"
  ```

### Task 3: 复用表格提取器和进程 worker 文档

**Files:**
- Modify: `src/hexai_pdf_parser/core/pipeline.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_pdf_parser.py`

**Interfaces:**
- `_run_page_pipeline(..., table_extractor=None, table_extractor_factory=None)` uses a supplied extractor instance when present.
- `_process_page_process_worker(...)` uses process-global worker resources keyed by PDF path and extractor configuration, rather than opening a new document for every page.
- Sequential processing creates one extractor per run; thread processing uses thread-local extractors; process processing uses process-local extractors.

- [ ] **Step 1: Write the failing tests**

  Add a test with a counting extractor class and two sequential pages asserting the extractor is constructed once and its `extract` method is called twice. Add a process-backend regression assertion that the process worker resource helper returns the same document/extractor for two pages with the same configuration and replaces them when the PDF path changes.

- [ ] **Step 2: Run tests to verify they fail**

  Run:

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_pipeline.py::test_pipeline_reuses_table_extractor_per_sequential_run tests/test_pipeline.py::test_process_worker_reuses_document_and_extractor -q
  ```

  Expected: failures because each page currently creates a new extractor and the process worker opens the PDF on every invocation.

- [ ] **Step 3: Write the minimal implementation**

  Add a thread-local extractor accessor, pass one sequential extractor through the page loop, and add process-global document/extractor state with explicit replacement and cleanup when configuration changes. Keep `_PROCESS_POOL` intact for existing callers and tests. Do not share a `fitz.Document` between threads.

- [ ] **Step 4: Run focused tests**

  Run:

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_pipeline.py tests/test_pdf_parser.py::test_parse_with_process_backend -q
  ```

  Expected: new reuse tests and existing process/backend tests pass, with only the pre-existing unrelated failures if they are selected.

- [ ] **Step 5: Commit**

  ```powershell
  git add src/hexai_pdf_parser/core/pipeline.py tests/test_pipeline.py tests/test_pdf_parser.py
  git commit -m "perf: reuse table extractors across pages"
  ```

### Task 4: 选页过滤和全量验证

**Files:**
- Modify: `src/hexai_pdf_parser/core/pipeline.py`
- Test: `tests/test_pipeline.py`
- Optional benchmark output: `perf/python-pipeline-20260909/`

- [ ] **Step 1: Write the failing test**

  Add a test passing duplicate and unordered `page_indices` and assert processing occurs once per selected page while the returned `Document.pages` order and original indices remain unchanged.

- [ ] **Step 2: Run the test to verify it fails**

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_pipeline.py::test_pipeline_deduplicates_page_indices_without_renumbering -q
  ```

- [ ] **Step 3: Write the minimal implementation**

  Normalize page selection once into a set for membership checks, retain PDF page order for processing, and do not change the returned document page count or page indices.

- [ ] **Step 4: Run verification**

  ```powershell
  $env:PYTHONPATH = "src"
  python -m pytest tests/test_page_cache.py tests/test_pipeline.py tests/test_pdf_parser.py tests/test_image_extractor.py tests/test_render_engine.py -q
  python -m pytest tests/test_wireless_structure_recoverer.py tests/test_wireless_extractor_split.py tests/test_wired_table_extractor.py -q
  ```

  Then run one representative PDF page with `backend=sequential` into a new output directory and compare its page JSON, table JSON, table PNG, and `timings.json` against the baseline.

- [ ] **Step 5: Commit**

  ```powershell
  git add src/hexai_pdf_parser/core/pipeline.py tests/test_pipeline.py
  git commit -m "perf: avoid repeated page selection checks"
  ```

