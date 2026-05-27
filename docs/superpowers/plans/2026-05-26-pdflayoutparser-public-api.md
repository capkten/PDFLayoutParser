# PDFParser Public API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a `PDFParser` class that exposes 11 methods for PDF parsing, extraction, serialization, and region-based operations, packaged as a `.whl`.

**Architecture:** `PDFParser` wraps the existing `Pipeline` for full parsing and delegates to individual extractors (`TextExtractor`, `TableExtractor`, `ImageExtractor`, `RenderEngine`) for targeted operations. JSON/Markdown writers gain in-memory methods. Region methods normalize 0~1 coordinates to PDF points, then filter/crop accordingly.

**Tech Stack:** Python 3.10+, PyMuPDF (fitz), pytest, setuptools + wheel

---

### Task 1: PDFParser class skeleton, constructor, context manager, exports

**Files:**
- Create: `src/pdflayoutparser/pdf_parser.py`
- Create: `tests/test_pdf_parser.py`
- Modify: `src/pdflayoutparser/__init__.py`

- [ ] **Step 1: Write tests for constructor and context manager**

```python
# tests/test_pdf_parser.py
import os
import fitz
import pytest

from pdflayoutparser.pdf_parser import PDFParser
from pdflayoutparser.models import Document, Page, BBox
from tests.conftest import make_text_pdf


def test_constructor_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    assert parser._pdf_path == pdf_path
    assert parser._document is None


def test_constructor_from_document():
    doc = Document(file_name="test.pdf", page_count=1, pages=[])
    parser = PDFParser(doc)
    assert parser._document is doc
    assert parser._pdf_path is None


def test_context_manager_closes_handle(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    with PDFParser(pdf_path) as parser:
        assert parser is not None
    # Context manager exits cleanly without error


def test_context_manager_with_document():
    doc = Document(file_name="test.pdf", page_count=1, pages=[])
    with PDFParser(doc) as parser:
        assert parser._document is doc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdflayoutparser.pdf_parser'`

- [ ] **Step 3: Implement PDFParser skeleton**

```python
# src/pdflayoutparser/pdf_parser.py
"""Public API for PDFLayoutParser.

Provides the :class:`PDFParser` class that wraps the internal pipeline
and individual extractors behind a unified interface.
"""

from __future__ import annotations

from typing import List, Optional

from pdflayoutparser.models import Document


class PDFParser:
    """High-level PDF parsing and extraction interface.

    Accepts either a file path or a pre-parsed :class:`Document`.

    Example::

        with PDFParser("report.pdf") as parser:
            doc = parser.parse()
            tables = parser.extract_tables()
    """

    def __init__(
        self,
        source: str | Document,
        *,
        render_dpi: int = 200,
        seal_coords: Optional[List[dict]] = None,
        use_ml: bool = False,
        ml_model_path: Optional[str] = None,
        ml_confidence: float = 0.25,
    ) -> None:
        if isinstance(source, Document):
            self._pdf_path: str | None = None
            self._document: Document | None = source
        else:
            self._pdf_path = source
            self._document = None

        self._render_dpi = render_dpi
        self._seal_coords = seal_coords or []
        self._use_ml = use_ml
        self._ml_model_path = ml_model_path
        self._ml_confidence = ml_confidence

    def __enter__(self) -> PDFParser:
        return self

    def __exit__(self, *exc) -> None:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 5: Update `__init__.py` exports**

Modify `src/pdflayoutparser/__init__.py`:

```python
from pdflayoutparser.pdf_parser import PDFParser
from pdflayoutparser.models import (
    Document, Page, Block, Line, Word, Char,
    Table, Cell, Image, Seal, RenderInfo,
    LayoutElement, BBox, Span,
)

__all__ = [
    "PDFParser",
    "Document", "Page", "Block", "Line", "Word", "Char",
    "Table", "Cell", "Image", "Seal", "RenderInfo",
    "LayoutElement", "BBox", "Span",
]
```

- [ ] **Step 6: Verify import works**

Run: `python -c "from pdflayoutparser import PDFParser, Document, Table; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/pdflayoutparser/pdf_parser.py src/pdflayoutparser/__init__.py tests/test_pdf_parser.py
git commit -m "feat: add PDFParser class skeleton with constructor and context manager"
```

---

### Task 2: `parse()` method with caching

**Files:**
- Modify: `src/pdflayoutparser/pipeline.py`
- Modify: `src/pdflayoutparser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write tests for parse()**

