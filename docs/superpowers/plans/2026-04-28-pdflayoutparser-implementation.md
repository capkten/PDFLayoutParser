# PDFLayoutParser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a vector PDF parser that outputs structured JSON, readable Markdown, and page/resource images using PyMuPDF.

**Architecture:** A pipeline of single-responsibility modules. TDD throughout; tests create temporary PDFs via PyMuPDF.

**Tech Stack:** Python 3.10+, PyMuPDF (fitz), pytest, dataclasses

---

## File Structure

```
src/hexai_pdf_parser/
  __init__.py
  models.py
  loader.py
  text_extractor.py
  layout_mapper.py
  image_extractor.py
  table_extractor.py
  layout_builder.py
  json_writer.py
  markdown_writer.py
  render_engine.py
  pipeline.py
  cli.py

tests/
  __init__.py
  conftest.py
  test_models.py
  test_loader.py
  test_text_extractor.py
  test_layout_mapper.py
  test_image_extractor.py
  test_table_extractor.py
  test_layout_builder.py
  test_json_writer.py
  test_markdown_writer.py
  test_render_engine.py
  test_pipeline.py
  test_cli.py
```

---

### Task 1: Project Scaffolding
Create pyproject.toml, src/hexai_pdf_parser/__init__.py, tests/__init__.py, tests/conftest.py with PDF creation helpers.

### Task 2: Data Models
Implement dataclasses: BBox, Char, Word, Line, Block, Span, Cell, Table, Image, Seal, RenderInfo, LayoutElement, Page, Document.

### Task 3: Loader Module
class Loader(file_path) with load() -> Document using fitz.open.

### Task 4: Text Extractor Module
class TextExtractor with extract_blocks(page) -> List[Block] using page.get_text("dict").

### Task 5: Layout Mapper Module
class LayoutMapper with map_blocks(blocks) -> List[LayoutElement].

### Task 6: Image Extractor Module
class ImageExtractor(output_dir) with extract(file_path, page_index) -> List[Image].

### Task 7: Table Extractor Module
class TableExtractor with extract(page) -> List[Table] using page.find_tables().

### Task 8: Layout Builder Module
class LayoutBuilder with build(elements, tables, images) -> List[LayoutElement].

### Task 9: Render Engine Module
class RenderEngine(output_dir, dpi=200) with render(file_path, page_index) -> RenderInfo.

### Task 10: JSON Writer Module
class JSONWriter with write(document, output_path) recursive to_dict serialization.

### Task 11: Markdown Writer Module
class MarkdownWriter with write(document, output_path) for text/table/image/seal.

### Task 12: Pipeline Module
class Pipeline(pdf_path, output_dir, render_dpi=200, seal_coords=[]) orchestrating all modules.

### Task 13: CLI Entry Point
argparse CLI: python -m hexai_pdf_parser.cli <pdf_path> --output <dir> --dpi <int>.
