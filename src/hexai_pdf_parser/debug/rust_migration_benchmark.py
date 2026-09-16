"""Deterministic benchmark and differential helpers for Rust migration work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from .benchmark_utils import percentile


def summarize_timings(values: Sequence[float]) -> Dict[str, float]:
    """Return stable timing statistics, including interpolated percentiles."""

    numbers = [float(value) for value in values]
    if not numbers:
        return {
            "count": 0,
            "total": 0.0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }
    return {
        "count": len(numbers),
        "total": float(sum(numbers)),
        "mean": float(sum(numbers) / len(numbers)),
        "min": min(numbers),
        "max": max(numbers),
        "p50": percentile(numbers, 50),
        "p95": percentile(numbers, 95),
        "p99": percentile(numbers, 99),
    }


def _value(value, name):
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name)


def _bbox(value):
    if value is None:
        return None
    if isinstance(value, Mapping):
        return [float(value[key]) for key in ("x0", "y0", "x1", "y1")]
    return [float(getattr(value, key)) for key in ("x0", "y0", "x1", "y1")]


def _canonical_cell(cell):
    return {
        "text": _value(cell, "text"),
        "row_index": _value(cell, "row_index"),
        "col_index": _value(cell, "col_index"),
        "bbox": _bbox(_value(cell, "bbox")),
        "rowspan": _value(cell, "rowspan"),
        "colspan": _value(cell, "colspan"),
    }


def canonicalize_tables(tables: Sequence[object]) -> List[Dict[str, object]]:
    """Convert Table-like objects into stable, JSON-compatible dictionaries."""

    result = []
    for table in tables:
        cells = [_canonical_cell(cell) for cell in (_value(table, "cells") or [])]
        cells.sort(key=lambda cell: (cell["row_index"], cell["col_index"], cell["text"]))
        result.append({
            "bbox": _bbox(_value(table, "bbox")),
            "cols": _value(table, "cols"),
            "confidence": _value(table, "confidence"),
            "rows": _value(table, "rows"),
            "source": _value(table, "source"),
            "cells": cells,
        })
    return result


def compare_canonical_tables(python_tables, rust_tables) -> Dict[str, object]:
    """Compare canonical tables and report each differing field."""

    differences = []

    def compare(left, right, path):
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    differences.append({
                        "path": path + "." + key,
                        "python_value": left.get(key),
                        "rust_value": right.get(key),
                        "classification": "structure_mismatch",
                    })
                else:
                    compare(left[key], right[key], path + "." + key)
        elif isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                item_path = "{}[{}]".format(path, index)
                if index >= len(left) or index >= len(right):
                    differences.append({
                        "path": item_path,
                        "python_value": left[index] if index < len(left) else None,
                        "rust_value": right[index] if index < len(right) else None,
                        "classification": "structure_mismatch",
                    })
                else:
                    compare(left[index], right[index], item_path)
        elif left != right:
            differences.append({
                "path": path,
                "python_value": left,
                "rust_value": right,
                "classification": "text_mismatch" if path.endswith(".text") else "value_mismatch",
            })

    compare(list(python_tables), list(rust_tables), "tables")
    return {"equal": not differences, "differences": differences}


def write_benchmark_run(path: Path, payload: Mapping[str, object]) -> None:
    """Write a sorted, indented JSON benchmark report."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
