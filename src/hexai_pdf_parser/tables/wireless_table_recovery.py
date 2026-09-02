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

from hexai_pdf_parser.core.models import BBox, Cell, Table


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
    source_position: Tuple[int, int, int] | None = None


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
class NativeSpanPageSignal:
    """Recall-only evidence that a page contains repeated numeric columns."""

    bbox: BBox
    numeric_row_count: int
    stable_column_count: int
    labeled_row_count: int


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


def collect_native_spans(
    page: fitz.Page,
    excluded_regions: Sequence[BBox] | None = None,
    allowed_regions: Sequence[BBox] | None = None,
) -> List[NativeSpan]:
    """Return native spans in allowed regions and outside excluded regions."""

    footer_page_number = re.compile(
        r"^\s*\u7b2c\s*\d+\s*\u9875\s*/\s*\u5171\s*\d+\s*\u9875\s*$"
    )
    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    spans: List[NativeSpan] = []
    order = 0
    for block_index, block in enumerate(raw.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            line_text = "".join(
                char.get("c", "")
                for item in line.get("spans", [])
                for char in item.get("chars", [])
            )
            if (
                footer_page_number.match(line_text)
                and line["bbox"][1] >= page.rect.y0 + page.rect.height * 0.85
            ):
                continue
            for span_index, item in enumerate(line.get("spans", [])):
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
                        source_position=(block_index, line_index, span_index),
                    )
                )
                order += 1
    return [
        span
        for span in spans
        if (
            allowed_regions is None
            or any(
                region.x0 <= (span.bbox.x0 + span.bbox.x1) / 2.0 <= region.x1
                and region.y0 <= (span.bbox.y0 + span.bbox.y1) / 2.0 <= region.y1
                for region in allowed_regions
            )
        )
        and (
            not excluded_regions
            or not any(
                region.x0 <= (span.bbox.x0 + span.bbox.x1) / 2.0 <= region.x1
                and region.y0 <= (span.bbox.y0 + span.bbox.y1) / 2.0 <= region.y1
                for region in excluded_regions
            )
        )
    ]


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
    ordered_spans = sorted(
        spans,
        key=lambda span: (
            (span.bbox.y0 + span.bbox.y1) / 2.0,
            span.bbox.x0,
            span.order,
        ),
    )
    strips: List[TextStrip] = []
    current = TextStrip(
        text=ordered_spans[0].text,
        bbox=ordered_spans[0].bbox,
        spans=[ordered_spans[0]],
    )
    for span in ordered_spans[1:]:
        previous = current.spans[-1]
        size = max(previous.size or 0.0, span.size or 0.0, 6.0)
        gap = span.bbox.x0 - current.bbox.x1
        same_band = abs(((span.bbox.y0 + span.bbox.y1) / 2.0) - current.center_y) <= max(2.5, size * 0.38)
        close = -1.0 <= gap <= max(2.0, size * 0.28)
        attached_super = -1.0 <= gap <= max(3.0, size * 0.45) and _is_small_superscript(current, span)
        if (same_band and close) or attached_super:
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


def _detect_native_span_page_signal(
    strips: Sequence[TextStrip],
) -> NativeSpanPageSignal | None:
    """Detect repeated native-span numeric columns without building cells."""

    numeric_strips = [strip for strip in strips if _is_number(strip.text)]
    numeric_rows = [
        row for row in _row_cluster(numeric_strips) if len(row) >= 4
    ]
    if len(numeric_rows) < 3:
        return None

    widths = [
        strip.bbox.x1 - strip.bbox.x0
        for row in numeric_rows
        for strip in row
        if strip.bbox.x1 > strip.bbox.x0
    ]
    if not widths:
        return None
    anchor_tolerance = min(24.0, max(10.0, statistics.median(widths) * 0.35))

    anchors = [
        (
            strip.bbox.x1,
            row_index,
            strip,
        )
        for row_index, row in enumerate(numeric_rows)
        for strip in row
    ]
    anchors.sort(
        key=lambda item: (item[0], item[1], item[2].bbox.x0, item[2].order)
    )
    anchor_groups: List[List[Tuple[float, int, TextStrip]]] = []
    for anchor, row_index, strip in anchors:
        if not anchor_groups:
            anchor_groups.append([(anchor, row_index, strip)])
            continue
        previous = anchor_groups[-1]
        reference = statistics.median(item[0] for item in previous)
        if abs(anchor - reference) <= anchor_tolerance:
            previous.append((anchor, row_index, strip))
        else:
            anchor_groups.append([(anchor, row_index, strip)])

    tracks = [
        statistics.median(item[0] for item in group)
        for group in anchor_groups
        if len({item[1] for item in group}) >= 3
    ]
    if len(tracks) < 4:
        return None

    qualifying_rows: List[List[TextStrip]] = []
    for row in numeric_rows:
        assigned: set[int] = set()
        for strip in row:
            nearest = min(
                range(len(tracks)),
                key=lambda index: abs(strip.bbox.x1 - tracks[index]),
            )
            if abs(strip.bbox.x1 - tracks[nearest]) <= anchor_tolerance:
                assigned.add(nearest)
        if len(assigned) >= 4:
            qualifying_rows.append(row)
    if len(qualifying_rows) < 3:
        return None

    heights = [
        strip.bbox.y1 - strip.bbox.y0
        for strip in strips
        if strip.bbox.y1 > strip.bbox.y0
    ]
    median_height = statistics.median(heights) if heights else 10.0
    label_gap_limit = max(14.0, median_height * 2.5)
    labeled_row_count = 0
    evidence_boxes = [
        strip.bbox
        for row in qualifying_rows
        for strip in row
    ]
    for row in qualifying_rows:
        row_box = _union(strip.bbox for strip in row)
        numeric_left = min(strip.bbox.x0 for strip in row)
        nearby_labels = []
        for strip in strips:
            if _is_number(strip.text) or strip.bbox.x1 > numeric_left + 8.0:
                continue
            vertical_gap = max(
                row_box.y0 - strip.bbox.y1,
                strip.bbox.y0 - row_box.y1,
                0.0,
            )
            if vertical_gap <= label_gap_limit:
                nearby_labels.append(strip)
        if nearby_labels:
            labeled_row_count += 1
            evidence_boxes.extend(strip.bbox for strip in nearby_labels)

    return NativeSpanPageSignal(
        bbox=_union(evidence_boxes),
        numeric_row_count=len(qualifying_rows),
        stable_column_count=len(tracks),
        labeled_row_count=labeled_row_count,
    )


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
        currency_then_number = _is_number(strip.text) and any(
            item.text.strip() in _CURRENCY for _, item in previous
        )
        if not currency_then_number and abs(_anchor(strip) - previous_anchor) <= tolerance:
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


