"""English wireless table extraction strategies."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from hexai_pdf_parser.tables.wireless_structure import continuations

import fitz

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.base_table_extractor import BaseTableExtractor
from hexai_pdf_parser.extractors.language_detector import detect_page_language
from hexai_pdf_parser.tables.wireless_table_recovery import recover_wireless_tables


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


class EnglishTableExtractor(BaseTableExtractor):

    @staticmethod
    def _merge_standalone_currency_columns(columns: List[Tuple[float, float]], words: List[Tuple]) -> List[Tuple[float, float]]:
        """Merge OCR-only ``$`` columns with the immediately following amount column."""
        cols = list(columns)
        i = 0
        while i < len(cols):
            x0, x1 = cols[i]
            tokens = [str(w[4]).strip() for w in (words or []) if x0 <= w[0] < x1]
            if (
                i > 0
                and x1 - x0 <= 8.0
                and not any("%" in token for token in tokens)
            ):
                next_tokens = (
                    [
                        str(w[4]).strip()
                        for w in (words or [])
                        if cols[i + 1][0] <= w[0] < cols[i + 1][1]
                    ]
                    if i < len(cols) - 1
                    else []
                )
                if any(
                    token == "$" or re.match(r"^\$[\d(]", token)
                    for token in next_tokens
                ):
                    cols[i] = (x0, cols[i + 1][1])
                    del cols[i + 1]
                    continue
                if i == len(cols) - 1:
                    cols[i - 1] = (cols[i - 1][0], x1)
                    del cols[i]
                    continue
            if tokens and all(token == "$" for token in tokens):
                if i == len(cols) - 1:
                    i += 1
                    continue
                cols[i] = (x0, cols[i + 1][1])
                del cols[i + 1]
            elif i > 0 and tokens and not any(ch.isdigit() for token in tokens for ch in token):
                next_tokens = [
                    str(w[4]).strip()
                    for w in (words or [])
                    if i < len(cols) - 1 and cols[i + 1][0] <= w[0] < cols[i + 1][1]
                ]
                if i < len(cols) - 1 and any(ch.isdigit() for token in next_tokens for ch in token):
                    cols[i] = (x0, cols[i + 1][1])
                    del cols[i + 1]
                    continue
            else:
                i += 1
        return cols

    @staticmethod
    def _adjust_columns_for_currency(columns: List[Tuple[float, float]], words: List[Tuple]) -> List[Tuple[float, float]]:
        """微调列分界线，确保位于各金额列左边缘的 '$' 完整归入右侧金额列，避免被划分到左侧列。"""
        new_cols = list(columns)
        for k in range(len(new_cols) - 1):
            c_left = new_cols[k]
            c_right = new_cols[k + 1]
            bk = c_left[1]
            misplaced_dollars = []
            for w in words:
                if w[4] == "$" and c_left[0] < (w[0] + w[2]) / 2.0 < bk:
                    row_words_left = [lw for lw in words if abs((lw[1] + lw[3]) / 2.0 - (w[1] + w[3]) / 2.0) <= 3.0 and c_left[0] <= (lw[0] + lw[2]) / 2.0 < bk]
                    if all(lw[2] <= w[0] + 0.1 for lw in row_words_left if lw != w):
                        row_words_right = [rw for rw in words if abs((rw[1] + rw[3]) / 2.0 - (w[1] + w[3]) / 2.0) <= 3.0 and bk <= (rw[0] + rw[2]) / 2.0 <= c_right[1]]
                        if any(any(ch.isdigit() for ch in rw[4]) for rw in row_words_right):
                            misplaced_dollars.append(w)
            if misplaced_dollars:
                min_dollar_x0 = min(w[0] for w in misplaced_dollars)
                left_words = [w for w in words if c_left[0] <= (w[0] + w[2]) / 2.0 < min_dollar_x0 and w not in misplaced_dollars and w[2] <= min_dollar_x0 + 0.5 and any(ch.isalnum() for ch in w[4])]
                left_data_words = [w for w in left_words if any(ch.isdigit() for ch in w[4])]
                max_left_x1 = max([w[2] for w in (left_data_words or left_words)], default=c_left[0])
                new_bk = (max_left_x1 + min_dollar_x0) / 2.0
                new_cols[k] = (c_left[0], new_bk)
                new_cols[k + 1] = (new_bk, c_right[1])
        return new_cols

    @staticmethod
    def _promote_grouped_header_cells(cells: List[Cell], columns: List[Tuple[float, float]], header_rows: int) -> None:
        """Apply one topology-based colspan rule to all English wireless paths."""
        if header_rows < 2:
            return
        for row_index in range(header_rows - 1):
            upper = [c for c in cells if c.row_index == row_index and c.text.strip()]
            lower = sorted([c for c in cells if c.row_index == row_index + 1 and c.text.strip()], key=lambda c: c.col_index)
            if len(upper) != 1 or len(lower) < 2:
                continue
            title = upper[0]
            center = (title.bbox.x0 + title.bbox.x1) / 2.0
            data_lower = [c for c in lower if c.col_index > 0]
            runs: List[List[Cell]] = []
            for child in data_lower:
                if not runs or child.col_index == runs[-1][-1].col_index + max(1, runs[-1][-1].colspan):
                    if not runs:
                        runs.append([])
                    runs[-1].append(child)
                else:
                    runs.append([child])
            run = next((r for r in runs if columns[r[0].col_index][0] <= center <= columns[r[-1].col_index + max(1, r[-1].colspan) - 1][1]), None)
            if run is None or len(run) < 2:
                continue
            start = run[0].col_index
            end = run[-1].col_index + max(1, run[-1].colspan)
            title.col_index = start
            title.colspan = end - start
            title.bbox = BBox(columns[start][0], title.bbox.y0, columns[end - 1][1], title.bbox.y1)
    """Extracts wireless tables: zebra colored background bands, 3-line tables, and borderless text-alignment."""

    def __init__(
        self,
        line_tolerance: float = 2.0,
        color_tolerance: float = 0.05,
        row_merge_tolerance: float = 2.0,
        method_owner: Optional[BaseTableExtractor] = None,
    ):
        self.line_tolerance = line_tolerance
        self.color_tolerance = color_tolerance
        self.row_merge_tolerance = row_merge_tolerance
        self._method_owner = method_owner
        self._last_wireless_recovery = None
        self._last_text_alignment_debug = None

    def extract(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
        page_language: Optional[str] = None,
    ) -> List[Table]:
        """Extract an English wireless table from a candidate region or page."""
        if page_language is None:
            page_language = detect_page_language(page)

        if page_language != "en":
            return []

        owner = self._method_owner or self
        if table_bbox is None:
            # Separate horizontal-line clusters are common in English
            # two-column reports and should be processed independently.
            try:
                drawings = page.get_drawings() if page else []
                h_segs = []
                for d in drawings:
                    for it in d.get("items", []):
                        if it[0] in ("l", "re"):
                            y = it[1].y if it[0] == "l" else it[1].y0
                            w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                            h = abs(it[2].y - it[1].y) if it[0] == "l" else it[1].height
                            x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                            x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                            if h <= 3.0 and w >= 20.0:
                                h_segs.append((x0, x1, y))
                if len(h_segs) >= 4:
                    col_clusters = []
                    for s in sorted(h_segs, key=lambda s: s[0]):
                        matched_cl = None
                        for cl in col_clusters:
                            cl_x0 = min(item[0] for item in cl)
                            cl_x1 = max(item[1] for item in cl)
                            if max(cl_x0, s[0]) < min(cl_x1, s[1]) + 20.0:
                                matched_cl = cl
                                break
                        if matched_cl is not None:
                            matched_cl.append(s)
                        else:
                            col_clusters.append([s])
                    if len(col_clusters) >= 2:
                        split_tables = []
                        page_words = page.get_text("words")
                        for cl in col_clusters:
                            if len(cl) >= 2:
                                cl_x0 = min(s[0] for s in cl) - 5.0
                                cl_x1 = max(s[1] for s in cl) + 5.0
                                cl_y0 = min(s[2] for s in cl)
                                cl_y1 = max(s[2] for s in cl)
                                related_words = [
                                    w for w in page_words
                                    if cl_x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= cl_x1 + 5.0
                                    and cl_y0 - 30.0 <= (w[1] + w[3]) / 2.0 <= cl_y1 + 5.0
                                ]
                                if related_words:
                                    t_x0 = min(min(w[0] for w in related_words), cl_x0)
                                    t_x1 = max(max(w[2] for w in related_words), cl_x1)
                                    t_y0 = min(w[1] for w in related_words)
                                    t_y1 = max(max(w[3] for w in related_words), cl_y1)
                                    region_bbox = BBox(t_x0, t_y0, t_x1, t_y1)
                                    split_tables.extend(
                                        owner.extract_general_wireless(
                                            page,
                                            table_bbox=region_bbox,
                                            confidence=confidence,
                                        )
                                    )
                        if split_tables:
                            return split_tables
            except Exception:
                pass

        zebra_tables = owner.extract_zebra(
            page, table_bbox=table_bbox, confidence=confidence
        )
        if zebra_tables:
            return zebra_tables

        general_tables = owner.extract_general_wireless(
            page, table_bbox=table_bbox, confidence=confidence
        )
        if general_tables:
            return general_tables

        if table_bbox is not None:
            row_count, col_count, cells = owner.extract_cells_from_region(page, table_bbox)
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

    def extract_text_alignment_candidates(
        self,
        page: fitz.Page,
        excluded_regions: Optional[List[BBox]] = None,
        allowed_regions: Optional[List[BBox]] = None,
        use_legacy_fallback: bool = True,
    ) -> List[Table]:
        """Return native-span candidates for an English page.

        The legacy words path remains an optional callback so the page-level
        orchestrator can keep its historical reconstruction without coupling
        this module to :class:`TableExtractor`.
        """
        if allowed_regions == []:
            self._last_wireless_recovery = {"regions": [], "disabled": True}
            self._last_text_alignment_debug = None
            return []

        owner = self._method_owner
        legacy = getattr(owner, "_extract_legacy_text_alignment", None)
        if (
            use_legacy_fallback
            and owner is not None
            and getattr(owner, "_legacy_text_alignment_callback", None) is not None
            and legacy is not None
        ):
            tables = legacy(
                page,
                excluded_regions=excluded_regions,
                allowed_regions=allowed_regions,
            )
            for name in ("_last_wireless_recovery", "_last_text_alignment_debug"):
                if hasattr(owner, name):
                    setattr(self, name, getattr(owner, name))
            return tables

        try:
            wireless = recover_wireless_tables(
                page,
                excluded_regions=excluded_regions,
                allowed_regions=allowed_regions,
            )
        except (AttributeError, TypeError, ValueError):
            wireless = None

        if wireless is None:
            self._last_wireless_recovery = {"regions": []}
            return []

        tables = list(wireless.tables)
        if excluded_regions:
            tables = [
                table
                for table in tables
                if not any(
                    min(table.bbox.x1, region.x1) > max(table.bbox.x0, region.x0)
                    and min(table.bbox.y1, region.y1) > max(table.bbox.y0, region.y0)
                    for region in excluded_regions
                )
            ]
        self._last_wireless_recovery = wireless.diagnostics
        self._last_text_alignment_debug = None

        return tables

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
                if page is not None:
                    expanded_x0 = max(float(page.rect.x0), expanded_x0)
                    expanded_y0 = max(float(page.rect.y0), expanded_y0)
                    expanded_x1 = min(float(page.rect.x1), expanded_x1)
                    expanded_y1 = min(float(page.rect.y1), expanded_y1)
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

        # 提取页面水平线段用于行划分、子表格划分与表头层级判定
        drawings = page.get_drawings() if page else []
        h_lines: List[Tuple[float, float, float]] = []
        for d in drawings:
            for it in d.get("items", []):
                if it[0] in ("l", "re"):
                    y = it[1].y if it[0] == "l" else it[1].y0
                    w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                    h = abs(it[2].y - it[1].y) if it[0] == "l" else it[1].height
                    x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                    x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                    if h <= 3.0 and w >= 2.0:
                        h_lines.append((round(y, 1), round(x0, 1), round(x1, 1)))

        # 1. 行的确定 (Y轴): 按 Y 坐标重叠聚类为行 (垂直重叠 <= 3.5pt，且中间无物理水平横线)
        t_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
        rows_words: List[List[Tuple]] = []
        for w in t_words:
            mid_y = (w[1] + w[3]) / 2.0
            matched = False
            for rw in rows_words:
                rw_mid = sum((lw[1] + lw[3]) / 2.0 for lw in rw) / len(rw)
                has_sep_line = any(
                    min(mid_y, rw_mid) + 0.5 < ly < max(mid_y, rw_mid) - 0.5
                    and max(w[0], min(lw[0] for lw in rw)) < lx1
                    and min(w[2], max(lw[2] for lw in rw)) > lx0
                    for ly, lx0, lx1 in h_lines
                )
                if not has_sep_line and abs(mid_y - rw_mid) <= 3.5:
                    rw.append(w)
                    matched = True
                    break
            if not matched:
                rows_words.append([w])

        rows_words.sort(key=lambda rw: min(w[1] for w in rw))
        for rw in rows_words:
            rw.sort(key=lambda w: w[0])

        # 纯几何子表格切分：查找独立的表头下划线分列组 (Header Column Underline Sets)
        tb_x0 = table_bbox.x0 if table_bbox else min(w[0] for w in t_words)
        tb_x1 = table_bbox.x1 if table_bbox else max(w[2] for w in t_words)

        lines_in_table = [l for l in h_lines if tb_x0 - 5.0 <= (l[1] + l[2]) / 2.0 <= tb_x1 + 5.0 and rows_words[0][0][1] - 5.0 <= l[0] <= rows_words[-1][0][3] + 5.0]
        lines_by_y: Dict[float, List[Tuple[float, float, float]]] = defaultdict(list)
        for l in lines_in_table:
            matched_y = None
            for ey in lines_by_y:
                if abs(l[0] - ey) <= 2.0:
                    matched_y = ey
                    break
            if matched_y is None:
                matched_y = l[0]
            lines_by_y[matched_y].append(l)

        header_underline_ys = []
        for y, segs in sorted(lines_by_y.items()):
            min_x0 = min(s[1] for s in segs)
            if len(segs) >= 2 and min_x0 > tb_x0 + 40.0:
                header_underline_ys.append(y)

        split_indices = [0]
        if table_bbox is None and len(header_underline_ys) > 1:
            prev_hy = header_underline_ys[0]
            for hy in header_underline_ys[1:]:
                # 纯几何判定：只有当下划线之间垂直跨度 >= 35pt（跨越多行数据）时才可能属于不同子表格
                if hy - prev_hy < 35.0:
                    continue
                target_r = None
                for r_idx in range(len(rows_words)):
                    r_y1 = max(w[3] for w in rows_words[r_idx])
                    if r_y1 < hy:
                        target_r = r_idx
                    else:
                        break
                if target_r is not None and target_r > 0:
                    split_r = target_r
                    for r in range(target_r, max(0, target_r - 2), -1):
                        r_prev_y1 = max(w[3] for w in rows_words[r - 1]) if r > 0 else 0
                        r_cur_y0 = min(w[1] for w in rows_words[r])
                        has_full_line = any(min(s[1] for s in segs) <= tb_x0 + 50.0 and len(segs) >= 3 and r_prev_y1 - 2.0 <= ly <= r_cur_y0 + 2.0 for ly, segs in lines_by_y.items())
                        if has_full_line:
                            split_r = r
                            break
                    if split_r not in split_indices and split_r > split_indices[-1]:
                        split_indices.append(split_r)
                        prev_hy = hy

        split_indices.append(len(rows_words))

        blocks = page.get_text("blocks") if page else []

        tables_out: List[Table] = []
        for s_i in range(len(split_indices) - 1):
            sub_rows = rows_words[split_indices[s_i]:split_indices[s_i + 1]]
            sub_words = [w for rw in sub_rows for w in rw]
            sub_y0 = min(w[1] for w in sub_words)
            sub_y1 = max(w[3] for w in sub_words)
            sub_bbox = BBox(
                table_bbox.x0 if table_bbox else min(w[0] for w in sub_words),
                sub_y0,
                table_bbox.x1 if table_bbox else max(w[2] for w in sub_words),
                sub_y1,
            )

            # 过滤与当前子表格相交的 text blocks
            table_blocks = [
                b for b in blocks
                if b[4].strip()
                and max(sub_bbox.x0 - 5.0, b[0]) < min(sub_bbox.x1 + 5.0, b[2])
                and max(sub_bbox.y0 - 2.0, b[1]) < min(sub_bbox.y1 + 2.0, b[3])
            ]

            # 行线切割文本框合并规则 (Rule 4.4) - 物理横线为最高优先级强制分割线
            if len(sub_rows) > 1 and table_blocks:
                merged_sub_rows = [sub_rows[0]]
                for r in range(1, len(sub_rows)):
                    prev_row = merged_sub_rows[-1]
                    cur_row = sub_rows[r]
                    prev_y1 = max(w[3] for w in prev_row)
                    cur_y0 = min(w[1] for w in cur_row)
                    boundary_y = (prev_y1 + cur_y0) / 2.0

                    has_line_between = any(
                        prev_y1 - 1.5 <= l[0] <= cur_y0 + 1.5
                        and max(min(w[0] for w in prev_row), min(w[0] for w in cur_row)) < l[2]
                        and min(max(w[2] for w in prev_row), max(w[2] for w in cur_row)) > l[1]
                        for l in lines_in_table
                    )
                    if has_line_between:
                        merged_sub_rows.append(cur_row)
                        continue

                    # 仅当两行之间没有独立数值冲突且 Text Block 高度较小（<= 28pt，仅为2行单元格换行）时才允许考虑合并
                    block_h = min((b[3] - b[1] for b in table_blocks if b[1] + 1.0 < boundary_y < b[3] - 1.0), default=999.0)
                    both_have_numeric = any(any(ch.isdigit() for ch in w[4]) for w in prev_row) and any(any(ch.isdigit() for ch in w[4]) for w in cur_row)
                    is_cut = (block_h <= 28.0) and not both_have_numeric and any(
                        b[1] + 1.0 < boundary_y < b[3] - 1.0
                        for b in table_blocks
                    )

                    if is_cut:
                        prev_row.extend(cur_row)
                        prev_row.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                    else:
                        merged_sub_rows.append(cur_row)
                sub_rows = merged_sub_rows

            # 2. 列的确定: 优先使用基于下划线几何与垂直空白投影的标准列检测器
            columns = self._detect_columns_from_header_underlines(
                page=page,
                table_y0=sub_y0,
                table_bbox=sub_bbox,
                words=sub_words,
            )
            if not columns or len(columns) < 2:
                columns = self._detect_columns(
                    words=sub_words,
                    data_rows=None,
                    page=page,
                    table_y0=sub_y0,
                    table_bbox=sub_bbox,
                )
            if not columns or len(columns) < 2:
                continue

            # 检查表头下划线并在各层表头无内横线时聚合单层表头 (Rule 2.2 & Rule 2.3)
            sub_h = [
                (l[1], l[2], l[0])
                for l in h_lines
                if sub_bbox.x0 - 5.0 <= (l[1] + l[2]) / 2.0 <= sub_bbox.x1 + 5.0
                and sub_y0 - 2.0 <= l[0] <= sub_y1 + 2.0
            ]
            sub_lines_by_y: Dict[float, List[Tuple[float, float, float]]] = defaultdict(list)
            for l in sub_h:
                matched_y = None
                for ey in sub_lines_by_y:
                    if abs(l[2] - ey) <= 2.0:
                        matched_y = ey
                        break
                if matched_y is None:
                    matched_y = l[2]
                sub_lines_by_y[matched_y].append(l)

            # 水平线段几何融合 (Rule: gap <= 3.0pt 视为同一条线)
            sub_fused_lines_by_y: Dict[float, List[Tuple[float, float, float]]] = {}
            for y, segs in sub_lines_by_y.items():
                sorted_s = sorted(segs, key=lambda s: s[0])
                fused = [sorted_s[0]]
                for s in sorted_s[1:]:
                    prev = fused[-1]
                    if s[0] - prev[1] <= 3.0:
                        fused[-1] = (min(prev[0], s[0]), max(prev[1], s[1]), prev[2])
                    else:
                        fused.append(s)
                sub_fused_lines_by_y[y] = fused
            raw_header_levels = sorted([
                y for y, segs in sub_fused_lines_by_y.items()
                if len(segs) >= 2 or max(s[1] for s in segs) - min(s[0] for s in segs) >= 25.0
            ])
            header_line_levels = []
            sub_w = sub_bbox.x1 - sub_bbox.x0
            for hy in raw_header_levels:
                header_line_levels.append(hy)
                segs = sub_fused_lines_by_y[hy]
                min_x = min(s[0] for s in segs)
                max_w = max(s[1] for s in segs) - min(s[0] for s in segs)
                if min_x <= sub_bbox.x0 + 15.0 and max_w >= sub_w * 0.75:
                    break

            raw_sub_rows = list(sub_rows)
            header_tier_count = 0
            if header_line_levels and len(sub_rows) > 1:
                bottom_header_y = max(header_line_levels)
                new_sub_rows = []
                prev_tier_y = sub_y0 - 5.0
                for h_level_y in header_line_levels:
                    tier_rows = [rw for rw in sub_rows if prev_tier_y < sum((w[1]+w[3])/2.0 for w in rw)/len(rw) <= h_level_y + 1.5]
                    if tier_rows:
                        merged_tier_w = []
                        for rw in tier_rows:
                            merged_tier_w.extend(rw)
                        merged_tier_w.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                        new_sub_rows.append(merged_tier_w)
                        header_tier_count += 1
                    prev_tier_y = h_level_y + 1.5

                data_rows = [rw for rw in sub_rows if sum((w[1]+w[3])/2.0 for w in rw)/len(rw) > bottom_header_y + 1.5]
                new_sub_rows.extend(data_rows)
                # 规则：如果表格只有一行（聚合后被误压为单行表头），按照原始文本行来划分
                if len(new_sub_rows) <= 1 and len(raw_sub_rows) > 1:
                    sub_rows = raw_sub_rows
                    header_tier_count = 1
                else:
                    sub_rows = new_sub_rows
            elif len(sub_rows) > 1:
                header_tier_count = 1

            # 规则指南第 56 条：多 $ 宽列自适应分裂与精准贴合（每一个 $ 的 x0 直接分裂为独立列）
            adj_cols = []
            for cx0, cx1 in columns:
                row_dollars_dict = defaultdict(list)
                for w in sub_words:
                    if w[4] == "$" and cx0 <= (w[0] + w[2]) / 2.0 < cx1:
                        mid_y = round((w[1] + w[3]) / 2.0 / 3.5)
                        row_dollars_dict[mid_y].append(w)
                multi_d_rows = [sorted(dw_list, key=lambda dw: dw[0]) for dw_list in row_dollars_dict.values() if len(dw_list) >= 2]
                if multi_d_rows:
                    max_d_count = max(len(r) for r in multi_d_rows)
                    split_cuts = [cx0]
                    for d_idx in range(1, max_d_count):
                        dollars_at_idx = [r[d_idx] for r in multi_d_rows if len(r) > d_idx]
                        if dollars_at_idx:
                            min_x0 = min(dw[0] for dw in dollars_at_idx)
                            split_cuts.append(min_x0)
                    split_cuts.append(cx1)
                    sorted_cuts = sorted(list(set(split_cuts)))
                    for i in range(len(sorted_cuts) - 1):
                        adj_cols.append((sorted_cuts[i], sorted_cuts[i + 1]))
                else:
                    adj_cols.append((cx0, cx1))
            if len(adj_cols) >= len(columns):
                columns = adj_cols

            # Grid X bounds
            table_x0 = sub_bbox.x0 if sub_bbox else columns[0][0]
            table_x1 = sub_bbox.x1 if sub_bbox else columns[-1][1]
            if page is not None:
                table_x0 = max(float(page.rect.x0), table_x0)
                table_x1 = min(float(page.rect.x1), table_x1)

            # 规则指南第 57 条：列线微调（严格与 $ 边框重合）
            grid_x_adj = [table_x0] + [c[1] for c in columns[:-1]] + [table_x1]
            data_w_list = [w for w in sub_words if (w[1] + w[3]) / 2.0 >= sub_y0 + 20.0]
            for ci in range(1, len(grid_x_adj) - 1):
                left_b = grid_x_adj[ci]
                col_dollars = [w for w in data_w_list if w[4] == "$" and left_b - 12.0 <= w[0] <= left_b + 12.0]
                if col_dollars:
                    min_d_x0 = min(w[0] for w in col_dollars)
                    if min_d_x0 > grid_x_adj[ci - 1] + 5.0:
                        grid_x_adj[ci] = min_d_x0
            grid_x = grid_x_adj

            # Grid Y bounds
            row_intervals = [(min(w[1] for w in rw), max(w[3] for w in rw)) for rw in sub_rows]
            grid_y = [sub_y0]
            for r in range(len(row_intervals) - 1):
                mid_y = (row_intervals[r][1] + row_intervals[r + 1][0]) / 2.0
                grid_y.append(mid_y)
            grid_y.append(sub_y1)

            num_rows = len(sub_rows)
            num_cols = len(columns)

            # 3. 单元格矩阵构建：纯几何按列投影与上层表头跨列构建
            grid_cells: Dict[Tuple[int, int], Cell] = {}
            for r_idx, rw in enumerate(sub_rows):
                is_header_tier = (r_idx < header_tier_count)

                if is_header_tier:
                    # 表头行：纯几何局部跨列识别与单列多行词完整聚合（避免覆盖丢失）
                    rw_y1 = max(w[3] for w in rw)
                    closest_y_lines = defaultdict(list)
                    for x0, x1, y in sub_h:
                        if rw_y1 - 2.0 <= y <= rw_y1 + 10.0:
                            matched_y = None
                            for ey in closest_y_lines:
                                if abs(y - ey) <= 1.5:
                                    matched_y = ey
                                    break
                            if matched_y is None:
                                matched_y = y
                            closest_y_lines[matched_y].append((x0, x1))

                    row_under_segs = []
                    if closest_y_lines:
                        best_y = min(closest_y_lines.keys())
                        sorted_segs = sorted(closest_y_lines[best_y], key=lambda s: s[0])
                        for s in sorted_segs:
                            if not row_under_segs:
                                row_under_segs.append(list(s))
                            else:
                                if s[0] - row_under_segs[-1][1] <= 3.0:
                                    row_under_segs[-1][1] = max(row_under_segs[-1][1], s[1])
                                else:
                                    row_under_segs.append(list(s))

                    # 1. 优先识别专属局部跨列下划线
                    spanning_cols = set()
                    for seg in row_under_segs:
                        if seg[0] <= grid_x[0] + 5.0 and seg[1] >= grid_x[-1] - 5.0:
                            continue
                        matched_cols = [
                            ci for ci in range(num_cols)
                            if seg[0] - 2.0 <= (grid_x[ci] + grid_x[ci + 1]) / 2.0 <= seg[1] + 2.0
                        ]
                        if 2 <= len(matched_cols) < num_cols:
                            sc = min(matched_cols)
                            ec = max(matched_cols)
                            colspan = ec - sc + 1
                            seg_words = [
                                w for w in rw
                                if seg[0] - 5.0 <= (w[0] + w[2]) / 2.0 <= seg[1] + 5.0
                            ]
                            if seg_words:
                                seg_rows = defaultdict(list)
                                for w in seg_words:
                                    my = round((w[1] + w[3]) / 2.0, 1)
                                    matched_y = next((ey for ey in seg_rows if abs(my - ey) <= 3.0), None)
                                    if matched_y is None:
                                        matched_y = my
                                    seg_rows[matched_y].append(w)
                                is_single_phrase_per_row = True
                                for ry, rwords in seg_rows.items():
                                    rwords.sort(key=lambda w: w[0])
                                    p_count = 0
                                    cur_p = []
                                    for w in rwords:
                                        if not cur_p:
                                            cur_p.append(w)
                                            p_count = 1
                                        else:
                                            if w[0] - cur_p[-1][2] <= 5.0:
                                                cur_p.append(w)
                                            else:
                                                p_count += 1
                                                cur_p = [w]
                                    if p_count >= 2:
                                        is_single_phrase_per_row = False
                                        break
                                if is_single_phrase_per_row:
                                    seg_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                                    txt = " ".join(w[4] for w in seg_words).strip().replace("$ ", "$")
                                    grid_cells[(r_idx, sc)] = Cell(
                                        row_index=r_idx,
                                        col_index=sc,
                                        rowspan=1,
                                        colspan=colspan,
                                        text=txt,
                                        bbox=BBox(round(grid_x[sc], 1), round(grid_y[r_idx], 1), round(grid_x[sc + colspan], 1), round(grid_y[r_idx + 1], 1)),
                                    )
                                    for ci in range(sc, ec + 1):
                                        spanning_cols.add(ci)

                    # 2. 规则 L27：无下划线或全宽底线时的纯几何中点投影跨列判定
                    remaining_words = [w for w in rw if not any(ci in spanning_cols for ci in range(num_cols) if grid_x[ci] <= (w[0] + w[2]) / 2.0 < grid_x[ci + 1])]
                    if remaining_words:
                        rem_rows = defaultdict(list)
                        for w in remaining_words:
                            my = round((w[1] + w[3]) / 2.0, 1)
                            matched_y = next((ey for ey in rem_rows if abs(my - ey) <= 3.0), None)
                            if matched_y is None:
                                matched_y = my
                            rem_rows[matched_y].append(w)

                        for ry, rwords in rem_rows.items():
                            rwords.sort(key=lambda w: w[0])
                            # 按水平间隙聚类出独立短语
                            p_list = []
                            cur_p = []
                            for w in rwords:
                                if not cur_p:
                                    cur_p.append(w)
                                else:
                                    prev_w = cur_p[-1]
                                    gap = w[0] - prev_w[2]
                                    c_prev = next((ci for ci in range(num_cols) if grid_x[ci] <= (prev_w[0] + prev_w[2]) / 2.0 < grid_x[ci + 1]), -1)
                                    c_curr = next((ci for ci in range(num_cols) if grid_x[ci] <= (w[0] + w[2]) / 2.0 < grid_x[ci + 1]), -1)
                                    if c_prev == c_curr and gap <= 6.0:
                                        cur_p.append(w)
                                    elif c_prev == 0 and c_curr == 0 and gap <= 10.0:
                                        cur_p.append(w)
                                    else:
                                        p_list.append(cur_p)
                                        cur_p = [w]
                            if cur_p:
                                p_list.append(cur_p)

                            for cl in p_list:
                                cl_x0 = min(w[0] for w in cl)
                                cl_x1 = max(w[2] for w in cl)
                                # 检查覆盖哪些数据列的几何中点（排除行标签列 Col 0）
                                cl_matched_cols = [
                                    ci for ci in range(1, num_cols)
                                    if ci not in spanning_cols
                                    and (cl_x0 - 2.0 <= (grid_x[ci] + grid_x[ci + 1]) / 2.0 <= cl_x1 + 2.0)
                                ]
                                if 2 <= len(cl_matched_cols) < num_cols:
                                    sc = min(cl_matched_cols)
                                    ec = max(cl_matched_cols)
                                    colspan = ec - sc + 1
                                    # 检查在当前短语列表中是否有其他并列短语也落在 [sc, ec] 范围内
                                    other_in_band = any(
                                        ocl is not cl and any(sc <= next((ci for ci in range(num_cols) if grid_x[ci] <= (ow[0] + ow[2]) / 2.0 < grid_x[ci + 1]), -1) <= ec for ow in ocl)
                                        for ocl in p_list
                                    )
                                    if other_in_band:
                                        continue
                                    # 收集该列带内的全部词
                                    band_words = [
                                        w for w in rw
                                        if grid_x[sc] - 2.0 <= (w[0] + w[2]) / 2.0 <= grid_x[ec + 1] + 2.0
                                    ]
                                    band_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                                    txt = " ".join(w[4] for w in band_words).strip().replace("$ ", "$")
                                    grid_cells[(r_idx, sc)] = Cell(
                                        row_index=r_idx,
                                        col_index=sc,
                                        rowspan=1,
                                        colspan=colspan,
                                        text=txt,
                                        bbox=BBox(round(grid_x[sc], 1), round(grid_y[r_idx], 1), round(grid_x[sc + colspan], 1), round(grid_y[r_idx + 1], 1)),
                                    )
                                    for ci in range(sc, ec + 1):
                                        spanning_cols.add(ci)

                    # 3. 其余未跨列的列，按列区间完整聚合多行词
                    for ci in range(num_cols):
                        if ci in spanning_cols:
                            continue
                        col_words = [
                            w for w in rw
                            if grid_x[ci] <= (w[0] + w[2]) / 2.0 < grid_x[ci + 1]
                        ]
                        if col_words:
                            col_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                            txt = " ".join(w[4] for w in col_words).strip().replace("$ ", "$")
                            grid_cells[(r_idx, ci)] = Cell(
                                row_index=r_idx,
                                col_index=ci,
                                rowspan=1,
                                colspan=1,
                                text=txt,
                                bbox=BBox(round(grid_x[ci], 1), round(grid_y[r_idx], 1), round(grid_x[ci + 1], 1), round(grid_y[r_idx + 1], 1)),
                            )
                        else:
                            grid_cells[(r_idx, ci)] = Cell(
                                row_index=r_idx,
                                col_index=ci,
                                rowspan=1,
                                colspan=1,
                                text="",
                                bbox=BBox(round(grid_x[ci], 1), round(grid_y[r_idx], 1), round(grid_x[ci + 1], 1), round(grid_y[r_idx + 1], 1)),
                            )
                    continue
                else:
                    # 表体数据行：纯文本跨列大标题自动合并 (Rule 4.1 Colspan)，普通数据行按列归属
                    rwords = sorted(rw, key=lambda w: w[0])
                    phrases = []
                    cur_p = []
                    for w in rwords:
                        if not cur_p:
                            cur_p.append(w)
                        else:
                            prev = cur_p[-1]
                            gap = w[0] - prev[2]
                            if gap <= 6.0 and not (prev[4] == "$" and any(ch.isdigit() for ch in w[4])) and not (any(ch.isdigit() for ch in prev[4]) and any(ch.isdigit() for ch in w[4]) and gap > 2.0):
                                cur_p.append(w)
                            else:
                                phrases.append(cur_p)
                                cur_p = [w]
                    if cur_p:
                        phrases.append(cur_p)

                    spanning_cols = set()
                    for p in phrases:
                        px0 = min(w[0] for w in p)
                        px1 = max(w[2] for w in p)
                        p_text = " ".join(w[4] for w in p).strip().replace("$ ", "$")
                        has_number = any(any(ch.isdigit() for ch in w[4]) for w in p) and not any(k in p_text for k in ("2024", "2023", "2022", "2021", "2020", "points", "Tenor", "Tier", "Level"))

                        covered_cols = [ci for ci in range(num_cols) if max(px0, grid_x[ci]) < min(px1, grid_x[ci + 1])]
                        if len(covered_cols) >= 2 and not has_number:
                            sc = min(covered_cols)
                            ec = max(covered_cols)
                            other_p_in_cols = [
                                op for op in phrases
                                if op is not p and any(sc <= ci <= ec for ci in [next((i for i in range(num_cols) if grid_x[i] <= (ow[0] + ow[2]) / 2.0 < grid_x[i + 1]), -1) for ow in op])
                            ]
                            if not other_p_in_cols:
                                colspan = ec - sc + 1
                                grid_cells[(r_idx, sc)] = Cell(
                                    row_index=r_idx,
                                    col_index=sc,
                                    rowspan=1,
                                    colspan=colspan,
                                    text=p_text,
                                    bbox=BBox(round(grid_x[sc], 1), round(grid_y[r_idx], 1), round(grid_x[sc + colspan], 1), round(grid_y[r_idx + 1], 1)),
                                )
                                for ci in range(sc, ec + 1):
                                    spanning_cols.add(ci)

                    col_words: Dict[int, List[Tuple]] = defaultdict(list)
                    for w in rw:
                        w_mid = (w[0] + w[2]) / 2.0
                        assigned_col = next((ci for ci in range(num_cols) if grid_x[ci] <= w_mid < grid_x[ci + 1]), None)
                        if assigned_col is None:
                            assigned_col = min(range(num_cols), key=lambda ci: abs(w_mid - (grid_x[ci] + grid_x[ci + 1]) / 2.0))
                        col_words[assigned_col].append(w)

                    for ci in range(num_cols):
                        if ci in spanning_cols:
                            continue
                        cw = col_words.get(ci, [])
                        if cw:
                            cw.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                            txt = " ".join(w[4] for w in cw).strip().replace("$ ", "$")
                            grid_cells[(r_idx, ci)] = Cell(
                                row_index=r_idx,
                                col_index=ci,
                                rowspan=1,
                                colspan=1,
                                text=txt,
                                bbox=BBox(round(grid_x[ci], 1), round(grid_y[r_idx], 1), round(grid_x[ci + 1], 1), round(grid_y[r_idx + 1], 1)),
                            )
                        else:
                            grid_cells[(r_idx, ci)] = Cell(
                                row_index=r_idx,
                                col_index=ci,
                                rowspan=1,
                                colspan=1,
                                text="",
                                bbox=BBox(round(grid_x[ci], 1), round(grid_y[r_idx], 1), round(grid_x[ci + 1], 1), round(grid_y[r_idx + 1], 1)),
                            )

            self._promote_grouped_header_cells(list(grid_cells.values()), columns, max(2, header_tier_count))
            rebuilt_grid_cells: Dict[Tuple[int, int], Cell] = {}
            for cell in grid_cells.values():
                if (cell.row_index, cell.col_index) not in rebuilt_grid_cells or cell.text.strip():
                    rebuilt_grid_cells[(cell.row_index, cell.col_index)] = cell
            grid_cells = rebuilt_grid_cells

            for key, cell in list(grid_cells.items()):
                for title in (c for c in grid_cells.values() if c.row_index == 0 and c.text.strip() and c.colspan > 1):
                    if cell is not title and cell.row_index == title.row_index and title.col_index <= key[1] < title.col_index + title.colspan:
                        del grid_cells[key]
                        break

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
                            cell.row_index == r and cell.col_index <= c < cell.col_index + cell.colspan
                            for cell in grid_cells.values()
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
            conf_score = round(confidence, 4) if confidence is not None else 0.90
            tables_out.append(
                Table(
                    bbox=sub_bbox,
                    rows=num_rows,
                    cols=num_cols,
                    cells=cells,
                    confidence=conf_score,
                    source="english_general_wireless",
                )
            )

        return tables_out

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
            else:
                return []

        colored_bgs = [bg for bg in row_backgrounds if bg[2] != "white"]
        if not colored_bgs:
            return []
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
                    drawings = page.get_drawings()
                    h_lines = []
                    for d in drawings:
                        for it in d.get("items", []):
                            if it[0] in ("l", "re"):
                                y = it[1].y if it[0] == "l" else (it[1].y0 + it[1].y1) / 2.0
                                x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                                x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                                if abs(x1 - x0) >= 15.0:
                                    h_lines.append((x0, x1, y))

                    filled_bgs = []
                    for i, bg in enumerate(data_bgs):
                        if i > 0:
                            prev_y1 = filled_bgs[-1][1]
                            cur_y0 = bg[0]
                            gap = cur_y0 - prev_y1
                            if gap >= 3.5:
                                filled_bgs.append((prev_y1, cur_y0, "white"))
                        filled_bgs.append(bg)

                    # Check if there's a top white zebra data row between header underline and first colored band
                    if table_bbox and table_bbox.y0 < first_colored_y - 6.0:
                        top_words = [w for w in words if table_bbox.y0 <= (w[1] + w[3]) / 2.0 < first_colored_y - 2.0]
                        if top_words:
                            top_lines = [l[2] for l in h_lines if table_bbox.y0 <= l[2] <= first_colored_y - 2.0]
                            if top_lines:
                                split_y = max(top_lines)
                                data_top_words = [w for w in top_words if (w[1] + w[3]) / 2.0 > split_y]
                                if data_top_words and first_colored_y - split_y >= 6.0:
                                    filled_bgs.insert(0, (split_y, first_colored_y, "white"))

                    # Check if there's a bottom white zebra row after last colored band
                    if table_bbox and table_bbox.y1 > last_colored_y + 4.0:
                        bot_words = [w for w in words if last_colored_y + 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0]
                        if bot_words:
                            filled_bgs.append((last_colored_y, table_bbox.y1, "white"))

                    data_bgs = filled_bgs
                    row_backgrounds = data_bgs
                except Exception:
                    pass

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

        columns = self._detect_columns_from_header_underlines(
            page=page,
            table_y0=table_y0,
            table_bbox=table_bbox,
            words=all_words_for_cols,
        )
        if not columns or len(columns) < 2:
            columns = self._detect_columns(all_words_for_cols, data_rows, page, table_y0=table_y0, table_bbox=table_bbox)
        if not columns or len(columns) < 2:
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

        colored_rects: List[List[Any]] = []
        white_rects: List[List[Any]] = []

        def _is_white(fill_val: Any) -> bool:
            if isinstance(fill_val, (tuple, list)):
                return all(c >= 0.98 for c in fill_val[:3])
            elif isinstance(fill_val, (int, float)):
                return fill_val >= 0.98
            return False

        def _is_colored_bg(fill_val: Any) -> bool:
            if isinstance(fill_val, (tuple, list)):
                if len(fill_val) >= 3:
                    avg = sum(fill_val[:3]) / 3.0
                    return 0.35 <= avg <= 0.97
            elif isinstance(fill_val, (int, float)):
                return 0.35 <= fill_val <= 0.97
            return False

        for d in drawings:
            fill = d.get("fill")
            rect = d.get("rect")
            items = d.get("items", [])
            if fill is None:
                continue

            rect_list = []
            if rect is not None and rect.height >= 4.0 and rect.width >= 30.0:
                rect_list.append(rect)
            for it in items:
                if it[0] == "re":
                    r = it[1]
                    if r.height >= 4.0 and r.width >= 30.0:
                        rect_list.append(r)

            if _is_colored_bg(fill):
                for r in rect_list:
                    colored_rects.append([r.y0, r.y1, "colored"])
            elif _is_white(fill):
                for r in rect_list:
                    white_rects.append([r.y0, r.y1, "white"])

        if not colored_rects and not white_rects:
            return []

        # Merge vertically overlapping/adjacent colored rects into unified row intervals
        colored_rects.sort(key=lambda x: x[0])
        merged_colored: List[List[Any]] = []
        for r in colored_rects:
            if not merged_colored:
                merged_colored.append(r)
            else:
                prev = merged_colored[-1]
                if r[0] <= prev[1] + 2.0:
                    prev[1] = max(prev[1], r[1])
                else:
                    merged_colored.append(r)

        all_bgs = merged_colored + white_rects
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
        raw_h_lines: List[Tuple[float, float, float]] = []
        if page is not None:
            try:
                drawings = page.get_drawings()
                y_min_bound = table_bbox.y0 - 2.0 if table_bbox else table_y0 - 50.0
                table_w = (table_bbox.x1 - table_bbox.x0) if table_bbox else 300.0
                for d in drawings:
                    for it in d.get("items", []):
                        if it[0] in ("l", "re"):
                            y = it[1].y if it[0] == "l" else it[1].y0
                            x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                            x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                            if table_bbox and (x1 < table_bbox.x0 - 5.0 or x0 > table_bbox.x1 + 5.0):
                                continue
                            if y_min_bound <= y <= table_y0 + 2.0 and x1 - x0 >= 2.0:
                                raw_h_lines.append((round(y, 1), x0, x1))
            except Exception:
                pass

        # Merge collinear line segments
        lines_by_y: Dict[float, List[Tuple[float, float]]] = defaultdict(list)
        for y, x0, x1 in raw_h_lines:
            matched_y = next((ey for ey in lines_by_y if abs(y - ey) <= 1.0), None)
            if matched_y is None:
                matched_y = y
            lines_by_y[matched_y].append((x0, x1))

        h_lines = []
        full_width_dividing_lines = []
        table_w = (table_bbox.x1 - table_bbox.x0) if table_bbox else 300.0
        for y, segs in lines_by_y.items():
            sorted_segs = sorted(segs, key=lambda s: s[0])
            cur_x0, cur_x1 = sorted_segs[0]
            tot_w = 0.0
            for nx0, nx1 in sorted_segs[1:]:
                if nx0 <= cur_x1 + 5.0:
                    cur_x1 = max(cur_x1, nx1)
                else:
                    tot_w += (cur_x1 - cur_x0)
                    cur_x0, cur_x1 = nx0, nx1
            tot_w += (cur_x1 - cur_x0)
            if tot_w >= 15.0:
                h_lines.append(y)
            if tot_w >= table_w * 0.6 and y < table_y0 - 8.0:
                full_width_dividing_lines.append(y)

        unique_h_lines = sorted(list(set(h_lines)))
        header_h_lines = [y for y in unique_h_lines if y not in full_width_dividing_lines and y <= table_y0]
        if header_h_lines:
            header_y_max = max(header_h_lines) - 0.2
            header_y_min = max(table_bbox.y0 - 2.0 if table_bbox else table_y0 - 30.0, min(header_h_lines) - 15.0)
        else:
            header_y_max = table_y0 - 1.0
            header_y_min = max(table_bbox.y0 - 2.0 if table_bbox else table_y0 - 25.0, table_y0 - 25.0)

        if full_width_dividing_lines:
            header_y_min = max(header_y_min, max(full_width_dividing_lines) + 1.0)
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
        internal_lines = [l for l in unique_h_lines if min_word_y + 2.0 < l < max_word_y - 2.0]

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
            tiers = [header_words]
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
        # 1. 优先使用表头/表尾物理下划线确定的列划分 (Rule 2.1 - 2.3)
        header_cols = self._detect_columns_from_header_underlines(page, table_y0, table_bbox=table_bbox, words=words)
        if header_cols and len(header_cols) >= 2:
            # A currency marker normally starts an amount column. When it is
            # preceded by a percentage token in the same physical header
            # interval, it instead starts the following amount column.
            body_words = [
                word for word in (words or [])
                if (
                    str(word[4]).strip() == "$"
                    or re.match(r"^\$[\d(]", str(word[4]).strip())
                )
                and word[0] >= header_cols[1][0]
            ]
            original_cols = list(header_cols)
            for x0 in sorted({round(float(word[0]), 1) for word in body_words}):
                ci = next(
                    (i for i, (cx0, cx1) in enumerate(original_cols) if cx0 <= x0 <= cx1),
                    None,
                )
                if ci is None:
                    continue
                interval_words = [
                    word for word in (words or [])
                    if original_cols[ci][0] <= word[0] < original_cols[ci][1]
                ]
                has_percentage_before = any(
                    word[0] < x0 and "%" in str(word[4])
                    for word in interval_words
                )
                if has_percentage_before and ci < len(original_cols) - 1:
                    header_cols[ci] = (original_cols[ci][0], x0)
                    header_cols[ci + 1] = (x0, original_cols[ci + 1][1])
                elif ci > 0:
                    header_cols[ci - 1] = (original_cols[ci - 1][0], x0)
                    header_cols[ci] = (x0, original_cols[ci][1])
            return header_cols

        # 2. Background column intervals (e.g. zebra tables with per-column background rects)
        if page is not None:
            try:
                drawings = page.get_drawings()
                table_y_min = table_bbox.y0 if table_bbox else table_y0
                table_y_max = table_bbox.y1 if table_bbox else table_y0 + 200.0
                bg_rects = []
                for d in drawings:
                    fill = d.get("fill")
                    if fill and (self._is_color_match(fill, LIGHT_BLUE) or self._is_color_match(fill, WHITE)):
                        for it in d.get("items", []):
                            if it[0] == "re":
                                r = it[1]
                                if table_y_min - 5.0 <= (r.y0 + r.y1) / 2.0 <= table_y_max + 5.0 and r.height >= 4.0:
                                    if table_bbox is None or (table_bbox.x0 - 5.0 <= r.x0 and r.x1 <= table_bbox.x1 + 5.0):
                                        bg_rects.append(r)
                if bg_rects:
                    x_cuts = set()
                    for r in bg_rects:
                        x_cuts.add(round(r.x0, 1))
                        x_cuts.add(round(r.x1, 1))
                    sorted_cuts = sorted(list(x_cuts))
                    merged_cuts: List[float] = []
                    for xc in sorted_cuts:
                        if not merged_cuts:
                            merged_cuts.append(xc)
                        elif xc - merged_cuts[-1] > 2.0:
                            merged_cuts.append(xc)
                    if len(merged_cuts) >= 3:
                        bg_cols = [(merged_cuts[i], merged_cuts[i + 1]) for i in range(len(merged_cuts) - 1)]
                        return bg_cols
            except Exception:
                pass

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
        total_tbl_w = (table_bbox.x1 - table_bbox.x0) if table_bbox else ((max(w[2] for w in words) - min(w[0] for w in words)) if words else 500.0)
        for ry, rwords in rows_by_y.items():
            rwords.sort(key=lambda w: w[0])
            cur: List[Tuple] = []
            row_segs: List[Tuple[float, float]] = []
            for w in rwords:
                if not cur:
                    cur.append(w)
                else:
                    if w[0] - cur[-1][2] <= 6.0:
                        cur.append(w)
                    else:
                        row_segs.append((min(x[0] for x in cur), max(x[2] for x in cur)))
                        cur = [w]
            if cur:
                row_segs.append((min(x[0] for x in cur), max(x[2] for x in cur)))
            # 跨列大标题子词隔离（Rule 2.4 / 4.2）：整行单一且宽度超 45% 全表宽度的跨列短语不参与基础列连通融合
            if len(row_segs) == 1 and (row_segs[0][1] - row_segs[0][0]) > total_tbl_w * 0.45 and len(rows_by_y) > 1:
                continue
            line_segments.extend(row_segs)

        line_segments.sort(key=lambda s: s[0])
        col_spans: List[List[float]] = []
        for s in line_segments:
            if not col_spans:
                col_spans.append(list(s))
            else:
                merged = False
                for cs in col_spans:
                    if not (s[1] < cs[0] or s[0] > cs[1]):
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
            if prev_end < next_start:
                bk = (prev_end + next_start) / 2.0
            else:
                bk = prev_end + 1.5
            boundaries.append(bk)

        columns = []
        curr_x = table_x0
        for b in boundaries:
            columns.append((curr_x, b))
            curr_x = b
        columns.append((curr_x, table_x1))

        # 悬空间隙/全空列剪枝（Empty Column Pruning）：
        # 若某列在数据行或全表文字中文字出现率为 0（全空列），将其向左合并，消除表体悬空间隙
        words_to_check = []
        if data_rows:
            for dr in (data_rows or []):
                words_to_check.extend(dr.words)
        elif words:
            words_to_check = words

        if words_to_check and len(columns) > 2:
            col_counts = [0] * len(columns)
            for w in words_to_check:
                w_mid = (w[0] + w[2]) / 2.0
                for ci, (cx0, cx1) in enumerate(columns):
                    if cx0 - 2.0 <= w_mid <= cx1 + 2.0:
                        col_counts[ci] += 1
                        break
            pruned_cols: List[Tuple[float, float]] = []
            for ci, (cx0, cx1) in enumerate(columns):
                if col_counts[ci] == 0 and pruned_cols:
                    pruned_cols[-1] = (pruned_cols[-1][0], cx1)
                elif col_counts[ci] == 0 and not pruned_cols and ci + 1 < len(columns):
                    pass
                else:
                    pruned_cols.append((cx0, cx1))
            if len(pruned_cols) >= 2:
                if table_bbox:
                    pruned_cols[0] = (table_bbox.x0, pruned_cols[0][1])
                    pruned_cols[-1] = (pruned_cols[-1][0], table_bbox.x1)
                columns = pruned_cols

        # Currency is a hard cell anchor: an amount cell containing ``$`` must
        # include the symbol and its number.  Move the left boundary of that
        # numeric column to the symbol's left edge so a column cut can never
        # occur between ``$`` and the amount.
        body_words = [word for row in (data_rows or []) for word in row.words]
        dollar_words = [
            word for word in body_words
            if str(word[4]).strip() == "$" or str(word[4]).strip().startswith("$")
        ]
        for dollar in dollar_words:
            x0 = float(dollar[0])
            for ci, (cx0, cx1) in enumerate(columns):
                if cx0 <= x0 <= cx1:
                    if ci > 0:
                        columns[ci - 1] = (columns[ci - 1][0], x0)
                    columns[ci] = (x0, cx1)
                    break

        ci = 0
        while ci < len(columns) - 1:
            x0, x1 = columns[ci]
            tokens = [w[4].strip() for w in (words or []) if x0 <= w[0] < x1]
            if tokens and all(token == "$" for token in tokens):
                columns[ci] = (x0, columns[ci + 1][1])
                del columns[ci + 1]
            else:
                ci += 1
        # 确保列分界线严格单调递增且相邻列无缝相接，彻底清除旧列线残留
        clean_bounds = [table_x0]
        for c in columns[:-1]:
            b = c[1]
            if b > clean_bounds[-1] + 2.0:
                clean_bounds.append(b)
        clean_bounds.append(table_x1)
        if len(clean_bounds) >= 3:
            columns = [(clean_bounds[i], clean_bounds[i + 1]) for i in range(len(clean_bounds) - 1)]

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

        y_min_bound = table_bbox.y0 + 8.0 if table_bbox else table_y0 + 8.0
        y_max_bound = table_bbox.y1 - 4.0 if table_bbox else table_y0 + 600.0
        x_min_bound = table_bbox.x0 - 5.0 if table_bbox else -1e9
        x_max_bound = table_bbox.x1 + 5.0 if table_bbox else 1e9

        for d in drawings:
            for it in d.get("items", []):
                if it[0] == "l":
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 8.0:
                        y = p1.y
                        x0 = min(p1.x, p2.x)
                        x1 = max(p1.x, p2.x)
                        if y_min_bound <= y <= y_max_bound and x_min_bound <= (x0 + x1) / 2.0 <= x_max_bound:
                            h_lines.append((x0, x1, y))
                elif it[0] == "re":
                    r = it[1]
                    if r.height <= 2.0 and r.width >= 8.0:
                        y = r.y0
                        if y_min_bound <= y <= y_max_bound and x_min_bound <= (r.x0 + r.x1) / 2.0 <= x_max_bound:
                            h_lines.append((r.x0, r.x1, y))

        if not h_lines:
            return []

        table_x0 = table_bbox.x0 if table_bbox else (min(w[0] for w in words) if words else 30.0)
        table_x1 = table_bbox.x1 if table_bbox else (max(w[2] for w in words) if words else 600.0)
        table_w = table_x1 - table_x0

        # 1. 表头部分下划线检测 (排除从最左侧开始贯穿整张表格的整行底部分隔线)
        header_h_lines = [
            l for l in h_lines
            if table_x0 - 5.0 <= (l[0] + l[1]) / 2.0 <= table_x1 + 5.0
            and table_y0 - 2.0 <= l[2] <= table_y0 + 60.0
            and not (l[0] <= table_x0 + 5.0 and l[1] >= table_x1 - 5.0)
        ]
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
            col_segs = [s for s in merged if not (s[0] <= table_x0 + 5.0 and s[1] >= table_x1 - 5.0)]
            if col_segs:
                merged_by_y[y] = col_segs

        # 2. 如果表头部分没有下划线，表尾存在，则列的划分按照表尾进行划分
        if not merged_by_y:
            footer_h_lines = [
                l for l in h_lines
                if table_x0 - 5.0 <= (l[0] + l[1]) / 2.0 <= table_x1 + 5.0
                and l[2] > table_y0 + 50.0
                and not (l[0] <= table_x0 + 5.0 and l[1] >= table_x1 - 5.0)
            ]
            if footer_h_lines:
                sorted_footer = sorted(footer_h_lines, key=lambda l: l[0])
                merged_footer_segs: List[List[float]] = []
                for x0, x1, _ in sorted_footer:
                    if not merged_footer_segs:
                        merged_footer_segs.append([x0, x1])
                    else:
                        if x0 <= merged_footer_segs[-1][1] + 3.0:
                            merged_footer_segs[-1][1] = max(merged_footer_segs[-1][1], x1)
                        else:
                            merged_footer_segs.append([x0, x1])
                col_footer = [s for s in merged_footer_segs if not (s[0] <= table_x0 + 5.0 and s[1] >= table_x1 - 5.0)]
                if col_footer:
                    merged_by_y[table_y0 + 999.0] = col_footer

        t_words = [
            w for w in (words if words else [])
            if (table_bbox is None or (table_bbox.y0 - 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0 and table_bbox.x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 5.0))
        ]

        if merged_by_y:
            best_y = max(merged_by_y.keys(), key=lambda y: (len(merged_by_y[y]), -abs(y - table_y0)))
            best_segments = merged_by_y[best_y]
        else:
            return []

        if not best_segments:
            return []

        # 3. 宽下划线段内基于数据行留白通道的通用子列细分（Sub-column Decomposition）
        refined_col_spans = []
        data_words = [w for w in t_words if (w[1] + w[3]) / 2.0 >= best_y - 2.0]
        for s in sorted(best_segments, key=lambda s: s[0]):
            sx0, sx1 = s[0], s[1]
            sw = sx1 - sx0
            sub_words = [
                w for w in data_words
                if sx0 - 2.0 <= (w[0] + w[2]) / 2.0 <= sx1 + 2.0
                and (w[2] - w[0]) < sw * 0.8
            ]
            # 按行分组查找数据项垂直留白通道
            rows_sub = defaultdict(list)
            for w in sub_words:
                mid_y = (w[1] + w[3]) / 2.0
                matched_y = next((ey for ey in rows_sub if abs(mid_y - ey) <= 3.5), None)
                if matched_y is None:
                    matched_y = mid_y
                rows_sub[matched_y].append(w)

            gaps = []
            for ry, rwords in rows_sub.items():
                rwords.sort(key=lambda w: w[0])
                items = []
                cur = []
                for w in rwords:
                    if not cur:
                        cur.append(w)
                    else:
                        prev = cur[-1]
                        gap = w[0] - prev[2]
                        # 纯英文短语单词间距 <= 6.0pt 属于同一句子；只有包含数值或大间距 (gap >= 8.0pt) 才拆分为不同 item
                        if prev[4] == "$" and any(ch.isdigit() for ch in w[4]):
                            cur.append(w)
                        elif not any(ch.isdigit() for ch in prev[4]) and not any(ch.isdigit() for ch in w[4]) and gap <= 6.0:
                            cur.append(w)
                        elif gap <= 4.0:
                            cur.append(w)
                        else:
                            items.append((min(x[0] for x in cur), max(x[2] for x in cur)))
                            cur = [w]
                if cur:
                    items.append((min(x[0] for x in cur), max(x[2] for x in cur)))
                if len(items) >= 2:
                    for k in range(len(items) - 1):
                        gaps.append((items[k][1], items[k + 1][0]))

            gap_clusters = []
            for g in sorted(gaps, key=lambda g: (g[0] + g[1]) / 2.0):
                g_mid = (g[0] + g[1]) / 2.0
                gc = next((c for c in gap_clusters if abs(g_mid - sum((x[0] + x[1]) / 2.0 for x in c) / len(c)) <= 10.0), None)
                if gc is not None:
                    gc.append(g)
                else:
                    gap_clusters.append([g])

            valid_gap_clusters = [gc for gc in gap_clusters if len(gc) >= max(3, len(rows_sub) // 4)]
            if valid_gap_clusters:
                cuts = [sx0]
                for gc in valid_gap_clusters:
                    max_left = max(g[0] for g in gc)
                    min_right = min(g[1] for g in gc)
                    if max_left < min_right:
                        cuts.append((max_left + min_right) / 2.0)
                    else:
                        cuts.append(sum((g[0] + g[1]) / 2.0 for g in gc) / len(gc))
                cuts.append(sx1)
                for ci in range(len(cuts) - 1):
                    refined_col_spans.append([cuts[ci], cuts[ci + 1]])
            else:
                refined_col_spans.append([sx0, sx1])

        all_col_spans = refined_col_spans
        all_col_spans.sort(key=lambda s: s[0])

        # Footer/header rules may expose only the trailing numeric columns.
        # Preserve repeated text-aligned columns that precede that rule grid.
        underlined_first_x0 = all_col_spans[0][0]
        leading_spans = self._infer_repeated_leading_text_spans(
            t_words,
            first_col_x0=underlined_first_x0,
            table_y0=table_y0,
        )
        if len(leading_spans) >= 2:
            all_col_spans = leading_spans + all_col_spans

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

        # 行标签列与第 1 数据列的分界线：严格依据行标签最长文本右边缘与数据列左边缘之间的物理空白中点
        boundaries = []
        stub_words = [w for w in data_words if w[2] < first_col_x0 - 2.0 and any(ch.isalnum() for ch in w[4])]
        if stub_words:
            max_stub_x1 = max(w[2] for w in stub_words)
            b0 = (max_stub_x1 + first_col_x0) / 2.0
            boundaries.append(b0)

        for k in range(len(all_col_spans) - 1):
            col_k_span = all_col_spans[k]
            col_next_span = all_col_spans[k + 1]
            left_words = [w for w in data_words if col_k_span[0] - 2.0 <= (w[0] + w[2]) / 2.0 <= col_k_span[1] + 2.0]
            right_words = [w for w in data_words if col_next_span[0] - 2.0 <= (w[0] + w[2]) / 2.0 <= col_next_span[1] + 2.0]
            max_left_x1 = max([w[2] for w in left_words], default=col_k_span[1])
            min_right_x0 = min([w[0] for w in right_words], default=col_next_span[0])
            if max_left_x1 < min_right_x0:
                bk = (max_left_x1 + min_right_x0) / 2.0
            else:
                bk = (col_k_span[1] + col_next_span[0]) / 2.0
            boundaries.append(bk)

        columns = []
        curr_x = table_x0
        for b in sorted(boundaries):
            columns.append((curr_x, b))
            curr_x = b
        columns.append((curr_x, table_x1))

        # 规则指南第 56 条：多 $ 宽列自适应分裂与精准贴合（每一个 $ 的 x0 直接分裂为独立列）
        adj_columns = []
        for cx0, cx1 in columns:
            row_dollars_dict = defaultdict(list)
            for w in data_words:
                if w[4] == "$" and cx0 <= (w[0] + w[2]) / 2.0 < cx1:
                    mid_y = round((w[1] + w[3]) / 2.0 / 3.5)
                    row_dollars_dict[mid_y].append(w)
            multi_d_rows = [sorted(dw_list, key=lambda dw: dw[0]) for dw_list in row_dollars_dict.values() if len(dw_list) >= 2]
            if multi_d_rows:
                max_d_count = max(len(r) for r in multi_d_rows)
                split_cuts = [cx0]
                for d_idx in range(1, max_d_count):
                    dollars_at_idx = [r[d_idx] for r in multi_d_rows if len(r) > d_idx]
                    if dollars_at_idx:
                        min_x0 = min(dw[0] for dw in dollars_at_idx)
                        split_cuts.append(min_x0)
                split_cuts.append(cx1)
                sorted_cuts = sorted(list(set(split_cuts)))
                for i in range(len(sorted_cuts) - 1):
                    adj_columns.append((sorted_cuts[i], sorted_cuts[i + 1]))
            else:
                adj_columns.append((cx0, cx1))

        # 全空列与孤立货币符号列剪枝
        ci = 0
        while ci < len(adj_columns) - 1:
            cx0, cx1 = adj_columns[ci]
            col_w = cx1 - cx0
            col_tokens = [w[4].strip() for w in data_words if cx0 <= (w[0] + w[2]) / 2.0 < cx1]
            is_dollar_col = col_tokens and all(tok == "$" for tok in col_tokens)
            is_empty_col = not col_tokens
            if is_dollar_col or (col_w <= 15.0 and is_empty_col):
                adj_columns[ci + 1] = (cx0, adj_columns[ci + 1][1])
                del adj_columns[ci]
            else:
                ci += 1

        clean_bounds = [table_x0]
        for c in adj_columns[:-1]:
            b = c[1]
            if b > clean_bounds[-1] + 2.0:
                clean_bounds.append(b)
        clean_bounds.append(table_x1)
        if len(clean_bounds) >= 3:
            adj_columns = [(clean_bounds[i], clean_bounds[i + 1]) for i in range(len(clean_bounds) - 1)]

        return adj_columns



    @staticmethod
    def _infer_repeated_leading_text_spans(
        words: List[Tuple],
        first_col_x0: float,
        table_y0: float,
    ) -> List[List[float]]:
        """Find repeated text intervals before the first explicit rule column."""
        leading_words = [
            word
            for word in words
            if word[2] < first_col_x0 - 15.0
            and (word[1] + word[3]) / 2.0 >= table_y0 - 15.0
        ]
        if not leading_words:
            return []

        rows: List[List[Tuple]] = []
        for word in sorted(leading_words, key=lambda item: ((item[1] + item[3]) / 2.0, item[0])):
            mid_y = (word[1] + word[3]) / 2.0
            matched_row = None
            for row in rows:
                row_mid = sum((item[1] + item[3]) / 2.0 for item in row) / len(row)
                if abs(mid_y - row_mid) <= 3.5:
                    matched_row = row
                    break
            if matched_row is None:
                rows.append([word])
            else:
                matched_row.append(word)

        segments: List[Tuple[float, float, int]] = []
        for row_index, row in enumerate(rows):
            current = []
            for word in sorted(row, key=lambda item: item[0]):
                if current and word[0] - current[-1][2] > 6.0:
                    segments.append((current[0][0], current[-1][2], row_index))
                    current = []
                current.append(word)
            if current:
                segments.append((current[0][0], current[-1][2], row_index))

        clusters: List[Dict[str, object]] = []
        for x0, x1, row_index in sorted(segments):
            matched = None
            for cluster in clusters:
                if not (x1 < cluster["x0"] or x0 > cluster["x1"]):
                    matched = cluster
                    break
            if matched is None:
                clusters.append({"x0": x0, "x1": x1, "rows": {row_index}})
            else:
                matched["x0"] = min(matched["x0"], x0)
                matched["x1"] = max(matched["x1"], x1)
                matched["rows"].add(row_index)

        min_support = max(2, int(len(rows) * 0.15))
        repeated = [
            cluster
            for cluster in sorted(clusters, key=lambda item: item["x0"])
            if len(cluster["rows"]) >= min_support
        ]
        if len(repeated) < 2:
            return []

        cooccurring = [repeated[0]]
        for cluster in repeated[1:]:
            if any(
                len(cluster["rows"] & previous["rows"]) >= 2
                for previous in cooccurring
            ):
                cooccurring.append(cluster)
        if len(cooccurring) < 2:
            return []

        return [
            [float(cluster["x0"]), float(cluster["x1"])]
            for cluster in cooccurring
        ]

    @staticmethod
    def _infer_repeated_leading_text_spans(
        words: List[Tuple],
        first_col_x0: float,
        table_y0: float,
    ) -> List[List[float]]:
        """Find repeated text intervals before the first explicit rule column."""
        leading_words = [
            word
            for word in words
            if word[2] < first_col_x0 - 15.0
            and (word[1] + word[3]) / 2.0 >= table_y0 - 15.0
        ]
        if not leading_words:
            return []

        rows: List[List[Tuple]] = []
        for word in sorted(leading_words, key=lambda item: ((item[1] + item[3]) / 2.0, item[0])):
            mid_y = (word[1] + word[3]) / 2.0
            matched_row = None
            for row in rows:
                row_mid = sum((item[1] + item[3]) / 2.0 for item in row) / len(row)
                if abs(mid_y - row_mid) <= 3.5:
                    matched_row = row
                    break
            if matched_row is None:
                rows.append([word])
            else:
                matched_row.append(word)

        segments: List[Tuple[float, float, int]] = []
        for row_index, row in enumerate(rows):
            current = []
            for word in sorted(row, key=lambda item: item[0]):
                if current and word[0] - current[-1][2] > 6.0:
                    segments.append((current[0][0], current[-1][2], row_index))
                    current = []
                current.append(word)
            if current:
                segments.append((current[0][0], current[-1][2], row_index))

        clusters: List[Dict[str, object]] = []
        for x0, x1, row_index in sorted(segments):
            matched = None
            for cluster in clusters:
                if not (x1 < cluster["x0"] or x0 > cluster["x1"]):
                    matched = cluster
                    break
            if matched is None:
                clusters.append({"x0": x0, "x1": x1, "rows": {row_index}})
            else:
                matched["x0"] = min(matched["x0"], x0)
                matched["x1"] = max(matched["x1"], x1)
                matched["rows"].add(row_index)

        min_support = max(2, int(len(rows) * 0.15))
        repeated = [
            cluster
            for cluster in sorted(clusters, key=lambda item: item["x0"])
            if len(cluster["rows"]) >= min_support
        ]
        if len(repeated) < 2:
            return []

        cooccurring = [repeated[0]]
        for cluster in repeated[1:]:
            if any(
                len(cluster["rows"] & previous["rows"]) >= 2
                for previous in cooccurring
            ):
                cooccurring.append(cluster)
        if len(cooccurring) < 2:
            return []

        return [
            [float(cluster["x0"]), float(cluster["x1"])]
            for cluster in cooccurring
        ]

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

        # Promote an upper-level group label when the next header tier contains
        # multiple contiguous child columns beneath it.  The label's glyph box
        # is usually narrower than the group band, so text-overlap alone cannot
        # determine colspan (e.g. "Average Balance for the").
        for t in range(num_tiers - 1):
            next_nonempty = [
                c for c in rows_dict[sorted_row_indices[t + 1]] if c.text.strip()
            ]
            for top in rows_dict[sorted_row_indices[t]]:
                if not top.text.strip() or top.colspan > 1:
                    continue
                top_mid = (top.bbox.x0 + top.bbox.x1) / 2.0
                tier_children = [
                    c for c in next_nonempty
                    if c.bbox.y0 >= top.bbox.y1
                ]
                if not tier_children:
                    continue
                tier_children.sort(key=lambda c: c.col_index)
                runs: List[List[Cell]] = []
                for child in tier_children:
                    if not runs or child.col_index > runs[-1][-1].col_index + max(1, runs[-1][-1].colspan):
                        runs.append([child])
                    else:
                        runs[-1].append(child)
                run = next(
                    (r for r in runs
                     if columns[r[0].col_index][0] <= top_mid <= columns[r[-1].col_index + max(1, r[-1].colspan) - 1][1]),
                    None,
                )
                if not run:
                    continue
                child_start = run[0].col_index
                child_end = max(c.col_index + max(1, c.colspan) - 1 for c in run)
                covered = run
                if len(covered) < 2 or child_end <= child_start:
                    continue
                # Do not absorb a separately aligned left/stub label.
                band_x0 = columns[child_start][0]
                band_x1 = columns[child_end][1]
                if top_mid < band_x0 or top_mid > band_x1:
                    continue
                has_separator = any(
                    top.bbox.y1 - 2.0 <= ly <= run[0].bbox.y0 + 2.0
                    and not (lx1 < band_x0 + 3.0 or lx0 > band_x1 - 3.0)
                    for ly, lx0, lx1 in h_lines
                )
                if has_separator:
                    continue
                top.col_index = child_start
                top.colspan = child_end - child_start + 1
                top.bbox = BBox(top.bbox.x0, top.bbox.y0, top.bbox.x1, top.bbox.y1)

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

        self._promote_grouped_header_cells(all_cells, columns, num_h_rows)

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
            if header_rows or data_rows:
                for hr in header_rows:
                    raw_row_intervals.append((hr.y0, hr.y1))
                for dr in data_rows:
                    raw_row_intervals.append((dr.y0, dr.y1))
            else:
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

        # 1. 聚类行内水平短语 (Line phrases)
        sorted_words = sorted(words, key=lambda w: (round(w[1], 1), w[0]))
        line_clusters: List[List[Tuple]] = []
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

        phrases: List[List[Tuple]] = []
        for cl in line_clusters:
            cl.sort(key=lambda w: w[0])
            cur_p: List[Tuple] = []
            for w in cl:
                if not cur_p:
                    cur_p.append(w)
                else:
                    prev_w = cur_p[-1]
                    gap = w[0] - prev_w[2]
                    c_prev = next((ci for ci, c in enumerate(columns) if c[0] <= (prev_w[0] + prev_w[2]) / 2.0 < c[1]), -1)
                    c_curr = next((ci for ci, c in enumerate(columns) if c[0] <= (w[0] + w[2]) / 2.0 < c[1]), -1)
                    if is_header and gap <= 6.0:
                        cur_p.append(w)
                    elif c_prev == c_curr and gap <= 6.0:
                        cur_p.append(w)
                    elif c_prev == 0 and c_curr == 0 and gap <= 10.0:
                        cur_p.append(w)
                    else:
                        phrases.append(cur_p)
                        cur_p = [w]
            if cur_p:
                phrases.append(cur_p)

        # 2. 表头行处理 (Header rows)
        if is_header:
            merged_phrases: List[List[Tuple]] = []
            used = set()
            for i, p1 in enumerate(phrases):
                if i in used:
                    continue
                p1_x0 = min(w[0] for w in p1)
                p1_x1 = max(w[2] for w in p1)
                cur_words = list(p1)
                used.add(i)
                for j, p2 in enumerate(phrases):
                    if j in used:
                        continue
                    p2_x0 = min(w[0] for w in p2)
                    p2_x1 = max(w[2] for w in p2)
                    ov = min(p1_x1, p2_x1) - max(p1_x0, p2_x0)
                    min_w = min(p1_x1 - p1_x0, p2_x1 - p2_x0)
                    if min_w > 0 and (ov >= 0.5 * min_w):
                        cur_words.extend(p2)
                        used.add(j)
                        p1_x0 = min(p1_x0, p2_x0)
                        p1_x1 = max(p1_x1, p2_x1)
                merged_phrases.append(cur_words)
            phrases = merged_phrases

            col_assigned_phrases: Dict[int, List[List[Tuple]]] = defaultdict(list)
            spanning_phrases: List[Tuple[List[Tuple], int, int]] = []

            for p in phrases:
                px0 = min(w[0] for w in p)
                px1 = max(w[2] for w in p)
                pmid = (px0 + px1) / 2.0

                # 判定短语覆盖的基础列区间 [sc, ec]
                sc = next((ci for ci, c in enumerate(columns) if c[0] <= px0 < c[1]), None)
                if sc is None:
                    sc = next((ci for ci, c in enumerate(columns) if c[0] <= pmid < c[1]), 0)

                ec = sc
                for ci in range(sc, len(columns)):
                    if px1 > columns[ci][0] + 5.0:
                        ec = ci

                # 严禁吸收最左侧行标签列
                if sc == 0 and ec > 0 and len(columns) > 1:
                    # 如果不是整表通栏标题，则将行标签与右侧分开
                    other_data_p = [op for op in phrases if op is not p and min(w[0] for w in op) >= columns[1][0] - 5.0]
                    if other_data_p:
                        ec = 0

                if ec > sc and sc > 0:
                    # 检查此区间内是否有并列的其他短语
                    other_in_band = any(
                        op is not p and (sc <= next((ci for ci, c in enumerate(columns) if c[0] <= (min(w[0] for w in op) + max(w[2] for w in op)) / 2.0 < c[1]), -1) <= ec)
                        for op in phrases
                    )
                    if not other_in_band:
                        spanning_phrases.append((p, sc, ec))
                        continue

                # 默认归入中心所在的单列
                best_ci = next((ci for ci, c in enumerate(columns) if c[0] <= pmid < c[1]), sc)
                col_assigned_phrases[best_ci].append(p)

            cells = []
            covered_cols = set()

            for p, sc, ec in spanning_phrases:
                colspan = ec - sc + 1
                for ci in range(sc, sc + colspan):
                    covered_cols.add(ci)
                p.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                txt = " ".join(w[4] for w in p).strip()
                txt = re.sub(r'\$\s+', '$', txt)
                cells.append(Cell(
                    text=txt,
                    row_index=row_idx,
                    col_index=sc,
                    colspan=colspan,
                    rowspan=1,
                    bbox=BBox(columns[sc][0], row_y0, columns[ec][1], row_y1),
                ))

            for ci in range(len(columns)):
                if ci in covered_cols:
                    continue
                phr_list = col_assigned_phrases.get(ci, [])
                if phr_list:
                    all_col_words = [w for phr in phr_list for w in phr]
                    all_col_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                    txt = " ".join(w[4] for w in all_col_words).strip()
                    txt = re.sub(r'\$\s+', '$', txt)
                    cells.append(Cell(
                        text=txt,
                        row_index=row_idx,
                        col_index=ci,
                        colspan=1,
                        rowspan=1,
                        bbox=BBox(columns[ci][0], row_y0, columns[ci][1], row_y1),
                    ))
                else:
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

        # 3. 数据行处理 (Body rows)
        # 检查是否为通栏标题行（只有 1 个短语且无右侧数据）
        if len(phrases) == 1 and len(columns) > 1:
            p = phrases[0]
            txt = " ".join(w[4] for w in p).strip()
            # 若不是纯数值
            if not re.match(r'^\$?\(?-?\d+[\d,\.]*\)?%?$', txt) and not any(ch.isdigit() for ch in txt):
                px0 = min(w[0] for w in p)
                if px0 < columns[1][0] + 10.0:
                    return [
                        Cell(
                            text=txt,
                            row_index=row_idx,
                            col_index=0,
                            colspan=len(columns),
                            rowspan=1,
                            bbox=BBox(columns[0][0], row_y0, columns[-1][1], row_y1),
                        )
                    ]

        # 逐列分配数据词
        col_words: Dict[int, List[Tuple]] = defaultdict(list)
        for w in words:
            w_mid = (w[0] + w[2]) / 2.0
            ci = next((i for i, c in enumerate(columns) if c[0] <= w_mid < c[1]), None)
            if ci is None:
                ci = 0 if w_mid < columns[0][0] else (len(columns) - 1)
            col_words[ci].append(w)

        cells = []
        for ci in range(len(columns)):
            cws = col_words.get(ci, [])
            if cws:
                cws.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                dollar_words = [w for w in cws if w[4] == '$']
                non_dollar_words = [w for w in cws if w[4] != '$']
                ordered_w = dollar_words + non_dollar_words if (dollar_words and non_dollar_words) else cws
                cell_text = " ".join(w[4] for w in ordered_w)
                cell_text = re.sub(r'(\d+,\d+)\s+(\d+)', r'\1\2', cell_text)
                cell_text = re.sub(r'(\(\d+,\d+)\s+(\d+)', r'\1\2', cell_text)
                cell_text = re.sub(r'\$\s+', '$', cell_text)
                cell_text = re.sub(r'\s+\)', ')', cell_text)
                cell_text = re.sub(r'\(\s+', '(', cell_text)
                cell_text = re.sub(r'\s+%', '%', cell_text)
                cells.append(Cell(
                    text=cell_text.strip(),
                    row_index=row_idx,
                    col_index=ci,
                    colspan=1,
                    rowspan=1,
                    bbox=BBox(columns[ci][0], row_y0, columns[ci][1], row_y1),
                ))
            else:
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
