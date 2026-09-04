"""Compress physical rows covered by vertical merged cells."""

from __future__ import annotations

from typing import Any, Sequence

from hexai_pdf_parser.core.models import BBox


def _wrapped_leaf_header_span(
    cells: Sequence[dict[str, Any]],
    candidate: dict[str, Any],
    header_cutoff: float | None,
) -> tuple[int, int] | None:
    """Find a wrapped leaf header whose first physical row is continuation-only."""
    if header_cutoff is None:
        return None
    if (
        candidate.get("merge_kind") != "multiline_cell"
        or "\n" not in str(candidate.get("text", ""))
        or int(candidate.get("row_end", 0)) <= int(candidate.get("row_start", 0))
        or int(candidate.get("col_start", 0)) != int(candidate.get("col_end", 0))
        or int(candidate.get("colspan", 1)) != 1
        or not candidate.get("bbox")
    ):
        return None
    center_y = (candidate["bbox"][1] + candidate["bbox"][3]) / 2.0
    if center_y > header_cutoff or candidate["bbox"][3] > header_cutoff:
        return None

    start = int(candidate["row_start"])
    started = [
        cell
        for cell in cells
        if int(cell["row_start"]) == start and str(cell.get("text", "")).strip()
    ]
    if not started or candidate not in started:
        return None
    # 首行启动的所有非空单元格必须全部是单列多行叶表头，不得包含单行独立表头或跨列父表头
    for item in started:
        if (
            item.get("merge_kind") != "multiline_cell"
            or "\n" not in str(item.get("text", ""))
            or int(item.get("row_end", 0)) <= start
            or int(item.get("col_start", 0)) != int(item.get("col_end", 0))
            or int(item.get("colspan", 1)) != 1
            or not item.get("bbox")
            or (item["bbox"][1] + item["bbox"][3]) / 2.0 > header_cutoff
            or item["bbox"][3] > header_cutoff
        ):
            return None

    end = max(int(item["row_end"]) for item in started)
    started_columns = {int(item["col_start"]) for item in started}

    candidate_column = int(candidate["col_start"])
    for cell in cells:
        if cell is candidate or not cell.get("bbox"):
            continue
        rows_overlap = not (
            int(cell["row_end"]) < start or int(cell["row_start"]) > end
        )
        columns_overlap = int(cell["col_start"]) <= candidate_column <= int(
            cell["col_end"]
        )
        if rows_overlap and columns_overlap:
            return None

    sibling_columns_by_row: dict[int, set[int]] = {}
    for cell in cells:
        if (
            cell in started
            or int(cell["row_start"]) < start
            or int(cell["row_end"]) > end
            or int(cell["row_start"]) != int(cell["row_end"])
            or int(cell["col_start"]) in started_columns
            or int(cell.get("colspan", 1)) != 1
            or not cell.get("bbox")
            or (cell["bbox"][1] + cell["bbox"][3]) / 2.0 > header_cutoff
            or not str(cell.get("text", "")).strip()
        ):
            continue
        sibling_columns_by_row.setdefault(int(cell["row_start"]), set()).add(
            int(cell["col_start"])
        )
    if not any(len(columns) >= 2 for columns in sibling_columns_by_row.values()):
        return None
    return start, end


def _grouped_mixed_leaf_header_span(
    cells: Sequence[dict[str, Any]],
    candidate: dict[str, Any],
    header_cutoff: float | None,
) -> tuple[int, int] | None:
    """Find mixed single/wrapped leaves proven by one two-column parent."""
    if header_cutoff is None or (
        candidate.get("merge_kind") != "multiline_cell"
        or "\n" not in str(candidate.get("text", ""))
        or int(candidate.get("row_end", 0)) <= int(candidate.get("row_start", 0))
        or int(candidate.get("col_start", 0)) != int(candidate.get("col_end", 0))
        or int(candidate.get("colspan", 1)) != 1
        or not candidate.get("bbox")
        or candidate["bbox"][3] > header_cutoff
    ):
        return None

    start = int(candidate["row_start"])
    end = int(candidate["row_end"])
    candidate_column = int(candidate["col_start"])
    header = [
        cell
        for cell in cells
        if str(cell.get("text", "")).strip()
        and cell.get("bbox")
        and cell["bbox"][3] <= header_cutoff
    ]
    parents = [
        cell
        for cell in header
        if int(cell["row_end"]) < start
        and int(cell["col_end"]) == int(cell["col_start"]) + 1
        and int(cell.get("colspan", 1)) == 2
        and int(cell["col_start"]) <= candidate_column <= int(cell["col_end"])
    ]
    if len(parents) != 1:
        return None

    parent = parents[0]
    parent_columns = set(range(int(parent["col_start"]), int(parent["col_end"]) + 1))
    overlapping = [
        cell
        for cell in header
        if cell is not parent
        and not (int(cell["row_end"]) < start or int(cell["row_start"]) > end)
    ]
    children = [
        cell
        for cell in overlapping
        if int(cell["col_start"]) in parent_columns
        or int(cell["col_end"]) in parent_columns
    ]
    if (
        len(children) != 2
        or candidate not in children
        or any(
            int(cell["col_start"]) != int(cell["col_end"])
            or not start <= int(cell["row_start"]) <= int(cell["row_end"]) <= end
            for cell in children
        )
        or {int(cell["col_start"]) for cell in children} != parent_columns
    ):
        return None

    outside_columns: set[int] = set()
    for cell in overlapping:
        if cell in children:
            continue
        if int(cell["col_start"]) != int(cell["col_end"]):
            return None
        column = int(cell["col_start"])
        if column in outside_columns:
            return None
        outside_columns.add(column)
    return start, end