def _two_row_field_runs(rows: Sequence[Sequence[TextStrip]]) -> List[List[List[TextStrip]]]:
    """Recognize two adjacent field rows despite a shifting right column."""
    candidates: List[List[List[TextStrip]]] = []
    for first, second in zip(rows, rows[1:]):
        if len(first) != 2 or len(second) != 2:
            continue
        first_box = _union(strip.bbox for strip in first)
        second_box = _union(strip.bbox for strip in second)
        gap = second_box.y0 - first_box.y1
        left_aligned = abs(_anchor(first[0]) - _anchor(second[0])) <= 8.0
        separated = min(
            _anchor(first[1]) - _anchor(first[0]),
            _anchor(second[1]) - _anchor(second[0]),
        ) >= 180.0
        if (
            0 <= gap <= 24.0
            and left_aligned
            and separated
            and all(
                _looks_like_field(strip.text)
                for row in (first, second)
                for strip in row
            )
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


def _drop_orphan_field_before_title(rows: Sequence[Sequence[TextStrip]]) -> List[List[TextStrip]]:
    """Remove a trailing field from the previous table before a new title."""
    if len(rows) < 3:
        return [list(row) for row in rows]
    first, title, detail = rows[:3]
    title_box = _union(strip.bbox for strip in title)
    if (
        len(first) == 1
        and first[0].text.startswith("\u7ed3\u6848\u65e5\u671f")
        and len(title) >= 2
    ):
        return [list(row) for row in rows[1:]]
    if (
        len(first) == 1
        and _looks_like_field(first[0].text)
        and len(title) == 1
        and title_box.x1 - title_box.x0 <= 180.0
        and not _looks_like_field(title[0].text)
        and len(detail) >= 2
    ):
        return [list(row) for row in rows[1:]]
    return [list(row) for row in rows]


def _completion_date_continuations(
    rows: Sequence[Sequence[TextStrip]],
) -> List[Table]:
    """Recover a page-leading completion-date row as a one-row continuation."""
    tables: List[Table] = []
    for first, second in zip(rows, rows[1:]):
        if (
            len(first) != 1
            or not first[0].text.startswith("\u7ed3\u6848\u65e5\u671f")
            or len(second) < 2
        ):
            continue
        left = first[0]
        right_x = min(strip.bbox.x0 for strip in second[1:])
        right_edge = max(strip.bbox.x1 for strip in second)
        bbox = BBox(left.bbox.x0, left.bbox.y0, right_edge, left.bbox.y1)
        tables.append(
            Table(
                bbox=bbox,
                rows=1,
                cols=2,
                cells=[
                    Cell(left.text, 0, 0, BBox(bbox.x0, bbox.y0, right_x, bbox.y1)),
                    Cell("", 0, 1, BBox(right_x, bbox.y0, bbox.x1, bbox.y1)),
                ],
                confidence=0.80,
                source="wireless_span_recovery",
            )
        )
    return tables


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
    short_title_rows = {
        index
        for index, row in enumerate(normalized_rows[:-1])
        if len(row) == 1
        and len(normalized_rows[index + 1]) >= 2
        and row[0].bbox.x1 - row[0].bbox.x0 <= 180.0
        and not _looks_like_field(row[0].text)
    }
    spanning_single_rows = centered_single_rows | short_title_rows
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
        # Native PDF span order can differ from visual order when fields are
        # positioned independently on the same line.
        members.sort(key=lambda item: (item.bbox.y0, item.bbox.x0, item.order))
        bbox = _union(item.bbox for item in members)
        col_index = 0 if row_index in spanning_single_rows else col_map[original_column]
        # 一条 Span 横跨多个列轨迹时，以 colspan 作为基础合并单元格表示。
        covered = [
            col_map[column]
            for column in active_columns
            if bbox.x0 <= tracks[column] <= bbox.x1
        ]
        colspan = len(active_columns) if row_index in spanning_single_rows else max(1, len(covered))
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


def _significant_overlap(left: BBox, right: BBox) -> bool:
    """Return whether two candidates cover substantially the same table."""
    width = min(left.x1, right.x1) - max(left.x0, right.x0)
    height = min(left.y1, right.y1) - max(left.y0, right.y0)
    if width <= 0 or height <= 0:
        return False
    overlap = width * height
    left_area = (left.x1 - left.x0) * (left.y1 - left.y0)
    right_area = (right.x1 - right.x0) * (right.y1 - right.y0)
    return overlap / min(left_area, right_area) >= 0.20


def _table_quality(table: Table) -> tuple[float, int, int]:
    """Rank overlapping candidates by confidence, populated cells and size."""
    populated = sum(1 for cell in table.cells if cell.text.strip())
    return (table.confidence, populated, table.rows * table.cols)


def recover_wireless_tables(
    page: fitz.Page,
    excluded_regions: Sequence[BBox] | None = None,
    allowed_regions: Sequence[BBox] | None = None,
) -> WirelessRecovery:
    """Recover borderless tables from a native PDF page and retain evidence."""

    spans = collect_native_spans(
        page,
        excluded_regions=excluded_regions,
        allowed_regions=allowed_regions,
    )
    strips = merge_text_strips(spans)
    page_signal = _detect_native_span_page_signal(strips)
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
    ] + [
        ("two_row_fields", run) for run in _two_row_field_runs(visual_rows)
    ]
    seen_boxes: List[BBox] = []
    accepted_region_indexes: List[int] = []
    for run_type, run in tagged_runs:
        if run_type in {"field_records", "two_line_field_records"}:
            expanded = run
        elif run_type in {"single_field_record", "two_row_fields"}:
            expanded = _prepend_short_title(run, visual_rows)
        else:
            expanded = _prepend_headers(run, visual_rows)
        expanded = _drop_orphan_field_before_title(expanded)
        tracks_override = None
        if run_type in {"single_field_record", "two_row_fields"}:
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
        overlapping_indexes = [
            index
            for index, old in enumerate(seen_boxes)
            if _significant_overlap(table.bbox, old)
        ]
        if overlapping_indexes and not all(
            _table_quality(table) > _table_quality(tables[index])
            for index in overlapping_indexes
        ):
            evidence["rejected_reason"] = "overlaps an accepted table candidate"
            regions.append(evidence)
            continue
        for index in reversed(overlapping_indexes):
            replaced_region = regions[accepted_region_indexes[index]]
            replaced_region["rejected_reason"] = (
                "replaced by a higher-quality overlapping table candidate"
            )
            del tables[index]
            del seen_boxes[index]
            del accepted_region_indexes[index]
        evidence["bbox"] = table.bbox.__dict__
        evidence["cells"] = [
            {"row": cell.row_index, "col": cell.col_index, "text": cell.text, "bbox": cell.bbox.__dict__}
            for cell in table.cells
        ]
        tables.append(table)
        seen_boxes.append(table.bbox)
        regions.append(evidence)
        accepted_region_indexes.append(len(regions) - 1)
    diagnostics = {
        "page_index": page.number,
        "excluded_regions": [region.__dict__ for region in (excluded_regions or [])],
        "allowed_regions": [region.__dict__ for region in (allowed_regions or [])],
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
        "page_signal": {
            "matched": page_signal is not None,
            "bbox": page_signal.bbox.__dict__ if page_signal else None,
            "numeric_row_count": page_signal.numeric_row_count if page_signal else 0,
            "stable_column_count": page_signal.stable_column_count if page_signal else 0,
            "labeled_row_count": page_signal.labeled_row_count if page_signal else 0,
        },
        "regions": regions,
    }
    for table in _completion_date_continuations(visual_rows):
        if any(_significant_overlap(table.bbox, old) for old in seen_boxes):
            continue
        tables.append(table)
        seen_boxes.append(table.bbox)
        diagnostics["regions"].append(
            {
                "run_type": "completion_date_continuation",
                "bbox": table.bbox.__dict__,
                "row_count": table.rows,
                "column_count": table.cols,
                "confidence": table.confidence,
            }
        )
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
