import os
import math
import traceback
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from . import _pdf_fast

Line4 = Tuple[float, float, float, float]

VALID_MODES = {"python", "shadow", "rust"}
_ROUTING_DIAGNOSTICS: List[Dict[str, Any]] = []


def _normalize_diagnostic_path(path: Any) -> str:
    if isinstance(path, str) and path.strip():
        return path.strip()
    return "unknown"


def get_diagnostics() -> List[Dict[str, Any]]:
    """Return a copy of the current routing diagnostics."""
    return list(_ROUTING_DIAGNOSTICS)


def clear_diagnostics() -> None:
    """Clear collected routing diagnostics."""
    _ROUTING_DIAGNOSTICS.clear()


def get_rust_mode(path: str = "") -> str:
    """Get the active rust execution mode for the given path or globally."""
    mode = None
    if path:
        env_key = f"PDF_RUST_MODE_{path.upper().replace('/', '_').replace('-', '_')}"
        mode = os.environ.get(env_key)
    if not mode:
        default_mode = "rust" if path == "personal-credit" else "python"
        mode = os.environ.get("PDF_RUST_MODE", default_mode)
    mode = mode.strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid PDF_RUST_MODE '{mode}'. Allowed modes are: {sorted(list(VALID_MODES))}"
        )
    return mode


def assert_equivalent(path: str, python_value: Any, rust_value: Any) -> None:
    """Assert that python and rust outputs are equivalent, recording mismatch diagnostic on difference."""
    if python_value != rust_value:
        diag = {
            "schema_version": 1,
            "status": "rust_output_mismatch",
            "path": _normalize_diagnostic_path(path),
            "field": "__root__",
            "python_value": {"str_val": str(python_value)},
            "rust_value": {"str_val": str(rust_value)},
            "classification": "defect",
        }
        _ROUTING_DIAGNOSTICS.append(diag)
        raise AssertionError(f"Output mismatch on path '{path}': Python={python_value!r} != Rust={rust_value!r}")


