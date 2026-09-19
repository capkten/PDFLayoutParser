"""Immutable, single-capture evidence for one PyMuPDF page."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import fitz


SCHEMA_VERSION = 1
SNAPSHOT_VERSION = 1


def _finite_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("snapshot values must contain finite floats")
    return result


def _is_rect(value: Any) -> bool:
    return all(hasattr(value, name) for name in ("x0", "y0", "x1", "y1"))


def _is_point(value: Any) -> bool:
    return hasattr(value, "x") and hasattr(value, "y") and not _is_rect(value)


def _plain(value: Any) -> Any:
    """Copy PyMuPDF containers without retaining library-owned objects."""

    if _is_rect(value):
        return tuple(
            _finite_float(getattr(value, name))
            for name in ("x0", "y0", "x1", "y1")
        )
    if _is_point(value):
        return (_finite_float(value.x), _finite_float(value.y))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_plain(item) for item in sorted(value, key=repr)]
    if isinstance(value, bytes):
        return {
            "byte_length": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, float):
        return _finite_float(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(_freeze(item) for item in sorted(value, key=repr))
    if isinstance(value, float):
        return _finite_float(value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _region(value: Any) -> dict[str, float]:
    if _is_rect(value):
        values = [getattr(value, name) for name in ("x0", "y0", "x1", "y1")]
    elif isinstance(value, Mapping):
        values = [value[name] for name in ("x0", "y0", "x1", "y1")]
    else:
        values = list(value)
    if len(values) != 4:
        raise ValueError("regions must contain x0, y0, x1, y1")
    return {
        "x0": _finite_float(values[0]),
        "y0": _finite_float(values[1]),
        "x1": _finite_float(values[2]),
        "y1": _finite_float(values[3]),
    }


def _regions(values: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(_freeze(_region(value)) for value in values)


def _bbox(record: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    value = record.get("bbox", record.get("rect"))
    if value is None:
        return None
    if isinstance(value, Mapping):
        return tuple(
            _finite_float(value[name]) for name in ("x0", "y0", "x1", "y1")
        )  # type: ignore[return-value]
    if len(value) != 4:
        return None
    return tuple(_finite_float(item) for item in value)  # type: ignore[return-value]


def _center_in_region(record: Mapping[str, Any], region: Mapping[str, Any]) -> bool:
    box = _bbox(record)
    if box is None:
        return False
    x = (box[0] + box[2]) / 2.0
    y = (box[1] + box[3]) / 2.0
    return region["x0"] <= x <= region["x1"] and region["y0"] <= y <= region["y1"]


def _selected(
    record: Mapping[str, Any],
    allowed_regions: Sequence[Mapping[str, Any]],
    excluded_regions: Sequence[Mapping[str, Any]],
) -> bool:
    allowed = not allowed_regions or any(
        _center_in_region(record, region) for region in allowed_regions
    )
    excluded = any(_center_in_region(record, region) for region in excluded_regions)
    return allowed and not excluded


def _ordered_filtered(
    records: Sequence[Mapping[str, Any]],
    allowed_regions: Sequence[Mapping[str, Any]],
    excluded_regions: Sequence[Mapping[str, Any]],
) -> tuple[Any, ...]:
    result = []
    for filtered_order, record in enumerate(
        record
        for record in records
        if _selected(record, allowed_regions, excluded_regions)
    ):
        copied = _thaw(record)
        copied["filtered_order"] = filtered_order
        result.append(_freeze(copied))
    return tuple(result)


def _raw_char(char: Mapping[str, Any], position: tuple[int, int, int, int], order: int) -> dict[str, Any]:
    result = _plain(char)
    result["raw_source_position"] = position
    result["source_order"] = order
    result.setdefault("c", "")
    return result


def _raw_span(
    span: Mapping[str, Any],
    position: tuple[int, int, int],
    source_order: int,
    character_order: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    raw_chars = span.get("chars", []) or []
    chars = [
        _raw_char(char, (*position, char_index), character_order + char_index)
        for char_index, char in enumerate(raw_chars)
    ]
    result = {key: _plain(value) for key, value in span.items() if key != "chars"}
    result["chars"] = chars
    result["text"] = "".join(char.get("c", "") for char in chars)
    result["raw_source_position"] = position
    result["source_order"] = source_order
    return result, chars, character_order + len(chars)


def _raw_line(
    line: Mapping[str, Any],
    block_index: int,
    line_index: int,
    span_order: int,
    character_order: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int, int]:
    nested_spans = []
    flat_spans = []
    flat_chars = []
    for span_index, span in enumerate(line.get("spans", []) or []):
        position = (block_index, line_index, span_index)
        nested, chars, character_order = _raw_span(
            span, position, span_order, character_order
        )
        nested_spans.append(nested)
        flat_spans.append(nested.copy())
        flat_chars.extend(chars)
        span_order += 1
    result = {key: _plain(value) for key, value in line.items() if key != "spans"}
    result["spans"] = nested_spans
    result["raw_source_position"] = (block_index, line_index)
    result["source_order"] = line_index
    return result, flat_spans, flat_chars, span_order, character_order


def _raw_block(
    block: Mapping[str, Any],
    block_index: int,
    span_order: int,
    character_order: int,
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], int, int, int]:
    nested_lines = []
    flat_spans = []
    flat_chars = []
    line_count = 0
    for line_index, line in enumerate(block.get("lines", []) or []):
        nested, spans, chars, span_order, character_order = _raw_line(
            line, block_index, line_index, span_order, character_order
        )
        nested_lines.append(nested)
        flat_spans.extend(spans)
        flat_chars.extend(chars)
        line_count += 1
    result = {key: _plain(value) for key, value in block.items() if key != "lines"}
    if "lines" in block:
        result["lines"] = nested_lines
    result["raw_source_position"] = (block_index,)
    result["source_order"] = block_index
    return (
        _freeze(result),
        flat_spans,
        flat_chars,
        span_order,
        character_order,
        line_count,
    )


def _word_records(words: Iterable[Any]) -> tuple[Any, ...]:
    records = []
    for source_order, word in enumerate(words):
        values = list(word)
        if len(values) < 8:
            raise ValueError("PyMuPDF words records must contain eight fields")
        records.append(
            _freeze(
                {
                    "bbox": tuple(_finite_float(item) for item in values[:4]),
                    "text": str(values[4]),
                    "block_index": int(values[5]),
                    "line_index": int(values[6]),
                    "word_index": int(values[7]),
                    "raw_source_position": (
                        int(values[5]),
                        int(values[6]),
                        int(values[7]),
                    ),
                    "source_order": source_order,
                    "extra": tuple(_plain(item) for item in values[8:]),
                }
            )
        )
    return tuple(records)


def _drawing_records(drawings: Iterable[Mapping[str, Any]]) -> tuple[Any, ...]:
    records = []
    for source_order, drawing in enumerate(drawings):
        result = {key: _plain(value) for key, value in drawing.items() if key != "items"}
        result["items"] = [
            _plain(item) for item in (drawing.get("items", []) or [])
        ]
        result["raw_source_position"] = (source_order,)
        result["source_order"] = source_order
        records.append(_freeze(result))
    return tuple(records)


@dataclass(frozen=True)
class PageSnapshot:
    schema_version: int
    version: int
    page_index: int
    geometry: Mapping[str, Any]
    text_blocks: tuple[Any, ...]
    spans: tuple[Any, ...]
    characters: tuple[Any, ...]
    words: tuple[Any, ...]
    drawings: tuple[Any, ...]
    allowed_regions: tuple[Any, ...]
    excluded_regions: tuple[Any, ...]
    extraction_options: Mapping[str, Any]
    summary: Mapping[str, Any]

    @property
    def digest(self) -> str:
        return page_snapshot_digest(self)


@dataclass(frozen=True)
class FilteredSnapshotEvidence:
    page_index: int
    geometry: Mapping[str, Any]
    text_blocks: tuple[Any, ...]
    spans: tuple[Any, ...]
    characters: tuple[Any, ...]
    words: tuple[Any, ...]
    drawings: tuple[Any, ...]
    allowed_regions: tuple[Any, ...]
    excluded_regions: tuple[Any, ...]


def capture_page_snapshot(
    page: fitz.Page,
    *,
    page_index: int,
    allowed_regions: Sequence[Any] = (),
    excluded_regions: Sequence[Any] = (),
) -> PageSnapshot:
    """Capture all page evidence once, before any filtering or parsing."""

    page_rect = page.rect
    rect_values = tuple(
        _finite_float(getattr(page_rect, name))
        for name in ("x0", "y0", "x1", "y1")
    )
    rotation = int(page.rotation)
    number = int(page.number)

    raw_text = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    words = page.get_text("words")
    drawings = page.get_drawings(extended=True)

    text_blocks = []
    spans = []
    characters = []
    span_order = 0
    character_order = 0
    line_count = 0
    for block_index, block in enumerate(raw_text.get("blocks", []) or []):
        (
            frozen_block,
            block_spans,
            block_characters,
            span_order,
            character_order,
            block_line_count,
        ) = _raw_block(block, block_index, span_order, character_order)
        text_blocks.append(frozen_block)
        spans.extend(_freeze(span) for span in block_spans)
        characters.extend(_freeze(char) for char in block_characters)
        line_count += block_line_count

    geometry = _freeze(
        {
            "rect": rect_values,
            "x0": rect_values[0],
            "y0": rect_values[1],
            "x1": rect_values[2],
            "y1": rect_values[3],
            "width": rect_values[2] - rect_values[0],
            "height": rect_values[3] - rect_values[1],
            "rotation": rotation,
            "number": number,
        }
    )
    frozen_allowed = _regions(allowed_regions)
    frozen_excluded = _regions(excluded_regions)
    extraction_options = _freeze(
        {
            "rawdict": {
                "method": "get_text",
                "mode": "rawdict",
                "args": ("rawdict",),
                "kwargs": {"flags": int(fitz.TEXT_PRESERVE_WHITESPACE)},
                "flags": int(fitz.TEXT_PRESERVE_WHITESPACE),
                "clip": None,
            },
            "words": {
                "method": "get_text",
                "mode": "words",
                "args": ("words",),
                "kwargs": {},
                "clip": None,
            },
            "drawings": {
                "method": "get_drawings",
                "args": (),
                "kwargs": {"extended": True},
                "extended": True,
            },
        }
    )
    frozen_spans = tuple(spans)
    frozen_characters = tuple(characters)
    frozen_words = _word_records(words)
    frozen_drawings = _drawing_records(drawings)
    summary = _freeze(
        {
            "block_count": len(text_blocks),
            "line_count": line_count,
            "span_count": len(frozen_spans),
            "character_count": len(frozen_characters),
            "word_count": len(frozen_words),
            "drawing_count": len(frozen_drawings),
            "allowed_region_count": len(frozen_allowed),
            "excluded_region_count": len(frozen_excluded),
        }
    )
    return PageSnapshot(
        schema_version=SCHEMA_VERSION,
        version=SNAPSHOT_VERSION,
        page_index=int(page_index),
        geometry=geometry,
        text_blocks=tuple(text_blocks),
        spans=frozen_spans,
        characters=frozen_characters,
        words=frozen_words,
        drawings=frozen_drawings,
        allowed_regions=frozen_allowed,
        excluded_regions=frozen_excluded,
        extraction_options=extraction_options,
        summary=summary,
    )


def filter_snapshot_evidence(
    snapshot: PageSnapshot,
    *,
    allowed_regions: Sequence[Any] = (),
    excluded_regions: Sequence[Any] = (),
) -> FilteredSnapshotEvidence:
    """Return an immutable filtered view without touching the original page."""

    allowed = _regions(allowed_regions) if allowed_regions else snapshot.allowed_regions
    excluded = (
        _regions(excluded_regions) if excluded_regions else snapshot.excluded_regions
    )
    return FilteredSnapshotEvidence(
        page_index=snapshot.page_index,
        geometry=snapshot.geometry,
        text_blocks=snapshot.text_blocks,
        spans=_ordered_filtered(snapshot.spans, allowed, excluded),
        characters=_ordered_filtered(snapshot.characters, allowed, excluded),
        words=_ordered_filtered(snapshot.words, allowed, excluded),
        drawings=_ordered_filtered(snapshot.drawings, allowed, excluded),
        allowed_regions=tuple(_freeze(_thaw(region)) for region in allowed),
        excluded_regions=tuple(_freeze(_thaw(region)) for region in excluded),
    )


def _snapshot_content_to_dto(snapshot: PageSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "version": snapshot.version,
        "page_index": snapshot.page_index,
        "geometry": _thaw(snapshot.geometry),
        "text_blocks": _thaw(snapshot.text_blocks),
        "spans": _thaw(snapshot.spans),
        "characters": _thaw(snapshot.characters),
        "words": _thaw(snapshot.words),
        "drawings": _thaw(snapshot.drawings),
        "allowed_regions": _thaw(snapshot.allowed_regions),
        "excluded_regions": _thaw(snapshot.excluded_regions),
        "extraction_options": _thaw(snapshot.extraction_options),
        "summary": _thaw(snapshot.summary),
    }


def _stable_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def page_snapshot_to_dto(snapshot: PageSnapshot) -> dict[str, Any]:
    """Convert an immutable snapshot to a complete, ordinary Python DTO."""

    dto = _snapshot_content_to_dto(snapshot)
    dto["digest"] = page_snapshot_digest(snapshot)
    return dto


def page_snapshot_digest(snapshot: PageSnapshot) -> str:
    """Return the SHA256 of the canonical snapshot content, excluding the digest."""

    return sha256(_stable_json(_snapshot_content_to_dto(snapshot))).hexdigest()


__all__ = [
    "FilteredSnapshotEvidence",
    "PageSnapshot",
    "capture_page_snapshot",
    "filter_snapshot_evidence",
    "page_snapshot_digest",
    "page_snapshot_to_dto",
]