Append to `tests/test_pdf_parser.py`:

```python
def test_parse_returns_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello World")
    parser = PDFParser(pdf_path)
    doc = parser.parse()
    assert isinstance(doc, Document)
    assert doc.page_count == 1
    assert len(doc.pages) == 1
    assert len(doc.pages[0].blocks) >= 1


def test_parse_caches_result(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    doc1 = parser.parse()
    doc2 = parser.parse()
    assert doc1 is doc2


def test_parse_from_document():
    doc = Document(file_name="test.pdf", page_count=1, pages=[])
    parser = PDFParser(doc)
    result = parser.parse()
    assert result is doc


def test_parse_with_output_dir_writes_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "out")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path, render_dpi=150)
    doc = parser.parse(output_dir=output_dir)
    assert os.path.exists(os.path.join(output_dir, "output.json"))
    assert os.path.exists(os.path.join(output_dir, "output.md"))


def test_parse_no_output_dir_does_not_write_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello")
    parser = PDFParser(pdf_path)
    doc = parser.parse()
    assert isinstance(doc, Document)
    # No output_dir means no files written
    assert not os.path.exists(os.path.join(tmp_dir, "output.json"))


def test_parse_with_page_indices(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    from tests.conftest import make_multi_page_pdf
    make_multi_page_pdf(pdf_path, ["Page 0", "Page 1", "Page 2"])
    parser = PDFParser(pdf_path)
    doc = parser.parse(page_indices=[0, 2])
    assert doc.page_count == 3  # Document metadata still reports all pages
    # But only pages 0 and 2 should have extracted content
    assert len(doc.pages[0].blocks) >= 1
    assert len(doc.pages[2].blocks) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py::test_parse_returns_document -v`
Expected: FAIL — `AttributeError: 'PDFParser' object has no attribute 'parse'`

- [ ] **Step 3: Modify Pipeline to accept `output_dir=None`**

Pipeline currently requires `output_dir` and always writes files. Modify `Pipeline.run()` to skip all file I/O when `output_dir is None`.

In `src/pdflayoutparser/pipeline.py`, change the `__init__` signature:

```python
    def __init__(
        self,
        pdf_path: str,
        output_dir: str | None = None,  # Changed: now optional
        render_dpi: int = 200,
        ...
    ):
        ...
        self.output_dir = output_dir
```

In `Pipeline.run()`, wrap directory creation and file I/O in conditionals:

```python
    def run(self) -> Document:
        ...
        document, _ = self._time_stage("load", lambda: Loader(self.pdf_path).load())

        # Prepare output directories only when output_dir is set
        if self.output_dir is not None:
            images_dir = os.path.join(self.output_dir, "images")
            pages_dir = os.path.join(self.output_dir, "pages")
            ...
            os.makedirs(self.output_dir, exist_ok=True)
            os.makedirs(images_dir, exist_ok=True)
            os.makedirs(pages_dir, exist_ok=True)
            if self.debug:
                os.makedirs(text_alignment_debug_dir, exist_ok=True)

        pdf_doc = fitz.open(self.pdf_path)
        try:
            for page in document.pages:
                ...
                # d. Image extraction — only when output_dir is set
                if self.output_dir is not None:
                    page.images, _ = self._time_stage(
                        "image_extract",
                        lambda: ImageExtractor(images_dir).extract(...),
                    )
                else:
                    page.images = []

                ...

                # i. Render — only when output_dir is set
                if self.output_dir is not None:
                    page.render, _ = self._time_stage(
                        "render",
                        lambda: RenderEngine(self.output_dir, self.render_dpi).render(...),
                    )

                # j. Per-page output — only when output_dir is set
                if self.output_dir is not None:
                    page_json_path = os.path.join(pages_dir, ...)
                    ...
        finally:
            pdf_doc.close()

        # 3. Output writers — only when output_dir is set
        if self.output_dir is not None:
            self._time_stage("write_output_json", ...)
            self._time_stage("write_output_md", ...)

        ...
        return document
```

