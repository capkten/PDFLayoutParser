"""Prototype borderless-table region detector built on visual rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hexai_pdf_parser.models import BBox


@dataclass
class CandidateRegion:
    """Candidate borderless-table region formed by one or more visual rows."""

    rows: list[Any]
    bbox: BBox
    features: dict[str, Any]
    score: float

    @staticmethod
    def bbox_union(boxes: list[BBox]) -> BBox:
        """Return the union box for the given bounding boxes."""
        return BBox(
            min(box.x0 for box in boxes),
            min(box.y0 for box in boxes),
            max(box.x1 for box in boxes),
            max(box.y1 for box in boxes),
        )


@dataclass
class HorizontalSeparator:
    """A lightweight horizontal separator hint on the page."""

    x0: float
    x1: float
    y: float


def _is_numeric_text(text: str) -> bool:
    stripped = text.replace(",", "").replace("%", "").replace(".", "").replace("-", "")
    return bool(stripped) and stripped.isdigit()


def _row_anchor_signature(row: Any) -> list[float]:
    return [round(fragment.bbox.x0 / 10.0) * 10.0 for fragment in row.fragments]


def _count_repeated_alignments(rows: list[Any]) -> int:
    guide_hits: dict[float, int] = {}
    for row in rows:
        for anchor in _row_anchor_signature(row):
            guide_hits[anchor] = guide_hits.get(anchor, 0) + 1
    return sum(1 for count in guide_hits.values() if count >= 2)


def _count_numeric_columns(rows: list[Any]) -> int:
    column_hits: dict[int, int] = {}
    for row in rows:
        for idx, fragment in enumerate(row.fragments):
            if _is_numeric_text(fragment.text):
                column_hits[idx] = column_hits.get(idx, 0) + 1
    return sum(1 for count in column_hits.values() if count >= 2)


def _row_is_candidate(row: Any) -> bool:
    score = score_row_structure(row)
    return score["looks_sparse"] or score["looks_structured"]


def _can_attach_bridge(anchor_row: Any, bridge_row: Any) -> bool:
    gap = bridge_row.bbox.y0 - anchor_row.bbox.y1
    anchor_height = max(anchor_row.bbox.y1 - anchor_row.bbox.y0, 1.0)
    bridge_height = max(bridge_row.bbox.y1 - bridge_row.bbox.y0, 1.0)
    max_gap = max(min(anchor_height, bridge_height) * 1.8, 12.0)
    return gap <= max_gap


def _group_contiguous_runs(rows: list[Any]) -> list[list[Any]]:
    runs: list[list[Any]] = []
    current: list[Any] = []
    pending_bridge: list[Any] = []
    for row in rows:
        if _row_is_candidate(row):
            if current and pending_bridge:
                if _can_attach_bridge(current[-1], pending_bridge[0]):
                    current.extend(pending_bridge)
                pending_bridge = []
            current.append(row)
            continue
        if current:
            score = score_row_structure(row)
            anchor_row = pending_bridge[-1] if pending_bridge else current[-1]
            if (
                score["fragment_count"] == 1
                and len(pending_bridge) < 2
                and _can_attach_bridge(anchor_row, row)
            ):
                pending_bridge.append(row)
                continue
            if pending_bridge and _can_attach_bridge(current[-1], pending_bridge[0]):
                current.extend(pending_bridge)
            runs.append(current)
            current = []
            pending_bridge = []
    if current:
        if pending_bridge and _can_attach_bridge(current[-1], pending_bridge[0]):
            current.extend(pending_bridge)
        runs.append(current)
    return [run for run in runs if len(run) >= 2]


def _merge_runs_across_separators(
    all_rows: list[Any],
    runs: list[list[Any]],
    horizontal_separators: list[HorizontalSeparator],
) -> list[list[Any]]:
    if len(runs) < 2 or not horizontal_separators:
        return runs

    row_index = {id(row): idx for idx, row in enumerate(all_rows)}
    merged_runs: list[list[Any]] = []
    i = 0
    while i < len(runs):
        current = runs[i]
        if i + 1 >= len(runs):
            merged_runs.append(current)
            break

        nxt = runs[i + 1]
        current_start = row_index[id(current[0])]
        current_end = row_index[id(current[-1])]
        next_start = row_index[id(nxt[0])]
        next_end = row_index[id(nxt[-1])]

        separator = _find_separator_between_runs(current, nxt, horizontal_separators)
        if separator is not None:
            combined = all_rows[current_start : next_end + 1]
            if _count_repeated_alignments(combined) >= 2:
                merged_runs.append(combined)
                i += 2
                continue

        merged_runs.append(current)
        i += 1

    return merged_runs


def _find_separator_between_runs(
    upper_run: list[Any],
    lower_run: list[Any],
    separators: list[HorizontalSeparator],
) -> HorizontalSeparator | None:
    upper_bottom = max(row.bbox.y1 for row in upper_run)
    lower_top = min(row.bbox.y0 for row in lower_run)
    upper_left = min(row.bbox.x0 for row in upper_run)
    upper_right = max(row.bbox.x1 for row in upper_run)
    lower_left = min(row.bbox.x0 for row in lower_run)
    lower_right = max(row.bbox.x1 for row in lower_run)
    overlap = min(upper_right, lower_right) - max(upper_left, lower_left)
    min_width = max(min(upper_right - upper_left, lower_right - lower_left), 1.0)
    if overlap / min_width < 0.35:
        return None

    for separator in separators:
        if upper_bottom <= separator.y <= lower_top:
            if separator.y - upper_bottom > 24:
                continue
            if lower_top - separator.y > 40:
                continue
            if separator.x1 - separator.x0 < min_width * 0.4:
                continue
            return separator
    return None


def _expand_region_with_nearby_header_rows(all_rows: list[Any], run: list[Any]) -> list[Any]:
    if not run:
        return run

    row_index = {id(row): idx for idx, row in enumerate(all_rows)}
    start_idx = row_index[id(run[0])]
    if start_idx == 0:
        return run

    candidate = all_rows[start_idx - 1]
    candidate_score = score_row_structure(candidate)
    if candidate_score["fragment_count"] < 2:
        return run

    first_row = run[0]
    gap = first_row.bbox.y0 - candidate.bbox.y1
    first_height = max(first_row.bbox.y1 - first_row.bbox.y0, 1.0)
    candidate_height = max(candidate.bbox.y1 - candidate.bbox.y0, 1.0)
    if gap > max(first_height, candidate_height):
        return run

    combined = [candidate] + run
    if candidate_score["fragment_count"] >= 3 and _count_repeated_alignments(combined) >= 2:
        return combined
    if _count_repeated_alignments(combined) < 2:
        combined_scores = [score_row_structure(row) for row in combined]
        structured_row_count = sum(
            1 for score in combined_scores if score["looks_structured"]
        )
        strong_numeric_row_count = sum(
            1 for score in combined_scores if score["numeric_fragment_count"] >= 2
        )
        if structured_row_count < 3 or strong_numeric_row_count < 1:
            return run
    return combined


def score_row_structure(row: Any) -> dict[str, Any]:
    """Score a visual row for sparse, table-like structure."""
    fragment_count = len(row.fragments)
    widths = [fragment.bbox.x1 - fragment.bbox.x0 for fragment in row.fragments]
    row_width = max(row.bbox.x1 - row.bbox.x0, 1.0)
    coverage = sum(widths) / row_width if row_width else 0.0
    numeric_fragment_count = sum(
        1 for fragment in row.fragments if _is_numeric_text(fragment.text)
    )
    return {
        "fragment_count": fragment_count,
        "coverage": coverage,
        "numeric_fragment_count": numeric_fragment_count,
        "looks_sparse": fragment_count >= 2 and coverage < 0.75,
        "looks_structured": fragment_count >= 3
        and (coverage < 0.85 or numeric_fragment_count >= 2),
    }


def detect_candidate_regions(
    rows: list[Any],
    horizontal_separators: list[HorizontalSeparator] | None = None,
) -> list[CandidateRegion]:
    """Return candidate regions built from contiguous table-like row runs."""
    regions: list[CandidateRegion] = []
    runs = _group_contiguous_runs(rows)
    if horizontal_separators:
        runs = _merge_runs_across_separators(rows, runs, horizontal_separators)

    for run in runs:
        run = _expand_region_with_nearby_header_rows(rows, run)
        scores = [score_row_structure(row) for row in run]
        sparse_row_count = sum(1 for score in scores if score["looks_sparse"])
        structured_row_count = sum(1 for score in scores if score["looks_structured"])
        strong_numeric_row_count = sum(
            1 for score in scores if score["numeric_fragment_count"] >= 2
        )
        repeated_alignment_count = _count_repeated_alignments(run)
        numeric_column_count = _count_numeric_columns(run)
        if max(sparse_row_count, structured_row_count) < 2:
            continue
        if repeated_alignment_count < 2 and not (
            structured_row_count >= 3
            and strong_numeric_row_count >= 1
            and len(run) >= 3
        ):
            continue

        regions.append(
            CandidateRegion(
                rows=run,
                bbox=CandidateRegion.bbox_union([row.bbox for row in run]),
                features={
                    "row_scores": scores,
                    "structured_row_count": structured_row_count,
                    "repeated_alignment_count": repeated_alignment_count,
                    "numeric_column_count": numeric_column_count,
                },
                score=float(
                    max(sparse_row_count, structured_row_count)
                    + repeated_alignment_count
                    + numeric_column_count
                ),
            )
        )
    return regions
