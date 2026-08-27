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


_PACKED_NUMERIC_FIELDS = re.compile(r"^[\s\d,().+\-–—−]+$")


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
    source_position = getattr(span, "source_position", (0, 0, span.order))
    characters = [
        {"text": char, "bbox": _bbox_list(box)}
        for char, box in span.characters
    ]
    return {
        "order": int(span.order),
        "source_position": list(source_position),
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
    if not _PACKED_NUMERIC_FIELDS.fullmatch(text) or len(char_boxes) < len(text):
        return [span]

    split_at = None
    for index, char in enumerate(text[:-1]):
        if not char.isspace() or text[index + 1].isspace():
            continue
        gap = char_boxes[index + 1]["bbox"][0] - char_boxes[index]["bbox"][2]
        if gap >= max(3.0, float(span.get("font_size") or 0) * 0.45):
            split_at = index + 1
            break
    if split_at is None:
        return [span]

    fragments: list[dict[str, Any]] = []
    block_index, line_index, span_index = span["source_position"]
    for fragment_index, (start, end) in enumerate(
        ((0, split_at), (split_at, len(text)))
    ):
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
                "source_fragment_count": 2,
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
