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
        xs = sorted(
            {
                round(bbox.x0, 1),
                round(bbox.x1, 1),
                *(round(line[0], 1) for line in v_lines),
            }
        )
        ys = sorted(list(set(round(l[1], 1) for l in h_lines)))

        if len(xs) < 2 or len(ys) < 2:
            return []

        cells: List[Cell] = []
        for r_idx in range(len(ys) - 1):
            for c_idx in range(len(xs) - 1):
                cx0, cy0 = xs[c_idx], ys[r_idx]
                cx1, cy1 = xs[c_idx + 1], ys[r_idx + 1]
                cells.append(
                    Cell(
                        text="",
                        row_index=r_idx,
                        col_index=c_idx,
                        bbox=BBox(cx0, cy0, cx1, cy1),
                    )
                )
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
