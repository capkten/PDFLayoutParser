"""Immutable, single-capture evidence for one PyMuPDF page."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

import fitz


SCHEMA_VERSION = 1
SNAPSHOT_VERSION = 1

_DIRECTION_ALIGNMENT_TOLERANCE = 1e-6
_DEGENERATE_PROJECTION_TOLERANCE = 1e-9
_CLIP_BOUNDARY_TOLERANCE = 1e-6
_FLOW_CONTINUITY_TOLERANCE = 1e-3
_NORMAL_OVERLAP_RATIO = 0.5
_SINGLE_GLYPH_EXTENSION_RATIO = 0.25
_SHORT_GLYPH_FLOW_THRESHOLD = 4.0


def _finite_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("snapshot values must contain finite floats")
    return result


def _safe_finite(value: Any, fallback: float = 0.0) -> float:
    try:
        return _finite_float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _is_rect(value: Any) -> bool:
    return all(hasattr(value, name) for name in ("x0", "y0", "x1", "y1"))


def _is_point(value: Any) -> bool:
    return hasattr(value, "x") and hasattr(value, "y") and not _is_rect(value)


def _plain(value: Any) -> Any:
    """Copy PyMuPDF containers without retaining library-owned objects."""

    pixmap_type = getattr(fitz, "Pixmap", ())
    if pixmap_type and isinstance(value, pixmap_type):
        return {
            "type": "pixmap",
            "width": int(value.width),
            "height": int(value.height),
            "stride": int(getattr(value, "stride", 0)),
            "n": int(getattr(value, "n", 0)),
            "alpha": bool(getattr(value, "alpha", False)),
            "colorspace": _plain(getattr(value, "colorspace", None)),
            "samples": _plain(getattr(value, "samples", b"")),
        }
    if _is_rect(value):
        return tuple(
            _finite_float(getattr(value, name))
            for name in ("x0", "y0", "x1", "y1")
        )
    if _is_point(value):
        return (_finite_float(value.x), _finite_float(value.y))
    if all(hasattr(value, name) for name in ("a", "b", "c", "d", "e", "f")):
        return tuple(_finite_float(getattr(value, name)) for name in "abcdef")
    colorspace_type = getattr(fitz, "Colorspace", ())
    if colorspace_type and isinstance(value, colorspace_type):
        name = str(getattr(value, "name", ""))
        identity = {
            "DeviceRGB": "csRGB",
            "DeviceGray": "csGRAY",
            "DeviceCMYK": "csCMYK",
        }.get(name, name or type(value).__name__)
        return {
            "type": "colorspace",
            "identity": identity,
            "name": name,
            "n": int(getattr(value, "n", 0)),
        }
    if isinstance(value, (fitz.Page, fitz.Document)):
        return {"type": type(value).__name__, "available": True}
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
            "hex": value.hex(),
        }
    if all(hasattr(value, name) for name in ("width", "height", "samples")):
        samples = getattr(value, "samples", b"")
        return {
            "type": "pixmap",
            "width": int(value.width),
            "height": int(value.height),
            "stride": int(getattr(value, "stride", 0)),
            "n": int(getattr(value, "n", 0)),
            "alpha": bool(getattr(value, "alpha", False)),
            "colorspace": _plain(getattr(value, "colorspace", None)),
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
        "names",
        "external",
        "status",
        "error",
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
    return {"type": type(value).__name__}


def _freeze(value: Any) -> Any:
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return _finite_float(value)
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, tuple):
        # If all items are immutable, return as is; else freeze
        return tuple(_freeze(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (set, frozenset)):
        return tuple(_freeze(item) for item in sorted(value, key=repr))
    return _freeze(_plain(value))


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _read_call(page: Any, method: str, *args: Any, **kwargs: Any) -> tuple[dict[str, Any], Any]:
    """Call one page API and retain only a deterministic result record."""

    record: dict[str, Any] = {"method": method}
    try:
        record["args"] = _plain(args)
        record["kwargs"] = _plain(kwargs)
    except Exception as exc:
        record.update(
            {
                "args": [],
                "kwargs": {},
                "status": "error",
                "error": {
                    "phase": "normalize_args",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "result": None,
            }
        )
        return record, None
    try:
        function = getattr(page, method)
    except AttributeError:
        record["status"] = "unavailable"
        record["result"] = None
        return record, None
    except Exception as exc:
        record["status"] = "error"
        record["error"] = {"phase": "call", "type": type(exc).__name__, "message": str(exc)}
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
    try:
        normalized = _plain(result)
    except Exception as exc:
        record["status"] = "error"
        record["error"] = {"phase": "normalize", "type": type(exc).__name__, "message": str(exc)}
        record["result"] = None
        return record, result
    record["status"] = "ok"
    record["result"] = normalized
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
        record["error"] = {"phase": "call", "type": type(exc).__name__, "message": str(exc)}
        record["result"] = None
        return record, None
    if name == "parent":
        record["status"] = "ok"
        record["result"] = {
            "available": result is not None,
            "type": type(result).__name__ if result is not None else None,
        }
        return record, result
    try:
        normalized = _plain(result)
    except Exception as exc:
        record["status"] = "error"
        record["error"] = {"phase": "normalize", "type": type(exc).__name__, "message": str(exc)}
        record["result"] = None
        return record, result
    record["status"] = "ok"
    record["result"] = normalized
    return record, result


def _find_tables_record(page: Any) -> dict[str, Any]:
    """Capture table fallback structure and eagerly materialize each table's rows."""

    record, finder = _read_call(page, "find_tables")
    if record.get("status") != "ok" or finder is None:
        return record
    if isinstance(finder, Mapping):
        tables = finder.get("tables", ())
    else:
        try:
            tables = getattr(finder, "tables", ())
        except Exception:
            tables = ()
    if not isinstance(tables, Iterable) or isinstance(tables, (str, bytes, Mapping)):
        tables = ()
    table_records = []
    for table in tables:
        try:
            table_record = _plain(table)
        except Exception as exc:
            table_record = {
                "type": type(table).__name__,
                "status": "error",
                "error": {
                    "phase": "normalize",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
        if not isinstance(table_record, dict):
            table_record = {"value": table_record}
        try:
            header = getattr(table, "header")
        except AttributeError:
            table_record["header"] = {
                "status": "unavailable",
                "result": None,
            }
        except Exception as exc:
            table_record["header"] = {
                "status": "error",
                "error": {
                    "phase": "call",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "result": None,
            }
        else:
            if header is None:
                table_record["header"] = {
                    "status": "unavailable",
                    "result": None,
                }
            else:
                try:
                    header_record = _plain(header)
                except Exception as exc:
                    header_record = {
                        "type": type(header).__name__,
                        "status": "error",
                        "error": {
                            "phase": "normalize",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                        "result": None,
                    }
                if not isinstance(header_record, dict):
                    header_record = {"value": header_record}
                if "error" not in header_record:
                    header_record["status"] = "ok"
                table_record["header"] = header_record
        try:
            extract = getattr(table, "extract")
        except AttributeError:
            table_record["extract"] = {
                "method": "extract",
                "args": [],
                "kwargs": {},
                "status": "unavailable",
                "result": None,
            }
        except Exception as exc:
            table_record["extract"] = {
                "method": "extract",
                "args": [],
                "kwargs": {},
                "status": "error",
                "error": {"phase": "call", "type": type(exc).__name__, "message": str(exc)},
                "result": None,
            }
        else:
            if not callable(extract):
                table_record["extract"] = {
                    "method": "extract",
                    "args": [],
                    "kwargs": {},
                    "status": "error",
                    "error": {"phase": "call", "type": "TypeError", "message": "attribute is not callable"},
                    "result": None,
                }
            else:
                extract_record = {"method": "extract", "args": [], "kwargs": {}}
                try:
                    rows = extract()
                except Exception as exc:
                    extract_record["status"] = "error"
                    extract_record["error"] = {
                        "phase": "call",
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    extract_record["result"] = None
                else:
                    try:
                        extract_record["status"] = "ok"
                        extract_record["result"] = _plain(rows)
                    except Exception as exc:
                        extract_record["status"] = "error"
                        extract_record["error"] = {
                            "phase": "normalize",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                        extract_record["result"] = None
                table_record["extract"] = extract_record
        table_records.append(table_record)
    record["tables"] = table_records
    return record


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
    predicate: Any = None,
) -> tuple[Any, ...]:
    result = []
    for filtered_order, record in enumerate(
        record
        for record in records
        if _selected(record, allowed_regions, excluded_regions)
        and (predicate is None or predicate(record))
    ):
        copied = _thaw(record)
        copied["filtered_order"] = filtered_order
        result.append(_freeze(copied))
    return tuple(result)


_FOOTER_PAGE_NUMBER = re.compile(
    r"^\s*第\s*\d+\s*页\s*/\s*共\s*\d+\s*页\s*$"
)


def _line_text(line: Mapping[str, Any]) -> str:
    text = line.get("text")
    if text is not None:
        return str(text)
    return "".join(
        str(char.get("c", ""))
        for span in line.get("spans", ())
        for char in span.get("chars", ())
    )


def _is_footer_line(line: Mapping[str, Any], geometry: Mapping[str, Any]) -> bool:
    box = _bbox(line)
    height = _finite_float(geometry.get("height", 0.0))
    y0 = _finite_float(geometry.get("y0", 0.0))
    return bool(
        box
        and height > 0
        and box[1] >= y0 + height * 0.85
        and _FOOTER_PAGE_NUMBER.match(_line_text(line))
    )


def _source_position(record: Mapping[str, Any], length: int) -> tuple[Any, ...]:
    value = record.get("raw_source_position", ())
    return tuple(value[:length]) if isinstance(value, (tuple, list)) else ()


def _capture_glyph_bbox(font: Any, char_value: Any) -> tuple[float, float, float, float] | None:
    if font is None or not isinstance(char_value, str) or len(char_value) != 1:
        return None
    try:
        glyph = font.glyph_bbox(ord(char_value))
        return tuple(
            _finite_float(getattr(glyph, name))
            for name in ("x0", "y0", "x1", "y1")
        )  # type: ignore[return-value]
    except Exception:
        return None


def _raw_char(
    char: Mapping[str, Any],
    position: tuple[int, int, int, int],
    order: int,
    glyph_bbox: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    result = _plain(char)
    result["raw_source_position"] = position
    result["source_order"] = order
    result.setdefault("c", "")
    if glyph_bbox is not None:
        result["glyph_bbox"] = glyph_bbox
    return result


def _raw_span(
    span: Mapping[str, Any],
    position: tuple[int, int, int],
    source_order: int,
    character_order: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    raw_chars = span.get("chars", []) or []
    font = None
    font_name = span.get("font")
    if isinstance(font_name, str) and font_name:
        try:
            font = fitz.Font(font_name)
        except Exception:
            font = None
    chars = [
        _raw_char(
            char,
            (*position, char_index),
            character_order + char_index,
            _capture_glyph_bbox(font, char.get("c", "")),
        )
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
    lines: tuple[Any, ...] = ()
    word_variants: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

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
            "lines",
            "word_variants",
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
    lines: tuple[Any, ...] = ()

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
            "lines",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


def capture_page_snapshot(
    page: fitz.Page,
    *,
    page_index: int,
    allowed_regions: Sequence[Any] = (),
    excluded_regions: Sequence[Any] = (),
    ml_render_dpi: float = 72.0,
    lightweight: bool = False,
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
            _safe_finite(getattr(page_rect, name))
            for name in ("x0", "y0", "x1", "y1")
        )
    else:
        rect_values = (0.0, 0.0, 0.0, 0.0)
    try:
        rotation = int(rotation_value) if rotation_value is not None else 0
    except (TypeError, ValueError, OverflowError):
        rotation = 0
    try:
        number = int(number_value) if number_value is not None else int(page_index)
    except (TypeError, ValueError, OverflowError):
        number = int(page_index)
    page_width = (
        _safe_finite(width_value, rect_values[2] - rect_values[0])
        if isinstance(width_value, (int, float))
        else rect_values[2] - rect_values[0]
    )
    page_height = (
        _safe_finite(height_value, rect_values[3] - rect_values[1])
        if isinstance(height_value, (int, float))
        else rect_values[3] - rect_values[1]
    )

    frozen_allowed = _regions(allowed_regions)
    frozen_excluded = _regions(excluded_regions)

    if lightweight:
        raw_text_record, raw_text_value = _read_call(page, "get_text", "rawdict")
        page_reads["text.rawdict"] = raw_text_record
        page_reads["text.rawdict.default"] = raw_text_record
        text_variants = {
            mode: {
                "default": raw_text_record,
                "preserve_whitespace": raw_text_record,
            }
            for mode in ("rawdict", "dict", "text", "blocks")
        }
        raw_text = raw_text_value if isinstance(raw_text_value, Mapping) else {}
        words = ()
        drawings = ()
        words_record = {"status": "skipped_lightweight"}
        words_default_record = words_record
        words_flags_zero_record = words_record
        words_preserve_record = words_record
        drawings_record = {"status": "skipped_lightweight"}
        drawings_default_record = drawings_record
        drawings_extended_record = drawings_record
    else:
        text_variants: dict[str, dict[str, Any]] = {}
        text_values: dict[str, Any] = {}
        for mode in ("rawdict", "dict", "text", "blocks"):
            default_record, default_value = _read_call(page, "get_text", mode)
            preserve_record, preserve_value = _read_call(
                page, "get_text", mode, flags=fitz.TEXT_PRESERVE_WHITESPACE
            )
            selected_record = (
                preserve_record if preserve_record.get("status") == "ok" else default_record
            )
            selected_value = (
                preserve_value if preserve_record.get("status") == "ok" else default_value
            )
            if preserve_record.get("status") != "ok" and default_record.get("status") != "ok":
                selected_value = None
            text_values[mode] = selected_value
            text_variants[mode] = {
                "default": default_record,
                "preserve_whitespace": preserve_record,
            }
            page_reads[f"text.{mode}.default"] = default_record
            page_reads[f"text.{mode}.preserve_whitespace"] = preserve_record
            page_reads[f"text.{mode}"] = selected_record

        words_default_record, words_default_value = _read_call(page, "get_text", "words")
        words_flags_zero_record, words_flags_zero_value = _read_call(
            page, "get_text", "words", flags=0
        )
        words_preserve_record, words_preserve_value = _read_call(
            page, "get_text", "words", flags=fitz.TEXT_PRESERVE_WHITESPACE
        )
        words_record = (
            words_default_record
            if words_default_record.get("status") == "ok"
            else words_preserve_record
        )
        words_value = (
            words_default_value
            if words_default_record.get("status") == "ok"
            else words_preserve_value
        )
        if (
            words_default_record.get("status") != "ok"
            and words_preserve_record.get("status") != "ok"
        ):
            words_value = None
        page_reads["text.words.default"] = words_default_record
        page_reads["text.words.flags_zero"] = words_flags_zero_record
        page_reads["text.words.preserve_whitespace"] = words_preserve_record
        page_reads["text.words"] = words_record
        for index, region in enumerate((*frozen_allowed, *frozen_excluded)):
            clip_default_record, _ = _read_call(
                page,
                "get_text",
                "words",
                clip=_clip_value(region),
            )
            clip_preserve_record, _ = _read_call(
                page,
                "get_text",
                "words",
                flags=fitz.TEXT_PRESERVE_WHITESPACE,
                clip=_clip_value(region),
            )
            page_reads[f"text.words.clip.{index}.default"] = clip_default_record
            page_reads[f"text.words.clip.{index}.preserve_whitespace"] = clip_preserve_record
            page_reads[f"text.words.clip.{index}"] = (
                clip_default_record
                if clip_default_record.get("status") == "ok"
                else clip_preserve_record
            )

        drawings_default_record, drawings_default_value = _read_call(page, "get_drawings")
        drawings_extended_record, drawings_extended_value = _read_call(
            page, "get_drawings", extended=True
        )
        drawings_record = (
            drawings_extended_record
            if drawings_extended_record.get("status") == "ok"
            else drawings_default_record
        )
        drawings_value = (
            drawings_extended_value
            if drawings_extended_record.get("status") == "ok"
            else drawings_default_value
        )
        if (
            drawings_extended_record.get("status") != "ok"
            and drawings_default_record.get("status") != "ok"
        ):
            drawings_value = None
        page_reads["drawings.default"] = drawings_default_record
        page_reads["drawings.extended"] = drawings_extended_record
        page_reads["drawings"] = drawings_record

        raw_text_value = text_values["rawdict"]
        dict_text_value = text_values["dict"]
        raw_text = raw_text_value if isinstance(raw_text_value, Mapping) else None
        if raw_text is None and isinstance(dict_text_value, Mapping):
            raw_text = dict_text_value
        raw_text = raw_text or {}
        words = words_value if isinstance(words_value, Iterable) and not isinstance(words_value, (str, bytes, Mapping)) else ()
        drawings = drawings_value if isinstance(drawings_value, Iterable) and not isinstance(drawings_value, (str, bytes, Mapping)) else ()

    text_blocks = []
    lines = []
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
        lines.extend(
            _freeze(_thaw(line)) for line in frozen_block.get("lines", ())
        )
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
            **{
                mode: {
                    "selected": (
                        text_variants[mode]["preserve_whitespace"]
                        if text_variants[mode]["preserve_whitespace"].get("status") == "ok"
                        else text_variants[mode]["default"]
                    ),
                    "variants": text_variants[mode],
                }
                for mode in ("rawdict", "dict", "text", "blocks")
            },
            "words": {
                "selected": words_record,
                "variants": {
                    "default": words_default_record,
                    "flags_zero": words_flags_zero_record,
                    "preserve_whitespace": words_preserve_record,
                },
                "clip_regions": tuple(
                    _thaw(region) for region in (*frozen_allowed, *frozen_excluded)
                ),
            },
            "drawings": {
                "selected": drawings_record,
                "variants": {
                    "default": drawings_default_record,
                    "extended": drawings_extended_record,
                },
            },
        }
    )
    frozen_spans = tuple(spans)
    frozen_characters = tuple(characters)
    frozen_words = _word_records(words)
    frozen_drawings = _drawing_records(drawings)

    if lightweight:
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
            resources=_freeze({}),
            raster=_freeze({}),
            bboxlog=_freeze({}),
            table_fallback=_freeze({}),
            page_reads=_freeze(page_reads),
            lines=tuple(lines),
            word_variants=_freeze({}),
        )

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

    pixmap_variants = {}
    production_matrix = fitz.Matrix(0.1, 0.1)
    production_record, _ = _read_call(
        page,
        "get_pixmap",
        matrix=production_matrix,
        colorspace=fitz.csRGB,
        alpha=False,
    )
    pixmap_variants["production"] = production_record
    page_reads["pixmap.production"] = production_record

    ml_dpi = _finite_float(ml_render_dpi)
    if ml_dpi <= 0:
        raise ValueError("ml_render_dpi must be positive")
    ml_factor = ml_dpi / 72.0
    ml_matrix = fitz.Matrix(ml_factor, ml_factor)
    ml_record, _ = _read_call(
        page,
        "get_pixmap",
        matrix=ml_matrix,
        alpha=False,
    )
    pixmap_variants["ml"] = ml_record
    page_reads["pixmap.ml"] = ml_record
    pixmap_record = pixmap_variants["production"]
    bboxlog_record, _ = _read_call(page, "get_bboxlog")
    tables_record = _find_tables_record(page)
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
        raster=_freeze(
            {
                "purpose": "algorithm",
                "selected_variant": "production",
                "variants": pixmap_variants,
                **pixmap_record,
            }
        ),
        bboxlog=_freeze(bboxlog_record),
        table_fallback=_freeze(tables_record),
        page_reads=_freeze(page_reads),
        lines=tuple(lines),
        word_variants={
            "default": _word_records(
                words_default_value
                if isinstance(words_default_value, Iterable)
                and not isinstance(words_default_value, (str, bytes, Mapping))
                else ()
            ),
            "flags_zero": _word_records(
                words_flags_zero_value
                if isinstance(words_flags_zero_value, Iterable)
                and not isinstance(words_flags_zero_value, (str, bytes, Mapping))
                else ()
            ),
            "preserve_whitespace": _word_records(
                words_preserve_value
                if isinstance(words_preserve_value, Iterable)
                and not isinstance(words_preserve_value, (str, bytes, Mapping))
                else ()
            ),
        },
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
    footer_positions = {
        _source_position(line, 2)
        for line in snapshot.lines
        if _is_footer_line(line, snapshot.geometry)
    }
    valid_span = lambda span: (
        bool(str(span.get("text", "")).strip())
        and _source_position(span, 3)[:2] not in footer_positions
    )
    selected_span = lambda span: valid_span(span) and _selected(
        span, allowed, excluded
    )
    valid_span_positions = {
        _source_position(span, 3)
        for span in snapshot.spans
        if selected_span(span)
    }
    valid_line = lambda line: (
        _source_position(line, 2) not in footer_positions
        and bool(_line_text(line).strip())
        and any(
            _source_position(span, 2) == _source_position(line, 2)
            and selected_span(span)
            for span in snapshot.spans
        )
    )
    valid_char = lambda char: (
        _source_position(char, 3) in valid_span_positions
    )
    filtered_lines = _ordered_filtered(
        snapshot.lines, (), (), lambda line: valid_line(line)
    )
    filtered_spans = _ordered_filtered(
        snapshot.spans, (), (), lambda span: selected_span(span)
    )
    line_orders = {
        _source_position(line, 2): line["filtered_order"]
        for line in filtered_lines
    }
    span_orders = {
        _source_position(span, 3): span["filtered_order"]
        for span in filtered_spans
    }
    filtered_blocks = []
    for block in snapshot.text_blocks:
        block_lines = [
            line
            for line in snapshot.lines
            if _source_position(line, 1) == _source_position(block, 1)
            and valid_line(line)
        ]
        if not block_lines and block.get("lines"):
            continue
        if not block_lines and not block.get("lines") and not _selected(
            block, allowed, excluded
        ):
            continue
        copied = _thaw(block)
        copied["lines"] = [_thaw(line) for line in block_lines]
        for line in copied["lines"]:
            line["filtered_order"] = line_orders[_source_position(line, 2)]
            line["spans"] = [
                _thaw(span)
                for span in snapshot.spans
                if _source_position(span, 2) == _source_position(line, 2)
                and selected_span(span)
            ]
            for span in line["spans"]:
                span["filtered_order"] = span_orders[_source_position(span, 3)]
        filtered_blocks.append(_freeze(copied))
    filtered_blocks = tuple(
        dict(block, filtered_order=index)
        for index, block in enumerate(filtered_blocks)
    )
    valid_word = lambda word: _source_position(word, 2) not in footer_positions
    return FilteredSnapshotEvidence(
        page_index=snapshot.page_index,
        geometry=snapshot.geometry,
        text_blocks=tuple(_freeze(block) for block in filtered_blocks),
        lines=filtered_lines,
        spans=filtered_spans,
        characters=_ordered_filtered(snapshot.characters, allowed, excluded, valid_char),
        words=_ordered_filtered(snapshot.words, allowed, excluded, valid_word),
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
        "lines": _thaw(snapshot.lines),
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


def snapshot_pixmap(
    snapshot: PageSnapshot,
    *,
    variant: str | None = None,
    matrix: Any = None,
    colorspace: Any = None,
    alpha: bool | None = None,
) -> Mapping[str, Any]:
    """Return one captured pixmap record without touching the source page."""

    variants = snapshot.raster.get("variants", {})
    if variant is not None:
        return variants[variant]
    if matrix is None and colorspace is None and alpha is None:
        return variants.get(
            snapshot.raster.get("selected_variant", "production"),
            snapshot.raster,
        )
    expected = {
        key: _plain(value)
        for key, value in (
            ("matrix", matrix),
            ("colorspace", colorspace),
            ("alpha", alpha),
        )
        if value is not None
    }
    for record in variants.values():
        if all(record.get("kwargs", {}).get(key) == value for key, value in expected.items()):
            return record
    raise KeyError("no captured pixmap matches the requested parameters")


def _word_intersects_clip(word: Mapping[str, Any], clip: Mapping[str, Any]) -> bool:
    box = _bbox(word)
    if box is None:
        return False
    return not (
        box[2] <= clip["x0"]
        or box[0] >= clip["x1"]
        or box[3] <= clip["y0"]
        or box[1] >= clip["y1"]
    )


def _clip_word_from_characters(
    word: Mapping[str, Any],
    characters: Sequence[Mapping[str, Any]],
    clip: Mapping[str, Any],
    spans: Mapping[tuple[Any, ...], Mapping[str, Any]] | None = None,
    line_directions: Mapping[tuple[Any, Any], Any] | None = None,
    use_glyph_geometry: bool = True,
) -> tuple[Mapping[str, Any], ...]:
    word_box = _bbox(word)
    if word_box is None:
        return ()
    word_characters = []
    for character in characters:
        char_box = _bbox(character)
        if char_box is None:
            continue
        if _source_position(character, 2) != (
            word.get("block_index"),
            word.get("line_index"),
        ):
            continue
        direction = (
            line_directions.get(_source_position(character, 2))
            if line_directions
            else None
        )
        rotated = (
            isinstance(direction, (tuple, list))
            and len(direction) >= 2
            and abs(_safe_finite(direction[0]) - 1.0) > 1e-6
        )
        boundary_epsilon = 1e-3 if rotated else 0.0
        if not (
            char_box[2] <= word_box[0] + boundary_epsilon
            or char_box[0] >= word_box[2] - boundary_epsilon
            or char_box[3] <= word_box[1] + boundary_epsilon
            or char_box[1] >= word_box[3] - boundary_epsilon
        ):
            word_characters.append(character)
    word_characters.sort(key=lambda character: character.get("source_order", 0))
    if not word_characters:
        return ()
    character_text = "".join(str(character.get("c", "")) for character in word_characters)
    word_text = str(word.get("text", ""))
    if character_text != word_text:
        return ()
    if len(word_characters) != len(word_text):
        return ()

    def glyph_clip_box(character: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
        origin = character.get("origin")
        glyph_bbox = character.get("glyph_bbox")
        if glyph_bbox is None:
            return None
        if not isinstance(origin, (tuple, list)) or len(origin) < 2:
            return None
        try:
            span = spans.get(_source_position(character, 3)) if spans else None
            size = _finite_float(span.get("size")) if span else 0.0
            origin_x = _finite_float(origin[0])
            origin_y = _finite_float(origin[1])
            if size <= 0.0 or len(glyph_bbox) != 4:
                return None
            direction = span.get("dir")
            if not isinstance(direction, (tuple, list)) and line_directions:
                direction = line_directions.get(_source_position(character, 2))
            if isinstance(direction, (tuple, list)) and len(direction) >= 2:
                dx = _finite_float(direction[0])
                dy = _finite_float(direction[1])
                length = math.hypot(dx, dy)
                if length > 0.0:
                    dx /= length
                    dy /= length
                    nx, ny = dy, -dx
                    points = [
                        (
                            origin_x + dx * _finite_float(glyph_x) * size
                            + nx * _finite_float(glyph_y) * size,
                            origin_y + dy * _finite_float(glyph_x) * size
                            + ny * _finite_float(glyph_y) * size,
                        )
                        for glyph_x, glyph_y in (
                            (glyph_bbox[0], glyph_bbox[1]),
                            (glyph_bbox[0], glyph_bbox[3]),
                            (glyph_bbox[2], glyph_bbox[1]),
                            (glyph_bbox[2], glyph_bbox[3]),
                        )
                    ]
                    return (
                        min(point[0] for point in points),
                        min(point[1] for point in points),
                        max(point[0] for point in points),
                        max(point[1] for point in points),
                    )
            return (
                origin_x + _finite_float(glyph_bbox[0]) * size,
                origin_y - _finite_float(glyph_bbox[3]) * size,
                origin_x + _finite_float(glyph_bbox[2]) * size,
                origin_y - _finite_float(glyph_bbox[1]) * size,
            )
        except (TypeError, ValueError, OverflowError, RuntimeError):
            return None

    def selected_by_clip(character: Mapping[str, Any]) -> bool:
        char_box = _bbox(character)
        assert char_box is not None
        direction = (
            line_directions.get(_source_position(character, 2))
            if line_directions
            else None
        )
        glyph_box = glyph_clip_box(character) or char_box
        selection_box = glyph_box if use_glyph_geometry else char_box
        return not (
            selection_box[2] <= clip["x0"]
            or selection_box[0] >= clip["x1"]
            or selection_box[3] <= clip["y0"]
            or selection_box[1] >= clip["y1"]
        )

    selected = [
        (index, character)
        for index, character in enumerate(word_characters)
        if selected_by_clip(character)
    ]
    if not selected:
        return ()

    runs: list[list[Mapping[str, Any]]] = []
    previous_index = None
    for index, character in selected:
        skipped = () if previous_index is None else word_characters[previous_index + 1 : index]
        split_run = previous_index is None or any(
            str(item.get("c", "")).isspace() for item in skipped
        )
        if not split_run and index != previous_index + 1:
            previous_box = _bbox(word_characters[previous_index])
            current_box = _bbox(character)
            direction = _unit_direction(
                line_directions.get(_source_position(character, 2))
            )
            if previous_box is None or current_box is None or direction is None:
                split_run = True
            else:
                previous_flow = _project_bbox(previous_box, direction)
                current_flow = _project_bbox(current_box, direction)
                gap = max(
                    previous_flow[0] - current_flow[1],
                    current_flow[0] - previous_flow[1],
                    0.0,
                )
                split_run = gap > 1e-6
        if split_run:
            runs.append([character])
        else:
            runs[-1].append(character)
        previous_index = index

    clipped_words = []
    for run in runs:
        copied = _thaw(word)
        copied["text"] = "".join(str(character.get("c", "")) for character in run)
        boxes = [_bbox(character) for character in run]
        copied["bbox"] = (
            min(box[0] for box in boxes if box is not None),
            min(box[1] for box in boxes if box is not None),
            max(box[2] for box in boxes if box is not None),
            max(box[3] for box in boxes if box is not None),
        )
        clipped_words.append(_freeze(copied))
    return tuple(clipped_words)


def _legacy_snapshot_words_for_clip(
    snapshot: PageSnapshot,
    clip: Any,
    *,
    flags: int | None = None,
) -> tuple[Any, ...]:
    """Return captured words intersecting a PyMuPDF-compatible clip rectangle."""

    clip_values = _region(clip)
    explicit_flags = flags is not None
    variant = (
        "preserve_whitespace"
        if flags is not None and flags & fitz.TEXT_PRESERVE_WHITESPACE
        else "flags_zero"
        if flags == 0
        else "default"
    )
    words = snapshot.word_variants.get(variant, snapshot.words)
    geometry = snapshot.geometry
    if (
        clip_values["x0"] <= _safe_finite(geometry.get("x0"))
        and clip_values["y0"] <= _safe_finite(geometry.get("y0"))
        and clip_values["x1"] >= _safe_finite(geometry.get("x1"))
        and clip_values["y1"] >= _safe_finite(geometry.get("y1"))
    ):
        return tuple(words)
    line_directions = {
        _source_position(line, 2): line.get("dir")
        for block in snapshot.text_blocks
        for line in block.get("lines", ())
    }
    space_widths: dict[tuple[Any, Any], float] = {}
    for character in snapshot.characters:
        if not str(character.get("c", "")).isspace():
            continue
        box = _bbox(character)
        source_line = _source_position(character, 2)
        if box is None:
            continue
        direction = line_directions.get(source_line)
        vertical = (
            isinstance(direction, (tuple, list))
            and len(direction) >= 2
            and abs(_safe_finite(direction[1])) > abs(_safe_finite(direction[0]))
        )
        width = (box[3] - box[1]) if vertical else (box[2] - box[0])
        if width <= 0.0:
            continue
        previous = space_widths.get(source_line)
        if previous is None or width < previous:
            space_widths[source_line] = width
    result = []
    spans = {
        _source_position(span, 3): span
        for span in snapshot.spans
    }
    for word in words:
        clipped_words = _clip_word_from_characters(
            word,
            snapshot.characters,
            clip_values,
            spans,
            line_directions,
            use_glyph_geometry=not explicit_flags,
        )
        result.extend(clipped_words)
    local_block_indices: dict[Any, int] = {}
    local_word_indices: dict[tuple[int, int], int] = {}
    source_word_indices: dict[tuple[Any, Any], int] = {}
    segment_for_word: dict[int, tuple[Any, int]] = {}
    segment_state: dict[Any, dict[str, Any]] = {}
    for result_index, word in enumerate(result):
        raw_block_index = word.get("block_index")
        raw_line_index = word.get("line_index")
        state = segment_state.setdefault(
            raw_block_index,
            {"segment": 0, "last_line": None, "last_line_left": None},
        )
        box = _bbox(word)
        direction = line_directions.get((raw_block_index, raw_line_index))
        horizontal = not (
            isinstance(direction, (tuple, list))
            and len(direction) >= 2
            and abs(_safe_finite(direction[1])) > abs(_safe_finite(direction[0]))
        )
        if (
            box is not None
            and state["last_line"] is not None
            and raw_line_index != state["last_line"]
            and horizontal
            and state["last_line_left"] is not None
            and box[0] > state["last_line_left"] + 1e-3
        ):
            state["segment"] += 1
        if raw_line_index != state["last_line"] and box is not None:
            state["last_line_left"] = box[0]
        state["last_line"] = raw_line_index
        segment_for_word[result_index] = (raw_block_index, state["segment"])

    selected_lines: dict[Any, list[Any]] = {}
    for result_index, word in enumerate(result):
        segment = segment_for_word[result_index]
        raw_line_index = word.get("line_index")
        lines = selected_lines.setdefault(segment, [])
        if raw_line_index not in lines:
            lines.append(raw_line_index)
    preserve_lines = {
        segment: any(
            current - previous > 1
            for previous, current in zip(lines, lines[1:])
        )
        for segment, lines in selected_lines.items()
    }
    normalized = []
    previous_word = None
    current_segment = None
    current_line = -1
    for result_index, word in enumerate(result):
        raw_block_index = word.get("block_index")
        raw_line_index = word.get("line_index")
        segment = segment_for_word[result_index]
        block_index = local_block_indices.setdefault(
            segment, len(local_block_indices)
        )
        if preserve_lines.get(segment):
            line_index = raw_line_index
        elif current_segment != segment:
            current_segment = segment
            current_line = 0
            line_index = current_line
        elif previous_word is None or previous_word.get("line_index") != raw_line_index:
            current_line += 1
            line_index = current_line
        else:
            previous_box = _bbox(previous_word)
            current_box = _bbox(word)
            direction = line_directions.get((raw_block_index, raw_line_index))
            vertical = (
                isinstance(direction, (tuple, list))
                and len(direction) >= 2
                and abs(_safe_finite(direction[1])) > abs(_safe_finite(direction[0]))
            )
            space_width = space_widths.get((raw_block_index, raw_line_index))
            if vertical and previous_word.get("word_index") != word.get("word_index"):
                dy = _safe_finite(direction[1]) if isinstance(direction, (tuple, list)) else 0.0
                gap = (
                    previous_box[1] - current_box[3]
                    if dy < 0.0
                    else current_box[1] - previous_box[3]
                )
                if space_width is None or gap > 2.0 * space_width:
                    current_line += 1
            elif (
                previous_box is not None
                and current_box is not None
                and previous_word.get("word_index") != word.get("word_index")
                and space_width is not None
                and current_box[0] - previous_box[2] > 2.0 * space_width
            ):
                current_line += 1
            line_index = current_line
        key = (block_index, line_index)
        word_index = local_word_indices.get(key, 0)
        local_word_indices[key] = word_index + 1
        copied = _thaw(word)
        if explicit_flags:
            copied["block_index"] = raw_block_index
            copied["line_index"] = raw_line_index
            source_key = (raw_block_index, raw_line_index)
            copied["word_index"] = source_word_indices.get(source_key, 0)
            source_word_indices[source_key] = copied["word_index"] + 1
        else:
            copied["block_index"] = block_index
            copied["line_index"] = line_index
            copied["word_index"] = word_index
        normalized.append(_freeze(copied))
        previous_word = word
    return tuple(normalized)


def _unit_direction(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    dx = _safe_finite(value[0])
    dy = _safe_finite(value[1])
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    return dx / length, dy / length


def _project_bbox(
    box: tuple[float, float, float, float],
    direction: tuple[float, float],
) -> tuple[float, float, float, float]:
    dx, dy = direction
    nx, ny = -dy, dx
    values = [
        (box[0] * dx + box[1] * dy, box[0] * nx + box[1] * ny),
        (box[0] * dx + box[3] * dy, box[0] * nx + box[3] * ny),
        (box[2] * dx + box[1] * dy, box[2] * nx + box[1] * ny),
        (box[2] * dx + box[3] * dy, box[2] * nx + box[3] * ny),
    ]
    flow = [item[0] for item in values]
    normal = [item[1] for item in values]
    return min(flow), max(flow), min(normal), max(normal)


def _character_glyph_clip_box(
    character: Mapping[str, Any],
    spans: Mapping[tuple[Any, ...], Mapping[str, Any]],
    line_directions: Mapping[tuple[Any, Any], Any],
) -> tuple[float, float, float, float] | None:
    char_box = _bbox(character)
    if char_box is None:
        return None
    span = spans.get(_source_position(character, 3))
    origin = character.get("origin")
    glyph_bbox = character.get("glyph_bbox")
    if not span or glyph_bbox is None:
        return char_box
    if not isinstance(origin, (tuple, list)) or len(origin) < 2:
        return char_box
    try:
        font_name = span.get("font")
        size = _finite_float(span.get("size"))
        if not isinstance(font_name, str) or not font_name or size <= 0.0:
            return char_box
        if len(glyph_bbox) != 4:
            return char_box
        direction = _unit_direction(span.get("dir"))
        if direction is None:
            direction = _unit_direction(
                line_directions.get(_source_position(character, 2))
            )
        if direction is None:
            return char_box
        dx, dy = direction
        nx, ny = dy, -dx
        origin_x = _finite_float(origin[0])
        origin_y = _finite_float(origin[1])
        points = [
            (
                origin_x + dx * _finite_float(glyph_x) * size
                + nx * _finite_float(glyph_y) * size,
                origin_y + dy * _finite_float(glyph_x) * size
                + ny * _finite_float(glyph_y) * size,
            )
            for glyph_x, glyph_y in (
                (glyph_bbox[0], glyph_bbox[1]),
                (glyph_bbox[0], glyph_bbox[3]),
                (glyph_bbox[2], glyph_bbox[1]),
                (glyph_bbox[2], glyph_bbox[3]),
            )
        ]
        return (
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        )
    except (TypeError, ValueError, OverflowError, RuntimeError):
        return char_box


def _boundary_space_is_clip_artifact(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    """Accept a boundary space only when clipping explains its selection."""

    if not (
        previous.get("clip_cuts_normal", False)
        and current.get("clip_cuts_normal", False)
    ):
        return False
    normal_remainder = current.get("clip_normal_max", current["normal_max"]) < (
        max(previous["normal_max"], current["normal_max"])
        - _CLIP_BOUNDARY_TOLERANCE
    )
    flow_remainder = previous.get("clip_flow_start", previous["flow_start"]) > (
        previous["flow_start"]
        + max(previous.get("word_gap", 0.0), _FLOW_CONTINUITY_TOLERANCE)
    )
    return normal_remainder or flow_remainder


def _clipped_line_chunk_can_merge(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> bool:
    """Join clipped raw lines only when their selected flow is continuous."""

    previous_source_line = previous.get(
        "last_source_line", previous["source_line"]
    )
    if previous_source_line[0] != current["source_line"][0]:
        return False
    if previous.get("source_line_count", 1) >= 2:
        return False
    direction = previous["direction"]
    if abs(
        direction[0] * current["direction"][0]
        + direction[1] * current["direction"][1]
    ) < 1.0 - _DIRECTION_ALIGNMENT_TOLERANCE:
        return False

    previous_nonspace = [
        item
        for item in previous["items"]
        if not str(item["character"].get("c", "")).isspace()
    ]
    current_nonspace = [
        item
        for item in current["items"]
        if not str(item["character"].get("c", "")).isspace()
    ]
    if not previous_nonspace or not current_nonspace:
        return False
    vertical = abs(direction[1]) > abs(direction[0])
    has_space = len(previous_nonspace) != len(previous["items"]) or len(
        current_nonspace
    ) != len(current["items"])
    previous_trailing_space = bool(previous["items"]) and str(
        previous["items"][-1]["character"].get("c", "")
    ).isspace()
    current_leading_space = bool(current["items"]) and str(
        current["items"][0]["character"].get("c", "")
    ).isspace()
    boundary_space = previous_trailing_space or current_leading_space
    if vertical:
        if has_space and direction[1] < 0.0 and boundary_space:
            return False

        def first_word(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
            result: list[Mapping[str, Any]] = []
            for item in items:
                if str(item["character"].get("c", "")).isspace():
                    if result:
                        break
                    continue
                result.append(item)
            return result

        def last_word(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
            result: list[Mapping[str, Any]] = []
            for item in reversed(items):
                if str(item["character"].get("c", "")).isspace():
                    if result:
                        break
                    continue
                result.append(item)
            result.reverse()
            return result

        previous_word = (
            last_word(previous["items"])
        )
        current_word = (
            first_word(current["items"])
        )
        if not previous_word or not current_word:
            return False
        normal_overlap = min(previous["normal_max"], current["normal_max"]) - max(
            previous["normal_min"], current["normal_min"]
        )
        normal_shortest = min(
            previous["normal_max"] - previous["normal_min"],
            current["normal_max"] - current["normal_min"],
        )
        if (
            normal_shortest > _DEGENERATE_PROJECTION_TOLERANCE
            and normal_overlap / normal_shortest < _NORMAL_OVERLAP_RATIO
        ):
            return False
        if not has_space:
            return False
        boundary_space_artifact = _boundary_space_is_clip_artifact(previous, current)
        if direction[1] > 0.0:
            if has_space and not current_leading_space:
                return False
            if current_leading_space and not boundary_space_artifact:
                return False
            previous_word_flow = _project_bbox(
                (
                    min(_bbox(item["character"])[0] for item in previous_word),
                    min(_bbox(item["character"])[1] for item in previous_word),
                    max(_bbox(item["character"])[2] for item in previous_word),
                    max(_bbox(item["character"])[3] for item in previous_word),
                ),
                direction,
            )
            current_word_flow = _project_bbox(
                (
                    min(_bbox(item["character"])[0] for item in current_word),
                    min(_bbox(item["character"])[1] for item in current_word),
                    max(_bbox(item["character"])[2] for item in current_word),
                    max(_bbox(item["character"])[3] for item in current_word),
                ),
                direction,
            )
            flow_overlap = min(
                previous_word_flow[1], current_word_flow[1]
            ) - max(previous_word_flow[0], current_word_flow[0])
            return (
                current_word_flow[0] >= previous_word_flow[0]
                and current_word_flow[1] > previous_word_flow[1]
                and flow_overlap > 0.0
                and flow_overlap
                <= max(previous.get("word_gap", 0.0), current.get("word_gap", 0.0))
            ) or (
                not has_space
                and len(previous_nonspace) == 1
                and len(current_nonspace) == 1
                and flow_overlap > 0.0
                and current_word_flow[1] > current_word_flow[0]
                and (
                    current_word_flow[0] >= previous_word_flow[0]
                    or previous_word_flow[0] - current_word_flow[0]
                    <= max(
                        1.0,
                        (previous_word_flow[1] - previous_word_flow[0])
                        * _SINGLE_GLYPH_EXTENSION_RATIO,
                    )
                )
            ) or (
                has_space
                and boundary_space
                and bool(current["items"])
                and str(current["items"][0]["character"].get("c", "")).isspace()
                and len(current_word) == 1
                and boundary_space_artifact
            )
        if has_space or len(previous_nonspace) > 2 or len(current_nonspace) > 2:
            return False
        previous_word_flow = _project_bbox(
            (
                min(_bbox(item["character"])[0] for item in previous_word),
                min(_bbox(item["character"])[1] for item in previous_word),
                max(_bbox(item["character"])[2] for item in previous_word),
                max(_bbox(item["character"])[3] for item in previous_word),
            ),
            direction,
        )
        current_word_flow = _project_bbox(
            (
                min(_bbox(item["character"])[0] for item in current_word),
                min(_bbox(item["character"])[1] for item in current_word),
                max(_bbox(item["character"])[2] for item in current_word),
                max(_bbox(item["character"])[3] for item in current_word),
            ),
            direction,
        )
        start_extension = previous_word_flow[0] - current_word_flow[0]
        if start_extension > 0.0:
            if start_extension < max(
                1.0,
                (previous_word_flow[1] - previous_word_flow[0])
                * _SINGLE_GLYPH_EXTENSION_RATIO,
            ):
                return False
        elif previous_word_flow[1] - previous_word_flow[0] > _SHORT_GLYPH_FLOW_THRESHOLD:
            return False
        return current_word_flow[1] > previous_word_flow[1]

    previous_item = previous["items"][-1]
    current_item = current["items"][0]
    previous_box = _bbox(previous_item["character"])
    current_box = _bbox(current_item["character"])
    if previous_box is None or current_box is None:
        return False
    previous_flow = _project_bbox(previous_box, direction)
    current_flow = _project_bbox(current_box, direction)
    normal_overlap = min(previous["normal_max"], current["normal_max"]) - max(
        previous["normal_min"], current["normal_min"]
    )
    normal_shortest = min(
        previous["normal_max"] - previous["normal_min"],
        current["normal_max"] - current["normal_min"],
    )
    if (
        normal_shortest > _DEGENERATE_PROJECTION_TOLERANCE
        and normal_overlap / normal_shortest < _NORMAL_OVERLAP_RATIO
    ):
        return False
    overlap = min(previous_flow[1], current_flow[1]) - max(
        previous_flow[0], current_flow[0]
    )
    shortest = min(
        previous_flow[1] - previous_flow[0],
        current_flow[1] - current_flow[0],
    )
    if (
        shortest > _DEGENERATE_PROJECTION_TOLERANCE
        and 0.0 < overlap / shortest <= _NORMAL_OVERLAP_RATIO
    ):
        return True
    if direction[1] > 0.0:
        gap = max(
            previous_flow[0] - current_flow[1],
            current_flow[0] - previous_flow[1],
            0.0,
        )
        return gap <= _FLOW_CONTINUITY_TOLERANCE
    return False


def _snapshot_words_from_clipped_characters(
    snapshot: PageSnapshot,
    clip: Mapping[str, Any],
    words: Sequence[Mapping[str, Any]],
    line_directions: Mapping[tuple[Any, Any], Any],
    *,
    preserve_source_indices: bool = False,
) -> tuple[Any, ...]:
    spans = {_source_position(span, 3): span for span in snapshot.spans}
    selected = []
    for character in snapshot.characters:
        char_box = _bbox(character)
        if char_box is None:
            continue
        direction = _unit_direction(
            line_directions.get(_source_position(character, 2))
        )
        if direction is None:
            continue
        glyph_box = _character_glyph_clip_box(character, spans, line_directions)
        selection_box = (
            char_box
            if preserve_source_indices or str(character.get("c", "")).isspace()
            else glyph_box
        )
        if selection_box is None or (
            selection_box[2] <= clip["x0"]
            or selection_box[0] >= clip["x1"]
            or selection_box[3] <= clip["y0"]
            or selection_box[1] >= clip["y1"]
        ):
            continue
        flow_start, flow_end, normal_min, normal_max = _project_bbox(
            char_box, direction
        )
        selected.append(
            {
                "character": character,
                "direction": direction,
                "flow_start": flow_start,
                "flow_end": flow_end,
                "normal_min": normal_min,
                "normal_max": normal_max,
            }
        )
    if not selected:
        return ()

    space_widths: dict[tuple[Any, Any], float] = {}
    for character in snapshot.characters:
        if not str(character.get("c", "")).isspace():
            continue
        source_line = _source_position(character, 2)
        direction = _unit_direction(line_directions.get(source_line))
        char_box = _bbox(character)
        if direction is None or char_box is None:
            continue
        flow_start, flow_end, _normal_min, _normal_max = _project_bbox(
            char_box, direction
        )
        width = flow_end - flow_start
        if width > 0.0:
            previous = space_widths.get(source_line)
            if previous is None or width < previous:
                space_widths[source_line] = width

    line_chunks: list[dict[str, Any]] = []
    for item in selected:
        direction = item["direction"]
        source_line = _source_position(item["character"], 2)
        if not line_chunks:
            line_chunks.append(
                {
                    "direction": direction,
                    "items": [item],
                    "source_line": source_line,
                    "flow_start": item["flow_start"],
                    "flow_end": item["flow_end"],
                    "normal_min": item["normal_min"],
                    "normal_max": item["normal_max"],
                    "word_gap": 2.0 * space_widths.get(source_line, 0.0),
                    "last_source_line": source_line,
                    "source_line_count": 1,
                    "clip_cuts_normal": False,
                }
            )
            continue
        current = line_chunks[-1]
        if source_line == current["source_line"]:
            current["items"].append(item)
            current["flow_start"] = min(current["flow_start"], item["flow_start"])
            current["flow_end"] = max(current["flow_end"], item["flow_end"])
            current["normal_min"] = min(current["normal_min"], item["normal_min"])
            current["normal_max"] = max(current["normal_max"], item["normal_max"])
        else:
            line_chunks.append(
                {
                    "direction": direction,
                    "items": [item],
                    "source_line": source_line,
                    "flow_start": item["flow_start"],
                    "flow_end": item["flow_end"],
                    "normal_min": item["normal_min"],
                    "normal_max": item["normal_max"],
                    "word_gap": 2.0 * space_widths.get(source_line, 0.0),
                    "last_source_line": source_line,
                    "source_line_count": 1,
                    "clip_cuts_normal": False,
                }
            )

    for chunk in line_chunks:
        clip_projection = _project_bbox(
            (clip["x0"], clip["y0"], clip["x1"], clip["y1"]),
            chunk["direction"],
        )
        chunk["clip_cuts_normal"] = (
            clip_projection[2] > chunk["normal_min"] + _CLIP_BOUNDARY_TOLERANCE
            or clip_projection[3] < chunk["normal_max"] - _CLIP_BOUNDARY_TOLERANCE
        )
        chunk["clip_flow_start"] = clip_projection[0]
        chunk["clip_normal_max"] = clip_projection[3]

    line_groups: list[dict[str, Any]] = []
    for chunk in line_chunks:
        if line_groups and _clipped_line_chunk_can_merge(line_groups[-1], chunk):
            current = line_groups[-1]
            strip_boundary_space = (
                current.get("clip_cuts_normal") and chunk.get("clip_cuts_normal")
            ) or (
                chunk.get("clip_flow_start", chunk["flow_start"])
                > current["flow_start"] + current.get("word_gap", 0.0)
                and bool(chunk["items"])
                and str(chunk["items"][0]["character"].get("c", "")).isspace()
                and len(
                    [
                        item
                        for item in chunk["items"]
                        if not str(item["character"].get("c", "")).isspace()
                    ]
                ) == 1
            )
            if strip_boundary_space:
                chunk_items = list(chunk["items"])
                while chunk_items and str(
                    chunk_items[0]["character"].get("c", "")
                ).isspace():
                    chunk_items.pop(0)
                current["items"].extend(chunk_items)
            else:
                current["items"].extend(chunk["items"])
            current["flow_start"] = min(current["flow_start"], chunk["flow_start"])
            current["flow_end"] = max(current["flow_end"], chunk["flow_end"])
            current["normal_min"] = min(current["normal_min"], chunk["normal_min"])
            current["normal_max"] = max(current["normal_max"], chunk["normal_max"])
            current["word_gap"] = max(current["word_gap"], chunk["word_gap"])
            current["last_source_line"] = chunk["source_line"]
            current["source_line_count"] = current.get("source_line_count", 1) + 1
            current["clip_cuts_normal"] = (
                current.get("clip_cuts_normal", False)
                or chunk.get("clip_cuts_normal", False)
            )
            current["clip_flow_start"] = chunk.get(
                "clip_flow_start", current.get("clip_flow_start", current["flow_start"])
            )
            current["clip_normal_max"] = max(
                current.get("clip_normal_max", current["normal_max"]),
                chunk.get("clip_normal_max", chunk["normal_max"]),
            )
        else:
            line_groups.append(chunk)

    words_by_line: dict[tuple[Any, Any], list[Mapping[str, Any]]] = {}
    for word in words:
        words_by_line.setdefault(_source_position(word, 2), []).append(word)

    def template_for(character: Mapping[str, Any]) -> Mapping[str, Any]:
        line_key = _source_position(character, 2)
        candidates = words_by_line.get(line_key, ())
        char_box = _bbox(character)
        if char_box is not None:
            center_x = (char_box[0] + char_box[2]) / 2.0
            center_y = (char_box[1] + char_box[3]) / 2.0
            containing = []
            for candidate in candidates:
                box = _bbox(candidate)
                if box is None:
                    continue
                if box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]:
                    containing.append(candidate)
            if containing:
                return containing[0]
        return candidates[0] if candidates else {
            "bbox": char_box or (0.0, 0.0, 0.0, 0.0),
            "text": "",
            "block_index": 0,
            "line_index": 0,
            "word_index": 0,
            "raw_source_position": line_key + (0,),
            "source_order": 0,
            "extra": (),
        }

    raw_lines = []
    for line in line_groups:
        word_groups: list[list[Mapping[str, Any]]] = []
        current_group: list[Mapping[str, Any]] = []
        previous_item = None
        for item in line["items"]:
            character = item["character"]
            text = str(character.get("c", ""))
            if text.isspace():
                if current_group:
                    word_groups.append(current_group)
                    current_group = []
                previous_item = None
                continue
            if previous_item is not None and abs(line["direction"][1]) <= abs(
                line["direction"][0]
            ):
                previous_source_position = _source_position(
                    previous_item["character"], 4
                )
                current_source_position = _source_position(character, 4)
                skipped_source_characters = (
                    len(previous_source_position) >= 4
                    and len(current_source_position) >= 4
                    and previous_source_position[:3] == current_source_position[:3]
                    and current_source_position[3] > previous_source_position[3] + 1
                )
                gap = max(
                    previous_item["flow_start"] - item["flow_end"],
                    item["flow_start"] - previous_item["flow_end"],
                    0.0,
                )
                source_line = _source_position(character, 2)
                previous_source_line = _source_position(
                    previous_item["character"], 2
                )
                word_gap = min(
                    value
                    for value in (
                        space_widths.get(source_line, 0.0) * 2.0,
                        space_widths.get(previous_source_line, 0.0) * 2.0,
                    )
                    if value > 0.0
                ) if (
                    space_widths.get(source_line, 0.0) > 0.0
                    or space_widths.get(previous_source_line, 0.0) > 0.0
                ) else 0.0
                if skipped_source_characters or gap > word_gap:
                    if current_group:
                        word_groups.append(current_group)
                    current_group = []
            current_group.append(item)
            previous_item = item
        if current_group:
            word_groups.append(current_group)
        output_words = []
        for group in word_groups:
            boxes = [_bbox(item["character"]) for item in group]
            boxes = [box for box in boxes if box is not None]
            if not boxes:
                continue
            template = template_for(group[0]["character"])
            copied = _thaw(template)
            copied["text"] = "".join(
                str(item["character"].get("c", "")) for item in group
            )
            copied["bbox"] = (
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            )
            output_words.append(copied)
        if output_words:
            split_lines: list[list[Mapping[str, Any]]] = [[]]
            for word in output_words:
                if split_lines[-1]:
                    previous_word = split_lines[-1][-1]
                    previous_flow = _project_bbox(
                        _bbox(previous_word) or (0.0, 0.0, 0.0, 0.0),
                        line["direction"],
                    )
                    current_flow = _project_bbox(
                        _bbox(word) or (0.0, 0.0, 0.0, 0.0),
                        line["direction"],
                    )
                    gap = max(
                        previous_flow[0] - current_flow[1],
                        current_flow[0] - previous_flow[1],
                        0.0,
                    )
                    if gap > line["word_gap"]:
                        split_lines.append([])
                split_lines[-1].append(word)
            for split_line in split_lines:
                raw_lines.append(
                    {
                        "direction": line["direction"],
                        "items": split_line,
                        "source_lines": {
                            _source_position(word, 2) for word in split_line
                        },
                    }
                )
    if not raw_lines:
        return ()

    blocks: list[dict[str, Any]] = []
    for line in raw_lines:
        direction = line["direction"]
        line_boxes = [_bbox(word) for word in line["items"]]
        line_boxes = [box for box in line_boxes if box is not None]
        line_box = (
            min(box[0] for box in line_boxes),
            min(box[1] for box in line_boxes),
            max(box[2] for box in line_boxes),
            max(box[3] for box in line_boxes),
        )
        flow0, flow1, normal0, normal1 = _project_bbox(line_box, direction)
        line_normal_center = (normal0 + normal1) / 2.0
        if not blocks:
            blocks.append({"direction": direction, "flow_min": flow0, "flow_max": flow1, "normal_min": normal0, "normal_max": normal1, "source_lines": set(line["source_lines"]), "lines": [line]})
            continue
        block = blocks[-1]
        dot = direction[0] * block["direction"][0] + direction[1] * block["direction"][1]
        normal_gap = max(
            block["normal_min"] - normal1,
            normal0 - block["normal_max"],
            0.0,
        )
        normal_size = max(normal1 - normal0, block["normal_max"] - block["normal_min"], 1.0)
        flow_center = (flow0 + flow1) / 2.0
        block_flow_center = (block["flow_min"] + block["flow_max"]) / 2.0
        flow_size = max(flow1 - flow0, block["flow_max"] - block["flow_min"], 1.0)
        horizontal_flow_alignment = (
            abs(direction[0]) >= abs(direction[1])
            and abs(flow_center - block_flow_center) <= flow_size * 0.30
        )
        negative_horizontal_normal_alignment = (
            direction[0] < -0.5
            and abs(line_normal_center - (block["normal_min"] + block["normal_max"]) / 2.0)
            <= normal_size * 0.5
        )
        same_source_line_fragment = bool(
            block["source_lines"] & line["source_lines"]
        )
        if dot >= 1.0 - 1e-6 and normal_gap <= normal_size * 0.15 and (
            same_source_line_fragment
            or abs(direction[0]) < abs(direction[1])
            or horizontal_flow_alignment
            or negative_horizontal_normal_alignment
        ):
            block["lines"].append(line)
            block["flow_min"] = min(block["flow_min"], flow0)
            block["flow_max"] = max(block["flow_max"], flow1)
            block["normal_min"] = min(block["normal_min"], normal0)
            block["normal_max"] = max(block["normal_max"], normal1)
            block["source_lines"].update(line["source_lines"])
        else:
            blocks.append({"direction": direction, "flow_min": flow0, "flow_max": flow1, "normal_min": normal0, "normal_max": normal1, "source_lines": set(line["source_lines"]), "lines": [line]})

    normalized = []
    source_word_indices: dict[tuple[Any, Any], int] = {}
    for block_index, block in enumerate(blocks):
        for line_index, line in enumerate(block["lines"]):
            for word_index, word in enumerate(line["items"]):
                if preserve_source_indices:
                    source_key = (word.get("block_index"), word.get("line_index"))
                    word["word_index"] = source_word_indices.get(source_key, 0)
                    source_word_indices[source_key] = word["word_index"] + 1
                else:
                    word["block_index"] = block_index
                    word["line_index"] = line_index
                    word["word_index"] = word_index
                normalized.append(_freeze(word))
    return tuple(normalized)


def snapshot_words_for_clip(
    snapshot: PageSnapshot,
    clip: Any,
    *,
    flags: int | None = None,
) -> tuple[Any, ...]:
    """Return captured words using PyMuPDF's clipped character stream semantics."""

    clip_values = _region(clip)
    explicit_flags = flags is not None
    variant = (
        "preserve_whitespace"
        if flags is not None and flags & fitz.TEXT_PRESERVE_WHITESPACE
        else "flags_zero"
        if flags == 0
        else "default"
    )
    words = snapshot.word_variants.get(variant, snapshot.words)
    geometry = snapshot.geometry
    if (
        clip_values["x0"] <= _safe_finite(geometry.get("x0"))
        and clip_values["y0"] <= _safe_finite(geometry.get("y0"))
        and clip_values["x1"] >= _safe_finite(geometry.get("x1"))
        and clip_values["y1"] >= _safe_finite(geometry.get("y1"))
    ):
        return tuple(words)
    line_directions = {
        _source_position(line, 2): line.get("dir")
        for block in snapshot.text_blocks
        for line in block.get("lines", ())
    }
    if not line_directions or any(
        _unit_direction(direction) is None for direction in line_directions.values()
    ):
        return _legacy_snapshot_words_for_clip(snapshot, clip, flags=flags)
    selected_line_keys = {
        _source_position(character, 2)
        for character in snapshot.characters
        if (box := _bbox(character)) is not None
        and not (
            box[2] <= clip_values["x0"]
            or box[0] >= clip_values["x1"]
            or box[3] <= clip_values["y0"]
            or box[1] >= clip_values["y1"]
        )
    }
    if len(selected_line_keys) <= 1:
        return _legacy_snapshot_words_for_clip(snapshot, clip, flags=flags)
    return _snapshot_words_from_clipped_characters(
        snapshot,
        clip_values,
        words,
        line_directions,
        preserve_source_indices=explicit_flags,
    )


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
    "snapshot_pixmap",
    "snapshot_words_for_clip",
]
