"""Immutable, single-capture evidence for one PyMuPDF page."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
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
    if all(hasattr(value, name) for name in ("a", "b", "c", "d", "e", "f")):
        return tuple(_finite_float(getattr(value, name)) for name in "abcdef")
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
    if all(hasattr(value, name) for name in ("width", "height", "samples")):
        samples = getattr(value, "samples", b"")
        return {
            "type": "pixmap",
            "width": int(value.width),
            "height": int(value.height),
            "n": int(getattr(value, "n", 0)),
            "alpha": bool(getattr(value, "alpha", False)),
            "samples": _plain(samples),
        }
    if isinstance(value, float):
        return _finite_float(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    known_attributes = {}
    for name in (
        "tables",
        "bbox",
        "cells",
        "header",
        "rows",
        "row_count",
        "col_count",
        "xref",
    ):
        try:
            item = getattr(value, name)
        except (AttributeError, TypeError):
            continue
        if not callable(item):
            known_attributes[name] = _plain(item)
    if known_attributes:
        return {"type": type(value).__name__, **known_attributes}
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        return {
            "type": type(value).__name__,
            "attributes": {
                str(key): _plain(item)
                for key, item in attributes.items()
                if not callable(item)
            },
        }
    return {"type": type(value).__name__}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(_freeze(item) for item in sorted(value, key=repr))
    if isinstance(value, float):
        return _finite_float(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return _freeze(_plain(value))


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _read_call(page: Any, method: str, *args: Any, **kwargs: Any) -> tuple[dict[str, Any], Any]:
    """Call one page API and retain only a deterministic result record."""

    record: dict[str, Any] = {
        "method": method,
        "args": _plain(args),
        "kwargs": _plain(kwargs),
    }
    try:
        function = getattr(page, method)
    except AttributeError:
        record["status"] = "unavailable"
        record["result"] = None
        return record, None
    if not callable(function):
        record["status"] = "error"
        record["error"] = {"type": "TypeError", "message": "attribute is not callable"}
        record["result"] = None
        return record, None
    try:
        result = function(*args, **kwargs)
    except Exception as exc:  # PyMuPDF capabilities vary by version/page.
        record["status"] = "error"
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        record["result"] = None
        return record, None
    record["status"] = "ok"
    record["result"] = _plain(result)
    return record, result


def _read_property(page: Any, name: str) -> tuple[dict[str, Any], Any]:
    record: dict[str, Any] = {"method": name, "args": [], "kwargs": {}}
    try:
        result = getattr(page, name)
    except AttributeError:
        record["status"] = "unavailable"
        record["result"] = None
        return record, None
    except Exception as exc:
        record["status"] = "error"
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        record["result"] = None
        return record, None
    record["status"] = "ok"
    record["result"] = _plain(result)
    return record, result


def _clip_value(region: Any) -> fitz.Rect:
    values = _region(region)
    return fitz.Rect(values["x0"], values["y0"], values["x1"], values["y1"])


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
    result["text"] = (
        "".join(char.get("c", "") for char in chars)
        if raw_chars
        else str(span.get("text", ""))
    )
    result["raw_source_position"] = position
    result["source_order"] = source_order
    return result, chars, character_order + len(chars)


def _raw_line(
    line: Mapping[str, Any],
    block_index: int,
    line_index: int,
    span_order: int,
    character_order: int,
    line_order: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int, int, int]:
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
    result["source_order"] = line_order
    return result, flat_spans, flat_chars, span_order, character_order, line_order + 1


def _raw_block(
    block: Mapping[str, Any],
    block_index: int,
    span_order: int,
    character_order: int,
    line_order: int,
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], int, int, int, int]:
    nested_lines = []
    flat_spans = []
    flat_chars = []
    line_count = 0
    for line_index, line in enumerate(block.get("lines", []) or []):
        nested, spans, chars, span_order, character_order, line_order = _raw_line(
            line, block_index, line_index, span_order, character_order, line_order
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
        line_order,
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
    resources: Mapping[str, Any] = field(default_factory=dict)
    raster: Mapping[str, Any] = field(default_factory=dict)
    bboxlog: Mapping[str, Any] = field(default_factory=dict)
    table_fallback: Mapping[str, Any] = field(default_factory=dict)
    page_reads: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "geometry",
            "text_blocks",
            "spans",
            "characters",
            "words",
            "drawings",
            "allowed_regions",
            "excluded_regions",
            "extraction_options",
            "summary",
            "resources",
            "raster",
            "bboxlog",
            "table_fallback",
            "page_reads",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

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

    def __post_init__(self) -> None:
        for name in (
            "geometry",
            "text_blocks",
            "spans",
            "characters",
            "words",
            "drawings",
            "allowed_regions",
            "excluded_regions",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


def capture_page_snapshot(
    page: fitz.Page,
    *,
    page_index: int,
    allowed_regions: Sequence[Any] = (),
    excluded_regions: Sequence[Any] = (),
) -> PageSnapshot:
    """Capture all page evidence once, before any filtering or parsing."""

    page_reads: dict[str, Any] = {}
    rect_record, page_rect = _read_property(page, "rect")
    width_record, width_value = _read_property(page, "width")
    height_record, height_value = _read_property(page, "height")
    size_record, size_value = _read_property(page, "size")
    rotation_record, rotation_value = _read_property(page, "rotation")
    number_record, number_value = _read_property(page, "number")
    page_reads.update(
        {
            "rect": rect_record,
            "width": width_record,
            "height": height_record,
            "size": size_record,
            "rotation": rotation_record,
            "number": number_record,
        }
    )
    if _is_rect(page_rect):
        rect_values = tuple(
            _finite_float(getattr(page_rect, name))
            for name in ("x0", "y0", "x1", "y1")
        )
    else:
        rect_values = (0.0, 0.0, 0.0, 0.0)
    rotation = int(rotation_value) if rotation_value is not None else 0
    number = int(number_value) if number_value is not None else int(page_index)
    page_width = _finite_float(width_value) if isinstance(width_value, (int, float)) else rect_values[2] - rect_values[0]
    page_height = _finite_float(height_value) if isinstance(height_value, (int, float)) else rect_values[3] - rect_values[1]

    frozen_allowed = _regions(allowed_regions)
    frozen_excluded = _regions(excluded_regions)

    raw_record, raw_text_value = _read_call(
        page, "get_text", "rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE
    )
    dict_record, dict_text_value = _read_call(
        page, "get_text", "dict", flags=fitz.TEXT_PRESERVE_WHITESPACE
    )
    text_record, _ = _read_call(
        page, "get_text", "text", flags=fitz.TEXT_PRESERVE_WHITESPACE
    )
    blocks_record, _ = _read_call(
        page, "get_text", "blocks", flags=fitz.TEXT_PRESERVE_WHITESPACE
    )
    words_record, words_value = _read_call(page, "get_text", "words")
    page_reads.update(
        {
            "text.rawdict": raw_record,
            "text.dict": dict_record,
            "text.text": text_record,
            "text.blocks": blocks_record,
            "text.words": words_record,
        }
    )
    for index, region in enumerate((*frozen_allowed, *frozen_excluded)):
        clip_record, _ = _read_call(
            page,
            "get_text",
            "words",
            clip=_clip_value(region),
        )
        page_reads[f"text.words.clip.{index}"] = clip_record

    drawings_record, drawings_value = _read_call(page, "get_drawings", extended=True)
    page_reads["drawings"] = drawings_record

    raw_text = raw_text_value if isinstance(raw_text_value, Mapping) else None
    if raw_text is None and isinstance(dict_text_value, Mapping):
        raw_text = dict_text_value
    raw_text = raw_text or {}
    words = words_value if isinstance(words_value, Iterable) and not isinstance(words_value, (str, bytes, Mapping)) else ()
    drawings = drawings_value if isinstance(drawings_value, Iterable) and not isinstance(drawings_value, (str, bytes, Mapping)) else ()

    text_blocks = []
    spans = []
    characters = []
    span_order = 0
    character_order = 0
    line_order = 0
    line_count = 0
    for block_index, block in enumerate(raw_text.get("blocks", []) or []):
        (
            frozen_block,
            block_spans,
            block_characters,
            span_order,
            character_order,
            block_line_count,
            line_order,
        ) = _raw_block(block, block_index, span_order, character_order, line_order)
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
            "reported_width": page_width,
            "reported_height": page_height,
            "size": _plain(size_value),
            "rotation": rotation,
            "number": number,
        }
    )
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
            "dict": {
                "method": "get_text",
                "mode": "dict",
                "args": ("dict",),
                "kwargs": {"flags": int(fitz.TEXT_PRESERVE_WHITESPACE)},
                "flags": int(fitz.TEXT_PRESERVE_WHITESPACE),
                "clip": None,
            },
            "text": {
                "method": "get_text",
                "mode": "text",
                "args": ("text",),
                "kwargs": {"flags": int(fitz.TEXT_PRESERVE_WHITESPACE)},
                "flags": int(fitz.TEXT_PRESERVE_WHITESPACE),
                "clip": None,
            },
            "blocks": {
                "method": "get_text",
                "mode": "blocks",
                "args": ("blocks",),
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
            "words_variants": {
                "clip_regions": tuple(
                    _thaw(region) for region in (*frozen_allowed, *frozen_excluded)
                ),
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

    fonts_record, fonts_value = _read_call(page, "get_fonts", full=True)
    images_default_record, images_default_value = _read_call(page, "get_images")
    images_full_record, images_full_value = _read_call(page, "get_images", full=True)
    image_info_record, image_info_value = _read_call(page, "get_image_info", xrefs=True)
    page_reads.update(
        {
            "fonts": fonts_record,
            "images": images_full_record,
            "images.default": images_default_record,
            "images.full": images_full_record,
            "image_info": image_info_record,
        }
    )

    def _xrefs(value: Any) -> tuple[int, ...]:
        result = []
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
            for item in value:
                try:
                    xref = int(item[0])
                except (IndexError, TypeError, ValueError):
                    continue
                if xref not in result:
                    result.append(xref)
        return tuple(result)

    font_xrefs = _xrefs(fonts_value)
    image_xrefs = _xrefs(images_full_value) or _xrefs(images_default_value)
    if isinstance(image_info_value, Iterable) and not isinstance(image_info_value, (str, bytes, Mapping)):
        for item in image_info_value:
            if isinstance(item, Mapping) and item.get("xref") is not None:
                try:
                    xref = int(item["xref"])
                except (TypeError, ValueError):
                    continue
                if xref not in image_xrefs:
                    image_xrefs += (xref,)

    image_rect_records: dict[str, Any] = {}
    for xref in image_xrefs:
        record, _ = _read_call(page, "get_image_rects", xref)
        image_rect_records[str(xref)] = record
        page_reads[f"image_rects.{xref}"] = record

    parent_record, parent = _read_property(page, "parent")
    page_reads["parent"] = parent_record
    font_xref_records: dict[str, Any] = {}
    for xref in font_xrefs:
        record, _ = _read_call(parent, "xref_object", xref) if parent is not None else (
            {"method": "xref_object", "args": [xref], "kwargs": {}, "status": "unavailable", "result": None},
            None,
        )
        font_xref_records[str(xref)] = record
        page_reads[f"xref_object.{xref}"] = record

    pixmap_record, _ = _read_call(
        page,
        "get_pixmap",
        matrix=fitz.Matrix(1, 1),
        alpha=False,
    )
    bboxlog_record, _ = _read_call(page, "get_bboxlog")
    tables_record, _ = _read_call(page, "find_tables")
    page_reads.update(
        {"pixmap": pixmap_record, "bboxlog": bboxlog_record, "find_tables": tables_record}
    )
    resources = _freeze(
        {
            "fonts": fonts_record,
            "images": images_full_record
            if images_full_record["status"] == "ok"
            else images_default_record,
            "image_info": image_info_record,
            "image_rects": image_rect_records,
            "font_xref_objects": font_xref_records,
        }
    )
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
            "read_count": len(page_reads),
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
        resources=resources,
        raster=_freeze({"purpose": "algorithm", **pixmap_record}),
        bboxlog=_freeze(bboxlog_record),
        table_fallback=_freeze(tables_record),
        page_reads=_freeze(page_reads),
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
        text_blocks=_ordered_filtered(snapshot.text_blocks, allowed, excluded),
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
        "resources": _thaw(snapshot.resources),
        "raster": _thaw(snapshot.raster),
        "bboxlog": _thaw(snapshot.bboxlog),
        "table_fallback": _thaw(snapshot.table_fallback),
        "page_reads": _thaw(snapshot.page_reads),
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
