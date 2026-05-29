"""Parameter-based table region rule engine.

Applies region-level corrections to candidate table regions based on a matched
layout profile's :class:`RegionRuleSet`.  This module is independent from
cell/grid reconstruction — it only adjusts which regions are considered and
how their bounding boxes are expanded or trimmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hexai_pdf_parser.models import BBox
from hexai_pdf_parser.table_config import RegionRuleSet


@dataclass
class TableRegionCandidate:
    """An intermediate region produced during rule processing."""

    bbox: BBox
    rows: List[Dict[str, Any]]
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def _find_anchor_regions(
    rows: List[Dict[str, Any]],
    anchors: List[str],
    min_row_window: int,
) -> List[TableRegionCandidate]:
    """Find regions anchored by keyword occurrences.

    Each anchor keyword defines a potential start row.  From there, expand
    downward by *min_row_window* rows to form a candidate region.
    """
    if not rows or not anchors:
        return []

    candidates: List[TableRegionCandidate] = []
    for row_idx, row in enumerate(rows):
        tokens = row.get("tokens", [])
        row_text = " ".join(t.get("text", "") for t in tokens)
        for anchor in anchors:
            if anchor in row_text:
                end_idx = min(row_idx + min_row_window, len(rows))
                region_rows = rows[row_idx:end_idx]
                bbox = _rows_bbox(region_rows)
                candidates.append(
                    TableRegionCandidate(
                        bbox=bbox,
                        rows=region_rows,
                        diagnostics={"anchor": anchor, "start_row": row_idx},
                    )
                )

    return candidates


def _expand_downward(
    candidate: TableRegionCandidate,
    all_rows: List[Dict[str, Any]],
    stop_keywords: List[str],
) -> TableRegionCandidate:
    """Expand a candidate region downward until a stop keyword is found."""
    if not candidate.rows or not all_rows:
        return candidate

    start_y = candidate.bbox.y1
    expanded_rows = list(candidate.rows)

    # Find the index of the last row in the candidate
    last_row_id = id(candidate.rows[-1])
    start_idx = next(
        (i for i, r in enumerate(all_rows) if id(r) == last_row_id),
        len(all_rows) - 1,
    )

    for row in all_rows[start_idx + 1 :]:
        tokens = row.get("tokens", [])
        row_text = " ".join(t.get("text", "") for t in tokens)
        if any(kw in row_text for kw in stop_keywords):
            break
        expanded_rows.append(row)

    if len(expanded_rows) > len(candidate.rows):
        bbox = _rows_bbox(expanded_rows)
        return TableRegionCandidate(
            bbox=bbox,
            rows=expanded_rows,
            diagnostics={**candidate.diagnostics, "expanded": True},
        )

    return candidate


def _merge_nearby_candidates(
    candidates: List[TableRegionCandidate],
    merge_distance: float,
) -> List[TableRegionCandidate]:
    """Merge candidates whose bboxes are within *merge_distance* vertically."""
    if len(candidates) <= 1:
        return candidates

    sorted_candidates = sorted(candidates, key=lambda c: c.bbox.y0)
    merged: List[TableRegionCandidate] = [sorted_candidates[0]]

    for candidate in sorted_candidates[1:]:
        prev = merged[-1]
        gap = candidate.bbox.y0 - prev.bbox.y1
        if gap <= merge_distance:
            combined_rows = prev.rows + candidate.rows
            merged[-1] = TableRegionCandidate(
                bbox=_rows_bbox(combined_rows),
                rows=combined_rows,
                diagnostics={**prev.diagnostics, "merged": True},
            )
        else:
            merged.append(candidate)

    return merged


def _rows_bbox(rows: List[Dict[str, Any]]) -> BBox:
    """Compute a tight bounding box around a list of row dicts."""
    if not rows:
        return BBox(0, 0, 0, 0)
    return BBox(
        min(r.get("x0", 0) for r in rows),
        min(r.get("y0", 0) for r in rows),
        max(r.get("x1", 0) for r in rows),
        max(r.get("y1", 0) for r in rows),
    )


def apply_region_rules(
    rules: RegionRuleSet,
    all_rows: List[Dict[str, Any]],
    existing_regions: Optional[List[TableRegionCandidate]] = None,
) -> List[TableRegionCandidate]:
    """Apply parameter-based region rules to produce corrected regions.

    If *existing_regions* is provided, they are returned unchanged (the rules
    supplement, not replace, the base pipeline).  Otherwise anchor-based
    detection is used.
    """
    if not rules.enabled:
        return existing_regions or []

    # If anchors are defined, generate candidates from keyword positions
    candidates: List[TableRegionCandidate] = []
    if rules.expand_anchors:
        candidates = _find_anchor_regions(
            all_rows, rules.expand_anchors, rules.min_row_window
        )

        # Expand each candidate downward
        for i, candidate in enumerate(candidates):
            if rules.stop_keywords:
                candidates[i] = _expand_downward(
                    candidate, all_rows, rules.stop_keywords
                )

        # Merge nearby regions
        candidates = _merge_nearby_candidates(candidates, rules.merge_distance)

    # If existing regions were provided and no anchor-based candidates were
    # generated, return existing regions unmodified.
    if not candidates and existing_regions:
        return existing_regions

    return candidates
