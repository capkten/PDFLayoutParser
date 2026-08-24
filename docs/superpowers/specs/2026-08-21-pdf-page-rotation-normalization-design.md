# PDF Page Rotation Normalization Design

## Goal

Make pages whose PDF rotation metadata is 90, 180, or 270 degrees use one
consistent coordinate system during text extraction, table detection, image
extraction, layout building, and rendering.

## Root Cause

`Loader` records `page.rotation`, but the downstream stages consume the raw
PyMuPDF page. On a rotated page, `page.rect` describes the displayed page
while drawing and text coordinates can still be expressed in the original
media-box coordinate system. The current pipeline therefore returns table
boxes that can fall outside the displayed page and renders them against a
different orientation.

PyMuPDF's `Page.remove_rotation()` transforms the page content and removes the
page rotation in memory. After that operation, drawing, text, table, and
render coordinates share the same page coordinate system. The original
rotation remains available in the parser's `Page.rotation` metadata loaded
before processing.

## Design

Add one small, idempotent page-normalization helper that calls
`page.remove_rotation()` only when `page.rotation` is non-zero. Apply it at
the earliest page-processing boundaries:

- the full `Pipeline` page stage before text, table, image, and layout work;
- direct `PDFParser.extract_tables()` and `extract_text()` page loops;
- direct `TableExtractor.extract()` calls used by library consumers and tests;
- `RenderEngine.render()` before rasterization so generated images use the
  same orientation as extraction coordinates.

The helper must not save or overwrite the source PDF. Calling it repeatedly on
the same page must be a no-op after the first call. `Page.rotation` in the
returned document remains the original PDF metadata value for traceability;
the working PyMuPDF page is normalized to rotation zero.

## Scope and Non-Goals

- Handle PDF page rotation metadata values 0, 90, 180, and 270.
- Keep existing table detection algorithms and sources unchanged.
- Do not infer orientation from OCR, text direction, or raster image content
  when PDF metadata reports rotation zero.
- Do not change caller-provided seal coordinates in this change; their
  coordinate contract remains the existing page-coordinate contract.

## Error Handling

PyMuPDF remains responsible for invalid page objects and malformed documents.
The helper should not swallow exceptions or silently fabricate a transform.
Rotation zero must return without changing the page.

## Verification

Add regression coverage for a synthetic ruled table saved with page rotations
90, 180, and 270. Each case must verify that table extraction still returns a
2-by-2 table and that its table bounding box is contained by the normalized
page rectangle. Add a render assertion that the output image dimensions match
the normalized page rectangle at the configured DPI. Run the focused tests,
then the existing table extractor, PDF parser, and pipeline suites.
