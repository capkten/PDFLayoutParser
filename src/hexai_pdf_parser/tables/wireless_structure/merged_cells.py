"""Conservative Chinese inline and multiline cell merging."""

from __future__ import annotations

import re
from typing import Any, Sequence


_VALUE_ONLY = re.compile(r"^[\s$¥£€HKRMB,'’()\-–—.\d%]+$")
_LIST_CONTINUATION = re.compile(r"^[\s\-–—•·]")
_INLINE_MARKER = re.compile(r"^[*#†‡\-–—]+$")
_SINGLE_CJK = re.compile(r"^[\u3400-\u9fff]$")


def _horizontal_overlap(left: Sequence[float], right: Sequence[float]) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0]))


def _native_continuous(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return right["flow_start"] == left["flow_end"] + 1


def _same_slot(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left[key] == right[key] for key in ("row_start", "row_end", "col_start", "col_end"))


def _same_native_inline(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("source_blocks") == right.get("source_blocks")
        and left.get("source_line_start") == right.get("source_line_start")
        and _native_continuous(left, right)
        and abs((left["bbox"][1] + left["bbox"][3]) / 2 - (right["bbox"][1] + right["bbox"][3]) / 2)
        <= max(2.0, min(left["font_size"], right["font_size"]) * 0.35)
        and right["bbox"][0] - left["bbox"][2]
        <= max(4.0, min(left["font_size"], right["font_size"]) * 0.75)
    )


def _same_slot_single_cjk(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        _SINGLE_CJK.fullmatch(left["text"]) is not None
        and _SINGLE_CJK.fullmatch(right["text"]) is not None
        and left.get("source_blocks") == right.get("source_blocks")
        and left.get("source_line_start") == right.get("source_line_start")
        and _native_continuous(left, right)
        and abs((left["bbox"][1] + left["bbox"][3]) / 2 - (right["bbox"][1] + right["bbox"][3]) / 2)
        <= max(2.0, min(left["font_size"], right["font_size"]) * 0.35)
        and right["bbox"][0] - left["bbox"][2]
        <= min(left["font_size"], right["font_size"]) * 2.1
    )


def _is_left_shifted_single_cjk_continuation(
    previous: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    """Recognize a short wrapped tail that starts just left of a long line."""
    font_size = min(previous["font_size"], candidate["font_size"])
    previous_width = previous["bbox"][2] - previous["bbox"][0]
    return (
        _SINGLE_CJK.fullmatch(candidate["text"].strip()) is not None
        and previous_width >= font_size * 4.0
        and candidate["bbox"][0] < previous["bbox"][0]
        and candidate["bbox"][2]
        <= previous["bbox"][0] + max(2.0, font_size * 0.5)
    )


def _merge_pair(left: dict[str, Any], right: dict[str, Any], joiner: str, kind: str) -> dict[str, Any]:
    merged = dict(left)
    merged["text"] = left["text"] + joiner + right["text"]
    merged["bbox"] = [
        min(left["bbox"][0], right["bbox"][0]),
        min(left["bbox"][1], right["bbox"][1]),
        max(left["bbox"][2], right["bbox"][2]),
        max(left["bbox"][3], right["bbox"][3]),
    ]
    merged["flow_start"] = min(left["flow_start"], right["flow_start"])
    merged["flow_end"] = max(left["flow_end"], right["flow_end"])
    merged["span_refs"] = list(left.get("span_refs", [])) + list(right.get("span_refs", []))
    merged["source_blocks"] = sorted(set(left.get("source_blocks", [])) | set(right.get("source_blocks", [])))
    merged["source_line_start"] = min(left.get("source_line_start"), right.get("source_line_start"))
    merged["source_line_end"] = max(left.get("source_line_end"), right.get("source_line_end"))
    merged["merged_from"] = list(left.get("merged_from", [left["candidate_label"]])) + list(right.get("merged_from", [right["candidate_label"]]))
    merged["cell_id"] = "+".join(merged["merged_from"])
    merged["merge_kind"] = kind
    return merged


def merge_same_slot_fragments(
    cells: Sequence[dict[str, Any]], header_cutoff: float | None
) -> list[dict[str, Any]]:
    """Merge only native-inline fragments already mapped to one logical slot."""
    del header_cutoff  # Bilingual header pairing is intentionally out of scope.
    pending = [dict(item) for item in sorted(cells, key=lambda item: item["flow_start"])]
    result: list[dict[str, Any]] = []
    while pending:
        current = pending.pop(0)
        current["merged_from"] = list(current.get("merged_from", [current["candidate_label"]]))
        index = 0
        while index < len(pending):
            candidate = pending[index]
            inline_marker = (
                _native_continuous(current, candidate)
                and (_INLINE_MARKER.fullmatch(current["text"]) or _INLINE_MARKER.fullmatch(candidate["text"]))
            )
            if _same_slot(current, candidate) and (
                _same_native_inline(current, candidate)
                or _same_slot_single_cjk(current, candidate)
                or inline_marker
            ):
                current = _merge_pair(current, candidate, "", "same_slot_native_inline")
                pending.pop(index)
                continue
            index += 1
        result.append(current)
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))


