"""中文使用说明：原生 PDF 无线表格恢复模块。

用途：保留 ``rawdict`` Span 的原始顺序、坐标、字体和字号，合并连续文本条，
再按视觉行和空间列轨迹恢复二维单元格；不确定候选会保留诊断证据。本模块
独立于 Pipeline，不改变现有处理流程。

PowerShell 最小运行方式（页码从 0 开始）：
``$env:PYTHONPATH = 'src'`` 后执行
``python -m hexai_pdf_parser.wireless_table_recovery 输入.pdf --output 输出目录 --pages 2 3``。
输出每页的 PNG 覆盖图、HTML 结构表和 JSON 诊断文件。激活 ``company_tool``
环境后可直接使用 ``python``。

Recover borderless tables from the native PDF span stream.

The existing table extractors work primarily from words or ruled grids.  This
module deliberately keeps the order emitted by the PDF's ``rawdict`` spans and
uses geometry only to turn that ordered stream into visual text strips, rows,
and columns.  It is intentionally self-contained so callers can inspect its
evidence without changing the main processing pipeline.

中文说明：本模块不改变 Pipeline；只把 PDF 原始 Span 输出顺序与空间坐标
转换为可审计的无线表格结构，无法确定时保留诊断证据给人工复核。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import fitz

from hexai_pdf_parser.models import BBox, Cell, Table


_CURRENCY = {"$", "¥", "￥", "€", "£", "₹"}


@dataclass
class NativeSpan:
    """One raw PDF span, in the exact traversal order from ``rawdict``."""

    text: str
    bbox: BBox
    font: str | None
    size: float | None
    order: int
    characters: List[Tuple[str, BBox]] = field(default_factory=list)


@dataclass
class TextStrip:
    """Conservatively merged adjacent native spans used for table recovery."""

    text: str
    bbox: BBox
    spans: List[NativeSpan] = field(default_factory=list)

    @property
    def order(self) -> int:
        return self.spans[0].order

    @property
    def center_y(self) -> float:
        return (self.bbox.y0 + self.bbox.y1) / 2.0


@dataclass
class WirelessRecovery:
    """Recovered tables plus JSON-serializable evidence for review."""

    tables: List[Table]
    diagnostics: Dict[str, Any]


def _union(items: Iterable[BBox]) -> BBox:
    boxes = list(items)
    return BBox(
        min(box.x0 for box in boxes),
        min(box.y0 for box in boxes),
        max(box.x1 for box in boxes),
        max(box.y1 for box in boxes),
    )


def collect_native_spans(page: fitz.Page) -> List[NativeSpan]:
    """Return non-empty raw spans while preserving PDF output order and style."""

    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    spans: List[NativeSpan] = []
    order = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for item in line.get("spans", []):
                text = "".join(char.get("c", "") for char in item.get("chars", []))
                if not text.strip():
                    continue
                spans.append(
                    NativeSpan(
                        text=text,
                        bbox=BBox(*item["bbox"]),
                        font=item.get("font"),
                        size=item.get("size"),
                        order=order,
                        characters=[
                            (char.get("c", ""), BBox(*char["bbox"]))
                            for char in item.get("chars", [])
                            if char.get("c", "")
                        ],
                    )
                )
                order += 1
    return spans


def _is_small_superscript(current: TextStrip, candidate: NativeSpan) -> bool:
    base_size = current.spans[-1].size or 0.0
    candidate_size = candidate.size or 0.0
    return (
        candidate_size > 0
        and base_size > 0
        and candidate_size <= base_size * 0.82
        and candidate.bbox.y0 < current.bbox.y0 + base_size * 0.35
    )


def _split_raw_field_strip(strip: TextStrip) -> List[TextStrip]:
    """Use raw character boxes to expose fields hidden by long PDF spaces."""

    if len(strip.spans) != 1:
        return [strip]
    span = strip.spans[0]
    if not span.characters:
        return [strip]
    text = span.text
    boundaries = list(re.finditer(r"\s{3,}", text))
    if not boundaries:
        return [strip]
    parts: List[Tuple[str, BBox]] = []
    start = 0
    for boundary in [*boundaries, None]:
        end = boundary.start() if boundary is not None else len(text)
        value = text[start:end].strip()
        boxes = [box for char, box in span.characters[start:end] if not char.isspace()]
        if value and boxes:
            parts.append((value, _union(boxes)))
        start = boundary.end() if boundary is not None else len(text)
    if len(parts) < 2 or not all(_looks_like_field(value) for value, _ in parts):
        return [strip]
    return [TextStrip(text=value, bbox=bbox, spans=[span]) for value, bbox in parts]


def merge_text_strips(spans: Sequence[NativeSpan]) -> List[TextStrip]:
    """Merge only consecutive, close spans on one text strip.

    The small horizontal threshold purposely prevents a span in the next visual
    column from being concatenated.  It still joins font splits, superscripts,
    and tightly attached currency/amount fragments.
    """

    # 合并阈值故意保守：宁可保留列间空隙，也不要误把相邻列拼成一个单元格。
    if not spans:
        return []
    strips: List[TextStrip] = []
    current = TextStrip(text=spans[0].text, bbox=spans[0].bbox, spans=[spans[0]])
    for span in spans[1:]:
        previous = current.spans[-1]
        size = max(previous.size or 0.0, span.size or 0.0, 6.0)
        gap = span.bbox.x0 - current.bbox.x1
        same_band = abs(((span.bbox.y0 + span.bbox.y1) / 2.0) - current.center_y) <= max(2.5, size * 0.38)
        close = -1.0 <= gap <= max(2.0, size * 0.28)
        attached_super = -1.0 <= gap <= max(3.0, size * 0.45) and _is_small_superscript(current, span)
        if span.order == previous.order + 1 and (same_band and close or attached_super):
            current.text += span.text
            current.bbox = _union([current.bbox, span.bbox])
            current.spans.append(span)
        else:
            strips.append(current)
            current = TextStrip(text=span.text, bbox=span.bbox, spans=[span])
    strips.append(current)
    return [piece for strip in strips for piece in _split_raw_field_strip(strip)]


def _is_number(text: str) -> bool:
    value = text.strip().replace(",", "").replace(" ", "")
    if value[:1] in _CURRENCY:
        value = value[1:]
    try:
        float(value.replace("(", "-").replace(")", ""))
        return any(char.isdigit() for char in value)
    except ValueError:
        return False


def _looks_like_field(text: str) -> bool:
    """字段键值行不是换行续写，例如“诉讼标的金额：700,000”。"""

    return ":" in text or "：" in text


def _split_wide_field_strip(strip: TextStrip, tracks: Sequence[float]) -> List[TextStrip]:
    """Split one raw span only when wide whitespace clearly hides field columns.

    Some native PDFs emit two independently positioned fields as one Span with
    a long run of spaces.  The raw Span remains intact in diagnostics; this
    function creates temporary geometry for cell assignment only.  Requiring
    field labels and exactly one part per established track keeps prose and
    normal text strips from being split.
    """

    parts = [part.strip() for part in re.split(r"\s{3,}", strip.text.strip()) if part.strip()]
    if len(parts) < 2 or len(parts) != len(tracks) or not all(_looks_like_field(part) for part in parts):
        return [strip]
    result: List[TextStrip] = []
    for index, part in enumerate(parts):
        x0 = tracks[index]
        x1 = tracks[index + 1] - 1.0 if index + 1 < len(parts) else strip.bbox.x1
        result.append(
            TextStrip(
                text=part,
                bbox=BBox(x0, strip.bbox.y0, max(x0 + 1.0, x1), strip.bbox.y1),
                spans=list(strip.spans),
            )
        )
    return result


def _row_cluster(strips: Sequence[TextStrip]) -> List[List[TextStrip]]:
    """Cluster strips into visual rows, keeping source order inside each row."""

    if not strips:
        return []
    sizes = [span.size for strip in strips for span in strip.spans if span.size]
    median_size = statistics.median(sizes) if sizes else 10.0
    tolerance = max(3.5, median_size * 0.48)
    rows: List[List[TextStrip]] = []
    centers: List[float] = []
    for strip in sorted(strips, key=lambda item: (item.center_y, item.bbox.x0, item.order)):
        if not rows or abs(strip.center_y - centers[-1]) > tolerance:
            rows.append([strip])
            centers.append(strip.center_y)
        else:
            rows[-1].append(strip)
            centers[-1] = sum(item.center_y for item in rows[-1]) / len(rows[-1])
    for row in rows:
        row.sort(key=lambda item: (item.bbox.x0, item.order))
    return rows


def merge_wrapped_rows(rows: Sequence[Sequence[TextStrip]]) -> List[List[TextStrip]]:
    """Merge sparse, close continuation lines back into their visual row.

    Only a row that is sparser than a preceding multi-column row may be a
    continuation.  Each of its strips must horizontally fall in an occupied
    preceding column, which avoids merging a genuine following record.
    """

    if len(rows) < 2:
        return [list(row) for row in rows]
    heights = [strip.bbox.y1 - strip.bbox.y0 for row in rows for strip in row]
    gap_limit = max(12.0, (statistics.median(heights) if heights else 10.0) * 1.45)
    merged: List[List[TextStrip]] = [list(rows[0])]
    for row in rows[1:]:
        current = merged[-1]
        previous_box = _union(strip.bbox for strip in current)
        row_box = _union(strip.bbox for strip in row)
        close = 0 <= row_box.y0 - previous_box.y1 <= gap_limit
        sparse = len(current) >= 2 and len(row) < len(current)
        centered_section_title = (
            len(row) == 1
            and abs((row_box.x0 + row_box.x1 - previous_box.x0 - previous_box.x1) / 2.0)
            <= max(18.0, (previous_box.x1 - previous_box.x0) * 0.12)
        )
        aligned = all(
            any(
                strip.bbox.x1 >= existing.bbox.x0 - 8.0
                and strip.bbox.x0 <= existing.bbox.x1 + 8.0
                for existing in current
            )
            for strip in row
        )
        # 续行通常为描述文字；数值行保持独立，避免吞掉下一条记录。
        continuation = (
            close
            and sparse
            and aligned
            and not centered_section_title
            and not any(_is_number(strip.text) for strip in row)
            and not any(_looks_like_field(strip.text) for strip in row)
        )
        if continuation:
            current.extend(row)
            current.sort(key=lambda item: (item.bbox.x0, item.order))
        else:
            merged.append(list(row))
    return merged


def _anchor(strip: TextStrip) -> float:
    """Numbers use their right edge; labels use their left edge as column tracks."""

    return strip.bbox.x1 if _is_number(strip.text) else strip.bbox.x0


def _column_tracks(rows: Sequence[Sequence[TextStrip]]) -> List[float]:
    # 文本左沿、数值右沿分别作为列轨迹，兼顾标签列与金额右对齐列。
    """Cluster repeated interval overlap before choosing each column track.

    A centered header and left-aligned data can have different left edges while
    their bounding boxes still occupy the same column.  Full-width strips are
    ignored here because they are titles or multi-field raw spans and would
    otherwise bridge independent columns.
    """

    entries = [
        (row_index, strip)
        for row_index, row in enumerate(rows)
        for strip in row
        if len(row) >= 2 and strip.bbox.x1 - strip.bbox.x0 < 350.0
    ]
    if not entries:
        return []
    widths = [strip.bbox.x1 - strip.bbox.x0 for _, strip in entries]
    tolerance = max(10.0, statistics.median(widths) * 0.42)
    entries.sort(key=lambda item: (_anchor(item[1]), item[1].bbox.x0))
    groups: List[List[Tuple[int, TextStrip]]] = []
    for row_index, strip in entries:
        if not groups:
            groups.append([(row_index, strip)])
            continue
        previous = groups[-1]
        previous_anchor = statistics.median(_anchor(item) for _, item in previous)
        overlaps_previous = any(
            strip.bbox.x1 >= item.bbox.x0 - 2.0 and strip.bbox.x0 <= item.bbox.x1 + 2.0
            for _, item in previous
        )
        currency_then_number = _is_number(strip.text) and any(
            item.text.strip() in _CURRENCY for _, item in previous
        )
        if not currency_then_number and (
            abs(_anchor(strip) - previous_anchor) <= tolerance or overlaps_previous
        ):
            previous.append((row_index, strip))
        else:
            groups.append([(row_index, strip)])

    tracks: List[float] = []
    for group in groups:
        support = len({row_index for row_index, _ in group})
        if support >= 2:
            tracks.append(statistics.median(_anchor(strip) for _, strip in group))
    return tracks


def _assign_column(strip: TextStrip, tracks: Sequence[float]) -> int:
    return min(range(len(tracks)), key=lambda index: abs(_anchor(strip) - tracks[index]))


def _table_runs(rows: Sequence[Sequence[TextStrip]]) -> List[List[List[TextStrip]]]:
    """Find compact consecutive runs that repeat at least two visual columns."""

    if not rows:
        return []
    row_boxes = [_union(item.bbox for item in row) for row in rows]
    heights = [box.y1 - box.y0 for box in row_boxes]
    gap_limit = max(30.0, (statistics.median(heights) if heights else 10.0) * 2.4)
    runs: List[List[List[TextStrip]]] = []
    current: List[List[TextStrip]] = []
    for index, row in enumerate(rows):
        multiple_items = len(row) >= 2
        row_box = _union(strip.bbox for strip in row)
        field_only_row = len(row) == 1 and any(_looks_like_field(strip.text) for strip in row)
        full_width_field = field_only_row and row_box.x1 - row_box.x0 >= 350.0
        close_to_previous = index == 0 or row_boxes[index].y0 - row_boxes[index - 1].y1 <= gap_limit
        # 左侧单字段行是结构中的一整行；保留它，但满宽字段行标记新记录，
        # 不能把它接到上一条记录后面。
        if (multiple_items or (field_only_row and current and not full_width_field)) and close_to_previous:
            current.append(row)
        else:
            if sum(len(item) >= 2 for item in current) >= 2:
                runs.append(current)
            current = [row] if multiple_items else []
    if sum(len(item) >= 2 for item in current) >= 2:
        runs.append(current)
    return runs


def _field_record_runs(rows: Sequence[Sequence[TextStrip]]) -> List[List[List[TextStrip]]]:
    """Recover repeated key-value records with intermittent one-column rows.

    A common native-PDF pattern is: a full-width first row, a two-column row,
    a left-only amount row, then another two-column row.  It has a stable
    two-column track, but the generic multi-column run detector would split it
    at the left-only row.  Each record remains a separate table candidate.
    """

    candidates: List[List[List[TextStrip]]] = []
    index = 0
    while index + 3 < len(rows):
        first, second, third, fourth = rows[index:index + 4]
        first_box = _union(strip.bbox for strip in first)
        gaps = [
            _union(strip.bbox for strip in after).y0 - _union(strip.bbox for strip in before).y1
            for before, after in ((first, second), (second, third), (third, fourth))
        ]
        is_full_width_first = len(first) == 1 and first_box.x1 - first_box.x0 >= 350.0
        split_field_first = len(first) >= 2 and all(_looks_like_field(strip.text) for strip in first)
        is_record = (
            (is_full_width_first or split_field_first)
            and len(second) >= 2
            and len(third) == 1
            and len(fourth) >= 2
            and all(0 <= gap <= 24.0 for gap in gaps)
        )
        if is_record:
            candidates.append([list(first), list(second), list(third), list(fourth)])
            index += 4
        else:
            index += 1
    return candidates


def _two_line_field_record_runs(rows: Sequence[Sequence[TextStrip]]) -> List[List[List[TextStrip]]]:
    """Group repeated full-width-field + two-column-detail records.

    The gap between records is allowed to be wider than the gap inside one
    record, so a third repeated record is not silently dropped.
    """

    def is_pair(first: Sequence[TextStrip], second: Sequence[TextStrip]) -> bool:
        box = _union(strip.bbox for strip in first)
        gap = _union(strip.bbox for strip in second).y0 - box.y1
        return (
            len(first) == 1
            and box.x1 - box.x0 >= 350.0
            and any(_looks_like_field(strip.text) for strip in first)
            and len(second) >= 2
            and 0 <= gap <= 24.0
        )

    candidates: List[List[List[TextStrip]]] = []
    index = 0
    while index + 1 < len(rows):
        if not is_pair(rows[index], rows[index + 1]):
            index += 1
            continue
        grouped: List[List[TextStrip]] = [list(rows[index]), list(rows[index + 1])]
        cursor = index + 2
        while cursor + 1 < len(rows) and is_pair(rows[cursor], rows[cursor + 1]):
            prior_bottom = _union(strip.bbox for strip in grouped[-1]).y1
            next_top = _union(strip.bbox for strip in rows[cursor]).y0
            if next_top - prior_bottom > 42.0:
                break
            grouped.extend([list(rows[cursor]), list(rows[cursor + 1])])
            cursor += 2
        if len(grouped) >= 4:
            candidates.append(grouped)
            index = cursor
        else:
            index += 1
    return candidates


def _single_field_record_runs(rows: Sequence[Sequence[TextStrip]]) -> List[List[List[TextStrip]]]:
    """Recognize one sparse, two-column field record without broadening normal runs.

    A number of credit-report sections contain exactly one full-width field line
    followed by a single left/right detail line.  The normal track estimator
    deliberately requires repeated support and therefore (correctly) rejects
    this shape unless this narrowly-scoped fallback supplies its two tracks.
    """

    candidates: List[List[List[TextStrip]]] = []
    for first, second in zip(rows, rows[1:]):
        first_box = _union(strip.bbox for strip in first)
        second_box = _union(strip.bbox for strip in second)
        gap = second_box.y0 - first_box.y1
        if (
            len(first) == 1
            and first_box.x1 - first_box.x0 >= 350.0
            and any(_looks_like_field(strip.text) for strip in first)
            and len(second) >= 2
            and 0 <= gap <= 24.0
        ):
            candidates.append([list(first), list(second)])
    return candidates


def _prepend_short_title(run: List[List[TextStrip]], all_rows: Sequence[Sequence[TextStrip]]) -> List[List[TextStrip]]:
    """Keep only a nearby short section title with a sparse single-record table."""

    first_strip_order = run[0][0].order
    first = next(index for index, row in enumerate(all_rows) if row and row[0].order == first_strip_order)
    if first == 0:
        return run
    title = all_rows[first - 1]
    title_box = _union(strip.bbox for strip in title)
    table_top = _union(strip.bbox for strip in run[0]).y0
    if len(title) == 1 and title_box.x1 - title_box.x0 <= 180.0 and 0 <= table_top - title_box.y1 <= 24.0:
        return [list(title), *run]
    return run


def _prepend_headers(run: List[List[TextStrip]], all_rows: Sequence[Sequence[TextStrip]]) -> List[List[TextStrip]]:
    first = next(index for index, row in enumerate(all_rows) if row is run[0])
    if first == 0:
        return run
    result = list(run)
    table_box = _union(strip.bbox for row in run for strip in row)
    for prior in reversed(all_rows[max(0, first - 2):first]):
        # 多列行已经是前一张表的正文，不能作为下一张表的表头带回去。
        if len(prior) >= 2:
            break
        prior_box = _union(strip.bbox for strip in prior)
        vertical_gap = result[0][0].bbox.y0 - prior_box.y1
        overlaps_table_width = prior_box.x1 >= table_box.x0 and prior_box.x0 <= table_box.x1
        if vertical_gap <= 28.0 and overlaps_table_width:
            result.insert(0, list(prior))
    return result


def _build_table(
    rows: Sequence[Sequence[TextStrip]], tracks_override: Sequence[float] | None = None
) -> Tuple[Table | None, Dict[str, Any]]:
    tracks = list(tracks_override) if tracks_override is not None else _column_tracks(rows)
    evidence: Dict[str, Any] = {"column_tracks": tracks}
    if len(rows) < 2 or len(tracks) < 2:
        evidence["rejected_reason"] = "insufficient repeated visual rows or columns"
        return None, evidence

    normalized_rows = [
        [piece for strip in row for piece in _split_wide_field_strip(strip, tracks)]
        for row in rows
    ]
    table_box = _union(strip.bbox for row in normalized_rows for strip in row)
    table_center = (table_box.x0 + table_box.x1) / 2.0
    centered_single_rows = {
        index
        for index, row in enumerate(normalized_rows)
        if len(row) == 1
        and abs((row[0].bbox.x0 + row[0].bbox.x1) / 2.0 - table_center)
        <= max(32.0, (table_box.x1 - table_box.x0) * 0.18)
    }
    grouped: Dict[Tuple[int, int], List[TextStrip]] = {}
    for row_index, row in enumerate(normalized_rows):
        for strip in row:
            col_index = _assign_column(strip, tracks)
            grouped.setdefault((row_index, col_index), []).append(strip)

    active_columns = sorted({column for _, column in grouped})
    if len(active_columns) < 2:
        evidence["rejected_reason"] = "one occupied column after assignment"
        return None, evidence
    col_map = {column: index for index, column in enumerate(active_columns)}
    cells: List[Cell] = []
    for (row_index, original_column), members in grouped.items():
        members.sort(key=lambda item: item.order)
        bbox = _union(item.bbox for item in members)
        col_index = 0 if row_index in centered_single_rows else col_map[original_column]
        # 一条 Span 横跨多个列轨迹时，以 colspan 作为基础合并单元格表示。
        covered = [
            col_map[column]
            for column in active_columns
            if bbox.x0 <= tracks[column] <= bbox.x1
        ]
        colspan = len(active_columns) if row_index in centered_single_rows else max(1, len(covered))
        cells.append(
            Cell(
                # 同一逻辑单元格的下一视觉行以换行保留，便于下游审计。
                text="".join(
                    ("\n" if index and item.bbox.y0 > members[index - 1].bbox.y1 + 1.0 else "")
                    + item.text
                    for index, item in enumerate(members)
                ).strip(),
                row_index=row_index,
                col_index=col_index,
                bbox=bbox,
                colspan=colspan,
            )
        )
    bbox = _union(cell.bbox for cell in cells)
    support = sum(1 for row in rows if len(row) >= 2)
    confidence = min(0.95, 0.5 + 0.15 * min(3, support - 1) + 0.05 * min(3, len(active_columns) - 2))
    evidence.update(
        {
            "active_column_tracks": [tracks[index] for index in active_columns],
            "row_count": len(rows),
            "column_count": len(active_columns),
            "confidence": confidence,
        }
    )
    return Table(
        bbox=bbox,
        rows=len(rows),
        cols=len(active_columns),
        cells=cells,
        confidence=confidence,
        source="wireless_span_recovery",
    ), evidence


def recover_wireless_tables(page: fitz.Page) -> WirelessRecovery:
    """Recover borderless tables from a native PDF page and retain evidence."""

    spans = collect_native_spans(page)
    strips = merge_text_strips(spans)
    visual_rows = merge_wrapped_rows(_row_cluster(strips))
    tables: List[Table] = []
    regions: List[Dict[str, Any]] = []
    candidate_runs = _table_runs(visual_rows)
    tagged_runs: List[Tuple[str, List[List[TextStrip]]]] = [
        ("two_line_field_records", run)
        for run in _two_line_field_record_runs(visual_rows)
    ] + [
        ("field_records", run) for run in _field_record_runs(visual_rows)
    ] + [("aligned_rows", run) for run in candidate_runs] + [
        ("single_field_record", run) for run in _single_field_record_runs(visual_rows)
    ]
    seen_boxes: List[BBox] = []
    for run_type, run in tagged_runs:
        if run_type in {"field_records", "two_line_field_records"}:
            expanded = run
        elif run_type == "single_field_record":
            expanded = _prepend_short_title(run, visual_rows)
        else:
            expanded = _prepend_headers(run, visual_rows)
        tracks_override = None
        if run_type == "single_field_record":
            detail_row = next(row for row in expanded if len(row) >= 2)
            tracks_override = sorted(_anchor(strip) for strip in detail_row)
        table, evidence = _build_table(expanded, tracks_override=tracks_override)
        evidence["run_type"] = run_type
        evidence["rows"] = [
            {"x0": _union(item.bbox for item in row).x0, "y0": _union(item.bbox for item in row).y0,
             "x1": _union(item.bbox for item in row).x1, "y1": _union(item.bbox for item in row).y1}
            for row in expanded
        ]
        if table is None:
            regions.append(evidence)
            continue
        if any(
            min(table.bbox.x1, old.x1) > max(table.bbox.x0, old.x0)
            and min(table.bbox.y1, old.y1) > max(table.bbox.y0, old.y0)
            for old in seen_boxes
        ):
            evidence["rejected_reason"] = "overlaps an accepted table candidate"
            regions.append(evidence)
            continue
        evidence["bbox"] = table.bbox.__dict__
        evidence["cells"] = [
            {"row": cell.row_index, "col": cell.col_index, "text": cell.text, "bbox": cell.bbox.__dict__}
            for cell in table.cells
        ]
        tables.append(table)
        seen_boxes.append(table.bbox)
        regions.append(evidence)
    diagnostics = {
        "page_index": page.number,
        "native_spans": [
            {
                "order": span.order,
                "text": span.text,
                "bbox": span.bbox.__dict__,
                "font": span.font,
                "size": span.size,
                "characters": [
                    {"text": char, "bbox": bbox.__dict__}
                    for char, bbox in span.characters
                ],
            }
            for span in spans
        ],
        "merged_strips": [
            {"order": strip.order, "text": strip.text, "bbox": strip.bbox.__dict__, "span_orders": [span.order for span in strip.spans]}
            for strip in strips
        ],
        "regions": regions,
    }
    if not candidate_runs:
        diagnostics["rejected_reason"] = "no consecutive multi-column visual rows"
    return WirelessRecovery(tables=tables, diagnostics=diagnostics)


def _table_html(table: Table) -> str:
    rows: List[str] = []
    for row_index in range(table.rows):
        cells = []
        for cell in sorted((item for item in table.cells if item.row_index == row_index), key=lambda item: item.col_index):
            attrs = ""
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            cells.append(f"<td{attrs}>{html.escape(cell.text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def export_wireless_debug(page: fitz.Page, recovery: WirelessRecovery, output_dir: str, dpi: int = 160) -> Dict[str, str]:
    """Write JSON evidence, an HTML grid, and a non-mutating PNG overlay."""

    os.makedirs(output_dir, exist_ok=True)
    stem = f"page-{page.number:03d}-wireless"
    json_path = os.path.join(output_dir, stem + ".json")
    html_path = os.path.join(output_dir, stem + ".html")
    image_path = os.path.join(output_dir, stem + ".png")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(recovery.diagnostics, handle, ensure_ascii=False, indent=2)
    table_markup = "".join(_table_html(table) for table in recovery.tables) or "<p>未恢复出可信表格。</p>"
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write("<!doctype html><meta charset='utf-8'><style>body{font-family:Arial,sans-serif;padding:20px}table{border-collapse:collapse;margin:0 0 20px}td{border:1px solid #999;padding:4px 8px;vertical-align:top}</style>" + table_markup)

    overlay = fitz.open()
    try:
        overlay_page = overlay.new_page(width=page.rect.width, height=page.rect.height)
        overlay_page.show_pdf_page(overlay_page.rect, page.parent, page.number)
        for table in recovery.tables:
            overlay_page.draw_rect(fitz.Rect(table.bbox.x0, table.bbox.y0, table.bbox.x1, table.bbox.y1), color=(0.62, 0.20, 0.89), width=1.5, overlay=True)
            for cell in table.cells:
                overlay_page.draw_rect(fitz.Rect(cell.bbox.x0, cell.bbox.y0, cell.bbox.x1, cell.bbox.y1), color=(0.05, 0.55, 0.95), width=0.8, overlay=True)
        pix = overlay_page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        pix.save(image_path)
    finally:
        overlay.close()
    return {"json": json_path, "html": html_path, "image": image_path}


def main() -> int:
    """Minimal entry point for inspecting native-PDF wireless table recovery."""

    parser = argparse.ArgumentParser(description="Recover borderless tables from native PDF spans.")
    parser.add_argument("pdf_path")
    parser.add_argument("--output", "-o", default="wireless-debug")
    parser.add_argument("--pages", type=int, nargs="*", help="0-based page indexes; defaults to every page")
    parser.add_argument("--dpi", type=int, default=160)
    args = parser.parse_args()
    with fitz.open(args.pdf_path) as document:
        indexes = args.pages if args.pages is not None else range(len(document))
        for index in indexes:
            recovery = recover_wireless_tables(document[index])
            paths = export_wireless_debug(document[index], recovery, args.output, args.dpi)
            print(json.dumps({"page": index, "tables": len(recovery.tables), **paths}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