def _row_components(
    row_count: int,
    cells: Sequence[dict[str, Any]],
    header_cutoff: float | None = None,
) -> list[list[int]]:
    # A surviving cell start marks a structural row; only continuation-only
    # physical rows may collapse into the preceding logical row.
    row_starts = {int(cell["row_start"]) for cell in cells}
    groups: list[list[int]] = []
    for row in range(1, row_count + 1):
        if groups and row not in row_starts:
            groups[-1].append(row)
        else:
            groups.append([row])
    if not cells:
        return groups

    first_column = min(int(cell["col_start"]) for cell in cells)
    body_prefix_spans = []
    for cell in cells:
        if (
            int(cell["col_start"]) != first_column
            or int(cell["row_end"]) <= int(cell["row_start"])
            or not str(cell.get("text", "")).strip()
        ):
            continue
        center_y = (cell["bbox"][1] + cell["bbox"][3]) / 2.0
        is_body = (
            center_y > header_cutoff
            if header_cutoff is not None
            else int(cell["row_start"]) > 1
        )
        if is_body:
            body_prefix_spans.append(
                (int(cell["row_start"]), int(cell["row_end"]))
            )

    wrapped_header_spans = [
        span
        for cell in cells
        for span in [_wrapped_leaf_header_span(cells, cell, header_cutoff)]
        if span is not None
    ]
    grouped_mixed_header_spans = [
        span
        for cell in cells
        for span in [_grouped_mixed_leaf_header_span(cells, cell, header_cutoff)]
        if span is not None
    ]

    for start, end in sorted(
        body_prefix_spans + wrapped_header_spans + grouped_mixed_header_spans
    ):
        matching = [
            index
            for index, group in enumerate(groups)
            if any(start <= row <= end for row in group)
        ]
        if len(matching) < 2:
            continue
        first, last = matching[0], matching[-1]
        merged = [row for group in groups[first : last + 1] for row in group]
        groups = groups[:first] + [merged] + groups[last + 1 :]
    return groups


def build_logical_grid(
    physical_rows: Sequence[dict[str, Any]],
    columns: Sequence[dict[str, Any]],
    cells: Sequence[dict[str, Any]],
    header_cutoff: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return logical rows while retaining physical source row ranges."""
    components = _row_components(len(physical_rows), cells, header_cutoff)
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


def merge_header_spans(
    cells: Sequence[dict[str, Any]],
    header_cutoff: float | None,
) -> list[dict[str, Any]]:
    """Extend proven group and stub headers through empty header slots."""
    result = [dict(cell) for cell in cells]
    if header_cutoff is None:
        return result

    header = [
        cell
        for cell in result
        if str(cell.get("text", "")).strip()
        and cell.get("bbox")
        and (cell["bbox"][1] + cell["bbox"][3]) / 2.0 <= header_cutoff
    ]
    parents = [
        cell
        for cell in header
        if cell["col_end"] > cell["col_start"]
    ]
    if not parents:
        return result

    proven_groups: list[tuple[dict[str, Any], int]] = []
    for parent in parents:
        parent_columns = set(range(parent["col_start"], parent["col_end"] + 1))
        leaf_row = None
        for row in sorted({cell["row_start"] for cell in header if cell["row_start"] > parent["row_end"]}):
            leaf_columns = {
                cell["col_start"]
                for cell in header
                if cell["row_start"] == row
                and cell["row_start"] == cell["row_end"]
                and cell["col_start"] == cell["col_end"]
                and cell["col_start"] in parent_columns
            }
            if leaf_columns == parent_columns:
                leaf_row = row
                break
        if leaf_row is None:
            continue
        proven_groups.append((parent, leaf_row))
        blocked = any(
            parent["row_end"] < cell["row_start"] < leaf_row
            and cell["col_start"] <= parent["col_end"]
            and cell["col_end"] >= parent["col_start"]
            for cell in header
            if cell is not parent
        )
        if not blocked and leaf_row > parent["row_end"] + 1:
            parent["row_end"] = leaf_row - 1
            parent["rowspan"] = parent["row_end"] - parent["row_start"] + 1

    if not proven_groups:
        return result
    first_header_row = min(parent["row_start"] for parent, _ in proven_groups)
    last_header_row = max(leaf_row for _, leaf_row in proven_groups)
    grouped_columns = {
        column
        for parent, _ in proven_groups
        for column in range(parent["col_start"], parent["col_end"] + 1)
    }
    for stub in header:
        if (
            stub["col_start"] != stub["col_end"]
            or stub["col_start"] in grouped_columns
            or not first_header_row <= stub["row_start"] <= last_header_row
        ):
            continue
        occupants = [
            cell
            for cell in header
            if cell["col_start"] <= stub["col_start"] <= cell["col_end"]
            and first_header_row <= cell["row_start"] <= last_header_row
        ]
        if occupants != [stub]:
            continue
        stub["row_start"] = first_header_row
        stub["row_end"] = last_header_row
        stub["rowspan"] = last_header_row - first_header_row + 1
    return result


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
