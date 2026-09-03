"""English wireless table extraction strategies."""

from __future__ import annotations

import copy
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import fitz

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.base_table_extractor import BaseTableExtractor
from hexai_pdf_parser.extractors.language_detector import detect_page_language
from hexai_pdf_parser.tables.wireless_table_recovery import recover_wireless_tables
from hexai_pdf_parser.tables.wireless_structure import continuations


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
    def _is_invisible_drawing(d: dict) -> bool:
        """判断 drawing 是否为不可见的纯白填充矩形、纯白线条或透明元素。"""
        fill = d.get("fill")
        color = d.get("color")
        is_white_fill = False
        if fill is not None:
            if isinstance(fill, (tuple, list)) and len(fill) >= 3 and all(c >= 0.98 for c in fill[:3]):
                is_white_fill = True
            elif isinstance(fill, (int, float)) and fill >= 0.98:
                is_white_fill = True

        is_white_color = False
        if color is not None:
            if isinstance(color, (tuple, list)) and len(color) >= 3 and all(c >= 0.98 for c in color[:3]):
                is_white_color = True
            elif isinstance(color, (int, float)) and color >= 0.98:
                is_white_color = True

        # 无 stroke 且 fill 为白
        if color is None and is_white_fill:
            return True
        # stroke 与 fill 均为白
        if is_white_color and (fill is None or is_white_fill):
            return True
        # 透明度为 0
        if d.get("fill_opacity") == 0 and d.get("stroke_opacity") == 0:
            return True
        return False

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
        if header_rows < 2 or not cells:
            return
        for row_index in range(header_rows - 1):
            upper = [c for c in cells if c.row_index == row_index and c.text.strip()]
            lower = sorted([c for c in cells if c.row_index == row_index + 1 and c.text.strip()], key=lambda c: c.col_index)
            if len(upper) != 1 or len(lower) < 2:
                continue
            title = upper[0]
            peer_boxes = []
            supported_cols = {ci for c in lower for ci in range(c.col_index, c.col_index + max(1, c.colspan))}

            col_content_extents: List[Optional[Tuple[float, float]]] = [None] * len(columns)
            for c in lower:
                if c.col_index < len(columns):
                    for ci in range(c.col_index, min(len(columns), c.col_index + max(1, c.colspan))):
                        col_content_extents[ci] = (c.bbox.x0, c.bbox.x1)

            span_res = EnglishTableExtractor._infer_centered_parent_header_span(
                px0=title.bbox.x0,
                px1=title.bbox.x1,
                peer_boxes=peer_boxes,
                columns=columns,
                col_content_extents=col_content_extents,
                supported_cols=supported_cols,
            )
            if span_res is not None:
                start, colspan = span_res
                end = start + colspan
                title.col_index = start
                title.colspan = colspan
                title.bbox = BBox(columns[start][0], title.bbox.y0, columns[end - 1][1], title.bbox.y1)
                covered_cols = set(range(start, end))
                to_remove = [
                    c for c in cells
                    if c.row_index == row_index and c is not title and c.col_index in covered_cols
                ]
                for c in to_remove:
                    cells.remove(c)
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
                    if table_bbox.x0 - 2.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 2.0 and table_bbox.y0 - 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0:
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

        # 提取页面水平线段与斑马背景色块用于行划分、子表格划分与表头层级判定
        drawings = page.get_drawings() if page else []
        h_lines: List[Tuple[float, float, float]] = []
        zebra_bands: List[Tuple[float, float, float, float]] = []
        for d in drawings:
            if self._is_invisible_drawing(d):
                continue
            fill = d.get("fill")
            for it in d.get("items", []):
                if it[0] in ("l", "re"):
                    y = it[1].y if it[0] == "l" else it[1].y0
                    w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                    h = abs(it[2].y - it[1].y) if it[0] == "l" else it[1].height
                    x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                    x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                    if h <= 3.0 and w >= 2.0:
                        is_hyperlink = fill is not None and len(fill) >= 3 and (fill[2] > 0.6 and fill[0] < 0.3 and fill[1] < 0.3)
                        if not is_hyperlink:
                            h_lines.append((round(y, 1), round(x0, 1), round(x1, 1)))
                    elif it[0] == "re" and h >= 5.0 and w >= 50.0 and fill is not None and fill != (1.0, 1.0, 1.0):
                        zebra_bands.append((round(x0, 1), round(it[1].y0, 1), round(x1, 1), round(it[1].y1, 1)))

        # 1. 行的确定 (Y轴): 动态字高与垂直重叠度自适应聚类
        word_heights = [w[3] - w[1] for w in t_words if w[3] > w[1]]
        avg_line_h = sum(word_heights) / len(word_heights) if word_heights else 10.0

        t_words.sort(key=lambda w: (w[1], w[0]))
        rows_words: List[List[Tuple]] = []
        for w in t_words:
            w_mid_y = (w[1] + w[3]) / 2.0
            matched = False
            for rw in rows_words:
                rw_y0 = min(lw[1] for lw in rw)
                rw_y1 = max(lw[3] for lw in rw)
                rw_mid_y = sum((lw[1] + lw[3]) / 2.0 for lw in rw) / len(rw)

                # 斑马底色块约束：同底色块文字天然聚类为同一行，跨底色块严格禁止合并
                in_same_band = any(
                    by0 <= min(w[1], rw_y0) and max(w[3], rw_y1) <= by1
                    for bx0, by0, bx1, by1 in zebra_bands
                )
                across_bands = any(
                    (by0 <= w_mid_y <= by1) != (by0 <= rw_mid_y <= by1)
                    for bx0, by0, bx1, by1 in zebra_bands
                )
                if across_bands:
                    continue

                # 垂直空间重叠判定 (Vertical Interval Overlap)：重叠高度超过字高 40%，或属于同一底色块
                v_overlap = max(0.0, min(w[3], rw_y1) - max(w[1], rw_y0))

                # 物理横线硬阻断检查：仅当文字块垂直空间分离（非同一行水平相邻词）且横线切实穿过其上下垂直间距时才阻断
                has_sep_line = (
                    v_overlap < min(w[3] - w[1], rw_y1 - rw_y0) * 0.35
                    and any(
                        min(rw_y1, w[3]) - 1.0 <= ly <= max(rw_y0, w[1]) + 1.0
                        and max(w[0], min(lw[0] for lw in rw)) < lx1
                        and min(w[2], max(lw[2] for lw in rw)) > lx0
                        for ly, lx0, lx1 in h_lines
                    )
                )
                if has_sep_line:
                    continue

                is_same_line = in_same_band or (v_overlap >= min(w[3] - w[1], rw_y1 - rw_y0) * 0.4) or abs(w_mid_y - rw_mid_y) < avg_line_h * 0.35

                if is_same_line:
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
        blocks = page.get_text("blocks") if page else []
        if table_bbox is None and len(header_underline_ys) > 1:
            prev_hy = header_underline_ys[0]
            for hy in header_underline_ys[1:]:
                # 纯几何拓扑判定：只有当两段下划线之间存在大段正文段落阻隔，或两区域垂直留白 >= 40pt 且列结构发生本质突变时才切分子表格
                if hy - prev_hy < 40.0:
                    continue
                target_r = None
                for r_idx in range(len(rows_words)):
                    r_y1 = max(w[3] for w in rows_words[r_idx])
                    if r_y1 < hy:
                        target_r = r_idx
                    else:
                        break
                if target_r is not None and target_r > 0:
                    # 纯几何拓扑判定：检查两段下划线之间是否存在连续排版的正文段落（Prose Paragraph Block）
                    # 正文段落的纯几何特征：宽度大（>= 45% 表格宽），垂直居中于两下划线之间，且词间距紧凑均匀（最大水平词间隙 < 15pt，无多列离散间隙）
                    has_paragraph_between = False
                    for b in blocks:
                        if not b[4].strip():
                            continue
                        by_mid = (b[1] + b[3]) / 2.0
                        if prev_hy + 2.0 <= by_mid <= hy - 2.0 and (b[2] - b[0]) >= (tb_x1 - tb_x0) * 0.45:
                            b_words = [w for w in t_words if b[1] - 1.0 <= (w[1] + w[3]) / 2.0 <= b[3] + 1.0 and b[0] - 1.0 <= (w[0] + w[2]) / 2.0 <= b[2] + 1.0]
                            b_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                            # 检查同一行内的词间隙
                            has_wide_col_gap = False
                            for rw_idx in range(len(b_words) - 1):
                                if abs(b_words[rw_idx][1] - b_words[rw_idx + 1][1]) <= 3.0:
                                    gap = b_words[rw_idx + 1][0] - b_words[rw_idx][2]
                                    if gap >= 25.0:
                                        has_wide_col_gap = True
                                        break
                            if not has_wide_col_gap and len(b_words) >= 12:
                                has_paragraph_between = True
                                break
                    
                    if has_paragraph_between:
                        # 查找新表头的首行 (向上查找首个与正文段落有明显垂直间隙且处于新表头区域的行)
                        split_r = target_r
                        for r in range(target_r, max(0, target_r - 3), -1):
                            r_words = rows_words[r]
                            if min(w[1] for w in r_words) >= prev_hy + 20.0:
                                split_r = r
                        if split_r not in split_indices and split_r > split_indices[-1]:
                            split_indices.append(split_r)
                            prev_hy = hy

        split_indices.append(len(rows_words))

        tables_out: List[Table] = []
        for s_i in range(len(split_indices) - 1):
            sub_rows = rows_words[split_indices[s_i]:split_indices[s_i + 1]]
            sub_words = [w for rw in sub_rows for w in rw]
            sub_y0 = max(0.0, min(w[1] for w in sub_words) - 2.0)
            sub_y1 = max(w[3] for w in sub_words) + 2.0
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

                    prev_x0 = min(w[0] for w in prev_row)
                    prev_x1 = max(w[2] for w in prev_row)
                    cur_x0 = min(w[0] for w in cur_row)
                    cur_x1 = max(w[2] for w in cur_row)

                    has_line_between = any(
                        prev_y1 - 1.5 <= l[0] <= cur_y0 + 1.5
                        and (
                            (l[1] <= min(prev_x1, cur_x1) + 15.0 and l[2] >= max(prev_x0, cur_x0) - 15.0)
                            or (l[1] <= prev_x0 + 15.0 and l[2] >= prev_x1 - 15.0)
                            or (l[1] <= cur_x0 + 15.0 and l[2] >= cur_x1 - 15.0)
                        )
                        for l in lines_in_table
                    )
                    if has_line_between:
                        merged_sub_rows.append(cur_row)
                        continue

                    is_inside_block = any(b[1] + 1.0 < boundary_y < b[3] - 1.0 for b in table_blocks)

                    col0_limit = sub_bbox.x0 + min(60.0, (sub_bbox.x1 - sub_bbox.x0) * 0.25)
                    prev_has_c0 = any(w[0] < col0_limit for w in prev_row)
                    cur_has_c0 = any(w[0] < col0_limit for w in cur_row)

                    across_zebra_boundary = any(
                        (by0 - 1.0 <= min(w[1] for w in prev_row) and prev_y1 <= by1 + 1.0) != (by0 - 1.0 <= cur_y0 and max(w[3] for w in cur_row) <= by1 + 1.0)
                        for bx0, by0, bx1, by1 in zebra_bands
                    )

                    is_cut = is_inside_block and not (prev_has_c0 and cur_has_c0) and not across_zebra_boundary

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
            # 纯几何提取表头分级水平物理线：
            # 只要标题存在下划线，且在数据行起始位置之前，所有下划线天然构成各层表头的物理分界线
            data_row_y_min = sub_bbox.y1
            rows_by_y = defaultdict(list)
            for w in sub_words:
                mid_y = (w[1] + w[3]) / 2.0
                matched_y = next((ey for ey in rows_by_y if abs(mid_y - ey) <= 3.5), None)
                if matched_y is None:
                    matched_y = mid_y
                rows_by_y[matched_y].append(w)

            def is_fin_metric(tok: str) -> bool:
                t = tok.strip()
                if not t or t in ("$", "%", "—", "-", "--", "n/m"):
                    return False
                if len(re.findall(r'[a-zA-Z]', t)) >= 3:
                    return False
                if "%" in t and any(ch.isdigit() for ch in t):
                    return True
                if "$" in t and any(ch.isdigit() for ch in t):
                    return True
                if t.startswith("(") and t.endswith(")") and any(ch.isdigit() for ch in t):
                    inner = t[1:-1].strip(" ,.")
                    if inner.isdigit() and len(inner) <= 2 and int(inner) <= 10:
                        return False
                    return True
                if "," in t and any(ch.isdigit() for ch in t):
                    clean = re.sub(r'[^\d]', '', t)
                    if clean.isdigit() and (len(clean) > 2 or int(clean) > 31):
                        return True
                if t.isdigit():
                    val = int(t)
                    if val not in range(1990, 2040) and val not in range(1, 32):
                        return True
                return False

            for ry, rwords in sorted(rows_by_y.items(), key=lambda item: item[0]):
                metric_count = sum(1 for w in rwords if is_fin_metric(w[4]))
                if metric_count >= 2:
                    data_row_y_min = ry
                    break

            header_line_levels = []
            sub_w = sub_bbox.x1 - sub_bbox.x0
            sub_h = sub_bbox.y1 - sub_bbox.y0
            max_header_y = sub_y0 + max(40.0, sub_h * 0.35)
            for y, segs in sorted(sub_fused_lines_by_y.items(), key=lambda item: item[0]):
                if y >= data_row_y_min - 1.0 or y > max_header_y or len(header_line_levels) >= 3:
                    break
                if len(segs) >= 2 or max(s[1] for s in segs) - min(s[0] for s in segs) >= 25.0:
                    header_line_levels.append(y)
                    min_x = min(s[0] for s in segs)
                    max_w = max(s[1] for s in segs) - min(s[0] for s in segs)
                    if min_x <= sub_bbox.x0 + 15.0 and max_w >= sub_w * 0.85:
                        break

            if header_line_levels:
                # 原则 2：两道下划线之间合并为一个表头层级；原则 3：顶部边界到第一道下划线区域合并为顶层表头
                header_bottom_y = header_line_levels[-1]
                header_sub_rows = []
                for k in range(len(header_line_levels)):
                    y_min = header_line_levels[k - 1] if k > 0 else sub_y0 - 2.0
                    y_max = header_line_levels[k]
                    tier_words = [w for w in sub_words if y_min < (w[1] + w[3]) / 2.0 <= y_max]
                    tier_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                    if tier_words:
                        header_sub_rows.append(tier_words)
                body_sub_rows = [rw for rw in sub_rows if (sum((w[1] + w[3]) / 2.0 for w in rw) / len(rw)) > header_bottom_y]
            else:
                # 保持天然物理行 (Natural Physical Rows)，表头层级数由数据区首行之前的天然行数决定
                header_row_list = [rw for rw in sub_rows if (sum((w[1] + w[3]) / 2.0 for w in rw) / len(rw)) < data_row_y_min - 1.5]
                if not header_row_list or len(header_row_list) >= len(sub_rows):
                    first_row_metrics = sum(1 for w in sub_rows[0] if is_fin_metric(w[4]))
                    if first_row_metrics >= 2:
                        header_tier_count = 0
                    else:
                        header_tier_count = 1 if len(sub_rows) > 1 else 0
                else:
                    header_tier_count = min(2, len(header_row_list))
                header_sub_rows = sub_rows[:header_tier_count]
                body_sub_rows = sub_rows[header_tier_count:]

            # 统一封装为 _RowData 结构，表头与表体分别标记
            header_rows_data = [
                _RowData(
                    words=rw,
                    y0=min(w[1] for w in rw),
                    y1=max(w[3] for w in rw),
                    color=None,
                    is_header=True,
                )
                for rw in header_sub_rows if rw
            ]
            data_rows_data = [
                _RowData(
                    words=rw,
                    y0=min(w[1] for w in rw),
                    y1=max(w[3] for w in rw),
                    color=None,
                    is_header=False,
                )
                for rw in body_sub_rows if rw
            ]

            # 统一委托 _build_wireless_table 执行网格生成、表头跨列规范化与二维闭合网格物化
            t = self._build_wireless_table(
                header_rows=header_rows_data,
                data_rows=data_rows_data,
                columns=columns,
                confidence=confidence,
                table_bbox=sub_bbox,
                page=page,
                source="english_general_wireless",
            )
            if t is not None:
                tables_out.append(t)

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
                    if table_bbox.x0 - 2.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 2.0 and table_bbox.y0 - 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0:
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
            if not filtered_bgs:
                return []
            tables_bg = [filtered_bgs]
        else:
            tables_bg = self._group_into_tables(row_backgrounds)

        tables: List[Table] = []
        for bg_group in tables_bg:
            colored_bgs = [bg for bg in bg_group if bg[2] != "white"]
            if not colored_bgs:
                continue

            last_colored_y = max(bg[1] for bg in colored_bgs)
            max_allowed_bottom = table_bbox.y1 + 5.0 if table_bbox else last_colored_y + 15.0
            data_bgs = [
                bg for bg in bg_group
                if bg[0] < max(last_colored_y + 1.0, max_allowed_bottom - 2.0) and bg[1] <= max_allowed_bottom
            ]
            if not data_bgs:
                continue

            filled_bgs = []
            for i, bg in enumerate(data_bgs):
                if i > 0:
                    prev_y1 = filled_bgs[-1][1]
                    cur_y0 = bg[0]
                    gap = cur_y0 - prev_y1
                    if 3.5 <= gap <= 25.0:
                        filled_bgs.append((prev_y1, cur_y0, "white"))
                    elif gap > 25.0:
                        gap_words = [w for w in page.get_text("words") if prev_y1 + 1.0 <= (w[1] + w[3]) / 2.0 <= cur_y0 - 1.0]
                        if gap_words:
                            gap_rows = defaultdict(list)
                            for w in gap_words:
                                mid_y = (w[1] + w[3]) / 2.0
                                matched_y = next((ey for ey in gap_rows if abs(mid_y - ey) <= 3.5), None)
                                if matched_y is None:
                                    matched_y = mid_y
                                gap_rows[matched_y].append(w)
                            sorted_rys = sorted(gap_rows.keys())
                            cur_top = prev_y1
                            for k, ry in enumerate(sorted_rys):
                                next_top = (ry + sorted_rys[k + 1]) / 2.0 if k < len(sorted_rys) - 1 else cur_y0
                                filled_bgs.append((cur_top, next_top, "white"))
                                cur_top = next_top
                        else:
                            filled_bgs.append((prev_y1, cur_y0, "white"))
                filled_bgs.append(bg)

            # Check if there's a bottom white zebra row after last filled band
            last_filled_y1 = filled_bgs[-1][1] if filled_bgs else last_colored_y
            if table_bbox and table_bbox.y1 > last_filled_y1 + 4.0:
                words = page.get_text("words")
                bot_words = [w for w in words if last_filled_y1 + 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0]
                if bot_words:
                    filled_bgs.append((last_filled_y1, table_bbox.y1, "white"))

            t = self._process_zebra_group(page, filled_bgs, table_bbox, confidence)
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
        first_band = bg_group[0]
        colored_bgs = [b for b in bg_group if b[2] != "white"]
        if colored_bgs and first_band[2] == "white" and (first_band[1] - first_band[0]) > 18.0:
            table_y0 = first_band[1]
            data_bgs = bg_group[1:]
        else:
            table_y0 = min(bg[0] for bg in bg_group)
            data_bgs = bg_group
        table_y1 = max(bg[1] for bg in data_bgs)
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

        data_rows = self._assign_words_to_zebra_rows(data_words, data_bgs)

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

        source = "ml_detection" if table_bbox else "english_color_based"
        return self._build_wireless_table(
            header_rows=header_rows,
            data_rows=data_rows,
            columns=columns,
            confidence=confidence,
            table_bbox=table_bbox,
            page=page,
            source=source,
        )

    def _merge_wrapped_label_rows(
        self,
        data_rows: List["_RowData"],
        page: Optional[fitz.Page],
        table_bbox: Optional[BBox],
    ) -> List["_RowData"]:
        """合并因折行标签文本被斑马色块边界切断的相邻两行（Rule 4.4）。

        判定条件（纯几何，不依赖业务文字）：
        1. 相邻两行的分界线（mid_y）穿透某 text block（block.y0 + 1 < mid_y < block.y1 - 1）；
        2. 两行之间无物理水平横线；
        3. 不是两行都有数值（否则是独立数据行之间的正常切分）；
        4. text block 高度 <= 40pt（避免误合并跨越大段落的情况）。
        合并结果：两行的 words 合并，y0/y1 取外包，color 保留上一行，is_header 不变。
        """
        if len(data_rows) < 2 or page is None:
            return data_rows

        # 获取页面 text blocks 和物理横线
        try:
            blocks = page.get_text("blocks")
        except Exception:
            return data_rows

        # 过滤出表格区域内的 text blocks
        if table_bbox:
            table_blocks = [
                b for b in blocks
                if b[4].strip()
                and b[0] < table_bbox.x1 + 5.0 and b[2] > table_bbox.x0 - 5.0
                and b[1] < table_bbox.y1 + 5.0 and b[3] > table_bbox.y0 - 5.0
            ]
        else:
            table_blocks = [b for b in blocks if b[4].strip()]

        # 获取物理水平横线 y 坐标集合
        h_line_ys: List[float] = []
        try:
            for d in page.get_drawings():
                if self._is_invisible_drawing(d):
                    continue
                for it in d.get("items", []):
                    if it[0] in ("l", "re"):
                        h = 0.0 if it[0] == "l" else it[1].height
                        w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                        y = it[1].y if it[0] == "l" else (it[1].y0 + it[1].y1) / 2.0
                        if h <= 2.5 and w >= 15.0:
                            h_line_ys.append(round(y, 2))
        except Exception:
            pass

        merged: List["_RowData"] = [data_rows[0]]
        for cur in data_rows[1:]:
            prev = merged[-1]
            # 相邻两行的分界中点
            mid_y = (prev.y1 + cur.y0) / 2.0

            # 条件 2：两行之间有物理横线 → 强制保留分割
            has_line_between = any(
                prev.y1 - 1.5 <= hl <= cur.y0 + 1.5
                for hl in h_line_ys
            )
            if has_line_between:
                merged.append(cur)
                continue

            # 条件 3：两行都有数值 → 独立数据行，不合并
            def _has_numeric(row: "_RowData") -> bool:
                return any(any(ch.isdigit() for ch in w[4]) for w in row.words)

            if _has_numeric(prev) and _has_numeric(cur):
                merged.append(cur)
                continue

            # 条件 1：mid_y 穿透某 text block 且两行之间无物理横线与数值冲突
            is_cut = any(
                b[1] + 1.0 < mid_y < b[3] - 1.0
                for b in table_blocks
            )
            if is_cut:
                # 合并：words 合并后按 (y, x) 重排，y0/y1 取外包，保留上一行 color
                combined_words = sorted(
                    prev.words + cur.words,
                    key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0]),
                )
                merged[-1] = _RowData(
                    words=combined_words,
                    y0=min(prev.y0, cur.y0),
                    y1=max(prev.y1, cur.y1),
                    color=prev.color,
                    is_header=prev.is_header,
                )
            else:
                merged.append(cur)

        return merged

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
                    if r.height <= 80.0:
                        colored_rects.append([r.y0, r.y1, "colored"])
            elif _is_white(fill):
                for r in rect_list:
                    if r.height <= 40.0:
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
                    if self._is_invisible_drawing(d):
                        continue
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

        # 首先基于 words 初步界定表头文字区间与实际表格宽度
        header_y_max = table_y0 - 0.5
        header_y_min = table_bbox.y0 - 2.0 if table_bbox else (table_y0 - 50.0)
        cand_header_words = [
            w for w in words
            if header_y_min <= (w[1] + w[3]) / 2.0 <= header_y_max
        ]
        if table_bbox:
            cand_header_words = [
                w for w in cand_header_words
                if table_bbox.x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 5.0
            ]
        table_x0 = table_bbox.x0 if table_bbox else (min(w[0] for w in cand_header_words) if cand_header_words else 0.0)
        table_x1 = table_bbox.x1 if table_bbox else (max(w[2] for w in cand_header_words) if cand_header_words else 600.0)
        table_w = max(50.0, table_x1 - table_x0)

        h_lines = []
        full_width_dividing_lines = []
        for y, segs in lines_by_y.items():
            sorted_segs = sorted(segs, key=lambda s: s[0])
            merged_segs = []
            for s in sorted_segs:
                if not merged_segs:
                    merged_segs.append(list(s))
                else:
                    if s[0] <= merged_segs[-1][1] + 2.0:
                        merged_segs[-1][1] = max(merged_segs[-1][1], s[1])
                    else:
                        merged_segs.append(list(s))
            tot_w = sum(s[1] - s[0] for s in merged_segs)
            is_full_width_line = any(
                (s[0] <= table_x0 + 15.0 and s[1] >= table_x1 - 15.0) or (s[1] - s[0] >= table_w * 0.70)
                for s in merged_segs
            )
            # 过滤表体内部紧贴文字底部的文本超链接划线
            if len(merged_segs) < 2 and y > table_y0 + 20.0 and not is_full_width_line:
                tight_words = [
                    w for w in words
                    if abs((w[1] + w[3]) / 2.0 - y) <= 6.0
                    and not (w[2] < merged_segs[0][0] - 5.0 or w[0] > merged_segs[-1][1] + 5.0)
                ]
                if tight_words:
                    w_y1 = max(w[3] for w in tight_words)
                    if abs(y - w_y1) <= 3.0:
                        continue

            if len(merged_segs) >= 2 or tot_w >= 20.0:
                h_lines.append(y)
            if is_full_width_line and y < table_y0 - 10.0:
                if not table_bbox or y < table_bbox.y0:
                    full_width_dividing_lines.append(y)

        unique_h_lines = sorted(list(set(h_lines)))
        header_h_lines = [y for y in unique_h_lines if y not in full_width_dividing_lines and y <= table_y0]
        header_h_lines_above = [y for y in header_h_lines if y < table_y0 - 3.0]
        if table_bbox:
            header_y_min = table_bbox.y0 - 2.0
        elif header_h_lines_above:
            header_y_min = max(table_y0 - 50.0, min(header_h_lines_above) - 20.0)
        else:
            header_y_min = table_y0 - 50.0

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

        dividing_lines = sorted(list(set(
            y for y in unique_h_lines
            if min_word_y + 3.0 < y < table_y0 - 3.0
        )))
        if not dividing_lines and header_h_lines:
            dividing_lines = sorted(list(set(
                y for y in header_h_lines
                if min_word_y + 3.0 < y <= table_y0
            )))

        if dividing_lines:
            tier_rows_dict = defaultdict(list)
            for w in header_words:
                w_yc = (w[1] + w[3]) / 2.0
                tier_idx = sum(1 for ly in dividing_lines if w_yc > ly)
                tier_rows_dict[tier_idx].append(w)

            header_rows = []
            for t_idx in sorted(tier_rows_dict.keys()):
                tw = tier_rows_dict[t_idx]
                tw.sort(key=lambda w: ((w[1] + w[3]) / 2.0, w[0]))
                t_y0 = dividing_lines[t_idx - 1] if t_idx > 0 else min_word_y
                t_y1 = dividing_lines[t_idx] if t_idx < len(dividing_lines) else table_y0
                header_rows.append(_RowData(
                    words=tw,
                    y0=t_y0,
                    y1=t_y1,
                    color=None,
                    is_header=True,
                ))
            return header_rows
        else:
            # 原则 3：表格顶部边界到第一道下划线区域（Table Top to First Underline）合并为顶层表头
            header_words_sorted = sorted(header_words, key=lambda w: (round((w[1] + w[3]) / 2.0 / 4.0), w[0]))
            return [_RowData(
                words=header_words_sorted,
                y0=min(w[1] for w in header_words_sorted),
                y1=max(w[3] for w in header_words_sorted),
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
                    elif next_text in ("—", "-", "–"):
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
            # 优先行级别为准：未落入背景色的文本直接按天然物理行归入数据行
            row_words_by_y: Dict[float, List[Tuple]] = defaultdict(list)
            for w in unassigned_words:
                mid_y = (w[1] + w[3]) / 2.0
                matched_y = next((ey for ey in row_words_by_y if abs(mid_y - ey) <= 3.5), None)
                if matched_y is None:
                    matched_y = mid_y
                row_words_by_y[matched_y].append(w)

            for ry in sorted(row_words_by_y.keys()):
                rwords = sorted(row_words_by_y[ry], key=lambda w: w[0])
                data_rows.append(_RowData(
                    words=rwords,
                    y0=min(w[1] for w in rwords),
                    y1=max(w[3] for w in rwords),
                    color=None,
                    is_header=False,
                ))

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
                and self._is_pure_amount_dollar(word, [w for w in (words or []) if abs((w[1] + w[3]) / 2.0 - (word[1] + word[3]) / 2.0) <= 3.5])
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

        all_row_segs: List[Tuple[float, List[Tuple[float, float]]]] = []
        total_tbl_w = (table_bbox.x1 - table_bbox.x0) if table_bbox else ((max(w[2] for w in words) - min(w[0] for w in words)) if words else 500.0)
        for ry, rwords in rows_by_y.items():
            rwords.sort(key=lambda w: w[0])
            cur: List[Tuple] = []
            row_segs: List[Tuple[float, float]] = []
            for w in rwords:
                if not cur:
                    cur.append(w)
                else:
                    prev = cur[-1]
                    gap = w[0] - prev[2]
                    # 纯金额货币符号属于其右侧金额项，绝不能与左侧独立数据项向左合并产生跨列粘连
                    is_new_currency = (
                        (str(w[4]).startswith("$") or str(w[4]).strip() == "$")
                        and self._is_pure_amount_dollar(w, rwords)
                        and not (str(prev[4]).startswith("$") or str(prev[4]).strip() == "$")
                    )
                    if is_new_currency:
                        row_segs.append((min(x[0] for x in cur), max(x[2] for x in cur)))
                        cur = [w]
                    elif gap <= 6.0:
                        cur.append(w)
                    else:
                        row_segs.append((min(x[0] for x in cur), max(x[2] for x in cur)))
                        cur = [w]
            if cur:
                row_segs.append((min(x[0] for x in cur), max(x[2] for x in cur)))
            # 单行大跨度文字段（Rule 2.4 / 4.2）若单段宽度超过 45% 全宽且存在多行，不参与通用列融合
            all_row_segs.append((ry, row_segs))

        line_segments: List[Tuple[float, float]] = []
        for ry, r_segs in all_row_segs:
            for s in r_segs:
                spanning_count = 0
                for other_ry, other_r_segs in all_row_segs:
                    if other_ry == ry:
                        continue
                    overlapping_sub_segs = [os for os in other_r_segs if min(s[1], os[1]) - max(s[0], os[0]) >= 2.0]
                    if len(overlapping_sub_segs) >= 2:
                        spanning_count += 1
                if spanning_count >= 2:
                    continue
                line_segments.append(s)

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

        # 空列间隙/全空行剪枝（Empty Column Pruning）
        # 若某列完全没有任何字（词频为 0）且非首全列，合并到邻近有效列
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
        body_words = [
            word for row in (data_rows or [])
            if not getattr(row, "is_header", False)
            for word in getattr(row, "words", [])
        ]
        dollar_words = [
            word for word in body_words
            if (str(word[4]).strip() == "$" or str(word[4]).strip().startswith("$"))
            and self._is_pure_amount_dollar(word, getattr(next((r for r in (data_rows or []) if word in getattr(r, "words", [])), None), "words", []))
        ]
        for dollar in dollar_words:
            x0 = float(dollar[0])
            for ci in range(1, len(columns)):
                cx0, cx1 = columns[ci]
                prev_x0, prev_x1 = columns[ci - 1]
                if prev_x0 < x0 < cx0 and abs(cx0 - x0) <= 6.0:
                    columns[ci - 1] = (prev_x0, x0)
                    columns[ci] = (x0, cx1)

        # 融合在纯数据/编号列左侧过度切分的连续描述与地址栏
        if len(columns) >= 3:
            ci = 0
            while ci < len(columns) - 1:
                cx0, cx1 = columns[ci]
                nx0, nx1 = columns[ci + 1]
                c_words = [w for w in (words or []) if cx0 - 2.0 <= (w[0] + w[2]) / 2.0 <= cx1 + 2.0]
                n_words = [w for w in (words or []) if nx0 - 2.0 <= (w[0] + w[2]) / 2.0 <= nx1 + 2.0]
                
                n_has_pure_data = any(
                    self._is_pure_amount_dollar(w, [x for x in (words or []) if abs((x[1] + x[3]) / 2.0 - (w[1] + w[3]) / 2.0) <= 3.5])
                    or bool(re.search(r'\d|%|\$|^(?:[A-D][+-]?|N/A|None|Yes|No|\*|—|-)$', w[4].strip()))
                    or bool(re.search(r'\b\d{2,}-\d+\b|\b\d{5}\b', w[4].strip()))  # IRS Employer No / Zip Code
                    for w in n_words
                )
                if not n_has_pure_data and ci < len(columns) - 1:
                    columns[ci] = (cx0, nx1)
                    del columns[ci + 1]
                else:
                    ci += 1

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

    @staticmethod
    def _is_pure_amount_dollar(w: Tuple, row_words: List[Tuple]) -> bool:
        """Check if a word containing '$' belongs to a pure numeric amount item, not an inline prose sentence."""
        if not w or not row_words:
            return False
        w_text = str(w[4]).strip()
        if "$" not in w_text:
            return False
        
        # Cluster row words into contiguous horizontal phrases (gap <= 5.0pt)
        sorted_rw = sorted(row_words, key=lambda x: x[0])
        phrases: List[List[Tuple]] = []
        cur: List[Tuple] = []
        for x in sorted_rw:
            if not cur:
                cur.append(x)
            else:
                if x[0] - cur[-1][2] <= 5.0:
                    cur.append(x)
                else:
                    phrases.append(cur)
                    cur = [x]
        if cur:
            phrases.append(cur)
        
        w_phrase = next((p for p in phrases if any(id(px) == id(w) for px in p)), None)
        if not w_phrase:
            return False
        
        # Standard currency and numeric unit/symbol tokens
        valid_units = {
            '$', '\u2009$', 'usd', 'eur', 'rmb', 'gbp', 'aud', 'cad', 'chf', 'hkd', 'sgd',
            'm', 'b', 'k', 'mn', 'bn', 'in', 'million', 'millions', 'thousand', 'thousands', 'billion', 'billions',
            '—', '-', '--', '(', ')', '%', 'n/m', 'nil', 'none'
        }
        
        non_numeric_tokens = [
            pw[4].strip().lower().rstrip('.,;:()')
            for pw in w_phrase
            if not any(ch.isdigit() for ch in pw[4])
        ]
        
        prose_tokens = [tok for tok in non_numeric_tokens if tok and tok not in valid_units]
        if prose_tokens:
            return False
        
        # Must contain at least one digit or standard nil token
        has_amount = any(any(ch.isdigit() for ch in pw[4]) or pw[4].strip() in ('—', '-', '--', 'nil', 'none') for pw in w_phrase)
        return has_amount

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
        x_min_bound = table_bbox.x0 - 5.0 if table_bbox else -1e9
        x_max_bound = table_bbox.x1 + 5.0 if table_bbox else 1e9

        for d in drawings:
            if self._is_invisible_drawing(d):
                continue
            for it in d.get("items", []):
                if it[0] == "l":
                    p1, p2 = it[1], it[2]
                    if abs(p1.y - p2.y) <= 1.0 and abs(p1.x - p2.x) >= 4.0:
                        y = p1.y
                        x0 = min(p1.x, p2.x)
                        x1 = max(p1.x, p2.x)
                        if y_min_bound <= y <= y_max_bound and x_min_bound <= (x0 + x1) / 2.0 <= x_max_bound:
                            h_lines.append((x0, x1, y))
                elif it[0] == "re":
                    r = it[1]
                    if r.height <= 2.5 and r.width >= 4.0:
                        y = r.y0
                        if y_min_bound <= y <= y_max_bound and x_min_bound <= (r.x0 + r.x1) / 2.0 <= x_max_bound:
                            h_lines.append((r.x0, r.x1, y))

        if not h_lines:
            return []

        table_x0 = table_bbox.x0 if table_bbox else (min(w[0] for w in words) if words else 30.0)
        table_x1 = table_bbox.x1 if table_bbox else (max(w[2] for w in words) if words else 600.0)
        table_w = table_x1 - table_x0

        # 表格内部下划线多段检测 (排除从最左侧开始贯穿整张表格的整行底部分隔线)
        table_h_lines = [
            l for l in h_lines
            if table_x0 - 5.0 <= (l[0] + l[1]) / 2.0 <= table_x1 + 5.0
            and y_min_bound <= l[2] <= y_max_bound
            and not (l[0] <= table_x0 + 5.0 and l[1] >= table_x1 - 5.0)
        ]
        lines_by_y: Dict[float, List[Tuple[float, float]]] = defaultdict(list)
        for x0, x1, y in table_h_lines:
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
                    if s[0] <= merged[-1][1]:
                        merged[-1][1] = max(merged[-1][1], s[1])
                    else:
                        merged.append(list(s))
            col_segs = [s for s in merged if not (s[0] <= table_x0 + 5.0 and s[1] >= table_x1 - 5.0)]
            
            # 过滤表体内部紧贴文字底部的文本超链接划线
            is_full_width = any((s[1] - s[0]) >= table_w * 0.70 for s in col_segs)
            if len(col_segs) < 2 and y > table_y0 + 20.0 and not is_full_width:
                tight_words = [
                    w for w in (words or [])
                    if abs((w[1] + w[3]) / 2.0 - y) <= 6.0
                    and not (w[2] < col_segs[0][0] - 5.0 or w[0] > col_segs[-1][1] + 5.0)
                ]
                if tight_words:
                    w_y1 = max(w[3] for w in tight_words)
                    if abs(y - w_y1) <= 3.0:
                        continue

            if col_segs and len(col_segs) >= 2:
                merged_by_y[y] = col_segs

        t_words = [
            w for w in (words if words else [])
            if (table_bbox is None or (table_bbox.y0 - 2.0 <= (w[1] + w[3]) / 2.0 <= table_bbox.y1 + 2.0 and table_bbox.x0 - 5.0 <= (w[0] + w[2]) / 2.0 <= table_bbox.x1 + 5.0))
        ]

        # 只有从表头起始连续的多道下划线才属于表头高度范围
        top_y = min((w[1] for w in t_words), default=(table_bbox.y0 if table_bbox else table_y0))
        sorted_all_ys = sorted(lines_by_y.keys())
        continuous_header_ys = set()
        for y in sorted_all_ys:
            if not continuous_header_ys:
                if y - top_y <= 35.0:
                    continuous_header_ys.add(y)
                else:
                    break
            else:
                prev_y = max(continuous_header_ys)
                if y - prev_y <= 35.0:
                    continuous_header_ys.add(y)
                else:
                    break

        valid_header_merged = {y: segs for y, segs in merged_by_y.items() if y in continuous_header_ys}
        if not valid_header_merged:
            return []

        best_y = max(valid_header_merged.keys(), key=lambda y: (len(valid_header_merged[y]), -abs(y - table_y0)))
        best_segments = valid_header_merged[best_y]

        if not best_segments:
            return []

        data_words = [w for w in t_words if (w[1] + w[3]) / 2.0 >= best_y - 2.0]
        # 检查数据行中的离散数据项列数：若数据行的离散列数明显多于下划线数，说明下划线不完整，交由数据行通用切分
        data_rows_dict = defaultdict(list)
        for w in data_words:
            mid_y = (w[1] + w[3]) / 2.0
            matched_y = next((ey for ey in data_rows_dict if abs(mid_y - ey) <= 3.5), None)
            if matched_y is None:
                matched_y = mid_y
            data_rows_dict[matched_y].append(w)

        max_row_discrete_items = 0
        for ry, rw in data_rows_dict.items():
            rw.sort(key=lambda w: w[0])
            items = []
            cur = []
            for w in rw:
                if not cur:
                    cur.append(w)
                else:
                    prev = cur[-1]
                    gap = w[0] - prev[2]
                    # $ 与紧邻数值合并
                    if ("$" in prev[4] or prev[4].strip() == "$") and any(ch.isdigit() for ch in w[4]):
                        cur.append(w)
                    elif (prev[4] == "(" or w[4] == ")") and gap <= 4.0:
                        cur.append(w)
                    elif any(ch.isdigit() for ch in prev[4]) and any(ch.isdigit() for ch in w[4]) and gap <= 3.0:
                        cur.append(w)
                    elif gap <= 3.0:
                        cur.append(w)
                    else:
                        items.append(cur)
                        cur = [w]
            if cur:
                items.append(cur)

            d_count = sum(
                1 for it in items
                if any(ch.isdigit() for ch in " ".join(w[4] for w in it))
                or any(w[4] in ("Gross", "Net", "%", "—", "-", "--", "n/m") for w in it)
            )
            if d_count > max_row_discrete_items:
                max_row_discrete_items = d_count

        if max_row_discrete_items >= len(best_segments) * 2.5:
            return []

        # 3. 宽下划线段内基于数据行留白通道的通用子列细分（Sub-column Decomposition）
        refined_col_spans = []
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
                        # 数值或包含特定标记独立分词；单词间距 gap >= 3.5pt 在下划线段内部拆分为不同 item
                        if prev[4] == "$" and any(ch.isdigit() for ch in w[4]):
                            cur.append(w)
                        elif any(ch.isdigit() for ch in prev[4]) or any(ch.isdigit() for ch in w[4]):
                            if gap <= 3.0:
                                cur.append(w)
                            else:
                                items.append((min(x[0] for x in cur), max(x[2] for x in cur)))
                                cur = [w]
                        elif gap <= 6.0:
                            # 正常文本短语词间距（<= 6.0pt）属于同一单元格语块，不得在下划线内部拆分为多列
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
            for g in gaps:
                matched_gc = None
                for gc in gap_clusters:
                    max_l = max(max(x[0] for x in gc), g[0])
                    min_r = min(min(x[1] for x in gc), g[1])
                    if max_l < min_r:
                        matched_gc = gc
                        break
                if matched_gc is not None:
                    matched_gc.append(g)
                else:
                    gap_clusters.append([g])

            min_cluster_size = 1 if len(rows_sub) <= 2 else max(1, len(rows_sub) // 3)
            valid_gap_clusters = [gc for gc in gap_clusters if len(gc) >= min_cluster_size]
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
                cuts = sorted(list(set(cuts)))
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

        # 过滤出严格属于表体（排除表头区域）的数据词，用于计算数据列留白中心点与表体货币锚点
        body_data_words = [w for w in t_words if (w[1] + w[3]) / 2.0 >= best_y - 2.0]
        # 表体纯金额货币符号识别（仅限纯金额数据项，排除长描述句子中的内嵌面值如 $0.0001 per share）
        body_rows_dict = defaultdict(list)
        for w in body_data_words:
            mid_y = (w[1] + w[3]) / 2.0
            matched_y = next((ey for ey in body_rows_dict if abs(mid_y - ey) <= 3.5), None)
            if matched_y is None:
                matched_y = mid_y
            body_rows_dict[matched_y].append(w)
        
        body_dollar_words = set()
        for ry, rw in body_rows_dict.items():
            for w in rw:
                if ("$" in w[4] or w[4].strip() == "$") and self._is_pure_amount_dollar(w, rw):
                    body_dollar_words.add(id(w))

        # 行标签列与各数据列的分界线：优先以文本间隙中心点（Gap Midpoint）划分；若表体数据列包含纯金额 $ 符号，则对齐到表体 $ 符号左侧
        boundaries = []
        if all_col_spans and all_col_spans[0][0] > table_x0 + 35.0:
            leading_body = [w for w in body_data_words if (w[0] + w[2]) / 2.0 < all_col_spans[0][0] - 2.0]
            if leading_body:
                lead_x1 = max(w[2] for w in leading_body)
                first_col_body_words = [w for w in body_data_words if all_col_spans[0][0] - 2.0 <= (w[0] + w[2]) / 2.0 <= all_col_spans[0][1] + 2.0]
                first_d = [w[0] for w in first_col_body_words if id(w) in body_dollar_words]
                if first_d:
                    b0 = min(first_d)
                else:
                    first_x0 = min((w[0] for w in first_col_body_words), default=all_col_spans[0][0])
                    b0 = (lead_x1 + first_x0) / 2.0 if lead_x1 < first_x0 else first_x0
                boundaries.append(b0)

        for k in range(len(all_col_spans) - 1):
            col_k_span = all_col_spans[k]
            col_next_span = all_col_spans[k + 1]
            left_words = [w for w in body_data_words if col_k_span[0] - 2.0 <= (w[0] + w[2]) / 2.0 <= col_k_span[1] + 2.0]
            right_words = [w for w in body_data_words if col_next_span[0] - 25.0 <= (w[0] + w[2]) / 2.0 <= col_next_span[1] + 2.0]
            next_dollars = [w[0] for w in right_words if id(w) in body_dollar_words and w[0] >= col_k_span[1] - 5.0]
            if next_dollars:
                bk = min(next_dollars)
            else:
                # 存在物理下划线间隔时，列线优先处于两下划线之间的物理留白通道内，不得穿透进入下一列下划线或标题
                if col_k_span[1] < col_next_span[0]:
                    bk = (col_k_span[1] + col_next_span[0]) / 2.0
                else:
                    prev_end = max((w[2] for w in left_words), default=col_k_span[1])
                    next_start = min((w[0] for w in right_words), default=col_next_span[0])
                    if prev_end < next_start:
                        bk = (prev_end + next_start) / 2.0
                    else:
                        bk = (col_k_span[1] + col_next_span[0]) / 2.0
            boundaries.append(bk)

        columns = []
        curr_x = table_x0
        for b in sorted(list(set(boundaries))):
            if b > curr_x + 2.0:
                columns.append((curr_x, b))
                curr_x = b
        if table_x1 > curr_x + 2.0:
            columns.append((curr_x, table_x1))

        # 规则指南第 56 条：多 $ 宽列自适应分裂与精准贴合（仅限表体纯金额单元格项）
        row_words_by_y = defaultdict(list)
        for w in data_words:
            mid_y = (w[1] + w[3]) / 2.0
            matched_y = next((ey for ey in row_words_by_y if abs(mid_y - ey) <= 3.5), None)
            if matched_y is None:
                matched_y = mid_y
            row_words_by_y[matched_y].append(w)

        adj_columns = []
        for cx0, cx1 in columns:
            row_dollars_dict = defaultdict(list)
            for w in data_words:
                rw = row_words_by_y.get(next((ey for ey in row_words_by_y if abs((w[1] + w[3]) / 2.0 - ey) <= 3.5), None), [])
                if ("$" in w[4] or w[4].strip() == "$") and cx0 <= (w[0] + w[2]) / 2.0 < cx1:
                    if self._is_pure_amount_dollar(w, rw):
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
            is_dollar_col = col_tokens and all(tok in ("$", "%", "—", "-", "--") or tok.endswith("$") for tok in col_tokens)
            is_empty_col = not col_tokens
            if is_dollar_col or (col_w <= 18.0 and is_empty_col):
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
    def _infer_centered_parent_header_span(
        px0: float,
        px1: float,
        peer_boxes: List[Tuple[float, float]],
        columns: List[Tuple[float, float]],
        col_content_extents: Optional[List[Optional[Tuple[float, float]]]] = None,
        supported_cols: Optional[Set[int]] = None,
        allow_full_width: bool = False,
    ) -> Optional[Tuple[int, int]]:
        """基于中文无线表格几何中心点对齐与拓扑约束推断父表头跨列合并 (sc, colspan)。"""
        num_cols = len(columns)
        if num_cols < 2:
            return None

        parent_center = (px0 + px1) / 2.0
        best_candidate = None
        best_dist = 9999.0

        max_span_cols = num_cols if allow_full_width else num_cols - 1
        for sc in range(num_cols):
            for ec in range(sc + 1, min(num_cols, sc + max_span_cols + 1)):
                group_col_x0 = columns[sc][0]
                group_col_x1 = columns[ec][1]

                # 优先使用子列内文字/下划线内容的实际真实区间
                if col_content_extents and sc < len(col_content_extents) and ec < len(col_content_extents):
                    valid_exts = [col_content_extents[ci] for ci in range(sc, ec + 1) if ci < len(col_content_extents) and col_content_extents[ci] is not None]
                    if valid_exts:
                        content_x0 = min(e[0] for e in valid_exts)
                        content_x1 = max(e[1] for e in valid_exts)
                    else:
                        content_x0, content_x1 = group_col_x0, group_col_x1
                else:
                    content_x0, content_x1 = group_col_x0, group_col_x1

                group_width = content_x1 - content_x0
                group_center = (content_x0 + content_x1) / 2.0

                # 1. 几何中心点偏差约束 (允许最大 15% 几何公差或 6.0pt)
                max_dev = max(6.0, group_width * 0.15)
                center_dist = abs(group_center - parent_center)

                # 同时备选网格列带中心点偏差
                grid_center = (group_col_x0 + group_col_x1) / 2.0
                grid_dev = abs(grid_center - parent_center)
                eff_dist = min(center_dist, grid_dev)

                if eff_dist > max_dev:
                    continue

                # 2. 文本不能明显溢出列带外侧 (<= 6.0pt)
                if px0 < group_col_x0 - 6.0 or px1 > group_col_x1 + 6.0:
                    continue

                # 3. 同层排他性：同层其他短语不得落入 [sc, ec] 列带内，且列带不得侵入左右同层短语边界
                conflict = False
                for p_bx0, p_bx1 in peer_boxes:
                    p_mid = (p_bx0 + p_bx1) / 2.0
                    if group_col_x0 + 2.0 <= p_mid <= group_col_x1 - 2.0:
                        conflict = True
                        break
                    if p_bx0 >= px1 - 5.0 and group_col_x1 > p_bx0 + 5.0:
                        conflict = True
                        break
                    if p_bx1 <= px0 + 5.0 and group_col_x0 < p_bx1 - 5.0:
                        conflict = True
                        break
                if conflict:
                    continue

                # 4. 纯拓扑子列完整支撑约束：区间 [sc, ec] 内的每一个子列都必须有有效的子表头单元格支撑
                if supported_cols is not None:
                    if not all(c in supported_cols for c in range(sc, ec + 1)):
                        continue

                # 5. 结构性叶子约束：若短语被候选内某一列 ci 完全包含，
                #    且该列在下一层没有独立内容支撑（col_content_extents[ci] is None），
                #    说明该短语是该列自身的叶子内容（如折行标题），而非跨列父标题
                if col_content_extents is not None:
                    leaf_contained = any(
                        columns[ci][0] <= px0 and px1 <= columns[ci][1]
                        and ci < len(col_content_extents)
                        and col_content_extents[ci] is None
                        for ci in range(sc, ec + 1)
                    )
                    if leaf_contained:
                        continue

                cur_span = ec - sc + 1
                if best_candidate is None:
                    best_dist = eff_dist
                    best_candidate = (sc, cur_span)
                else:
                    best_span = best_candidate[1]
                    if eff_dist < best_dist - 1.5:
                        best_dist = eff_dist
                        best_candidate = (sc, cur_span)
                    elif abs(eff_dist - best_dist) <= 1.5:
                        if cur_span > best_span:
                            best_dist = eff_dist
                            best_candidate = (sc, cur_span)

        return best_candidate

    def _normalize_headers(
        self,
        header_cells: List[Cell],
        columns: List[Tuple[float, float]],
        page: Optional[fitz.Page] = None,
    ) -> Tuple[List[Cell], int]:
        """多层表头规范化与跨列跨行推断（斑马线与通用无线表格通用）：
        1. 通栏单位/金额说明行（如 (Dollars in thousands)）全宽跨列合并；
        2. 自底向上推断父表头跨列合并（列合并原则 2）：
           - 优先级 1（最高，物理下划线覆盖）：检查文本下方是否存在物理下划线，以下划线覆盖的子列范围作为跨列范围；
           - 优先级 2（次之，中心对称扩充）：无下划线时，以标题文字水平中心点为锚点，向左右两边同时对称扩充相同数量单元格（左右等步长扩展），
             只要中心点未偏移且左右单元格为空则继续合并，直至遇到边界、相邻内容或中心点发生偏移；
        3. 垂直折行融合：两层单元格列跨度完全相同且中间无物理水平横线阻断时融合；
        4. 向下空槽位跨行覆盖：下一层对应槽位全为空且无横线阻断时整块向下跨行；
        5. 无父表头单列单元格跨表头提升；
        6. 物理行压缩（Row Compression）：压缩完全被合并消除的物理行，物化未被占用的独立空单元格。
        """
        if not header_cells:
            return [], 0

        # 兼容历史别名
        # _normalize_zebra_headers 在类末尾统一绑定

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
            if self._is_invisible_drawing(d):
                continue
            for it in d.get("items", []):
                if it[0] in ("l", "re"):
                    y = it[1].y if it[0] == "l" else it[1].y0
                    w = abs(it[2].x - it[1].x) if it[0] == "l" else it[1].width
                    h = abs(it[2].y - it[1].y) if it[0] == "l" else it[1].height
                    x0 = min(it[1].x, it[2].x) if it[0] == "l" else it[1].x0
                    x1 = max(it[1].x, it[2].x) if it[0] == "l" else it[1].x1
                    if w >= 10.0 and h <= 2.5:
                        h_lines.append((round(y, 1), x0, x1))

        # 0. 表头中独立的通栏金额/单位说明行（如 (Dollars in thousands)）全宽跨列合并
        for orig_r in sorted_row_indices:
            tier_non_empty = [c for c in rows_dict[orig_r] if c.text.strip()]
            if len(tier_non_empty) == 1 and re.search(r'^\(?\s*(?:dollars|in\s+(?:thousands|millions|billions)|usd|\$|rmb)', tier_non_empty[0].text.strip(), re.IGNORECASE):
                unit_c = tier_non_empty[0]
                unit_c.col_index = 0
                unit_c.colspan = len(columns)
                unit_c.bbox = BBox(columns[0][0], unit_c.bbox.y0, columns[-1][1], unit_c.bbox.y1)
                rows_dict[orig_r] = [unit_c]

        # 1. 非叶子父表头行连续词组预合并（如 R0 中的 Unrealized + Investments, R1 中的 Net IRRs + (d)）
        hier_tiers = list(sorted_row_indices)
        for pt in hier_tiers[:-1]:
            row_c = sorted([c for c in rows_dict[pt] if c.text.strip()], key=lambda c: c.bbox.x0)
            non_empty_c = list(row_c)
            i = 0
            while i < len(non_empty_c) - 1:
                c1 = non_empty_c[i]
                c2 = non_empty_c[i + 1]
                gap = c2.bbox.x0 - c1.bbox.x1
                if -2.0 <= gap <= 4.5:
                    c1.text = (c1.text + " " + c2.text).strip()
                    c1.bbox = BBox(
                        min(c1.bbox.x0, c2.bbox.x0),
                        min(c1.bbox.y0, c2.bbox.y0),
                        max(c1.bbox.x1, c2.bbox.x1),
                        max(c1.bbox.y1, c2.bbox.y1),
                    )
                    c2.text = ""
                    c2.colspan = 1
                    non_empty_c.pop(i + 1)
                else:
                    i += 1

        # 2. 自底向上推断父表头跨列合并（叶子行保持单列，只推断父层表头；优先级 1：物理下划线；优先级 2：中心对称扩充）
        for t in range(num_tiers - 2, -1, -1):
            cur_tier_cells = [c for c in rows_dict[sorted_row_indices[t]] if c.text.strip()]
            next_tier_cells = rows_dict[sorted_row_indices[t + 1]] if t + 1 < num_tiers else []
            # 支撑列为所有下层表头中有效列的并集
            supported_cols = {
                ci for nt in range(t + 1, num_tiers)
                for c in rows_dict[sorted_row_indices[nt]] if c.text.strip()
                for ci in range(c.col_index, c.col_index + c.colspan)
            }
            if not supported_cols:
                supported_cols = set(range(1, len(columns))) if len(columns) > 1 else {0}

            col_content_extents: List[Optional[Tuple[float, float]]] = [None] * len(columns)
            for nt in range(t + 1, num_tiers):
                for c in rows_dict[sorted_row_indices[nt]]:
                    if c.text.strip() and c.col_index < len(columns):
                        for ci in range(c.col_index, min(len(columns), c.col_index + max(1, c.colspan))):
                            if col_content_extents[ci] is None:
                                col_content_extents[ci] = (c.bbox.x0, c.bbox.x1)
            for ci in range(len(columns)):
                if col_content_extents[ci] is None:
                    col_content_extents[ci] = (columns[ci][0], columns[ci][1])

            lower_spans = []
            for nt in range(t + 1, num_tiers):
                for c in rows_dict[sorted_row_indices[nt]]:
                    if c.text.strip():
                        lower_spans.append((c.col_index, c.col_index + max(1, c.colspan) - 1))
            for ci in supported_cols:
                if not any(s[0] <= ci <= s[1] for s in lower_spans):
                    lower_spans.append((ci, ci))
            lower_spans = sorted(list(set(lower_spans)), key=lambda s: (s[0], s[1]))
            atomic_spans = []
            covered_indices = set()
            for s in lower_spans:
                if s[0] not in covered_indices:
                    atomic_spans.append(s)
                    for x in range(s[0], s[1] + 1):
                        covered_indices.add(x)
            atomic_spans.sort(key=lambda s: s[0])

            non_empty_tops = sorted([c for c in cur_tier_cells if c.text.strip()], key=lambda c: c.bbox.x0)
            if non_empty_tops:
                num_cols = len(columns)
                occupied = set()

                # 1. 优先级最高：当文本存在物理下划线（或由列间隙隔开的连续下划线线段组）时，以下划线覆盖的子列范围为准
                processed_tops = set()
                y_groups = {}
                for ly, lx0, lx1 in h_lines:
                    matched_y = None
                    for y_key in y_groups:
                        if abs(y_key - ly) <= 1.5:
                            matched_y = y_key
                            break
                    if matched_y is None:
                        y_groups[ly] = [(lx0, lx1)]
                    else:
                        y_groups[matched_y].append((lx0, lx1))

                all_underline_groups = []
                for y_key, segs in y_groups.items():
                    sorted_segs = sorted(segs, key=lambda s: s[0])
                    curr_chain = []
                    for s in sorted_segs:
                        if not curr_chain:
                            curr_chain.append(s)
                        else:
                            gap = s[0] - curr_chain[-1][1]
                            if gap <= 25.0:
                                curr_chain.append(s)
                            else:
                                all_underline_groups.append((y_key, min(x[0] for x in curr_chain), max(x[1] for x in curr_chain)))
                                curr_chain = [s]
                    if curr_chain:
                        all_underline_groups.append((y_key, min(x[0] for x in curr_chain), max(x[1] for x in curr_chain)))

                for top in sorted(non_empty_tops, key=lambda c: -(c.bbox.x1 - c.bbox.x0)):
                    line_h = max(8.0, top.bbox.y1 - top.bbox.y0)
                    best_covered_cols = []
                    # 寻找紧贴在当前表头文本下方的物理下划线组（优先距离最近的第一道下划线，避免跨层匹配到下层横线）
                    matching_groups = [
                        (y_key, gx0, gx1) for y_key, gx0, gx1 in all_underline_groups
                        if top.bbox.y1 - 1.5 <= y_key <= top.bbox.y1 + min(8.0, line_h * 0.4)
                        and min(top.bbox.x1, gx1) - max(top.bbox.x0, gx0) >= 2.0
                    ]
                    if not matching_groups:
                        matching_groups = [
                            (y_key, gx0, gx1) for y_key, gx0, gx1 in all_underline_groups
                            if top.bbox.y1 - 1.5 <= y_key <= top.bbox.y1 + 10.0
                            and min(top.bbox.x1, gx1) - max(top.bbox.x0, gx0) >= 2.0
                        ]

                    if matching_groups:
                        closest_y = min(g[0] for g in matching_groups)
                        for y_key, gx0, gx1 in matching_groups:
                            if abs(y_key - closest_y) > 1.5:
                                continue
                            cols_in_grp = [
                                ci for ci, (cx0, cx1) in enumerate(columns)
                                if min(cx1, gx1) - max(cx0, gx0) >= 2.0
                            ]
                            overlapping_tops = [
                                other for other in non_empty_tops
                                if min(other.bbox.x1, gx1) - max(other.bbox.x0, gx0) >= 2.0
                                and other.bbox.y1 - 1.5 <= y_key <= other.bbox.y1 + 10.0
                            ]
                            if len(overlapping_tops) <= 1:
                                if len(cols_in_grp) > len(best_covered_cols):
                                    best_covered_cols = cols_in_grp
                            else:
                                sorted_ov = sorted(overlapping_tops, key=lambda t: (t.bbox.x0 + t.bbox.x1) / 2.0)
                                top_idx = sorted_ov.index(top)
                                top_mid = (top.bbox.x0 + top.bbox.x1) / 2.0
                                left_mid = (sorted_ov[top_idx - 1].bbox.x0 + sorted_ov[top_idx - 1].bbox.x1) / 2.0 if top_idx > 0 else -float("inf")
                                right_mid = (sorted_ov[top_idx + 1].bbox.x0 + sorted_ov[top_idx + 1].bbox.x1) / 2.0 if top_idx < len(sorted_ov) - 1 else float("inf")

                                x_left = (left_mid + top_mid) / 2.0 if left_mid != -float("inf") else gx0 - 5.0
                                x_right = (top_mid + right_mid) / 2.0 if right_mid != float("inf") else gx1 + 5.0

                                my_cols = [
                                    ci for ci in cols_in_grp
                                    if x_left <= (columns[ci][0] + columns[ci][1]) / 2.0 <= x_right
                                ]
                                if len(my_cols) > len(best_covered_cols):
                                    best_covered_cols = my_cols

                    if len(best_covered_cols) > 1 and not any(ci in occupied for ci in best_covered_cols):
                        sc = min(best_covered_cols)
                        ec = max(best_covered_cols)
                        for ci in range(sc, ec + 1):
                            occupied.add(ci)
                        top.col_index = sc
                        top.colspan = ec - sc + 1
                        top.bbox = BBox(columns[sc][0], top.bbox.y0, columns[ec][1], top.bbox.y1)
                        processed_tops.add(id(top))

                # 2. 优先级次之：当没有下划线的时候，中心点向两边同时对称扩充相同数量单元格
                for top in sorted(non_empty_tops, key=lambda c: -(c.bbox.x1 - c.bbox.x0)):
                    if id(top) in processed_tops:
                        continue

                    t_mid = (top.bbox.x0 + top.bbox.x1) / 2.0

                    # 寻找初始锚点列（按中心点对齐优先）
                    best_anchor = None
                    best_dev = float("inf")

                    for k in range(num_cols):
                        if k in occupied:
                            continue
                        cmid = (columns[k][0] + columns[k][1]) / 2.0
                        dev = abs(cmid - t_mid)
                        if dev < best_dev:
                            best_dev = dev
                            best_anchor = (k, k)

                    for k in range(num_cols - 1):
                        if k in occupied or (k + 1) in occupied:
                            continue
                        cmid = (columns[k][0] + columns[k + 1][1]) / 2.0
                        dev = abs(cmid - t_mid)
                        if dev < best_dev:
                            best_dev = dev
                            best_anchor = (k, k + 1)

                    if best_anchor is None:
                        continue

                    sc, ec = best_anchor

                    # 中心点向两边同时对称扩充相同数量单元格
                    while True:
                        left = sc - 1
                        right = ec + 1
                        # 达到边界检查
                        if left < 0 or right >= num_cols:
                            break
                        # 左右单元格为空检查
                        if left in occupied or right in occupied:
                            break
                        if any(other for other in non_empty_tops if other is not top and max(other.bbox.x0, columns[left][0]) < min(other.bbox.x1, columns[left][1])):
                            break
                        if any(other for other in non_empty_tops if other is not top and max(other.bbox.x0, columns[right][0]) < min(other.bbox.x1, columns[right][1])):
                            break

                        # 若当前跨度已完全包围文本，且外部列在子层中均无内容支撑，则停止向外扩充空白列
                        if columns[sc][0] <= top.bbox.x0 and columns[ec][1] >= top.bbox.x1:
                            if left not in supported_cols and right not in supported_cols:
                                break

                        new_mid = (columns[left][0] + columns[right][1]) / 2.0
                        new_dev = abs(new_mid - t_mid)

                        # 中心点发生偏移检查：如果扩充后中心点偏出文本自身横向跨度或偏出最小列宽半距，停止扩充
                        min_col_w = min(c[1] - c[0] for c in columns)
                        if new_dev > min_col_w / 2.0 and (new_mid < top.bbox.x0 or new_mid > top.bbox.x1):
                            break

                        sc = left
                        ec = right

                    for ci in range(sc, ec + 1):
                        occupied.add(ci)

                    top.col_index = sc
                    top.colspan = ec - sc + 1
                    top.bbox = BBox(columns[sc][0], top.bbox.y0, columns[ec][1], top.bbox.y1)

        grid: List[List[Optional[Cell]]] = [[None for _ in range(len(columns))] for _ in range(num_tiers)]
        for out_r, orig_r in enumerate(sorted_row_indices):
            for c in rows_dict[orig_r]:
                if c.text.strip():
                    for ci in range(c.col_index, c.col_index + c.colspan):
                        grid[out_r][ci] = c

        merged_down = set()
        processed_pairs = set()
        for t in range(num_tiers - 1):
            tier_top_cells = [c for c in rows_dict[sorted_row_indices[t]] if c.text.strip()]
            tier_bot_cells = [c for c in rows_dict[sorted_row_indices[t + 1]] if c.text.strip()]
            t_y1 = max((c.bbox.y1 for c in tier_top_cells), default=0.0) if tier_top_cells else 0.0
            b_y0 = min((c.bbox.y0 for c in tier_bot_cells), default=0.0) if tier_bot_cells else 0.0

            # 检查两层表头之间是否存在物理水平线（不论覆盖全表还是部分列，只要处于两层之间即构成层级分割线，遵循原则 2/3）
            has_tier_line = any(
                min(t_y1, b_y0) - 1.5 <= ly <= max(t_y1, b_y0) + 1.5
                and max(columns[0][0] - 5.0, lx0) < min(columns[-1][1] + 5.0, lx1)
                for ly, lx0, lx1 in h_lines
            )

            for ci, (cx0, cx1) in enumerate(columns):
                c_top = grid[t][ci]
                c_bot = grid[t + 1][ci]
                if c_top is not None and c_bot is not None and c_bot is not c_top and c_top.col_index == c_bot.col_index and c_top.colspan == c_bot.colspan:
                    # 纯几何折行判别：两单元格列跨度完全相同，且中间无物理水平横线阻断
                    has_col_line = any(
                        c_top.bbox.y1 - 1.5 <= ly <= c_bot.bbox.y0 + 1.5
                        and max(columns[c_top.col_index][0] + 5.0, lx0) < min(columns[c_top.col_index + c_top.colspan - 1][1] - 5.0, lx1)
                        for ly, lx0, lx1 in h_lines
                    )
                    is_compact_wrapping = (not has_tier_line and not has_col_line and c_bot.bbox.y0 >= c_top.bbox.y1 - 4.0)
                    
                    if is_compact_wrapping:
                        pair_key = (id(c_top), id(c_bot))
                        if pair_key not in processed_pairs:
                            processed_pairs.add(pair_key)
                            c_top.text = (c_top.text + " " + c_bot.text).strip()
                            c_top.bbox = BBox(
                                min(c_top.bbox.x0, c_bot.bbox.x0),
                                min(c_top.bbox.y0, c_bot.bbox.y0),
                                max(c_top.bbox.x1, c_bot.bbox.x1),
                                max(c_top.bbox.y1, c_bot.bbox.y1),
                            )
                            c_bot.text = ""
                        for span_ci in range(c_top.col_index, c_top.col_index + c_top.colspan):
                            grid[t + 1][span_ci] = c_top
                            merged_down.add((t + 1, span_ci))
                elif c_top is not None:
                    # 只有当下一层覆盖的所有槽位全部为空，且下方无物理下划线阻断时，上一层单元格才允许整块向下跨行覆盖
                    has_sep_line = any(
                        c_top.bbox.y1 - 1.5 <= ly <= columns[-1][1]
                        and not (lx1 < columns[c_top.col_index][0] + 5.0 or lx0 > columns[c_top.col_index + c_top.colspan - 1][1] - 5.0)
                        for ly, lx0, lx1 in h_lines
                    )
                    # 父表头（colspan > 1）或层间存在物理横线时，严格保持自身层级（rowspan=1），不得向下吞并子列表头槽位
                    if (c_top.colspan > 1 or has_tier_line) and has_sep_line:
                        continue

                    all_sub_slots_empty = all(
                        grid[t + 1][span_ci] is None
                        for span_ci in range(c_top.col_index, c_top.col_index + c_top.colspan)
                    )
                    if all_sub_slots_empty and not has_tier_line:
                        for span_ci in range(c_top.col_index, c_top.col_index + c_top.colspan):
                            grid[t + 1][span_ci] = c_top
                            merged_down.add((t + 1, span_ci))

        # 处理在所有上层均无父表头覆盖的单列单元格（如 Col 0, 1, 2 行标签或单列指标，提升并设置 rowspan 跨越表头）
        if len(hier_tiers) >= 2:
            top_r = sorted_row_indices[0]
            leaf_r = hier_tiers[-1]
            top_cells = [c for c in rows_dict[top_r] if c.text.strip()]
            leaf_cells = [c for c in rows_dict[leaf_r] if c.text.strip()]
            top_y1 = max((c.bbox.y1 for c in top_cells), default=0.0) if top_cells else 0.0
            leaf_y0 = min((c.bbox.y0 for c in leaf_cells), default=0.0) if leaf_cells else 0.0

            # 检查首层与叶子层之间是否存在物理横线阻断
            has_inter_tier_line = any(
                top_y1 - 1.5 <= ly <= leaf_y0 + 1.5
                and max(columns[0][0] - 5.0, lx0) < min(columns[-1][1] + 5.0, lx1)
                for ly, lx0, lx1 in h_lines
            )

            if not has_inter_tier_line:
                for ci in range(len(columns)):
                    all_upper_empty = all(grid[t][ci] is None for t in range(leaf_r))
                    if all_upper_empty and grid[leaf_r][ci] is not None and grid[leaf_r][ci].colspan == 1:
                        c_leaf = grid[leaf_r][ci]
                        if c_leaf.text.strip():
                            # 若上层与当前单元格之间存在物理水平横线，严格禁止跨线提升
                            upper_cells = [grid[t][other_ci] for t in range(leaf_r) for other_ci in range(len(columns)) if grid[t][other_ci] is not None]
                            has_sep_line = any(
                                min((c.bbox.y1 for c in upper_cells), default=c_leaf.bbox.y0) - 1.5 <= ly <= c_leaf.bbox.y0 + 1.5
                                for ly, _, _ in h_lines
                            ) if upper_cells else False
                            if has_sep_line:
                                continue

                            # 从叶子行移除，放入首行
                            for orig_r in sorted_row_indices:
                                rows_dict[orig_r] = [c for c in rows_dict[orig_r] if c is not c_leaf]
                            rows_dict[top_r].append(c_leaf)
                            c_leaf.row_index = top_r
                            for t in range(leaf_r + 1):
                                grid[t][ci] = c_leaf
                                if t > 0:
                                    merged_down.add((t, ci))

        # 压缩完全被合并消除的物理行（Row Compression）
        active_tier_indices = []
        for out_r_idx in range(num_tiers):
            has_unmerged = any(
                grid[out_r_idx][ci] is not None and (out_r_idx, ci) not in merged_down
                for ci in range(len(columns))
            )
            if has_unmerged:
                active_tier_indices.append(out_r_idx)

        if not active_tier_indices:
            active_tier_indices = list(range(num_tiers))

        tier_remap = {orig_t: new_t for new_t, orig_t in enumerate(active_tier_indices)}

        output_cells = []
        occupied_2d = set()

        for new_r_idx, orig_t in enumerate(active_tier_indices):
            cur_row_cells = rows_dict[sorted_row_indices[orig_t]]
            row_y0 = min((c.bbox.y0 for c in cur_row_cells), default=0.0)
            row_y1 = max((c.bbox.y1 for c in cur_row_cells), default=row_y0 + 15.0)

            for c in cur_row_cells:
                if (orig_t, c.col_index) in merged_down or not c.text.strip():
                    continue
                # 计算该单元格在压缩后的实际 rowspan
                eff_rowspan = 1
                for check_t in active_tier_indices[new_r_idx + 1:]:
                    if any(grid[check_t][ci] is c for ci in range(c.col_index, c.col_index + c.colspan)):
                        eff_rowspan += 1
                    else:
                        break

                out_cell = Cell(
                    text=c.text,
                    row_index=new_r_idx,
                    col_index=c.col_index,
                    colspan=c.colspan,
                    rowspan=eff_rowspan,
                    bbox=c.bbox,
                )
                output_cells.append(out_cell)
                for r in range(new_r_idx, new_r_idx + eff_rowspan):
                    for ci in range(c.col_index, c.col_index + c.colspan):
                        occupied_2d.add((r, ci))

            # 物化该行未被占用的空槽位
            for ci in range(len(columns)):
                if (new_r_idx, ci) not in occupied_2d:
                    output_cells.append(Cell(
                        text="",
                        row_index=new_r_idx,
                        col_index=ci,
                        colspan=1,
                        rowspan=1,
                        bbox=BBox(columns[ci][0], row_y0, columns[ci][1], row_y1),
                    ))
                    occupied_2d.add((new_r_idx, ci))

        output_cells.sort(key=lambda c: (c.row_index, c.col_index))
        return output_cells, len(active_tier_indices)

    def _build_wireless_table(
        self,
        header_rows: List[_RowData],
        data_rows: List[_RowData],
        columns: List[Tuple[float, float]],
        confidence: Optional[float] = None,
        table_bbox: Optional[BBox] = None,
        page: Optional[fitz.Page] = None,
        source: Optional[str] = None,
    ) -> Optional[Table]:
        """统一构建英文无线表格（斑马底色与通用无线表格通用结构还原）：
        1. 表头与表体单元格短语归列（_assign_words_to_columns）；
        2. 表头多层级规范化与跨度推断（_normalize_headers，依据原则 2 优先级 1/2）；
        3. 自动合并全空列与孤立货币符号列（_prune_empty_columns，依据原则 3）；
        4. 统一行垂直分界线与 2D 包围盒无重叠闭合网格；
        5. 物化所有未覆盖槽位为独立空单元格（text=""），确保闭合二维网格；
        6. 通用质量检查与空行修剪。
        """
        if not header_rows and not data_rows:
            return None
        if not columns:
            return None

        # 1. 表头行单元格构建与短语归列
        raw_header_cells: List[Cell] = []
        for r_idx, hr in enumerate(header_rows):
            rc = self._assign_words_to_columns(
                words=hr.words,
                columns=columns,
                row_idx=r_idx,
                row_y0=hr.y0,
                row_y1=hr.y1,
                page=page,
                is_header=True,
            )
            raw_header_cells.extend(rc)

        # 2. 多层表头规范化（原则 2 跨列/跨行推断与物理行压缩）
        norm_h_cells, num_h_rows = self._normalize_headers(raw_header_cells, columns, page=page)

        # 3. 表体行单元格构建
        body_cells: List[Cell] = []
        for r_idx, dr in enumerate(data_rows):
            rc = self._assign_words_to_columns(
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

        # 4. 列合并原则 3：全空列与只含 $ 列向右合并
        all_cells, col_count = self._prune_empty_columns(all_cells, len(columns))

        total_rows = num_h_rows + len(data_rows)

        # 5. 统一行垂直分界线与 2D 包围盒（无重叠闭合网格）
        if all_cells and total_rows > 0:
            h_lines = []
            if page:
                try:
                    drawings = page.get_drawings()
                    for d in drawings:
                        if self._is_invisible_drawing(d):
                            continue
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
                for hr_idx in range(num_h_rows):
                    if hr_idx < len(header_rows):
                        raw_row_intervals.append((header_rows[hr_idx].y0, header_rows[hr_idx].y1))
                    else:
                        hr_cells = [c for c in norm_h_cells if c.row_index == hr_idx and c.text.strip()]
                        if hr_cells:
                            hr_y0 = min(c.bbox.y0 for c in hr_cells)
                            hr_y1 = max(c.bbox.y1 for c in hr_cells)
                        else:
                            hr_y0 = header_rows[min(hr_idx, len(header_rows) - 1)].y0 if header_rows else 0.0
                            hr_y1 = header_rows[min(hr_idx, len(header_rows) - 1)].y1 if header_rows else hr_y0 + 15.0
                        raw_row_intervals.append((hr_y0, hr_y1))
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
                cur_y0, cur_y1 = raw_row_intervals[i]
                next_y0, next_y1 = raw_row_intervals[i + 1]
                mid_y = (cur_y1 + next_y0) / 2.0

                min_allowed = row_bounds[-1] + 2.0
                candidates = [
                    hl for hl in unique_h_lines
                    if min_allowed <= hl and abs(hl - mid_y) <= 4.0
                ]
                if candidates:
                    snap_line = min(candidates, key=lambda hl: abs(hl - mid_y))
                    row_bounds.append(snap_line)
                else:
                    row_bounds.append(max(mid_y, min_allowed))
            row_bounds.append(bot_y1)

            for c in all_cells:
                r_s = c.row_index
                r_e = c.row_index + max(1, c.rowspan) - 1
                c_s = c.col_index
                c_e = c.col_index + max(1, c.colspan) - 1
                c_x0 = columns[c_s][0] if 0 <= c_s < len(columns) else c.bbox.x0
                c_x1 = columns[c_e][1] if 0 <= c_e < len(columns) else c.bbox.x1
                c_y0 = row_bounds[r_s] if 0 <= r_s < len(row_bounds) - 1 else c.bbox.y0
                c_y1 = row_bounds[r_e + 1] if 0 <= r_e < len(row_bounds) - 1 else c.bbox.y1
                c.bbox = BBox(round(c_x0, 1), round(c_y0, 1), round(c_x1, 1), round(c_y1, 1))

            # 物化所有未覆盖槽位为独立 Cell(text="")，保证闭合二维网格
            grid_occupied: Set[Tuple[int, int]] = set()
            for c in all_cells:
                for r in range(c.row_index, c.row_index + max(1, c.rowspan)):
                    for ci in range(c.col_index, c.col_index + max(1, c.colspan)):
                        grid_occupied.add((r, ci))

            for r in range(total_rows):
                for ci in range(col_count):
                    if (r, ci) not in grid_occupied:
                        c_x0 = columns[ci][0] if ci < len(columns) else 0.0
                        c_x1 = columns[ci][1] if ci < len(columns) else c_x0 + 20.0
                        c_y0 = row_bounds[r] if 0 <= r < len(row_bounds) - 1 else 0.0
                        c_y1 = row_bounds[r + 1] if 0 <= r < len(row_bounds) - 1 else c_y0 + 15.0
                        all_cells.append(Cell(
                            text="",
                            row_index=r,
                            col_index=ci,
                            colspan=1,
                            rowspan=1,
                            bbox=BBox(round(c_x0, 1), round(c_y0, 1), round(c_x1, 1), round(c_y1, 1)),
                        ))
                        grid_occupied.add((r, ci))

        if table_bbox is not None:
            bbox = table_bbox
            tbl_source = source or "ml_detection"
        else:
            all_r = header_rows + data_rows
            bbox = BBox(
                min(col[0] for col in columns),
                min(r.y0 for r in all_r) if all_r else 0.0,
                max(col[1] for col in columns),
                max(r.y1 for r in all_r) if all_r else 0.0,
            )
            tbl_source = source or "english_color_based"

        # 修剪末尾纯全空行
        all_cells.sort(key=lambda c: (c.row_index, c.col_index))
        while total_rows > num_h_rows:
            last_row_cells = [c for c in all_cells if c.row_index == total_rows - 1]
            if last_row_cells and all(not c.text.strip() for c in last_row_cells):
                all_cells = [c for c in all_cells if c.row_index != total_rows - 1]
                total_rows -= 1
            else:
                break

        conf_score = round(confidence, 4) if confidence is not None else 0.85

        return Table(
            bbox=bbox,
            rows=total_rows,
            cols=col_count,
            cells=all_cells,
            confidence=conf_score,
            source=tbl_source,
        )

    # 兼容历史别名
    _build_zebra_table = _build_wireless_table

    def _assign_words_to_columns(
        self,
        words: List[Tuple[float, float, float, float, str]],
        columns: List[Tuple[float, float]],
        row_idx: int,
        row_y0: float,
        row_y1: float,
        page: Optional[fitz.Page] = None,
        is_header: bool = False,
    ) -> List[Cell]:
        """将当前物理行中的 words 按几何投影分配到各列中，生成单元格列表：
        1. 聚类行内自然语块（Line phrase grouping，基于原生流式排版行与自适应字符宽度/高度，自然语块完整保留，不硬切西文词组）；
        2. 表头行（is_header=True）：自然语块保护 + 多行垂直融合 + 列归属综合评分（右对齐贴合度与中心偏离度）；
        3. 表体行（is_header=False）：跨列大文本识别（colspan > 1）+ 纯金额数据项货币符号吸附 + 标准西文清洗（$ 2,201 -> $2,201、千分位粘连修复、括号与百分号贴合）。
        """
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
                    font_h = min(prev_w[3] - prev_w[1], w[3] - w[1]) if (len(w) >= 4 and len(prev_w) >= 4) else 10.0
                    avg_char_w = ((prev_w[2] - prev_w[0]) / max(1, len(prev_w[4]))) if (len(prev_w) >= 5 and prev_w[4]) else 5.0
                    max_word_space = max(avg_char_w * 1.5, font_h * 0.5)

                    is_same_stream_line = (
                        len(w) >= 8 and len(prev_w) >= 8
                        and w[5] == prev_w[5]
                        and w[6] == prev_w[6]
                    )
                    is_num_repeat = (
                        any(ch.isdigit() for ch in prev_w[4])
                        and any(ch.isdigit() for ch in w[4])
                        and gap > avg_char_w * 0.8
                    )
                    is_text_phrase = (
                        not any(ch.isdigit() for ch in prev_w[4])
                        and not any(ch.isdigit() for ch in w[4])
                        and prev_w[4] not in ("$", "\u2009$")
                        and w[4] not in ("$", "\u2009$")
                    )

                    if is_num_repeat:
                        phrases.append(cur_p)
                        cur_p = [w]
                    elif is_header:
                        # 表头自然语块保护：依据流式文本行拓扑或字体空间尺寸判断是否属于同一自然语块，不使用固定阈值
                        if is_same_stream_line or gap <= max_word_space:
                            cur_p.append(w)
                        else:
                            phrases.append(cur_p)
                            cur_p = [w]
                    elif c_prev != c_curr and (c_prev != -1 and c_curr != -1):
                        # 自然语块跨列保护：当相邻词为纯文本词组且具有排版连续性时，严禁因落入不同列槽而强行切碎
                        if is_text_phrase and (is_same_stream_line or gap <= max_word_space):
                            cur_p.append(w)
                        else:
                            phrases.append(cur_p)
                            cur_p = [w]
                    elif c_prev == c_curr and (is_same_stream_line or gap <= max_word_space):
                        cur_p.append(w)
                    elif gap <= avg_char_w * 1.2 and not (w[4] in ("$", "\u2009$") or (any(ch.isdigit() for ch in w[4]) and gap > avg_char_w * 0.8)):
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
                p1_char_w = sum((w[2] - w[0]) / max(1, len(w[4])) for w in p1) / max(1, len(p1))
                cur_words = list(p1)
                used.add(i)
                for j, p2 in enumerate(phrases):
                    if j in used:
                        continue
                    p2_x0 = min(w[0] for w in p2)
                    p2_x1 = max(w[2] for w in p2)
                    ov = min(p1_x1, p2_x1) - max(p1_x0, p2_x0)
                    min_w = min(p1_x1 - p1_x0, p2_x1 - p2_x0)
                    if min_w > 0 and (ov >= 0.25 * min_w or abs(p1_x1 - p2_x1) <= p1_char_w * 1.2):
                        cur_words.extend(p2)
                        used.add(j)
                        p1_x0 = min(p1_x0, p2_x0)
                        p1_x1 = max(p1_x1, p2_x1)
                merged_phrases.append(cur_words)
            phrases = merged_phrases

            col_assigned_phrases: Dict[int, List[List[Tuple]]] = defaultdict(list)
            for p in phrases:
                px0 = min(w[0] for w in p)
                px1 = max(w[2] for w in p)
                pmid = (px0 + px1) / 2.0
                p_char_w = sum((w[2] - w[0]) / max(1, len(w[4])) for w in p) / max(1, len(p))

                # 寻找表头语块最佳归属列
                best_ci = None
                best_score = -1e9
                for ci, (cx0, cx1) in enumerate(columns):
                    col_w = max(1.0, cx1 - cx0)
                    phrase_w = max(1.0, px1 - px0)
                    right_fit = -abs(px1 - cx1) / col_w
                    ov = max(0.0, min(px1, cx1) - max(px0, cx0)) / phrase_w
                    cmid = (cx0 + cx1) / 2.0
                    center_dist = -abs(pmid - cmid) / col_w
                    in_col_right = (cx0 - p_char_w <= px1 <= cx1 + p_char_w and px0 >= (columns[ci - 1][0] if ci > 0 else -1e9))
                    in_col_center = (cx0 <= pmid <= cx1)
                    score = (2.0 if in_col_right else 0.0) + (1.0 if in_col_center else 0.0) + ov + right_fit * 0.5 + center_dist * 0.1
                    if score > best_score:
                        best_score = score
                        best_ci = ci
                if best_ci is not None:
                    col_assigned_phrases[best_ci].append(p)

            cells = []
            for ci, (col_x0, col_x1) in enumerate(columns):
                phr_list = col_assigned_phrases.get(ci, [])
                if phr_list:
                    all_col_words = [w for phr in phr_list for w in phr]
                    all_col_words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                    txt = " ".join(w[4] for w in all_col_words).strip()
                    txt = re.sub(r'\$\s+', '$', txt)
                    c_bbox = BBox(min(w[0] for w in all_col_words), row_y0, max(w[2] for w in all_col_words), row_y1)
                else:
                    txt = ""
                    c_bbox = BBox(col_x0, row_y0, col_x1, row_y1)
                cells.append(Cell(
                    text=txt,
                    row_index=row_idx,
                    col_index=ci,
                    colspan=1,
                    rowspan=1,
                    bbox=c_bbox,
                ))
            cells.sort(key=lambda c: c.col_index)
            return cells

        # 3. 数据行处理 (Body rows)
        # 识别多列跨列大文本短语 (Description / Multi-column Spans)
        spanning_phrases: Dict[int, Tuple[int, int, str, BBox]] = {}
        assigned_word_ids = set()

        for p in phrases:
            px0 = min(w[0] for w in p)
            px1 = max(w[2] for w in p)
            p_center = (px0 + px1) / 2.0

            # 首先检查是否属于单列内容
            single_col = next((i for i, (cx0, cx1) in enumerate(columns) if cx0 - 5.0 <= px0 and px1 <= cx1 + 5.0), None)
            if single_col is not None:
                continue

            # 寻找跨列候选区间 [sc, ec]
            best_span = None
            best_dist = 9999.0
            for sc in range(len(columns)):
                for ec in range(sc + 1, len(columns)):
                    span_x0 = columns[sc][0]
                    span_x1 = columns[ec][1]
                    if px0 < span_x0 - 6.0 or px1 > span_x1 + 6.0:
                        continue
                    
                    other_in_span = any(
                        op is not p
                        and any(sc <= ci <= ec for ci in [next((i for i, (cx0, cx1) in enumerate(columns) if cx0 <= (ow[0] + ow[2]) / 2.0 < cx1), -1) for ow in op])
                        for op in phrases
                    )
                    if other_in_span:
                        continue

                    span_w = span_x1 - span_x0
                    span_center = (span_x0 + span_x1) / 2.0
                    max_dev = max(10.0, span_w * 0.15)
                    dist = abs(span_center - p_center)
                    is_left_aligned_span = (px0 <= span_x0 + 15.0 and px1 >= span_x0 + span_w * 0.5)
                    if (dist <= max_dev or is_left_aligned_span) and dist < best_dist:
                        best_dist = dist
                        best_span = (sc, ec)
            if best_span is not None:
                sc, ec = best_span
                txt = " ".join(w[4] for w in p).strip()
                txt = re.sub(r'\$\s+', '$', txt)
                spanning_phrases[sc] = (sc, ec, txt, BBox(columns[sc][0], row_y0, columns[ec][1], row_y1))
                for w in p:
                    assigned_word_ids.add(id(w))

        if len(spanning_phrases) == 1 and len(phrases) == 1:
            sc, ec, txt, bbox = list(spanning_phrases.values())[0]
            cells = []
            for ci in range(sc):
                cells.append(Cell(text="", row_index=row_idx, col_index=ci, colspan=1, rowspan=1, bbox=BBox(columns[ci][0], row_y0, columns[ci][1], row_y1)))
            cells.append(Cell(text=txt, row_index=row_idx, col_index=sc, colspan=ec - sc + 1, rowspan=1, bbox=bbox))
            for ci in range(ec + 1, len(columns)):
                cells.append(Cell(text="", row_index=row_idx, col_index=ci, colspan=1, rowspan=1, bbox=BBox(columns[ci][0], row_y0, columns[ci][1], row_y1)))
            return cells

        # 逐列分配数据词
        col_words: Dict[int, List[Tuple]] = defaultdict(list)
        for w in words:
            if id(w) in assigned_word_ids:
                continue
            w_mid = (w[0] + w[2]) / 2.0
            ci = next((i for i, c in enumerate(columns) if c[0] <= w_mid < c[1]), None)
            if ci is None:
                ci = 0 if w_mid < columns[0][0] else (len(columns) - 1)
            col_words[ci].append(w)

        cells = []
        skip_until = -1
        for ci in range(len(columns)):
            if ci <= skip_until:
                continue
            if ci in spanning_phrases:
                sc, ec, txt, bbox = spanning_phrases[ci]
                cells.append(Cell(
                    text=txt,
                    row_index=row_idx,
                    col_index=sc,
                    colspan=ec - sc + 1,
                    rowspan=1,
                    bbox=bbox,
                ))
                skip_until = ec
                continue

            cws = col_words.get(ci, [])
            if cws:
                cws.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
                is_pure_amount = not any(
                    w[4].strip().lower().rstrip('.,;:()') not in {
                        '$', '\u2009$', 'usd', 'eur', 'rmb', 'gbp', 'aud', 'cad', 'chf', 'hkd', 'sgd',
                        'm', 'b', 'k', 'mn', 'bn', 'in', 'million', 'millions', 'thousand', 'thousands', 'billion', 'billions',
                        '—', '-', '--', '(', ')', '%', 'n/m', 'nil', 'none'
                    }
                    for w in cws
                    if not any(ch.isdigit() for ch in w[4]) and w[4].strip().lower().rstrip('.,;:()')
                )
                if is_pure_amount:
                    dollar_words = [w for w in cws if ("$" in w[4] or w[4].strip() == "$")]
                    non_dollar_words = [w for w in cws if not ("$" in w[4] or w[4].strip() == "$")]
                    ordered_w = dollar_words + non_dollar_words if (dollar_words and non_dollar_words) else cws
                else:
                    ordered_w = cws
                cell_text = " ".join(w[4] for w in ordered_w)
                cell_text = cell_text.replace('\u2009', '')
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

    # 兼容历史别名
    _assign_words_to_zebra_columns = _assign_words_to_columns
    _normalize_zebra_headers = _normalize_headers

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
                if self._is_invisible_drawing(d):
                    continue
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
                if self._is_invisible_drawing(d):
                    continue
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

        # 检查并融合无数据对比关系的过拆拆分描述/地址列 (如 Form 10-Q 注册人信息表中的 multi-column prose)
        col_cells = defaultdict(list)
        for c in cells:
            for ci in range(c.col_index, c.col_index + c.colspan):
                col_cells[ci].append(c)

        merge_map = list(range(num_cols))
        for ci in range(num_cols - 1):
            c0_cells = col_cells[ci]
            c1_cells = col_cells[ci + 1]
            c1_texts = [c.text.strip() for c in c1_cells if c.text.strip()]
            c0_texts = [c.text.strip() for c in c0_cells if c.text.strip()]
            
            c1_has_pure_amount = any(
                any(ch.isdigit() for ch in txt) and any(kw in txt.lower() for kw in ('$', 'no.', 'code', 'zip', 'tel', 'fax', '%'))
                for txt in c1_texts
            )
            # 若右侧列不是独立的编号/金额/ZipCode列，且左侧为多行纯英文描述
            if c1_texts and c0_texts and not c1_has_pure_amount and not any(any(ch.isdigit() for ch in txt) for txt in c0_texts):
                # 将 ci+1 融合到 ci
                merge_map[ci + 1] = merge_map[ci]

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


__all__ = ["EnglishTableExtractor", "_RowData"]
