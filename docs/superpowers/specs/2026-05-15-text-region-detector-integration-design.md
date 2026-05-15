# Text Region Detector Integration Design

Date: 2026-05-15

## Background

The current borderless-table path lives in `TableExtractor._extract_via_text_alignment()`.
Its responsibilities are mixed:

1. Collect text rows from `page.get_text("words")`
2. Discover candidate table-like regions
3. Merge likely header spans
4. Trim non-structured prose rows
5. Infer column guides
6. Build `Cell` and `Table`

The new `text_region_detector.py` module already prototypes a stronger region-discovery stage, but it is not part of the production extraction flow. The goal of this change is to integrate that region detector into the borderless-table path without changing the wired-table path or rewriting cell construction in the same step.

## Goal

Refactor the borderless-table flow inside `TableExtractor._extract_via_text_alignment()` into two explicit stages:

1. Region discovery
2. Region-internal grid reconstruction

The first implementation step replaces only the region-discovery stage. Existing downstream logic for header merge, trim, guide inference, and cell construction remains in place.

## Non-Goals

- Do not change the main pipeline boundary in `pipeline.py`
- Do not change the line-based table extraction path
- Do not change the PyMuPDF fallback path
- Do not change `LayoutBuilder` behavior
- Do not fully rewrite `_extract_via_text_alignment()`
- Do not let `text_region_detector` become responsible for final column/cell construction in this step

## Current Flow

Today the relevant borderless-table flow is:

```text
page.get_text("words")
-> _collect_text_rows(words)
-> _collect_text_candidate_regions(rows, page_bbox)
-> _merge_header_like_span(...)
-> _trim_span_to_structured_rows(...)
-> _infer_column_guides(region_rows)
-> token-to-column assignment
-> Cell / Table
```

This proposal replaces `_collect_text_candidate_regions(...)` with a region-detector-backed stage while preserving the rest of the flow.

## Proposed Design

### Integration Point

Keep integration inside `TableExtractor.extract()` by modifying only the internal implementation of `_extract_via_text_alignment()`. `Pipeline.run()` remains unchanged and still calls `TableExtractor.extract()` as it does today.

### New Internal Boundary

Introduce a new helper in `table_extractor.py`:

- `_detect_text_regions(rows, page) -> list[dict]`

This helper is the adapter between `table_extractor` row dictionaries and `text_region_detector`.

### Responsibilities of `_detect_text_regions`

`_detect_text_regions(rows, page)` should:

1. Convert `_collect_text_rows()` output into the row/fragment shape expected by `text_region_detector`
2. Optionally derive horizontal separator hints from the page when available
3. Call `detect_candidate_regions(...)`
4. Map each returned `CandidateRegion` back to the original row dictionaries used by `table_extractor`
5. Return region records compatible with the rest of `_extract_via_text_alignment()`

The returned region records should contain, at minimum:

- `rows`: the original row dict objects for the detected span
- `bbox`: union bbox of the participating rows

No new column structure should be produced at this stage.

## Detailed Data Flow

The new borderless-table flow becomes:

```text
page.get_text("words")
-> _collect_text_rows(words)
-> _detect_text_regions(rows, page)
-> for each region:
   -> _merge_header_like_span(...)
   -> _trim_span_to_structured_rows(...)
   -> _infer_column_guides(region_rows)
   -> token-to-column assignment
   -> Cell / Table
```

This preserves existing guide inference and cell construction semantics while making region discovery explicit and replaceable.

## Adapter Design

### Row Conversion

`_collect_text_rows()` already returns row dictionaries with token lists and row bbox information. The adapter should construct lightweight visual rows for `text_region_detector` from those same values.

Each visual row should preserve:

- row bbox
- token text
- token bbox
- token order within the row

The adapter must also maintain a stable mapping from each visual row back to the original row dict instance. This mapping is the key to converting `CandidateRegion.rows` back into `table_extractor` spans without re-parsing text.

### Separator Hints

If practical, `_detect_text_regions()` may pass horizontal separators into `detect_candidate_regions(...)`.

In this step, separator extraction should remain conservative:

- use only strong horizontal visual separators
- avoid adding soft or speculative separators
- if separator extraction is unavailable or unreliable, pass none

The region detector must still work without separator hints.

### Region Mapping

