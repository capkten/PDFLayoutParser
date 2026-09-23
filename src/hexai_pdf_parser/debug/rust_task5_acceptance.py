"""Stable field-level normalizers for Task 5 Rust wireless acceptance."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
from typing import Any

from hexai_pdf_parser.core.models import BBox, Cell
from hexai_pdf_parser.tables.wireless_table_recovery import WirelessRecovery


_NONDETERMINISTIC_KEYS = {"traceback_id", "generated_at", "duration_seconds"}
_ROUTING_DIAGNOSTIC_KEYS = {
    "status",
    "path",
    "field",
    "classification",
    "error_type",
    "message",
    "schema_version",
}


def _number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 4)
    return value


def _bbox(value: BBox | None) -> list[float] | None:
    if value is None:
        return None
    return [_number(value.x0), _number(value.y0), _number(value.x1), _number(value.y1)]


def _safe_value(value: Any) -> Any:
    if isinstance(value, BBox):
        return _bbox(value)
    if is_dataclass(value):
        return _safe_value(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in _NONDETERMINISTIC_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    return _number(value)


def _normalize_diagnostics(value: Any) -> Any:
    """Keep diagnostics stable while leaving detailed evidence in debug JSON."""

    if isinstance(value, dict):
        if _ROUTING_DIAGNOSTIC_KEYS.intersection(value):
            return {
                key: _safe_value(value[key])
                for key in sorted(_ROUTING_DIAGNOSTIC_KEYS.intersection(value))
                if key not in _NONDETERMINISTIC_KEYS
            }
        result: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key = str(key)
            if key in {"native_spans", "merged_strips", "regions"} and isinstance(item, list):
                result[f"{key}_count"] = len(item)
            elif key == "rust":
                result[key] = _normalize_diagnostics(item)
            elif key in {
                "page_index",
                "source",
                "rejected_reason",
                "excluded_regions",
                "allowed_regions",
                "page_signal",
            }:
                result[key] = _safe_value(item)
        return result
    if isinstance(value, list):
        return [_normalize_diagnostics(item) for item in value]
    return _safe_value(value)


def _cell_record(cell: Cell, owner: str) -> dict[str, Any]:
    return {
        "owner": owner,
        "row": int(cell.row_index),
        "col": int(cell.col_index),
        "rowspan": int(cell.rowspan),
        "colspan": int(cell.colspan),
        "text": cell.text,
        "bbox": _bbox(cell.bbox),
    }


def _occupancy(cells: list[dict[str, Any]], rows: int, cols: int) -> dict[str, Any]:
    owners: dict[tuple[int, int], list[str]] = {}
    out_of_bounds: list[dict[str, Any]] = []
    for cell in cells:
        row_start = cell["row"]
        col_start = cell["col"]
        row_end = row_start + max(cell["rowspan"], 1)
        col_end = col_start + max(cell["colspan"], 1)
        for row in range(row_start, row_end):
            for col in range(col_start, col_end):
                if 0 <= row < rows and 0 <= col < cols:
                    owners.setdefault((row, col), []).append(cell["owner"])
                else:
                    out_of_bounds.append(
                        {"row": row, "col": col, "owner": cell["owner"]}
                    )

    all_slots = {(row, col) for row in range(max(rows, 0)) for col in range(max(cols, 0))}
    duplicate_slots = sorted(
        [[row, col] for (row, col), values in owners.items() if len(values) > 1]
    )
    conflicts = [
        {"row": row, "col": col, "owners": owners[(row, col)]}
        for row, col in (tuple(item) for item in duplicate_slots)
    ]
    covered = set(owners)
    return {
        "covered_slots": len(covered),
        "missing_slots": [[row, col] for row, col in sorted(all_slots - covered)],
        "duplicate_slots": duplicate_slots,
        "conflicts": conflicts,
        "out_of_bounds": out_of_bounds,
        "owners": [
            {"row": row, "col": col, "owners": owners[(row, col)]}
            for row, col in sorted(owners)
        ],
    }


def _normalize_table(table: Any, index: int) -> dict[str, Any]:
    cells = [
        _cell_record(cell, f"table-{index}-cell-{cell_index}")
        for cell_index, cell in enumerate(
            sorted(table.cells, key=lambda item: (item.row_index, item.col_index, item.text))
        )
    ]
    return {
        "index": index,
        "source": table.source,
        "rows": int(table.rows),
        "cols": int(table.cols),
        "bbox": _bbox(table.bbox),
        "cells": cells,
        "empty_slots": [
            [cell["row"], cell["col"]]
            for cell in cells
            if cell["text"] == "" and cell["rowspan"] == 1 and cell["colspan"] == 1
        ],
        "occupancy": _occupancy(cells, int(table.rows), int(table.cols)),
    }


def normalize_recovery(
    recovery: WirelessRecovery,
    page_index: int,
    mode: str,
) -> dict[str, Any]:
    """Convert a page recovery to stable JSON-safe comparison data."""

    return {
        "page_index": int(page_index),
        "mode": mode,
        "table_count": len(recovery.tables),
        "tables": [_normalize_table(table, index) for index, table in enumerate(recovery.tables)],
        "diagnostics": _normalize_diagnostics(recovery.diagnostics),
    }


def normalize_region_result(
    result: tuple[int, int, list[Cell]],
    region: BBox,
    page_index: int,
    mode: str,
) -> dict[str, Any]:
    """Convert a region-level recovery result to stable JSON-safe data."""

    rows, cols, cells = result
    records = [
        _cell_record(cell, f"region-cell-{index}")
        for index, cell in enumerate(
            sorted(cells, key=lambda item: (item.row_index, item.col_index, item.text))
        )
    ]
    return {
        "page_index": int(page_index),
        "mode": mode,
        "region": _bbox(region),
        "rows": int(rows),
        "cols": int(cols),
        "cells": records,
        "empty_slots": [
            [cell["row"], cell["col"]]
            for cell in records
            if cell["text"] == "" and cell["rowspan"] == 1 and cell["colspan"] == 1
        ],
        "occupancy": _occupancy(records, int(rows), int(cols)),
    }


def _append_mismatch(
    result: list[dict[str, Any]],
    entry: str,
    layer: str,
    field: str,
    python_value: Any,
    rust_value: Any,
) -> None:
    result.append(
        {
            "entry": entry,
            "layer": layer,
            "field": field,
            "python_value": _safe_value(python_value),
            "rust_value": _safe_value(rust_value),
        }
    )


def compare_normalized(
    python_value: Any,
    candidate_value: Any,
    *,
    entry: str,
) -> list[dict[str, Any]]:
    """Compare normalized values without reducing differences to root strings."""

    mismatches: list[dict[str, Any]] = []

    def equivalent_scalar(left: Any, right: Any, field_name: str) -> bool:
        """Allow only the bounded numeric noise expected from JSON/Rust geometry."""

        if field_name != "bbox" or not isinstance(left, list) or not isinstance(right, list):
            return left == right
        if len(left) != 4 or len(right) != 4:
            return False
        return all(
            isinstance(left_item, (int, float))
            and isinstance(right_item, (int, float))
            and math.isfinite(float(left_item))
            and math.isfinite(float(right_item))
            and abs(float(left_item) - float(right_item)) <= 0.01
            for left_item, right_item in zip(left, right)
        )

    def walk(left: Any, right: Any, layer: str, field: str) -> None:
        if field == "mode":
            return
        if field == "bbox" and isinstance(left, list) and isinstance(right, list):
            if not equivalent_scalar(left, right, field):
                _append_mismatch(mismatches, entry, layer or field, field, left, right)
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    _append_mismatch(
                        mismatches,
                        entry,
                        layer or str(key),
                        str(key),
                        left.get(key) if key in left else None,
                        right.get(key) if key in right else None,
                    )
                    continue
                next_layer = layer or str(key)
                walk(left[key], right[key], next_layer, str(key))
            return
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                _append_mismatch(mismatches, entry, layer or field, "presence", len(left), len(right))
            for left_item, right_item in zip(left, right):
                walk(left_item, right_item, layer or field, field)
            return
        if not equivalent_scalar(left, right, field):
            _append_mismatch(mismatches, entry, layer or field, field, left, right)

    walk(python_value, candidate_value, "", "root")
    return mismatches
