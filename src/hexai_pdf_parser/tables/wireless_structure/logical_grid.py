"""Compress physical rows covered by vertical merged cells."""

from __future__ import annotations

from typing import Any, Sequence

from hexai_pdf_parser.core.models import BBox


def _row_components(row_count: int, cells: Sequence[dict[str, Any]]) -> list[list[int]]:
    parent = list(range(row_count + 1))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def join(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for cell in cells:
        for row in range(cell["row_start"] + 1, cell["row_end"] + 1):
            join(cell["row_start"], row)

    groups: list[list[int]] = []
    for row in range(1, row_count + 1):
        if groups and find(groups[-1][0]) == find(row):
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def build_logical_grid(
    physical_rows: Sequence[dict[str, Any]],
    columns: Sequence[dict[str, Any]],
    cells: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return logical rows while retaining physical source row ranges."""
    components = _row_components(len(physical_rows), cells)
    row_mapping = {
        source: index + 1
        for index, group in enumerate(components)
        for source in group
    }
    logical_rows = [
        {"id": index + 1, "source_rows": group}
        for index, group in enumerate(components)
    ]
    logical_cells: list[dict[str, Any]] = []
    for source in cells:
        cell = dict(source)
        cell["source_row_start"] = source["row_start"]
        cell["source_row_end"] = source["row_end"]
        cell["row_start"] = row_mapping[source["row_start"]]
        cell["row_end"] = row_mapping[source["row_end"]]
        cell["rowspan"] = cell["row_end"] - cell["row_start"] + 1
        logical_cells.append(cell)
    return logical_rows, list(columns), logical_cells


def materialize_empty_cells(
    logical_rows: Sequence[dict[str, Any]],
    physical_rows: Sequence[dict[str, Any]],
    columns: Sequence[dict[str, Any]],
    cells: Sequence[dict[str, Any]],
    region_bbox: BBox,
) -> list[dict[str, Any]]:
    """Add one independent cell for every unoccupied logical grid slot."""
    if not logical_rows or not columns:
        return list(cells)

    physical_y = {int(row["id"]): float(row["y"]) for row in physical_rows}
    row_tracks = [
        sum(physical_y[source] for source in row["source_rows"]) / len(row["source_rows"])
        for row in logical_rows
    ]
    row_bounds = [region_bbox.y0]
    row_bounds.extend((left + right) / 2.0 for left, right in zip(row_tracks, row_tracks[1:]))
    row_bounds.append(region_bbox.y1)

    ordered_columns = sorted(columns, key=lambda item: item["id"])
    column_bounds = [region_bbox.x0]
    column_bounds.extend(
        (left["x1"] + right["x0"]) / 2.0
        for left, right in zip(ordered_columns, ordered_columns[1:])
    )
    column_bounds.append(region_bbox.x1)

    occupied: set[tuple[int, int]] = set()
    for cell in cells:
        for row in range(cell["row_start"], cell["row_end"] + 1):
            for column in range(cell["col_start"], cell["col_end"] + 1):
                occupied.add((row, column))

    result = [dict(cell) for cell in cells]
    for row in range(1, len(logical_rows) + 1):
        for column in range(1, len(ordered_columns) + 1):
            if (row, column) in occupied:
                continue
            result.append(
                {
                    "cell_id": f"E{row}_{column}",
                    "text": "",
                    "bbox": [
                        column_bounds[column - 1],
                        row_bounds[row - 1],
                        column_bounds[column],
                        row_bounds[row],
                    ],
                    "row_start": row,
                    "row_end": row,
                    "col_start": column,
                    "col_end": column,
                    "rowspan": 1,
                    "colspan": 1,
                    "merge_kind": "empty_slot",
                }
            )
    return sorted(result, key=lambda item: (item["row_start"], item["col_start"]))
