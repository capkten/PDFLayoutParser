"""Chinese text-run construction for wireless table recovery."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Sequence

from .columns import assign_column
from .span_chain import _union


_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_NUMERIC = re.compile(r"^\(?[+\-–—−]?\d[\d,]*(?:\.\d+)?%?\)?$")
_SEPARATOR_CHARS = set("-_=—–─━＝□■▪▫")
_PLACEHOLDER_CHARS = set("-—–")


def script_kind(text: str) -> str:
    if _CJK.search(text):
        return "cjk"
    if _LATIN.search(text):
        return "latin"
    if any(char.isdigit() for char in text):
        return "numeric"
    return "symbol"


def _center_y(item: dict[str, Any]) -> float:
    return (item["bbox"][1] + item["bbox"][3]) / 2.0


def _separator_text(item: dict[str, Any]) -> str:
    text = "".join(str(item.get("text", "")).split())
    return text if text and all(char in _SEPARATOR_CHARS for char in text) else ""


def _is_placeholder(item: dict[str, Any]) -> bool:
    text = _separator_text(item)
    return 1 <= len(text) <= 3 and all(char in _PLACEHOLDER_CHARS for char in text)


def _filter_separator_spans(spans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove wide text-rendered separator lines, but keep body dash values."""
    if not spans:
        return []

    rows: list[list[dict[str, Any]]] = []
    for span in sorted(spans, key=lambda item: (_center_y(item), item["bbox"][0])):
        row = next(
            (
                candidate
                for candidate in reversed(rows)
                if abs(_center_y(span) - sum(_center_y(item) for item in candidate) / len(candidate)) <= 2.4
            ),
            None,
        )
        if row is None:
            row = []
            rows.append(row)
        row.append(span)

    filtered: list[dict[str, Any]] = []
    for row in rows:
        kept: list[dict[str, Any]] = []
        index = 0
        ordered = sorted(row, key=lambda item: item["bbox"][0])
        while index < len(ordered):
            span = ordered[index]
            separator = _separator_text(span)
            if len(separator) > 3:
                index += 1
                continue
            if separator:
                group = [span]
                next_index = index + 1
                while next_index < len(ordered):
                    candidate = ordered[next_index]
                    if not _separator_text(candidate) or candidate["bbox"][0] - group[-1]["bbox"][2] > 2.0:
                        break
                    group.append(candidate)
                    next_index += 1
                if len(group) > 1 and sum(len(_separator_text(item)) for item in group) > 3:
                    index = next_index
                    continue
            kept.append(span)
            index += 1
        filtered.extend(kept)
    return filtered


def _same_native_line(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left["source_position"][:2] == right["source_position"][:2]
        and right["source_position"][2] == left["source_position"][2] + 1
    )


def _normal_word_gap(spans: Sequence[dict[str, Any]]) -> float | None:
    gaps: list[float] = []
    ordered = sorted(spans, key=lambda item: item["flow"])
    for left, right in zip(ordered, ordered[1:]):
        if _is_placeholder(left) or _is_placeholder(right):
            continue
        if not _same_native_line(left, right):
            continue
        if abs(_center_y(left) - _center_y(right)) > max(
            1.8, min(left["font_size"], right["font_size"]) * 0.22
        ):
            continue
        gap = right["bbox"][0] - left["bbox"][2]
        if 0 <= gap <= min(left["font_size"], right["font_size"]) * 1.5:
            gaps.append(gap)
    if len(gaps) < 3:
        return None
    counts = Counter(round(gap * 2) / 2 for gap in gaps)
    return max(counts, key=lambda value: (counts[value], -value))


def _join_gap_limit(left: dict[str, Any], right: dict[str, Any], normal_gap: float | None) -> float:
    fallback = max(3.5, min(left["font_size"], right["font_size"]) * 0.8)
    return fallback if normal_gap is None else min(fallback, max(1.5, normal_gap))


