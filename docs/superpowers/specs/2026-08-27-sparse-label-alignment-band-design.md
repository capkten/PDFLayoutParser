# Sparse Label Alignment Band Design

## Problem

Page 189 contains two wireless financial tables recovered as four columns even
though each table has three logical columns. The first inferred band contains
left-aligned body labels. The adjacent weak band contains only the centered
header and total labels. No row occupies both bands, and no physical vertical
separator exists between them.

This differs from the paired-CJK artifact handled for page 188: the page 189
atoms are already complete multi-character spans. The error is caused by two
alignment styles inside one logical label column, not by character splitting.

## Decision

Add a separate column-band cleanup rule before header topology annotation and
physical grid construction. The rule removes a weak alignment-only band when
all of the following structural evidence is present:

- the candidate is immediately right of a stronger left label band;
- the candidate has two or three supported y levels;
- the candidate and left band have mutually exclusive row occupancy;
- candidate levels lie outside the vertical range occupied by the left band,
  representing header/footer alignment rather than a parallel body field;
- the gap between the two bands is no more than 0.6 times the median font size;
- a stable band exists to the right and its gap is at least both three times
  the inner gap and 2.5 times the median font size;
- the left band has at least two supported body levels.

The rule is text-agnostic. It must not depend on words such as `项目` or `合计`.
After removing the candidate, bands are renumbered. Existing assignment logic
then maps its atoms to the remaining left band.

## Placement

Implement the rule in `wireless_structure/columns.py` beside the paired-CJK
band cleanup. Call it in `recoverer.py` after paired-CJK cleanup and before
`refine_leaf_bands()` and `annotate_columns()`.

This keeps recovery boundary-first. No cells are merged after grid creation,
and page words are not reread.

## Safety Cases

The rule must preserve:

- a real pair of narrow columns that both contain text on the same row;
- mutually exclusive sparse columns separated by a normal column gap;
- the already-correct three-column table on page 189, whose centered labels
  already overlap the body-label band;
- the existing page 188 paired-CJK behavior.

## Verification

Use test-first coverage at both the band and recoverer levels. Re-run page 189
from `fix/zh_all_table_pages.pdf` and verify table shapes `6x3`, `4x3`, and
`4x3`, complete non-overlapping occupancy, and the visualization. Run all
wireless-structure tests plus `git diff --check`.