def run_python_or_rust(mode: str, python_fn, rust_fn, input_dto: Any = None, path: str = ""):
    """Execute Python or Rust according to mode contract."""
    if not isinstance(mode, str):
        raise ValueError(f"Invalid mode '{mode}'. Allowed modes are: {sorted(list(VALID_MODES))}")
    m = mode.strip().lower()
    if m not in VALID_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Allowed modes are: {sorted(list(VALID_MODES))}")
    diagnostic_path = _normalize_diagnostic_path(path)

    if m == "python":
        return python_fn()

    if m == "rust":
        try:
            if input_dto is not None:
                return rust_fn(input_dto)
            return rust_fn()
        except Exception as exc:
            tb_str = traceback.format_exc()
            diag = {
                "schema_version": 1,
                "status": "rust_fallback",
                "path": diagnostic_path,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback_id": tb_str[-200:],
            }
            _ROUTING_DIAGNOSTICS.append(diag)
            return python_fn()

    if m == "shadow":
        py_res = python_fn()
        try:
            if input_dto is not None:
                r_res = rust_fn(input_dto)
            else:
                r_res = rust_fn()
            if py_res != r_res:
                diag = {
                    "schema_version": 1,
                    "status": "rust_output_mismatch",
                    "path": diagnostic_path,
                    "field": "__root__",
                    "python_value": {"str_val": str(py_res)},
                    "rust_value": {"str_val": str(r_res)},
                    "classification": "defect",
                }
                _ROUTING_DIAGNOSTICS.append(diag)
        except Exception as exc:
            tb_str = traceback.format_exc()
            diag = {
                "schema_version": 1,
                "status": "rust_fallback",
                "path": diagnostic_path,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback_id": tb_str[-200:],
            }
            _ROUTING_DIAGNOSTICS.append(diag)
        return py_res


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _require_sequence(value: Any, path: str) -> Union[List[Any], Tuple[Any, ...]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{path} must be a list or tuple")
    return value


def _required_field(record: Mapping[str, Any], name: str, path: str) -> Any:
    if name not in record or record[name] is None:
        raise ValueError(f"{path}.{name} is required")
    return record[name]


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    return value


def _required_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    return value


def _finite_float(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _optional_string(record: Mapping[str, Any], name: str, path: str) -> Optional[str]:
    if name not in record or record[name] is None:
        return None
    return _required_string(record[name], f"{path}.{name}")


def _optional_int(record: Mapping[str, Any], name: str, path: str) -> Optional[int]:
    if name not in record or record[name] is None:
        return None
    return _required_int(record[name], f"{path}.{name}")


def _optional_float(record: Mapping[str, Any], name: str, path: str) -> Optional[float]:
    if name not in record or record[name] is None:
        return None
    return _finite_float(record[name], f"{path}.{name}")


def _snapshot_value(value: Any, path: str = "snapshot") -> Any:
    if isinstance(value, Mapping):
        copied: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} object keys must be strings")
            copied[key] = _snapshot_value(item, f"{path}.{key}")
        return copied
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")


def _snapshot_field(snapshot: Any, name: str) -> Any:
    try:
        return getattr(snapshot, name)
    except AttributeError as exc:
        raise ValueError(f"snapshot is missing required field '{name}'") from exc


def _rect_input(value: Any, path: str) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        values = [_required_field(value, name, path) for name in ("x0", "y0", "x1", "y1")]
    else:
        sequence = _require_sequence(value, path)
        if len(sequence) != 4:
            raise ValueError(f"{path} must contain exactly four coordinates")
        values = list(sequence)
    return {
        "schema_version": 1,
        "x0": _finite_float(values[0], f"{path}.x0"),
        "y0": _finite_float(values[1], f"{path}.y0"),
        "x1": _finite_float(values[2], f"{path}.x1"),
        "y1": _finite_float(values[3], f"{path}.y1"),
    }


def _raw_position(record: Mapping[str, Any], length: int, path: str) -> List[int]:
    value = _required_field(record, "raw_source_position", path)
    sequence = _require_sequence(value, f"{path}.raw_source_position")
    if len(sequence) < length:
        raise ValueError(f"{path}.raw_source_position must contain at least {length} values")
    return [
        _required_int(item, f"{path}.raw_source_position[{index}]")
        for index, item in enumerate(sequence)
    ]


def _character_to_rust_input(character: Any, index: int) -> Dict[str, Any]:
    character = _require_mapping(character, f"span.chars[{index}]")
    raw_source_position = _raw_position(character, 4, f"span.chars[{index}]")
    return {
        "schema_version": 1,
        "text": _required_string(_required_field(character, "c", f"span.chars[{index}]"), f"span.chars[{index}].c"),
        "rect": _rect_input(_required_field(character, "bbox", f"span.chars[{index}]"), f"span.chars[{index}].bbox"),
        "order": _required_int(
            _required_field(character, "source_order", f"span.chars[{index}]"),
            f"span.chars[{index}].source_order",
        ),
        "raw_source_position": raw_source_position,
    }


def _span_to_rust_input(span: Any, index: int) -> Dict[str, Any]:
    path = f"span[{index}]"
    span = _require_mapping(span, path)
    position = _raw_position(span, 3, path)
    characters = _require_sequence(_required_field(span, "chars", path), f"{path}.chars")
    return {
        "schema_version": 1,
        "text": _required_string(_required_field(span, "text", path), f"{path}.text"),
        "rect": _rect_input(_required_field(span, "bbox", path), f"{path}.bbox"),
        "font": _optional_string(span, "font", path),
        "size": _optional_float(span, "size", path),
        "flags": _optional_int(span, "flags", path),
        "order": _required_int(_required_field(span, "source_order", path), f"{path}.source_order"),
        "characters": [
            _character_to_rust_input(character, character_index)
            for character_index, character in enumerate(characters)
        ],
        "source_position": {
            "schema_version": 1,
            "block": position[0],
            "line": position[1],
        },
        "raw_source_position": position,
        "block": position[0],
        "line": position[1],
    }


def _text_line_to_rust_input(line: Any, index: int) -> Dict[str, Any]:
    path = f"line[{index}]"
    line = _require_mapping(line, path)
    position = _raw_position(line, 2, path)
    spans = _require_sequence(_required_field(line, "spans", path), f"{path}.spans")
    return {
        "schema_version": 1,
        "rect": _rect_input(_required_field(line, "bbox", path), f"{path}.bbox"),
        "spans": [
            _span_to_rust_input(span, span_index) for span_index, span in enumerate(spans)
        ],
        "source_position": position,
        "source_order": _required_int(_required_field(line, "source_order", path), f"{path}.source_order"),
    }


def _text_block_to_rust_input(block: Any, index: int) -> Dict[str, Any]:
    path = f"block[{index}]"
    block = _require_mapping(block, path)
    position = _raw_position(block, 1, path)
    if "type" not in block:
        block_type = 0
    elif block["type"] is None:
        block_type = None
    else:
        block_type = _required_int(block["type"], f"{path}.type")
    line_value = (
        _required_field(block, "lines", path)
        if block_type == 0
        else block.get("lines", ())
    )
    lines = _require_sequence(line_value, f"{path}.lines")
    result = {
        "schema_version": 1,
        "rect": _rect_input(_required_field(block, "bbox", path), f"{path}.bbox"),
        "lines": [
            _text_line_to_rust_input(line, line_index) for line_index, line in enumerate(lines)
        ],
        "source_position": position,
        "source_order": _required_int(_required_field(block, "source_order", path), f"{path}.source_order"),
    }
    if block_type is None:
        result["type"] = None
    elif block_type != 0:
        result["type"] = block_type
    return result


def _drawing_line_items(
    items: Union[List[Any], Tuple[Any, ...]], width: Optional[float], path: str
) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        item_path = f"{path}.items[{index}]"
        item_values = _require_sequence(item, item_path)
        if not item_values:
            raise ValueError(f"{item_path} must not be empty")
        kind = _required_string(item_values[0], f"{item_path}[0]")
        rect = None
        if kind == "l":
            if len(item_values) != 3:
                raise ValueError(f"{item_path} line item must contain kind and two points")
            start = _require_sequence(item_values[1], f"{item_path}[1]")
            end = _require_sequence(item_values[2], f"{item_path}[2]")
            if len(start) != 2 or len(end) != 2:
                raise ValueError(f"{item_path} line points must contain two coordinates")
            x0 = _finite_float(start[0], f"{item_path}[1][0]")
            y0 = _finite_float(start[1], f"{item_path}[1][1]")
            x1 = _finite_float(end[0], f"{item_path}[2][0]")
            y1 = _finite_float(end[1], f"{item_path}[2][1]")
            rect = _rect_input((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), f"{item_path}.rect")
        elif kind == "re":
            if len(item_values) < 2:
                raise ValueError(f"{item_path} rectangle item must contain a rectangle")
            rect = _rect_input(item_values[1], f"{item_path}[1]")
        if rect is not None:
            lines.append(
                {
                    "schema_version": 1,
                    "rect": rect,
                    "width": width,
                    "color": None,
                    "source_order": index,
                }
            )
    return lines


def _drawing_to_rust_input(drawing: Any, index: int) -> Dict[str, Any]:
    path = f"drawing[{index}]"
    drawing = _require_mapping(drawing, path)
    raw_source_position = _raw_position(drawing, 1, path)
    items = _require_sequence(_required_field(drawing, "items", path), f"{path}.items")
    width = _optional_float(drawing, "width", path)
    known = {
        "type", "kind", "rect", "color", "fill", "stroke", "clip", "opacity",
        "fill_opacity", "width", "items", "source_order", "schema_version",
        "raw_source_position",
    }
    result: Dict[str, Any] = {
        "schema_version": 1,
        "kind": _required_string(
            _required_field(drawing, "type", path), f"{path}.type"
        ),
        "raw_source_position": raw_source_position,
        "lines": _drawing_line_items(items, width, path),
        "rect": _rect_input(
            drawing.get("rect") or drawing.get("scissor") or (0.0, 0.0, 0.0, 0.0),
            f"{path}.rect",
        ),
        "fill": None if drawing.get("fill") is None else _snapshot_value(drawing["fill"], f"{path}.fill"),
        "stroke": None if drawing.get("stroke") is None else _snapshot_value(drawing["stroke"], f"{path}.stroke"),
        "clip": None if drawing.get("clip") is None else _rect_input(drawing["clip"], f"{path}.clip"),
        "source_order": _required_int(_required_field(drawing, "source_order", path), f"{path}.source_order"),
    }
    for key in ("color", "opacity", "fill_opacity", "width", "items"):
        if key in drawing:
            result[key] = _snapshot_value(drawing[key], f"{path}.{key}")
    extra = {key: _snapshot_value(value, f"{path}.{key}") for key, value in drawing.items() if key not in known}
    if extra:
        result["extra"] = extra
    return result


def _region_to_rust_input(region: Any, source_order: int, allowed: bool) -> Dict[str, Any]:
    region = _require_mapping(region, "region")
    return {
        "schema_version": 1,
        "rect": _rect_input(region, "region"),
        "source_order": _required_int(source_order, "region.source_order"),
        "allowed": bool(allowed),
    }


def _word_to_rust_input(word: Any, index: int) -> Dict[str, Any]:
    path = f"word[{index}]"
    word = _require_mapping(word, path)
    raw_source_position = _raw_position(word, 3, path)
    return {
        "schema_version": 1,
        "text": _required_string(_required_field(word, "text", path), f"{path}.text"),
        "rect": _rect_input(_required_field(word, "bbox", path), f"{path}.bbox"),
        "order": _required_int(_required_field(word, "source_order", path), f"{path}.source_order"),
        "block": _required_int(_required_field(word, "block_index", path), f"{path}.block_index"),
        "line": _required_int(_required_field(word, "line_index", path), f"{path}.line_index"),
        "raw_source_position": raw_source_position,
    }


def page_snapshot_to_rust_input(snapshot: Any) -> Dict[str, Any]:
    """Copy the algorithm-facing, owned DTO from an already captured snapshot."""
    schema_version = _required_int(_snapshot_field(snapshot, "schema_version"), "snapshot.schema_version")
    if schema_version != 1:
        raise ValueError(f"Unsupported schema_version: {schema_version}, expected 1")
    geometry = _require_mapping(_snapshot_field(snapshot, "geometry"), "snapshot.geometry")
    page = {
        "schema_version": 1,
        "width": _finite_float(_required_field(geometry, "width", "snapshot.geometry"), "snapshot.geometry.width"),
        "height": _finite_float(_required_field(geometry, "height", "snapshot.geometry"), "snapshot.geometry.height"),
        "rotation": _required_int(_required_field(geometry, "rotation", "snapshot.geometry"), "snapshot.geometry.rotation"),
    }
    page_y0 = _finite_float(geometry.get("y0", 0.0), "snapshot.geometry.y0")
    blocks = _require_sequence(_snapshot_field(snapshot, "text_blocks"), "snapshot.text_blocks")
    spans = _require_sequence(_snapshot_field(snapshot, "spans"), "snapshot.spans")
    words = _require_sequence(_snapshot_field(snapshot, "words"), "snapshot.words")
    drawings = _require_sequence(_snapshot_field(snapshot, "drawings"), "snapshot.drawings")
    allowed_regions = _require_sequence(_snapshot_field(snapshot, "allowed_regions"), "snapshot.allowed_regions")
    excluded_regions = _require_sequence(_snapshot_field(snapshot, "excluded_regions"), "snapshot.excluded_regions")
    extraction_options = _require_mapping(
        _snapshot_field(snapshot, "extraction_options"), "snapshot.extraction_options"
    )
    result = {
        "schema_version": 1,
        "page_index": _required_int(_snapshot_field(snapshot, "page_index"), "snapshot.page_index"),
        "page": page,
        "text_blocks": [
            _text_block_to_rust_input(block, index) for index, block in enumerate(blocks)
        ],
        "spans": [_span_to_rust_input(span, index) for index, span in enumerate(spans)],
        "words": [_word_to_rust_input(word, index) for index, word in enumerate(words)],
        "drawings": [
            _drawing_to_rust_input(drawing, index)
            for index, drawing in enumerate(drawings)
        ],
        "allowed_regions": [
            _region_to_rust_input(region, index, True)
            for index, region in enumerate(allowed_regions)
        ],
        "excluded_regions": [
            _region_to_rust_input(region, index, False)
            for index, region in enumerate(excluded_regions)
        ],
        "extraction_options": {
            "schema_version": 1,
            "options": _snapshot_value(extraction_options, "snapshot.extraction_options"),
        },
    }
    if page_y0 != 0.0:
        result["page_y0"] = page_y0
    return result


def stage_input_digest(stage_dto: Mapping[str, Any]) -> str:
    if not isinstance(stage_dto, Mapping):
        raise ValueError("stage DTO must be an object")
    return _pdf_fast.stage_input_digest(dict(stage_dto))


def page_snapshot_digest(snapshot_dto: Mapping[str, Any]) -> str:
    """Validate and hash a normalized PageSnapshotDto through Rust."""
    return _pdf_fast.page_snapshot_digest(dict(snapshot_dto))


def collect_native_spans_from_snapshot(
    snapshot: Any,
    excluded_regions: Optional[Sequence[Any]] = None,
    allowed_regions: Optional[Sequence[Any]] = None,
) -> tuple[Any, ...]:
    """Extract and spatially filter native spans directly using the Rust kernel."""
    from hexai_pdf_parser.models import BBox
    from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan

    snapshot_dto = (
        page_snapshot_to_rust_input(snapshot)
        if not isinstance(snapshot, Mapping) or "schema_version" not in snapshot
        else dict(snapshot)
    )

    def _to_rect_list(regions):
        if not regions:
            return None
        rects = []
        for r in regions:
            if isinstance(r, Mapping):
                rects.append(
                    {
                        "schema_version": 1,
                        "x0": float(r["x0"]),
                        "y0": float(r["y0"]),
                        "x1": float(r["x1"]),
                        "y1": float(r["y1"]),
                    }
                )
            elif hasattr(r, "x0"):
                rects.append(
                    {
                        "schema_version": 1,
                        "x0": float(r.x0),
                        "y0": float(r.y0),
                        "x1": float(r.x1),
                        "y1": float(r.y1),
                    }
                )
            else:
                rects.append(
                    {
                        "schema_version": 1,
                        "x0": float(r[0]),
                        "y0": float(r[1]),
                        "x1": float(r[2]),
                        "y1": float(r[3]),
                    }
                )
        return rects

    allowed_dicts = _to_rect_list(allowed_regions)
    excluded_dicts = _to_rect_list(excluded_regions)
    raw_spans = _pdf_fast.collect_native_spans_from_snapshot(
        snapshot_dto, allowed_dicts, excluded_dicts
    )
    converted = []
    for s in raw_spans:
        rect = s["rect"]
        characters = [
            (
                c["text"],
                BBox(c["rect"]["x0"], c["rect"]["y0"], c["rect"]["x1"], c["rect"]["y1"]),
            )
            for c in s.get("characters", [])
        ]
        raw_pos = s.get("raw_source_position")
        source_pos = (
            (int(raw_pos[0]), int(raw_pos[1]), int(raw_pos[2]))
            if raw_pos and len(raw_pos) >= 3
            else (int(s.get("block", 0)), int(s.get("line", 0)), 0)
        )
        converted.append(
            NativeSpan(
                text=s["text"],
                bbox=BBox(rect["x0"], rect["y0"], rect["x1"], rect["y1"]),
                font=s.get("font"),
                size=s.get("size"),
                order=int(s["order"]),
                characters=characters,
                source_position=source_pos,
            )
        )
    return tuple(converted)


def recover_cells_from_snapshot(
    snapshot: Any,
    region: Any,
) -> tuple[int, int, list[Any]]:
    """Recover table structure (rows, cols, cells) directly from snapshot using Rust kernel."""
    from hexai_pdf_parser.models import BBox
    from hexai_pdf_parser.tables.wireless_table_recovery import _rust_cells_to_project

    snapshot_dto = (
        page_snapshot_to_rust_input(snapshot)
        if not isinstance(snapshot, Mapping) or "schema_version" not in snapshot
        else dict(snapshot)
    )

    if isinstance(region, Mapping):
        reg_dict = {
            "schema_version": 1,
            "x0": float(region["x0"]),
            "y0": float(region["y0"]),
            "x1": float(region["x1"]),
            "y1": float(region["y1"]),
        }
    elif hasattr(region, "x0"):
        reg_dict = {
            "schema_version": 1,
            "x0": float(region.x0),
            "y0": float(region.y0),
            "x1": float(region.x1),
            "y1": float(region.y1),
        }
    else:
        reg_dict = {
            "schema_version": 1,
            "x0": float(region[0]),
            "y0": float(region[1]),
            "x1": float(region[2]),
            "y1": float(region[3]),
        }

    raw_output = _pdf_fast.recover_cells_from_snapshot(snapshot_dto, reg_dict)
    if not isinstance(raw_output, Mapping):
        raise TypeError("Rust native recovery output must be a mapping")
    grid_output = raw_output.get("grid", {})
    if not isinstance(grid_output, Mapping):
        raise TypeError("Rust native recovery grid must be a mapping")
    grid = grid_output.get("grid", grid_output)
    if not isinstance(grid, Mapping):
        raise TypeError("Rust native recovery inner grid must be a mapping")
    rows = int(grid.get("rows", 0))
    cols = int(grid.get("cols", 0))
    raw_cells = raw_output.get("cells", grid_output.get("cells", []))
    cells = _rust_cells_to_project(
        raw_cells,
        rows,
        cols,
    )
    if rows <= 0 or cols <= 0 or not cells:
        return 0, 0, []
    return rows, cols, cells


def recover_native_text_input(
    snapshot: Any,
    *,
    input_snapshot_digest: Optional[str] = None,
    region: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return raw spans only from a validated, digest-bearing snapshot input."""
    required_keys = {
        "schema_version",
        "page_index",
        "page",
        "text_blocks",
        "spans",
        "words",
        "drawings",
        "allowed_regions",
        "excluded_regions",
        "extraction_options",
    }
    allowed_keys = required_keys | {"page_y0"}
    if isinstance(snapshot, Mapping):
        owned = _snapshot_value(snapshot, "snapshot_input")
        if "input_snapshot_digest" not in owned:
            raise ValueError("input_snapshot_digest is required")
        input_digest = _required_string(
            owned.pop("input_snapshot_digest"), "input_snapshot_digest"
        )
        if input_snapshot_digest is not None:
            explicit_digest = _required_string(
                input_snapshot_digest, "input_snapshot_digest"
            )
            if explicit_digest != input_digest:
                raise ValueError("input_snapshot_digest values do not match")
        snapshot_dto = owned
        if not required_keys.issubset(snapshot_dto) or not set(snapshot_dto) <= allowed_keys:
            raise ValueError("snapshot input must contain exactly the validated PageSnapshotDto fields")
    else:
        if input_snapshot_digest is None:
            raise ValueError("input_snapshot_digest is required")
        input_digest = _required_string(input_snapshot_digest, "input_snapshot_digest")
        snapshot_dto = page_snapshot_to_rust_input(snapshot)
    if len(input_digest) != 64 or any(char not in "0123456789abcdef" for char in input_digest):
        raise ValueError("input_snapshot_digest must be a lowercase SHA-256 hex digest")
    canonical_digest = page_snapshot_digest(snapshot_dto)
    if input_digest != canonical_digest:
        raise ValueError("input_snapshot_digest does not match the canonical snapshot input")
    selected_region = None if region is None else _snapshot_value(
        _require_mapping(region, "region"), "region"
    )
    return {
        "schema_version": 1,
        "stage": "recover_native_text_input",
        "input_snapshot_digest": input_digest,
        "page_index": snapshot_dto["page_index"],
        "region": selected_region,
        "spans": _snapshot_value(snapshot_dto["spans"]),
    }



def merge_h_lines(lines: List[Line4], merge_group_tol: float) -> List[Line4]:
    owned_lines = [tuple(float(value) for value in line) for line in lines]
    merged_lines = _pdf_fast.merge_h_lines(owned_lines, float(merge_group_tol))
    return [tuple(float(value) for value in line) for line in merged_lines]


def merge_v_lines(
    lines: List[Line4],
    h_lines: Optional[List[Line4]] = None,
    merge_group_tol: float = 0.3,
    line_tolerance: float = 2.3,
) -> List[Line4]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    owned_h = [tuple(float(v) for v in line) for line in (h_lines or [])]
    merged = _pdf_fast.merge_v_lines(
        owned_lines, owned_h, float(merge_group_tol), float(line_tolerance)
    )
    return [tuple(float(v) for v in line) for line in merged]


def merge_region_line_coordinates(
    lines: List[Line4],
    horizontal: bool,
    tolerance: float = 2.3,
) -> List[Line4]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    merged = _pdf_fast.merge_region_line_coordinates(
        owned_lines, bool(horizontal), float(tolerance)
    )
    return [tuple(float(v) for v in line) for line in merged]


def lines_intersect(
    h_line: Line4,
    v_line: Line4,
    tolerance: float = 2.3,
) -> bool:
    return _pdf_fast.lines_intersect(
        tuple(float(v) for v in h_line),
        tuple(float(v) for v in v_line),
        float(tolerance),
    )


def find_table_regions(
    h_lines: List[Line4],
    v_lines: List[Line4],
    tolerance: float = 2.3,
) -> List[Tuple[Dict[str, Any], List[Line4], List[Line4]]]:
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    regions = _pdf_fast.find_table_regions(owned_h, owned_v, float(tolerance))
    res = []
    for bbox, comp_h, comp_v in regions:
        res.append((
            bbox,
            [tuple(float(v) for v in l) for l in comp_h],
            [tuple(float(v) for v in l) for l in comp_v],
        ))
    return res


def snap_coordinates(
    coords: List[float],
    anchor_coords: List[float],
    tol: float = 1.5,
) -> List[float]:
    return _pdf_fast.snap_coordinates(
        [float(c) for c in coords],
        [float(a) for a in anchor_coords],
        float(tol),
    )


def snap_grid_coordinates(
    start: float,
    end: float,
    orthogonal_start: float,
    orthogonal_end: float,
    lines: List[Line4],
    horizontal: bool,
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> List[float]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    return _pdf_fast.snap_grid_coordinates(
        float(start),
        float(end),
        float(orthogonal_start),
        float(orthogonal_end),
        owned_lines,
        bool(horizontal),
        float(tolerance),
        float(merge_group_tol),
    )


def complete_partial_outer_boundaries(
    bbox: Dict[str, Any],
    h_lines: List[Line4],
    v_lines: List[Line4],
    h_ys: List[float],
    v_xs: List[float],
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> Tuple[List[Line4], List[Line4]]:
    if "schema_version" not in bbox:
        bbox = {"schema_version": 1, **bbox}
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    eff_h, eff_v = _pdf_fast.complete_partial_outer_boundaries(
        bbox,
        owned_h,
        owned_v,
        [float(y) for y in h_ys],
        [float(x) for x in v_xs],
        float(tolerance),
        float(merge_group_tol),
    )
    return (
        [tuple(float(v) for v in line) for line in eff_h],
        [tuple(float(v) for v in line) for line in eff_v],
    )


def build_cells_for_region(
    bbox: Dict[str, Any],
    h_lines: List[Line4],
    v_lines: List[Line4],
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> List[Dict[str, Any]]:
    if "schema_version" not in bbox:
        bbox = {"schema_version": 1, **bbox}
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    return _pdf_fast.build_cells_for_region(
        bbox,
        owned_h,
        owned_v,
        float(tolerance),
        float(merge_group_tol),
    )


def trim_ghost_edge_rows(
    cells: List[Dict[str, Any]],
    h_lines: List[Line4],
    tol: float = 2.0,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    return _pdf_fast.trim_ghost_edge_rows(owned_cells, owned_h, float(tol))


def merge_oversegmented_line_columns(
    cells: List[Dict[str, Any]],
    tolerance: float = 2.3,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)
    return _pdf_fast.merge_oversegmented_line_columns(owned_cells, float(tolerance))


def assign_text_to_line_cells(
    cells: List[Dict[str, Any]],
    words: List[Dict[str, Any]],
    chars: Optional[List[Dict[str, Any]]] = None,
    tolerance: float = 2.3,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)

    owned_words = []
    for w in words:
        w_dict = dict(w)
        if "schema_version" not in w_dict:
            w_dict["schema_version"] = 1
        rect = w_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            w_dict["rect"] = {"schema_version": 1, **rect}
        owned_words.append(w_dict)

    owned_chars = []
    if chars:
        for ch in chars:
            ch_dict = dict(ch)
            if "schema_version" not in ch_dict:
                ch_dict["schema_version"] = 1
            rect = ch_dict["rect"]
            if isinstance(rect, dict) and "schema_version" not in rect:
                ch_dict["rect"] = {"schema_version": 1, **rect}
            owned_chars.append(ch_dict)

    return _pdf_fast.assign_text_to_line_cells(
        owned_cells,
        owned_words,
        owned_chars,
        float(tolerance),
    )


def extract_wired_region(input_data: Dict[str, Any]) -> Dict[str, Any]:
    if "schema_version" not in input_data:
        input_data = {"schema_version": 1, **input_data}
    return _pdf_fast.extract_wired_region(input_data)


def recover_personal_credit_tables(input_dto: Mapping[str, Any]) -> Dict[str, Any]:
    """Run the Rust personal-credit table kernel on an owned page snapshot."""
    output = _pdf_fast.recover_personal_credit_tables(dict(input_dto))
    if not isinstance(output, Mapping):
        raise TypeError("Rust personal-credit output must be a mapping")
    if output.get("schema_version") != 1:
        raise ValueError("Rust personal-credit output has invalid schema_version")
    if not isinstance(output.get("tables"), (list, tuple)):
        raise TypeError("Rust personal-credit tables must be a sequence")
    if not isinstance(output.get("diagnostics"), (list, tuple)):
        raise TypeError("Rust personal-credit diagnostics must be a sequence")
    if output["diagnostics"]:
        raise ValueError("Rust personal-credit output contains blocking diagnostics")
    return dict(output)


def _personal_credit_candidate_input(table: Any) -> Dict[str, Any]:
    def bbox_input(bbox: Any) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "x0": _finite_float(bbox.x0, "candidate.bbox.x0"),
            "y0": _finite_float(bbox.y0, "candidate.bbox.y0"),
            "x1": _finite_float(bbox.x1, "candidate.bbox.x1"),
            "y1": _finite_float(bbox.y1, "candidate.bbox.y1"),
        }

    candidate = {
        "schema_version": 1,
        "rect": bbox_input(table.bbox),
        "source": str(table.source or ""),
        "confidence": table.confidence,
        "rows": int(table.rows),
        "cols": int(table.cols),
        "cells": [
            {
                "schema_version": 1,
                "text": str(cell.text),
                "row": int(cell.row_index),
                "col": int(cell.col_index),
                "rect": bbox_input(cell.bbox),
                "rowspan": int(cell.rowspan),
                "colspan": int(cell.colspan),
                "source": None,
            }
            for cell in table.cells
        ],
    }
    if bool(table.h_lines) and bool(table.v_lines):
        candidate["has_wired_lines"] = True
    return candidate


def personal_credit_snapshot_to_rust_input(
    snapshot: Any,
    wired_line_tolerance: float,
    candidate_tables: Sequence[Any],
    *,
    supplement_rust_candidates: bool = False,
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": page_snapshot_to_rust_input(snapshot),
        "wired_line_tolerance": _finite_float(
            wired_line_tolerance, "wired_line_tolerance"
        ),
        "candidate_tables": [
            _personal_credit_candidate_input(table) for table in candidate_tables
        ],
        "supplement_rust_candidates": bool(supplement_rust_candidates),
    }


def personal_credit_tables_to_project(
    raw_output: Mapping[str, Any],
) -> List[Any]:
    from hexai_pdf_parser.core.models import BBox, Cell, Table

    if not isinstance(raw_output, Mapping) or raw_output.get("schema_version") != 1:
        raise ValueError("Rust personal-credit output has invalid schema_version")
    diagnostics = _require_sequence(
        raw_output.get("diagnostics"), "personal_credit.diagnostics"
    )
    if diagnostics:
        raise ValueError("Rust personal-credit output contains blocking diagnostics")
    table_values = _require_sequence(raw_output.get("tables"), "personal_credit.tables")

    def bbox_from_dto(value: Any, path: str) -> BBox:
        record = _require_mapping(value, path)
        return BBox(
            _finite_float(_required_field(record, "x0", path), f"{path}.x0"),
            _finite_float(_required_field(record, "y0", path), f"{path}.y0"),
            _finite_float(_required_field(record, "x1", path), f"{path}.x1"),
            _finite_float(_required_field(record, "y1", path), f"{path}.y1"),
        )

    tables = []
    for table_index, value in enumerate(table_values):
        path = f"personal_credit.tables[{table_index}]"
        record = _require_mapping(value, path)
        if _required_int(_required_field(record, "schema_version", path), f"{path}.schema_version") != 1:
            raise ValueError(f"{path}.schema_version must equal 1")
        rows = _required_int(_required_field(record, "rows", path), f"{path}.rows")
        cols = _required_int(_required_field(record, "cols", path), f"{path}.cols")
        if rows < 1 or cols < 1:
            raise ValueError(f"{path} must have positive rows and cols")
        source = _required_string(_required_field(record, "source", path), f"{path}.source")
        confidence_value = record.get("confidence")
        confidence = (
            None
            if confidence_value is None
            else _finite_float(confidence_value, f"{path}.confidence")
        )
        cell_values = _require_sequence(
            _required_field(record, "cells", path), f"{path}.cells"
        )
        cells = []
        occupied = set()
        for cell_index, cell_value in enumerate(cell_values):
            cell_path = f"{path}.cells[{cell_index}]"
            cell_record = _require_mapping(cell_value, cell_path)
            row = _required_int(_required_field(cell_record, "row", cell_path), f"{cell_path}.row")
            col = _required_int(_required_field(cell_record, "col", cell_path), f"{cell_path}.col")
            rowspan = _required_int(
                _required_field(cell_record, "rowspan", cell_path), f"{cell_path}.rowspan"
            )
            colspan = _required_int(
                _required_field(cell_record, "colspan", cell_path), f"{cell_path}.colspan"
            )
            if row < 0 or col < 0 or rowspan < 1 or colspan < 1:
                raise ValueError(f"{cell_path} has invalid grid coordinates or span")
            if row + rowspan > rows or col + colspan > cols:
                raise ValueError(f"{cell_path} span exceeds the table grid")
            for occupied_row in range(row, row + rowspan):
                for occupied_col in range(col, col + colspan):
                    slot = (occupied_row, occupied_col)
                    if slot in occupied:
                        raise ValueError(f"{cell_path} conflicts at grid slot {slot}")
                    occupied.add(slot)
            cells.append(
                Cell(
                    text=_required_string(
                        _required_field(cell_record, "text", cell_path),
                        f"{cell_path}.text",
                    ),
                    row_index=row,
                    col_index=col,
                    bbox=bbox_from_dto(
                        _required_field(cell_record, "rect", cell_path),
                        f"{cell_path}.rect",
                    ),
                    rowspan=rowspan,
                    colspan=colspan,
                )
            )
        tables.append(
            Table(
                bbox=bbox_from_dto(_required_field(record, "rect", path), f"{path}.rect"),
                rows=rows,
                cols=cols,
                cells=cells,
                confidence=confidence,
                source=source,
            )
        )
    return tables


def roundtrip_dto(dto_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _pdf_fast.roundtrip_dto(str(dto_type), data)


def rect_overlap(
    a: Dict[str, Any],
    b: Dict[str, Any],
    strict: bool = True,
) -> bool:
    a_dict = dict(a)
    if "schema_version" not in a_dict:
        a_dict["schema_version"] = 1
    b_dict = dict(b)
    if "schema_version" not in b_dict:
        b_dict["schema_version"] = 1
    return _pdf_fast.rect_overlap(a_dict, b_dict, bool(strict))


def filter_regions(
    regions: List[Dict[str, Any]],
    excluded: Optional[List[Dict[str, Any]]] = None,
    allowed: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    owned_regions = []
    for r in regions:
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_regions.append(d)
    owned_excluded = []
    for r in (excluded or []):
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_excluded.append(d)
    owned_allowed = []
    for r in (allowed or []):
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_allowed.append(d)
    return _pdf_fast.filter_regions(owned_regions, owned_excluded, owned_allowed)


def cluster_rows(
    items: List[Dict[str, Any]],
    tolerance: float,
) -> List[Dict[str, Any]]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.cluster_rows(owned_items, float(tolerance))


def cluster_columns(
    items: List[Dict[str, Any]],
    tolerance: float,
) -> List[Dict[str, Any]]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.cluster_columns(owned_items, float(tolerance))


def stable_output_order(
    tables: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    owned_tables = []
    for t in tables:
        d = dict(t)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        cells = d.get("cells", [])
        owned_cells = []
        for c in cells:
            cd = dict(c)
            if "schema_version" not in cd:
                cd["schema_version"] = 1
            cr = cd.get("rect")
            if isinstance(cr, dict) and "schema_version" not in cr:
                cd["rect"] = {"schema_version": 1, **cr}
            owned_cells.append(cd)
        d["cells"] = owned_cells
        owned_tables.append(d)
    return _pdf_fast.stable_output_order(owned_tables)


def build_text_runs(
    spans: List[Dict[str, Any]],
    region: Dict[str, Any],
) -> List[Dict[str, Any]]:
    owned_region = dict(region)
    if "schema_version" not in owned_region:
        owned_region["schema_version"] = 1
    owned_spans = []
    for s in spans:
        d = dict(s)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        sp = d.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            d["source_position"] = {"schema_version": 1, **sp}
        chars = d.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        d["characters"] = owned_chars
        owned_spans.append(d)
    return _pdf_fast.build_text_runs(owned_spans, owned_region)


def build_atoms(
    runs: List[Dict[str, Any]],
    region: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    owned_runs = []
    for r in runs:
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_runs.append(d)
    owned_region = None
    if region is not None:
        owned_region = dict(region)
        if "schema_version" not in owned_region:
            owned_region["schema_version"] = 1
    return _pdf_fast.build_atoms(owned_runs, owned_region)


def merge_wrapped_rows(
    atoms: List[Dict[str, Any]],
    tolerance: float = 5.0,
) -> List[Dict[str, Any]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    return _pdf_fast.merge_wrapped_rows(owned_atoms, float(tolerance))


def infer_output_order_mode(
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.infer_output_order_mode(owned_items)


def recover_native_candidates(
    input_dto: Dict[str, Any],
) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    page = dict(d["page"])
    if "schema_version" not in page:
        page["schema_version"] = 1
    d["page"] = page
    region = dict(d["region"])
    if "schema_version" not in region:
        region["schema_version"] = 1
    r_rect = region.get("rect")
    if isinstance(r_rect, dict) and "schema_version" not in r_rect:
        region["rect"] = {"schema_version": 1, **r_rect}
    d["region"] = region
    config = dict(d["config"])
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config
    owned_spans = []
    for s in d.get("spans", []):
        sd = dict(s)
        if "schema_version" not in sd:
            sd["schema_version"] = 1
        rect = sd.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            sd["rect"] = {"schema_version": 1, **rect}
        sp = sd.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            sd["source_position"] = {"schema_version": 1, **sp}
        chars = sd.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        sd["characters"] = owned_chars
        owned_spans.append(sd)
    d["spans"] = owned_spans
    return _pdf_fast.recover_native_candidates(d)


def infer_column_bands(
    atoms: List[Dict[str, Any]],
    region: Dict[str, Any],
) -> List[Dict[str, Any]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    r = dict(region)
    if "schema_version" not in r:
        r["schema_version"] = 1
    return _pdf_fast.infer_column_bands(owned_atoms, r)


def refine_leaf_bands(
    atoms: List[Dict[str, Any]],
    bands: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    owned_bands = []
    for b in bands:
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        owned_bands.append(bd)
    return _pdf_fast.refine_leaf_bands(owned_atoms, owned_bands)


def build_grid(
    atoms: List[Dict[str, Any]],
    bands: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    owned_bands = []
    for b in bands:
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        owned_bands.append(bd)
    return _pdf_fast.build_grid(owned_atoms, owned_bands)


def _ensure_atom_dto(a: Any, idx: int = 0) -> Dict[str, Any]:
    ad = dict(a) if isinstance(a, dict) else (a.__dict__.copy() if hasattr(a, "__dict__") else {})
    if "schema_version" not in ad:
        ad["schema_version"] = 1
    rect = ad.get("rect")
    if isinstance(rect, dict) and "schema_version" not in rect:
        ad["rect"] = {"schema_version": 1, **rect}
    elif isinstance(rect, (list, tuple)) and len(rect) >= 4:
        ad["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif "bbox" in ad:
        b = ad["bbox"]
        if isinstance(b, (list, tuple)) and len(b) >= 4:
            ad["rect"] = {"schema_version": 1, "x0": float(b[0]), "y0": float(b[1]), "x1": float(b[2]), "y1": float(b[3])}
        elif isinstance(b, dict):
            ad["rect"] = {"schema_version": 1, "x0": float(b["x0"]), "y0": float(b["y0"]), "x1": float(b["x1"]), "y1": float(b["y1"])}
        elif hasattr(b, "x0") and hasattr(b, "y0"):
            ad["rect"] = {"schema_version": 1, "x0": float(b.x0), "y0": float(b.y0), "x1": float(b.x1), "y1": float(b.y1)}
    ad.setdefault("run_refs", [idx])
    ad.setdefault("row_hint", None)
    ad.setdefault("col_hint", None)
    ad.setdefault("col_end_hint", ad["col_hint"])
    ad.setdefault("order", idx)
    ad.setdefault("text", "")
    return ad


def build_logical_grid(
    atoms: List[Dict[str, Any]],
    grid: Dict[str, Any],
) -> Dict[str, Any]:
    owned_atoms = [_ensure_atom_dto(a, idx) for idx, a in enumerate(atoms)]
    g = dict(grid)
    if "schema_version" not in g:
        g["schema_version"] = 1
    return _pdf_fast.build_logical_grid(owned_atoms, g)


def recover_native_region(
    input_dto: Dict[str, Any],
) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    region = dict(d["region"])
    if "schema_version" not in region:
        region["schema_version"] = 1
    r_rect = region.get("rect")
    if isinstance(r_rect, dict) and "schema_version" not in r_rect:
        region["rect"] = {"schema_version": 1, **r_rect}
    d["region"] = region
    config = dict(d.get("config", {}))
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config
    owned_atoms = [_ensure_atom_dto(a, idx) for idx, a in enumerate(d.get("atoms", []))]
    d["atoms"] = owned_atoms
    owned_bands = []
    for idx, b in enumerate(d.get("bands", [])):
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        bd.setdefault("source_atoms", [])
        bd.setdefault("order", idx)
        owned_bands.append(bd)
    d["bands"] = owned_bands
    return _pdf_fast.recover_native_region(d)


def table_quality(candidate: Dict[str, Any]) -> float:
    c = dict(candidate)
    if "schema_version" not in c:
        c["schema_version"] = 1
    rect = c.get("rect")
    if isinstance(rect, dict) and "schema_version" not in rect:
        c["rect"] = {"schema_version": 1, **rect}
    owned_cells = []
    for cell in c.get("cells", []):
        cd = dict(cell)
        if "schema_version" not in cd:
            cd["schema_version"] = 1
        c_rect = cd.get("rect")
        if isinstance(c_rect, dict) and "schema_version" not in c_rect:
            cd["rect"] = {"schema_version": 1, **c_rect}
        owned_cells.append(cd)
    c["cells"] = owned_cells
    return float(_pdf_fast.table_quality(c))


def select_candidates(
    candidates: List[Dict[str, Any]],
    excluded: Optional[List[Dict[str, Any]]] = None,
    allowed: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    owned_candidates = []
    for cand in candidates:
        c = dict(cand)
        if "schema_version" not in c:
            c["schema_version"] = 1
        rect = c.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            c["rect"] = {"schema_version": 1, **rect}
        owned_cells = []
        for cell in c.get("cells", []):
            cd = dict(cell)
            if "schema_version" not in cd:
                cd["schema_version"] = 1
            c_rect = cd.get("rect")
            if isinstance(c_rect, dict) and "schema_version" not in c_rect:
                cd["rect"] = {"schema_version": 1, **c_rect}
            owned_cells.append(cd)
        c["cells"] = owned_cells
        owned_candidates.append(c)

    owned_excluded = []
    for ex in (excluded or []):
        d = dict(ex)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_excluded.append(d)

    owned_allowed = []
    for al in (allowed or []):
        d = dict(al)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_allowed.append(d)

    return _pdf_fast.select_candidates(owned_candidates, owned_excluded, owned_allowed)


def recover_wireless_tables(input_dto: Union[Dict[str, Any], Tuple[Any, ...]]) -> Dict[str, Any]:
    if isinstance(input_dto, tuple):
        return recover_wireless_tables_packed(*input_dto)

    try:
        packed = pack_wireless_recovery_input(input_dto)
        return recover_wireless_tables_packed(*packed)
    except Exception:
        pass

    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    page = dict(d["page"])
    if "schema_version" not in page:
        page["schema_version"] = 1
    d["page"] = page

    owned_spans = []
    for s in d.get("spans", []):
        sd = dict(s)
        if "schema_version" not in sd:
            sd["schema_version"] = 1
        rect = sd.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            sd["rect"] = {"schema_version": 1, **rect}
        sp = sd.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            sd["source_position"] = {"schema_version": 1, **sp}
        chars = sd.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        sd["characters"] = owned_chars
        owned_spans.append(sd)
    d["spans"] = owned_spans

    owned_regions = []
    for r in d.get("regions", []):
        rd = dict(r)
        if "schema_version" not in rd:
            rd["schema_version"] = 1
        r_rect = rd.get("rect")
        if isinstance(r_rect, dict) and "schema_version" not in r_rect:
            rd["rect"] = {"schema_version": 1, **r_rect}
        owned_regions.append(rd)
    d["regions"] = owned_regions

    config = dict(d["config"])
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config

    return _pdf_fast.recover_wireless_tables(d)


def collect_native_spans_from_rawdict(
    rawdict: Dict[str, Any],
    page_height: float,
    page_y0: float = 0.0,
    allowed_regions: Optional[Sequence[Any]] = None,
    excluded_regions: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Directly collect native spans from PyMuPDF rawdict via Rust kernel."""
    return _pdf_fast.collect_native_spans_from_rawdict(
        rawdict,
        float(page_height),
        float(page_y0),
        list(allowed_regions) if allowed_regions else None,
        list(excluded_regions) if excluded_regions else None,
    )


def recover_wireless_tables_from_rawdict(
    rawdict: Dict[str, Any],
    page_width: float,
    page_height: float,
    rotation: int = 0,
    page_y0: float = 0.0,
    allowed_regions: Optional[Sequence[Any]] = None,
    excluded_regions: Optional[Sequence[Any]] = None,
    config: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Recover wireless tables directly from PyMuPDF rawdict in Rust, bypassing snapshot overhead."""
    page_info = (float(page_width), float(page_height), int(rotation))
    cfg_tuple = None
    if config is not None:
        cfg_tuple = (
            float(config.get("line_tolerance", 2.0)),
            float(config.get("row_tolerance", 2.0)),
            float(config.get("column_tolerance", 2.0)),
            float(config.get("span_tolerance", 2.0)),
            float(config.get("numeric_tolerance", 2.0)),
        )
    return _pdf_fast.recover_wireless_tables_from_rawdict(
        rawdict,
        page_info,
        float(page_y0),
        list(allowed_regions) if allowed_regions else None,
        list(excluded_regions) if excluded_regions else None,
        cfg_tuple,
    )


def pack_wireless_recovery_input(input_dto: Dict[str, Any]) -> Tuple[Any, ...]:
    """Convert a dictionary input_dto into compact flat arrays for fast FFI."""
    page = input_dto.get("page", {})
    page_info = (
        float(page.get("width", 595.0)),
        float(page.get("height", 842.0)),
        int(page.get("rotation", 0)),
    )

    regions_flat = []
    for r in input_dto.get("regions", []):
        rect = r.get("rect", {})
        regions_flat.append((
            float(rect.get("x0", 0.0)),
            float(rect.get("y0", 0.0)),
            float(rect.get("x1", 0.0)),
            float(rect.get("y1", 0.0)),
            bool(r.get("allowed", True)),
        ))

    config = input_dto.get("config", {})
    config_tuple = (
        float(config.get("line_tolerance", 2.0)),
        float(config.get("row_tolerance", 2.0)),
        float(config.get("column_tolerance", 2.0)),
        float(config.get("span_tolerance", 2.0)),
        float(config.get("numeric_tolerance", 2.0)),
    )

    spans = input_dto.get("spans", [])
    spans_num: List[float] = []
    spans_text: List[str] = []
    spans_font: List[Optional[str]] = []
    chars_num: List[float] = []
    chars_text: List[str] = []
    has_custom_chars = False

    char_idx = 0
    for s in spans:
        rect = s.get("rect", {})
        x0 = float(rect.get("x0", 0.0))
        y0 = float(rect.get("y0", 0.0))
        x1 = float(rect.get("x1", 0.0))
        y1 = float(rect.get("y1", 0.0))
        size = float(s.get("size") or 0.0)
        order = float(s.get("order", 0))
        sp = s.get("source_position", {})
        block = float(s.get("block", sp.get("block", 0)))
        line = float(s.get("line", sp.get("line", 0)))

        text = str(s.get("text", ""))
        spans_text.append(text)
        spans_font.append(s.get("font"))

        chars = s.get("characters", [])
        char_count = len(chars)
        char_start = char_idx

        spans_num.extend([x0, y0, x1, y1, size, order, block, line, float(char_start), float(char_count)])

        text_chars = list(text)
        for i, c in enumerate(chars):
            c_rect = c.get("rect", {})
            cx0 = float(c_rect.get("x0", 0.0))
            cy0 = float(c_rect.get("y0", 0.0))
            cx1 = float(c_rect.get("x1", 0.0))
            cy1 = float(c_rect.get("y1", 0.0))
            c_order = float(c.get("order", i))
            chars_num.extend([cx0, cy0, cx1, cy1, c_order])
            c_text = str(c.get("text", ""))
            chars_text.append(c_text)
            if i >= len(text_chars) or c_text != text_chars[i]:
                has_custom_chars = True
            char_idx += 1

    return (
        page_info,
        regions_flat,
        config_tuple,
        spans_num,
        spans_text,
        spans_font,
        chars_num,
        chars_text if has_custom_chars else None,
    )


def recover_wireless_tables_packed(
    page_info: Tuple[float, float, int],
    regions_flat: List[Tuple[float, float, float, float, bool]],
    config: Tuple[float, float, float, float, float],
    spans_num: List[float],
    spans_text: List[str],
    spans_font: List[Optional[str]],
    chars_num: List[float],
    chars_text: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return _pdf_fast.recover_wireless_tables_packed(
        page_info,
        regions_flat,
        config,
        spans_num,
        spans_text,
        spans_font,
        chars_num,
        chars_text,
    )


def pack_native_spans(
    spans: Sequence[Any],
    page_width: float = 595.0,
    page_height: float = 842.0,
    rotation: int = 0,
    allowed_regions: Optional[Sequence[Any]] = None,
    excluded_regions: Optional[Sequence[Any]] = None,
    config: Optional[Mapping[str, float]] = None,
) -> Tuple[Any, ...]:
    """Directly pack a list of NativeSpan objects into flat FFI buffers without intermediate dicts."""
    page_info = (float(page_width), float(page_height), int(rotation))

    regions_flat = []
    for r in allowed_regions or []:
        regions_flat.append((float(r.x0), float(r.y0), float(r.x1), float(r.y1), True))
    for r in excluded_regions or []:
        regions_flat.append((float(r.x0), float(r.y0), float(r.x1), float(r.y1), False))

    cfg = config or {}
    config_tuple = (
        float(cfg.get("line_tolerance", 2.0)),
        float(cfg.get("row_tolerance", 2.0)),
        float(cfg.get("column_tolerance", 2.0)),
        float(cfg.get("span_tolerance", 2.0)),
        float(cfg.get("numeric_tolerance", 2.0)),
    )

    spans_num: List[float] = []
    spans_text: List[str] = []
    spans_font: List[Optional[str]] = []
    chars_num: List[float] = []
    chars_text: List[str] = []
    has_custom_chars = False

    char_idx = 0
    for s in spans:
        bbox = s.bbox
        x0 = float(bbox.x0)
        y0 = float(bbox.y0)
        x1 = float(bbox.x1)
        y1 = float(bbox.y1)
        size = float(s.size or 0.0)
        order = float(s.order)
        sp = getattr(s, "source_position", None) or (0, 0, 0)
        block = float(sp[0]) if len(sp) > 0 else 0.0
        line = float(sp[1]) if len(sp) > 1 else 0.0

        text = s.text
        spans_text.append(text)
        spans_font.append(s.font)

        chars = s.characters
        char_count = len(chars)
        char_start = char_idx

        spans_num.extend([x0, y0, x1, y1, size, order, block, line, float(char_start), float(char_count)])

        text_chars = list(text)
        for i, (c_str, c_bbox) in enumerate(chars):
            cx0 = float(c_bbox.x0)
            cy0 = float(c_bbox.y0)
            cx1 = float(c_bbox.x1)
            cy1 = float(c_bbox.y1)
            c_order = float(i)
            chars_num.extend([cx0, cy0, cx1, cy1, c_order])
            chars_text.append(c_str)
            if i >= len(text_chars) or c_str != text_chars[i]:
                has_custom_chars = True
            char_idx += 1

    return (
        page_info,
        regions_flat,
        config_tuple,
        spans_num,
        spans_text,
        spans_font,
        chars_num,
        chars_text if has_custom_chars else None,
    )


def _ensure_background_dto(bg: Dict[str, Any], default_order: int = 0) -> Dict[str, Any]:
    b = dict(bg)
    if "schema_version" not in b:
        b["schema_version"] = 1
    rect = b.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        b["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        b["rect"] = {"schema_version": 1, **rect}
    if "source_order" not in b:
        b["source_order"] = default_order
    if "color" not in b:
        b["color"] = None
    if "opacity" not in b:
        b["opacity"] = None
    return b


def _ensure_word_dto(word: Dict[str, Any], default_order: int = 0) -> Dict[str, Any]:
    w = dict(word)
    if "schema_version" not in w:
        w["schema_version"] = 1
    rect = w.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        w["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        w["rect"] = {"schema_version": 1, **rect}
    if "order" not in w:
        w["order"] = default_order
    if "block" not in w:
        w["block"] = None
    if "line" not in w:
        w["line"] = None
    return w


def _ensure_region_dto(reg: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(reg)
    if "schema_version" not in r:
        r["schema_version"] = 1
    rect = r.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        r["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        r["rect"] = {"schema_version": 1, **rect}
    if "source_order" not in r:
        r["source_order"] = 0
    if "allowed" not in r:
        r["allowed"] = True
    return r


def _ensure_config_dto(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = dict(cfg or {})
    if "schema_version" not in c:
        c["schema_version"] = 1
    c.setdefault("line_tolerance", 2.0)
    c.setdefault("row_tolerance", 2.0)
    c.setdefault("column_tolerance", 2.0)
    c.setdefault("span_tolerance", 2.0)
    c.setdefault("numeric_tolerance", 2.0)
    return c


def group_backgrounds(
    backgrounds: List[Dict[str, Any]],
    gap_threshold: float = 30.0,
) -> List[List[Dict[str, Any]]]:
    owned = [_ensure_background_dto(b, idx) for idx, b in enumerate(backgrounds)]
    return _pdf_fast.group_backgrounds(owned, float(gap_threshold))


def detect_zebra_rows(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    page = dict(d.get("page", {}))
    if "schema_version" not in page:
        page["schema_version"] = 1
    d["page"] = page
    d["backgrounds"] = [_ensure_background_dto(b, idx) for idx, b in enumerate(d.get("backgrounds", []))]
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.detect_zebra_rows(d)


def assign_words_to_zebra_rows(
    words: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    row_tol: float = 2.0,
) -> List[Dict[str, Any]]:
    owned_words = [_ensure_word_dto(w, idx) for idx, w in enumerate(words)]
    owned_rows = []
    for idx, r in enumerate(rows):
        rd = dict(r)
        if "schema_version" not in rd:
            rd["schema_version"] = 1
        rect = rd.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            rd["rect"] = {"schema_version": 1, **rect}
        elif isinstance(rect, (list, tuple)) and len(rect) >= 4:
            rd["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
        rd.setdefault("row_index", idx)
        rd.setdefault("source_backgrounds", [])
        rd.setdefault("words", [])
        rd.setdefault("cells", [])
        owned_rows.append(rd)
    return _pdf_fast.assign_words_to_zebra_rows(owned_words, owned_rows, float(row_tol))


def infer_english_columns(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["backgrounds"] = [_ensure_background_dto(b, idx) for idx, b in enumerate(d.get("backgrounds", []))]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.infer_english_columns(d)


def build_english_cells(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["backgrounds"] = [_ensure_background_dto(b, idx) for idx, b in enumerate(d.get("backgrounds", []))]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.build_english_cells(d)


def build_general_wireless_cells(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    owned_atoms = []
    for idx, a in enumerate(d.get("atoms", [])):
        ad = dict(a)
        if "schema_version" not in ad:
            ad["schema_version"] = 1
        rect = ad.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            ad["rect"] = {"schema_version": 1, **rect}
        elif isinstance(rect, (list, tuple)) and len(rect) >= 4:
            ad["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
        ad.setdefault("run_refs", [idx])
        ad.setdefault("row_hint", None)
        ad.setdefault("col_hint", None)
        ad.setdefault("order", idx)
        owned_atoms.append(ad)
    d["atoms"] = owned_atoms
    owned_bands = []
    for idx, b in enumerate(d.get("bands", [])):
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        bd.setdefault("source_atoms", [])
        bd.setdefault("order", idx)
        owned_bands.append(bd)
    d["bands"] = owned_bands
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.build_general_wireless_cells(d)


def build_legacy_text_alignment(input_dto: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["region"] = _ensure_region_dto(d.get("region", {}))
    d["words"] = [_ensure_word_dto(w, idx) for idx, w in enumerate(d.get("words", []))]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.build_legacy_text_alignment(d)


def _ensure_cell_dto(c: Dict[str, Any]) -> Dict[str, Any]:
    cd = dict(c)
    if "schema_version" not in cd:
        cd["schema_version"] = 1
    rect = cd.get("rect")
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        cd["rect"] = {"schema_version": 1, "x0": float(rect[0]), "y0": float(rect[1]), "x1": float(rect[2]), "y1": float(rect[3])}
    elif isinstance(rect, dict) and "schema_version" not in rect:
        cd["rect"] = {"schema_version": 1, **rect}
    cd.setdefault("text", "")
    cd.setdefault("row", 0)
    cd.setdefault("col", 0)
    cd.setdefault("rowspan", 1)
    cd.setdefault("colspan", 1)
    cd.setdefault("source", None)
    return cd


def _ensure_inner_grid_dto(g: Dict[str, Any]) -> Dict[str, Any]:
    gd = dict(g)
    if "schema_version" not in gd:
        gd["schema_version"] = 1
    gd.setdefault("rows", 0)
    gd.setdefault("cols", 0)
    gd.setdefault("row_edges", [])
    gd.setdefault("col_edges", [])
    gd.setdefault("occupancy", [])
    return gd


def infer_header_structure(input_dto: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    grid = dict(d.get("grid", {}))
    if "schema_version" not in grid:
        grid["schema_version"] = 1
    inner_g = _ensure_inner_grid_dto(grid.get("grid", {}))
    grid["grid"] = inner_g
    grid["cells"] = [_ensure_cell_dto(c) for c in grid.get("cells", [])]
    grid.setdefault("empty_slots", [])
    d["grid"] = grid
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.infer_header_structure(d)


def merge_header_spans(input_dto: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    grid = dict(d.get("grid", {}))
    if "schema_version" not in grid:
        grid["schema_version"] = 1
    inner_g = _ensure_inner_grid_dto(grid.get("grid", {}))
    grid["grid"] = inner_g
    grid["cells"] = [_ensure_cell_dto(c) for c in grid.get("cells", [])]
    grid.setdefault("empty_slots", [])
    d["grid"] = grid
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.merge_header_spans(d)


def normalize_financial_header_tokens(input_dto: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    d["cells"] = [_ensure_cell_dto(c) for c in d.get("cells", [])]
    d["config"] = _ensure_config_dto(d.get("config"))
    return _pdf_fast.normalize_financial_header_tokens(d)
