"""Wired Table Extractor (physical vector line grid topology)."""

from __future__ import annotations

import bisect
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import fitz

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.base_table_extractor import BaseTableExtractor


class WiredTableExtractor(BaseTableExtractor):
    """Extracts wired tables that have explicit physical horizontal and vertical grid lines."""

    def __init__(
        self,
        line_tolerance: float = 2.0,
        merge_group_tol: float = 0.3,
    ):
        self.line_tolerance = line_tolerance
        self.merge_group_tol = merge_group_tol

    def extract(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
    ) -> List[Table]:
        """Extract wired tables using physical vector line-projection and intersection topology."""
        h_lines, v_lines = self._extract_lines_from_drawings(page, clip_bbox=table_bbox)

        if len(h_lines) < 2 or not v_lines:
            return []

        h_lines = self._merge_h_lines(h_lines)
        v_lines = self._merge_v_lines(v_lines)

        if len(h_lines) < 2 or not v_lines:
            return []

        table_regions = self._find_table_regions(h_lines, v_lines)
        if not table_regions:
            return []

        tables: List[Table] = []
        for region_bbox, region_h_lines, region_v_lines in table_regions:
            cells = self._build_cells_for_region(
                region_bbox, region_h_lines, region_v_lines
            )
            if not cells:
                continue

            cells = self._assign_text_to_line_cells(cells, page)
            cells = self._merge_oversegmented_line_columns(cells)

            row_count = max((c.row_index for c in cells), default=-1) + 1
            col_count = max((c.col_index for c in cells), default=-1) + 1

            if row_count >= 1 and col_count >= 1 and cells:
                has_text = any(c.text.strip() for c in cells)
                table_height = region_bbox.y1 - region_bbox.y0
                if not has_text and (table_height < 6.0 or row_count * col_count <= 1):
                    continue

                conf_score = round(confidence, 4) if confidence is not None else 0.90
                tables.append(
                    Table(
                        bbox=region_bbox,
                        rows=row_count,
                        cols=col_count,
                        cells=cells,
                        confidence=conf_score,
                        source="line_projection",
                    )
                )

        return tables

    def _extract_lines_from_drawings(
        self, page: fitz.Page, clip_bbox: Optional[BBox] = None
    ) -> Tuple[List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]:
        h_lines = []
        v_lines = []

        try:
            drawings = page.get_drawings()
        except Exception:
            return [], []

        for d in drawings:
            items = d.get("items", [])
            for item in items:
                if item[0] == "l":
                    p1 = item[1]
                    p2 = item[2]
                    x1, y1 = float(p1.x), float(p1.y)
                    x2, y2 = float(p2.x), float(p2.y)

                    if clip_bbox:
                        if max(x1, x2) < clip_bbox.x0 - 2.0 or min(x1, x2) > clip_bbox.x1 + 2.0:
                            continue
                        if max(y1, y2) < clip_bbox.y0 - 2.0 or min(y1, y2) > clip_bbox.y1 + 2.0:
                            continue

                    if abs(y1 - y2) <= self.line_tolerance and abs(x1 - x2) >= 3.0:
                        h_lines.append((min(x1, x2), (y1 + y2) / 2.0, max(x1, x2), (y1 + y2) / 2.0))
                    elif abs(x1 - x2) <= self.line_tolerance and abs(y1 - y2) >= 3.0:
                        v_lines.append(((x1 + x2) / 2.0, min(y1, y2), (x1 + x2) / 2.0, max(y1, y2)))

                elif item[0] == "re":
                    rect = item[1]
                    x0, y0 = float(rect.x0), float(rect.y0)
                    x1, y1 = float(rect.x1), float(rect.y1)
                    w = x1 - x0
                    h = y1 - y0

                    if clip_bbox:
                        if x1 < clip_bbox.x0 - 2.0 or x0 > clip_bbox.x1 + 2.0:
                            continue
                        if y1 < clip_bbox.y0 - 2.0 or y0 > clip_bbox.y1 + 2.0:
                            continue

                    if h <= self.line_tolerance and w >= 3.0:
                        h_lines.append((x0, (y0 + y1) / 2.0, x1, (y0 + y1) / 2.0))
                    elif w <= self.line_tolerance and h >= 3.0:
                        v_lines.append(((x0 + x1) / 2.0, y0, (x0 + x1) / 2.0, y1))

        return h_lines, v_lines

    def _merge_h_lines(
        self, lines: List[Tuple[float, float, float, float]]
    ) -> List[Tuple[float, float, float, float]]:
        if not lines:
            return []

        sorted_lines = sorted(lines, key=lambda l: (round(l[1], 1), l[0]))
        groups: List[List[Tuple[float, float, float, float]]] = []

        for line in sorted_lines:
            y = line[1]
            matched = False
            for group in groups:
                if abs(group[0][1] - y) <= self.merge_group_tol:
                    group.append(line)
                    matched = True
                    break
            if not matched:
                groups.append([line])

        merged = []
        for group in groups:
            avg_y = sum(l[1] for l in group) / len(group)
            segs = sorted([(l[0], l[2]) for l in group], key=lambda s: s[0])
            cur_x0, cur_x1 = segs[0]

            for s_x0, s_x1 in segs[1:]:
                if s_x0 <= cur_x1 + 3.0:
                    cur_x1 = max(cur_x1, s_x1)
                else:
                    merged.append((cur_x0, avg_y, cur_x1, avg_y))
                    cur_x0, cur_x1 = s_x0, s_x1
            merged.append((cur_x0, avg_y, cur_x1, avg_y))

        return merged

    def _merge_v_lines(
        self, lines: List[Tuple[float, float, float, float]]
    ) -> List[Tuple[float, float, float, float]]:
        if not lines:
            return []

        sorted_lines = sorted(lines, key=lambda l: (round(l[0], 1), l[1]))
        groups: List[List[Tuple[float, float, float, float]]] = []

        for line in sorted_lines:
            x = line[0]
            matched = False
            for group in groups:
                if abs(group[0][0] - x) <= self.merge_group_tol:
                    group.append(line)
                    matched = True
                    break
            if not matched:
                groups.append([line])

        merged = []
        for group in groups:
            avg_x = sum(l[0] for l in group) / len(group)
            segs = sorted([(l[1], l[3]) for l in group], key=lambda s: s[0])
            cur_y0, cur_y1 = segs[0]

            for s_y0, s_y1 in segs[1:]:
                if s_y0 <= cur_y1 + 3.0:
                    cur_y1 = max(cur_y1, s_y1)
                else:
                    merged.append((avg_x, cur_y0, avg_x, cur_y1))
                    cur_y0, cur_y1 = s_y0, s_y1
            merged.append((avg_x, cur_y0, avg_x, cur_y1))

        return merged

    def _find_table_regions(
        self,
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> List[Tuple[BBox, List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]]:
        if len(h_lines) < 2 or not v_lines:
            return []

        # Ignore page rules, footer lines, and text underlines that do not
        # participate in the same connected line network as the table.
        h_lines = [
            line
            for line in h_lines
            if sum(self._lines_intersect(h_line=line, v_line=v_line) for v_line in v_lines) >= 1
        ]
        v_lines = [
            line
            for line in v_lines
            if sum(self._lines_intersect(h_line=h_line, v_line=line) for h_line in h_lines) >= 1
        ]
        h_lines = [
            line
            for line in h_lines
            if sum(self._lines_intersect(h_line=line, v_line=v_line) for v_line in v_lines) >= 1
        ]

        if len(h_lines) < 2 or not v_lines:
            return []

        h_to_v = {
            h_idx: [
                v_idx
                for v_idx, v_line in enumerate(v_lines)
                if self._lines_intersect(h_line=h_line, v_line=v_line)
            ]
            for h_idx, h_line in enumerate(h_lines)
        }
        v_to_h = {
            v_idx: [
                h_idx
                for h_idx, h_line in enumerate(h_lines)
                if self._lines_intersect(h_line=h_line, v_line=v_line)
            ]
            for v_idx, v_line in enumerate(v_lines)
        }

        components = []
        visited_h = set()
        visited_v = set()
        for start_h in range(len(h_lines)):
            if start_h in visited_h:
                continue

            component_h = set()
            component_v = set()
            pending = [("h", start_h)]
            while pending:
                line_type, line_idx = pending.pop()
                if line_type == "h":
                    if line_idx in visited_h:
                        continue
                    visited_h.add(line_idx)
                    component_h.add(line_idx)
                    pending.extend(("v", v_idx) for v_idx in h_to_v[line_idx])
                else:
                    if line_idx in visited_v:
                        continue
                    visited_v.add(line_idx)
                    component_v.add(line_idx)
                    pending.extend(("h", h_idx) for h_idx in v_to_h[line_idx])

            if len(component_h) < 2 or not component_v:
                continue
            components.append(
                (
                    [h_lines[idx] for idx in sorted(component_h)],
                    [v_lines[idx] for idx in sorted(component_v)],
                )
            )

        regions = []
        for component_h, component_v in components:
            all_x = [
                value
                for line in component_h
                for value in (line[0], line[2])
            ] + [line[0] for line in component_v]
            all_y = [line[1] for line in component_h] + [
                value
                for line in component_v
                for value in (line[1], line[3])
            ]
            bbox = BBox(min(all_x), min(all_y), max(all_x), max(all_y))
            regions.append((bbox, component_h, component_v))

        return sorted(regions, key=lambda region: (region[0].y0, region[0].x0))

    def _lines_intersect(
        self,
        *,
        h_line: Tuple[float, float, float, float],
        v_line: Tuple[float, float, float, float],
    ) -> bool:
        """Return whether a horizontal and vertical line touch within tolerance."""
        hx0, hy, hx1, _ = h_line
        vx, vy0, _, vy1 = v_line
        tolerance = self.line_tolerance
        return (
            hx0 - tolerance <= vx <= hx1 + tolerance
            and vy0 - tolerance <= hy <= vy1 + tolerance
        )

    def _build_cells_for_region(
        self,
        bbox: BBox,
        h_lines: List[Tuple[float, float, float, float]],
        v_lines: List[Tuple[float, float, float, float]],
    ) -> List[Cell]:
        h_ys = sorted(set(round(line[1], 1) for line in h_lines))
        v_xs = sorted(
            {
                round(bbox.x0, 1),
                round(bbox.x1, 1),
                *(round(line[0], 1) for line in v_lines),
            }
        )

        if len(h_ys) < 2 or len(v_xs) < 2:
            return []

        rows = len(h_ys) - 1
        cols = len(v_xs) - 1
        tol = self.line_tolerance
        effective_v_lines = list(v_lines)
        if not any(abs(line[0] - bbox.x0) <= tol for line in v_lines):
            effective_v_lines.append((bbox.x0, bbox.y0, bbox.x0, bbox.y1))
        if not any(abs(line[0] - bbox.x1) <= tol for line in v_lines):
            effective_v_lines.append((bbox.x1, bbox.y0, bbox.x1, bbox.y1))

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
            for lx, ly0, _, ly1 in effective_v_lines:
                if abs(lx - x) > tol:
                    continue
                overlap = min(ly1, y1 + tol) - max(ly0, y0 - tol)
                if overlap >= max(span - tol, span * 0.9):
                    return True
            return False

        h_edges = [
            [
                has_h_segment(h_ys[row], v_xs[col], v_xs[col + 1])
                for col in range(cols)
            ]
            for row in range(rows + 1)
        ]
        v_edges = [
            [
                has_v_segment(v_xs[col], h_ys[row], h_ys[row + 1])
                for col in range(cols + 1)
            ]
            for row in range(rows)
        ]

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

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        inside_set = set(inside_cells)
        for row, col in inside_cells:
            if (
                col + 1 < cols
                and (row, col + 1) in inside_set
                and not v_edges[row][col + 1]
            ):
                union(cell_id(row, col), cell_id(row, col + 1))
            if (
                row + 1 < rows
                and (row + 1, col) in inside_set
                and not h_edges[row + 1][col]
            ):
                union(cell_id(row, col), cell_id(row + 1, col))

        components: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
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
                for row, col in sorted(coords):
                    cells.append(
                        Cell(
                            text="",
                            row_index=row,
                            col_index=col,
                            bbox=BBox(
                                v_xs[col],
                                h_ys[row],
                                v_xs[col + 1],
                                h_ys[row + 1],
                            ),
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

    def _assign_text_to_line_cells(self, cells: List[Cell], page: fitz.Page) -> List[Cell]:
        try:
            words = page.get_text("words")
        except Exception:
            return cells

        cell_words: Dict[int, List[Tuple]] = defaultdict(list)
        for w in words:
            wxc = (w[0] + w[2]) / 2.0
            wyc = (w[1] + w[3]) / 2.0

            matched_idx = None
            for idx, c in enumerate(cells):
                if c.bbox.x0 - 2.0 <= wxc <= c.bbox.x1 + 2.0 and c.bbox.y0 - 2.0 <= wyc <= c.bbox.y1 + 2.0:
                    matched_idx = idx
                    break
            if matched_idx is not None:
                cell_words[matched_idx].append(w)

        for idx, ws in cell_words.items():
            ws.sort(key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0]))
            cells[idx].text = " ".join(w[4].strip() for w in ws if w[4].strip()).strip()

        return cells

    def _merge_oversegmented_line_columns(self, cells: List[Cell]) -> List[Cell]:
        if not cells:
            return cells

        cols: Dict[int, List[Cell]] = defaultdict(list)
        for c in cells:
            cols[c.col_index].append(c)

        col_has_text = {
            ci: any(c.text.strip() for c in c_list) for ci, c_list in cols.items()
        }

        if all(col_has_text.values()):
            return cells

        new_ci = 0
        ci_map = {}
        for ci in sorted(cols.keys()):
            if col_has_text[ci]:
                ci_map[ci] = new_ci
                new_ci += 1
            else:
                ci_map[ci] = -1

        pruned = []
        for c in cells:
            if ci_map.get(c.col_index, -1) != -1:
                c.col_index = ci_map[c.col_index]
                pruned.append(c)

        return pruned
