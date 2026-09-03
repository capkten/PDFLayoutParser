# Language-aware wireless table extraction

## Goal

Ensure zebra-background extraction is used only for English pages, while Chinese and mixed-language pages use the text-alignment wireless-table logic.

## Design

`TableExtractor.extract()` detects the page language once and passes it into model-region extraction. For each ML table region, wired results remain preferred. If no wired result overlaps:

- English (`en`): try zebra-background extraction, then fall back to text alignment.
- Chinese (`zh`) or mixed (`mixed`): skip zebra-background extraction and use text alignment directly.

The language decision stays in `TableExtractor`, which owns the page-level detection policy. `WirelessTableExtractor` receives the decision rather than independently classifying pages. Existing wired extraction and English zebra behavior remain unchanged.

## Verification

Add regression coverage for the two wireless branches. Run the focused table-extractor tests and the existing wired-table tests, then run the relevant page-level extraction check.