After `detect_candidate_regions(...)` returns candidate regions:

- map detector rows back to original row dicts
- compute region bbox from the mapped rows, not from an expanded heuristic bbox
- preserve row order exactly as it appears in `_collect_text_rows()`

This prevents downstream logic from operating on synthetic or reordered rows.

## Why This Design

This design keeps the refactor narrow and testable:

- `text_region_detector` owns region discovery
- `table_extractor` still owns table assembly
- the wired-table path is untouched
- the ML and PyMuPDF branches are untouched
- the existing borderless-table post-processing logic remains the same

This is the smallest change that meaningfully integrates the new module and establishes a cleaner boundary for later refactors.

## Rejected Alternatives

### Alternative 1: Replace only when no prior table path succeeds

Rejected because the product direction is to make region detection the default entry for the borderless-table path, not a narrow fallback.

### Alternative 2: Hide the detector inside `_collect_text_candidate_regions()`

Rejected because it would preserve the old abstraction while mixing old and new heuristics behind the same interface. That would make future cleanup harder.

### Alternative 3: Fully rewrite `_extract_via_text_alignment()`

Rejected for the first step because it would expand the regression surface too much. Column inference and cell construction should be refactored only after the region boundary is stable.

## Impact on Wired Tables

This change should not directly alter wired-table extraction because:

- line-based extraction still runs first
- PyMuPDF fallback still runs independently
- the integration point is only inside `_extract_via_text_alignment()`

Indirect risk still exists:

- region bbox changes can affect overlap-based deduplication
- region bbox changes can affect later text filtering in `LayoutBuilder`

For that reason, region bbox must be derived strictly from the participating rows and must not be expanded in this step.

## Risks

### Row Structure Mismatch

`text_region_detector` operates on visual rows and fragments, while `table_extractor` uses row dictionaries and token dictionaries. A mismatch here could cause region hits that cannot be mapped back cleanly.

Mitigation:

- build a one-to-one adapter layer
- keep original row dicts as the source of truth
- add mapping-focused tests

### Over-Broad Region Boxes

If detected regions grow beyond the actual structured rows, later layout filtering may hide prose text incorrectly.

Mitigation:

- compute region bbox from mapped rows only
- avoid region padding in this step

### Behavioral Drift in Borderless Tables

Changing candidate region selection may change row spans, which can alter inferred column guides and final cell grouping.

Mitigation:

- keep downstream logic unchanged
- add regression coverage for representative borderless-table layouts

## Testing Strategy

### 1. Region Adapter Tests

Add tests around the new `_detect_text_regions()` integration layer to verify:

- detector output maps back to the correct original row span
- mapped rows preserve original order
- mapped bbox matches the union of original rows

### 2. Borderless Table Integration Tests

Add or update `tests/test_table_extractor.py` coverage for:

- generic sparse aligned table text
- long Chinese financial table text
- header span merged into table body
- separator-assisted multi-section table region

Assertions should focus on final table shape and cell content, not only intermediate region count.

### 3. False-Positive Protection

Keep regression coverage for:

- prose with repeated numbers
- dense narrative rows
- partial alignment patterns that should not become tables

### 4. Wired-Path Safety

Run affected wired-table tests to confirm that integrating the detector into the borderless path does not change line-based outcomes.

## Implementation Notes

Expected implementation sequence:

1. Add `_detect_text_regions(rows, page)` adapter
2. Wire `_extract_via_text_alignment()` to call it instead of `_collect_text_candidate_regions(...)`
3. Preserve existing downstream header/trim/guide/cell logic
4. Add adapter-focused tests
5. Update borderless-table regression tests
6. Run affected `pytest` targets

## Future Follow-Ups

Once this integration is stable, later refactors can evaluate:

- moving more header handling into the region-discovery stage
- replacing `_infer_column_guides()` with a region-aware guide builder
- using detector features as confidence inputs for final table acceptance
- simplifying or removing legacy `_collect_text_candidate_regions(...)`

## Success Criteria

This design is successful when:

- `text_region_detector` participates every time `_extract_via_text_alignment()` runs
- the wired-table path remains unchanged in behavior
- borderless-table extraction becomes cleaner in structure
- existing borderless-table coverage still passes or is updated only where the new region boundary is intentionally better
- the code has a clear separation between region discovery and region-internal table assembly
