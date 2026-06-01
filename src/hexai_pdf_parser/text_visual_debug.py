"""Debug helpers for visualizing text words, fragments, and rows."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Sequence

import fitz

from hexai_pdf_parser.models import BBox
from hexai_pdf_parser.text_region_detector import (
    CandidateRegion,
    HorizontalSeparator,
    detect_candidate_regions,
)


@dataclass
class TextWord:
    """Normalized word-level text item from ``page.get_text("words")``."""

    text: str
    bbox: BBox


@dataclass
class TextFragment:
    """Merged short phrase inside a single visual band."""

    text: str
    bbox: BBox | tuple[float, float, float, float]

    def __post_init__(self) -> None:
        if not isinstance(self.bbox, BBox):
            self.bbox = BBox(*self.bbox)


@dataclass
class VisualRow:
    """Visual text row composed of one or more fragments."""

    fragments: list[TextFragment]
    bbox: BBox


def make_text_fragments(words: Sequence[tuple]) -> list[TextFragment]:
    """Merge nearby words inside each visual band into conservative fragments."""
    word_items = _normalize_words(words)
    if not word_items:
        return []

    fragments: list[TextFragment] = []
    for band in _group_items_into_bands(word_items):
        if not band:
            continue
        band_height = median(_bbox_height(word.bbox) for word in band)
        current = [band[0]]
        for word in band[1:]:
            if _should_merge_words(current[-1], word, band_height):
                current.append(word)
            else:
                fragments.append(_merge_words(current))
                current = [word]
        fragments.append(_merge_words(current))

    return fragments


def build_visual_rows(fragments: Sequence[TextFragment]) -> list[VisualRow]:
    """Group fragments into visual rows using only vertical alignment."""
    if not fragments:
        return []

    sorted_fragments = sorted(
        fragments,
        key=lambda fragment: (_bbox_y_center(fragment.bbox), fragment.bbox.x0),
    )
    rows: list[list[TextFragment]] = []
    current: list[TextFragment] = [sorted_fragments[0]]

    for fragment in sorted_fragments[1:]:
        if _belongs_to_same_band(current, fragment.bbox):
            current.append(fragment)
        else:
            rows.append(sorted(current, key=lambda item: item.bbox.x0))
            current = [fragment]
    rows.append(sorted(current, key=lambda item: item.bbox.x0))

    return [
        VisualRow(fragments=row_fragments, bbox=_bbox_union(f.bbox for f in row_fragments))
        for row_fragments in rows
    ]


def render_text_debug_pages(
    pdf_path: str,
    output_dir: str,
    page_numbers: Sequence[int],
    dpi: int = 160,
) -> list[dict]:
    """Render debug overlays for selected 1-based page numbers."""
    os.makedirs(output_dir, exist_ok=True)
    outputs: list[dict] = []

    doc = fitz.open(pdf_path)
    try:
        for page_number in page_numbers:
            page_index = page_number - 1
            if page_index < 0 or page_index >= doc.page_count:
                continue

            page = doc[page_index]
            words = page.get_text("words")
            word_items = _normalize_words(words)
            fragments = make_text_fragments(words)
            rows = build_visual_rows(fragments)
            horizontal_separators = extract_horizontal_separators(page)
            candidate_regions = detect_candidate_regions(
                rows,
                horizontal_separators=horizontal_separators,
            )

            _draw_debug_boxes(page, word_items, fragments, rows, candidate_regions)

            matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            image_path = os.path.join(output_dir, f"text-debug-page-{page_number:03d}.png")
            json_path = os.path.join(output_dir, f"text-debug-page-{page_number:03d}.json")
            pix.save(image_path)
            _write_debug_json(
                json_path,
                word_items,
                fragments,
                rows,
                candidate_regions,
                page_number,
            )

            outputs.append(
                {
                    "page_number": page_number,
                    "image_path": image_path,
                    "json_path": json_path,
                    "word_count": len(word_items),
                    "fragment_count": len(fragments),
                    "row_count": len(rows),
                    "horizontal_separator_count": len(horizontal_separators),
                    "candidate_region_count": len(candidate_regions),
                }
            )
    finally:
        doc.close()

    return outputs


def extract_horizontal_separators(page: fitz.Page) -> list[HorizontalSeparator]:
    """Extract long thin horizontal rectangles as separator hints."""
    separators: list[HorizontalSeparator] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return separators

    for drawing in drawings:
        stroke_width = drawing.get("width", 1.0)
        for item in drawing.get("items", []):
            if item[0] == "re":
                rect = item[1]
                width = rect.x1 - rect.x0
                height = rect.y1 - rect.y0
                if width < 5 or height > 1.5:
                    continue
                separators.append(
                    HorizontalSeparator(
                        x0=float(rect.x0),
                        x1=float(rect.x1),
                        y=float((rect.y0 + rect.y1) / 2.0),
                    )
                )
            elif item[0] == "l":
                p1, p2 = item[1], item[2]
                line_width = abs(p2.x - p1.x)
                line_height = abs(p2.y - p1.y)
                if line_width < 5 or line_height > 1.5:
                    continue
                if stroke_width > 1.5:
                    continue
                separators.append(
                    HorizontalSeparator(
                        x0=float(min(p1.x, p2.x)),
                        x1=float(max(p1.x, p2.x)),
                        y=float((p1.y + p2.y) / 2.0),
                    )
                )

    separators.sort(key=lambda item: (item.y, item.x0))
    deduped: list[HorizontalSeparator] = []
    for separator in separators:
        if deduped and abs(separator.y - deduped[-1].y) <= 1.0 and separator.x0 <= deduped[-1].x1 + 2.0:
            prev = deduped[-1]
            deduped[-1] = HorizontalSeparator(
                x0=min(prev.x0, separator.x0),
                x1=max(prev.x1, separator.x1),
                y=(prev.y + separator.y) / 2.0,
            )
            continue
        deduped.append(separator)
    return [separator for separator in deduped if separator.x1 - separator.x0 >= 200]


def _normalize_words(words: Sequence[tuple]) -> list[TextWord]:
    normalized: list[TextWord] = []
    for word in words:
        x0, y0, x1, y1 = word[:4]
        text = word[4] if len(word) > 4 else ""
        normalized.append(TextWord(text=text, bbox=BBox(x0, y0, x1, y1)))
    normalized.sort(key=lambda item: (_bbox_y_center(item.bbox), item.bbox.x0))
    return normalized


def _group_items_into_bands(items: Sequence[TextWord]) -> list[list[TextWord]]:
    if not items:
        return []

    bands: list[list[TextWord]] = []
    current: list[TextWord] = [items[0]]
    for item in items[1:]:
        if _belongs_to_same_band(current, item.bbox):
            current.append(item)
        else:
            bands.append(sorted(current, key=lambda word: word.bbox.x0))
            current = [item]
    bands.append(sorted(current, key=lambda word: word.bbox.x0))
    return bands


def _belongs_to_same_band(current_items: Sequence[TextWord | TextFragment], bbox: BBox) -> bool:
    current_bbox = _bbox_union(item.bbox for item in current_items)
    current_height = max(_bbox_height(current_bbox), 1.0)
    new_height = max(_bbox_height(bbox), 1.0)
    center_diff = abs(_bbox_y_center(current_bbox) - _bbox_y_center(bbox))
    overlap = _vertical_overlap_ratio(current_bbox, bbox)
    tolerance = max(min(current_height, new_height) * 0.55, 4.0)
    return overlap >= 0.45 or center_diff <= tolerance


def _should_merge_words(left: TextWord, right: TextWord, band_height: float) -> bool:
    gap = right.bbox.x0 - left.bbox.x1
    if gap < 0:
        return True

    overlap = _vertical_overlap_ratio(left.bbox, right.bbox)
    if overlap < 0.6:
        return False

    char_widths = []
    for item in (left, right):
        text = item.text.strip()
        if text:
            char_widths.append((_bbox_width(item.bbox)) / max(len(text), 1))
    avg_char_width = sum(char_widths) / len(char_widths) if char_widths else band_height / 2

    max_gap = min(max(avg_char_width * 0.6, band_height * 0.25, 2.0), 8.0)
    return gap <= max_gap


def _merge_words(words: Sequence[TextWord]) -> TextFragment:
    return TextFragment(
        text="".join(word.text for word in words),
        bbox=_bbox_union(word.bbox for word in words),
    )


def _draw_debug_boxes(
    page: fitz.Page,
    words: Sequence[TextWord],
    fragments: Sequence[TextFragment],
    rows: Sequence[VisualRow],
    candidate_regions: Sequence[CandidateRegion],
) -> None:
    for region in candidate_regions:
        page.draw_rect(
            fitz.Rect(region.bbox.x0, region.bbox.y0, region.bbox.x1, region.bbox.y1),
            color=(0.62, 0.20, 0.89),
            width=2.2,
            overlay=True,
        )

    for row in rows:
        page.draw_rect(
            fitz.Rect(row.bbox.x0, row.bbox.y0, row.bbox.x1, row.bbox.y1),
            color=(0.95, 0.34, 0.14),
            width=1.6,
            overlay=True,
        )

    for fragment in fragments:
        page.draw_rect(
            fitz.Rect(
                fragment.bbox.x0,
                fragment.bbox.y0,
                fragment.bbox.x1,
                fragment.bbox.y1,
            ),
            color=(0.05, 0.72, 0.38),
            width=1.2,
            overlay=True,
        )

    for word in words:
        page.draw_rect(
            fitz.Rect(word.bbox.x0, word.bbox.y0, word.bbox.x1, word.bbox.y1),
            color=(0.22, 0.48, 0.96),
            width=0.8,
            overlay=True,
        )


def _write_debug_json(
    path: str,
    words: Sequence[TextWord],
    fragments: Sequence[TextFragment],
    rows: Sequence[VisualRow],
    candidate_regions: Sequence[CandidateRegion],
    page_number: int,
) -> None:
    payload = {
        "page_number": page_number,
        "words": [_item_to_dict(word.text, word.bbox) for word in words],
        "fragments": [_item_to_dict(fragment.text, fragment.bbox) for fragment in fragments],
        "rows": [
            {
                "bbox": _bbox_to_dict(row.bbox),
                "fragments": [_item_to_dict(fragment.text, fragment.bbox) for fragment in row.fragments],
            }
            for row in rows
        ],
        "candidate_regions": [
            {
                "bbox": _bbox_to_dict(region.bbox),
                "score": region.score,
                "features": region.features,
                "row_count": len(region.rows),
            }
            for region in candidate_regions
        ],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _item_to_dict(text: str, bbox: BBox) -> dict:
    return {
        "text": text,
        "bbox": _bbox_to_dict(bbox),
    }


def _bbox_to_dict(bbox: BBox) -> dict:
    return {
        "x0": bbox.x0,
        "y0": bbox.y0,
        "x1": bbox.x1,
        "y1": bbox.y1,
    }


def _bbox_union(boxes: Iterable[BBox]) -> BBox:
    box_list = list(boxes)
    return BBox(
        min(box.x0 for box in box_list),
        min(box.y0 for box in box_list),
        max(box.x1 for box in box_list),
        max(box.y1 for box in box_list),
    )


def _bbox_width(bbox: BBox) -> float:
    return bbox.x1 - bbox.x0


def _bbox_height(bbox: BBox) -> float:
    return bbox.y1 - bbox.y0


def _bbox_y_center(bbox: BBox) -> float:
    return (bbox.y0 + bbox.y1) / 2.0


def _vertical_overlap_ratio(left: BBox, right: BBox) -> float:
    inter = min(left.y1, right.y1) - max(left.y0, right.y0)
    if inter <= 0:
        return 0.0
    return inter / max(min(_bbox_height(left), _bbox_height(right)), 1.0)
