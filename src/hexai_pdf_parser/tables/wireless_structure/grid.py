"""Physical grid construction and occupancy validation."""

from __future__ import annotations

import statistics
from typing import Any, Sequence


def _center_y(item: dict[str, Any]) -> float:
    return (item["bbox"][1] + item["bbox"][3]) / 2.0


def _same_visual_row(
    left: dict[str, Any], right: dict[str, Any], tolerance: float
) -> bool:
    if abs(_center_y(left) - _center_y(right)) <= tolerance:
        return True
    left_height = left["bbox"][3] - left["bbox"][1]
    right_height = right["bbox"][3] - right["bbox"][1]
    overlap = max(
        0.0,
        min(left["bbox"][3], right["bbox"][3])
        - max(left["bbox"][1], right["bbox"][1]),
    )
    return (
        overlap >= min(left_height, right_height) * 0.45
        and abs(left["bbox"][1] - right["bbox"][1])
        <= max(2.4, min(left_height, right_height) * 0.4)
    )


def _cols_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start = left.get("column_start", left.get("column_id"))
    left_end = left.get("column_end", left.get("column_id"))
    right_start = right.get("column_start", right.get("column_id"))
    right_end = right.get("column_end", right.get("column_id"))
    if left_start is None or right_start is None:
        return False
    return not (left_end < right_start or right_end < left_start)


def _y_overlap_ratio(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Return the smaller vertical coverage ratio across both candidate boxes."""
    left_height = left["bbox"][3] - left["bbox"][1]
    right_height = right["bbox"][3] - right["bbox"][1]
    taller_height = max(left_height, right_height)
    if taller_height <= 0:
        return 0.0
    overlap = max(
        0.0,
        min(left["bbox"][3], right["bbox"][3])
        - max(left["bbox"][1], right["bbox"][1]),
    )
    return overlap / taller_height


def _is_left_shifted_cjk_continuation(
    previous: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    """Recognize a left-shifted CJK wrapped tail that may overlap its bbox."""
    if candidate.get("flow_start") != previous.get("flow_end", -1) + 1:
        return False
    if _center_y(candidate) <= _center_y(previous):
        return False
    font_size = min(
        float(previous.get("font_size", 0.0) or 0.0),
        float(candidate.get("font_size", 0.0) or 0.0),
    )
    if font_size <= 0.0:
        return False
    previous_width = previous["bbox"][2] - previous["bbox"][0]
    if previous_width < font_size * 4.0:
        return False
    if candidate["bbox"][0] >= previous["bbox"][0]:
        return False
    text = "".join(str(candidate.get("text", "")).split())
    if not text:
        return False
    if not any(
        0x3400 <= ord(character) <= 0x9FFF
        or 0xF900 <= ord(character) <= 0xFAFF
        for character in text
    ):
        return False
    if text.startswith(("-", "–", "—", "•", "·")):
        return False
    if any(character.isascii() and character.isalnum() for character in text):
        return False
    return candidate["bbox"][2] <= previous["bbox"][0] + max(2.0, font_size * 0.5)


def _can_join_row_group(
    group: Sequence[dict[str, Any]], candidate: dict[str, Any], tolerance: float
) -> bool:
    representative = min(
        group, key=lambda item: abs(_center_y(item) - _center_y(candidate))
    )
    if not _same_visual_row(representative, candidate, tolerance):
        return False

    # 链式传递防御：候选框不得距离组中心均值过远
    group_mean_y = statistics.mean(_center_y(item) for item in group)
    if abs(_center_y(candidate) - group_mean_y) > tolerance * 1.5:
        return False

    # 同列互斥防护：如果与当前行已有元素存在列重叠，但两者的列跨度不一致
    # （例如跨列父表头与子表头：col 5-6 vs col 5），二者绝对不可能属于同一单元格。
    # 即使文本框有松动，也不能把这种上下层结构并入同一行，防止产生致命槽位冲突。
    for existing in group:
        if _cols_overlap(existing, candidate):
            span_differs = (
                existing.get("column_start") != candidate.get("column_start")
                or existing.get("column_end") != candidate.get("column_end")
            )
            if span_differs:
                return False
            # 同一列只有在 bbox 的纵向重叠足够稳定时才视为同一物理行。
            # 这样保留完全重复候选的冲突检测，同时避免上下两行因松动 bbox
            # 和接近的中心点被错误合并。
            if (
                _y_overlap_ratio(existing, candidate) < 0.45
                and not _is_left_shifted_cjk_continuation(existing, candidate)
            ):
                return False
    return True


def _cluster_rows(
    candidates: Sequence[dict[str, Any]], tolerance: float
) -> list[float]:
    groups: list[list[dict[str, Any]]] = []
    for candidate in sorted(candidates, key=_center_y):
        if groups and _can_join_row_group(groups[-1], candidate, tolerance):
            groups[-1].append(candidate)
            continue
        groups.append([candidate])
    return [round(statistics.mean(_center_y(item) for item in group), 2) for group in groups]


def build_grid(
    candidates: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Map candidate cells to physical rows and stable column bands."""
    if not candidates or not bands:
        return [], [], [], ["缺少可用文本条或稳定列带。"]
    heights = [item["bbox"][3] - item["bbox"][1] for item in candidates]
    tolerance = max(3.0, statistics.median(heights) * 0.70)
    row_centers = _cluster_rows(candidates, tolerance)
    rows = [
        {"id": index + 1, "y": value}
        for index, value in enumerate(row_centers)
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