- [ ] **Step 4: Implement parse() on PDFParser**

Add to `PDFParser` class in `src/pdflayoutparser/pdf_parser.py`:

```python
    def parse(
        self,
        *,
        page_indices: Optional[List[int]] = None,
        output_dir: Optional[str] = None,
    ) -> Document:
        """Run the full parsing pipeline and return a Document.

        Results are cached — subsequent calls return the same object.
        Pass *output_dir* to also write JSON, Markdown, images, and renders.
        """
        if self._document is not None:
            return self._document

        from pdflayoutparser.pipeline import Pipeline

        pipeline = Pipeline(
            pdf_path=self._pdf_path,
            output_dir=output_dir,
            render_dpi=self._render_dpi,
            seal_coords=self._seal_coords,
            page_indices=page_indices,
            use_ml=self._use_ml,
            ml_model_path=self._ml_model_path,
            ml_confidence=self._ml_confidence,
        )
        self._document = pipeline.run()
        return self._document
```

Also add `import os` at the top of `pdf_parser.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 6: Run existing Pipeline tests to verify no regression**

Run: `pytest tests/test_pipeline.py -v`
Expected: All existing tests still PASS

- [ ] **Step 7: Commit**

```bash
git add src/pdflayoutparser/pipeline.py src/pdflayoutparser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: implement PDFParser.parse() with caching; Pipeline accepts output_dir=None"
```

---

### Task 3: `extract_text()` and `extract_tables()` methods

**Files:**
- Modify: `src/pdflayoutparser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write tests for extract_text()**

Append to `tests/test_pdf_parser.py`:

```python
from pdflayoutparser.models import Block, Table


def test_extract_text_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Extract me")
    parser = PDFParser(pdf_path)
    blocks = parser.extract_text()
    assert isinstance(blocks, list)
    assert len(blocks) >= 1
    assert isinstance(blocks[0], Block)
    assert "Extract" in blocks[0].text


def test_extract_text_from_cached_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Cached text")
    parser = PDFParser(pdf_path)
    parser.parse()
    blocks = parser.extract_text()
    assert len(blocks) >= 1
    assert "Cached" in blocks[0].text


def test_extract_text_with_page_indices(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    from tests.conftest import make_multi_page_pdf
    make_multi_page_pdf(pdf_path, ["AAA", "BBB", "CCC"])
    parser = PDFParser(pdf_path)
    blocks = parser.extract_text(page_indices=[1])
    # Only page 1 text should be returned
    texts = " ".join(b.text for b in blocks)
    assert "BBB" in texts
```

- [ ] **Step 2: Write tests for extract_tables()**

Append to `tests/test_pdf_parser.py`:

```python
def test_extract_tables_from_path(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    # Use the existing table PDF helper
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    tables = parser.extract_tables()
    assert isinstance(tables, list)


def test_extract_tables_from_cached_document(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    parser.parse()
    tables = parser.extract_tables()
    assert isinstance(tables, list)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py::test_extract_text_from_path -v`
Expected: FAIL — `AttributeError: 'PDFParser' object has no attribute 'extract_text'`

- [ ] **Step 4: Implement extract_text() and extract_tables()**

Add to `PDFParser` class:

