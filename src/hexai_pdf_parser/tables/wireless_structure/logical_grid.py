"""Compress physical rows covered by vertical merged cells."""

from __future__ import annotations

from typing import Any, Sequence


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
        logical_cells.append(cell)
    return logical_rows, list(columns), logical_cells
