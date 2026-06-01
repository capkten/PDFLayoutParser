# Table Layout Rule System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a layout-driven table rule system that separates region and structure processing, supports JSON-configured profiles for common cases, and supports registered Python handlers for complex table layouts.

**Architecture:** Keep `TableExtractor.extract()` as the only public table entry point, but refactor it into a coordinator over four new units: config loading, profile matching, region rule application, and structure rule application. Existing line-based and text-aligned extraction remain the base pipeline; layout rules only enhance and correct their outputs.

**Tech Stack:** Python 3.10+, dataclasses, pytest, PyMuPDF, argparse, JSON

---

## File Structure

| Action | File | Responsibility |
|------|------|------|
| Create | `src/hexai_pdf_parser/table_config.py` | Global table config, layout profiles, JSON loading |
| Create | `src/hexai_pdf_parser/table_profile_matcher.py` | Match page/profile by keywords, order, distance, score |
| Create | `src/hexai_pdf_parser/table_region_rules.py` | Parameter-based region correction |
| Create | `src/hexai_pdf_parser/table_structure_rules.py` | Parameter-based structure correction |
| Create | `src/hexai_pdf_parser/table_rule_handlers.py` | Registered Python handlers for complex rules |
| Modify | `src/hexai_pdf_parser/table_extractor.py` | Wire in config, matcher, region/structure rule flow |
| Modify | `src/hexai_pdf_parser/text_region_detector.py` | Consume extracted config instead of local hardcoded thresholds where needed |
| Modify | `src/hexai_pdf_parser/pipeline.py` | Pass optional `table_config` into `TableExtractor` |
| Modify | `src/hexai_pdf_parser/cli.py` | Add `--table-config` option |
| Modify | `src/hexai_pdf_parser/__init__.py` | Export `TableConfig` if public API needs it |
| Create | `tests/test_table_config.py` | Config model and JSON loading tests |
| Create | `tests/test_table_profile_matcher.py` | Profile matching tests |
| Create | `tests/test_table_region_rules.py` | Region rule tests |
| Create | `tests/test_table_structure_rules.py` | Structure rule tests |
| Modify | `tests/test_table_extractor.py` | Integration and regression tests for extractor orchestration |
| Modify | `tests/test_pipeline.py` | Config pass-through tests |

---

### Task 1: Add table config data model and JSON loading

**Files:**
- Create: `src/hexai_pdf_parser/table_config.py`
- Create: `tests/test_table_config.py`
- Modify: `src/hexai_pdf_parser/__init__.py`

- [ ] Define config dataclasses for global settings, matcher config, region rule set, structure rule set, and layout profiles.
- [ ] Implement UTF-8 JSON loading with defaults and validation for missing/unknown fields.
- [ ] Expose a `TableConfig.load(path)` helper and a `TableConfig.default()` helper.
- [ ] Add tests covering default construction, JSON loading, invalid profile schema, and handler name preservation.
- [ ] Run `pytest tests/test_table_config.py -v`.
- [ ] Commit with `feat: add table rule config models`.

### Task 2: Add layout profile matcher

**Files:**
- Create: `src/hexai_pdf_parser/table_profile_matcher.py`
- Create: `tests/test_table_profile_matcher.py`
- Read: `src/hexai_pdf_parser/table_extractor.py`

- [ ] Define a page/profile matching input that carries normalized text lines, keyword positions, and optional header candidates.
- [ ] Implement keyword presence scoring for `required_keywords`, `optional_keywords`, and `forbidden_keywords`.
- [ ] Implement order and distance checks for header-like keyword sequences.
- [ ] Implement score ranking using `priority` and `min_match_score`.
- [ ] Add tests for exact match, optional keyword boost, forbidden keyword rejection, order mismatch, and profile priority tie-break.
- [ ] Run `pytest tests/test_table_profile_matcher.py -v`.
- [ ] Commit with `feat: add layout profile matcher`.

### Task 3: Add parameter-based region rule engine

**Files:**
- Create: `src/hexai_pdf_parser/table_region_rules.py`
- Create: `tests/test_table_region_rules.py`
- Read: `src/hexai_pdf_parser/text_region_detector.py`
- Read: `src/hexai_pdf_parser/table_extractor.py`

- [ ] Define an internal `TableRegionCandidate` model in the rule module or extractor-private area.
- [ ] Implement region expansion from matched keyword anchors and repeated row windows.
- [ ] Implement downward expansion, termination by stop keywords such as `注`, `说明`, `单位`, and adjacent region merge by distance.
- [ ] Keep region rules independent from cell/grid reconstruction.
- [ ] Add tests for anchor-based region generation, stop-key truncation, region merge, and disabled rule behavior.
- [ ] Run `pytest tests/test_table_region_rules.py -v`.
- [ ] Commit with `feat: add parameter-based table region rules`.

### Task 4: Add parameter-based structure rule engine

**Files:**
- Create: `src/hexai_pdf_parser/table_structure_rules.py`
- Create: `tests/test_table_structure_rules.py`
- Read: `src/hexai_pdf_parser/table_extractor.py`
- Read: `src/hexai_pdf_parser/models.py`

