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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import fitz

from hexai_pdf_parser.models import BBox, Cell, Table
from hexai_pdf_parser.table_config import TableConfig, LayoutProfile
from hexai_pdf_parser.table_profile_matcher import PageFeatures, match_profiles
from hexai_pdf_parser.table_region_rules import (
    TableRegionCandidate,
    apply_region_rules as apply_region_rules_fn,
)
from hexai_pdf_parser.table_structure_rules import apply_structure_rules
from hexai_pdf_parser.table_rule_handlers import (
    get_region_handler,
    get_structure_handler,
)
from hexai_pdf_parser.text_region_detector import (
    HorizontalSeparator,
    detect_candidate_regions,
    detect_separator_driven_regions,
)


@dataclass
class _RegionFragmentView:
    text: str
    bbox: BBox


@dataclass
class _RegionRowView:
    fragments: list[_RegionFragmentView]
    bbox: BBox


class TableExtractor:
    """Extract tables from a single PDF page using line-projection."""

    def __init__(
        self,
        line_tolerance: float = 2.0,
        merge_group_tol: float = 0.3,
        row_gap_threshold: float = 30.0,
        fallback_max_cols: int = 30,
        fallback_max_tables: int = 10,
        use_ml: bool = False,
        ml_model_path: str | None = None,
        ml_confidence: float = 0.25,
        table_config: TableConfig | None = None,
        ):
        self.line_tolerance = line_tolerance
        self.merge_group_tol = merge_group_tol
        self.row_gap_threshold = row_gap_threshold
        self.fallback_max_cols = fallback_max_cols
        self.fallback_max_tables = fallback_max_tables
        self.use_ml = use_ml
        self._ml_model_path = ml_model_path
        self._ml_confidence = ml_confidence
        self._ml_detector = None  # Lazy initialization
        self._last_text_alignment_debug: dict | None = None
        self._table_config = table_config

        # Override scalar args from config when provided
        if table_config is not None:
            settings = table_config.settings
            self.line_tolerance = settings.line_tolerance
            self.merge_group_tol = settings.merge_group_tol
            self.row_gap_threshold = settings.row_gap_threshold
            self.fallback_max_cols = settings.fallback_max_cols
            self.fallback_max_tables = settings.fallback_max_tables
            self._separator_min_width = settings.separator_min_width
            self._separator_max_height = settings.separator_max_height
        else:
            self._separator_min_width = 200.0
            self._separator_max_height = 1.5

    def extract(self, page: fitz.Page) -> List[Table]:
        """Return a list of :class:`Table` objects detected on *page*."""
        self._last_text_alignment_debug = None
        tables = self._extract_via_lines(page)

        # Fallback to PyMuPDF if no tables or if line_projection produced
        # overly fragmented / wide tables (merged-cell layouts).
        if not tables:
            tables = self._extract_via_pymupdf(page)
        elif self._should_fallback(tables):
            fallback_tables = self._extract_via_pymupdf(page)
            if fallback_tables:
                tables = fallback_tables

        # ML-based table region detection (supplemental).
        if self.use_ml:
            ml_tables = self._extract_via_ml(page)
            if ml_tables:
                existing_bboxes = [t.bbox for t in tables]
                for mt in ml_tables:
                    if not self._bbox_overlaps_any(mt.bbox, existing_bboxes):
                        tables.append(mt)

        # Supplement with text-aligned tables (text-only tables without drawn lines).
        text_tables = self._extract_via_text_alignment(page)
        if text_tables:
            existing_bboxes = [t.bbox for t in tables]
            for tt in text_tables:
                if not self._bbox_overlaps_any(tt.bbox, existing_bboxes):
                    tables.append(tt)

        # Apply layout rule system when a config with profiles is provided.
        if self._table_config and self._table_config.profiles:
            tables = self._apply_layout_rules(page, tables)

        return tables

    def _collect_page_text_lines(self, page: fitz.Page) -> List[str]:
        """Collect normalized text lines from a page for profile matching."""
        try:
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        except Exception:
            return []
        lines: List[str] = []
        for block in blocks:
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", []))
                stripped = text.strip()
                if stripped:
                    lines.append(stripped)
        return lines

    def _apply_layout_rules(
        self, page: fitz.Page, tables: List[Table]
    ) -> List[Table]:
        """Run profile matching and apply region/structure rules."""
        assert self._table_config is not None

        # 1. Profile matching
        text_lines = self._collect_page_text_lines(page)
        features = PageFeatures(text_lines=text_lines)
        profile = match_profiles(self._table_config.profiles, features)
        if profile is None:
            return tables

        # 2. Apply region rules
        if profile.region_rules.enabled:
            raw_rows = self._collect_text_rows(page.get_text("words"))

            # Build an initial candidate list: anchor-driven if anchors are
            # configured, otherwise derive from existing tables so that a
            # handler-only profile still receives candidates to refine.
            if profile.region_rules.expand_anchors:
                region_candidates = apply_region_rules_fn(
                    profile.region_rules, raw_rows
                )
            else:
                region_candidates = [
                    TableRegionCandidate(
                        bbox=t.bbox,
                        rows=[],
                        diagnostics={"source": t.source},
                    )
                    for t in tables
                ]

            # Let a registered handler refine the candidates regardless of
            # whether they came from anchors or from existing tables.
            if profile.region_rules.handler:
                try:
                    handler = get_region_handler(profile.region_rules.handler)
                    region_candidates = handler(region_candidates, raw_rows, {})
                except KeyError:
                    pass

            # Merge anchor-driven regions into the table list: add a
            # region as a new table only if it doesn't overlap existing
            # tables and contains enough rows to be plausible.
            if profile.region_rules.expand_anchors:
                existing_bboxes = [t.bbox for t in tables]
                for candidate in region_candidates:
                    if len(candidate.rows) < profile.region_rules.min_row_window:
                        continue
                    if not self._bbox_overlaps_any(
                        candidate.bbox, existing_bboxes
                    ):
                        row_count, col_count, cells = self._extract_cells_from_region(
                            page, candidate.bbox
                        )
                        if row_count >= profile.region_rules.min_row_window:
                            tables.append(
                                Table(
                                    bbox=candidate.bbox,
                                    rows=row_count,
                                    cols=col_count,
                                    cells=cells,
                                    confidence=0.7,
                                    source="region_rule",
                                )
                            )
                            existing_bboxes.append(candidate.bbox)

        # 3. Apply structure rules to each table
        if profile.structure_rules.enabled:
            corrected: List[Table] = []
            for table in tables:
                corrected.append(apply_structure_rules(profile.structure_rules, table))
            tables = corrected

            # Apply structure handler if specified — always write back so
            # cell-level corrections (text, bbox, col_index) take effect.
            if profile.structure_rules.handler:
                try:
                    handler = get_structure_handler(profile.structure_rules.handler)
                    from hexai_pdf_parser.table_structure_rules import TableStructureCandidate
                    for i, table in enumerate(tables):
                        candidate = TableStructureCandidate(
                            rows=table.rows,
                            cols=table.cols,
                            cells=list(table.cells),
                        )
                        result = handler(candidate, {})
                        tables[i] = Table(
                            bbox=table.bbox,
                            rows=result.rows,
                            cols=result.cols,
                            cells=result.cells,
                            confidence=table.confidence,
                            source=table.source,
                        )
                except KeyError:
                    pass

        return tables

    @staticmethod
    def _bbox_overlaps_any(bbox: BBox, others: List[BBox], threshold: float = 0.5) -> bool:
        """Return True if *bbox* overlaps significantly with any box in *others*."""
        for other in others:
            ix0 = max(bbox.x0, other.x0)
            iy0 = max(bbox.y0, other.y0)
            ix1 = min(bbox.x1, other.x1)
            iy1 = min(bbox.y1, other.y1)
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            area = (bbox.x1 - bbox.x0) * (bbox.y1 - bbox.y0)
            if area > 0 and inter / area >= threshold:
                return True
        return False

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
        occluding_rects: List[Tuple[int, fitz.Rect]],
    ) -> bool:
        """Return True if a later opaque paint operation fully covers *rect*.

        We use this as a conservative heuristic only for solid later content:
        fill paths, images, and shadings. Partial overlap should not hide the
        border candidate, but near-complete containment usually means the
        rectangle is not visually contributing to the final page appearance.
        """
        if seqno is None or not occluding_rects:
            return False

        area = rect.get_area()
        if area <= 0:
            return False

        import bisect
        # Find the first entry with an index > seqno.
        start_pos = bisect.bisect_right(occluding_rects, seqno, key=lambda x: x[0])

        for i in range(start_pos, len(occluding_rects)):
            _, cover_rect = occluding_rects[i]

            # Fast coordinate check for containment (allowing 0.1pt tolerance)
            # This avoids expensive Rect object creation and area calculations in the majority of cases.
            if (
                cover_rect.x0 <= rect.x0 + 0.1
                and cover_rect.y0 <= rect.y0 + 0.1
                and cover_rect.x1 >= rect.x1 - 0.1
                and cover_rect.y1 >= rect.y1 - 0.1
            ):
                return True

            # If not fully contained, check for partial intersection
            # Manual bbox overlap check to avoid calling into MuPDF
            if not (
                rect.x1 < cover_rect.x0
                or rect.x0 > cover_rect.x1
                or rect.y1 < cover_rect.y0
                or rect.y0 > cover_rect.y1
            ):
                inter = rect & cover_rect
                if inter.get_area() / area >= 0.98:
                    return True

        return False

    def _get_occluding_rects(self, bboxlog: List[Tuple]) -> List[Tuple[int, fitz.Rect]]:
        """Pre-filter and pre-convert occluding entries from bboxlog."""
        occluding_types = {"fill-path", "fill-image", "fill-shade"}
        result = []
        for idx, entry in enumerate(bboxlog):
            if entry and entry[0] in occluding_types:
                result.append((idx, fitz.Rect(entry[1])))
        return result

    def _iter_effective_drawing_rects(self, page: fitz.Page):
        """Yield (rect, drawing) for visible border rectangles not later occluded."""
        bboxlog = self._get_bboxlog(page)
        occluding_rects = self._get_occluding_rects(bboxlog)

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

                if self._is_rect_fully_covered_later(rect, seqno, occluding_rects):
                    continue

                yield rect, drawing

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
    # Text-aligned extraction
    # ------------------------------------------------------------------

    def _token_alignment_anchor(self, token: dict) -> Tuple[float, float]:
        """Return the anchor x-position and weight for a token."""
        if token.get("is_numeric"):
            anchor_x = token["x0"]  # use left edge for stability across number widths
            weight = 3.0
            if token.get("has_decimal"):
                weight += 1.5
            if token.get("has_group_separator"):
                weight += 1.0
            return anchor_x, weight

        text = token.get("text", "").strip()
        anchor_x = token["x0"]
        weight = 1.0
        if len(text) <= 2:
            weight = 1.1
        return anchor_x, weight

    def _rows_bbox(self, rows: List[dict]) -> BBox:
        """Return the tight bounding box around a list of row dictionaries."""
        return BBox(
            min(row["x0"] for row in rows),
            min(row["y0"] for row in rows),
            max(row["x1"] for row in rows),
            max(row["y1"] for row in rows),
        )

    def _is_section_header_row(self, row: dict) -> bool:
        """Return True when a row starts with a section/table-continuation marker."""
        if not row.get("tokens"):
            return False
        first_text = row["tokens"][0].get("text", "")
        SECTION_PATTERNS = (
            "续：", "（1）", "（2）", "（3）", "（4）", "（5）", "（6）",
            "（一）", "（二）", "（三）", "（四）", "（五）", "（六）",
            "Ⅰ.", "Ⅱ.", "Ⅲ.", "Ⅳ.", "Ⅴ.", "Ⅵ.",
        )
        for pat in SECTION_PATTERNS:
            if first_text.startswith(pat):
                return True
        # "3.", "4.", "5." etc. (ASCII or fullwidth "。") at row start (x0 < 150)
        # signal a new section header in financial reports.
        if len(first_text) >= 2 and first_text[1] in (".", "。" ) and first_text[0].isdigit():
            if first_text[0] in "3456789" and row["tokens"][0]["x0"] < 150:
                return True
        return False

    def _split_rows_into_spans(self, rows: List[dict]) -> List[List[dict]]:
        """Split sorted rows into spans using vertical gaps AND section-header signals.

        Section header rows (e.g. "续：", "（1）...") END the current span,
        so that the header itself starts the next span.  This ensures that
        each company's data section gets its own span for column inference.

        Large gaps (>= 25pt) also end the current span, with the row after
        the gap starting the next span.
        """
        if not rows:
            return []

        heights = [row["y1"] - row["y0"] for row in rows if row["y1"] > row["y0"]]
        median_height = sorted(heights)[len(heights) // 2] if heights else 10.0
        gap_threshold = max(18.0, median_height * 1.75)
        large_gap_threshold = max(22.0, median_height * 2.2)

        def left_x(row: dict) -> float:
            return row["tokens"][0]["x0"] if row.get("tokens") else row["x0"]

        spans: List[List[dict]] = []
        current: List[dict] = [rows[0]]
        current_bottom = rows[0]["y1"]
        # Track consecutive text-only rows for company 2 section-header detection.
        # Company 2 section headers: consecutive text-only rows with at least one
        # having text_end > 120 AND the sequence starts at x0 < 90.
        # Track the max text_end across the consecutive text-only rows.
        seq_text_only_count = 0
        seq_first_x0: float | None = None
        seq_max_text_end: float = 0.0

        def row_is_text_only(row: dict) -> bool:
            return not any(t.get("is_numeric") for t in row.get("tokens", []))

        def row_last_text_end(row: dict) -> float | None:
            last = None
            for t in row.get("tokens", []):
                if not t.get("is_numeric"):
                    last = t
            return last["x1"] if last is not None else None

        def _commit_split():
            spans.append(current)
            current_bottom = current[-1]["y1"]

        for row in rows[1:]:
            is_header = self._is_section_header_row(row)
            gap = row["y0"] - current_bottom
            lx = left_x(row)
            prev_lx = left_x(current[-1])
            is_text_only = row_is_text_only(row)
            text_end = row_last_text_end(row) if is_text_only else None

            if is_header:
                _commit_split()
                current = [row]
                current_bottom = row["y1"]
                seq_text_only_count = 0
                seq_first_x0 = None
                seq_max_text_end = 0.0
            elif gap > large_gap_threshold:
                _commit_split()
                current = [row]
                current_bottom = row["y1"]
                seq_text_only_count = 1 if is_text_only else 0
                seq_first_x0 = row["tokens"][0]["x0"] if is_text_only else None
                seq_max_text_end = text_end if is_text_only else 0.0
            elif gap > gap_threshold and (lx - prev_lx) > 50.0:
                _commit_split()
                current = [row]
                current_bottom = row["y1"]
                seq_text_only_count = 1 if is_text_only else 0
                seq_first_x0 = row["tokens"][0]["x0"] if is_text_only else None
                seq_max_text_end = text_end if is_text_only else 0.0
            elif (gap > gap_threshold
                    and is_text_only and text_end is not None and text_end > 200.0):
                # Medium gap followed by a very-wide text-only row (>200pt) → section
                # header (e.g. "二十二、应付票据").  Split here so each section gets
                # its own span for column inference.
                _commit_split()
                current = [row]
                current_bottom = row["y1"]
                seq_text_only_count = 1
                seq_first_x0 = row["tokens"][0]["x0"]
                seq_max_text_end = text_end
            elif (not is_text_only and seq_text_only_count >= 3
                    and seq_max_text_end > 120.0
                    and seq_first_x0 is not None and seq_first_x0 < 90):
                # First data row after 3+ consecutive text-only rows where at least
                # one has text_end > 120, and they start at x0<90 (company-data
                # label position).  Detects company 2 section headers whose "续："
                # marker was not extracted.
                _commit_split()
                current = [row]
                current_bottom = row["y1"]
                seq_text_only_count = 0
                seq_first_x0 = None
                seq_max_text_end = 0.0
            else:
                current.append(row)
                current_bottom = max(current_bottom, row["y1"])
                if is_text_only:
                    if seq_text_only_count == 0:
                        seq_first_x0 = row["tokens"][0]["x0"]
                        seq_max_text_end = text_end if text_end is not None else 0.0
                    else:
                        if text_end is not None:
                            seq_max_text_end = max(seq_max_text_end, text_end)
                    seq_text_only_count += 1
                else:
                    seq_text_only_count = 0
                    seq_first_x0 = None
                    seq_max_text_end = 0.0

        spans.append(current)
        return spans

    def _score_row_against_guides(self, row: dict, guides: List[float]) -> dict:
        """Score a row against the inferred column guides."""
        token_count = len(row["tokens"])
        tolerance = max(8.0, self.line_tolerance * 4)
        hits: set[int] = set()
        for token in row["tokens"]:
            anchor_x, _ = self._token_alignment_anchor(token)
            guide_idx = min(
                range(len(guides)),
                key=lambda idx: abs(guides[idx] - anchor_x),
            )
            if abs(guides[guide_idx] - anchor_x) <= tolerance:
                hits.add(guide_idx)

        hits = sorted(hits)
        row_width = max(row["x1"] - row["x0"], 0.0)
        guide_span = guides[-1] - guides[0] if len(guides) >= 2 else 0.0
        full_width = guide_span > 0 and row_width >= guide_span * 0.75
        long_text_tokens = sum(
            1
            for token in row["tokens"]
            if not token["is_numeric"] and len(token["text"].strip()) >= 8
        )
        numeric_tokens = sum(1 for token in row["tokens"] if token["is_numeric"])
        separated_hit_count = 0
        if hits:
            separated_hit_count = 1
            for left, right in zip(hits, hits[1:]):
                if guides[right] - guides[left] >= 24:
                    separated_hit_count += 1

        return {
            "hit_count": len(hits),
            "separated_hit_count": separated_hit_count,
            "token_count": token_count,
            "numeric_tokens": numeric_tokens,
            "long_text_tokens": long_text_tokens,
            "full_width": full_width,
            "looks_prose_with_fragments": full_width
            and len(hits) <= 2
            and separated_hit_count < 2
            and numeric_tokens <= 2
            and long_text_tokens >= 1,
            "is_structured": separated_hit_count >= 2 or len(hits) >= 3,
        }

    def _is_textual_false_positive_span(
        self, rows: List[dict], guides: List[float]
    ) -> bool:
        """Return True when a span looks like prose with numeric fragments.

        We only use this as a tightening filter after repeated column structure
        has already been detected.  Pure text-only tables are left alone.
        Section-header-prefixed spans (e.g. "续：" / "（1）" / "4.主要..." rows)
        are given more leeway since they start with header rows before the data.
        """
        if not rows or len(guides) < 2:
            return True

        # Detect if this span starts with a section header row
        starts_with_header = self._is_section_header_row(rows[0])

        row_scores = [self._score_row_against_guides(row, guides) for row in rows]
        structured_rows = sum(1 for score in row_scores if score["is_structured"])
        strong_rows = sum(1 for score in row_scores if score["hit_count"] >= 3)
        prose_fragment_rows = sum(
            1 for score in row_scores if score["looks_prose_with_fragments"]
        )

        # Section-header spans: require at least 1 structured row and allow
        # more prose-fragment rows (the header itself counts as one).
        if starts_with_header:
            if structured_rows < 1:
                return True
            # For short spans (≤10 rows) with a section header, allow them
            # through — the header is the "weak signal" and data rows follow.
            if len(rows) <= 10 and structured_rows >= 1:
                return False
            if len(rows) > 10 and structured_rows < max(2, len(rows) // 3):
                return True
            if prose_fragment_rows >= max(2, len(rows) - 1):
                return True
            return False

        if structured_rows < 2:
            return True
        if len(rows) >= 4 and structured_rows < max(2, len(rows) // 2):
            return True
        if len(guides) >= 3 and strong_rows == 0:
            return True
        if prose_fragment_rows >= max(2, len(rows) - 1):
            return True
        if len(rows) == 3 and prose_fragment_rows >= 1 and strong_rows >= 2:
            return True
        return False

    def _trim_span_to_structured_rows(
        self, rows: List[dict], guides: List[float]
    ) -> List[dict]:
        """Trim prose prefix/suffix rows from a candidate region.

        Uses a two-signal approach to label rows:

        1. **Guide-weight score** – each guide is weighted by the number of
           rows whose tokens align with it.  A row that only hits
           weakly-supported guides (e.g. a position used by just one row)
           gets a low score and is labelled *prose*.
        2. **Token-width gap** – when guide scores are uniform (all rows hit
           the same guides), we fall back to analysing mean token widths.
           A large gap in the sorted widths reveals a natural prose/table
           boundary.

        After labelling, the algorithm finds the highest-scoring contiguous
        interval of *structured*/*weak* rows (``structured * 3 + weak``)
        with at least 2 structured rows.
        """
        if not rows:
            return []

        labels = self._classify_rows_for_trimming(rows, guides)

        best_start = 0
        best_end = -1
        best_score = -1
        start = None
        structured_count = 0
        weak_count = 0

        for idx, label in enumerate(labels):
            if label == "prose":
                if start is not None:
                    interval_score = structured_count * 3 + weak_count
                    if structured_count >= 2 and interval_score > best_score:
                        best_start = start
                        best_end = idx - 1
                        best_score = interval_score
                start = None
                structured_count = 0
                weak_count = 0
                continue

            if start is None:
                start = idx
            if label == "structured":
                structured_count += 1
            else:
                weak_count += 1

        if start is not None:
            interval_score = structured_count * 3 + weak_count
            if structured_count >= 2 and interval_score > best_score:
                best_start = start
                best_end = len(labels) - 1

        if best_end < best_start:
            return []
        return rows[best_start : best_end + 1]

    def _classify_rows_for_trimming(
        self, rows: List[dict], guides: List[float]
    ) -> List[str]:
        """Return a label ("structured", "weak", or "prose") for each row."""
        if len(guides) < 2:
            return ["structured"] * len(rows)

        # --- Signal 1: guide weights ---
        # Score every row once via the shared helper, then derive guide
        # weights from the returned hit information to avoid recomputing
        # tolerance and guide matching.
        row_details = [self._score_row_against_guides(row, guides) for row in rows]

        tolerance = max(8.0, self.line_tolerance * 4)
        guide_hit_rows: List[set[int]] = [set() for _ in guides]
        for row_idx, row in enumerate(rows):
            for token in row["tokens"]:
                anchor_x, _ = self._token_alignment_anchor(token)
                guide_idx = min(
                    range(len(guides)),
                    key=lambda i: abs(guides[i] - anchor_x),
                )
                if abs(guides[guide_idx] - anchor_x) <= tolerance:
                    guide_hit_rows[guide_idx].add(row_idx)
        guide_weights = [len(r) for r in guide_hit_rows]

        # Filter out minority guides (supported by < 50% of the
        # strongest guide).  A spurious guide created by a few prose
        # tokens can inflate prose row scores above data rows.
        max_guide_weight = max(guide_weights) if guide_weights else 0
        majority_guides: set[int] = set()
        if max_guide_weight > 0:
            for gi, w in enumerate(guide_weights):
                if w >= max_guide_weight * 0.5:
                    majority_guides.add(gi)

        row_guide_scores: List[float] = []
        for row_idx, row in enumerate(rows):
            row_guide_scores.append(
                sum(
                    guide_weights[g]
                    for g in majority_guides
                    if row_idx in guide_hit_rows[g]
                )
            )

        guide_min = min(row_guide_scores)
        guide_max = max(row_guide_scores)
        guide_gap = guide_max - guide_min

        if guide_gap >= 2:
            # Guide weights distinguish rows: threshold = midpoint.
            guide_threshold = (guide_min + guide_max) / 2.0
            labels: List[str] = []
            for idx, row in enumerate(rows):
                score_detail = row_details[idx]
                if score_detail["is_structured"] and row_guide_scores[idx] >= guide_threshold:
                    labels.append("structured")
                elif score_detail["hit_count"] >= 1 and row_guide_scores[idx] >= guide_threshold:
                    labels.append("weak")
                else:
                    labels.append("prose")
        else:
            # --- Signal 2: token-width gap ---
            # Guide weights are uniform; look at mean token widths instead.
            # We only apply this signal when the gap is both relatively large
            # (>30% of range) AND absolutely significant (>3pt) to avoid
            # false positives on tightly-clustered widths.
            mean_widths = [
                sum(t["x1"] - t["x0"] for t in row["tokens"]) / max(len(row["tokens"]), 1)
                for row in rows
            ]
            sorted_widths = sorted(mean_widths)
            gaps = [
                sorted_widths[i + 1] - sorted_widths[i]
                for i in range(len(sorted_widths) - 1)
            ]

            if gaps:
                max_gap = max(gaps)
                width_range = sorted_widths[-1] - sorted_widths[0]
                # Require both a proportional and absolute gap to avoid
                # mis-classifying tightly-clustered widths (e.g. CJK text).
                if width_range > 0 and max_gap / width_range >= 0.30 and max_gap >= 2.0:
                    gap_idx = gaps.index(max_gap)
                    width_threshold = (
                        sorted_widths[gap_idx] + sorted_widths[gap_idx + 1]
                    ) / 2.0
                    # Token count heuristic: prose rows usually have more
                    # tokens per row than actual table data rows.
                    tokens_per_row = [len(r["tokens"]) for r in rows]
                    min_tokens = min(tokens_per_row)

                    labels = []
                    for idx, row in enumerate(rows):
                        score_detail = row_details[idx]
                        # Only mark a row as prose when the wider tokens are
                        # genuinely prose-like (no numeric content, full-width,
                        # sparse guide alignment, or extra tokens vs table rows).
                        is_wide_non_numeric = (
                            score_detail.get("full_width", False)
                            and score_detail.get("numeric_tokens", 0) == 0
                        )
                        is_prose_like = (
                            score_detail.get("looks_prose_with_fragments", False)
                            or (is_wide_non_numeric and score_detail.get("hit_count", 0) <= 2)
                            or (is_wide_non_numeric and len(row["tokens"]) > min_tokens)
                        )
                        if mean_widths[idx] > width_threshold and is_prose_like:
                            labels.append("prose")
                        elif score_detail["is_structured"]:
                            labels.append("structured")
                        elif score_detail["hit_count"] >= 1:
                            labels.append("weak")
                        else:
                            labels.append("prose")
                else:
                    labels = self._classify_rows_fallback(rows, row_details)
            else:
                labels = self._classify_rows_fallback(rows, row_details)

        # Protect rows that were merged as table headers via
        # _merge_header_like_span.  These rows were already verified to
        # have hit_count >= 1 against body guides, so they should not be
        # classified as prose even if the guide-weight or token-width
        # signals would normally reject them.
        for idx, row in enumerate(rows):
            if labels[idx] == "prose" and row.get("_is_merged_header"):
                if row_details[idx]["hit_count"] >= 1:
                    labels[idx] = "weak"

        return labels

    @staticmethod
    def _classify_rows_fallback(
        rows: List[dict], row_details: List[dict]
    ) -> List[str]:
        """Fallback classification when no clear guide-weight or width signal."""
        labels: List[str] = []
        for score_detail in row_details:
            if score_detail["is_structured"]:
                labels.append("structured")
            elif score_detail["hit_count"] >= 1:
                labels.append("weak")
            else:
                labels.append("prose")
        return labels

    def _looks_like_paragraph_region(self, rows: List[dict]) -> bool:
        """Return True for regions that look like flowing prose, not tables."""
        if len(rows) < 2:
            return False

        token_counts = [len(row["tokens"]) for row in rows]
        if max(token_counts) <= 1:
            return True

        numeric_rows = [
            row for row in rows if any(token["is_numeric"] for token in row["tokens"])
        ]
        if self._has_numeric_right_column_pattern(rows):
            return False

        region_width = max(row["x1"] for row in rows) - min(row["x0"] for row in rows)
        if region_width <= 0:
            return False

        avg_row_width = sum(row["x1"] - row["x0"] for row in rows) / len(rows)
        avg_token_count = sum(token_counts) / len(token_counts)
        avg_coverage = 0.0
        for row in rows:
            row_width = row["x1"] - row["x0"]
            if row_width <= 0:
                continue
            token_width = sum(
                token["x1"] - token["x0"]
                for token in row["tokens"]
                if token["x1"] > token["x0"]
            )
            avg_coverage += token_width / row_width
        avg_coverage /= len(rows)

        # Paragraphs usually consume most of the width on each line while not
        # repeating a stable multi-column pattern.
        if (
            not numeric_rows
            and len(rows) >= 3
            and max(token_counts) <= 2
            and avg_coverage >= 0.45
        ):
            return True

        if (
            len(rows) == 2
            and not numeric_rows
            and max(token_counts) <= 3
            and avg_row_width >= region_width * 0.8
            and avg_coverage >= 0.5
        ):
            return True

        if (
            avg_row_width >= region_width * 0.75
            and avg_token_count >= 3
            and avg_coverage >= 0.55
            and not numeric_rows
        ):
            return True

        dense_rows = sum(1 for count in token_counts if count >= 4)
        if (
            dense_rows >= max(2, len(rows) // 2)
            and avg_row_width >= region_width * 0.65
            and avg_coverage >= 0.5
            and not numeric_rows
        ):
            return True

        return False

    def _has_numeric_right_column_pattern(self, rows: List[dict]) -> bool:
        """Return True when rows consistently pair left text with a right numeric column."""
        if len(rows) < 2:
            return False

        supporting_rows = 0
        for row in rows:
            tokens = row["tokens"]
            numeric_tokens = [token for token in tokens if token["is_numeric"]]
            text_tokens = [token for token in tokens if not token["is_numeric"]]
            if not numeric_tokens or not text_tokens:
                continue

            numeric_anchor = min(token["x0"] for token in numeric_tokens)
            text_anchor = max(token["x1"] for token in text_tokens)
            if numeric_anchor - text_anchor >= 8.0:
                supporting_rows += 1

        return supporting_rows >= 2

    def _has_repeated_column_structure(self, rows: List[dict], guides: List[float]) -> bool:
        """Return True when multiple rows share at least two stable guides."""
        if len(guides) < 2:
            return False

        tolerance = max(8.0, self.line_tolerance * 4)
        row_hits: list[set[int]] = []
        for row in rows:
            hits: set[int] = set()
            for token in row["tokens"]:
                anchor_x, _ = self._token_alignment_anchor(token)
                guide_idx = min(
                    range(len(guides)),
                    key=lambda idx: abs(guides[idx] - anchor_x),
                )
                if abs(guides[guide_idx] - anchor_x) <= tolerance:
                    hits.add(guide_idx)
            row_hits.append(hits)

        if len(rows) == 1:
            return len(row_hits[0]) >= 2
        if len(rows) == 2:
            shared = row_hits[0] & row_hits[1]
            if len(shared) >= 2:
                return True
            # Allow sparse 2-row tables where one row has a blank cell, as long
            # as the surviving guides still line up across both rows.
            if len(shared) >= 1 and all(hits for hits in row_hits):
                return any(len(hits) >= 2 for hits in row_hits)
            return False

        guide_rows: list[set[int]] = [set() for _ in guides]
        supporting_rows = 0
        for row_idx, hits in enumerate(row_hits):
            if len(hits) >= 2:
                supporting_rows += 1
            for guide_idx in hits:
                guide_rows[guide_idx].add(row_idx)

        repeated_guides = sum(1 for row_ids in guide_rows if len(row_ids) >= 2)
        return supporting_rows >= 2 and repeated_guides >= 2

    def _infer_column_guides(
        self, rows: List[dict], region_bbox: BBox | None = None
    ) -> List[float]:
        """Infer stable column guide positions from aligned text rows.

        Two-phase strategy:
        1. Numeric anchors (right-aligned, x1) define data column boundaries.
           Text anchors (left-aligned, x0) in rows with numbers are used for
           the label column.  Text-only rows use x0 for all tokens.
        2. After clustering, text guides between two numeric guides are removed
           (they are header labels, not column boundaries).  Label-area text
           guides are merged with wider tolerance.
        """
        if not rows:
            return []

        anchors: List[Tuple[float, float, int, bool]] = []
        for row_idx, row in enumerate(rows):
            row_tokens = row["tokens"]
            numeric_positions = [
                idx for idx, token in enumerate(row_tokens) if token["is_numeric"]
            ]

            if numeric_positions:
                first_numeric_idx = numeric_positions[0]
                left_tokens = row_tokens[:first_numeric_idx]
                if left_tokens:
                    anchor_x = min(token["x0"] for token in left_tokens)
                    weight = sum(
                        self._token_alignment_anchor(token)[1]
                        for token in left_tokens
                    )
                    if (
                        region_bbox is None
                        or region_bbox.x0 - 5 <= anchor_x <= region_bbox.x1 + 5
                    ):
                        anchors.append((anchor_x, weight, row_idx, False))

                for token in row_tokens[first_numeric_idx:]:
                    anchor_x, weight = self._token_alignment_anchor(token)
                    if region_bbox is not None and not (
                        region_bbox.x0 - 5 <= anchor_x <= region_bbox.x1 + 5
                    ):
                        continue
                    anchors.append(
                        (anchor_x, weight, row_idx, token["is_numeric"])
                    )
                continue

            for token in row_tokens:
                anchor_x, weight = self._token_alignment_anchor(token)
                if region_bbox is not None and not (
                    region_bbox.x0 - 5 <= anchor_x <= region_bbox.x1 + 5
                ):
                    continue
                anchors.append(
                    (anchor_x, weight, row_idx, token["is_numeric"])
                )

        if not anchors:
            return []

        tolerance = max(8.0, self.line_tolerance * 4)
        clusters: List[dict] = []
        for anchor_x, weight, row_idx, is_num in sorted(
            anchors, key=lambda item: item[0]
        ):
            target = None
            for cluster in clusters:
                if abs(anchor_x - cluster["x"]) <= tolerance:
                    target = cluster
                    break

            if target is None:
                clusters.append(
                    {
                        "x": anchor_x,
                        "weight": weight,
                        "rows": {row_idx},
                        "numeric_weight": weight if is_num else 0.0,
                    }
                )
                continue

            total_weight = target["weight"] + weight
            target["x"] = (
                target["x"] * target["weight"] + anchor_x * weight
            ) / total_weight
            target["weight"] = total_weight
            target["rows"].add(row_idx)
            if is_num:
                target["numeric_weight"] += weight

        guides = [
            cluster
            for cluster in clusters
            if cluster["weight"] >= 2.0
            and (
                len(cluster["rows"]) >= 2
                or (len(rows) == 2 and cluster["weight"] >= 3.0)
            )
        ]

        # --- Post-processing: remove spurious text-only guides ---
        numeric_xs = sorted(
            c["x"] for c in guides if c["numeric_weight"] >= 2.0
        )

        if len(numeric_xs) >= 2:
            # 1. Remove text-only guides that sit between two numeric
            #    guides — they are header labels, not column boundaries.
            filtered: List[dict] = []
            for cluster in guides:
                if cluster["numeric_weight"] >= 2.0:
                    filtered.append(cluster)
                    continue
                x = cluster["x"]
                between = any(
                    numeric_xs[i] < x < numeric_xs[i + 1]
                    for i in range(len(numeric_xs) - 1)
                )
                if not between:
                    filtered.append(cluster)

            # 2. Merge label-area text guides (left of first numeric) with
            #    wider tolerance.  Different text tokens in the same label
            #    column often have different left margins.
            first_numeric_x = numeric_xs[0]
            label_clusters = [
                c
                for c in filtered
                if c["x"] < first_numeric_x and c["numeric_weight"] < 2.0
            ]
            other_clusters = [
                c
                for c in filtered
                if not (c["x"] < first_numeric_x and c["numeric_weight"] < 2.0)
            ]

            if len(label_clusters) > 1:
                min_gap = min(
                    numeric_xs[i + 1] - numeric_xs[i]
                    for i in range(len(numeric_xs) - 1)
                )
                label_tol = min_gap * 0.5
                label_clusters.sort(key=lambda c: c["x"])
                merged_labels: List[dict] = [label_clusters[0]]
                for lc in label_clusters[1:]:
                    prev = merged_labels[-1]
                    if abs(lc["x"] - prev["x"]) <= label_tol:
                        tw = prev["weight"] + lc["weight"]
                        prev["x"] = (
                            prev["x"] * prev["weight"] + lc["x"] * lc["weight"]
                        ) / tw
                        prev["weight"] = tw
                        prev["rows"].update(lc["rows"])
                    else:
                        merged_labels.append(lc)
                guides = other_clusters + merged_labels
            else:
                guides = other_clusters + label_clusters

        result = sorted(c["x"] for c in guides)
        return result

    def _extract_text_region_separators(
        self,
        page: fitz.Page,
    ) -> list[HorizontalSeparator]:
        separators: list[HorizontalSeparator] = []

        # First, try to detect text-based separators (lines of dashes/underscores)
        text_separators = self._extract_text_based_separators(page)
        separators.extend(text_separators)

        # Then, try to detect drawing-based separators
        drawing_separators = self._extract_drawing_separators(page)
        separators.extend(drawing_separators)

        if not separators:
            return []

        separators.sort(key=lambda item: (item.y, item.x0))
        deduped: list[HorizontalSeparator] = []
        for separator in separators:
            if (
                deduped
                and abs(separator.y - deduped[-1].y) <= 1.0
                and separator.x0 <= deduped[-1].x1 + 2.0
            ):
                prev = deduped[-1]
                deduped[-1] = HorizontalSeparator(
                    x0=min(prev.x0, separator.x0),
                    x1=max(prev.x1, separator.x1),
                    y=(prev.y + separator.y) / 2.0,
                )
            else:
                deduped.append(separator)
        return deduped

    def _extract_text_based_separators(
        self,
        page: fitz.Page,
    ) -> list[HorizontalSeparator]:
        """Detect horizontal separators made of text characters (dashes, underscores, etc.)."""
        separators: list[HorizontalSeparator] = []
        try:
            words = page.get_text("words")
        except Exception:
            return separators

        # Patterns that indicate a text-based separator line
        separator_chars = {"-", "_", "—", "–", "─", "━", "＝", "□", "■", "▪", "▫"}

        # Group words by y position
        words_by_y: dict[float, list] = defaultdict(list)
        for word in words:
            x0, y0, x1, y1 = word[0], word[1], word[2], word[3]
            text = word[4].strip()
            y_center = (y0 + y1) / 2.0
            words_by_y[y_center].append((x0, x1, text))

        # Check each y position for separator patterns
        page_width = page.rect.width
        for y, word_list in words_by_y.items():
            # Check if all words at this y are separator characters
            separator_words = [w for w in word_list if len(w[2]) > 0 and all(c in separator_chars for c in w[2])]
            if not separator_words:
                continue

            # Check if combined width is substantial
            min_x = min(w[0] for w in separator_words)
            max_x = max(w[1] for w in separator_words)
            total_width = max_x - min_x

            # Require separator to span at least 100 pixels
            # (This catches typical dash/underscore separator lines)
            min_separator_width = 100.0
            if total_width >= min_separator_width:
                separators.append(
                    HorizontalSeparator(
                        x0=float(min_x),
                        x1=float(max_x),
                        y=float(y),
                    )
                )

        return separators

    def _extract_drawing_separators(
        self,
        page: fitz.Page,
    ) -> list[HorizontalSeparator]:
        """Detect horizontal separators from page drawings (rectangles, lines)."""
        separators: list[HorizontalSeparator] = []
        try:
            drawings = page.get_drawings()
        except Exception:
            return separators

        # Use a larger threshold for line stroke width to catch thicker separators
        # The _separator_max_height is typically 1.5, but real PDFs often have
        # stroke widths of 2.0-3.0 for visible separator lines
        max_line_stroke = max(self._separator_max_height, 3.0)

        for drawing in drawings:
            stroke_width = drawing.get("width", 1.0)
            for item in drawing.get("items", []):
                if item[0] == "re":
                    rect = item[1]
                    width = rect.x1 - rect.x0
                    height = rect.y1 - rect.y0
                    if width < self._separator_min_width or height > self._separator_max_height:
                        continue
                    separators.append(
                        HorizontalSeparator(
                            x0=float(rect.x0),
                            x1=float(rect.x1),
                            y=float((rect.y0 + rect.y1) / 2.0),
                        )
                    )
                elif item[0] == "l":
                    p1, p2 = item[1], item[2]
                    line_width = abs(p2.x - p1.x)
                    line_height = abs(p2.y - p1.y)
                    # Accept near-horizontal lines that are long enough
                    # Use larger stroke width threshold to catch thicker lines
                    if line_width < self._separator_min_width:
                        continue
                    if line_height > max_line_stroke:
                        continue
                    if stroke_width > max_line_stroke:
                        continue
                    separators.append(
                        HorizontalSeparator(
                            x0=float(min(p1.x, p2.x)),
                            x1=float(max(p1.x, p2.x)),
                            y=float((p1.y + p2.y) / 2.0),
                        )
                    )

        return separators

    def _detect_text_regions(
        self,
        rows: List[dict],
        page: fitz.Page,
    ) -> List[dict]:
        if not rows:
            return []

        visual_rows: list[_RegionRowView] = []
        original_rows_by_view_id: dict[int, dict] = {}
        for row in rows:
            fragments = [
                _RegionFragmentView(
                    text=token["text"],
                    bbox=BBox(
                        token["x0"],
                        token["y0"],
                        token["x1"],
                        token["y1"],
                    ),
                )
                for token in row["tokens"]
            ]
            visual_row = _RegionRowView(
                fragments=fragments,
                bbox=BBox(row["x0"], row["y0"], row["x1"], row["y1"]),
            )
            visual_rows.append(visual_row)
            original_rows_by_view_id[id(visual_row)] = row

        separators = self._extract_text_region_separators(page)
        candidate_regions = detect_candidate_regions(
            visual_rows,
            horizontal_separators=separators,
        )

        # If no candidate regions found, try separator-driven detection
        # This handles dense prose pages where _group_contiguous_runs filters everything
        if not candidate_regions and separators:
            separator_regions = detect_separator_driven_regions(
                visual_rows,
                separators,
                page.rect.width,
            )
            candidate_regions.extend(separator_regions)

        mapped_regions: List[dict] = []
        for region in candidate_regions:
            mapped_rows = [
                original_rows_by_view_id[id(view_row)]
                for view_row in region.rows
                if id(view_row) in original_rows_by_view_id
            ]
            if not mapped_rows:
                continue
            bbox = self._rows_bbox(mapped_rows)
            guides = self._infer_column_guides(mapped_rows, bbox)
            if len(guides) < 2:
                continue
            if not self._has_repeated_column_structure(mapped_rows, guides):
                continue
            if self._is_textual_false_positive_span(mapped_rows, guides):
                continue
            mapped_regions.append(
                {
                    "rows": mapped_rows,
                    "bbox": bbox,
                    "column_guides": guides,
                }
            )

        return mapped_regions

    def _merge_header_like_span(
        self,
        previous_rows: List[dict],
        body_rows: List[dict],
        body_guides: List[float],
    ) -> List[dict]:
        """Merge a short header-like span with its following body span."""
        if not previous_rows or not body_rows:
            return body_rows

        prev_bbox = self._rows_bbox(previous_rows)
        body_bbox = self._rows_bbox(body_rows)
        vertical_gap = body_bbox.y0 - prev_bbox.y1
        horizontal_overlap = min(prev_bbox.x1, body_bbox.x1) - max(
            prev_bbox.x0, body_bbox.x0
        )
        overlap_ratio = horizontal_overlap / max(
            min(prev_bbox.x1 - prev_bbox.x0, body_bbox.x1 - body_bbox.x0), 1.0
        )

        if len(previous_rows) > 3:
            return body_rows
        if vertical_gap < 0 or vertical_gap > 60:
            return body_rows
        if overlap_ratio < 0.6:
            return body_rows
        if self._looks_like_paragraph_region(previous_rows):
            return body_rows

        aligned_rows = 0
        for row in previous_rows:
            score = self._score_row_against_guides(row, body_guides)
            if score["hit_count"] >= 1:
                aligned_rows += 1

        if aligned_rows == 0:
            return body_rows
        return previous_rows + body_rows

    def _extract_via_text_alignment(self, page: fitz.Page) -> List[Table]:
        """Extract tables from aligned text when drawing lines are absent."""
        self._last_text_alignment_debug = None
        try:
            words = page.get_text("words")
        except Exception:
            return []

        rows = self._collect_text_rows(words)
        if not rows:
            return []

        candidate_regions = self._detect_text_regions(rows, page)
        if not candidate_regions:
            return []

        # Identify spans rejected by _detect_text_regions so we can attempt
        # to merge them as headers with the next candidate region.
        all_spans = self._split_rows_into_spans(rows)
        region_start_rows = {id(reg["rows"][0]) for reg in candidate_regions}
        rejected_span_before: dict[int, List[dict]] = {}
        prev_rejected: List[dict] | None = None
        for span in all_spans:
            if id(span[0]) in region_start_rows:
                # This span became a candidate region.
                # Find which region index it corresponds to.
                for ri, reg in enumerate(candidate_regions):
                    if reg["rows"][0] is span[0]:
                        if prev_rejected is not None:
                            rejected_span_before[ri] = prev_rejected
                            prev_rejected = None
                        break
            else:
                prev_rejected = span

        tables: List[Table] = []
        debug_regions: list[dict] = []
        for idx, region in enumerate(candidate_regions):
            region_rows = region["rows"]
            guides = region["column_guides"]

            # Try merging a preceding rejected span as a table header.
            if idx in rejected_span_before:
                header_rows = rejected_span_before[idx]
                merged_rows = self._merge_header_like_span(
                    header_rows, region_rows, guides
                )
                if merged_rows is not region_rows:
                    for hr in header_rows:
                        hr["_is_merged_header"] = True
                    region_rows = merged_rows

            if len(guides) < 2:
                continue

            # Trim prose prefix/suffix rows that don't align with the
            # column structure.  Only applies to short spans to avoid
            # accidentally removing rows from multi-section financial
            # tables where different sections have different column
            # patterns.
            if len(region_rows) <= 12:
                trimmed = self._trim_span_to_structured_rows(region_rows, guides)
                if 2 <= len(trimmed) < len(region_rows):
                    trimmed_start = next(
                        (
                            idx
                            for idx, row in enumerate(region_rows)
                            if row is trimmed[0]
                        ),
                        0,
                    )
                    leading_rows = region_rows[:trimmed_start]
                    region_rows = trimmed
                    # Re-infer guides from trimmed rows so that columns
                    # created only by prose tokens are removed.
                    guides = self._infer_column_guides(region_rows)
                    if len(guides) < 2:
                        continue
                    # Merge a single leading row as header if it looks like
                    # a table header. We check two conditions:
                    # 1. Token count matches column count (len(guides)) —
                    #    this handles header rows with different alignment
                    #    (e.g., centered) from the body rows.
                    # 2. Vertical gap is reasonable (>= 16px for a table title).
                    if leading_rows:
                        is_header_by_column_count = len(leading_rows[-1]["tokens"]) == len(guides)
                        is_header_by_gap = (
                            region_rows[0]["y0"] - leading_rows[-1]["y1"] >= 16.0
                        )
                        # Check if there's a separator between header and body.
                        # Separator presence strongly indicates a table structure
                        # where the header row should be included.
                        has_separator = False
                        header_bottom = leading_rows[-1]["y1"]
                        body_top = region_rows[0]["y0"]
                        for sep in self._extract_text_region_separators(page):
                            if header_bottom <= sep.y <= body_top:
                                has_separator = True
                                break

                        if len(leading_rows) == 1 and (
                            is_header_by_gap or (is_header_by_column_count and has_separator)
                        ):
                            if is_header_by_column_count:
                                # Direct merge: header row has same number of tokens
                                # as columns. Only bypass the alignment check when:
                                # 1. The header row has NO tokens aligned with guides
                                #    (hit_count == 0) — handles centered/offset headers
                                # 2. There's a visible separator between header and body
                                #    OR the vertical gap is large enough (>= 16px)
                                header_score = self._score_row_against_guides(
                                    leading_rows[-1], guides
                                )
                                if (
                                    header_score["hit_count"] == 0
                                    and (has_separator or is_header_by_gap)
                                ):
                                    for header_row in leading_rows:
                                        header_row["_is_merged_header"] = True
                                    region_rows = leading_rows + region_rows
                                else:
                                    merged_rows = self._merge_header_like_span(
                                        leading_rows,
                                        region_rows,
                                        guides,
                                    )
                                    if merged_rows is not region_rows:
                                        for header_row in leading_rows:
                                            header_row["_is_merged_header"] = True
                                        region_rows = merged_rows
                            else:
                                merged_rows = self._merge_header_like_span(
                                    leading_rows,
                                    region_rows,
                                    guides,
                                )
                                if merged_rows is not region_rows:
                                    for header_row in leading_rows:
                                        header_row["_is_merged_header"] = True
                                    region_rows = merged_rows

                region_bbox = self._rows_bbox(region_rows)

            row_count, col_count, cells = self._build_text_alignment_table(
                region_rows, guides, region_bbox
            )

            if row_count < 1 or col_count < 1 or not cells:
                continue

            tables.append(
                Table(
                    bbox=region_bbox,
                    rows=row_count,
                    cols=col_count,
                    cells=cells,
                    confidence=0.75,
                    source="text_alignment",
                )
            )
            debug_regions.append(
                {
                    "bbox": {
                        "x0": region_bbox.x0,
                        "y0": region_bbox.y0,
                        "x1": region_bbox.x1,
                        "y1": region_bbox.y1,
                    },
                    "rows": [
                        {
                            "x0": row["x0"],
                            "y0": row["y0"],
                            "x1": row["x1"],
                            "y1": row["y1"],
                        }
                        for row in region_rows
                    ],
                    "column_guides": list(guides),
                }
            )

        if tables and debug_regions:
            self._last_text_alignment_debug = {
                "page_index": page.number,
                "regions": debug_regions,
            }

        return tables

    def capture_text_alignment_snapshot(
        self, page: fitz.Page, region_bbox: BBox
    ) -> dict:
        """Capture the structure-stage input for a trusted text region.

        The returned snapshot is JSON-serializable and can be replayed without
        re-running PDF text extraction.
        """

        try:
            words = page.get_text(
                "words",
                clip=fitz.Rect(
                    region_bbox.x0,
                    region_bbox.y0,
                    region_bbox.x1,
                    region_bbox.y1,
                ),
            )
        except Exception:
            return {}

        rows = self._collect_text_rows(words)
        if not rows:
            return {}

        guides = self._build_region_guides(rows, region_bbox)
        if len(guides) < 2:
            return {}

        return {
            "bbox": {
                "x0": region_bbox.x0,
                "y0": region_bbox.y0,
                "x1": region_bbox.x1,
                "y1": region_bbox.y1,
            },
            "rows": rows,
            "column_guides": guides,
        }

    def build_table_from_text_alignment_snapshot(
        self, snapshot: dict
    ) -> tuple[int, int, List[Cell]]:
        """Rebuild a table from a text-alignment snapshot."""

        bbox_data = snapshot.get("bbox") or {}
        region_bbox = BBox(
            float(bbox_data.get("x0", 0.0)),
            float(bbox_data.get("y0", 0.0)),
            float(bbox_data.get("x1", 0.0)),
            float(bbox_data.get("y1", 0.0)),
        )
        rows = snapshot.get("rows") or []
        guides = [float(x) for x in snapshot.get("column_guides") or []]
        return self._build_text_alignment_table(rows, guides, region_bbox)

    def _build_text_alignment_table(
        self, region_rows: List[dict], guides: List[float], region_bbox: BBox
    ) -> tuple[int, int, List[Cell]]:
        """Build a table from precomputed text rows and column guides."""

        if len(region_rows) < 1 or len(guides) < 2:
            return 0, 0, []

        guides = self._compact_column_guides(region_rows, guides)
        if len(guides) < 2:
            return 0, 0, []

        # Column boundaries = midpoints between consecutive guides.
        boundaries = [
            (guides[i] + guides[i + 1]) / 2.0
            for i in range(len(guides) - 1)
        ]

        def _col_for_token(token: dict) -> int:
            cx = (token["x0"] + token["x1"]) / 2.0
            for bi, b in enumerate(boundaries):
                if cx < b:
                    return bi
            return len(boundaries)

        cells_by_row: dict[int, dict[int, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row_idx, row in enumerate(region_rows):
            for token in row["tokens"]:
                col_idx = _col_for_token(token)
                cells_by_row[row_idx][col_idx].append(token)

        cells: List[Cell] = []
        for row_idx, guide_map in cells_by_row.items():
            for col_idx, tokens in guide_map.items():
                tokens.sort(key=lambda token: token["x0"])
                text = " ".join(
                    token["text"].strip()
                    for token in tokens
                    if token["text"].strip()
                )
                if not text:
                    continue

                cells.append(
                    Cell(
                        text=text,
                        row_index=row_idx,
                        col_index=col_idx,
                        bbox=BBox(
                            min(token["x0"] for token in tokens),
                            min(token["y0"] for token in tokens),
                            max(token["x1"] for token in tokens),
                            max(token["y1"] for token in tokens),
                        ),
                    )
                )

        if not cells:
            return 0, 0, []

        cells = self._merge_oversegmented_columns(cells)
        cells = self._merge_numeric_fragment_columns(cells)
        cells = self._infer_sparse_rowspans(cells, region_rows)

        if not cells:
            return 0, 0, []

        row_count = max(
            (c.row_index + max(1, c.rowspan) - 1 for c in cells),
            default=-1,
        ) + 1
        col_count = max(
            (c.col_index + max(1, c.colspan) - 1 for c in cells),
            default=-1,
        ) + 1
        return row_count, col_count, cells

    def _compact_column_guides(
        self, rows: List[dict], guides: List[float]
    ) -> List[float]:
        """Remove weak guide spikes that create over-fragmented columns."""

        if len(guides) < 3:
            return sorted(guides)

        tolerance = max(8.0, self.line_tolerance * 4)
        support_rows: list[set[int]] = [set() for _ in guides]
        numeric_weight: list[float] = [0.0 for _ in guides]

        for row_idx, row in enumerate(rows):
            row_hits: set[int] = set()
            for token in row["tokens"]:
                anchor_x, weight = self._token_alignment_anchor(token)
                guide_idx = min(
                    range(len(guides)),
                    key=lambda idx: abs(guides[idx] - anchor_x),
                )
                if abs(guides[guide_idx] - anchor_x) <= tolerance:
                    row_hits.add(guide_idx)
                    if token["is_numeric"]:
                        numeric_weight[guide_idx] += weight
            for guide_idx in row_hits:
                support_rows[guide_idx].add(row_idx)

        target_max = max(4, min(12, len(rows) // 2 + 4))
        if len(guides) <= target_max:
            return sorted(guides)

        active = list(range(len(guides)))
        support = [len(rows_hit) for rows_hit in support_rows]

        def guide_gap(left_idx: int, right_idx: int) -> float:
            return abs(guides[right_idx] - guides[left_idx])

        while len(active) > target_max:
            best_pos = None
            best_score = None

            for pos, guide_idx in enumerate(active):
                if pos == 0 or pos == len(active) - 1:
                    continue

                left_idx = active[pos - 1]
                right_idx = active[pos + 1]
                left_gap = guide_gap(left_idx, guide_idx)
                right_gap = guide_gap(guide_idx, right_idx)
                closeness = min(left_gap, right_gap)
                if closeness > max(22.0, self.line_tolerance * 6):
                    continue

                score = (
                    support[guide_idx] * 3.0
                    + numeric_weight[guide_idx] * 0.5
                    + closeness
                )

                if best_score is None or score < best_score:
                    best_score = score
                    best_pos = pos

            if best_pos is None:
                break

            active.pop(best_pos)

        compacted = [guides[idx] for idx in active]
        return sorted(compacted) if len(compacted) >= 2 else sorted(guides)

    def _merge_numeric_fragment_columns(self, cells: List[Cell]) -> List[Cell]:
        """Merge short numeric fragments that were split into adjacent columns."""

        if not cells:
            return cells

        rows: dict[int, List[Cell]] = defaultdict(list)
        for cell in cells:
            rows[cell.row_index].append(cell)

        merged: List[Cell] = []
        for row_idx in sorted(rows):
            row_cells = sorted(rows[row_idx], key=lambda cell: cell.col_index)
            numeric_cells = [
                cell for cell in row_cells if self._looks_like_numeric_fragment(cell.text)
            ]

            if len(row_cells) < 4 or len(numeric_cells) < 4:
                merged.extend(row_cells)
                continue

            i = 0
            while i < len(row_cells):
                cell = row_cells[i]
                if not self._looks_like_numeric_fragment(cell.text):
                    merged.append(cell)
                    i += 1
                    continue

                run = [cell]
                j = i + 1
                while j < len(row_cells):
                    nxt = row_cells[j]
                    if not self._looks_like_numeric_fragment(nxt.text):
                        break
                    prev = run[-1]
                    gap = nxt.bbox.x0 - prev.bbox.x1
                    if gap > max(14.0, self.line_tolerance * 2):
                        break
                    run.append(nxt)
                    j += 1

                if len(run) >= 2 and any(len(part.text.strip()) <= 8 for part in run):
                    merged.append(
                        Cell(
                            text="".join(part.text.strip() for part in run if part.text.strip()),
                            row_index=run[0].row_index,
                            col_index=run[0].col_index,
                            bbox=BBox(
                                min(part.bbox.x0 for part in run),
                                min(part.bbox.y0 for part in run),
                                max(part.bbox.x1 for part in run),
                                max(part.bbox.y1 for part in run),
                            ),
                            colspan=(
                                run[-1].col_index + max(1, run[-1].colspan)
                                - run[0].col_index
                            ),
                        )
                    )
                    i = j
                    continue

                merged.extend(run)
                i += len(run)

        merged.sort(key=lambda cell: (cell.row_index, cell.col_index))
        return merged

    @staticmethod
    def _looks_like_numeric_fragment(text: str) -> bool:
        """Return True for short numeric strings that often get over-split."""

        stripped = text.strip()
        if not stripped:
            return False
        if len(stripped) > 12:
            return False
        has_digit = any(ch.isdigit() for ch in stripped)
        if not has_digit:
            return False
        numeric_chars = set("0123456789,.-+()% ")
        return all(ch in numeric_chars for ch in stripped)

    # ------------------------------------------------------------------
    # ML-based table detection
    # ------------------------------------------------------------------

    def _extract_via_ml(self, page: fitz.Page) -> List[Table]:
        """Detect table regions using ML model and build cells via text alignment."""
        try:
            if self._ml_detector is None:
                from hexai_pdf_parser.ml_table_detector import MLTableDetector
                self._ml_detector = MLTableDetector(
                    model_path=self._ml_model_path,
                    confidence_threshold=self._ml_confidence,
                )
            bboxes = self._ml_detector.detect(page)
        except ImportError:
            import warnings
            warnings.warn(
                "ML table detection unavailable (onnxruntime not installed). "
                "Install with: pip install hexai_pdf_parser[ml]",
                stacklevel=2,
            )
            return []
        except Exception:
            return []

        if not bboxes:
            return []

        tables: List[Table] = []
        for bbox in bboxes:
            row_count, col_count, cells = self._extract_cells_from_region(page, bbox)
            if row_count >= 1 and col_count >= 1 and cells:
                tables.append(
                    Table(
                        bbox=bbox,
                        rows=row_count,
                        cols=col_count,
                        cells=cells,
                        confidence=0.85,
                        source="ml_detection",
                    )
                )
        return tables

    def _extract_cells_from_region(
        self, page: fitz.Page, region_bbox: BBox
    ) -> tuple[int, int, List[Cell]]:
        """Recover a table grid from text inside a trusted table region."""
        try:
            words = page.get_text(
                "words",
                clip=fitz.Rect(
                    region_bbox.x0, region_bbox.y0,
                    region_bbox.x1, region_bbox.y1,
                ),
            )
        except Exception:
            return 0, 0, []

        rows = self._collect_text_rows(words)
        if not rows:
            return 0, 0, []

        guides = self._build_region_guides(rows, region_bbox)
        if len(guides) < 2:
            return 0, 0, []

        cells = self._build_text_grid_cells(rows, guides)
        if not cells:
            return 0, 0, []

        cells = self._merge_oversegmented_columns(cells)
        cells = self._infer_sparse_rowspans(cells, rows)

        if not cells:
            return 0, 0, []

        row_count = max(
            (c.row_index + max(1, c.rowspan) - 1 for c in cells),
            default=-1,
        ) + 1
        col_count = max(
            (c.col_index + max(1, c.colspan) - 1 for c in cells),
            default=-1,
        ) + 1
        return row_count, col_count, cells

    def _build_region_guides(
        self, rows: List[dict], region_bbox: BBox
    ) -> List[float]:
        """Combine row-level and span-level column guides into one skeleton."""

        guide_sources: list[tuple[List[float], int]] = []

        full_guides = self._infer_column_guides(rows, region_bbox)
        if len(full_guides) >= 2:
            guide_sources.append((full_guides, len(rows)))

        for span in self._split_rows_into_spans(rows):
            if len(span) < 2:
                continue
            span_guides = self._infer_column_guides(span, region_bbox)
            if len(span_guides) < 2:
                continue
            if self._is_textual_false_positive_span(span, span_guides):
                continue
            guide_sources.append((span_guides, len(span)))

        if not guide_sources:
            return []

        anchors: list[tuple[float, float]] = []
        for guides, support in guide_sources:
            weight = float(max(1, support))
            for guide in guides:
                anchors.append((guide, weight))

        if not anchors:
            return []

        tolerance = max(8.0, self.line_tolerance * 4)
        clusters: list[dict[str, float]] = []
        for guide, weight in sorted(anchors, key=lambda item: item[0]):
            if not clusters or abs(guide - clusters[-1]["x"]) > tolerance:
                clusters.append({"x": guide, "weight": weight})
                continue

            prev = clusters[-1]
            total_weight = prev["weight"] + weight
            prev["x"] = (prev["x"] * prev["weight"] + guide * weight) / total_weight
            prev["weight"] = total_weight

        guides = [cluster["x"] for cluster in clusters if cluster["weight"] >= 1.0]
        if len(guides) >= 2:
            return sorted(guides)

        strongest = max(guide_sources, key=lambda item: (len(item[0]), item[1]))
        return sorted(strongest[0])

    def _build_text_grid_cells(
        self, rows: List[dict], guides: List[float]
    ) -> List[Cell]:
        """Build cells by assigning each text token to a guide interval."""

        if len(guides) < 2:
            return []

        boundaries = [
            (guides[i] + guides[i + 1]) / 2.0
            for i in range(len(guides) - 1)
        ]

        def _token_column_span(token: dict) -> tuple[int, int]:
            x0 = float(token["x0"])
            x1 = float(token["x1"])
            if x1 < x0:
                x0, x1 = x1, x0

            start_col = 0
            while start_col < len(boundaries) and x0 > boundaries[start_col]:
                start_col += 1

            end_col = 0
            while end_col < len(boundaries) and x1 >= boundaries[end_col]:
                end_col += 1

            start_col = min(start_col, len(guides) - 1)
            end_col = min(max(end_col, start_col), len(guides) - 1)
            return start_col, end_col

        grouped_tokens: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
        for row_idx, row in enumerate(rows):
            for token in row["tokens"]:
                if not token["text"].strip():
                    continue
                start_col, end_col = _token_column_span(token)
                grouped_tokens[(row_idx, start_col, end_col)].append(token)

        cells: List[Cell] = []
        for (row_idx, start_col, end_col), tokens in grouped_tokens.items():
            tokens.sort(key=lambda token: token["x0"])
            text = " ".join(
                token["text"].strip()
                for token in tokens
                if token["text"].strip()
            ).strip()
            if not text:
                continue

            cells.append(
                Cell(
                    text=text,
                    row_index=row_idx,
                    col_index=start_col,
                    bbox=BBox(
                        min(token["x0"] for token in tokens),
                        min(token["y0"] for token in tokens),
                        max(token["x1"] for token in tokens),
                        max(token["y1"] for token in tokens),
                    ),
                    colspan=end_col - start_col + 1,
                )
            )

        cells.sort(key=lambda cell: (cell.row_index, cell.col_index))
        return cells

    def _infer_sparse_rowspans(
        self, cells: List[Cell], rows: List[dict]
    ) -> List[Cell]:
        """Extend obvious vertical label cells downward when columns stay empty.

        This is conservative: it only extends cells when a following row has
        content elsewhere but leaves the same column empty, which is the common
        signature of a vertically merged stub or header cell in wireless tables.
        """

        if not cells or not rows:
            return cells

        row_coverage: dict[int, set[int]] = defaultdict(set)
        for cell in cells:
            for col in range(cell.col_index, cell.col_index + max(1, cell.colspan)):
                row_coverage[cell.row_index].add(col)

        cells_by_row: dict[int, list[Cell]] = defaultdict(list)
        for cell in cells:
            cells_by_row[cell.row_index].append(cell)

        max_row_index = max(row_coverage.keys(), default=-1)
        result: List[Cell] = []
        for row_idx in range(max_row_index + 1):
            row_cells = sorted(cells_by_row.get(row_idx, []), key=lambda c: c.col_index)
            for cell in row_cells:
                if cell.rowspan > 1 or cell.colspan > 1:
                    result.append(cell)
                    continue

                text = cell.text.strip()
                if not text:
                    result.append(cell)
                    continue

                # Only extend compact label-like cells.  This keeps the
                # heuristic conservative for ordinary data cells.
                if len(text) > 24:
                    result.append(cell)
                    continue

                if cell.col_index > 1 and any(ch.isdigit() for ch in text):
                    result.append(cell)
                    continue

                span_end = row_idx
                while span_end + 1 <= max_row_index:
                    next_row = span_end + 1
                    next_coverage = row_coverage.get(next_row, set())
                    if cell.col_index in next_coverage:
                        break
                    if not next_coverage:
                        break
                    span_end += 1

                if span_end > row_idx:
                    cell = Cell(
                        text=cell.text,
                        row_index=cell.row_index,
                        col_index=cell.col_index,
                        bbox=BBox(
                            cell.bbox.x0,
                            min(cell.bbox.y0, rows[row_idx]["y0"]),
                            cell.bbox.x1,
                            max(cell.bbox.y1, rows[span_end]["y1"]),
                        ),
                        rowspan=span_end - row_idx + 1,
                        colspan=cell.colspan,
                    )
                result.append(cell)

        result.sort(key=lambda cell: (cell.row_index, cell.col_index))
        return result

    def _classify_token_text(self, text: str) -> dict:
        """Classify a token as numeric or text and flag numeric separators."""
        import re

        token_text = text.strip()
        has_decimal = False
        has_group_separator = False

        if not token_text:
            is_numeric = False
        else:
            normalized = token_text
            if (
                len(normalized) >= 2
                and normalized[0] == "("
                and normalized[-1] == ")"
            ):
                normalized = normalized[1:-1]
            if normalized and normalized[0] in "$€£¥":
                normalized = normalized[1:]
            if normalized and normalized[-1] in "$€£¥":
                normalized = normalized[:-1]
            if normalized.endswith("%"):
                normalized = normalized[:-1]

            numeric_pattern = re.compile(
                r"^[+-]?(?:\d{1,3}(?:[,\s]\d{3})+|\d+)(?:\.\d+)?$"
            )
            is_numeric = bool(normalized) and bool(numeric_pattern.match(normalized))

        if is_numeric:
            has_decimal = "." in token_text
            has_group_separator = "," in token_text or " " in token_text

        return {
            "text": text,
            "is_numeric": is_numeric,
            "has_decimal": has_decimal,
            "has_group_separator": has_group_separator,
        }

    def _merge_text_tokens(self, tokens: list[dict]) -> list[dict]:
        """Merge near-touching fragments that belong to the same visual token."""
        if len(tokens) < 2:
            return tokens

        ordered = sorted(tokens, key=lambda token: (token["y_center"], token["x0"]))
        merged: list[dict] = []
        current = dict(ordered[0])

        for token in ordered[1:]:
            same_row = abs(token["y_center"] - current["y_center"]) <= 3.0
            x_gap = token["x0"] - current["x1"]
            close_horizontally = -1.0 <= x_gap <= 1.5

            if same_row and close_horizontally:
                merged_text = f'{current["text"]}{token["text"]}'
                merged_x0 = min(current["x0"], token["x0"])
                merged_y0 = min(current["y0"], token["y0"])
                merged_x1 = max(current["x1"], token["x1"])
                merged_y1 = max(current["y1"], token["y1"])
                current = self._classify_token_text(merged_text)
                current["x0"] = merged_x0
                current["y0"] = merged_y0
                current["x1"] = merged_x1
                current["y1"] = merged_y1
                current["y_center"] = (merged_y0 + merged_y1) / 2
                continue

            merged.append(current)
            current = dict(token)

        merged.append(current)
        return merged

    def _collect_text_rows(self, words: list[tuple]) -> list[dict]:
        """Group word tuples into visual rows ordered top-to-bottom."""
        if not words:
            return []

        normalized = []
        for word in words:
            x0, y0, x1, y1 = word[:4]
            text = word[4] if len(word) > 4 else ""
            token = self._classify_token_text(text)
            token.update({"x0": x0, "y0": y0, "x1": x1, "y1": y1})
            token["y_center"] = (y0 + y1) / 2
            normalized.append(token)

        normalized.sort(key=lambda token: (token["y_center"], token["x0"]))
        normalized = self._merge_text_tokens(normalized)
        normalized.sort(key=lambda token: (token["y_center"], token["x0"]))

        rows: list[dict] = []
        current_row: dict | None = None
        row_tolerance = 5.0

        for token in normalized:
            if current_row is None:
                current_row = {
                    "tokens": [token],
                    "x0": token["x0"],
                    "x1": token["x1"],
                    "y0": token["y0"],
                    "y1": token["y1"],
                    "_y_center": token["y_center"],
                }
                continue

            if abs(token["y_center"] - current_row["_y_center"]) <= row_tolerance:
                current_row["tokens"].append(token)
                current_row["x0"] = min(current_row["x0"], token["x0"])
                current_row["x1"] = max(current_row["x1"], token["x1"])
                current_row["y0"] = min(current_row["y0"], token["y0"])
                current_row["y1"] = max(current_row["y1"], token["y1"])
                current_row["_y_center"] = (
                    current_row["_y_center"] * (len(current_row["tokens"]) - 1)
                    + token["y_center"]
                ) / len(current_row["tokens"])
            else:
                current_row["tokens"].sort(key=lambda item: item["x0"])
                rows.append({k: v for k, v in current_row.items() if k != "_y_center"})
                current_row = {
                    "tokens": [token],
                    "x0": token["x0"],
                    "x1": token["x1"],
                    "y0": token["y0"],
                    "y1": token["y1"],
                    "_y_center": token["y_center"],
                }

        if current_row is not None:
            current_row["tokens"].sort(key=lambda item: item["x0"])
            rows.append({k: v for k, v in current_row.items() if k != "_y_center"})

        return rows

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

        rows = self._collect_text_rows(words)

        # Map each row token to its containing cell (by index, since Cell is not hashable).
        # Rows are already clustered visually, so each row contributes one line of text.
        cell_lines: dict[int, list[tuple[float, str]]] = defaultdict(list)
        for row_idx, row in enumerate(rows):
            row_tokens: dict[int, list[dict]] = defaultdict(list)
            for token in row["tokens"]:
                cx = (token["x0"] + token["x1"]) / 2
                cy = (token["y0"] + token["y1"]) / 2

                for idx, cell in enumerate(cells):
                    if (
                        cell.bbox.x0 <= cx <= cell.bbox.x1
                        and cell.bbox.y0 <= cy <= cell.bbox.y1
                    ):
                        row_tokens[idx].append(token)
                        break

            for idx, tokens in row_tokens.items():
                tokens.sort(key=lambda token: token["x0"])
                line_text = " ".join(
                    token["text"].strip() for token in tokens if token["text"].strip()
                )
                if line_text:
                    cell_lines[idx].append((float(row_idx), line_text))

        # Join lines without spaces (for wrapped numbers), preserving row order.
        for idx, line_list in cell_lines.items():
            line_list.sort(key=lambda item: item[0])
            cells[idx].text = "".join(text for _, text in line_list)

        return cells

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
