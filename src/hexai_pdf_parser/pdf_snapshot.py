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
) -> Mapping[str, Any] | None:
    word_box = _bbox(word)
    if word_box is None:
        return None
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
        if not (
            char_box[2] <= word_box[0]
            or char_box[0] >= word_box[2]
            or char_box[3] <= word_box[1]
            or char_box[1] >= word_box[3]
        ):
            word_characters.append(character)
    word_characters.sort(key=lambda character: character.get("source_order", 0))
    if not word_characters:
        return None
    character_text = "".join(str(character.get("c", "")) for character in word_characters)
    word_text = str(word.get("text", ""))
    if character_text != word_text:
        return None
    if len(word_characters) != len(word_text):
        return None

    def horizontal_interval(index: int, character: Mapping[str, Any]) -> tuple[float, float]:
        char_box = _bbox(character)
        assert char_box is not None
        origin = character.get("origin")
        origin_x = None
        if isinstance(origin, (tuple, list)) and origin:
            try:
                origin_x = _finite_float(origin[0])
            except (TypeError, ValueError, OverflowError):
                origin_x = None
        x0 = origin_x if origin_x is not None else char_box[0]
        if index + 1 < len(word_characters):
            next_origin = word_characters[index + 1].get("origin")
            if isinstance(next_origin, (tuple, list)) and next_origin:
                try:
                    x1 = _finite_float(next_origin[0])
                except (TypeError, ValueError, OverflowError):
                    x1 = char_box[2]
            else:
                x1 = char_box[2]
        else:
            x1 = char_box[2]
        if x1 <= x0:
            x0, x1 = char_box[0], char_box[2]
        return x0, x1

    def selected_by_clip(index: int, character: Mapping[str, Any]) -> bool:
        char_box = _bbox(character)
        if char_box is None:
            return False
        x0, x1 = horizontal_interval(index, character)
        overlap = max(0.0, min(x1, clip["x1"]) - max(x0, clip["x0"]))
        width = x1 - x0
        if width <= 0.0 or overlap / width < 0.1:
            return False
        return not (
            char_box[3] <= clip["y0"]
            or char_box[1] >= clip["y1"]
        )

    selected = [
        character
        for index, character in enumerate(word_characters)
        if selected_by_clip(index, character)
    ]
    if not selected:
        return None
    copied = _thaw(word)
    copied["text"] = "".join(str(character.get("c", "")) for character in selected)
    boxes = [_bbox(character) for character in selected]
    copied["bbox"] = (
        min(box[0] for box in boxes if box is not None),
        min(box[1] for box in boxes if box is not None),
        max(box[2] for box in boxes if box is not None),
        max(box[3] for box in boxes if box is not None),
    )
    return _freeze(copied)


def snapshot_words_for_clip(
    snapshot: PageSnapshot,
    clip: Any,
    *,
    flags: int = 0,
) -> tuple[Any, ...]:
    """Return captured words intersecting a PyMuPDF-compatible clip rectangle."""

    clip_values = _region(clip)
    variant = (
        "preserve_whitespace"
        if flags & fitz.TEXT_PRESERVE_WHITESPACE
        else "default"
    )
    words = snapshot.word_variants.get(variant, snapshot.words)
    result = []
    for word in words:
        clipped = _clip_word_from_characters(word, snapshot.characters, clip_values)
        if clipped is not None:
            result.append(clipped)
    local_word_indices: dict[tuple[Any, Any], int] = {}
    normalized = []
    for word in result:
        key = (word.get("block_index"), word.get("line_index"))
        word_index = local_word_indices.get(key, 0)
        local_word_indices[key] = word_index + 1
        copied = _thaw(word)
        copied["word_index"] = word_index
        normalized.append(_freeze(copied))
    return tuple(normalized)


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