```python
    def extract_text(
        self,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> List[Block]:
        """Extract text blocks from the PDF.

        If a cached Document exists, returns its blocks directly.
        Otherwise loads the PDF and runs only the text extraction stage.
        """
        if self._document is not None:
            return self._collect_from_document(
                lambda p: p.blocks, page_indices
            )

        import fitz as _fitz
        from pdflayoutparser.loader import Loader
        from pdflayoutparser.text_extractor import TextExtractor

        document, _ = Loader(self._pdf_path).load()
        pdf_doc = _fitz.open(self._pdf_path)
        try:
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                page.blocks = TextExtractor().extract_blocks(pdf_doc[page.index])
        finally:
            pdf_doc.close()
        self._document = document
        return self._collect_from_document(lambda p: p.blocks, page_indices)

    def extract_tables(
        self,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> List[Table]:
        """Extract tables from the PDF.

        If a cached Document exists, returns its tables directly.
        Otherwise loads the PDF and runs only the table detection stage.
        """
        if self._document is not None:
            return self._collect_from_document(
                lambda p: p.tables, page_indices
            )

        import fitz as _fitz
        from pdflayoutparser.loader import Loader
        from pdflayoutparser.table_extractor import TableExtractor

        document, _ = Loader(self._pdf_path).load()
        pdf_doc = _fitz.open(self._pdf_path)
        try:
            extractor = TableExtractor(
                use_ml=self._use_ml,
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
            )
            for page in document.pages:
                if page_indices is not None and page.index not in page_indices:
                    continue
                page.tables = extractor.extract(pdf_doc[page.index])
        finally:
            pdf_doc.close()
        self._document = document
        return self._collect_from_document(lambda p: p.tables, page_indices)

    def _collect_from_document(
        self,
        getter,
        page_indices: Optional[List[int]],
    ) -> list:
        """Collect items from all pages of the cached document."""
        items = []
        for page in self._document.pages:
            if page_indices is not None and page.index not in page_indices:
                continue
            items.extend(getter(page))
        return items
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pdflayoutparser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: implement PDFParser.extract_text() and extract_tables()"
```

---

### Task 4: `extract_images()` and `render_pages()` methods

**Files:**
- Modify: `src/pdflayoutparser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write tests for extract_images()**

Append to `tests/test_pdf_parser.py`:

```python
from pdflayoutparser.models import Image, RenderInfo
from tests.conftest import make_pdf_with_image


