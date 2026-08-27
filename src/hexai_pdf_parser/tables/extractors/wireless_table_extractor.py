"""Unified Wireless Table Extractor (Zebra background rows, 3-line header guides & text projection)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import fitz

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.base_table_extractor import BaseTableExtractor
from hexai_pdf_parser.extractors.language_detector import detect_page_language


# Color constants for English zebra row backgrounds
LIGHT_BLUE = (0.8, 0.933, 1.0)
WHITE = (1.0, 1.0, 1.0)


@dataclass
class _RowData:
    """Internal representation of a table row in zebra background tables."""
    words: List[Tuple[float, float, float, float, str]]
    y0: float
    y1: float
    color: Optional[str]
    is_header: bool = False


class WirelessTableExtractor(BaseTableExtractor):
    """Extracts wireless tables: zebra colored background bands, 3-line tables, and borderless text-alignment."""

    def __init__(
        self,
        line_tolerance: float = 2.0,
        color_tolerance: float = 0.05,
        row_merge_tolerance: float = 2.0,
    ):
        self.line_tolerance = line_tolerance
        self.color_tolerance = color_tolerance
        self.row_merge_tolerance = row_merge_tolerance

    def extract(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
        page_language: Optional[str] = None,
    ) -> List[Table]:
        """Extract wireless tables from candidate region or page."""
        if page_language is None:
            page_language = detect_page_language(page)

        if page_language == "en":
            zebra_tables = self.extract_zebra(
                page, table_bbox=table_bbox, confidence=confidence
            )
            if zebra_tables:
                return zebra_tables

        # 2. 文本对齐与表头引导无线表格提取 (如 850 页 Exhibit 表、A股三线表等)
        if table_bbox is not None:
            row_count, col_count, cells = self.extract_cells_from_region(page, table_bbox)
            if row_count >= 1 and col_count >= 1 and cells:
                conf_score = round(confidence, 4) if confidence is not None else 0.85
                return [
                    Table(
                        bbox=table_bbox,
                        rows=row_count,
                        cols=col_count,
                        cells=cells,
                        confidence=conf_score,
                        source="text_alignment",
                    )
                ]

        return []

    # =========================================================================
    # 斑马纹底色无线表格提取 (Zebra Background Wireless Tables)
    # =========================================================================

    def extract_zebra(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
    ) -> List[Table]:
        """Extract wireless tables using color-alternating row backgrounds."""
        row_backgrounds = self._detect_row_backgrounds(page)
        if not row_backgrounds:
            return []

        if table_bbox is not None:
            filtered_bgs = [
                bg for bg in row_backgrounds
                if not (bg[1] <= table_bbox.y0 + 2.0 or bg[0] >= table_bbox.y1 - 2.0)
                and not (bg[1] > table_bbox.y1 + 15.0 and bg[2] == "white")
            ]
            if filtered_bgs:
                row_backgrounds = filtered_bgs

        colored_bgs = [bg for bg in row_backgrounds if bg[2] != "white"]
        if colored_bgs:
            first_colored_y = min(bg[0] for bg in colored_bgs)
            last_colored_y = max(bg[1] for bg in colored_bgs)
            max_allowed_bottom = table_bbox.y1 + 5.0 if table_bbox else last_colored_y + 15.0
            data_bgs = [
                bg for bg in row_backgrounds
                if bg[0] >= first_colored_y - 2.0 and bg[0] < max(last_colored_y + 1.0, max_allowed_bottom - 2.0) and bg[1] <= max_allowed_bottom
            ]
            if data_bgs:
                try:
                    words = page.get_text("words")
                    filled_bgs = []
                    for i, bg in enumerate(data_bgs):
                        if i > 0:
                            prev_y1 = filled_bgs[-1][1]
                            cur_y0 = bg[0]
                            gap = cur_y0 - prev_y1
                            if gap >= 6.0:
                                gap_words = [w for w in words if prev_y1 - 2.0 <= (w[1] + w[3]) / 2.0 <= cur_y0 + 2.0]
                                if gap_words:
                                    filled_bgs.append((prev_y1, cur_y0, "white"))
                        filled_bgs.append(bg)
                    data_bgs = filled_bgs
                except Exception:
                    pass
                row_backgrounds = data_bgs

        if not row_backgrounds:
            return []

        if table_bbox is not None:
            tables_bg = [row_backgrounds]
        else:
            tables_bg = self._group_into_tables(row_backgrounds)

        tables: List[Table] = []
        for bg_group in tables_bg:
            t = self._process_zebra_group(page, bg_group, table_bbox, confidence)
            if t is not None:
                tables.append(t)

        return tables

    def _process_zebra_group(
        self,
        page: fitz.Page,
        bg_group: List[Tuple[float, float, str]],
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
    ) -> Optional[Table]:
        table_y0 = min(bg[0] for bg in bg_group)
        table_y1 = max(bg[1] for bg in bg_group)
        if table_bbox:
            table_y1 = max(table_y1, table_bbox.y1)

        try:
            words = page.get_text("words")
        except Exception:
            return None

        header_rows = self._detect_header_rows(words, table_y0, page, table_bbox=table_bbox)

        data_words = [
            w for w in words
            if table_y0 - 2.0 <= (w[1] + w[3]) / 2.0 <= table_y1 + 2.0
        ]
        if table_bbox:
            data_words = [
                w for w in data_words
                if table_bbox.x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 5.0
            ]

        data_rows = self._assign_words_to_zebra_rows(data_words, bg_group)
        data_rows = self._handle_dollar_signs(data_rows)

        all_words_for_cols = []
        for hr in header_rows:
            all_words_for_cols.extend(hr.words)
        for dr in data_rows:
            all_words_for_cols.extend(dr.words)

        columns = self._detect_columns(all_words_for_cols, data_rows, page, table_y0=table_y0, table_bbox=table_bbox)
        if len(columns) < 2:
            return None

        return self._build_zebra_table(
            header_rows=header_rows,
            data_rows=data_rows,
            columns=columns,
            confidence=confidence,
            table_bbox=table_bbox,
            page=page,
        )

    def _is_color_match(self, color1: Any, color2: Tuple) -> bool:
        if not isinstance(color1, (tuple, list)) or len(color1) != len(color2):
            return False
        return all(abs(c1 - c2) <= self.color_tolerance for c1, c2 in zip(color1, color2))

    def _detect_row_backgrounds(self, page: fitz.Page) -> List[Tuple[float, float, str]]:
        try:
            drawings = page.get_drawings()
        except Exception:
            return []

        blue_rects: List[List[Any]] = []
        white_rects: List[List[Any]] = []
        for d in drawings:
            fill = d.get("fill")
            rect = d.get("rect")
            if fill is None or rect is None:
                continue

            if isinstance(fill, (tuple, list)):
                key = tuple(round(c, 3) for c in fill)
            else:
                key = round(fill, 3)

            if self._is_color_match(key, LIGHT_BLUE):
                blue_rects.append([rect.y0, rect.y1, "blue"])
            elif self._is_color_match(key, WHITE):
                white_rects.append([rect.y0, rect.y1, "white"])

        if not blue_rects and not white_rects:
            return []

        # Merge vertically overlapping/adjacent blue rects into unified row intervals
        blue_rects.sort(key=lambda x: x[0])
        merged_blue: List[List[Any]] = []
        for r in blue_rects:
            if not merged_blue:
                merged_blue.append(r)
            else:
                prev = merged_blue[-1]
                if r[0] <= prev[1] + 2.0:
                    prev[1] = max(prev[1], r[1])
                else:
                    merged_blue.append(r)

        all_bgs = merged_blue + white_rects
        all_bgs.sort(key=lambda x: x[0])

        merged_all: List[List[Any]] = []
        for r in all_bgs:
            if not merged_all:
                merged_all.append(r)
            else:
                prev = merged_all[-1]
                if prev[2] == r[2] and r[0] <= prev[1] + 2.0:
                    prev[1] = max(prev[1], r[1])
                elif r[0] < prev[1] - 2.0:
                    continue
                else:
                    merged_all.append(r)

        return [(r[0], r[1], r[2]) for r in merged_all]

    def _group_into_tables(self, bgs: List[Tuple[float, float, str]]) -> List[List[Tuple[float, float, str]]]:
        if not bgs:
            return []

        tables = []
        current_table = [bgs[0]]

        for bg in bgs[1:]:
            prev_y1 = current_table[-1][1]
            gap = bg[0] - prev_y1

            if gap > 30.0:
                if len(current_table) >= 2:
                    tables.append(current_table)
                current_table = [bg]
            else:
                current_table.append(bg)

        if len(current_table) >= 2:
            tables.append(current_table)

        return tables

    def _detect_header_rows(
        self,
        words: List[Tuple],
        table_y0: float,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
    ) -> List[_RowData]:
        h_lines: List[float] = []
        if page is not None:
            try:
                drawings = page.get_drawings()
                y_min_bound = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 50.0
                for d in drawings:
                    for it in d.get("items", []):
                        if it[0] in ("l", "re"):
                            y = it[1].y if it[0] == "l" else it[1].y0
                            w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                            x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                            x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                            if table_bbox and (x1 < table_bbox.x0 - 5.0 or x0 > table_bbox.x1 + 5.0):
                                continue
                            if y_min_bound <= y <= table_y0 + 2.0 and w >= 20.0:
                                h_lines.append(round(y, 1))
            except Exception:
                pass

        unique_h_lines = sorted(list(set(h_lines)))
        merged_h_lines = []
        for hl in unique_h_lines:
            if not merged_h_lines:
                merged_h_lines.append(hl)
            elif hl - merged_h_lines[-1] > 3.0:
                merged_h_lines.append(hl)
            else:
                merged_h_lines[-1] = hl

        header_y_max = table_y0 - 1.0
        if merged_h_lines:
            header_y_max = max(merged_h_lines) - 0.2

        header_y_min = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 50.0
        header_words = [
            w for w in words
            if header_y_min <= (w[1] + w[3]) / 2.0 <= header_y_max
        ]
        if table_bbox:
            header_words = [
                w for w in header_words
                if table_bbox.x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 5.0
            ]

        if not header_words:
            return []

        min_word_y = min(w[1] for w in header_words)
        max_word_y = max(w[3] for w in header_words)
        internal_lines = [l for l in merged_h_lines if min_word_y + 2.0 < l < max_word_y - 2.0]

        if internal_lines:
            tiers: List[List[Tuple]] = []
            bounds = [header_y_min] + internal_lines + [header_y_max + 1.0]
            for b_idx in range(len(bounds) - 1):
                t_min = bounds[b_idx]
                t_max = bounds[b_idx + 1]
                t_words = [w for w in header_words if t_min <= (w[1] + w[3]) / 2.0 < t_max]
                if t_words:
                    tiers.append(t_words)

            header_rows = []
            for tier in tiers:
                sorted_tier = sorted(tier, key=lambda w: (round((w[1] + w[3]) / 2.0 / 3.5), w[0]))
                y0 = min(w[1] for w in sorted_tier)
                y1 = max(w[3] for w in sorted_tier)
                header_rows.append(_RowData(
                    words=sorted_tier,
                    y0=y0,
                    y1=y1,
                    color=None,
                    is_header=True,
                ))
            return header_rows

        # No internal dividing lines: all header words belong to a single header tier,
        # allowing multi-line words in each column to be merged into that column's header cell.
        sorted_words = sorted(header_words, key=lambda w: (round((w[1] + w[3]) / 2.0 / 3.5), w[0]))
        y0 = min(w[1] for w in sorted_words)
        y1 = max(w[3] for w in sorted_words)
        return [_RowData(
            words=sorted_words,
            y0=y0,
            y1=y1,
            color=None,
            is_header=True,
        )]

    def _handle_dollar_signs(self, rows: List[_RowData]) -> List[_RowData]:
        for row in rows:
            words = row.words
            i = 0
            while i < len(words):
                text = words[i][4].strip()
                if text == "$" and i + 1 < len(words):
                    next_text = words[i + 1][4].strip()
                    if any(ch.isdigit() for ch in next_text):
                        dw = words[i]
                        aw = words[i + 1]
                        merged_w = (
                            dw[0],
                            min(dw[1], aw[1]),
                            aw[2],
                            max(dw[3], aw[3]),
                            "$" + aw[4].strip(),
                        )
                        words[i] = merged_w
                        words.pop(i + 1)
                        continue
                i += 1
        return rows

    def _assign_words_to_zebra_rows(
        self,
        words: List[Tuple],
        row_backgrounds: List[Tuple[float, float, str]],
    ) -> List[_RowData]:
        row_words: Dict[int, List[Tuple]] = defaultdict(list)
        unassigned_words: List[Tuple] = []

        for w in words:
            w_yc = (w[1] + w[3]) / 2.0
            matched_idx = None
            for idx, (bg_y0, bg_y1, _) in enumerate(row_backgrounds):
                if bg_y0 - 2.0 <= w_yc <= bg_y1 + 2.0:
                    matched_idx = idx
                    break
            if matched_idx is not None:
                row_words[matched_idx].append(w)
            else:
                unassigned_words.append(w)

        data_rows = []
        for idx, (bg_y0, bg_y1, color) in enumerate(row_backgrounds):
            ws = row_words.get(idx, [])
            data_rows.append(_RowData(
                words=ws,
                y0=bg_y0,
                y1=bg_y1,
                color=color,
                is_header=False,
            ))

        if unassigned_words:
            unassigned_words.sort(key=lambda w: (w[1] + w[3]) / 2.0)
            clusters: List[List[Tuple]] = []
            curr: List[Tuple] = [unassigned_words[0]]
            for w in unassigned_words[1:]:
                prev_y1 = max(cw[3] for cw in curr)
                curr_y0 = w[1]
                if curr_y0 - prev_y1 <= 6.0 or (w[1] + w[3]) / 2.0 - (curr[-1][1] + curr[-1][3]) / 2.0 <= 10.0:
                    curr.append(w)
                else:
                    clusters.append(curr)
                    curr = [w]
            if curr:
                clusters.append(curr)

            for c in clusters:
                c_y0 = min(w[1] for w in c)
                c_y1 = max(w[3] for w in c)
                row_data = _RowData(
                    words=sorted(c, key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0])),
                    y0=c_y0,
                    y1=c_y1,
                    color=None,
                    is_header=False,
                )
                data_rows.append(row_data)

            data_rows.sort(key=lambda r: r.y0)

        return data_rows

    def _detect_columns(
        self,
        words: List[Tuple],
        data_rows: List[_RowData],
        page: fitz.Page,
        table_y0: float = 0.0,
        table_bbox: Optional[BBox] = None,
    ) -> List[Tuple[float, float]]:
        header_cols = self._detect_columns_from_header_underlines(page, table_y0, table_bbox=table_bbox, words=words)
        if header_cols and len(header_cols) >= 2:
            return header_cols

        # Universal column detection via horizontal overlap
        rows_by_y: Dict[float, List[Tuple]] = defaultdict(list)
        for w in words:
            mid_y = (w[1] + w[3]) / 2.0
            matched_y = None
            for ey in rows_by_y:
                if abs(mid_y - ey) <= 3.5:
                    matched_y = ey
                    break
            if matched_y is None:
                matched_y = mid_y
            rows_by_y[matched_y].append(w)

        line_segments: List[Tuple[float, float]] = []
        for ry, rwords in rows_by_y.items():
            rwords.sort(key=lambda w: w[0])
            cur: List[Tuple] = []
            for w in rwords:
                if not cur:
                    cur.append(w)
                else:
                    if w[0] - cur[-1][2] <= 12.0:
                        cur.append(w)
                    else:
                        line_segments.append((min(x[0] for x in cur), max(x[2] for x in cur)))
                        cur = [w]
            if cur:
                line_segments.append((min(x[0] for x in cur), max(x[2] for x in cur)))

        line_segments.sort(key=lambda s: s[0])
        col_spans: List[List[float]] = []
        for s in line_segments:
            if not col_spans:
                col_spans.append(list(s))
            else:
                merged = False
                for cs in col_spans:
                    if not (s[1] < cs[0] - 8.0 or s[0] > cs[1] + 8.0):
                        cs[0] = min(cs[0], s[0])
                        cs[1] = max(cs[1], s[1])
                        merged = True
                        break
                if not merged:
                    col_spans.append(list(s))

        col_spans.sort(key=lambda s: s[0])
        if len(col_spans) < 2:
            return []

        table_x0 = table_bbox.x0 if table_bbox else min(w[0] for w in words)
        table_x1 = table_bbox.x1 if table_bbox else max(w[2] for w in words)

        boundaries = []
        for k in range(len(col_spans) - 1):
            prev_end = col_spans[k][1]
            next_start = col_spans[k + 1][0]
            cur_col_words = [w for w in words if col_spans[k][0] - 5.0 <= (w[0] + w[2]) / 2.0 <= (prev_end + next_start) / 2.0]
            next_col_words = [w for w in words if (prev_end + next_start) / 2.0 <= (w[0] + w[2]) / 2.0 <= (col_spans[k + 1][1] + (col_spans[k + 2][0] if k + 2 < len(col_spans) else col_spans[k + 1][1])) / 2.0]
            max_cur_x1 = max([w[2] for w in cur_col_words] + [prev_end], default=prev_end)
            min_next_x0 = min([w[0] for w in next_col_words] + [next_start], default=next_start)
            if max_cur_x1 < min_next_x0:
                bk = (max_cur_x1 + min_next_x0) / 2.0
            else:
                bk = max_cur_x1 + 1.5
            boundaries.append(bk)

        columns = []
        curr_x = table_x0
        for b in boundaries:
            columns.append((curr_x, b))
            curr_x = b
        columns.append((curr_x, table_x1))
        return columns

    def _detect_columns_from_header_underlines(
        self,
        page: fitz.Page,
        table_y0: float,
        table_bbox: Optional[BBox] = None,
        words: Optional[List[Tuple]] = None,
    ) -> List[Tuple[float, float]]:
        drawings = page.get_drawings()
        h_lines = []

        y_min_bound = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 40.0
        y_max_bound = table_bbox.y1 + 2.0 if table_bbox else table_y0 + 600.0

        for d in drawings:
            for it in d.get("items", []):
                if it[0] == "l":
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 10.0:
                        y = p1.y
                        if y_min_bound <= y <= y_max_bound:
                            h_lines.append((min(p1.x, p2.x), max(p1.x, p2.x), y))
                elif it[0] == "re":
                    r = it[1]
                    if r.height <= 2.0 and r.width >= 10.0:
                        y = r.y0
                        if y_min_bound <= y <= y_max_bound:
                            h_lines.append((r.x0, r.x1, y))

        if not h_lines:
            return []

        lines_by_y: Dict[float, List[Tuple[float, float]]] = defaultdict(list)
        for x0, x1, y in h_lines:
            matched_y = None
            for ey in lines_by_y:
                if abs(y - ey) <= 2.0:
                    matched_y = ey
                    break
            if matched_y is None:
                matched_y = y
            lines_by_y[matched_y].append((x0, x1))

        if not lines_by_y:
            return []

        merged_by_y: Dict[float, List[List[float]]] = {}
        table_w = (table_bbox.x1 - table_bbox.x0) if table_bbox else 500.0
        for y, segs in lines_by_y.items():
            sorted_segs = sorted(segs, key=lambda s: s[0])
            merged = []
            for s in sorted_segs:
                if not merged:
                    merged.append(list(s))
                else:
                    if s[0] - merged[-1][1] <= 3.0:
                        merged[-1][1] = max(merged[-1][1], s[1])
                    else:
                        merged.append(list(s))
            col_segs = [s for s in merged if s[1] - s[0] < table_w * 0.85]
            if len(col_segs) >= 2:
                merged_by_y[y] = col_segs

        if not merged_by_y:
            return []

        best_y = max(merged_by_y.keys(), key=lambda y: (len(merged_by_y[y]), -y))
        best_segments = merged_by_y[best_y]

        table_x0 = 30.0
        table_x1 = 600.0
        if table_bbox:
            table_x0 = table_bbox.x0
            table_x1 = table_bbox.x1

        if words is None:
            try:
                words = page.get_text("words")
            except Exception:
                words = []

        t_words = [
            w for w in words
            if (table_bbox is None or (table_bbox.y0 - 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0 and table_bbox.x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 5.0))
            and not (w[3] < table_y0 + 20.0 and (w[2] - w[0] > 100.0 or w[0] > 300.0 and any(k in w[4] for k in ['Ended', 'March', 'As of'])))
        ]

        last_u_end = best_segments[-1][1]
        all_col_spans = [list(u) for u in best_segments]

        if table_x1 - last_u_end > 30.0:
            right_words = [w for w in t_words if (w[0] + w[2]) / 2.0 > last_u_end + 3.0]
            right_header_words = [w for w in right_words if w[1] <= table_y0 + 5.0 and w[4].strip() not in ("$", "—", "-")]
            right_numeric_words = [w for w in right_words if any(ch.isdigit() for ch in w[4]) or w[4].strip() in ("$", "—", "-")]

            if right_header_words:
                hw_x = [(w[0], w[2]) for w in right_header_words]
                hw_x.sort(key=lambda x: x[0])
                hw_clusters = []
                for hx0, hx1 in hw_x:
                    if not hw_clusters:
                        hw_clusters.append([(hx0, hx1)])
                    else:
                        if hx0 <= max(item[1] for item in hw_clusters[-1]) + 8.0:
                            hw_clusters[-1].append((hx0, hx1))
                        else:
                            hw_clusters.append([(hx0, hx1)])
                for cl in hw_clusters:
                    cl_x0 = min(item[0] for item in cl)
                    cl_x1 = max(item[1] for item in cl)
                    if cl_x0 > last_u_end + 3.0:
                        all_col_spans.append([cl_x0, cl_x1])
            elif right_numeric_words:
                cand_x = [(w[0], w[2]) for w in right_numeric_words]
                cand_x.sort(key=lambda x: x[0])
                c_clusters = []
                for cx0, cx1 in cand_x:
                    if not c_clusters:
                        c_clusters.append([(cx0, cx1)])
                    else:
                        if cx0 <= max(item[1] for item in c_clusters[-1]) + 5.0:
                            c_clusters[-1].append((cx0, cx1))
                        else:
                            c_clusters.append([(cx0, cx1)])
                for cl in c_clusters:
                    cl_x0 = min(item[0] for item in cl)
                    cl_x1 = max(item[1] for item in cl)
                    if cl_x0 > last_u_end + 3.0:
                        all_col_spans.append([cl_x0, cl_x1])

        all_col_spans.sort(key=lambda s: s[0])

        # Exclude multi-column spanning header titles when determining single-column text extents
        data_words = [w for w in t_words if (w[1] + w[3]) / 2.0 >= table_y0 - 15.0]

        first_col_x0 = all_col_spans[0][0]
        col_words: List[List[Tuple]] = [[] for _ in range(len(all_col_spans))]
        for w in data_words:
            mid_x = (w[0] + w[2]) / 2.0
            if mid_x < first_col_x0 - 15.0:
                continue
            best_ci = -1
            best_dist = 9999.0
            for ci, (sx0, sx1) in enumerate(all_col_spans):
                if sx0 - 4.0 <= mid_x <= sx1 + 4.0:
                    best_ci = ci
                    break
                smid = (sx0 + sx1) / 2.0
                dist = abs(mid_x - smid)
                if dist < best_dist:
                    best_dist = dist
                    best_ci = ci
            if best_ci >= 0:
                col_words[best_ci].append(w)

        boundaries = []
        if all_col_spans[0][0] - table_x0 > 25.0:
            stub_words = [w for w in t_words if w[2] < first_col_x0 - 15.0 and (w[1] + w[3]) / 2.0 >= table_y0 - 15.0]
            max_stub_x1 = max([w[2] for w in stub_words], default=table_x0)
            min_col1_x0 = min([w[0] for w in col_words[0]] + [first_col_x0], default=first_col_x0)
            if max_stub_x1 < min_col1_x0:
                b0 = (max_stub_x1 + min_col1_x0) / 2.0
            else:
                b0 = max_stub_x1 + 1.5
            boundaries.append(b0)

        for k in range(len(all_col_spans) - 1):
            prev_w = col_words[k]
            next_w = col_words[k + 1]
            max_cur = max([w[2] for w in prev_w] + [all_col_spans[k][1]], default=all_col_spans[k][1])
            min_next = min([w[0] for w in next_w] + [all_col_spans[k + 1][0]], default=all_col_spans[k + 1][0])
            if max_cur < min_next:
                bk = (max_cur + min_next) / 2.0
            else:
                bk = max_cur + 1.5
            boundaries.append(bk)

        last_w = col_words[-1]
        max_last = max([w[2] for w in last_w] + [all_col_spans[-1][1]], default=all_col_spans[-1][1])
        table_x1 = max(table_x1, max_last + 2.0)

        columns = []
        curr_x = table_x0
        for b in boundaries:
            columns.append((curr_x, b))
            curr_x = b
        columns.append((curr_x, table_x1))

        return columns

    def _normalize_zebra_headers(
        self,
        header_cells: List[Cell],
        columns: List[Tuple[float, float]],
        page: Optional[fitz.Page] = None,
    ) -> Tuple[List[Cell], int]:
        """Normalize multi-line column headers into structured header rows."""
        if not header_cells:
            return [], 0

        # Multi-tier header: preserve each distinct row_index (tier) as its own header row
        rows_dict = defaultdict(list)
        for c in header_cells:
            rows_dict[c.row_index].append(c)

        sorted_row_indices = sorted(rows_dict.keys())
        num_tiers = len(sorted_row_indices)

        if num_tiers <= 1:
            out = []
            for c in header_cells:
                out.append(Cell(
                    text=c.text,
                    row_index=0,
                    col_index=c.col_index,
                    colspan=c.colspan,
                    rowspan=1,
                    bbox=c.bbox,
                ))
            return out, 1

        drawings = page.get_drawings() if page else []
        h_lines = []
        for d in drawings:
            for it in d.get("items", []):
                if it[0] in ("l", "re"):
                    y = it[1].y if it[0] == "l" else it[1].y0
                    w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                    x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                    x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                    if w >= 10.0:
                        h_lines.append((round(y, 1), x0, x1))

        grid: List[List[Optional[Cell]]] = [[None for _ in range(len(columns))] for _ in range(num_tiers)]
        for out_r, orig_r in enumerate(sorted_row_indices):
            for c in rows_dict[orig_r]:
                if c.text.strip():
                    for ci in range(c.col_index, c.col_index + c.colspan):
                        grid[out_r][ci] = c

        merged_down = set()
        for t in range(num_tiers - 1):
            for ci, (cx0, cx1) in enumerate(columns):
                c_top = grid[t][ci]
                c_bot = grid[t + 1][ci]
                if c_top and c_bot and c_top.colspan == 1 and c_bot.colspan == 1 and c_top is not c_bot:
                    y_min = min(c_top.bbox.y1, c_bot.bbox.y0) - 2.0
                    y_max = max(c_top.bbox.y1, c_bot.bbox.y0) + 4.0
                    has_sep_line = any(
                        y_min <= ly <= y_max and not (lx1 < cx0 + 5.0 or lx0 > cx1 - 5.0)
                        for ly, lx0, lx1 in h_lines
                    )
                    if not has_sep_line:
                        merged_text = (c_top.text + " " + c_bot.text).strip()
                        merged_bbox = BBox(
                            min(c_top.bbox.x0, c_bot.bbox.x0),
                            min(c_top.bbox.y0, c_bot.bbox.y0),
                            max(c_top.bbox.x1, c_bot.bbox.x1),
                            max(c_top.bbox.y1, c_bot.bbox.y1),
                        )
                        c_top.text = merged_text
                        c_top.rowspan = 2
                        c_top.bbox = merged_bbox
                        c_bot.text = ""
                        merged_down.add((t + 1, ci))

        output_cells = []
        for out_r_idx, orig_r_idx in enumerate(sorted_row_indices):
            cur_row_cells = rows_dict[orig_r_idx]

            covered_cols = set()
            non_empty = []
            for c in cur_row_cells:
                if (out_r_idx, c.col_index) in merged_down:
                    continue
                if c.text.strip():
                    non_empty.append(c)
                    for ci in range(c.col_index, c.col_index + c.colspan):
                        covered_cols.add(ci)

            for c in non_empty:
                output_cells.append(Cell(
                    text=c.text,
                    row_index=out_r_idx,
                    col_index=c.col_index,
                    colspan=c.colspan,
                    rowspan=c.rowspan,
                    bbox=c.bbox,
                ))

            y0 = min(c.bbox.y0 for c in cur_row_cells)
            y1 = max(c.bbox.y1 for c in cur_row_cells)
            for ci in range(len(columns)):
                if ci not in covered_cols and (out_r_idx, ci) not in merged_down:
                    output_cells.append(Cell(
                        text="",
                        row_index=out_r_idx,
                        col_index=ci,
                        colspan=1,
                        bbox=BBox(columns[ci][0], y0, columns[ci][1], y1),
                    ))

        output_cells.sort(key=lambda c: (c.row_index, c.col_index))
        return output_cells, len(sorted_row_indices)

    def _build_zebra_table(
        self,
        header_rows: List[_RowData],
        data_rows: List[_RowData],
        columns: List[Tuple[float, float]],
        confidence: Optional[float],
        table_bbox: Optional[BBox],
        page: Optional[fitz.Page] = None,
    ) -> Optional[Table]:
        if not header_rows and not data_rows:
            return None
        if not columns:
            return None

        raw_header_cells: List[Cell] = []
        for r_idx, hr in enumerate(header_rows):
            rc = self._assign_words_to_zebra_columns(
                words=hr.words,
                columns=columns,
                row_idx=r_idx,
                row_y0=hr.y0,
                row_y1=hr.y1,
                page=page,
                is_header=True,
            )
            raw_header_cells.extend(rc)

        norm_h_cells, num_h_rows = self._normalize_zebra_headers(raw_header_cells, columns, page=page)

        body_cells: List[Cell] = []
        for r_idx, dr in enumerate(data_rows):
            rc = self._assign_words_to_zebra_columns(
                words=dr.words,
                columns=columns,
                row_idx=num_h_rows + r_idx,
                row_y0=dr.y0,
                row_y1=dr.y1,
                page=page,
                is_header=False,
            )
            body_cells.extend(rc)

        all_cells = norm_h_cells + body_cells
        if not all_cells:
            return None

        all_cells, col_count = self._prune_empty_columns(all_cells, len(columns))

        if table_bbox is not None:
            bbox = table_bbox
            source = "ml_detection"
        else:
            all_r = header_rows + data_rows
            bbox = BBox(
                min(col[0] for col in columns),
                min(r.y0 for r in all_r),
                max(col[1] for col in columns),
                max(r.y1 for r in all_r),
            )
            source = "english_color_based"

        total_rows = num_h_rows + len(data_rows)
        conf_score = round(confidence, 4) if confidence is not None else 0.85

        return Table(
            bbox=bbox,
            rows=total_rows,
            cols=col_count,
            cells=all_cells,
            confidence=conf_score,
            source=source,
        )

    def _assign_words_to_zebra_columns(
        self,
        words: List[Tuple[float, float, float, float, str]],
        columns: List[Tuple[float, float]],
        row_idx: int,
        row_y0: float,
        row_y1: float,
        page: Optional[fitz.Page] = None,
        is_header: bool = False,
    ) -> List[Cell]:
        if not words or not columns:
            return [
                Cell(
                    text="",
                    row_index=row_idx,
                    col_index=col_idx,
                    bbox=BBox(col_x0, row_y0, col_x1, row_y1),
                )
                for col_idx, (col_x0, col_x1) in enumerate(columns)
            ]

        if is_header:
            h_words = sorted(words, key=lambda w: (round(w[1], 1), w[0]))
            line_clusters = []
            for w in h_words:
                wy = (w[1] + w[3]) / 2.0
                matched = False
                for cl in line_clusters:
                    cl_y = sum((item[1] + item[3]) / 2.0 for item in cl) / len(cl)
                    if abs(wy - cl_y) <= 4.0:
                        cl.append(w)
                        matched = True
                        break
                if not matched:
                    line_clusters.append([w])

            line_phrases = []
            for cl in line_clusters:
                cl.sort(key=lambda w: w[0])
                cur_p = []
                for w in cl:
                    if not cur_p:
                        cur_p.append(w)
                    else:
                        if w[0] - cur_p[-1][2] <= 12.0:
                            cur_p.append(w)
                        else:
                            line_phrases.append(cur_p)
                            cur_p = [w]
                if cur_p:
                    line_phrases.append(cur_p)

            merged_phrases = []
            used = set()
            for i, p1 in enumerate(line_phrases):
                if i in used:
                    continue
                p1_x0 = min(w[0] for w in p1)
                p1_x1 = max(w[2] for w in p1)
                cur_words = list(p1)
                used.add(i)
                for j, p2 in enumerate(line_phrases):
                    if j in used:
                        continue
                    p2_x0 = min(w[0] for w in p2)
                    p2_x1 = max(w[2] for w in p2)
                    overlap = min(p1_x1, p2_x1) - max(p1_x0, p2_x0)
                    min_w = min(p1_x1 - p1_x0, p2_x1 - p2_x0)
                    if overlap > 0.4 * min_w or abs((p1_x0 + p1_x1) / 2.0 - (p2_x0 + p2_x1) / 2.0) <= 20.0:
                        cur_words.extend(p2)
                        used.add(j)
                merged_phrases.append(cur_words)

            cells = []
            covered_cols = set()
            for p in merged_phrases:
                p.sort(key=lambda w: (round(w[1], 1), w[0]))
                p_text = " ".join(w[4] for w in p)
                px0 = min(w[0] for w in p)
                py0 = min(w[1] for w in p)
                px1 = max(w[2] for w in p)
                py1 = max(w[3] for w in p)

                start_col = 0
                for ci, (cx0, cx1) in enumerate(columns):
                    if (px0 + min(px0 + 10.0, px1)) / 2.0 < cx1:
                        start_col = ci
                        break
                end_col = start_col
                for ci in range(start_col, len(columns)):
                    cx0, cx1 = columns[ci]
                    if px1 > cx0 + 5.0:
                        end_col = ci
                colspan = max(1, end_col - start_col + 1)
                for ci in range(start_col, start_col + colspan):
                    covered_cols.add(ci)
                cells.append(Cell(
                    text=p_text,
                    row_index=row_idx,
                    col_index=start_col,
                    colspan=colspan,
                    rowspan=1,
                    bbox=BBox(columns[start_col][0], py0, columns[start_col + colspan - 1][1], py1),
                ))

            for ci in range(len(columns)):
                if ci not in covered_cols:
                    cells.append(Cell(
                        text="",
                        row_index=row_idx,
                        col_index=ci,
                        colspan=1,
                        rowspan=1,
                        bbox=BBox(columns[ci][0], row_y0, columns[ci][1], row_y1),
                    ))
            cells.sort(key=lambda c: c.col_index)
            return cells

        col_words = [[] for _ in range(len(columns))]
        for w in words:
            mid_x = (w[0] + w[2]) / 2.0
            matched_ci = -1
            for ci, (cx0, cx1) in enumerate(columns):
                if cx0 <= mid_x < cx1:
                    matched_ci = ci
                    break
            if matched_ci >= 0:
                col_words[matched_ci].append(w)

        cells = []
        for ci, (cx0, cx1) in enumerate(columns):
            c_w = col_words[ci]
            if not c_w:
                cells.append(Cell(
                    text="",
                    row_index=row_idx,
                    col_index=ci,
                    colspan=1,
                    rowspan=1,
                    bbox=BBox(cx0, row_y0, cx1, row_y1),
                ))
                continue

            c_w.sort(key=lambda w: w[0])
            dollar_words = [w for w in c_w if w[4] == '$']
            non_dollar_words = [w for w in c_w if w[4] != '$']
            if dollar_words and non_dollar_words:
                ordered_w = dollar_words + non_dollar_words
            else:
                ordered_w = c_w

            cell_text = " ".join(w[4] for w in ordered_w)
            cell_text = re.sub(r'(\d+,\d+)\s+(\d+)', r'\1\2', cell_text)
            cell_text = re.sub(r'(\(\d+,\d+)\s+(\d+)', r'\1\2', cell_text)
            cell_text = re.sub(r'\$\s+', '$', cell_text)
            cell_text = re.sub(r'\s+\)', ')', cell_text)
            cell_text = re.sub(r'\(\s+', '(', cell_text)
            cell_text = re.sub(r'\s+%', '%', cell_text)

            cy0 = min(w[1] for w in c_w)
            cy1 = max(w[3] for w in c_w)
            cells.append(Cell(
                text=cell_text,
                row_index=row_idx,
                col_index=ci,
                colspan=1,
                rowspan=1,
                bbox=BBox(cx0, cy0, cx1, cy1),
            ))
        return cells

    def _find_column(self, x: float, columns: List[Tuple[float, float]]) -> int:
        for i, (x_start, x_end) in enumerate(columns):
            if x <= x_end:
                return i
        return len(columns) - 1

    # =========================================================================
    # 纯文本对齐与表头引导无线表格提取 (Borderless / Header-Guided Wireless Tables)
    # =========================================================================

    def extract_cells_from_region(
        self, page: fitz.Page, region_bbox: BBox
    ) -> Tuple[int, int, List[Cell]]:
        """Recover a table grid from text inside a trusted table region."""
        try:
            words = page.get_text(
                "words",
                clip=fitz.Rect(
                    region_bbox.x0, region_bbox.y0,
                    region_bbox.x1, region_bbox.y1,
                ),
            )
            rx0, ry0, rx1, ry1 = region_bbox.x0, region_bbox.y0, region_bbox.x1, region_bbox.y1
            words = [
                w for w in words
                if (w[0] + w[2]) / 2.0 >= rx0 - 2.0
                and (w[0] + w[2]) / 2.0 <= rx1 + 2.0
                and (w[1] + w[3]) / 2.0 >= ry0 - 2.0
                and (w[1] + w[3]) / 2.0 <= ry1 + 2.0
            ]
        except Exception:
            return 0, 0, []

        rows = self._collect_text_rows(words)
        if not rows:
            return 0, 0, []

        rows = self._merge_continuation_rows(rows, page=page)

        h_lines: List[Tuple[float, float, float]] = []
        try:
            for d in page.get_drawings():
                for it in d.get("items", []):
                    if it[0] == "l":
                        p1, p2 = it[1], it[2]
                        if abs(p1.y - p2.y) <= 1.5 and abs(p1.x - p2.x) >= 10.0:
                            y = p1.y
                            if region_bbox.y0 - 2.0 <= y <= region_bbox.y1 + 2.0:
                                h_lines.append((round(y, 1), min(p1.x, p2.x), max(p1.x, p2.x)))
                    elif it[0] == "re":
                        r = it[1]
                        if r.height <= 3.0 and r.width >= 10.0:
                            y = r.y0
                            if region_bbox.y0 - 2.0 <= y <= region_bbox.y1 + 2.0:
                                h_lines.append((round(y, 1), r.x0, r.x1))
        except Exception:
            pass

        header_cols = self._detect_columns_from_header_lines(page, rows, region_bbox)
        if header_cols and len(header_cols) >= 2:
            boundaries = [c[1] for c in header_cols[:-1]]
            num_cols = len(header_cols)
        else:
            guides = self._build_region_guides(rows, region_bbox)
            if len(guides) < 2:
                return 0, 0, []
            
            # Find whitespace gutters between column phrase boundaries
            all_phrases = []
            for r in rows:
                tokens = sorted(r["tokens"], key=lambda t: t["x0"])
                cur = [tokens[0]]
                for t in tokens[1:]:
                    if t["x0"] - cur[-1]["x1"] <= 12.0:
                        cur.append(t)
                    else:
                        all_phrases.append({"x0": cur[0]["x0"], "x1": cur[-1]["x1"]})
                        cur = [t]
                if cur:
                    all_phrases.append({"x0": cur[0]["x0"], "x1": cur[-1]["x1"]})

            boundaries = []
            for k in range(len(guides) - 1):
                mid = (guides[k] + guides[k + 1]) / 2.0
                k_phrases_x1 = [p["x1"] for p in all_phrases if p["x0"] < mid]
                k_max_x1 = max(k_phrases_x1) if k_phrases_x1 else guides[k]
                next_start = guides[k + 1]
                if k_max_x1 < next_start:
                    boundaries.append((k_max_x1 + next_start) / 2.0)
                else:
                    boundaries.append((guides[k] + guides[k + 1]) / 2.0)
            num_cols = len(boundaries) + 1

        def get_span(x0: float, x1: float) -> Tuple[int, int]:
            if x1 < x0:
                x0, x1 = x1, x0
            start_col = 0
            while start_col < len(boundaries) and x0 > boundaries[start_col]:
                start_col += 1
            end_col = 0
            while end_col < len(boundaries) and x1 >= boundaries[end_col]:
                end_col += 1
            start_col = min(start_col, num_cols - 1)
            end_col = min(max(end_col, start_col), num_cols - 1)
            return start_col, end_col

        table_y0 = min(r["y0"] for r in rows)
        sep_ys = sorted([
            y for y, lx0, lx1 in h_lines
            if table_y0 + 10.0 <= y <= table_y0 + 60.0
        ])
        tier_lines = [
            (y, lx0, lx1) for y, lx0, lx1 in h_lines
            if sep_ys and table_y0 + 5.0 <= y <= sep_ys[0] - 3.0
        ]

        cells: List[Cell] = []
        if sep_ys and not tier_lines:
            y_sep = sep_ys[0]
            header_rows = [r for r in rows if r["y1"] <= y_sep + 1.0]
            body_rows = [r for r in rows if r["y0"] > y_sep - 1.0]

            if header_rows:
                header_col_tokens: Dict[Tuple[int, int], List[Dict]] = defaultdict(list)
                for hr in header_rows:
                    for t in hr["tokens"]:
                        if not t.get("text", "").strip():
                            continue
                        sc, ec = get_span(t["x0"], t["x1"])
                        header_col_tokens[(sc, ec)].append(t)

                header_cells: List[Cell] = []
                for (sc, ec), tokens in sorted(header_col_tokens.items()):
                    tokens.sort(key=lambda t: (round(t["y0"] / 3.0), t["x0"]))
                    seen = set()
                    uniq = []
                    for t in tokens:
                        tid = (round(t["x0"], 1), round(t["y0"], 1), t["text"])
                        if tid not in seen:
                            seen.add(tid)
                            uniq.append(t)
                    text = " ".join(t["text"].strip() for t in uniq if t["text"].strip()).strip()
                    if text:
                        header_cells.append(
                            Cell(
                                text=text,
                                row_index=0,
                                col_index=sc,
                                colspan=ec - sc + 1,
                                bbox=BBox(
                                    min(t["x0"] for t in uniq),
                                    min(t["y0"] for t in uniq),
                                    max(t["x1"] for t in uniq),
                                    max(t["y1"] for t in uniq),
                                ),
                            )
                        )

                body_cells: List[Cell] = []
                for row_idx, r in enumerate(body_rows, start=1):
                    tokens = [t for t in r["tokens"] if t.get("text", "").strip()]
                    col_tokens: Dict[int, List[Dict]] = defaultdict(list)
                    for t in tokens:
                        txc = (t["x0"] + t["x1"]) / 2.0
                        sc, _ = get_span(txc, txc)
                        col_tokens[sc].append(t)

                    for ci, c_toks in sorted(col_tokens.items()):
                        c_toks.sort(key=lambda t: (round(t["y0"] / 3.0), t["x0"]))
                        text = " ".join(t["text"].strip() for t in c_toks if t["text"].strip()).strip()
                        if text:
                            body_cells.append(
                                Cell(
                                    text=text,
                                    row_index=row_idx,
                                    col_index=ci,
                                    colspan=1,
                                    bbox=BBox(
                                        min(t["x0"] for t in c_toks),
                                        min(t["y0"] for t in c_toks),
                                        max(t["x1"] for t in c_toks),
                                        max(t["y1"] for t in c_toks),
                                    ),
                                )
                            )
                cells = header_cells + body_cells

        if not cells:
            cells = self._build_text_grid_cells_from_boundaries(rows, boundaries, num_cols)

        cells = self._infer_sparse_rowspans(cells, rows, page=page)
        cells, num_cols = self._prune_empty_columns(cells, num_cols)

        # Multi-line header merging (e.g. Page 850 Exhibit Number)
        row_cells_map = defaultdict(list)
        for c in cells:
            row_cells_map[c.row_index].append(c)

        if 0 in row_cells_map and 1 in row_cells_map:
            r0 = row_cells_map[0]
            r1 = row_cells_map[1]
            if len(r0) == 1 and r0[0].col_index == 0:
                r1_c0 = next((c for c in r1 if c.col_index == 0), None)
                if r1_c0 is not None:
                    r1_c0.text = f"{r0[0].text} {r1_c0.text}".strip()
                    r1_c0.bbox = BBox(
                        min(r0[0].bbox.x0, r1_c0.bbox.x0),
                        min(r0[0].bbox.y0, r1_c0.bbox.y0),
                        max(r0[0].bbox.x1, r1_c0.bbox.x1),
                        max(r0[0].bbox.y1, r1_c0.bbox.y1),
                    )
                    adjusted_cells = []
                    for c in cells:
                        if c.row_index == 0:
                            continue
                        c.row_index -= 1
                        adjusted_cells.append(c)
                    cells = adjusted_cells

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

    def _collect_text_rows(self, words: List[Tuple]) -> List[Dict]:
        if not words:
            return []

        sorted_words = sorted(words, key=lambda w: (w[1] + w[3]) / 2.0)
        rows: List[Dict] = []

        for w in sorted_words:
            wx0, wy0, wx1, wy1, text = w[0], w[1], w[2], w[3], w[4]
            yc = (wy0 + wy1) / 2.0
            h = wy1 - wy0

            matched_row = None
            for r in rows:
                if abs(r["yc"] - yc) <= max(3.0, h * 0.45):
                    matched_row = r
                    break

            token = {
                "x0": wx0, "y0": wy0, "x1": wx1, "y1": wy1,
                "text": text, "is_numeric": bool(re.match(r"^[+-]?\d+(?:\.\d+)?%?$", text.strip())),
            }

            if matched_row is not None:
                matched_row["tokens"].append(token)
                matched_row["x0"] = min(matched_row["x0"], wx0)
                matched_row["y0"] = min(matched_row["y0"], wy0)
                matched_row["x1"] = max(matched_row["x1"], wx1)
                matched_row["y1"] = max(matched_row["y1"], wy1)
                matched_row["yc"] = (matched_row["y0"] + matched_row["y1"]) / 2.0
            else:
                rows.append({
                    "x0": wx0, "y0": wy0, "x1": wx1, "y1": wy1,
                    "yc": yc, "tokens": [token],
                })

        rows.sort(key=lambda r: r["y0"])
        return rows

    def _merge_continuation_rows(self, rows: List[Dict], page: Optional[fitz.Page] = None) -> List[Dict]:
        if len(rows) <= 1:
            return rows

        # Pass 1: Single token continuations
        merged: List[Dict] = [rows[0]]
        for r in rows[1:]:
            prev = merged[-1]
            if len(r["tokens"]) == 1 and r["x0"] < (prev["x0"] + prev["x1"]) / 2.0 and r["y0"] - prev["y1"] <= 8.0:
                prev["tokens"].extend(r["tokens"])
                prev["x0"] = min(prev["x0"], r["x0"])
                prev["y0"] = min(prev["y0"], r["y0"])
                prev["x1"] = max(prev["x1"], r["x1"])
                prev["y1"] = max(prev["y1"], r["y1"])
                prev["yc"] = (prev["y0"] + prev["y1"]) / 2.0
            else:
                merged.append(r)

        # Pass 2: Multi-line description rows for index-headed items (e.g. Exhibit 101, 104, 31.1)
        if len(merged) <= 1:
            return merged

        c0_starts = [min(t["x0"] for t in r["tokens"]) for r in merged]
        c0_min = min(c0_starts)
        col0_threshold = c0_min + 30.0

        final_merged: List[Dict] = [merged[0]]
        for r in merged[1:]:
            prev = final_merged[-1]
            prev_c0 = [t for t in prev["tokens"] if t["x0"] <= col0_threshold]
            r_c0 = [t for t in r["tokens"] if t["x0"] <= col0_threshold]

            prev_has_index = bool(prev_c0) and any(
                t["text"].replace(".", "").isdigit() for t in prev_c0
            )

            if prev_has_index and not r_c0 and r["y0"] - prev["y1"] <= 8.0:
                prev["tokens"].extend(r["tokens"])
                prev["x0"] = min(prev["x0"], r["x0"])
                prev["y0"] = min(prev["y0"], r["y0"])
                prev["x1"] = max(prev["x1"], r["x1"])
                prev["y1"] = max(prev["y1"], r["y1"])
                prev["yc"] = (prev["y0"] + prev["y1"]) / 2.0
            else:
                final_merged.append(r)

        return final_merged

    def _detect_columns_from_header_lines(
        self, page: fitz.Page, rows: List[Dict], region_bbox: BBox
    ) -> List[Tuple[float, float]]:
        try:
            drawings = page.get_drawings()
            lines = []
            for d in drawings:
                for it in d.get("items", []):
                    if it[0] == "l":
                        p1, p2 = it[1], it[2]
                        if abs(p1.y - p2.y) <= 1.5 and abs(p1.x - p2.x) >= 15.0:
                            if region_bbox.y0 <= p1.y <= region_bbox.y0 + 80.0:
                                lines.append((min(p1.x, p2.x), max(p1.x, p2.x)))
                    elif it[0] == "re":
                        r = it[1]
                        if r.height <= 3.0 and r.width >= 15.0:
                            if region_bbox.y0 <= r.y0 <= region_bbox.y0 + 80.0:
                                lines.append((r.x0, r.x1))
            if len(lines) >= 2:
                lines.sort(key=lambda s: s[0])
                cols = []
                for x0, x1 in lines:
                    if not cols or x0 > cols[-1][1] + 5.0:
                        cols.append((x0, x1))
                    else:
                        cols[-1] = (cols[-1][0], max(cols[-1][1], x1))
                if len(cols) >= 2:
                    return cols
        except Exception:
            pass
        return []

    def _build_region_guides(self, rows: List[Dict], region_bbox: BBox) -> List[float]:
        # Group words into phrases per row
        row_phrases = []
        for r in rows:
            tokens = sorted(r["tokens"], key=lambda t: t["x0"])
            cur_phrase = [tokens[0]]
            p_list = []
            for t in tokens[1:]:
                if t["x0"] - cur_phrase[-1]["x1"] <= 12.0:
                    cur_phrase.append(t)
                else:
                    p_list.append({
                        "x0": min(p["x0"] for p in cur_phrase),
                        "x1": max(p["x1"] for p in cur_phrase),
                        "tokens": cur_phrase,
                        "text": " ".join(p["text"] for p in cur_phrase),
                    })
                    cur_phrase = [t]
            if cur_phrase:
                p_list.append({
                    "x0": min(p["x0"] for p in cur_phrase),
                    "x1": max(p["x1"] for p in cur_phrase),
                    "tokens": cur_phrase,
                    "text": " ".join(p["text"] for p in cur_phrase),
                })
            row_phrases.append(p_list)

        all_starts = [p["x0"] for plist in row_phrases for p in plist]
        if not all_starts:
            return []

        all_starts.sort()
        clusters: List[List[float]] = []
        for x in all_starts:
            if not clusters or x - clusters[-1][-1] > 20.0:
                clusters.append([x])
            else:
                clusters[-1].append(x)

        sig_clusters = [c for c in clusters if len(c) >= max(2, len(rows) * 0.15)]
        if len(sig_clusters) < 2:
            sig_clusters = clusters

        col_starts = sorted([sum(c) / len(c) for c in sig_clusters])
        return col_starts

    def _build_text_grid_cells_from_boundaries(
        self, rows: List[Dict], boundaries: List[float], num_cols: int
    ) -> List[Cell]:
        cells: List[Cell] = []
        for row_idx, r in enumerate(rows):
            col_tokens: Dict[int, List[Dict]] = defaultdict(list)
            for t in r["tokens"]:
                txc = (t["x0"] + t["x1"]) / 2.0
                ci = 0
                while ci < len(boundaries) and txc > boundaries[ci]:
                    ci += 1
                ci = min(ci, num_cols - 1)
                col_tokens[ci].append(t)

            for ci in range(num_cols):
                tokens = col_tokens.get(ci, [])
                if not tokens:
                    continue
                # Sort vertically first (with 3.0pt line quantization), then horizontally
                tokens.sort(key=lambda t: (round(t["y0"] / 3.0), t["x0"]))
                text = " ".join(t["text"].strip() for t in tokens if t["text"].strip()).strip()
                if text:
                    cells.append(
                        Cell(
                            text=text,
                            row_index=row_idx,
                            col_index=ci,
                            colspan=1,
                            bbox=BBox(
                                min(t["x0"] for t in tokens),
                                min(t["y0"] for t in tokens),
                                max(t["x1"] for t in tokens),
                                max(t["y1"] for t in tokens),
                            ),
                        )
                    )
        return cells

    def _infer_sparse_rowspans(
        self, cells: List[Cell], rows: List[Dict], page: Optional[fitz.Page] = None
    ) -> List[Cell]:
        return cells

    def _prune_empty_columns(
        self, cells: List[Cell], num_cols: int
    ) -> Tuple[List[Cell], int]:
        if not cells or num_cols <= 1:
            return cells, num_cols

        col_has_text = [False] * num_cols
        for c in cells:
            if c.text.strip():
                for ci in range(c.col_index, min(num_cols, c.col_index + max(1, c.colspan))):
                    col_has_text[ci] = True

        if all(col_has_text):
            return cells, num_cols

        new_col_indices = []
        curr = 0
        for ht in col_has_text:
            if ht:
                new_col_indices.append(curr)
                curr += 1
            else:
                new_col_indices.append(-1)

        new_num_cols = curr
        if new_num_cols == 0:
            return cells, num_cols

        pruned_cells: List[Cell] = []
        for c in cells:
            old_start = c.col_index
            old_end = c.col_index + max(1, c.colspan) - 1
            new_start = None
            for ci in range(old_start, min(num_cols, old_end + 1)):
                if new_col_indices[ci] != -1:
                    new_start = new_col_indices[ci]
                    break
            new_end = None
            for ci in range(min(num_cols - 1, old_end), old_start - 1, -1):
                if new_col_indices[ci] != -1:
                    new_end = new_col_indices[ci]
                    break
            if new_start is not None and new_end is not None:
                c.col_index = new_start
                c.colspan = max(1, new_end - new_start + 1)
                pruned_cells.append(c)

        return pruned_cells, new_num_cols
