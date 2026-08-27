"""Physical grid construction and occupancy validation."""

from __future__ import annotations

import statistics
from typing import Any, Sequence


def _center_y(item: dict[str, Any]) -> float:
    return (item["bbox"][1] + item["bbox"][3]) / 2.0


def _cluster(values: Sequence[float], tolerance: float) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(values):
        if groups and value - statistics.mean(groups[-1]) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [round(statistics.mean(group), 2) for group in groups]


def build_grid(
    candidates: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Map candidate cells to physical rows and stable column bands."""
    if not candidates or not bands:
        return [], [], [], ["缺少可用文本条或稳定列带。"]
    heights = [item["bbox"][3] - item["bbox"][1] for item in candidates]
    tolerance = max(3.0, statistics.median(heights) * 0.70)
    rows = [
        {"id": index + 1, "y": value}
        for index, value in enumerate(_cluster([_center_y(item) for item in candidates], tolerance))
    ]
    columns = [
        {"id": band["id"], "x0": band["x0"], "x1": band["x1"]}
        for band in bands
    ]
    cells = []
    for item in candidates:
        row = min(rows, key=lambda value: abs(value["y"] - _center_y(item)))["id"]
        col_start = item.get("column_start", item["column_id"])
        col_end = item.get("column_end", item["column_id"])
        cells.append(
            dict(
                item,
                row_start=row,
                row_end=row,
                col_start=col_start,
                col_end=col_end,
                rowspan=1,
                colspan=col_end - col_start + 1,
            )
        )

    occupied: dict[tuple[int, int], str] = {}
    issues: list[str] = []
    for cell in cells:
        for column in range(cell["col_start"], cell["col_end"] + 1):
            key = (cell["row_start"], column)
            if key in occupied:
                issues.append(
                    "R{0}C{1} conflict: {2}/{3}".format(
                        key[0], key[1], occupied[key], cell["cell_id"]
                    )
                )
            else:
                occupied[key] = cell["cell_id"]
    return rows, columns, cells, issues
