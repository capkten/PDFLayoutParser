"""Recursive XY-Cut based reading order sorting for document layouts.

Provides universal topological reading order determination (top-to-bottom,
column-by-column, multi-column with full-width headers/footers) for layout
elements and text blocks.
"""

from __future__ import annotations

from typing import Any, Callable, List, Sequence, TypeVar

from hexai_pdf_parser.core.models import BBox

T = TypeVar("T")


def _default_get_bbox(item: Any) -> BBox:
    if hasattr(item, "bbox"):
        return item.bbox
    if isinstance(item, dict) and "bbox" in item:
        b = item["bbox"]
        if isinstance(b, BBox):
            return b
        return BBox(*b)
    if isinstance(item, (list, tuple)) and len(item) == 4:
        return BBox(*item)
    raise ValueError(f"Cannot extract BBox from item: {item}")


def _find_projection_cuts(
    intervals: List[tuple[float, float]],
    min_gap: float,
) -> List[float]:
    """Find split positions between disjoint projection intervals with at least min_gap separation."""
    if not intervals:
        return []

    sorted_intervals = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    merged: List[tuple[float, float]] = []

    for start, end in sorted_intervals:
        if not merged:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

    cuts: List[float] = []
    for i in range(len(merged) - 1):
        gap = merged[i + 1][0] - merged[i][1]
        if gap >= min_gap:
            cuts.append((merged[i][1] + merged[i + 1][0]) / 2.0)

    return cuts


def _is_valid_column_partition(
    cols: List[List[T]],
    bboxes_by_col: List[List[BBox]],
    total_w: float,
    min_col_width: float = 30.0,
    min_col_ratio: float = 0.15,
) -> bool:
    """Check if vertical partition forms legitimate multi-column layout rather than inline labels/numbers."""
    if len(cols) < 2:
        return False

    for col_items, col_bboxes in zip(cols, bboxes_by_col):
        if not col_items:
            return False
        col_w = max(b.x1 for b in col_bboxes) - min(b.x0 for b in col_bboxes)
        if col_w < min_col_width and (col_w / total_w) < min_col_ratio:
            return False

    return True


def _has_spanning_element(bboxes: List[BBox]) -> bool:
    """Check if any element spans across a significant portion of the total layout width."""
    if not bboxes:
        return False
    min_x = min(b.x0 for b in bboxes)
    max_x = max(b.x1 for b in bboxes)
    total_w = max_x - min_x
    if total_w <= 0:
        return False

    for b in bboxes:
        w = b.x1 - b.x0
        if w >= 0.65 * total_w:
            return True
    return False


def _recursive_xy_cut(
    items: List[T],
    get_bbox: Callable[[T], BBox],
    min_y_gap: float = 1.0,
    min_x_gap: float = 5.0,
) -> List[T]:
    if len(items) <= 1:
        return list(items)

    bboxes = [get_bbox(item) for item in items]
    min_x = min(b.x0 for b in bboxes)
    max_x = max(b.x1 for b in bboxes)
    total_w = max_x - min_x

    has_spanning = _has_spanning_element(bboxes)

    x_intervals = [(b.x0, b.x1) for b in bboxes]
    x_cuts = _find_projection_cuts(x_intervals, min_gap=min_x_gap)

    # 1. Check if valid multi-column X-cut exists and no spanning elements present
    if not has_spanning and x_cuts:
        cols: List[List[T]] = [[] for _ in range(len(x_cuts) + 1)]
        bboxes_by_col: List[List[BBox]] = [[] for _ in range(len(x_cuts) + 1)]
        for item, b in zip(items, bboxes):
            mid_x = (b.x0 + b.x1) / 2.0
            assigned = False
            for idx, cut in enumerate(x_cuts):
                if mid_x < cut:
                    cols[idx].append(item)
                    bboxes_by_col[idx].append(b)
                    assigned = True
                    break
            if not assigned:
                cols[-1].append(item)
                bboxes_by_col[-1].append(b)

        if _is_valid_column_partition(cols, bboxes_by_col, total_w):
            result: List[T] = []
            for col in cols:
                if col:
                    result.extend(_recursive_xy_cut(col, get_bbox, min_y_gap, min_x_gap))
            return result

    # 2. Try horizontal cut (Y-axis projection / line bands)
    y_intervals = [(b.y0, b.y1) for b in bboxes]
    y_cuts = _find_projection_cuts(y_intervals, min_gap=min_y_gap)

    if y_cuts:
        bands: List[List[T]] = [[] for _ in range(len(y_cuts) + 1)]
        for item, b in zip(items, bboxes):
            mid_y = (b.y0 + b.y1) / 2.0
            assigned = False
            for idx, cut in enumerate(y_cuts):
                if mid_y < cut:
                    bands[idx].append(item)
                    assigned = True
                    break
            if not assigned:
                bands[-1].append(item)

        result: List[T] = []
        for band in bands:
            if band:
                result.extend(_recursive_xy_cut(band, get_bbox, min_y_gap, min_x_gap))
        return result

    # 3. If no horizontal cut possible, try X-Cut ONLY if valid column partition
    if x_cuts:
        cols = [[] for _ in range(len(x_cuts) + 1)]
        bboxes_by_col = [[] for _ in range(len(x_cuts) + 1)]
        for item, b in zip(items, bboxes):
            mid_x = (b.x0 + b.x1) / 2.0
            assigned = False
            for idx, cut in enumerate(x_cuts):
                if mid_x < cut:
                    cols[idx].append(item)
                    bboxes_by_col[idx].append(b)
                    assigned = True
                    break
            if not assigned:
                cols[-1].append(item)
                bboxes_by_col[-1].append(b)

        if _is_valid_column_partition(cols, bboxes_by_col, total_w):
            result = []
            for col in cols:
                if col:
                    result.extend(_recursive_xy_cut(col, get_bbox, min_y_gap, min_x_gap))
            return result

    # 4. Fallback: Sort by (y0, x0, y1, x1)
    return sorted(
        items,
        key=lambda item: (
            get_bbox(item).y0,
            get_bbox(item).x0,
            get_bbox(item).y1,
            get_bbox(item).x1,
        ),
    )


def sort_by_reading_order(
    items: Sequence[T],
    get_bbox_fn: Callable[[T], BBox] | None = None,
    min_y_gap: float = 0.0,
    min_x_gap: float = 5.0,
) -> List[T]:
    """Sort elements in natural reading order using Recursive XY-Cut."""
    if not items:
        return []
    getter = get_bbox_fn or _default_get_bbox
    return _recursive_xy_cut(list(items), getter, min_y_gap=min_y_gap, min_x_gap=min_x_gap)