- [ ] Define an internal `TableStructureCandidate` model carrying rows, header rows, guides, cells, and diagnostics.
- [ ] Implement profile-driven header row identification and main-column selection.
- [ ] Implement simple structure corrections such as trailing summary/page row trimming, numeric-column bias, and narrow header split hints.
- [ ] Keep structure rules independent from page-level region candidate generation.
- [ ] Add tests for header row selection, main-column selection, trailing row trimming, and no-op behavior when profile rules are absent.
- [ ] Run `pytest tests/test_table_structure_rules.py -v`.
- [ ] Commit with `feat: add parameter-based table structure rules`.

### Task 5: Add registered complex rule handlers

**Files:**
- Create: `src/hexai_pdf_parser/table_rule_handlers.py`
- Modify: `tests/test_table_config.py`
- Modify: `tests/test_table_region_rules.py`
- Modify: `tests/test_table_structure_rules.py`

- [ ] Define `REGION_RULE_HANDLERS` and `STRUCTURE_RULE_HANDLERS` registries.
- [ ] Implement lookup helpers that return callable handlers by name and raise clear errors for unknown names.
- [ ] Add one small built-in sample handler used only for tests.
- [ ] Add tests that verify handler lookup, unknown handler failure, and combined parameter+handler flow.
- [ ] Run the affected test modules.
- [ ] Commit with `feat: add registered table rule handlers`.

### Task 6: Refactor table extractor into coordinator flow

**Files:**
- Modify: `src/hexai_pdf_parser/table_extractor.py`
- Modify: `tests/test_table_extractor.py`

- [ ] Update `TableExtractor.__init__` to accept an optional `table_config` object while preserving backward-compatible scalar args.
- [ ] Add feature collection helpers for page text rows, keyword anchors, and candidate diagnostics without changing public output schema.
- [ ] Run existing base extraction first, then profile matching, then region rules, then structure rules, then optional handlers.
- [ ] Keep behavior unchanged when no profile/config is supplied.
- [ ] Add integration tests for no-config parity, profile-matched region correction, profile-matched structure correction, and handler invocation.
- [ ] Run `pytest tests/test_table_extractor.py -v`.
- [ ] Commit with `feat: integrate layout rule system into table extractor`.

### Task 7: Propagate config through pipeline and CLI

**Files:**
- Modify: `src/hexai_pdf_parser/pipeline.py`
- Modify: `src/hexai_pdf_parser/cli.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_cli.py`

- [ ] Add optional `table_config` path/object support to `Pipeline`.
- [ ] Ensure `Pipeline` builds `TableExtractor(table_config=...)`.
- [ ] Add CLI argument `--table-config` and load JSON with UTF-8.
- [ ] Add tests covering pipeline pass-through and CLI argument parsing.
- [ ] Run `pytest tests/test_pipeline.py tests/test_cli.py -v`.
- [ ] Commit with `feat: wire table config through pipeline and cli`.

### Task 8: Replace selected hardcoded thresholds with config-backed values

**Files:**
- Modify: `src/hexai_pdf_parser/table_extractor.py`
- Modify: `src/hexai_pdf_parser/text_region_detector.py`
- Modify: `tests/test_table_extractor.py`

- [ ] Move the currently exposed thresholds into `TableConfig` defaults.
- [ ] Replace the first batch of stable hardcoded thresholds used by text-region detection and fallback heuristics with config-backed fields.
- [ ] Leave highly experimental heuristics alone if they cannot yet be grouped cleanly under stable config names.
- [ ] Add regression tests verifying default behavior parity and one config override scenario.
- [ ] Run focused table tests.
- [ ] Commit with `refactor: back stable table thresholds with config`.

### Task 9: Add end-to-end regression coverage

**Files:**
- Modify: `tests/test_table_extractor.py`
- Modify: `tests/test_pipeline.py`

- [ ] Add one synthetic PDF case showing a pure config-driven profile improves region detection.
- [ ] Add one synthetic PDF case showing a registered structure handler improves table shape.
- [ ] Add one regression case confirming line-based tables remain unchanged without profile rules.
- [ ] Run `pytest tests/test_table_extractor.py tests/test_pipeline.py -v`.
- [ ] Commit with `test: add end-to-end table rule regressions`.

### Task 10: Update docs for users and maintainers

**Files:**
- Modify: `README.md`
- Modify: `docs/algorithm.md`
- Optionally modify: `docs/api-reference.md`

- [ ] Document the new config file entry point and the difference between parameter rules and handler rules.
- [ ] Document the execution order: base extraction, profile match, region rules, structure rules, handlers.
- [ ] Add one minimal JSON example for a layout profile and one short note on registering a custom handler.
- [ ] Run the relevant test commands again after doc-linked code changes, if any.
- [ ] Commit with `docs: describe table layout rule system`.

---

## Verification Checklist

- [ ] `pytest tests/test_table_config.py tests/test_table_profile_matcher.py -v`
- [ ] `pytest tests/test_table_region_rules.py tests/test_table_structure_rules.py -v`
- [ ] `pytest tests/test_table_extractor.py tests/test_pipeline.py tests/test_cli.py -v`
- [ ] `pytest`

---

## Notes for Execution

- Keep `TableExtractor.extract()` as the only end-to-end table entry point.
- Do not change `Table` / `Cell` public schema in the first iteration.
- Prefer extractor-private intermediate objects for rule processing.
- Default behavior with no `table_config` must stay compatible with current output.
- Complex layout handlers should be registered explicitly, not imported from arbitrary strings.
