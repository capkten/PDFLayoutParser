"""Conservative Chinese inline and multiline cell merging."""

from __future__ import annotations

import re
from typing import Any, Sequence


_VALUE_ONLY = re.compile(r"^[\s$¥£€HKRMB,'’()\-–—.\d%]+$")
_LIST_CONTINUATION = re.compile(r"^[\s\-–—•·]")
_INLINE_MARKER = re.compile(r"^[*#†‡\-–—]+$")
_NUMBERED_MARKER = re.compile(
    r"^(?:\d+[.)、]|[（(]\d+[）)]|[一二三四五六七八九十百]+[.)、])$"
)
_NUMBERED_ITEM_START = re.compile(
    r"^(?:\d+[.)、]|[（(]\d+[）)]|[一二三四五六七八九十百]+[.)、])"
)
_SINGLE_CJK = re.compile(r"^[\u3400-\u9fff\u2460-\u2473\uff00-\uffef\w()（）]$")


def _horizontal_overlap(left: Sequence[float], right: Sequence[float]) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0]))


def _has_substantive_text(text: str) -> bool:
    return any(character.isalnum() for character in text)


def _native_continuous(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return right["flow_start"] == left["flow_end"] + 1


def _same_slot(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left[key] == right[key] for key in ("row_start", "row_end", "col_start", "col_end"))


def _same_native_inline(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("source_blocks") == right.get("source_blocks")
        and _native_continuous(left, right)
        and abs((left["bbox"][1] + left["bbox"][3]) / 2 - (right["bbox"][1] + right["bbox"][3]) / 2)
        <= max(2.0, min(left["font_size"], right["font_size"]) * 0.35)
        and right["bbox"][0] - left["bbox"][2]
        <= max(4.0, min(left["font_size"], right["font_size"]) * 0.75)
    )


def _same_slot_single_cjk(left: dict[str, Any], right: dict[str, Any]) -> bool:
    source_blocks_match = (
        left.get("source_blocks") == right.get("source_blocks")
        if left.get("source_blocks") is not None and right.get("source_blocks") is not None
        else True
    )
    source_lines_close = (
        abs(left.get("source_line_start", 0) - right.get("source_line_start", 0)) <= 1
        if left.get("source_line_start") is not None and right.get("source_line_start") is not None
        else True
    )
    is_toc_title_pair = (left["text"], right["text"]) in {("目", "录"), ("页", "次")}
    max_gap_multiplier = 2.8 if is_toc_title_pair else 2.1
    return (
        _SINGLE_CJK.fullmatch(left["text"]) is not None
        and _SINGLE_CJK.fullmatch(right["text"]) is not None
        and source_blocks_match
        and source_lines_close
        and _native_continuous(left, right)
        and abs((left["bbox"][1] + left["bbox"][3]) / 2 - (right["bbox"][1] + right["bbox"][3]) / 2)
        <= max(2.0, min(left["font_size"], right["font_size"]) * 0.35)
        and right["bbox"][0] - left["bbox"][2]
        <= min(left["font_size"], right["font_size"]) * max_gap_multiplier
    )




def _same_slot_horizontal_prefix(
    left: dict[str, Any], right: dict[str, Any]
) -> bool:
    """Join a numbered prefix with its right-hand text in one visual row."""
    left_text = left["text"].strip()
    right_text = right["text"].strip()
    if (
        _NUMBERED_MARKER.fullmatch(left_text) is None
        or _NUMBERED_MARKER.fullmatch(right_text) is not None
        or _VALUE_ONLY.fullmatch(right_text) is not None
        or not _has_substantive_text(right_text)
        or not left.get("source_position_known", False)
        or not right.get("source_position_known", False)
    ):
        return False
    same_source_line = (
        left.get("source_blocks") == right.get("source_blocks")
        and left.get("source_line_start") == left.get("source_line_end")
        and right.get("source_line_start") == right.get("source_line_end")
        and left.get("source_line_start") == right.get("source_line_start")
    )
    if not same_source_line or not _native_continuous(left, right):
        return False
    vertical_overlap = max(
        0.0,
        min(left["bbox"][3], right["bbox"][3])
        - max(left["bbox"][1], right["bbox"][1]),
    )
    minimum_height = min(
        left["bbox"][3] - left["bbox"][1],
        right["bbox"][3] - right["bbox"][1],
    )
    if vertical_overlap < minimum_height * 0.35:
        return False
    minimum_font_size = min(left["font_size"], right["font_size"])
    gap = right["bbox"][0] - left["bbox"][2]
    return 0.0 <= gap <= max(4.0, minimum_font_size * 2.1)


def _is_left_shifted_cjk_continuation(
    previous: dict[str, Any],
    candidate: dict[str, Any],
    row_columns: dict[int, set[int]],
) -> bool:
    """Recognize a wrapped tail or hanging-indent continuation that starts left of the previous line."""
    font_size = min(previous["font_size"], candidate["font_size"])
    previous_width = previous["bbox"][2] - previous["bbox"][0]
    if previous_width < font_size * 4.0:
        return False
    if candidate["bbox"][0] >= previous["bbox"][0]:
        return False
    candidate_text = candidate["text"].strip()
    if (
        _LIST_CONTINUATION.match(candidate_text)
        or candidate_text.startswith(
            ("1.", "2.", "3.", "4.", "5.", "(1)", "(2)", "(3)", "(4)", "(5)", "①", "②", "③")
        )
        or _VALUE_ONLY.fullmatch(candidate_text)
    ):
        return False
    if (
        _SINGLE_CJK.fullmatch(candidate_text)
        and candidate["bbox"][2] <= previous["bbox"][0] + max(2.0, font_size * 0.5)
    ):
        return True
    is_empty_witness = row_columns.get(candidate["row_start"]) == {candidate["col_start"]}
    if is_empty_witness:
        return True
    return False


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
    merged["source_position_known"] = bool(left.get("source_position_known", False)) and bool(
        right.get("source_position_known", False)
    )
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
            horizontal_prefix = _same_slot_horizontal_prefix(current, candidate)
            if _same_slot(current, candidate) and (
                _same_native_inline(current, candidate)
                or _same_slot_single_cjk(current, candidate)
                or inline_marker
                or horizontal_prefix
            ):
                merge_kind = (
                    "same_slot_horizontal_prefix"
                    if horizontal_prefix
                    else "same_slot_native_inline"
                )
                current = _merge_pair(current, candidate, "", merge_kind)
                pending.pop(index)
                continue
            index += 1
        result.append(current)
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))


