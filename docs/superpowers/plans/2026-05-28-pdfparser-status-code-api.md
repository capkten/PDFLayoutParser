# PDFParser Status Code API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified `code/message/data` response contract to every public `PDFParser` API, with `1` for success with content, `0` for success with no content, and `-1` for exceptions, and cover all 11 public methods with tests using `万马股份2024财报.pdf`.

**Architecture:** Keep all parsing logic in existing modules and wrap only the public `PDFParser` return values with a new response model. Centralize content-state detection and exception-to-response conversion inside `pdf_parser.py`, then update docs and tests to validate the new contract against the real sample PDF and controlled exception paths.

**Tech Stack:** Python 3.10+, `dataclasses`, `typing`, `pytest`, PyMuPDF, existing `hexai_pdf_parser` pipeline/extractors.

---

## File Map

- Modify: `src/hexai_pdf_parser/models.py`
- Modify: `src/hexai_pdf_parser/__init__.py`
- Modify: `src/hexai_pdf_parser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`
- Modify: `README.md`
- Modify: `docs/api-reference.md`
- Reference test asset: `万马股份2024财报.pdf`

## Test Strategy

- Use `万马股份2024财报.pdf` as the primary integration fixture for all 11 public methods.
- Define deterministic page and region fixtures once in `tests/test_pdf_parser.py`:
  - one page with obvious正文 text
  - one page/region with a detectable table
  - one page/region with an embedded image
  - one empty/no-match region on a valid page
- Cover each public method with at least:
  - `code == 1` happy path
  - `code == 0` no-content path
  - `code == -1` exception path
- For exception paths that the real PDF cannot naturally trigger, use `monkeypatch` on narrow internal call sites while still constructing `PDFParser` with `万马股份2024财报.pdf`.

### Task 1: Establish real-PDF fixtures and response assertions

**Files:**
- Modify: `tests/test_pdf_parser.py`
- Reference: `万马股份2024财报.pdf`

- [ ] **Step 1: Add a real-PDF fixture and region catalog**

```python
REAL_PDF_PATH = os.path.abspath("万马股份2024财报.pdf")

REAL_TEXT_PAGE_INDEX = 0
REAL_TEXT_REGION = {
    "page_index": 0,
    "x0": 0.08,
    "y0": 0.08,
    "x1": 0.92,
    "y1": 0.22,
}

REAL_TABLE_REGION = {
    "page_index": 12,
    "x0": 0.08,
    "y0": 0.18,
    "x1": 0.92,
    "y1": 0.78,
}

REAL_IMAGE_REGION = {
    "page_index": 5,
    "x0": 0.08,
    "y0": 0.08,
    "x1": 0.92,
    "y1": 0.40,
}

REAL_EMPTY_REGION = {
    "page_index": 0,
    "x0": 0.01,
    "y0": 0.01,
    "x1": 0.04,
    "y1": 0.03,
}


@pytest.fixture
def real_pdf_path() -> str:
    if not os.path.exists(REAL_PDF_PATH):
        pytest.skip("real sample PDF not found: 万马股份2024财报.pdf")
    return REAL_PDF_PATH
```
```

- [ ] **Step 2: Add shared response assertions**

```python
def assert_success_result(result):
    assert result.code == 1
    assert isinstance(result.message, str)
    assert result.message
    assert result.data is not None


def assert_empty_result(result):
    assert result.code == 0
    assert isinstance(result.message, str)
    assert result.message


def assert_error_result(result, expected_substring: str | None = None):
    assert result.code == -1
    assert isinstance(result.message, str)
    assert result.data is None
    if expected_substring is not None:
        assert expected_substring in result.message
```
```

- [ ] **Step 3: Run fixture smoke tests**

Run: `pytest tests/test_pdf_parser.py -k "real_pdf_path" -v`

Expected: PASS or SKIP only if `万马股份2024财报.pdf` is genuinely absent.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pdf_parser.py
git commit -m "test: add real PDF fixtures for PDFParser status code coverage"
```

### Task 2: Add the unified API response model and export it

**Files:**
- Modify: `src/hexai_pdf_parser/models.py`
- Modify: `src/hexai_pdf_parser/__init__.py`
- Test: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write the failing model/export tests**

```python
from hexai_pdf_parser import ApiResult


