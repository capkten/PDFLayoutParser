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
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region


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
            # 1. 斑马底色无线表格处理逻辑 (Zebra Background Wireless Tables)
            zebra_tables = self.extract_zebra(
                page, table_bbox=table_bbox, confidence=confidence
            )
            if zebra_tables:
                return zebra_tables

            # 2. 通用无线表格处理逻辑 (General English Wireless Tables)
            general_tables = self.extract_general_wireless(
                page, table_bbox=table_bbox, confidence=confidence
            )
            if general_tables:
                return general_tables

            # Preserve the historical English fallback when specialized
            # English extraction finds no table.
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

        # 3. 中文/混合页面走新的 native-span 结构恢复逻辑。
        if table_bbox is not None:
            if page_language in {"zh", "mixed"}:
                row_count, col_count, cells = recover_cells_from_region(page, table_bbox)
                table_source = "wireless_span_recovery"
            else:
                row_count, col_count, cells = self.extract_cells_from_region(page, table_bbox)
                table_source = "text_alignment"
            if row_count >= 1 and col_count >= 1 and cells:
                conf_score = round(confidence, 4) if confidence is not None else 0.85
                return [
                    Table(
                        bbox=table_bbox,
                        rows=row_count,
                        cols=col_count,
                        cells=cells,
                        confidence=conf_score,
                        source=table_source,
                    )
                ]

        return []

    # =========================================================================
    # 1. 斑马纹底色无线表格提取 (Zebra Background Wireless Tables)
    # =========================================================================

    def extract_general_wireless(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
    ) -> List[Table]:
        """Extract general English wireless tables strictly using geometric distance:
        1. Rows are determined along the Y-axis.
        2. Columns are determined along the X-axis (overlapping intervals form a column, including underlines `————`).
        """
        if table_bbox is not None:
            try:
                page_words = page.get_text("words")
                expanded_x0, expanded_y0 = table_bbox.x0, table_bbox.y0
                expanded_x1, expanded_y1 = table_bbox.x1, table_bbox.y1
                for w in page_words:
                    if min(table_bbox.x1, w[2]) > max(table_bbox.x0, w[0]) and min(table_bbox.y1, w[3]) > max(table_bbox.y0, w[1]):
                        expanded_x0 = min(expanded_x0, w[0])
                        expanded_x1 = max(expanded_x1, w[2])
                        expanded_y0 = min(expanded_y0, w[1])
                        expanded_y1 = max(expanded_y1, w[3])
                table_bbox = BBox(round(expanded_x0, 1), round(expanded_y0, 1), round(expanded_x1, 1), round(expanded_y1, 1))
            except Exception:
                pass

        try:
            words = page.get_text("words")
        except Exception:
            return []

        if table_bbox is not None:
            t_words = [
                w for w in words
                if table_bbox.y0 - 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0
                and table_bbox.x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 5.0
            ]
        else:
            t_words = words

        if not t_words:
            return []

        # 1. 行的确定 (Y轴): 按 Y 坐标重叠聚类为行 (垂直重叠 <= 3.5pt)
        t_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
        rows_words: List[List[Tuple]] = []
        for w in t_words:
            mid_y = (w[1] + w[3]) / 2.0
            matched = False
            for rw in rows_words:
                rw_mid = sum((lw[1] + lw[3]) / 2.0 for lw in rw) / len(rw)
                if abs(mid_y - rw_mid) <= 3.5:
                    rw.append(w)
                    matched = True
                    break
            if not matched:
                rows_words.append([w])

        rows_words.sort(key=lambda rw: min(w[1] for w in rw))
        for rw in rows_words:
            rw.sort(key=lambda w: w[0])

        # 2. 提取物理横线/下划线 (————)
        drawings = page.get_drawings()
        h_lines: List[Tuple[float, float, float, float]] = []
        for d in drawings:
            for it in d.get("items", []):
                if it[0] == "l":
                    p1, p2 = it[1], it[2]
                    lx0, lx1 = min(p1.x, p2.x), max(p1.x, p2.x)
                    ly0, ly1 = min(p1.y, p2.y), max(p1.y, p2.y)
                    if abs(ly1 - ly0) <= 2.0 and (lx1 - lx0) >= 3.0:
                        if table_bbox is None or (table_bbox.x0 - 5 <= lx0 and lx1 <= table_bbox.x1 + 5 and table_bbox.y0 - 5 <= ly0 <= table_bbox.y1 + 5):
                            h_lines.append((lx0, ly0, lx1, ly1))
                elif it[0] == "re":
                    r = it[1]
                    if r.height <= 3.0 and r.width >= 3.0:
                        if table_bbox is None or (table_bbox.x0 - 5 <= r.x0 and r.x1 <= table_bbox.x1 + 5 and table_bbox.y0 - 5 <= r.y0 <= table_bbox.y1 + 5):
                            h_lines.append((r.x0, r.y0, r.x1, r.y1))

        # 3. 列的确定 (X轴，存在重叠的为一列，注意————也是一列)
        table_total_width = max(w[2] for w in t_words) - min(w[0] for w in t_words)
        col_segments: List[Tuple[float, float]] = []

        for rw in rows_words:
            phrases = []
            cur = [rw[0]]
            for w in rw[1:]:
                if w[0] - cur[-1][2] <= 8.0:
                    cur.append(w)
                else:
                    phrases.append(cur)
                    cur = [w]
            if cur:
                phrases.append(cur)

            if len(phrases) >= 2:
                for p in phrases:
                    col_segments.append((min(w[0] for w in p), max(w[2] for w in p)))
            elif len(phrases) == 1:
                p = phrases[0]
                pw = max(w[2] for w in p) - min(w[0] for w in p)
                if pw < table_total_width * 0.70:
                    col_segments.append((min(w[0] for w in p), max(w[2] for w in p)))

        # 将所有物理下划线 (————) 作为列片段加入
        for lx0, ly0, lx1, ly1 in h_lines:
            lw = lx1 - lx0
            if lw < table_total_width * 0.90:
                col_segments.append((lx0, lx1))

        if not col_segments:
            col_segments = [(min(w[0] for w in t_words), max(w[2] for w in t_words))]

        # 按 x0 排序并合并 X 轴重叠区间 (存在重叠的合并为一列)
        col_segments.sort(key=lambda s: s[0])
        merged_cols: List[List[float]] = []
        for s0, s1 in col_segments:
            if not merged_cols:
                merged_cols.append([s0, s1])
            else:
                prev = merged_cols[-1]
                if s0 <= prev[1] + 3.0:
                    prev[1] = max(prev[1], s1)
                else:
                    merged_cols.append([s0, s1])

        # Grid X bounds
        table_x0 = table_bbox.x0 if table_bbox else merged_cols[0][0]
        table_x1 = table_bbox.x1 if table_bbox else merged_cols[-1][1]

        grid_x = [table_x0]
        for i in range(len(merged_cols) - 1):
            mid_x = (merged_cols[i][1] + merged_cols[i + 1][0]) / 2.0
            grid_x.append(mid_x)
        grid_x.append(table_x1)

        # Grid Y bounds
        row_intervals = [(min(w[1] for w in rw), max(w[3] for w in rw)) for rw in rows_words]
        table_y0 = table_bbox.y0 if table_bbox else row_intervals[0][0]
        table_y1 = table_bbox.y1 if table_bbox else row_intervals[-1][1]

        grid_y = [table_y0]
        for r in range(len(row_intervals) - 1):
            mid_y = (row_intervals[r][1] + row_intervals[r + 1][0]) / 2.0
            grid_y.append(mid_y)
        grid_y.append(table_y1)

        num_rows = len(rows_words)
        num_cols = len(merged_cols)

        # 4. 构建 2D 单元格矩阵，各列独立分配，避免左上角和最后一列盲目合并
        grid_cells: Dict[Tuple[int, int], Cell] = {}

        for r_idx, rw in enumerate(rows_words):
            phrases = []
            cur = [rw[0]]
            for w in rw[1:]:
                if w[0] - cur[-1][2] <= 8.0:
                    cur.append(w)
                else:
                    phrases.append(cur)
                    cur = [w]
            if cur:
                phrases.append(cur)

            for p in phrases:
                px0 = min(w[0] for w in p)
                px1 = max(w[2] for w in p)
                txt = " ".join(w[4] for w in p).strip()

                sc = 0
                while sc < len(grid_x) - 2 and px0 > grid_x[sc + 1]:
                    sc += 1

                ec = sc
                while ec < len(grid_x) - 2 and px1 > grid_x[ec + 1]:
                    ec += 1

                colspan = max(1, ec - sc + 1)
                cell_box = BBox(grid_x[sc], grid_y[r_idx], grid_x[sc + colspan], grid_y[r_idx + 1])
                grid_cells[(r_idx, sc)] = Cell(
                    text=txt,
                    row_index=r_idx,
                    col_index=sc,
                    colspan=colspan,
                    rowspan=1,
                    bbox=cell_box,
                )

        # 补齐未填充的单元格，保证完整的 2D 网格结构
        cells: List[Cell] = []
        for r in range(num_rows):
            c = 0
            while c < num_cols:
                if (r, c) in grid_cells:
                    cell = grid_cells[(r, c)]
                    cells.append(cell)
                    c += cell.colspan
                else:
                    covered = any(
                        (r, oc) in grid_cells and oc <= c < oc + grid_cells[(r, oc)].colspan
                        for oc in range(c)
                    )
                    if not covered:
                        empty_box = BBox(grid_x[c], grid_y[r], grid_x[c + 1], grid_y[r + 1])
                        cells.append(Cell(
                            text="",
                            row_index=r,
                            col_index=c,
                            colspan=1,
                            rowspan=1,
                            bbox=empty_box,
                        ))
                    c += 1

        cells.sort(key=lambda cell: (cell.row_index, cell.col_index))
        tb = Table(
            bbox=table_bbox if table_bbox else BBox(table_x0, table_y0, table_x1, table_y1),
            rows=num_rows,
            cols=num_cols,
            cells=cells,
            confidence=round(confidence, 4) if confidence is not None else 0.90,
            source="english_general_wireless",
        )
        return [tb]

    def extract_zebra(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
    ) -> List[Table]:
        """Extract wireless tables using color-alternating row backgrounds."""
        # Rule 4: Strict geometric intersection expansion
        if table_bbox is not None:
            try:
                page_words = page.get_text("words")
                expanded_x0, expanded_y0 = table_bbox.x0, table_bbox.y0
                expanded_x1, expanded_y1 = table_bbox.x1, table_bbox.y1
                for w in page_words:
                    if min(table_bbox.x1, w[2]) > max(table_bbox.x0, w[0]) and min(table_bbox.y1, w[3]) > max(table_bbox.y0, w[1]):
                        expanded_x0 = min(expanded_x0, w[0])
                        expanded_x1 = max(expanded_x1, w[2])
                        expanded_y0 = min(expanded_y0, w[1])
                        expanded_y1 = max(expanded_y1, w[3])
                table_bbox = BBox(round(expanded_x0, 1), round(expanded_y0, 1), round(expanded_x1, 1), round(expanded_y1, 1))
            except Exception:
                pass

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
        else:
            sorted_hw = sorted(header_words, key=lambda w: w[1])
            tiers = []
            for w in sorted_hw:
                wy0, wy1 = w[1], w[3]
                matched_tier = None
                for t in tiers:
                    t_y0 = min(tw[1] for tw in t)
                    t_y1 = max(tw[3] for tw in t)
                    if not (wy1 <= t_y0 + 0.5 or wy0 >= t_y1 - 0.5):
                        matched_tier = t
                        break
                if matched_tier is not None:
                    matched_tier.append(w)
                else:
                    tiers.append([w])

        tiers.sort(key=lambda t: min(w[1] for w in t))
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
        # 1. Background column intervals (e.g. zebra tables with per-column background rects)
        if page is not None:
            try:
                drawings = page.get_drawings()
                bg_col_intervals = set()
                table_y_min = table_bbox.y0 if table_bbox else table_y0
                table_y_max = table_bbox.y1 if table_bbox else table_y0 + 200.0
                total_w = (table_bbox.x1 - table_bbox.x0) if table_bbox else 500.0
                for d in drawings:
                    fill = d.get("fill")
                    if fill and (self._is_color_match(fill, LIGHT_BLUE) or self._is_color_match(fill, WHITE)):
                        for it in d.get("items", []):
                            if it[0] == "re":
                                r = it[1]
                                if table_y_min - 5.0 <= (r.y0 + r.y1) / 2.0 <= table_y_max + 5.0 and r.height >= 4.0:
                                    if table_bbox is None or (table_bbox.x0 - 5.0 <= r.x0 and r.x1 <= table_bbox.x1 + 5.0):
                                        if r.width < total_w * 0.85:
                                            bg_col_intervals.add((round(r.x0, 1), round(r.x1, 1)))
                if len(bg_col_intervals) >= 2:
                    sorted_bg_cols = sorted(list(bg_col_intervals), key=lambda x: x[0])
                    merged_bg_cols: List[List[float]] = []
                    for c0, c1 in sorted_bg_cols:
                        if not merged_bg_cols:
                            merged_bg_cols.append([c0, c1])
                        else:
                            if c0 <= merged_bg_cols[-1][1] + 2.0:
                                merged_bg_cols[-1][1] = max(merged_bg_cols[-1][1], c1)
                            else:
                                merged_bg_cols.append([c0, c1])
                    if len(merged_bg_cols) >= 2:
                        return [(c[0], c[1]) for c in merged_bg_cols]
            except Exception:
                pass

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

        y_min_bound = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 50.0
        y_max_bound = table_bbox.y1 + 2.0 if table_bbox else table_y0 + 600.0

        for d in drawings:
            for it in d.get("items", []):
                if it[0] == "l":
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 8.0:
                        y = p1.y
                        if y_min_bound <= y <= y_max_bound:
                            h_lines.append((min(p1.x, p2.x), max(p1.x, p2.x), y))
                elif it[0] == "re":
                    r = it[1]
                    if r.height <= 2.0 and r.width >= 8.0:
                        y = r.y0
                        if y_min_bound <= y <= y_max_bound:
                            h_lines.append((r.x0, r.x1, y))

        if not h_lines:
            return []

        table_x0 = table_bbox.x0 if table_bbox else (min(w[0] for w in words) if words else 30.0)
        table_x1 = table_bbox.x1 if table_bbox else (max(w[2] for w in words) if words else 600.0)
        table_w = table_x1 - table_x0

        # 1. 表头部分下划线检测 (y <= table_y0 + 4.0)
        header_h_lines = [l for l in h_lines if l[2] <= table_y0 + 4.0]
        lines_by_y: Dict[float, List[Tuple[float, float]]] = defaultdict(list)
        for x0, x1, y in header_h_lines:
            matched_y = None
            for ey in lines_by_y:
                if abs(y - ey) <= 2.0:
                    matched_y = ey
                    break
            if matched_y is None:
                matched_y = y
            lines_by_y[matched_y].append((x0, x1))

        merged_by_y: Dict[float, List[List[float]]] = {}
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

        # 2. 如果表头部分没有下划线，表尾存在，则列的划分按照表尾进行划分，下划线为一列，没有下划线为一列
        if not merged_by_y:
            footer_h_lines = [l for l in h_lines if l[2] > table_y0 + 10.0]
            if footer_h_lines:
                sorted_footer = sorted(footer_h_lines, key=lambda l: l[0])
                merged_footer_segs: List[List[float]] = []
                for x0, x1, _ in sorted_footer:
                    if x1 - x0 >= table_w * 0.85:
                        continue
                    if not merged_footer_segs:
                        merged_footer_segs.append([x0, x1])
                    else:
                        if x0 <= merged_footer_segs[-1][1] + 3.0:
                            merged_footer_segs[-1][1] = max(merged_footer_segs[-1][1], x1)
                        else:
                            merged_footer_segs.append([x0, x1])

                if merged_footer_segs:
                    cols: List[Tuple[float, float]] = []
                    curr_x = table_x0
                    for seg_x0, seg_x1 in merged_footer_segs:
                        if seg_x0 > curr_x + 10.0:
                            cols.append((curr_x, seg_x0))
                        cols.append((seg_x0, seg_x1))
                        curr_x = seg_x1

                    if table_x1 > curr_x + 10.0:
                        cols.append((curr_x, table_x1))

                    if len(cols) >= 2:
                        return cols
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
            min_col1_x0 = all_col_spans[0][0]
            if max_stub_x1 < min_col1_x0:
                b0 = (max_stub_x1 + min_col1_x0) / 2.0
            else:
                b0 = max_stub_x1 + 1.5
            boundaries.append(b0)

        for k in range(len(all_col_spans) - 1):
            cur_end = all_col_spans[k][1]
            next_start = all_col_spans[k + 1][0]
            bk = (cur_end + next_start) / 2.0
            boundaries.append(bk)

        # 列线避让单词：检查是否有单列单词被列线切分，自动向外微调
        single_col_words = [
            w for w in t_words
            if (w[1] + w[3]) / 2.0 >= table_y0 - 2.0 or w[4].strip() in ('2023', '2022', '$', '%', '*', '-')
        ]
        adjusted_boundaries = list(boundaries)
        for k in range(len(adjusted_boundaries)):
            b = adjusted_boundaries[k]
            for w in single_col_words:
                if w[0] < b < w[2]:
                    if (w[0] + w[2]) / 2.0 < b:
                        adjusted_boundaries[k] = max(adjusted_boundaries[k], w[2] + 1.0)
                    else:
                        adjusted_boundaries[k] = min(adjusted_boundaries[k], w[0] - 1.0)
        boundaries = adjusted_boundaries

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

        total_rows = num_h_rows + len(data_rows)

        # Unify row vertical boundaries into continuous shared dividing lines (0 double lines)
        if all_cells and total_rows > 0:
            h_lines = []
            if page:
                try:
                    drawings = page.get_drawings()
                    for d in drawings:
                        for it in d.get("items", []):
                            if it[0] in ("l", "re"):
                                y = it[1].y if it[0] == "l" else (it[1].y0 + it[1].y1) / 2.0
                                w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                                h = 0.0 if it[0] == "l" else it[1].height
                                if h <= 2.5 and w >= 15.0:
                                    h_lines.append(round(y, 2))
                except Exception:
                    pass
            unique_h_lines = sorted(list(set(h_lines)))

            raw_row_intervals = []
            for r in range(total_rows):
                r_single_cells = [c for c in all_cells if c.row_index == r and c.rowspan == 1]
                r_all_cells = [c for c in all_cells if c.row_index == r]
                if r_single_cells:
                    raw_row_intervals.append((min(c.bbox.y0 for c in r_single_cells), max(c.bbox.y1 for c in r_single_cells)))
                elif r_all_cells:
                    raw_row_intervals.append((min(c.bbox.y0 for c in r_all_cells), max(c.bbox.y1 for c in r_all_cells)))
                else:
                    raw_row_intervals.append((0.0, 0.0))

            top_y0 = table_bbox.y0 if table_bbox is not None else raw_row_intervals[0][0]
            bot_y1 = table_bbox.y1 if table_bbox is not None else raw_row_intervals[-1][1]

            row_bounds = [top_y0]
            for i in range(len(raw_row_intervals) - 1):
                cur_y1 = raw_row_intervals[i][1]
                next_y0 = raw_row_intervals[i + 1][0]
                mid_y = (cur_y1 + next_y0) / 2.0

                # Snap to physical horizontal line (—————) if present near boundary
                snap_line = None
                for hl in unique_h_lines:
                    if min(cur_y1, next_y0) - 8.0 <= hl <= max(cur_y1, next_y0) + 8.0:
                        snap_line = hl
                        break
                if snap_line is not None:
                    row_bounds.append(snap_line)
                else:
                    row_bounds.append(mid_y)
            row_bounds.append(bot_y1)

            for c in all_cells:
                r_s = c.row_index
                r_e = c.row_index + max(1, c.rowspan) - 1
                if 0 <= r_s < len(row_bounds) - 1 and 0 <= r_e < len(row_bounds) - 1:
                    c.bbox = BBox(c.bbox.x0, row_bounds[r_s], c.bbox.x1, row_bounds[r_e + 1])

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

        # Cluster words in this row into line phrases
        sorted_words = sorted(words, key=lambda w: (round(w[1], 1), w[0]))
        line_clusters = []
        for w in sorted_words:
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
                    prev_w = cur_p[-1]
                    gap = w[0] - prev_w[2]
                    c_prev = next((ci for ci, c in enumerate(columns) if c[0] <= (prev_w[0] + prev_w[2]) / 2.0 < c[1]), -1)
                    c_curr = next((ci for ci, c in enumerate(columns) if c[0] <= (w[0] + w[2]) / 2.0 < c[1]), -1)
                    if c_prev == c_curr and gap <= 6.0:
                        cur_p.append(w)
                    elif c_prev != c_curr and gap <= 3.5:
                        cur_p.append(w)
                    else:
                        line_phrases.append(cur_p)
                        cur_p = [w]
            if cur_p:
                line_phrases.append(cur_p)

        if is_header:
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

            phrase_boxes = []
            for p in merged_phrases:
                p.sort(key=lambda w: (round(w[1], 1), w[0]))
                p_text = " ".join(w[4] for w in p)
                px0 = min(w[0] for w in p)
                py0 = min(w[1] for w in p)
                px1 = max(w[2] for w in p)
                py1 = max(w[3] for w in p)
                phrase_boxes.append({
                    "words": p,
                    "text": p_text,
                    "x0": px0, "y0": py0, "x1": px1, "y1": py1,
                    "mid_x": (px0 + px1) / 2.0
                })

            phrase_boxes.sort(key=lambda b: b["x0"])

            data_col_x0 = columns[1][0] if len(columns) > 1 else columns[0][0]
            assigned_spans = []
            for i, pb in enumerate(phrase_boxes):
                px0, px1 = pb["x0"], pb["x1"]
                data_phrases = [b for b in phrase_boxes if b["mid_x"] >= data_col_x0 - 10.0]
                if len(data_phrases) == 1 and pb == data_phrases[0] and len(columns) > 1:
                    # Single phrase over all data columns -> span all data columns!
                    start_col = 1
                    end_col = len(columns) - 1
                else:
                    overlaps = []
                    for ci, (cx0, cx1) in enumerate(columns):
                        ov = max(0.0, min(px1, cx1) - max(px0, cx0))
                        col_w = cx1 - cx0
                        overlaps.append((ci, ov, ov / col_w if col_w > 0 else 0))

                    matching_cols = []
                    for ci, ov, col_ratio in overlaps:
                        if ov >= 3.0 or col_ratio >= 0.15:
                            matching_cols.append(ci)

                    if not matching_cols:
                        best_ci = min(range(len(columns)), key=lambda ci: abs((columns[ci][0] + columns[ci][1]) / 2.0 - pb["mid_x"]))
                        matching_cols = [best_ci]

                    start_col = matching_cols[0]
                    end_col = matching_cols[-1]

                assigned_spans.append((pb, start_col, end_col))

            # Resolve overlapping collisions between consecutive phrases
            for i in range(len(assigned_spans) - 1):
                pb1, s1, e1 = assigned_spans[i]
                pb2, s2, e2 = assigned_spans[i + 1]
                s1 = max(0, min(s1, len(columns) - 1))
                e1 = max(s1, min(e1, len(columns) - 1))
                s2 = max(0, min(s2, len(columns) - 1))
                e2 = max(s2, min(e2, len(columns) - 1))
                if s2 <= e1:
                    ov_col = min(e1, len(columns) - 1)
                    c_mid = (columns[ov_col][0] + columns[ov_col][1]) / 2.0
                    dist1 = abs(pb1["mid_x"] - c_mid)
                    dist2 = abs(pb2["mid_x"] - c_mid)
                    if dist1 < dist2:
                        s2 = max(s2, min(len(columns) - 1, e1 + 1))
                        e2 = max(s2, min(len(columns) - 1, e2))
                        assigned_spans[i + 1] = (pb2, s2, e2)
                    else:
                        e1 = min(e1, max(0, s2 - 1))
                        s1 = min(s1, e1)
                        assigned_spans[i] = (pb1, s1, e1)

            cells = []
            covered_cols = set()
            for pb, sc, ec in assigned_spans:
                sc = max(0, min(sc, len(columns) - 1))
                ec = max(sc, min(ec, len(columns) - 1))
                colspan = max(1, ec - sc + 1)
                for ci in range(sc, sc + colspan):
                    covered_cols.add(ci)
                cells.append(Cell(
                    text=pb["text"],
                    row_index=row_idx,
                    col_index=sc,
                    colspan=colspan,
                    rowspan=1,
                    bbox=BBox(columns[sc][0], pb["y0"], columns[sc + colspan - 1][1], pb["y1"]),
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

        # Body rows: cluster into horizontal phrases to support 表体跨列
        sorted_body_words = sorted(words, key=lambda w: w[0])
        phrases = []
        for w in sorted_body_words:
            if not phrases:
                phrases.append([w])
            else:
                prev_w = phrases[-1][-1]
                gap = w[0] - prev_w[2]
                c_prev = next((ci for ci, c in enumerate(columns) if c[0] <= (prev_w[0] + prev_w[2]) / 2.0 < c[1]), -1)
                c_curr = next((ci for ci, c in enumerate(columns) if c[0] <= (w[0] + w[2]) / 2.0 < c[1]), -1)

                def _is_numeric(txt: str) -> bool:
                    t = txt.strip()
                    return bool(re.match(r'^\(?-?\$?\d+[\d,\.]*\)?%?$', t)) or t in ('$', '%', '*', '-', '—', '–')

                both_text = not _is_numeric(prev_w[4]) and not _is_numeric(w[4])

                if c_prev == c_curr and 0.0 <= gap <= 6.0:
                    phrases[-1].append(w)
                elif c_prev == 0 and c_curr == 0 and 0.0 <= gap <= 10.0:
                    phrases[-1].append(w)
                elif both_text and 0.0 <= gap <= 6.0:
                    phrases[-1].append(w)
                else:
                    phrases.append([w])

        phrase_spans = []
        for p in phrases:
            p_x0 = min(w[0] for w in p)
            p_x1 = max(w[2] for w in p)
            p_mid = (p_x0 + p_x1) / 2.0
            start_col = 0
            for ci, (cx0, cx1) in enumerate(columns):
                if cx0 <= p_x0 < cx1 or (ci == 0 and p_x0 < cx0):
                    start_col = ci
                    break
                elif cx0 <= p_mid < cx1:
                    start_col = ci
                    break
            end_col = start_col
            for ci in range(start_col, len(columns)):
                if p_x1 > columns[ci][0] + 5.0:
                    end_col = ci
            phrase_spans.append((p, start_col, end_col, p_x0, p_x1))

        cells = []
        covered_cols = set()
        for p, sc, ec, px0, px1 in phrase_spans:
            other_in_span = any(
                op is not p and not (op_ec < sc or op_sc > ec)
                for op, op_sc, op_ec, _, _ in phrase_spans
            )
            if other_in_span:
                colspan = 1
                ec = sc
            else:
                colspan = max(1, ec - sc + 1)

            p_words = list(p)
            p_words.sort(key=lambda w: w[0])
            dollar_words = [w for w in p_words if w[4] == '$']
            non_dollar_words = [w for w in p_words if w[4] != '$']
            if dollar_words and non_dollar_words:
                ordered_w = dollar_words + non_dollar_words
            else:
                ordered_w = p_words

            cell_text = " ".join(w[4] for w in ordered_w)
            cell_text = re.sub(r'(\d+,\d+)\s+(\d+)', r'\1\2', cell_text)
            cell_text = re.sub(r'(\(\d+,\d+)\s+(\d+)', r'\1\2', cell_text)
            cell_text = re.sub(r'\$\s+', '$', cell_text)
            cell_text = re.sub(r'\s+\)', ')', cell_text)
            cell_text = re.sub(r'\(\s+', '(', cell_text)
            cell_text = re.sub(r'\s+%', '%', cell_text)

            py0 = min(w[1] for w in p)
            py1 = max(w[3] for w in p)
            for ci in range(sc, sc + colspan):
                covered_cols.add(ci)

            cells.append(Cell(
                text=cell_text,
                row_index=row_idx,
                col_index=sc,
                colspan=colspan,
                rowspan=1,
                bbox=BBox(columns[sc][0], row_y0, columns[sc + colspan - 1][1], row_y1),
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
