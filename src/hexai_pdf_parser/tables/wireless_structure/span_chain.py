"""Native-span normalization for wireless table structure recovery.

This module is intentionally independent from the production extractor.  It
adapts the current ``NativeSpan`` model to the traceable dictionary shape used
by the wireless recovery algorithms from ``feature-gangwei``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan


_PACKED_NUMERIC_FIELDS = re.compile(r"^[\s\d,().%+\-–—−]+$")


def _bbox_list(box: BBox) -> list[float]:
    return [box.x0, box.y0, box.x1, box.y1]


def _union(items: Iterable[dict[str, Any]]) -> list[float]:
    values = list(items)
    return [
        min(item["bbox"][0] for item in values),
        min(item["bbox"][1] for item in values),
        max(item["bbox"][2] for item in values),
        max(item["bbox"][3] for item in values),
    ]


def _native_dict(span: NativeSpan) -> dict[str, Any]:
    source_position = getattr(span, "source_position", None)
    source_position_known = source_position is not None
    if source_position is None:
        source_position = (0, 0, span.order)
    characters = [
        {"text": char, "bbox": _bbox_list(box)}
        for char, box in span.characters
    ]
    return {
        "order": int(span.order),
        "source_position": list(source_position),
        "source_position_known": source_position_known,
        "bbox": _bbox_list(span.bbox),
        "text": span.text.replace("\n", " ").strip(),
        "font": span.font or "",
        "font_size": float(span.size or 0),
        "bold": "bold" in (span.font or "").lower(),
        "object_id": getattr(span, "object_id", None),
        "char_boxes": characters,
    }


def _split_packed_numeric_fields(span: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(span.get("text", ""))
    char_boxes = list(span.get("char_boxes") or [])
    while char_boxes and str(char_boxes[0].get("text", "")).isspace():
        char_boxes.pop(0)
    while char_boxes and str(char_boxes[-1].get("text", "")).isspace():
        char_boxes.pop()
    if (
        not _PACKED_NUMERIC_FIELDS.fullmatch(text)
        or "".join(str(char.get("text", "")) for char in char_boxes) != text
    ):
        return [span]

    split_points = [0]
    gap_limit = max(2.5, float(span.get("font_size") or 0) * 0.35)
    index = 0
    while index < len(text):
        if not text[index].isspace():
            index += 1
            continue
        whitespace_start = index
        while index < len(text) and text[index].isspace():
            index += 1
        whitespace_end = index
        if whitespace_start == 0 or whitespace_end == len(text):
            continue
        gaps = [
            char_boxes[right]["bbox"][0] - char_boxes[right - 1]["bbox"][2]
            for right in range(whitespace_start, whitespace_end + 1)
        ]
        if max(gaps) >= gap_limit:
            split_points.append(whitespace_end)
    if len(split_points) == 1:
        return [span]
    split_points.append(len(text))

    fragments: list[dict[str, Any]] = []
    block_index, line_index, span_index = span["source_position"]
    ranges = list(zip(split_points, split_points[1:]))
    for fragment_index, (start, end) in enumerate(ranges):
        fragment_text = text[start:end].strip()
        glyph_boxes = [
            char_boxes[index]
            for index, char in enumerate(text[start:end], start)
            if not char.isspace()
        ]
        if not fragment_text or not glyph_boxes:
            return [span]
        fragments.append(
            {
                **span,
                "text": fragment_text,
                "bbox": _union(glyph_boxes),
                "char_boxes": glyph_boxes,
                "source_position": [
                    block_index,
                    line_index,
                    span_index * 100 + fragment_index * 2,
                ],
                "source_fragment_index": fragment_index,
                "source_fragment_count": len(ranges),
            }
        )
    return fragments


def region_spans(spans: Sequence[NativeSpan], region: BBox) -> list[dict[str, Any]]:
    """Normalize region spans while preserving native order and traceability."""
    normalized = []
    for span in spans:
        if not span.text.strip():
            continue
        center_x = (span.bbox.x0 + span.bbox.x1) / 2.0
        center_y = (span.bbox.y0 + span.bbox.y1) / 2.0
        if not (region.x0 <= center_x <= region.x1 and region.y0 <= center_y <= region.y1):
            continue
        normalized.extend(_split_packed_numeric_fields(_native_dict(span)))

    normalized.sort(key=lambda item: (item["order"], item.get("source_fragment_index", -1)))
    for flow, item in enumerate(normalized, 1):
        item["flow"] = flow
        if item.get("source_fragment_count", 1) > 1:
            item["span_ref"] = "S{0}.{1}".format(item["order"], item["source_fragment_index"] + 1)
        else:
            item["span_ref"] = "S{0}".format(item["order"])
    return normalized