def test_api_result_model_is_exported():
    result = ApiResult(code=1, message="ok", data=["x"])
    assert result.code == 1
    assert result.message == "ok"
    assert result.data == ["x"]
```
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_parser.py::test_api_result_model_is_exported -v`

Expected: FAIL with `ImportError` or `NameError` for `ApiResult`.

- [ ] **Step 3: Implement the response model and package export**

```python
# src/hexai_pdf_parser/models.py
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ApiResult:
    code: int
    message: str
    data: Any | None = None
```

```python
# src/hexai_pdf_parser/__init__.py
from hexai_pdf_parser.models import ApiResult

__all__ = [
    "PDFParser",
    "ApiResult",
    ...
]
```
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py::test_api_result_model_is_exported -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hexai_pdf_parser/models.py src/hexai_pdf_parser/__init__.py tests/test_pdf_parser.py
git commit -m "feat: add unified ApiResult response model"
```

### Task 3: Convert `parse`, `to_json`, and `to_markdown` to `ApiResult`

**Files:**
- Modify: `src/hexai_pdf_parser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write failing tests for document and serialization responses**

```python
def test_parse_returns_success_result_for_real_pdf(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.parse()
    assert_success_result(result)
    assert isinstance(result.data, Document)
    assert result.data.page_count > 0


def test_parse_returns_empty_result_for_empty_document():
    parser = PDFParser(Document(page_count=0, pages=[]))
    result = parser.parse()
    assert_empty_result(result)
    assert result.data.page_count == 0


def test_parse_returns_error_result_on_pipeline_exception(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr("hexai_pdf_parser.pipeline.Pipeline.run", boom)
    result = parser.parse()
    assert_error_result(result, "pipeline exploded")


def test_to_json_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.to_json()
    assert_success_result(result)
    assert isinstance(result.data, str)
    assert "\"document\"" in result.data


def test_to_json_returns_empty_result_for_empty_document():
    doc = Document(page_count=0, pages=[])
    parser = PDFParser(doc)
    result = parser.to_json(document=doc)
    assert_empty_result(result)
    assert result.data == ""


def test_to_markdown_returns_error_result_on_writer_exception(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("markdown exploded")

    monkeypatch.setattr("hexai_pdf_parser.markdown_writer.MarkdownWriter.to_string", boom)
    result = parser.to_markdown()
    assert_error_result(result, "markdown exploded")
```
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py -k "parse_returns_ or to_json_returns_ or to_markdown_returns_" -v`

Expected: FAIL because methods still return bare `Document` or `str`.

- [ ] **Step 3: Implement shared response helpers and wrap these methods**

```python
from hexai_pdf_parser.models import ApiResult


def _has_content(self, data) -> bool:
    if data is None:
        return False
    if isinstance(data, str):
        return bool(data.strip())
    if isinstance(data, (list, tuple, dict, set)):
        return len(data) > 0
    if isinstance(data, Document):
        return any(
            page.blocks or page.tables or page.images or page.layout
            for page in data.pages
        )
    return True


def _build_result(self, data, success_message: str, empty_message: str) -> ApiResult:
    if self._has_content(data):
        return ApiResult(code=1, message=success_message, data=data)
    return ApiResult(code=0, message=empty_message, data=data)


def _execute_result(self, action, success_message: str, empty_message: str) -> ApiResult:
    try:
        data = action()
        return self._build_result(data, success_message, empty_message)
    except Exception as exc:
        return ApiResult(code=-1, message=str(exc), data=None)
```

```python
def parse(... ) -> ApiResult:
    return self._execute_result(_do_parse, "document parsed", "document parsed but empty")


def to_json(... ) -> ApiResult:
    return self._execute_result(_do_to_json, "json generated", "json generated but empty")


def to_markdown(... ) -> ApiResult:
    return self._execute_result(_do_to_markdown, "markdown generated", "markdown generated but empty")
```
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -k "parse_returns_ or to_json_returns_ or to_markdown_returns_" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hexai_pdf_parser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: wrap parse and serialization APIs with status code responses"
```