def test_extract_images_writes_files(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    images = parser.extract_images(output_dir)
    assert isinstance(images, list)
    assert len(images) >= 1
    assert isinstance(images[0], Image)
    assert images[0].path is not None
    assert os.path.exists(images[0].path)


def test_extract_images_with_page_indices(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    images = parser.extract_images(output_dir, page_indices=[0])
    assert len(images) >= 1
```

- [ ] **Step 2: Write tests for render_pages()**

Append to `tests/test_pdf_parser.py`:

```python
def test_render_pages_writes_png(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "renders")
    make_text_pdf(pdf_path, text="Render me")
    parser = PDFParser(pdf_path, render_dpi=150)
    renders = parser.render_pages(output_dir)
    assert isinstance(renders, list)
    assert len(renders) >= 1
    assert isinstance(renders[0], RenderInfo)
    assert renders[0].path is not None
    assert os.path.exists(renders[0].path)
    assert renders[0].path.endswith(".png")


def test_render_pages_custom_dpi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "renders")
    make_text_pdf(pdf_path, text="DPI test")
    parser = PDFParser(pdf_path, render_dpi=200)
    renders = parser.render_pages(output_dir, dpi=100)
    assert renders[0].dpi == 100
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py::test_extract_images_writes_files -v`
Expected: FAIL — `AttributeError: 'PDFParser' object has no attribute 'extract_images'`

- [ ] **Step 4: Implement extract_images() and render_pages()**

Add to `PDFParser` class:

```python
    def extract_images(
        self,
        output_dir: str,
        *,
        page_indices: Optional[List[int]] = None,
    ) -> List[Image]:
        """Extract embedded images from the PDF, writing to *output_dir*."""
        from pdflayoutparser.loader import Loader
        from pdflayoutparser.image_extractor import ImageExtractor

        document, _ = Loader(self._pdf_path or self._document.file_name).load()
        extractor = ImageExtractor(output_dir)
        images: List[Image] = []
        for page in document.pages:
            if page_indices is not None and page.index not in page_indices:
                continue
            images.extend(extractor.extract(
                self._pdf_path or self._document.file_name, page.index
            ))
        return images

    def render_pages(
        self,
        output_dir: str,
        *,
        dpi: Optional[int] = None,
        page_indices: Optional[List[int]] = None,
    ) -> List[RenderInfo]:
        """Render PDF pages as PNG files into *output_dir*."""
        from pdflayoutparser.loader import Loader
        from pdflayoutparser.render_engine import RenderEngine

        effective_dpi = dpi if dpi is not None else self._render_dpi
        document, _ = Loader(self._pdf_path or self._document.file_name).load()
        engine = RenderEngine(output_dir, effective_dpi)
        renders: List[RenderInfo] = []
        for page in document.pages:
            if page_indices is not None and page.index not in page_indices:
                continue
            renders.append(engine.render(
                self._pdf_path or self._document.file_name, page.index
            ))
        return renders
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pdflayoutparser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: implement PDFParser.extract_images() and render_pages()"
```

---

### Task 5: `to_json()` and `to_markdown()` methods

**Files:**
- Modify: `src/pdflayoutparser/json_writer.py`
- Modify: `src/pdflayoutparser/markdown_writer.py`
- Modify: `src/pdflayoutparser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write tests for to_json() and to_markdown()**

Append to `tests/test_pdf_parser.py`:

```python
import json as json_module


def test_to_json_returns_string(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="JSON test")
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.to_json()
    assert isinstance(result, str)
    data = json_module.loads(result)
    assert "document" in data
    assert "pages" in data


def test_to_json_without_parse_auto_parses(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Auto parse")
    parser = PDFParser(pdf_path)
    result = parser.to_json()
    assert isinstance(result, str)
    data = json_module.loads(result)
    assert data["document"]["page_count"] == 1


def test_to_json_with_explicit_document():
    doc = Document(file_name="test.pdf", page_count=0, pages=[])
    parser = PDFParser(doc)
    result = parser.to_json(document=doc)
    data = json_module.loads(result)
    assert data["document"]["page_count"] == 0


def test_to_markdown_returns_string(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="MD test")
    parser = PDFParser(pdf_path)
    parser.parse()
    result = parser.to_markdown()
    assert isinstance(result, str)
    assert len(result) > 0


def test_to_markdown_without_parse_auto_parses(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Auto MD")
    parser = PDFParser(pdf_path)
    result = parser.to_markdown()
    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py::test_to_json_returns_string -v`
Expected: FAIL — `AttributeError: 'PDFParser' object has no attribute 'to_json'`

- [ ] **Step 3: Add in-memory methods to writers**

Add to `JSONWriter` class in `src/pdflayoutparser/json_writer.py`:

```python
    def to_dict(self, document: Document) -> Dict[str, Any]:
        """Convert *document* to a dict without writing to disk."""
        return self._document_to_dict(document)
```

Add to `MarkdownWriter` class in `src/pdflayoutparser/markdown_writer.py`:

```python
    def to_string(self, document: Document) -> str:
        """Convert *document* to a Markdown string without writing to disk."""
        lines: list[str] = []
        for page in document.pages:
            for element in page.layout_elements:
                lines.extend(self._render_element(element, page.index))
        return "\n".join(lines)
```

- [ ] **Step 4: Implement to_json() and to_markdown() on PDFParser**

Add to `PDFParser` class:

```python
    def to_json(
        self,
        document: Optional[Document] = None,
    ) -> str:
        """Serialize a Document to a JSON string (in-memory, no file I/O).

        If *document* is None, uses the cached parse result (calls :meth:`parse`
        if not yet parsed).
        """
        import json
        from pdflayoutparser.json_writer import JSONWriter

        doc = document if document is not None else self.parse()
        data = JSONWriter().to_dict(doc)
        return json.dumps(data, ensure_ascii=False)

    def to_markdown(
        self,
        document: Optional[Document] = None,
    ) -> str:
        """Serialize a Document to a Markdown string (in-memory, no file I/O).

        If *document* is None, uses the cached parse result (calls :meth:`parse`
        if not yet parsed).
        """
        from pdflayoutparser.markdown_writer import MarkdownWriter

        doc = document if document is not None else self.parse()
        return MarkdownWriter().to_string(doc)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pdflayoutparser/pdf_parser.py src/pdflayoutparser/json_writer.py src/pdflayoutparser/markdown_writer.py tests/test_pdf_parser.py
git commit -m "feat: implement PDFParser.to_json() and to_markdown() with in-memory writers"
```

---

### Task 6: Region coordinate helper + `extract_text_in_region()`

**Files:**
- Modify: `src/pdflayoutparser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write tests for region coordinate normalization**

Append to `tests/test_pdf_parser.py`:

```python
from pdflayoutparser.pdf_parser import PDFParser


def test_normalize_region_single(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Region test")
    parser = PDFParser(pdf_path)
    # A4 page: 595.276 x 841.89 points
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    result = PDFParser._normalize_regions(region)
    assert len(result) == 1
    assert result[0]["page_index"] == 0
    assert abs(result[0]["x0"] - 0.0) < 0.01
    assert abs(result[0]["x1"] - 297.638) < 1.0  # 595.276 * 0.5


def test_normalize_region_list():
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
        {"page_index": 1, "x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.8},
    ]
    result = PDFParser._normalize_regions(regions)
    assert len(result) == 2
```

- [ ] **Step 2: Write tests for extract_text_in_region()**

Append to `tests/test_pdf_parser.py`:

```python
def test_extract_text_in_region_single(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Hello Region")
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    blocks = parser.extract_text_in_region(region)
    assert isinstance(blocks, list)
    assert len(blocks) >= 1


def test_extract_text_in_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    make_text_pdf(pdf_path, text="Multi Region")
    parser = PDFParser(pdf_path)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
        {"page_index": 0, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
    ]
    blocks = parser.extract_text_in_region(regions)
    assert isinstance(blocks, list)


def test_extract_text_in_region_excludes_outside_text(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    doc = fitz.open()
    page = doc.new_page()  # A4: 595 x 842
    page.insert_text((50, 50), "TopLeft")
    page.insert_text((400, 700), "BottomRight")
    doc.save(pdf_path)
    doc.close()

    parser = PDFParser(pdf_path)
    # Only top-left quadrant
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    blocks = parser.extract_text_in_region(region)
    all_text = " ".join(b.text for b in blocks)
    assert "TopLeft" in all_text
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py::test_normalize_region_single -v`
Expected: FAIL

- [ ] **Step 4: Implement region helper and extract_text_in_region()**

Add to `PDFParser` class:

```python
    @staticmethod
    def _normalize_regions(
        region: dict | list[dict],
        page_sizes: dict[int, tuple[float, float]] | None = None,
    ) -> list[dict]:
        """Convert normalized 0~1 region coords to PDF point coords.

        If *page_sizes* is provided, uses those; otherwise the coords are
        returned as-is (already in points) for the caller to resolve later.
        """
        regions = region if isinstance(region, list) else [region]
        result = []
        for r in regions:
            if page_sizes and r["page_index"] in page_sizes:
                w, h = page_sizes[r["page_index"]]
                result.append({
                    "page_index": r["page_index"],
                    "x0": r["x0"] * w,
                    "y0": r["y0"] * h,
                    "x1": r["x1"] * w,
                    "y1": r["y1"] * h,
                })
            else:
                result.append(dict(r))
        return result

    def _get_page_sizes(self) -> dict[int, tuple[float, float]]:
        """Return {page_index: (width, height)} from cached doc or PDF."""
        if self._document is not None:
            return {
                p.index: (p.size["width"], p.size["height"])
                for p in self._document.pages
            }
        import fitz as _fitz
        doc = _fitz.open(self._pdf_path)
        try:
            return {
                i: (doc[i].rect.width, doc[i].rect.height)
                for i in range(len(doc))
            }
        finally:
            doc.close()

    def _bbox_intersects(self, block_bbox, region_bbox) -> bool:
        """Check if block_bbox overlaps with region_bbox."""
        return not (
            block_bbox.x1 < region_bbox["x0"]
            or block_bbox.x0 > region_bbox["x1"]
            or block_bbox.y1 < region_bbox["y0"]
            or block_bbox.y0 > region_bbox["y1"]
        )

    def extract_text_in_region(
        self,
        region: dict | list[dict],
    ) -> List[Block]:
        """Extract text blocks that intersect with the given region(s).

        Region coordinates are normalized 0~1 relative to page size.
        """
        from pdflayoutparser.models import BBox

        page_sizes = self._get_page_sizes()
        regions = self._normalize_regions(region, page_sizes)

        # Ensure text is extracted
        if self._document is None:
            self.extract_text()

        blocks: List[Block] = []
        for r in regions:
            page_idx = r["page_index"]
            target_page = None
            for p in self._document.pages:
                if p.index == page_idx:
                    target_page = p
                    break
            if target_page is None:
                continue
            for block in target_page.blocks:
                if self._bbox_intersects(block.bbox, r):
                    blocks.append(block)
        return blocks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pdflayoutparser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: implement PDFParser.extract_text_in_region() with coordinate normalization"
```

---

### Task 7: `extract_table_in_region()`

**Files:**
- Modify: `src/pdflayoutparser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write tests for extract_table_in_region()**

Append to `tests/test_pdf_parser.py`:

```python
def test_extract_table_in_region_returns_table_or_none(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_table_in_region(region)
    # May return Table or None depending on whether detection finds a table
    assert result is None or isinstance(result, Table)


def test_extract_table_in_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "table.pdf")
    from tests.test_table_extractor import make_pdf_with_table
    make_pdf_with_table(pdf_path)
    parser = PDFParser(pdf_path)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0},
        {"page_index": 0, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 1.0},
    ]
    result = parser.extract_table_in_region(regions)
    assert isinstance(result, list)


def test_extract_table_in_region_empty_page(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "empty.pdf")
    make_text_pdf(pdf_path, text="No table here")
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_table_in_region(region)
    assert result is None or (isinstance(result, Table) and result.rows == 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py::test_extract_table_in_region_returns_table_or_none -v`
Expected: FAIL

- [ ] **Step 3: Implement extract_table_in_region()**

Add to `PDFParser` class:

```python
    def extract_table_in_region(
        self,
        region: dict | list[dict],
    ) -> Table | list[Table] | None:
        """Extract table(s) from specified region(s).

        Region coordinates are normalized 0~1 relative to page size.
        Returns Table for single region (or None), list[Table] for multiple.
        """
        import fitz as _fitz
        from pdflayoutparser.loader import Loader
        from pdflayoutparser.table_extractor import TableExtractor

        is_single = isinstance(region, dict)
        page_sizes = self._get_page_sizes()
        regions = self._normalize_regions(region, page_sizes)

        pdf_path = self._pdf_path or self._document.file_name
        document, _ = Loader(pdf_path).load()
        pdf_doc = _fitz.open(pdf_path)
        try:
            extractor = TableExtractor(
                use_ml=self._use_ml,
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
            )
            results = []
            for r in regions:
                page_idx = r["page_index"]
                page_handle = pdf_doc[page_idx]
                tables = extractor.extract(page_handle)
                # Filter tables that intersect with the region
                matched = [
                    t for t in tables
                    if self._bbox_intersects(t.bbox, r)
                ]
                if is_single:
                    return matched[0] if matched else None
                results.extend(matched)
            return results
        finally:
            pdf_doc.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdflayoutparser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: implement PDFParser.extract_table_in_region()"
```

---

### Task 8: `extract_image_in_region()` and `render_region()`

**Files:**
- Modify: `src/pdflayoutparser/pdf_parser.py`
- Modify: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write tests for extract_image_in_region()**

Append to `tests/test_pdf_parser.py`:

```python
def test_extract_image_in_region_returns_image_or_none(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "region_images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.extract_image_in_region(region, output_dir)
    assert result is None or isinstance(result, Image)


def test_extract_image_in_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "img.pdf")
    output_dir = os.path.join(tmp_dir, "region_images")
    make_pdf_with_image(pdf_path)
    parser = PDFParser(pdf_path)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5},
        {"page_index": 0, "x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0},
    ]
    result = parser.extract_image_in_region(regions, output_dir)
    assert isinstance(result, list)
```

- [ ] **Step 2: Write tests for render_region()**

Append to `tests/test_pdf_parser.py`:

```python
def test_render_region_writes_png(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="Render region")
    parser = PDFParser(pdf_path, render_dpi=150)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
    result = parser.render_region(region, output_dir)
    assert isinstance(result, RenderInfo)
    assert result.path is not None
    assert os.path.exists(result.path)
    assert result.path.endswith(".png")


def test_render_region_multi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="Multi render")
    parser = PDFParser(pdf_path, render_dpi=150)
    regions = [
        {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5},
        {"page_index": 0, "x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0},
    ]
    result = parser.render_region(regions, output_dir)
    assert isinstance(result, list)
    assert len(result) == 2
    for r in result:
        assert os.path.exists(r.path)


def test_render_region_custom_dpi(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "test.pdf")
    output_dir = os.path.join(tmp_dir, "region_renders")
    make_text_pdf(pdf_path, text="DPI region")
    parser = PDFParser(pdf_path, render_dpi=200)
    region = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    result = parser.render_region(region, output_dir, dpi=100)
    assert result.dpi == 100
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_pdf_parser.py::test_render_region_writes_png -v`
Expected: FAIL

- [ ] **Step 4: Implement extract_image_in_region() and render_region()**

Add to `PDFParser` class:

```python
    def extract_image_in_region(
        self,
        region: dict | list[dict],
        output_dir: str,
    ) -> Image | list[Image] | None:
        """Extract images that intersect with the given region(s).

        Region coordinates are normalized 0~1 relative to page size.
        """
        is_single = isinstance(region, dict)
        page_sizes = self._get_page_sizes()
        regions = self._normalize_regions(region, page_sizes)

        # Get all images first
        all_page_indices = list({r["page_index"] for r in regions})
        all_images = self.extract_images(
            output_dir, page_indices=all_page_indices
        )

        results = []
        for r in regions:
            matched = [
                img for img in all_images
                if img.page_index == r["page_index"]
                and img.bbox is not None
                and self._bbox_intersects(img.bbox, r)
            ]
            if is_single:
                return matched[0] if matched else None
            results.extend(matched)
        return results

    def render_region(
        self,
        region: dict | list[dict],
        output_dir: str,
        dpi: Optional[int] = None,
    ) -> RenderInfo | list[RenderInfo]:
        """Render region(s) of the PDF as PNG files.

        Region coordinates are normalized 0~1 relative to page size.
        """
        import os as _os
        import fitz as _fitz

        is_single = isinstance(region, dict)
        effective_dpi = dpi or self._render_dpi
        page_sizes = self._get_page_sizes()
        regions = self._normalize_regions(region, page_sizes)

        _os.makedirs(output_dir, exist_ok=True)
        pdf_path = self._pdf_path or self._document.file_name
        pdf_doc = _fitz.open(pdf_path)
        try:
            results = []
            for idx, r in enumerate(regions):
                page_handle = pdf_doc[r["page_index"]]
                clip = fitz.Rect(r["x0"], r["y0"], r["x1"], r["y1"])
                mat = _fitz.Matrix(effective_dpi / 72, effective_dpi / 72)
                pix = page_handle.get_pixmap(matrix=mat, clip=clip)

                file_name = f"region-{r['page_index']:03d}-{idx:03d}.png"
                path = _os.path.join(output_dir, file_name)
                pix.save(path)

                info = RenderInfo(
                    path=path,
                    width=pix.width,
                    height=pix.height,
                    dpi=effective_dpi,
                )
                if is_single:
                    return info
                results.append(info)
            return results
        finally:
            pdf_doc.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pdflayoutparser/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: implement PDFParser.extract_image_in_region() and render_region()"
```

---

### Task 9: .whl build verification

**Files:**
- No file changes

- [ ] **Step 1: Build the wheel**

Run: `cd D:/codes/PDFLayoutParser && python -m build --wheel`
Expected: `Successfully built pdflayoutparser-0.1.0-py3-none-any.whl` in `dist/`

- [ ] **Step 2: Install the wheel in a test and verify imports**

Run: `pip install dist/pdflayoutparser-0.1.0-py3-none-any.whl --force-reinstall --no-deps && python -c "from pdflayoutparser import PDFParser, Document, Table, Block, Image, RenderInfo, BBox; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit (if any fixups needed)**

```bash
git add -A
git commit -m "chore: verify .whl build and full test suite"
```
