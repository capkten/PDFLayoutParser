"""Deterministic statistics, manifests, and differential helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from .benchmark_utils import summarize_timings_with_percentiles


def summarize_migration_timings(values: Sequence[float]) -> Dict[str, float]:
    return summarize_timings_with_percentiles(values)


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _bbox(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    if isinstance(value, Mapping):
        return [float(value[key]) for key in ("x0", "y0", "x1", "y1")]
    return [float(getattr(value, key)) for key in ("x0", "y0", "x1", "y1")]


def _canonical_cell(cell: Any) -> Dict[str, object]:
    return {
        "text": _value(cell, "text", ""),
        "row_index": _value(cell, "row_index"),
        "col_index": _value(cell, "col_index"),
        "bbox": _bbox(_value(cell, "bbox")),
        "rowspan": _value(cell, "rowspan", 1),
        "colspan": _value(cell, "colspan", 1),
    }


def canonicalize_tables(tables: Sequence[object]) -> List[Dict[str, object]]:
    """Convert Table-like objects without changing table or Cell order."""

    result = []
    for table in tables:
        cells = [_canonical_cell(cell) for cell in (_value(table, "cells", []) or [])]
        item = {
            "bbox": _bbox(_value(table, "bbox")),
            "cols": _value(table, "cols"),
            "confidence": _value(table, "confidence"),
            "rows": _value(table, "rows"),
            "source": _value(table, "source"),
            "cells": cells,
        }
        empty_slots = _value(table, "empty_slots")
        if empty_slots is not None:
            item["empty_slots"] = list(empty_slots)
        result.append(item)
    return result


_KNOWN_DIFFERENCE_KINDS = {
    "missing_key", "extra_key", "list_length", "text", "bbox", "span", "order", "value",
}


def _field_for_path(path: str) -> str:
    if not path or path == "__root__":
        return "__root__"
    if path.endswith("]"):
        return "__list_length__"
    return path.rsplit(".", 1)[-1]


def _difference(path: str, python_value: Any, rust_value: Any, kind: str) -> Dict[str, object]:
    if kind not in _KNOWN_DIFFERENCE_KINDS:
        kind = "value"
    return {
        "path": path,
        "field": _field_for_path(path),
        "python_value": python_value,
        "rust_value": rust_value,
        "difference_kind": kind,
        "classification": "defect",
    }


def _json_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compare_canonical_tables(python_tables: Sequence[object], rust_tables: Sequence[object]) -> Dict[str, object]:
    """Compare ordered canonical structures with explicit difference taxonomy."""

    differences: List[Dict[str, object]] = []

    def compare(left: Any, right: Any, path: str) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left) | set(right), key=str):
                child_path = path + "." + str(key) if path else str(key)
                if key not in left:
                    differences.append(_difference(child_path, None, right[key], "extra_key"))
                elif key not in right:
                    differences.append(_difference(child_path, left[key], None, "missing_key"))
                else:
                    compare(left[key], right[key], child_path)
            return
        if isinstance(left, list) and isinstance(right, list):
            if path.endswith("bbox"):
                if len(left) != len(right):
                    differences.append(_difference(path, left, right, "list_length"))
                elif left != right:
                    differences.append(_difference(path, left, right, "bbox"))
                return
            if len(left) != len(right):
                differences.append(_difference(path, left, right, "list_length"))
                limit = min(len(left), len(right))
            else:
                limit = len(left)
                if len(left) > 1 and sorted(_json_key(item) for item in left) == sorted(_json_key(item) for item in right):
                    if left != right:
                        differences.append(_difference(path, left, right, "order"))
                        return
            for index in range(limit):
                compare(left[index], right[index], "{}[{}]".format(path, index))
            return
        if left != right:
            field = _field_for_path(path)
            kind = "text" if field == "text" else "bbox" if field == "bbox" else "span" if field in ("rowspan", "colspan", "span") else "value"
            differences.append(_difference(path, left, right, kind))

    compare(list(python_tables), list(rust_tables), "tables")
    return {"equal": not differences, "differences": differences}


def write_benchmark_run(path: Path, payload: Mapping[str, object]) -> None:
    """Write sorted, deterministic JSON and reject accidental replacement."""

    path = Path(path)
    if path.exists():
        raise FileExistsError("benchmark output already exists: {}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