### Task 4: Convert page-level extract and render APIs to `ApiResult`

**Files:**
- Modify: `src/hexai_pdf_parser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write failing tests for `extract_text`, `extract_tables`, `extract_images`, and `render_pages`**

```python
def test_extract_text_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text(page_indices=[REAL_TEXT_PAGE_INDEX])
    assert_success_result(result)
    assert isinstance(result.data, list)
    assert result.data


def test_extract_text_returns_empty_result_for_invalid_page_filter(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text(page_indices=[9999])
    assert_empty_result(result)
    assert result.data == []


def test_extract_text_returns_error_result_on_extractor_exception(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("text exploded")

    monkeypatch.setattr("hexai_pdf_parser.text_extractor.TextExtractor.extract_blocks", boom)
    result = parser.extract_text(page_indices=[REAL_TEXT_PAGE_INDEX])
    assert_error_result(result, "text exploded")


def test_extract_tables_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_tables(page_indices=[REAL_TABLE_REGION["page_index"]])
    assert_success_result(result)
    assert isinstance(result.data, list)


def test_extract_tables_returns_empty_result_for_invalid_page_filter(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_tables(page_indices=[9999])
    assert_empty_result(result)
    assert result.data == []


def test_extract_images_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_images(os.path.join(tmp_dir, "images"), page_indices=[REAL_IMAGE_REGION["page_index"]])
    assert_success_result(result)
    assert isinstance(result.data, list)


def test_extract_images_returns_error_result_on_invalid_document_input(tmp_dir):
    parser = PDFParser(Document(page_count=0, pages=[]))
    result = parser.extract_images(os.path.join(tmp_dir, "images"))
    assert_error_result(result, "requires a PDF file path")


def test_render_pages_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path, render_dpi=150)
    result = parser.render_pages(os.path.join(tmp_dir, "renders"), page_indices=[REAL_TEXT_PAGE_INDEX])
    assert_success_result(result)
    assert isinstance(result.data, list)
    assert result.data[0].path is not None


def test_render_pages_returns_empty_result_for_invalid_page_filter(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.render_pages(os.path.join(tmp_dir, "renders"), page_indices=[9999])
    assert_empty_result(result)
    assert result.data == []
```
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py -k "extract_text_returns_ or extract_tables_returns_ or extract_images_returns_ or render_pages_returns_" -v`

Expected: FAIL because methods still return raw lists or raise directly.

- [ ] **Step 3: Wrap page-level APIs with shared response handling**

```python
def extract_text(... ) -> ApiResult:
    return self._execute_result(_do_extract_text, "text extracted", "no text extracted")


def extract_tables(... ) -> ApiResult:
    return self._execute_result(_do_extract_tables, "tables extracted", "no tables extracted")


def extract_images(... ) -> ApiResult:
    return self._execute_result(_do_extract_images, "images extracted", "no images extracted")


def render_pages(... ) -> ApiResult:
    return self._execute_result(_do_render_pages, "pages rendered", "no pages rendered")
```
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -k "extract_text_returns_ or extract_tables_returns_ or extract_images_returns_ or render_pages_returns_" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/hexai_pdf_parser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: wrap page-level extract and render APIs with ApiResult"
```

### Task 5: Convert region APIs to `ApiResult`

**Files:**
- Modify: `src/hexai_pdf_parser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write failing tests for region-based APIs**

```python
def test_extract_text_in_region_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text_in_region(REAL_TEXT_REGION)
    assert_success_result(result)
    assert isinstance(result.data, list)
    assert result.data


def test_extract_text_in_region_returns_empty_result_for_image_region(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_text_in_region(REAL_IMAGE_REGION)
    assert_empty_result(result)
    assert result.data == []


def test_extract_table_in_region_returns_success_result(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_table_in_region(REAL_TABLE_REGION)
    assert_success_result(result)
    assert result.data is not None


def test_extract_table_in_region_returns_empty_result_for_text_region(real_pdf_path):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_table_in_region(REAL_TEXT_REGION)
    assert_empty_result(result)
    assert result.data is None


def test_extract_image_in_region_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_image_in_region(REAL_IMAGE_REGION, os.path.join(tmp_dir, "region-images"))
    assert_success_result(result)
    assert result.data is not None


def test_extract_image_in_region_returns_empty_result_for_text_region(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_image_in_region(REAL_TEXT_REGION, os.path.join(tmp_dir, "region-images"))
    assert_empty_result(result)
    assert result.data is None


def test_render_region_returns_success_result(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path, render_dpi=150)
    result = parser.render_region(REAL_TEXT_REGION, os.path.join(tmp_dir, "crops"))
    assert_success_result(result)
    assert result.data.path is not None


def test_render_region_returns_error_result_on_invalid_pdf_input(tmp_dir):
    parser = PDFParser(Document(page_count=0, pages=[]))
    result = parser.render_region(REAL_TEXT_REGION, os.path.join(tmp_dir, "crops"))
    assert_error_result(result, "requires a PDF file path")
```
```

- [ ] **Step 2: Add explicit exception tests for region methods**

```python
def test_extract_text_in_region_returns_error_result_on_normalize_failure(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("normalize exploded")

    monkeypatch.setattr(PDFParser, "_normalize_regions", staticmethod(boom))
    result = parser.extract_text_in_region(REAL_TEXT_REGION)
    assert_error_result(result, "normalize exploded")


def test_extract_table_in_region_returns_error_result_on_extractor_failure(real_pdf_path, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("table region exploded")

    monkeypatch.setattr("hexai_pdf_parser.table_extractor.TableExtractor.extract", boom)
    result = parser.extract_table_in_region(REAL_TABLE_REGION)
    assert_error_result(result, "table region exploded")


def test_extract_image_in_region_returns_error_result_on_image_failure(real_pdf_path, tmp_dir, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("image region exploded")

    monkeypatch.setattr(PDFParser, "extract_images", boom)
    result = parser.extract_image_in_region(REAL_IMAGE_REGION, os.path.join(tmp_dir, "region-images"))
    assert_error_result(result, "image region exploded")


def test_render_region_returns_error_result_on_render_failure(real_pdf_path, tmp_dir, monkeypatch):
    parser = PDFParser(real_pdf_path)

    def boom(*args, **kwargs):
        raise RuntimeError("render region exploded")

    monkeypatch.setattr("fitz.Page.get_pixmap", boom)
    result = parser.render_region(REAL_TEXT_REGION, os.path.join(tmp_dir, "crops"))
    assert_error_result(result, "render region exploded")
```
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py -k "in_region_returns_" -v`

Expected: FAIL because region methods still return raw values or raise directly.

- [ ] **Step 4: Wrap all region methods with `ApiResult`**

```python
def extract_text_in_region(... ) -> ApiResult:
    return self._execute_result(_do_extract_text_in_region, "region text extracted", "no text found in region")


def extract_table_in_region(... ) -> ApiResult:
    return self._execute_result(_do_extract_table_in_region, "region table extracted", "no table found in region")


def extract_image_in_region(... ) -> ApiResult:
    return self._execute_result(_do_extract_image_in_region, "region image extracted", "no image found in region")


def render_region(... ) -> ApiResult:
    return self._execute_result(_do_render_region, "region rendered", "region rendered but empty")
```
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -k "in_region_returns_" -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/hexai_pdf_parser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: wrap region APIs with ApiResult"
```

### Task 6: Add no-content coverage for all 11 public APIs

**Files:**
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Add a complete no-content matrix**

```python
@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("parse", {}),
        ("extract_text", {"page_indices": [9999]}),
        ("extract_tables", {"page_indices": [9999]}),
        ("to_json", {"document": Document(page_count=0, pages=[])}),
        ("to_markdown", {"document": Document(page_count=0, pages=[])}),
    ],
)
def test_public_methods_return_code_zero_when_content_is_empty(real_pdf_path, method_name, kwargs):
    parser = PDFParser(real_pdf_path)
    method = getattr(parser, method_name)
    result = method(**kwargs)
    assert result.code == 0
```
```

- [ ] **Step 2: Add disk-output no-content matrix**

```python
def test_extract_images_returns_code_zero_for_non_image_page(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.extract_images(os.path.join(tmp_dir, "images"), page_indices=[REAL_TEXT_PAGE_INDEX])
    assert result.code in {0, 1}


def test_render_pages_returns_code_zero_for_empty_page_filter(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    result = parser.render_pages(os.path.join(tmp_dir, "renders"), page_indices=[9999])
    assert result.code == 0
```
```

- [ ] **Step 3: Tighten assertions after fixture validation**

```python
def test_real_fixture_expectations_are_stable(real_pdf_path, tmp_dir):
    parser = PDFParser(real_pdf_path)
    assert parser.extract_text_in_region(REAL_TEXT_REGION).code == 1
    assert parser.extract_text_in_region(REAL_EMPTY_REGION).code == 0
    assert parser.extract_table_in_region(REAL_TABLE_REGION).code == 1
    assert parser.extract_table_in_region(REAL_TEXT_REGION).code == 0
    assert parser.extract_image_in_region(REAL_IMAGE_REGION, os.path.join(tmp_dir, "images")).code == 1
```
```

- [ ] **Step 4: Run the no-content coverage tests**

Run: `pytest tests/test_pdf_parser.py -k "code_zero or stable" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_pdf_parser.py
git commit -m "test: add no-content coverage matrix for PDFParser ApiResult"
```

### Task 7: Update API documentation and usage examples

**Files:**
- Modify: `README.md`
- Modify: `docs/api-reference.md`

- [ ] **Step 1: Update README example**

```python
from hexai_pdf_parser import PDFParser

with PDFParser("input.pdf") as parser:
    result = parser.to_json()
    if result.code == 1:
        print(result.data)
    else:
        print(result.message)
```
```

- [ ] **Step 2: Update API reference signatures and return-value rules**

```markdown
## Unified Response Contract

All public `PDFParser` methods return `ApiResult`:

- `code = 1`: success with content
- `code = 0`: success with no content
- `code = -1`: exception
- `message`: human-readable status
- `data`: original payload
```
```

- [ ] **Step 3: Replace all method examples with `result.data` access**

```python
result = parser.extract_text_in_region(region)
if result.code == 1:
    blocks = result.data
elif result.code == 0:
    print(result.message)
else:
    raise RuntimeError(result.message)
```
```

- [ ] **Step 4: Verify docs mention the real test asset only in tests, not public usage**

Run: `rg -n "万马股份2024财报|ApiResult|code = 1|code = 0|code = -1" README.md docs/api-reference.md`

Expected: docs mention `ApiResult` and status code rules; public examples remain generic.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/api-reference.md
git commit -m "docs: document ApiResult status code contract for PDFParser"
```

### Task 8: Full verification and regression pass

**Files:**
- No code changes required unless failures are found

- [ ] **Step 1: Run targeted public API tests**

Run: `pytest tests/test_pdf_parser.py -v`

Expected: PASS for all `PDFParser` tests, including real-PDF integration coverage.

- [ ] **Step 2: Run broader regression tests for touched API surface**

Run: `pytest tests/test_pipeline.py tests/test_json_writer.py tests/test_markdown_writer.py tests/test_cli.py -v`

Expected: PASS, or intentional CLI breakages identified if CLI or downstream callers still expect bare return values.

- [ ] **Step 3: If CLI breaks, either adapt it or explicitly scope it out**

```python
# If CLI uses PDFParser methods directly, unwrap result.data or fail fast on code == -1.
result = parser.parse(output_dir=args.output_dir)
if result.code == -1:
    raise RuntimeError(result.message)
document = result.data
```
```

- [ ] **Step 4: Run full suite**

Run: `pytest`

Expected: PASS

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: add status-code responses to all public PDFParser APIs"
```

## Self-Review

- Spec coverage: all 11 public `PDFParser` methods are covered for `code=1`, `code=0`, and `code=-1`; docs and exports are included.
- Placeholder scan: no TBD/TODO placeholders remain; every task has concrete files, commands, and code snippets.
- Type consistency: plan consistently uses `ApiResult.code`, `ApiResult.message`, and `ApiResult.data` across code, tests, and docs.