def _can_join(group: Sequence[dict[str, Any]], candidate: dict[str, Any], normal_gap: float | None) -> bool:
    previous = group[-1]
    if previous["text"] == "$" or candidate["text"] == "$":
        return False
    if abs(_center_y(previous) - _center_y(candidate)) > max(
        2.4, min(previous["font_size"], candidate["font_size"]) * 0.38
    ):
        return False
    gap = candidate["bbox"][0] - previous["bbox"][2]
    native_line = _same_native_line(previous, candidate)
    inline_punct = native_line and (len(candidate["text"].strip()) == 1 or len(previous["text"].strip()) == 1) and gap <= 1.0
    if gap > 0 and not inline_punct and (_is_placeholder(previous) or _is_placeholder(candidate)):
        return False
    if (
        gap > 0.8
        and _NUMERIC.fullmatch(previous["text"].strip())
        and _NUMERIC.fullmatch(candidate["text"].strip())
    ):
        return False
    superscript = (
        candidate["font_size"] < previous["font_size"] * 0.82
        and previous["bbox"][2] - previous["font_size"] * 0.9
        <= candidate["bbox"][0]
        <= previous["bbox"][2] + previous["font_size"] * 0.45
    )
    if (
        not superscript
        and not inline_punct
        and _CJK.search(previous["text"])
        and (
            _NUMERIC.fullmatch(candidate["text"].strip())
            or _is_placeholder(candidate)
        )
    ):
        return False
    normal_gap_join = native_line and -0.8 <= gap <= _join_gap_limit(previous, candidate, normal_gap)
    spaced_single_cjk = (
        native_line
        and _CJK.fullmatch(previous["text"]) is not None
        and _CJK.fullmatch(candidate["text"]) is not None
        and -0.8 <= gap <= min(previous["font_size"], candidate["font_size"]) * 1.25
    )
    return superscript or normal_gap_join or spaced_single_cjk


def _join_text(group: Sequence[dict[str, Any]]) -> str:
    # 中文、数字和符号直接连接；中文财报中的空格由原生文本保留。
    return "".join(item["text"] for item in group)


def _horizontal_overlap(left: Sequence[float], right: Sequence[float]) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0]))


def _right_witnesses(
    chain: Sequence[dict[str, Any]],
    candidate: dict[str, Any],
    runs: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    y0 = min(chain[0]["bbox"][1], candidate["bbox"][1]) - 2.0
    y1 = max(chain[-1]["bbox"][3], candidate["bbox"][3]) + max(candidate.get("font_size", 10.0), 10.0) * 4.0
    x1 = max(item["bbox"][2] for item in chain + [candidate])
    return [
        item
        for item in runs
        if item not in chain
        and item is not candidate
        and item["flow_start"] > candidate["flow_end"]
        and item["bbox"][0] >= x1 + 8.0
        and min(y1, item["bbox"][3]) > max(y0, item["bbox"][1])
    ]


def _is_wrapped_chain_pair(
    chain: Sequence[dict[str, Any]],
    candidate: dict[str, Any],
    runs: Sequence[dict[str, Any]],
) -> bool:
    left = chain[-1]
    if candidate["flow_start"] != left["flow_end"] + 1:
        return False
    if left.get("bold") != candidate.get("bold"):
        return False
    if abs(left.get("font_size", 10.0) - candidate.get("font_size", 10.0)) > 1.0:
        return False
    if (
        _NUMERIC.fullmatch(left["text"].strip())
        or _NUMERIC.fullmatch(candidate["text"].strip())
        or _is_placeholder(left)
        or _is_placeholder(candidate)
    ):
        return False

    left_center = _center_y(left)
    candidate_center = _center_y(candidate)
    if candidate_center <= left_center or candidate["bbox"][1] < left["bbox"][3]:
        return False
    minimum_width = min(
        left["bbox"][2] - left["bbox"][0],
        candidate["bbox"][2] - candidate["bbox"][0],
    )
    if _horizontal_overlap(left["bbox"], candidate["bbox"]) < minimum_width * 0.45:
        return False
    if candidate["bbox"][1] - left["bbox"][3] > max(
        6.0, min(left["font_size"], candidate["font_size"])
    ):
        return False

    witnesses = _right_witnesses(chain, candidate, runs)
    if not witnesses:
        return False
    return True


def _merge_wrapped_field_runs(
    runs: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted((dict(item) for item in runs), key=lambda item: item["flow_start"])
    result: list[dict[str, Any]] = []
    index = 0
    while index < len(ordered):
        chain = [ordered[index]]
        cursor = index + 1
        while cursor < len(ordered) and _is_wrapped_chain_pair(
            chain, ordered[cursor], ordered
        ):
            chain.append(ordered[cursor])
            cursor += 1
        if len(chain) == 1:
            result.append(ordered[index])
            index += 1
            continue
        merged = dict(chain[0])
        merged.update(
            text="\n".join(item["text"] for item in chain),
            bbox=_union(chain),
            span_refs=[span for item in chain for span in item["span_refs"]],
            flow_start=chain[0]["flow_start"],
            flow_end=chain[-1]["flow_end"],
            char_boxes=[char for item in chain for char in item.get("char_boxes", [])],
            source_blocks=sorted(
                {block for item in chain for block in item["source_blocks"]}
            ),
            source_line_start=min(item["source_line_start"] for item in chain),
            source_line_end=max(item["source_line_end"] for item in chain),
            merge_kind="wrapped_field",
        )
        result.append(merged)
        index = cursor
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))