def _can_merge_multiline(
    previous: dict[str, Any], candidate: dict[str, Any], row_columns: dict[int, set[int]]
) -> bool:
    if previous["col_start"] != candidate["col_start"] or previous["col_end"] != candidate["col_end"]:
        return False
    same_or_adjacent_row = candidate["row_start"] in {
        previous["row_end"],
        previous["row_end"] + 1,
    }
    if not same_or_adjacent_row or not _native_continuous(previous, candidate):
        return False
    previous_center_y = (previous["bbox"][1] + previous["bbox"][3]) / 2.0
    candidate_center_y = (candidate["bbox"][1] + candidate["bbox"][3]) / 2.0
    if candidate_center_y <= previous_center_y:
        return False
    if previous["script"] != candidate["script"] and "numeric" not in {previous["script"], candidate["script"]}:
        return False
    if _VALUE_ONLY.fullmatch(previous["text"]) and _VALUE_ONLY.fullmatch(candidate["text"]):
        return False
    if previous["text"].rstrip().endswith((":", "：")) or _LIST_CONTINUATION.match(candidate["text"]):
        return False
    if previous.get("bold") != candidate.get("bold"):
        bold = previous if previous.get("bold") else candidate
        if bold["col_start"] == bold["col_end"] == 1 and row_columns.get(bold["row_start"], {1}) == {1}:
            return False
    minimum_width = min(previous["bbox"][2] - previous["bbox"][0], candidate["bbox"][2] - candidate["bbox"][0])
    if (
        _horizontal_overlap(previous["bbox"], candidate["bbox"]) < minimum_width * 0.45
        and not _is_left_shifted_single_cjk_continuation(previous, candidate)
    ):
        return False
    gap = candidate["bbox"][1] - previous["bbox"][3]
    return gap <= max(6.0, min(previous["font_size"], candidate["font_size"]))


def merge_multiline_cells(
    cells: Sequence[dict[str, Any]], header_cutoff: float | None
) -> list[dict[str, Any]]:
    """Merge only evidence-complete same-column Chinese continuation chains."""
    del header_cutoff  # Header topology is handled by the dedicated topology layer.
    pending = [dict(item) for item in sorted(cells, key=lambda item: item["flow_start"])]
    row_columns: dict[int, set[int]] = {}
    for cell in pending:
        row_columns.setdefault(cell["row_start"], set()).update(
            range(cell["col_start"], cell["col_end"] + 1)
        )
    result: list[dict[str, Any]] = []
    while pending:
        current = pending.pop(0)
        current["merged_from"] = list(current.get("merged_from", [current["candidate_label"]]))
        while pending and _can_merge_multiline(current, pending[0], row_columns):
            candidate = pending.pop(0)
            current = _merge_pair(current, candidate, "\n", "multiline_cell")
            current["row_end"] = candidate["row_end"]
            current["rowspan"] = current["row_end"] - current["row_start"] + 1
        result.append(current)
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))
