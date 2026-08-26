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
    ) -> List[Table]:
        """Extract wireless tables from candidate region or page."""
        # 1. 优先尝试斑马纹底色无线表格提取 (如美股 10-K/10-Q 847, 846, 838 等)
        zebra_tables = self.extract_zebra(page, table_bbox=table_bbox, confidence=confidence)
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
                if not (bg[1] < table_bbox.y0 - 5.0 or bg[0] > table_bbox.y1 - 2.0)
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

        row_rects: List[Tuple[float, float, str]] = []
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
                row_rects.append((rect.y0, rect.y1, "blue"))
            elif self._is_color_match(key, WHITE):
                row_rects.append((rect.y0, rect.y1, "white"))

        if not row_rects:
            return []

        row_rects.sort(key=lambda x: x[0])
        unique_rows: List[Tuple[float, float, str]] = []
        seen_y_ranges: set = set()

        for y0, y1, color in row_rects:
            y_key = (round(y0, 1), round(y1, 1))
            if y_key not in seen_y_ranges:
                seen_y_ranges.add(y_key)
                unique_rows.append((y0, y1, color))

        return unique_rows

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
        header_y_max = table_y0 - 1.0
        if page is not None:
            try:
                drawings = page.get_drawings()
                h_lines = []
                y_min_bound = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 40.0
                for d in drawings:
                    for it in d.get("items", []):
                        if it[0] in ("l", "re"):
                            y = it[1].y if it[0] == "l" else it[1].y0
                            w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                            if y_min_bound <= y <= table_y0 + 2.0 and w >= 10.0:
                                h_lines.append(y)
                if h_lines:
                    header_y_max = max(h_lines) + 1.0
            except Exception:
                pass

        header_y_min = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 45.0
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

        header_words.sort(key=lambda w: (w[1] + w[3]) / 2.0)
        row_clusters: List[List[Tuple]] = []
        current_cluster: List[Tuple] = [header_words[0]]

        for w in header_words[1:]:
            prev_yc = (current_cluster[-1][1] + current_cluster[-1][3]) / 2.0
            cur_yc = (w[1] + w[3]) / 2.0
            if abs(cur_yc - prev_yc) <= 3.5:
                current_cluster.append(w)
            else:
                row_clusters.append(current_cluster)
                current_cluster = [w]

        if current_cluster:
            row_clusters.append(current_cluster)

        header_rows = []
        for cluster in row_clusters:
            sorted_cluster = sorted(cluster, key=lambda w: w[0])
            y0 = min(w[1] for w in sorted_cluster)
            y1 = max(w[3] for w in sorted_cluster)
            header_rows.append(_RowData(
                words=sorted_cluster,
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

        for w in words:
            w_yc = (w[1] + w[3]) / 2.0
            matched_idx = None
            for idx, (bg_y0, bg_y1, _) in enumerate(row_backgrounds):
                if bg_y0 - 2.0 <= w_yc <= bg_y1 + 2.0:
                    matched_idx = idx
                    break
            if matched_idx is not None:
                row_words[matched_idx].append(w)

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

        return data_rows

    def _detect_columns(
        self,
        words: List[Tuple],
        data_rows: List[_RowData],
        page: fitz.Page,
        table_y0: float = 0.0,
        table_bbox: Optional[BBox] = None,
    ) -> List[Tuple[float, float]]:
        header_cols = self._detect_columns_from_header_underlines(page, table_y0, table_bbox=table_bbox)
        if header_cols and len(header_cols) >= 3:
            return header_cols

        numeric_words = [
            w for w in words
            if any(ch.isdigit() for ch in w[4]) or w[4].strip() in {"$", "—", "-", "%"}
        ]
        if not numeric_words:
            numeric_words = words

        x_intervals = [(w[0], w[2]) for w in numeric_words]
        x_intervals.sort(key=lambda x: x[0])

        clusters: List[List[Tuple[float, float]]] = []
        for x0, x1 in x_intervals:
            if not clusters:
                clusters.append([(x0, x1)])
            else:
                last_c = clusters[-1]
                c_max_x1 = max(item[1] for item in last_c)
                if x0 <= c_max_x1 + 8.0:
                    last_c.append((x0, x1))
                else:
                    clusters.append([(x0, x1)])

        raw_columns = []
        for c in clusters:
            c_x0 = min(item[0] for item in c)
            c_x1 = max(item[1] for item in c)
            raw_columns.append((c_x0, c_x1))

        if not raw_columns:
            return []

        merged_cols = [raw_columns[0]]
        for col in raw_columns[1:]:
            prev = merged_cols[-1]
            if col[0] - prev[1] < 12.0:
                merged_cols[-1] = (prev[0], max(prev[1], col[1]))
            else:
                merged_cols.append(col)

        table_x0 = table_bbox.x0 if table_bbox else min(w[0] for w in words)
        table_x1 = table_bbox.x1 if table_bbox else max(w[2] for w in words)

        # Build continuous gutter-midpoint columns
        boundaries = []
        for k in range(len(merged_cols) - 1):
            prev_end = merged_cols[k][1]
            next_start = merged_cols[k + 1][0]
            if prev_end < next_start:
                boundaries.append((prev_end + next_start) / 2.0)
            else:
                boundaries.append((merged_cols[k][0] + merged_cols[k + 1][0]) / 2.0)

        continuous_cols = []
        curr_x = table_x0
        for b in boundaries:
            continuous_cols.append((curr_x, b))
            curr_x = b
        continuous_cols.append((curr_x, table_x1))

        return continuous_cols

    def _detect_columns_from_header_underlines(
        self, page: fitz.Page, table_y0: float, table_bbox: Optional[BBox] = None
    ) -> List[Tuple[float, float]]:
        drawings = page.get_drawings()
        h_lines = []

        y_min_bound = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 40.0
        y_max_bound = table_bbox.y0 + 60.0 if table_bbox else table_y0 + 5.0

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

        best_y = max(lines_by_y.keys(), key=lambda y: (len(lines_by_y[y]), y))
        segments = lines_by_y[best_y]
        segments.sort(key=lambda s: s[0])

        merged = []
        for s in segments:
            if not merged:
                merged.append(list(s))
            else:
                if s[0] - merged[-1][1] <= 3.0:
                    merged[-1][1] = max(merged[-1][1], s[1])
                else:
                    merged.append(list(s))

        if len(merged) < 2:
            return []

        table_x0 = 30.0
        table_x1 = 600.0
        if table_bbox:
            table_x0 = table_bbox.x0
            table_x1 = table_bbox.x1

        boundaries = []
        if merged[0][0] - table_x0 > 25.0:
            b0 = merged[0][0] - 8.0
            boundaries.append(b0)

        for k in range(len(merged) - 1):
            prev_end = merged[k][1]
            next_start = merged[k + 1][0]
            bk = (prev_end + next_start) / 2.0
            boundaries.append(bk)

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
    ) -> Tuple[List[Cell], int]:
        """Normalize multi-line column headers into single structured header rows."""
        if not header_cells:
            return [], 0

        has_spans = any(c.colspan > 1 for c in header_cells)
        if not has_spans:
            merged_header_cells: List[Cell] = []
            col_cells: Dict[int, List[Cell]] = defaultdict(list)
            for c in header_cells:
                col_cells[c.col_index].append(c)

            for ci, (cx0, cx1) in enumerate(columns):
                cs = [c for c in col_cells.get(ci, []) if c.text.strip()]
                if cs:
                    cs.sort(key=lambda c: (c.row_index, c.bbox.y0))
                    merged_text = " ".join(c.text.strip() for c in cs if c.text.strip()).strip()
                    merged_bbox = BBox(
                        min(c.bbox.x0 for c in cs),
                        min(c.bbox.y0 for c in cs),
                        max(c.bbox.x1 for c in cs),
                        max(c.bbox.y1 for c in cs),
                    )
                    merged_header_cells.append(
                        Cell(
                            text=merged_text,
                            row_index=0,
                            col_index=ci,
                            colspan=1,
                            bbox=merged_bbox,
                        )
                    )
                else:
                    merged_header_cells.append(
                        Cell(
                            text="",
                            row_index=0,
                            col_index=ci,
                            colspan=1,
                            bbox=BBox(
                                cx0,
                                min(c.bbox.y0 for c in header_cells),
                                cx1,
                                max(c.bbox.y1 for c in header_cells),
                            ),
                        )
                    )
            return merged_header_cells, 1

        # Multi-tier spanning header
        spanning_rows = set(c.row_index for c in header_cells if c.colspan > 1)
        max_span_row = max(spanning_rows)

        span_partitions: List[Tuple[int, int]] = []
        spanned_cols = set()
        for c in header_cells:
            if c.row_index <= max_span_row and c.colspan > 1:
                sc = c.col_index
                ec = c.col_index + c.colspan - 1
                span_partitions.append((sc, ec))
                for ci in range(sc, ec + 1):
                    spanned_cols.add(ci)

        for ci in range(len(columns)):
            if ci not in spanned_cols:
                span_partitions.append((ci, ci))

        span_partitions = sorted(list(set(span_partitions)))

        tier0_cells = []
        for sc, ec in span_partitions:
            part_cells = [
                c for c in header_cells
                if c.row_index <= max_span_row
                and c.text.strip()
                and (
                    (c.colspan > 1 and c.col_index == sc and c.col_index + c.colspan - 1 == ec)
                    or (c.colspan == 1 and sc <= c.col_index <= ec)
                )
            ]
            if part_cells:
                part_cells.sort(key=lambda c: (round(c.bbox.y0 / 4.0), c.bbox.x0))
                text = " ".join(c.text.strip() for c in part_cells if c.text.strip()).strip()
                bbox_merged = BBox(
                    min(c.bbox.x0 for c in part_cells),
                    min(c.bbox.y0 for c in part_cells),
                    max(c.bbox.x1 for c in part_cells),
                    max(c.bbox.y1 for c in part_cells),
                )
                tier0_cells.append(
                    Cell(
                        text=text,
                        row_index=0,
                        col_index=sc,
                        colspan=ec - sc + 1,
                        bbox=bbox_merged,
                    )
                )
            else:
                tier0_cells.append(
                    Cell(
                        text="",
                        row_index=0,
                        col_index=sc,
                        colspan=ec - sc + 1,
                        bbox=BBox(
                            columns[sc][0],
                            min(c.bbox.y0 for c in header_cells),
                            columns[ec][1],
                            max(c.bbox.y1 for c in header_cells if c.row_index <= max_span_row),
                        ),
                    )
                )

        tier0_cells.sort(key=lambda c: c.col_index)

        sub_cells = [c for c in header_cells if c.row_index > max_span_row]
        if not sub_cells:
            return tier0_cells, 1

        merged_sub_cells = []
        col_sub: Dict[int, List[Cell]] = defaultdict(list)
        for c in sub_cells:
            col_sub[c.col_index].append(c)

        for ci, (cx0, cx1) in enumerate(columns):
            cs = [c for c in col_sub.get(ci, []) if c.text.strip()]
            if cs:
                cs.sort(key=lambda c: (c.row_index, c.bbox.y0))
                merged_text = " ".join(c.text.strip() for c in cs if c.text.strip()).strip()
                merged_bbox = BBox(
                    min(c.bbox.x0 for c in cs),
                    min(c.bbox.y0 for c in cs),
                    max(c.bbox.x1 for c in cs),
                    max(c.bbox.y1 for c in cs),
                )
                merged_sub_cells.append(
                    Cell(
                        text=merged_text,
                        row_index=1,
                        col_index=ci,
                        colspan=1,
                        bbox=merged_bbox,
                    )
                )
            else:
                merged_sub_cells.append(
                    Cell(
                        text="",
                        row_index=1,
                        col_index=ci,
                        colspan=1,
                        bbox=BBox(
                            cx0,
                            min(c.bbox.y0 for c in sub_cells),
                            cx1,
                            max(c.bbox.y1 for c in sub_cells),
                        ),
                    )
                )

        return tier0_cells + merged_sub_cells, 2

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

        norm_h_cells, num_h_rows = self._normalize_zebra_headers(raw_header_cells, columns)

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
        if not words:
            return [
                Cell(
                    text="",
                    row_index=row_idx,
                    col_index=col_idx,
                    bbox=BBox(col_x0, row_y0, col_x1, row_y1),
                )
                for col_idx, (col_x0, col_x1) in enumerate(columns)
            ]

        span_lines: List[Tuple[float, float, int, int]] = []
        if page is not None and is_header:
            try:
                drawings = page.get_drawings()
                h_lines = []
                for d in drawings:
                    for it in d.get("items", []):
                        if it[0] == "l":
                            p1, p2 = it[1], it[2]
                            if abs(p1.y - p2.y) <= 1.5:
                                y = p1.y
                                if row_y0 + 2.0 <= y <= row_y1 + 6.0:
                                    h_lines.append((round(y, 1), min(p1.x, p2.x), max(p1.x, p2.x)))
                        elif it[0] == "re":
                            r = it[1]
                            if r.height <= 3.0:
                                y = r.y0
                                if row_y0 + 2.0 <= y <= row_y1 + 6.0:
                                    h_lines.append((round(y, 1), r.x0, r.x1))

                lines_by_y: Dict[float, List[Tuple[float, float]]] = defaultdict(list)
                for y, x0, x1 in h_lines:
                    matched_y = None
                    for ey in lines_by_y:
                        if abs(y - ey) <= 2.0:
                            matched_y = ey
                            break
                    if matched_y is None:
                        matched_y = y
                    lines_by_y[matched_y].append((x0, x1))

                table_min_x = min(col[0] for col in columns)
                table_max_x = max(col[1] for col in columns)
                table_w = table_max_x - table_min_x

                for y, segs in sorted(lines_by_y.items()):
                    segs.sort(key=lambda s: s[0])
                    merged = []
                    for s in segs:
                        if not merged:
                            merged.append(list(s))
                        else:
                            if s[0] - merged[-1][1] <= 3.0:
                                merged[-1][1] = max(merged[-1][1], s[1])
                            else:
                                merged.append(list(s))

                    for lx0, lx1 in merged:
                        if (lx1 - lx0) >= table_w * 0.95:
                            continue
                        sc = None
                        ec = None
                        for ci, (cx0, cx1) in enumerate(columns):
                            col_w = max(1.0, cx1 - cx0)
                            overlap = max(0.0, min(lx1, cx1) - max(lx0, cx0))
                            if overlap / col_w >= 0.20:
                                if sc is None:
                                    sc = ci
                                ec = ci
                        if sc is not None and ec is not None and ec > sc:
                            span_lines.append((lx0, lx1, sc, ec))
            except Exception:
                pass

        if span_lines and is_header:
            cells: List[Cell] = []
            covered_cols = set()
            used_words = set()

            for lx0, lx1, sc, ec in span_lines:
                line_words = [
                    w for w in words
                    if lx0 - 5.0 <= (w[0] + w[2]) / 2.0 <= lx1 + 5.0
                ]
                if not line_words:
                    continue

                sorted_lw = sorted(line_words, key=lambda w: w[0])
                lw_clusters: List[List[Tuple]] = []
                curr_c: List[Tuple] = [sorted_lw[0]]
                for w in sorted_lw[1:]:
                    if w[0] - curr_c[-1][2] <= 12.0:
                        curr_c.append(w)
                    else:
                        lw_clusters.append(curr_c)
                        curr_c = [w]
                if curr_c:
                    lw_clusters.append(curr_c)

                if len(lw_clusters) == 1:
                    ws = lw_clusters[0]
                    ws.sort(key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0]))
                    text = " ".join(w[4].strip() for w in ws if w[4].strip()).strip()
                    cells.append(Cell(
                        text=text,
                        row_index=row_idx,
                        col_index=sc,
                        colspan=ec - sc + 1,
                        bbox=BBox(
                            min(w[0] for w in ws),
                            min(w[1] for w in ws),
                            max(w[2] for w in ws),
                            max(w[3] for w in ws),
                        ),
                    ))
                    for w in ws:
                        used_words.add(id(w))
                    for c in range(sc, ec + 1):
                        covered_cols.add(c)
                else:
                    for ws in lw_clusters:
                        ws_xc = (min(w[0] for w in ws) + max(w[2] for w in ws)) / 2.0
                        ci = self._find_column(ws_xc, columns)
                        ws.sort(key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0]))
                        text = " ".join(w[4].strip() for w in ws if w[4].strip()).strip()
                        cells.append(Cell(
                            text=text,
                            row_index=row_idx,
                            col_index=ci,
                            colspan=1,
                            bbox=BBox(
                                min(w[0] for w in ws),
                                min(w[1] for w in ws),
                                max(w[2] for w in ws),
                                max(w[3] for w in ws),
                            ),
                        ))
                        for w in ws:
                            used_words.add(id(w))
                        covered_cols.add(ci)

            remaining_words = [w for w in words if id(w) not in used_words]
            col_words: Dict[int, List[Tuple]] = defaultdict(list)
            for w in remaining_words:
                w_xc = (w[0] + w[2]) / 2.0
                ci = self._find_column(w_xc, columns)
                col_words[ci].append(w)

            for ci, (cx0, cx1) in enumerate(columns):
                if ci in covered_cols:
                    continue
                ws = col_words.get(ci, [])
                if not ws:
                    cells.append(Cell(text="", row_index=row_idx, col_index=ci, bbox=BBox(cx0, row_y0, cx1, row_y1)))
                else:
                    ws.sort(key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0]))
                    text = " ".join(w[4].strip() for w in ws if w[4].strip()).strip()
                    cells.append(Cell(
                        text=text,
                        row_index=row_idx,
                        col_index=ci,
                        colspan=1,
                        bbox=BBox(min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws)),
                    ))

            cells.sort(key=lambda c: c.col_index)
            return cells

        col_to_words: Dict[int, List[Tuple]] = defaultdict(list)
        for w in words:
            x_center = (w[0] + w[2]) / 2.0
            ci = self._find_column(x_center, columns)
            col_to_words[ci].append(w)

        cells: List[Cell] = []
        for col_idx, (col_x0, col_x1) in enumerate(columns):
            words_in_col = col_to_words.get(col_idx, [])
            if not words_in_col:
                cells.append(Cell(
                    text="",
                    row_index=row_idx,
                    col_index=col_idx,
                    bbox=BBox(col_x0, row_y0, col_x1, row_y1),
                ))
                continue

            words_in_col.sort(key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0]))
            text = " ".join(w[4].strip() for w in words_in_col if w[4].strip())

            x0 = min(w[0] for w in words_in_col)
            y0 = min(w[1] for w in words_in_col)
            x1 = max(w[2] for w in words_in_col)
            y1 = max(w[3] for w in words_in_col)

            cells.append(Cell(
                text=text,
                row_index=row_idx,
                col_index=col_idx,
                colspan=1,
                bbox=BBox(x0, y0, x1, y1),
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