def build_text_runs(spans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge source-continuous native fragments into complete field atoms."""
    if not spans:
        return []
    spans = _filter_separator_spans(spans)
    if not spans:
        return []
    normal_gap = _normal_word_gap(spans)
    rows: list[list[dict[str, Any]]] = []
    for span in sorted(spans, key=lambda item: (_center_y(item), item["bbox"][0], item["flow"])):
        row = next(
            (
                candidate
                for candidate in reversed(rows)
                if abs(_center_y(span) - sum(_center_y(item) for item in candidate) / len(candidate))
                <= max(2.4, span["font_size"] * 0.38)
            ),
            None,
        )
        if row is None:
            row = []
            rows.append(row)
        row.append(span)

    result: list[dict[str, Any]] = []
    for row in rows:
        groups: list[list[dict[str, Any]]] = []
        for span in sorted(row, key=lambda item: item["bbox"][0]):
            if groups and _can_join(groups[-1], span, normal_gap):
                groups[-1].append(span)
            else:
                groups.append([span])
        for group in groups:
            result.append(
                {
                    "span_refs": [item["span_ref"] for item in group],
                    "flow_start": min(item["flow"] for item in group),
                    "flow_end": max(item["flow"] for item in group),
                    "bbox": _union(group),
                    "text": _join_text(group),
                    "font": group[0]["font"],
                    "font_size": group[0]["font_size"],
                    "bold": group[0]["bold"],
                    "script": script_kind(_join_text(group)),
                    "char_boxes": [char for item in group for char in item.get("char_boxes", [])],
                    "source_blocks": sorted({item["source_position"][0] for item in group}),
                    "source_line_start": min(item["source_position"][1] for item in group),
                    "source_line_end": max(item["source_position"][1] for item in group),
                    "merge_kind": "same_line" if len(group) > 1 else "single",
                    "normal_word_gap": normal_gap,
                }
            )
    return _merge_wrapped_field_runs(result)


def _same_native_line_run(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("source_blocks") == right.get("source_blocks")
        and left.get("source_line_start") == left.get("source_line_end")
        and right.get("source_line_start") == right.get("source_line_end")
        and left.get("source_line_start") == right.get("source_line_start")
        and right["flow_start"] == left["flow_end"] + 1
    )


def _can_join_same_band_native_line(
    previous: dict[str, Any],
    candidate: dict[str, Any],
    previous_band: int | None,
    candidate_band: int | None,
) -> bool:
    if previous_band is None or previous_band != candidate_band:
        return False
    if previous.get("script") != "latin" or candidate.get("script") != "latin":
        return False
    if not _same_native_line_run(previous, candidate):
        return False
    if abs(_center_y(previous) - _center_y(candidate)) > max(
        2.4, min(previous["font_size"], candidate["font_size"]) * 0.38
    ):
        return False
    gap = candidate["bbox"][0] - previous["bbox"][2]
    return -0.8 <= gap <= max(
        30.0, min(previous["font_size"], candidate["font_size"]) * 3.5
    )


def _merge_same_band_native_line_group(
    group: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    merged = dict(group[0])
    merged.update(
        text=" ".join(item["text"].strip() for item in group),
        bbox=_union(group),
        span_refs=[span for item in group for span in item["span_refs"]],
        flow_start=group[0]["flow_start"],
        flow_end=group[-1]["flow_end"],
        char_boxes=[char for item in group for char in item.get("char_boxes", [])],
        source_blocks=sorted(
            {block for item in group for block in item["source_blocks"]}
        ),
        source_line_start=group[0]["source_line_start"],
        source_line_end=group[-1]["source_line_end"],
        merge_kind="same_band_native_line",
    )
    return merged


def merge_same_band_native_line_runs(
    runs: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join wide-spaced Latin fragments only after a coarse band is known."""
    if not runs or not bands:
        return [dict(item) for item in runs]

    ordered = sorted(
        (dict(item) for item in runs),
        key=lambda item: item["flow_start"],
    )
    result: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_band: int | None = None
    for item in ordered:
        item_band = assign_column(item, bands)
        if current and not _can_join_same_band_native_line(
            current[-1], item, current_band, item_band
        ):
            result.append(
                _merge_same_band_native_line_group(current)
                if len(current) > 1
                else current[0]
            )
            current = []
            current_band = None
        if not current:
            current = [item]
            current_band = item_band
        else:
            current.append(item)

    if current:
        result.append(
            _merge_same_band_native_line_group(current)
            if len(current) > 1
            else current[0]
        )
    return result
