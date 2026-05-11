"""Table extractor module.

Detects tables on a PDF page using a line-projection approach:
1. Extract thin rectangles from page drawings as lines
2. Merge nearby lines (with tight tolerance to preserve grid structure)
3. Find cell grid from line intersections
4. Group connected cells into tables
5. Assign text to cells

For rectangle-based borders (WPS/Office), each cell border is a separate
thin rectangle. The merge step must only combine fragments of the SAME
border, not adjacent rows/columns.

Special handling for WPS/Office financial tables:
- Filled cell rectangles reveal actual sub-row structure (merged cells)
- Many narrow columns are used for number alignment
- We detect sub-rows from cell rectangles and merge over-segmented columns
"""

from collections import defaultdict
from typing import List, Set, Tuple

import fitz

from pdflayoutparser.models import BBox, Cell, Table


class TableExtractor:
    """Extract tables from a single PDF page using line-projection."""

    def __init__(
        self,
        line_tolerance: float = 2.0,
        merge_group_tol: float = 0.3,
        row_gap_threshold: float = 30.0,
        fallback_max_cols: int = 30,
        fallback_max_tables: int = 10,
    ):
        self.line_tolerance = line_tolerance
        self.merge_group_tol = merge_group_tol
        self.row_gap_threshold = row_gap_threshold
        self.fallback_max_cols = fallback_max_cols
        self.fallback_max_tables = fallback_max_tables

    def extract(self, page: fitz.Page) -> List[Table]:
        """Return a list of :class:`Table` objects detected on *page*."""
        tables = self._extract_via_lines(page)

        # Fallback to PyMuPDF if no tables or if line_projection produced
        # overly fragmented / wide tables (merged-cell layouts).
        if not tables:
            tables = self._extract_via_pymupdf(page)
        elif self._should_fallback(tables):
            fallback_tables = self._extract_via_pymupdf(page)
            if fallback_tables:
                tables = fallback_tables

        return tables

    def _should_fallback(self, tables: List[Table]) -> bool:
        """Return True if line_projection results look unreliable."""
        if not tables:
            return False
        if all(t.rows <= 1 and t.cols <= 1 for t in tables):
            return True
        total_cells = sum(len(t.cells) for t in tables)
        if total_cells <= len(tables):
            return True
        total_capacity = sum(max(t.rows * t.cols, 1) for t in tables)
        density = total_cells / total_capacity if total_capacity else 0

        # High column count alone is not enough to trigger fallback.
        # Only very wide and sparse tables are likely over-segmented.
        avg_cols = sum(t.cols for t in tables) / len(tables)
        if avg_cols > self.fallback_max_cols and density < 0.8:
            return True
        # Too many tiny tables also signals fragmentation.
        if len(tables) > self.fallback_max_tables:
            return True
        return False

    # ------------------------------------------------------------------
    # Line extraction from drawings
    # ------------------------------------------------------------------

    def _has_visible_stroke(self, path: dict) -> bool:
        """Return True when a drawing path has a visible stroke."""
        if path.get("type") not in {"s", "fs"}:
            return False

        stroke_opacity = path.get("stroke_opacity")
        if stroke_opacity is not None and stroke_opacity <= 0:
            return False

        width = path.get("width")
        if width is not None and width <= 0:
            return False

        return path.get("color") is not None

    def _is_visible_fill_line_rect(self, path: dict, rect: fitz.Rect) -> bool:
        """Return True for visible fill-only rectangles that behave like lines."""
        if path.get("type") != "f":
            return False

        fill_opacity = path.get("fill_opacity")
        if fill_opacity is not None and fill_opacity <= 0:
            return False

        if path.get("fill") is None:
            return False

        w, h = rect.width, rect.height
        return (
            (h < self.line_tolerance and w >= self.line_tolerance * 2)
            or (w < self.line_tolerance and h >= self.line_tolerance * 2)
        )

    def _is_blackish_fill(self, path: dict) -> bool:
        """Return True when a fill-only path has a black/near-black fill color.

        Gray cell-background rectangles (e.g. ~0.83 RGB) are excluded so they
        do not get decomposed into spurious border edges.
        """
        fill = path.get("fill")
        if fill is None:
            return False
        if isinstance(fill, (tuple, list)):
            return max(fill) <= 0.5
        return fill <= 0.5

    def _iter_visible_drawing_rects(self, page: fitz.Page):
        """Yield rectangle items that can contribute visible table borders."""
        try:
            drawings = page.get_drawings()
        except Exception:
            return

        for drawing in drawings:
            for item in drawing.get("items", []):
                if item[0] != "re":
                    continue

                rect = fitz.Rect(item[1])
                if self._has_visible_stroke(drawing) or self._is_visible_fill_line_rect(
                    drawing, rect
                ):
                    yield rect

    def _get_bboxlog(self, page: fitz.Page) -> List[Tuple]:
        """Return the page bbox log, or an empty list if unavailable."""
        try:
            return list(page.get_bboxlog())
        except Exception:
            return []

    def _is_rect_fully_covered_later(
        self,
        rect: fitz.Rect,
        seqno: int | None,
        bboxlog: List[Tuple],
    ) -> bool:
        """Return True if a later opaque paint operation fully covers *rect*.

        We use this as a conservative heuristic only for solid later content:
        fill paths, images, and shadings. Partial overlap should not hide the
        border candidate, but near-complete containment usually means the
        rectangle is not visually contributing to the final page appearance.
        """
        if seqno is None or not bboxlog:
            return False

        area = rect.get_area()
        if area <= 0:
            return False

        occluding_types = {"fill-path", "fill-image", "fill-shade"}
        for idx, entry in enumerate(bboxlog):
            if idx <= seqno or not entry:
                continue

            item_type = entry[0]
            if item_type not in occluding_types:
                continue

            cover_rect = fitz.Rect(entry[1])
            inter = rect & cover_rect
            if inter.is_empty:
                continue

            if inter.get_area() / area >= 0.98:
                return True

        return False

    def _iter_effective_drawing_rects(self, page: fitz.Page):
        """Yield (rect, drawing) for visible border rectangles not later occluded."""
        bboxlog = self._get_bboxlog(page)

        try:
            drawings = page.get_drawings()
        except Exception:
            return

        for drawing in drawings:
            seqno = drawing.get("seqno")
            for item in drawing.get("items", []):
                if item[0] != "re":
                    continue

                rect = fitz.Rect(item[1])
                if not (
                    self._has_visible_stroke(drawing)
                    or self._is_visible_fill_line_rect(drawing, rect)
                    or self._is_blackish_fill(drawing)
                ):
                    continue

                if self._is_rect_fully_covered_later(rect, seqno, bboxlog):
                    continue

                yield rect, drawing

    def _extract_lines_from_drawings_legacy(
        self, page: fitz.Page
    ) -> Tuple[List[Tuple], List[Tuple]]:
        """Extract thin rectangles from page drawings as horizontal/vertical lines.

        Also converts normal rectangles (cell backgrounds, merged cell borders)
        into their four edge lines, so that merged cells without internal lines
        can still be detected by the grid builder.
        """
        h_lines = []
        v_lines = []

        try:
            drawings = page.get_drawings()
        except Exception:
            return h_lines, v_lines

        page_area = page.rect.width * page.rect.height

        for d in drawings:
            for item in d.get("items", []):
                if item[0] != "re":
                    continue

                rect = fitz.Rect(item[1])
                w, h = rect.width, rect.height

                # Horizontal line-like rectangle: very short height, wide
                if h < self.line_tolerance and w >= self.line_tolerance * 2:
                    y = (rect.y0 + rect.y1) / 2
                    h_lines.append((rect.x0, y, rect.x1, y))
                # Vertical line-like rectangle: very short width, tall
                elif w < self.line_tolerance and h >= self.line_tolerance * 2:
                    x = (rect.x0 + rect.x1) / 2
                    v_lines.append((x, rect.y0, x, rect.y1))
                elif w >= self.line_tolerance and h >= self.line_tolerance:
                    # Normal rectangle (cell background, merged cell border, etc.)
                    # Convert its four edges to lines to unify handling.
                    # Skip overly large rectangles (page backgrounds, etc.)
                    rect_area = w * h
                    if rect_area < page_area * 0.5:
                        # Top edge
                        h_lines.append((rect.x0, rect.y0, rect.x1, rect.y0))
                        # Bottom edge
                        h_lines.append((rect.x0, rect.y1, rect.x1, rect.y1))
                        # Left edge
                        v_lines.append((rect.x0, rect.y0, rect.x0, rect.y1))
                        # Right edge
                        v_lines.append((rect.x1, rect.y0, rect.x1, rect.y1))
                # else: w < tol and h < tol — tiny corner rectangles, ignore

        return h_lines, v_lines

    def _extract_lines_from_drawings(
        self, page: fitz.Page
    ) -> Tuple[List[Tuple], List[Tuple]]:
        """Extract visible rectangles as candidate table lines.

        Line-like rectangles (thin borders) are accepted regardless of fill
        colour.  Normal rectangles are only decomposed into edge lines when
        their fill is black/near-black; gray cell-background rectangles are
        skipped so they do not create spurious inner borders.
        """
        h_lines = []
        v_lines = []
        page_area = page.rect.width * page.rect.height

        for rect, drawing in self._iter_effective_drawing_rects(page):
            w, h = rect.width, rect.height

            if h < self.line_tolerance and w >= self.line_tolerance * 2:
                y = (rect.y0 + rect.y1) / 2
                h_lines.append((rect.x0, y, rect.x1, y))
            elif w < self.line_tolerance and h >= self.line_tolerance * 2:
                x = (rect.x0 + rect.x1) / 2
                v_lines.append((x, rect.y0, x, rect.y1))
            elif w >= self.line_tolerance and h >= self.line_tolerance:
                rect_area = w * h
                if rect_area < page_area * 0.5 and (
                    self._has_visible_stroke(drawing)
                    or self._is_blackish_fill(drawing)
                ):
                    h_lines.append((rect.x0, rect.y0, rect.x1, rect.y0))
                    h_lines.append((rect.x0, rect.y1, rect.x1, rect.y1))
                    v_lines.append((rect.x0, rect.y0, rect.x0, rect.y1))
                    v_lines.append((rect.x1, rect.y0, rect.x1, rect.y1))

        return h_lines, v_lines

    # ------------------------------------------------------------------
    # Filled cell rectangle extraction (for WPS/Office merged cells)
    # ------------------------------------------------------------------

    def _extract_subrow_boundaries(
        self, page: fitz.Page, table_bbox: BBox
    ) -> List[float]:
        """Extract sub-row boundaries from filled cell rectangles.

        WPS/Office draws filled rectangles for cells. In tables with merged
        cells (e.g., parent items spanning multiple sub-rows), the sub-cells
        are drawn as narrower rectangles inside the parent cell. We use these
        to find the actual row boundaries.

        Returns a sorted list of y-coordinates that define sub-row boundaries.
        Only includes boundaries for intervals that have actual sub-cell coverage.
        """
        try:
            drawings = page.get_drawings()
        except Exception:
            return []

        subcells = []
        for d in drawings:
            for item in d.get("items", []):
                if item[0] != "re":
                    continue
                rect = fitz.Rect(item[1])
                # Look for sub-cell rectangles in the first column area:
                # - wider than a border (>= 20pt) but narrower than full column (< 55pt)
                # - tall enough to be a cell (>= 10pt) but not a full section (< 25pt)
                # - positioned in the first column area
                if (
                    20 <= rect.width < 55
                    and 10 <= rect.height < 25
                    and table_bbox.x0 <= rect.x0 <= table_bbox.x0 + 60
                    and table_bbox.y0 <= rect.y0 <= table_bbox.y1
                ):
                    subcells.append(rect)

        if not subcells:
            return []

        # Group sub-cells by their row range (same y0 and y1 within 1pt)
        row_ranges: List[Tuple[float, float]] = []
        for rect in subcells:
            merged = False
            for i, (ry0, ry1) in enumerate(row_ranges):
                if abs(rect.y0 - ry0) <= 1.0 and abs(rect.y1 - ry1) <= 1.0:
                    row_ranges[i] = ((ry0 + rect.y0) / 2, (ry1 + rect.y1) / 2)
                    merged = True
                    break
            if not merged:
                row_ranges.append((rect.y0, rect.y1))

        row_ranges.sort()

        # Merge overlapping ranges (but not just touching)
        merged_ranges: List[Tuple[float, float]] = []
        for y0, y1 in row_ranges:
            if merged_ranges and y0 < merged_ranges[-1][1] - 0.5:
                merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], y1))
            else:
                merged_ranges.append((y0, y1))

        # Build boundaries from valid row ranges + table boundaries
        y_bounds = [table_bbox.y0]
        for y0, y1 in merged_ranges:
            if abs(y0 - y_bounds[-1]) > 1.0:
                y_bounds.append(y0)
            if abs(y1 - y_bounds[-1]) > 1.0:
                y_bounds.append(y1)

        # Ensure table bottom is included
        if abs(y_bounds[-1] - table_bbox.y1) > 1.0:
            y_bounds.append(table_bbox.y1)

        return y_bounds

    # ------------------------------------------------------------------
    # Line merging (tight tolerance to preserve grid structure)
    # ------------------------------------------------------------------

    def _merge_h_lines(
        self, lines: List[Tuple[float, float, float, float]]
    ) -> List[Tuple[float, float, float, float]]:
        """Merge horizontal line segments that are on the same row.

        Groups segments by y-position (within ``merge_group_tol``) and then
        merges overlapping/adjacent x-ranges within each group.
        """
        if not lines:
            return []

        # Sort by y, then x0
        sorted_lines = sorted(lines, key=lambda line: (line[1], line[0]))
        merged = []
        group = [sorted_lines[0]]
        group_y = sorted_lines[0][1]

        def _flush_group():
            if not group:
                return
            # Average y for the group
            avg_y = sum(line[1] for line in group) / len(group)
            segs = sorted(group, key=lambda s: s[0])
            cur_x0, cur_x1 = segs[0][0], segs[0][2]
            for x0, _, x1, _ in segs[1:]:
                if x0 <= cur_x1 + self.line_tolerance:
                    cur_x1 = max(cur_x1, x1)
                else:
                    merged.append((cur_x0, avg_y, cur_x1, avg_y))
                    cur_x0, cur_x1 = x0, x1
            merged.append((cur_x0, avg_y, cur_x1, avg_y))

        for line in sorted_lines[1:]:
            _, y, _, _ = line
            if abs(y - group_y) <= self.merge_group_tol:
                group.append(line)
            else:
                _flush_group()
                group = [line]
                group_y = y
        _flush_group()

        return merged

    def _merge_v_lines(
        self, lines: List[Tuple[float, float, float, float]]
    ) -> List[Tuple[float, float, float, float]]:
        """Merge vertical line segments that are on the same column.

        Groups segments by x-position (within ``merge_group_tol``) and then
        merges overlapping/adjacent y-ranges within each group.
        """
        if not lines:
            return []

        # Sort by x, then y0
        sorted_lines = sorted(lines, key=lambda line: (line[0], line[1]))
        merged = []
        group = [sorted_lines[0]]
        group_x = sorted_lines[0][0]

        def _flush_group():
            if not group:
                return
            # Average x for the group
            avg_x = sum(line[0] for line in group) / len(group)
            segs = sorted(group, key=lambda s: s[1])
            cur_y0, cur_y1 = segs[0][1], segs[0][3]
            for _, y0, _, y1 in segs[1:]:
                if y0 <= cur_y1 + self.line_tolerance:
                    cur_y1 = max(cur_y1, y1)
                else:
                    merged.append((avg_x, cur_y0, avg_x, cur_y1))
                    cur_y0, cur_y1 = y0, y1
            merged.append((avg_x, cur_y0, avg_x, cur_y1))

        for line in sorted_lines[1:]:
            x, _, _, _ = line
            if abs(x - group_x) <= self.merge_group_tol:
                group.append(line)
            else:
                _flush_group()
                group = [line]
                group_x = x
        _flush_group()

        return merged

    def _filter_lines_by_components(
        self,
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> Tuple[List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]:
        """Filter out lines that belong to small isolated components.

        Uses connected-component analysis on line intersections:
        1. Find all h/v line intersections
        2. Build a graph where intersections are nodes and segments between
           adjacent intersections on the same line are edges
        3. Find connected components
        4. Only keep lines from components large enough to form a table grid
           (at least 3h x 3v lines and 10 intersections)
        """
        if not h_lines or not v_lines:
            return h_lines, v_lines

        tol = self.line_tolerance

        # 1. Find all intersections
        intersections: List[Tuple[float, float, int, int]] = []
        h_by_v: dict[int, list[int]] = defaultdict(list)
        v_by_h: dict[int, list[int]] = defaultdict(list)

        for hi, (hx0, hy, hx1, _) in enumerate(h_lines):
            for vi, (vx, vy0, _, vy1) in enumerate(v_lines):
                if hx0 - tol <= vx <= hx1 + tol and vy0 - tol <= hy <= vy1 + tol:
                    intersections.append((vx, hy, hi, vi))
                    h_by_v[vi].append(hi)
                    v_by_h[hi].append(vi)

        if not intersections:
            return h_lines, v_lines

        # 2. Union-Find on intersections
        parent = list(range(len(intersections)))

        def find(i: int) -> int:
            if parent[i] != i:
                parent[i] = find(parent[i])
            return parent[i]

        def union(i: int, j: int) -> None:
            pi, pj = find(i), find(j)
            if pi != pj:
                parent[pi] = pj

        hv_to_idx: dict[tuple[int, int], int] = {
            (hi, vi): idx for idx, (_, _, hi, vi) in enumerate(intersections)
        }

        # Connect intersections on the same h-line (adjacent in x)
        for hi in range(len(h_lines)):
            iv_list = [
                (v_lines[vi][0], hv_to_idx[(hi, vi)])
                for vi in v_by_h[hi]
                if (hi, vi) in hv_to_idx
            ]
            iv_list.sort()
            for i in range(len(iv_list) - 1):
                union(iv_list[i][1], iv_list[i + 1][1])

        # Connect intersections on the same v-line (adjacent in y)
        for vi in range(len(v_lines)):
            ih_list = [
                (h_lines[hi][1], hv_to_idx[(hi, vi)])
                for hi in h_by_v[vi]
                if (hi, vi) in hv_to_idx
            ]
            ih_list.sort()
            for i in range(len(ih_list) - 1):
                union(ih_list[i][1], ih_list[i + 1][1])

        # 3. Gather lines per component
        comp_lines: dict[int, dict[str, set[int]]] = defaultdict(
            lambda: {"h": set(), "v": set()}
        )
        for idx, (_, _, hi, vi) in enumerate(intersections):
            root = find(idx)
            comp_lines[root]["h"].add(hi)
            comp_lines[root]["v"].add(vi)

        # 4. Count intersections per component
        comp_size: dict[int, int] = defaultdict(int)
        for i in range(len(intersections)):
            comp_size[find(i)] += 1

        # 5. Keep lines from large components only
        keep_h: set[int] = set()
        keep_v: set[int] = set()

        for comp_id, lines in comp_lines.items():
            size = comp_size[comp_id]
            h_count = len(lines["h"])
            v_count = len(lines["v"])
            # A valid table grid needs at least 3x3 lines and 10 intersections
            if size >= 10 and h_count >= 3 and v_count >= 3:
                keep_h.update(lines["h"])
                keep_v.update(lines["v"])

        filtered_h = [h_lines[i] for i in sorted(keep_h)]
        filtered_v = [v_lines[i] for i in sorted(keep_v)]

        # 6. Additional filtering: remove h-lines whose coverage width is too
        # small relative to the overall table width. Short horizontal segments
        # (e.g., from sub-cell rectangles) cannot be real row boundaries.
        if filtered_h and filtered_v:
            v_xs = sorted(set(x for x, _, _, _ in filtered_v))
            if len(v_xs) >= 2:
                table_width = v_xs[-1] - v_xs[0]
                min_width = table_width * 0.2
                filtered_h = [
                    line for line in filtered_h if (line[2] - line[0]) >= min_width
                ]

        # 7. Additional filtering: remove v-lines whose span is too short
        # relative to the overall table height. Short vertical segments
        # (e.g., from cell rectangles inside a merged cell) cannot be real
        # column boundaries.
        if filtered_h and filtered_v:
            h_ys = sorted(set(y for _, y, _, _ in filtered_h))
            if len(h_ys) >= 2:
                table_height = h_ys[-1] - h_ys[0]
                min_span = table_height * 0.25
                filtered_v = [
                    line for line in filtered_v if (line[3] - line[1]) >= min_span
                ]

        return filtered_h, filtered_v

    # ------------------------------------------------------------------
    # Table region discovery
    # ------------------------------------------------------------------

    def _find_line_components(
        self,
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> List[Tuple[List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]]:
        """Group lines into connected components based on h/v intersections."""
        if len(h_lines) < 2 or len(v_lines) < 2:
            return []

        tol = self.line_tolerance
        h_to_v: dict[int, set[int]] = defaultdict(set)
        v_to_h: dict[int, set[int]] = defaultdict(set)

        for hi, (hx0, hy, hx1, _) in enumerate(h_lines):
            for vi, (vx, vy0, _, vy1) in enumerate(v_lines):
                if hx0 - tol <= vx <= hx1 + tol and vy0 - tol <= hy <= vy1 + tol:
                    h_to_v[hi].add(vi)
                    v_to_h[vi].add(hi)

        components = []
        visited_h: set[int] = set()
        visited_v: set[int] = set()

        for start_hi in sorted(h_to_v.keys()):
            if start_hi in visited_h:
                continue

            queue: list[tuple[str, int]] = [("h", start_hi)]
            comp_h: set[int] = set()
            comp_v: set[int] = set()

            while queue:
                kind, idx = queue.pop()
                if kind == "h":
                    if idx in visited_h:
                        continue
                    visited_h.add(idx)
                    comp_h.add(idx)
                    for vi in h_to_v.get(idx, ()):
                        if vi not in visited_v:
                            queue.append(("v", vi))
                else:
                    if idx in visited_v:
                        continue
                    visited_v.add(idx)
                    comp_v.add(idx)
                    for hi in v_to_h.get(idx, ()):
                        if hi not in visited_h:
                            queue.append(("h", hi))

            if len(comp_h) >= 2 and len(comp_v) >= 2:
                components.append(
                    (
                        [h_lines[i] for i in sorted(comp_h)],
                        [v_lines[i] for i in sorted(comp_v)],
                    )
                )

        return components

    def _select_primary_component_lines(
        self,
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> Tuple[
        List[Tuple[float, float, float, float]],
        List[Tuple[float, float, float, float]],
    ]:
        """Keep the main grid lines of one connected component.

        Short local segments from filled sub-cells are common in financial
        tables and should not define global columns / rows for the component.
        """
        if len(h_lines) < 2 or len(v_lines) < 2:
            return h_lines, v_lines

        min_x = min(min(x0, x1) for x0, _, x1, _ in h_lines)
        max_x = max(max(x0, x1) for x0, _, x1, _ in h_lines)
        min_y = min(min(y0, y1) for _, y0, _, y1 in v_lines)
        max_y = max(max(y0, y1) for _, y0, _, y1 in v_lines)
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)

        primary_v = [
            line for line in v_lines
            if (line[3] - line[1]) >= height * 0.6
        ]
        primary_h = [
            line for line in h_lines
            if (line[2] - line[0]) >= width * 0.5
        ]

        if len(primary_v) < 2:
            primary_v = v_lines
        if len(primary_h) < 2:
            primary_h = h_lines

        return primary_h, primary_v

    def _find_table_regions(
        self,
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> List[Tuple[BBox, List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]]:
        """Partition the page into table regions by line connectivity.

        Returns a list of (bbox, h_lines, v_lines) for each detected table region.
        """
        if len(h_lines) < 2 or len(v_lines) < 2:
            return []

        components = self._find_line_components(h_lines, v_lines)

        regions: List[Tuple[BBox, List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]] = []
        for h_group, v_group in components:
            h_ys = sorted(set(y for _, y, _, _ in h_group))
            if len(h_ys) < 2:
                continue

            # Keep only horizontal lines that truly intersect this component's
            # vertical lines, so local bbox construction stays tight.
            tol = self.line_tolerance
            valid_h_group = [
                line
                for line in h_group
                if any(
                    v[1] - tol <= line[1] <= v[3] + tol
                    and line[0] - tol <= v[0] <= line[2] + tol
                    for v in v_group
                )
            ]
            h_ys = sorted(set(y for _, y, _, _ in valid_h_group))
            if len(h_ys) < 2:
                continue

            v_xs = sorted(set(x for x, _, _, _ in v_group))
            if len(v_xs) < 2:
                continue

            x0, x1 = v_xs[0], v_xs[-1]
            y0, y1 = h_ys[0], h_ys[-1]

            regions.append((BBox(x0, y0, x1, y1), valid_h_group, v_group))

        regions = self._merge_adjacent_regions(regions)
        return regions

    def _build_cells_for_region(
        self,
        bbox: BBox,
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> List[Cell]:
        """Build cells for a single table region from its border lines."""
        h_ys = sorted(set(y for _, y, _, _ in h_lines))
        v_xs = sorted(set(x for x, _, _, _ in v_lines))

        if len(h_ys) < 2 or len(v_xs) < 2:
            return []

        return self._build_cells_in_region(h_ys, v_xs, h_lines, v_lines)

    def _cluster_h_lines(
        self, h_lines: List[Tuple[float, float, float, float]]
    ) -> List[List[Tuple[float, float, float, float]]]:
        """Cluster horizontal lines by y-position.

        Uses ``row_gap_threshold`` to separate distinct tables on the same page.
        """
        if not h_lines:
            return []

        sorted_lines = sorted(h_lines, key=lambda line: line[1])
        groups: List[List[Tuple[float, float, float, float]]] = []
        current_group = [sorted_lines[0]]

        for line in sorted_lines[1:]:
            prev_y = current_group[-1][1]
            curr_y = line[1]
            if curr_y - prev_y > self.row_gap_threshold:
                groups.append(current_group)
                current_group = [line]
            else:
                current_group.append(line)

        groups.append(current_group)
        return groups

    def _build_cells_in_region(
        self,
        h_ys: List[float],
        v_xs: List[float],
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> List[Cell]:
        """Build cells from a global atomic grid and merge across missing edges."""
        rows = len(h_ys) - 1
        cols = len(v_xs) - 1
        if rows <= 0 or cols <= 0:
            return []

        tol = self.line_tolerance
        def has_h_segment(y: float, x0: float, x1: float) -> bool:
            span = x1 - x0
            for lx0, ly, lx1, _ in h_lines:
                if abs(ly - y) > tol:
                    continue
                overlap = min(lx1, x1 + tol) - max(lx0, x0 - tol)
                if overlap >= max(span - tol, span * 0.9):
                    return True
            return False

        def has_v_segment(x: float, y0: float, y1: float) -> bool:
            span = y1 - y0
            for lx, ly0, _, ly1 in v_lines:
                if abs(lx - x) > tol:
                    continue
                overlap = min(ly1, y1 + tol) - max(ly0, y0 - tol)
                if overlap >= max(span - tol, span * 0.9):
                    return True
            return False

        # Boundary-edge occupancy on the global atomic grid.
        h_edges = [
            [has_h_segment(h_ys[row], v_xs[col], v_xs[col + 1]) for col in range(cols)]
            for row in range(rows + 1)
        ]
        v_edges = [
            [has_v_segment(v_xs[col], h_ys[row], h_ys[row + 1]) for col in range(cols + 1)]
            for row in range(rows)
        ]

        # Flood-fill from the outside through any missing outer border to
        # identify Cartesian-product cells that are not actually part of the table.
        outside: set[tuple[int, int]] = set()
        stack: list[tuple[int, int]] = []

        def mark_outside(row: int, col: int) -> None:
            if (row, col) not in outside:
                outside.add((row, col))
                stack.append((row, col))

        for col in range(cols):
            if not h_edges[0][col]:
                mark_outside(0, col)
            if not h_edges[rows][col]:
                mark_outside(rows - 1, col)

        for row in range(rows):
            if not v_edges[row][0]:
                mark_outside(row, 0)
            if not v_edges[row][cols]:
                mark_outside(row, cols - 1)

        while stack:
            row, col = stack.pop()
            if row > 0 and not h_edges[row][col]:
                mark_outside(row - 1, col)
            if row + 1 < rows and not h_edges[row + 1][col]:
                mark_outside(row + 1, col)
            if col > 0 and not v_edges[row][col]:
                mark_outside(row, col - 1)
            if col + 1 < cols and not v_edges[row][col + 1]:
                mark_outside(row, col + 1)

        inside_cells = [
            (row, col)
            for row in range(rows)
            for col in range(cols)
            if (row, col) not in outside
        ]
        if not inside_cells:
            return []

        parent = list(range(rows * cols))

        def cell_id(row: int, col: int) -> int:
            return row * cols + col

        def find(idx: int) -> int:
            while parent[idx] != idx:
                parent[idx] = parent[parent[idx]]
                idx = parent[idx]
            return idx

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        inside_set = set(inside_cells)
        for row, col in inside_cells:
            if col + 1 < cols and (row, col + 1) in inside_set and not v_edges[row][col + 1]:
                union(cell_id(row, col), cell_id(row, col + 1))
            if row + 1 < rows and (row + 1, col) in inside_set and not h_edges[row + 1][col]:
                union(cell_id(row, col), cell_id(row + 1, col))

        components: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for row, col in inside_cells:
            components[find(cell_id(row, col))].append((row, col))

        cells: List[Cell] = []
        for coords in components.values():
            min_row = min(row for row, _ in coords)
            max_row = max(row for row, _ in coords)
            min_col = min(col for _, col in coords)
            max_col = max(col for _, col in coords)

            expected_size = (max_row - min_row + 1) * (max_col - min_col + 1)
            if len(coords) != expected_size:
                # Keep pathological non-rectangular components split to avoid
                # inventing invalid merged cells.
                for row, col in sorted(coords):
                    cells.append(
                        Cell(
                            text="",
                            row_index=row,
                            col_index=col,
                            bbox=BBox(v_xs[col], h_ys[row], v_xs[col + 1], h_ys[row + 1]),
                        )
                    )
                continue

            cells.append(
                Cell(
                    text="",
                    row_index=min_row,
                    col_index=min_col,
                    bbox=BBox(
                        v_xs[min_col],
                        h_ys[min_row],
                        v_xs[max_col + 1],
                        h_ys[max_row + 1],
                    ),
                    rowspan=max_row - min_row + 1,
                    colspan=max_col - min_col + 1,
                )
            )

        cells.sort(key=lambda cell: (cell.row_index, cell.col_index))
        return cells

    def _merge_adjacent_regions(
        self,
        regions: List[Tuple[BBox, List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]],
    ) -> List[Tuple[BBox, List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]]:
        """Merge regions that are adjacent in x and overlapping in y."""
        if len(regions) <= 1:
            return regions

        regions = list(regions)
        merged_any = True

        while merged_any:
            merged_any = False
            new_regions = []
            used = set()

            for i in range(len(regions)):
                if i in used:
                    continue

                bbox_i, h_i, v_i = regions[i]
                merged_h = list(h_i)
                merged_v = list(v_i)
                used.add(i)

                for j in range(i + 1, len(regions)):
                    if j in used:
                        continue

                    bbox_j, h_j, v_j = regions[j]

                    y_overlap = (
                        min(bbox_i.y1, bbox_j.y1) - max(bbox_i.y0, bbox_j.y0)
                    )
                    y_overlap_ratio = y_overlap / max(
                        bbox_i.y1 - bbox_i.y0, bbox_j.y1 - bbox_j.y0, 1
                    )

                    x_gap = max(bbox_i.x0, bbox_j.x0) - min(bbox_i.x1, bbox_j.x1)
                    if x_gap < 0:
                        x_gap = 0

                    if y_overlap_ratio > 0.5 and x_gap < 20:
                        merged_h.extend(h_j)
                        merged_v.extend(v_j)
                        bbox_i = BBox(
                            min(bbox_i.x0, bbox_j.x0),
                            min(bbox_i.y0, bbox_j.y0),
                            max(bbox_i.x1, bbox_j.x1),
                            max(bbox_i.y1, bbox_j.y1),
                        )
                        used.add(j)
                        merged_any = True

                new_regions.append((bbox_i, merged_h, merged_v))

            regions = new_regions

        return regions

    # ------------------------------------------------------------------
    # Text assignment
    # ------------------------------------------------------------------

    def _assign_text_to_cells(
        self, cells: List[Cell], page: fitz.Page
    ) -> List[Cell]:
        """Assign text to cells using word-level granularity.

        Words on the same line are joined with spaces; words on different
        lines are joined without spaces. This handles wrapped numbers in
        narrow financial-table cells correctly.
        """
        if not cells:
            return cells

        x0 = min(c.bbox.x0 for c in cells)
        y0 = min(c.bbox.y0 for c in cells)
        x1 = max(c.bbox.x1 for c in cells)
        y1 = max(c.bbox.y1 for c in cells)

        rect = fitz.Rect(x0 - 5, y0 - 5, x1 + 5, y1 + 5)

        try:
            words = page.get_text("words", clip=rect)
        except Exception:
            return cells

        # Map each word to its containing cell (by index, since Cell is not hashable)
        cell_words: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
        for word in words:
            wx0, wy0, wx1, wy1, text, block_no, line_no, word_no = word
            cx = (wx0 + wx1) / 2
            cy = (wy0 + wy1) / 2

            for idx, cell in enumerate(cells):
                if (
                    cell.bbox.x0 <= cx <= cell.bbox.x1
                    and cell.bbox.y0 <= cy <= cell.bbox.y1
                ):
                    cell_words[idx].append((cy, cx, text.strip()))
                    break

        # Reconstruct text for each cell, grouping words by line
        for idx, word_list in cell_words.items():
            cell = cells[idx]
            word_list.sort()  # Sort by y, then x
            lines: list[str] = []
            current_line: list[tuple[float, str]] = []
            last_y: float | None = None

            for cy, cx, text in word_list:
                if last_y is None or abs(cy - last_y) <= 5:
                    current_line.append((cx, text))
                else:
                    current_line.sort()
                    lines.append(" ".join(t for _, t in current_line))
                    current_line = [(cx, text)]
                last_y = cy

            if current_line:
                current_line.sort()
                lines.append(" ".join(t for _, t in current_line))

            # Join lines without spaces (for wrapped numbers)
            cell.text = "".join(lines)

        return cells

    # ------------------------------------------------------------------
    # Sub-row cell building (for WPS/Office merged-cell tables)
    # ------------------------------------------------------------------

    def _build_cells_with_subrows(
        self,
        subrows: List[float],
        v_lines: List[Tuple[float, float, float, float]],
        table_bbox: BBox,
    ) -> List[Cell]:
        """Build cells using sub-row boundaries and vertical lines.

        This is used for tables where horizontal borders only exist at
        section boundaries, but sub-rows are revealed by filled cell rectangles.
        """
        # Get vertical lines that span the table
        table_v_lines = [
            (x, y0, y1)
            for x, y0, _, y1 in v_lines
            if y0 <= table_bbox.y0 + 5 and y1 >= table_bbox.y1 - 5
        ]
        v_xs = sorted(set(x for x, _, _ in table_v_lines))

        if len(v_xs) < 2:
            return []

        cells: List[Cell] = []
        for i in range(len(subrows) - 1):
            y0, y1 = subrows[i], subrows[i + 1]
            row_height = y1 - y0

            # Skip intervals that are too short to be real rows (< 5pt)
            if row_height < 5.0:
                continue

            # Find vertical lines that span this sub-row
            row_v_xs = []
            for x, vy0, vy1 in table_v_lines:
                if vy0 <= y0 + 1 and vy1 >= y1 - 1:
                    row_v_xs.append(x)

            row_v_xs = sorted(set(row_v_xs))
            if len(row_v_xs) < 2:
                continue

            for j in range(len(row_v_xs) - 1):
                x0, x1 = row_v_xs[j], row_v_xs[j + 1]
                cells.append(
                    Cell(
                        text="",
                        row_index=i,
                        col_index=j,
                        bbox=BBox(x0, y0, x1, y1),
                    )
                )

        return cells

    def _filter_empty_rows(self, cells: List[Cell]) -> List[Cell]:
        """Remove rows that contain no text in any cell."""
        if not cells:
            return cells

        rows: dict[int, List[Cell]] = defaultdict(list)
        for c in cells:
            rows[c.row_index].append(c)

        valid_row_indices = {
            row_idx
            for row_idx, row_cells in rows.items()
            if any(c.text.strip() for c in row_cells)
        }

        if not valid_row_indices:
            return cells

        row_index_map = {
            old_idx: new_idx
            for new_idx, old_idx in enumerate(sorted(valid_row_indices))
        }

        return [
            Cell(
                text=c.text,
                row_index=row_index_map[c.row_index],
                col_index=c.col_index,
                bbox=c.bbox,
                rowspan=c.rowspan,
                colspan=c.colspan,
            )
            for c in cells
            if c.row_index in row_index_map
        ]

    def _is_section_marker(self, text: str) -> bool:
        """Check if text starts with a section/item marker."""
        text = text.strip()
        if not text:
            return False
        # Chinese numbered sections: 一、 二、 三、 ... 十、
        if text[:2] in (
            "一、", "二、", "三、", "四、", "五、", "六、",
            "七、", "八、", "九、", "十、",
        ):
            return True
        # Parenthesized numbers: （一） （二） ...
        if len(text) >= 3 and text[0] == "（" and text[2] == "）":
            return True
        # Arabic numbers: 1. 2. 3.  (full-width or half-width)
        if text[0].isdigit() and len(text) >= 2 and text[1] in ".．":
            return True
        # Special prefixes
        if text.startswith(("加：", "减：", "其中：")):
            return True
        return False

    def _merge_rows_by_text_pattern(self, cells: List[Cell]) -> List[Cell]:
        """Merge consecutive sub-rows that form a single logical row.

        Uses text in the first column to detect section markers. Rows without
        section markers are merged with the previous row. Empty gap rows are
        skipped.

        Special handling for rows with empty first column but data elsewhere:
        these are merged with the nearest section-marker row, not the header.
        """
        if not cells:
            return cells

        # Group cells by row
        rows: dict[int, List[Cell]] = defaultdict(list)
        for c in cells:
            rows[c.row_index].append(c)

        # Build logical row groups
        groups: list[list[int]] = []
        current_group: list[int] = []
        pending: list[int] = []  # Rows with empty col 0 before first section marker

        def _group_has_section_marker(group: list[int]) -> bool:
            for r in group:
                col0 = next(
                    (c.text.strip() for c in rows[r] if c.col_index == 0), ""
                )
                if self._is_section_marker(col0):
                    return True
            return False

        for ri in sorted(rows.keys()):
            row_cells = rows[ri]
            row_text = " ".join(c.text.strip() for c in row_cells if c.text.strip())
            col0_text = next(
                (c.text.strip() for c in row_cells if c.col_index == 0), ""
            )

            if not row_text:
                continue

            if self._is_section_marker(col0_text):
                # Start a new logical row
                if current_group:
                    groups.append(current_group)
                # Include pending rows (gap rows before first section marker)
                # in the first data row, not the header
                current_group = pending + [ri]
                pending = []
            elif not col0_text:
                # Row has no col 0 text
                if current_group and _group_has_section_marker(current_group):
                    # Current group has a section marker - this is a continuation
                    current_group.append(ri)
                elif not current_group:
                    # Before any group - keep as pending for first data row
                    pending.append(ri)
                else:
                    # Current group is header - don't merge, keep as pending
                    pending.append(ri)
            else:
                # Normal continuation row
                if not current_group:
                    current_group = [ri]
                else:
                    current_group.append(ri)

        # Flush remaining
        if pending:
            if current_group:
                current_group.extend(pending)
            else:
                current_group = pending
        if current_group:
            groups.append(current_group)

        if not groups:
            return cells

        # Merge cells within each group
        merged_cells: List[Cell] = []
        for new_ri, group_rows in enumerate(groups):
            # Group by column
            cols: dict[int, List[Cell]] = defaultdict(list)
            for ri in group_rows:
                for c in rows[ri]:
                    cols[c.col_index].append(c)

            for ci in sorted(cols.keys()):
                col_cells = sorted(cols[ci], key=lambda c: c.bbox.y0)
                texts = [c.text.strip() for c in col_cells if c.text.strip()]
                merged_text = "".join(texts)
                merged_cells.append(
                    Cell(
                        text=merged_text,
                        row_index=new_ri,
                        col_index=ci,
                        bbox=BBox(
                            min(c.bbox.x0 for c in col_cells),
                            min(c.bbox.y0 for c in col_cells),
                            max(c.bbox.x1 for c in col_cells),
                            max(c.bbox.y1 for c in col_cells),
                        ),
                    )
                )

        return merged_cells

    def _merge_oversegmented_columns(self, cells: List[Cell]) -> List[Cell]:
        """Remove narrow border columns from over-segmented tables.

        Rectangle edge decomposition creates inner border lines that split
        actual data columns into sub-columns. These border columns are narrow
        (< 10pt wide) and empty. We merge them with their adjacent data column.

        Wider empty columns (potential spacer columns with density == 0) are
        removed entirely and the remaining columns are renumbered.
        """
        if not cells:
            return cells

        # Group cells by row and column
        rows: dict[int, List[Cell]] = defaultdict(list)
        cols: dict[int, List[Cell]] = defaultdict(list)
        for c in cells:
            rows[c.row_index].append(c)
            cols[c.col_index].append(c)

        row_count = len(rows)
        if row_count == 0:
            return cells

        col_count = max((c.col_index for c in cells), default=-1) + 1
        sorted_col_indices = sorted(cols.keys())

        # Calculate width and text density for each column
        col_width: dict[int, float] = {}
        col_density: dict[int, float] = {}
        for ci, col_cells in cols.items():
            widths = [c.bbox.x1 - c.bbox.x0 for c in col_cells]
            col_width[ci] = sum(widths) / len(widths) if widths else 0
            col_density[ci] = sum(1 for c in col_cells if c.text.strip()) / row_count

        # Identify narrow border columns: empty AND narrow (< 10pt).
        # These are artifacts of rectangle edge decomposition.
        narrow_border = {
            ci for ci in sorted_col_indices
            if col_density[ci] == 0.0 and col_width[ci] < 10.0
        }

        # Preserve wider empty columns: they are part of the geometric table
        # structure even when they contain no text on the current page.
        spacer_cols: set[int] = set()

        # If nothing to merge, return as-is
        if not narrow_border and col_count <= 10:
            return cells

        # Build merge map
        merge_map: dict[int, int] = {}

        # Step 1: Merge narrow border columns with adjacent data column.
        # Prefer the wider neighbor.
        for ci in narrow_border:
            idx = sorted_col_indices.index(ci)
            left = sorted_col_indices[idx - 1] if idx > 0 else None
            right = sorted_col_indices[idx + 1] if idx < len(sorted_col_indices) - 1 else None

            candidates = []
            if left is not None and left not in narrow_border:
                candidates.append((left, col_width.get(left, 0)))
            if right is not None and right not in narrow_border:
                candidates.append((right, col_width.get(right, 0)))

            if candidates:
                merge_map[ci] = max(candidates, key=lambda x: x[1])[0]
            # If no valid neighbor, leave unmapped (will get renumbered)

        # Step 2: Keep all non-narrow columns, including empty structural ones.
        keep_cols = [ci for ci in sorted_col_indices if ci not in spacer_cols]
        renumber: dict[int, int] = {}
        for new_idx, old_idx in enumerate(keep_cols):
            renumber[old_idx] = new_idx

        # Final merge map: narrow borders → target col → renumber
        # non-border non-spacer cols → renumber
        final_map: dict[int, int] = {}
        for ci in sorted_col_indices:
            if ci in merge_map:
                # Narrow border: merge into target, then renumber target
                target = merge_map[ci]
                # The target might itself be a merge target or a normal column
                while target in merge_map:
                    target = merge_map[target]
                final_map[ci] = renumber.get(target, target)
            else:
                final_map[ci] = renumber.get(ci, ci)

        # Apply merge map
        merged: dict[tuple[int, int], List[Cell]] = defaultdict(list)
        for c in cells:
            key = (c.row_index, final_map[c.col_index])
            merged[key].append(c)

        merged_cells: List[Cell] = []
        for (ri, ci), group in merged.items():
            texts = [c.text.strip() for c in group if c.text.strip()]
            merged_text = " ".join(texts) if texts else ""
            covered_cols: set[int] = set()
            for cell in group:
                for original_col in range(
                    cell.col_index, cell.col_index + cell.colspan
                ):
                    mapped_col = final_map.get(original_col)
                    if mapped_col is not None:
                        covered_cols.add(mapped_col)

            if covered_cols:
                start_col = min(covered_cols)
                end_col = max(covered_cols)
            else:
                start_col = ci
                end_col = ci

            merged_cells.append(
                Cell(
                    text=merged_text,
                    row_index=ri,
                    col_index=start_col,
                    bbox=BBox(
                        min(c.bbox.x0 for c in group),
                        min(c.bbox.y0 for c in group),
                        max(c.bbox.x1 for c in group),
                        max(c.bbox.y1 for c in group),
                    ),
                    colspan=end_col - start_col + 1,
                )
            )

        return merged_cells

    def _filter_sparse_top_rows(self, cells: List[Cell]) -> List[Cell]:
        """Remove sparse rows at the top that are likely header fragments.

        In financial tables, column headers or page-break fragments can appear
        as rows with very low text density. We skip leading rows until we find
        one with a meaningful section marker or reasonable density.
        """
        if not cells:
            return cells

        rows: dict[int, List[Cell]] = defaultdict(list)
        for c in cells:
            rows[c.row_index].append(c)

        row_count = len(rows)
        if row_count <= 2:
            return cells

        def _is_numbered_marker(text: str) -> bool:
            """Check if text starts with a numbered section marker."""
            if not text:
                return False
            # Chinese numbered sections: 一、 二、 ... 十、
            if text[:2] in (
                "一、", "二、", "三、", "四、", "五、", "六、",
                "七、", "八、", "九、", "十、",
            ):
                return True
            # Parenthesized numbers: （一） （二） ...
            if len(text) >= 3 and text[0] == "（" and text[2] == "）":
                return True
            # Arabic numbers: 1. 2. 3.  (full-width or half-width)
            if text[0].isdigit() and len(text) >= 2 and text[1] in ".．":
                return True
            return False

        # Find the first row that looks like real data
        first_valid_row = None
        for ri in sorted(rows.keys()):
            row_cells = rows[ri]
            total = len(row_cells)
            filled = sum(1 for c in row_cells if c.text.strip())
            density = filled / total if total else 0

            col0_text = next(
                (c.text.strip() for c in row_cells if c.col_index == 0), ""
            )
            has_numbered = _is_numbered_marker(col0_text)

            # A row is valid if it has a numbered section marker,
            # or has decent density (>= 40%) with text in col 0.
            # We do NOT count "加：", "减：" as valid first-row markers
            # because they can appear in header fragments.
            if has_numbered or (density >= 0.4 and col0_text):
                first_valid_row = ri
                break

        if first_valid_row is None or first_valid_row == 0:
            return cells

        # Keep only rows from first_valid_row onward
        row_index_map = {
            old_idx: new_idx
            for new_idx, old_idx in enumerate(
                sorted(r for r in rows.keys() if r >= first_valid_row)
            )
        }

        return [
            Cell(
                text=c.text,
                row_index=row_index_map[c.row_index],
                col_index=c.col_index,
                bbox=c.bbox,
                rowspan=c.rowspan,
                colspan=c.colspan,
            )
            for c in cells
            if c.row_index in row_index_map
        ]

    # ------------------------------------------------------------------
    # Main line-projection extraction
    # ------------------------------------------------------------------

    def _extract_via_lines(self, page: fitz.Page) -> List[Table]:
        """Extract tables using line-projection approach."""
        h_lines, v_lines = self._extract_lines_from_drawings(page)

        if len(h_lines) < 2 or len(v_lines) < 2:
            return []

        h_lines = self._merge_h_lines(h_lines)
        v_lines = self._merge_v_lines(v_lines)

        # NOTE: _filter_lines_by_components removed - it was over-filtering
        # legitimate table lines (60 -> 17, 112 -> 18). User confirmed:
        # "多余的线不影响表格结构的话，不过滤也没关系".
        # h_lines, v_lines = self._filter_lines_by_components(h_lines, v_lines)

        if len(h_lines) < 2 or len(v_lines) < 2:
            return []

        table_regions = self._find_table_regions(h_lines, v_lines)

        if not table_regions:
            return []

        tables = []
        for table_bbox, region_h_lines, region_v_lines in table_regions:
            cells = self._build_cells_for_region(
                table_bbox, region_h_lines, region_v_lines
            )
            if not cells:
                continue

            cells = self._assign_text_to_cells(cells, page)

            # Merge over-segmented columns (empty spacer columns)
            cells = self._merge_oversegmented_columns(cells)

            # NOTE: Removed _filter_sparse_top_rows and _filter_empty_rows
            # to preserve all rows detected by line projection.

            row_count = max((c.row_index for c in cells), default=-1) + 1
            col_count = max((c.col_index for c in cells), default=-1) + 1

            if row_count >= 1 and col_count >= 1 and cells:
                tables.append(
                    Table(
                        bbox=table_bbox,
                        rows=row_count,
                        cols=col_count,
                        cells=cells,
                        confidence=0.9,
                        source="line_projection",
                    )
                )

        return tables

    # ------------------------------------------------------------------
    # PyMuPDF fallback
    # ------------------------------------------------------------------

    def _extract_via_pymupdf(self, page: fitz.Page) -> List[Table]:
        """Fallback using PyMuPDF find_tables()."""
        try:
            tables_result = page.find_tables()
        except AttributeError:
            return []

        tables = []
        for table in tables_result.tables:
            bbox = BBox(*table.bbox)
            rows_data = table.extract()
            row_count = len(rows_data)
            col_count = len(rows_data[0]) if row_count > 0 else 0

            cells = []
            cell_bboxes = table.cells if hasattr(table, "cells") else []
            cell_idx = 0

            for r_idx, row in enumerate(rows_data):
                for c_idx, text in enumerate(row):
                    if cell_idx < len(cell_bboxes):
                        cb = BBox(*cell_bboxes[cell_idx])
                    else:
                        cb = BBox(0.0, 0.0, 0.0, 0.0)

                    cells.append(
                        Cell(
                            text=text or "",
                            row_index=r_idx,
                            col_index=c_idx,
                            bbox=cb,
                        )
                    )
                    cell_idx += 1

            tables.append(
                Table(
                    bbox=bbox,
                    rows=row_count,
                    cols=col_count,
                    cells=cells,
                    confidence=1.0,
                    source="PyMuPDF.find_tables",
                )
            )

        return tables