def _can_merge_multiline(
    previous: dict[str, Any],
    candidate: dict[str, Any],
    row_columns: dict[int, set[int]],
    output_mode: str,
) -> bool:
    if previous["col_start"] != candidate["col_start"] or previous["col_end"] != candidate["col_end"]:
        return False
    same_or_adjacent_row = candidate["row_start"] in {
        previous["row_end"],
        previous["row_end"] + 1,
    }
    if not same_or_adjacent_row or not _native_continuous(previous, candidate):
        return False
    if _NUMBERED_ITEM_START.match(candidate["text"].strip()) is not None:
        return False
    if output_mode == "columnar":
        previous_blocks = previous.get("source_blocks", [])
        candidate_blocks = candidate.get("source_blocks", [])
        if not (
            previous.get("source_position_known", False)
            and candidate.get("source_position_known", False)
            and len(previous_blocks) == 1
            and previous_blocks == candidate_blocks
            and candidate["source_line_start"] == previous["source_line_end"] + 1
        ):
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
        and not _is_left_shifted_cjk_continuation(previous, candidate, row_columns)
    ):
        return False
    gap = candidate["bbox"][1] - previous["bbox"][3]
    return gap <= max(6.0, min(previous["font_size"], candidate["font_size"]))


def merge_multiline_cells(
    cells: Sequence[dict[str, Any]],
    header_cutoff: float | None,
    *,
    output_mode: str = "row_interleaved",
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
        while pending and _can_merge_multiline(
            current, pending[0], row_columns, output_mode
        ):
            candidate = pending.pop(0)
            current = _merge_pair(current, candidate, "\n", "multiline_cell")
            current["row_end"] = candidate["row_end"]
            current["rowspan"] = current["row_end"] - current["row_start"] + 1
        result.append(current)
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))
