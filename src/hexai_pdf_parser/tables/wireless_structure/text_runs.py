"""Chinese text-run construction for wireless table recovery."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Sequence

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
    if gap > 0 and (_is_placeholder(previous) or _is_placeholder(candidate)):
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
    native_line = _same_native_line(previous, candidate)
    normal_gap_join = native_line and -0.8 <= gap <= _join_gap_limit(previous, candidate, normal_gap)
    return superscript or normal_gap_join


def _join_text(group: Sequence[dict[str, Any]]) -> str:
    # 中文、数字和符号直接连接；中文财报中的空格由原生文本保留。
    return "".join(item["text"] for item in group)


def build_text_runs(spans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge only same-line native fragments; do not pair bilingual content."""
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
    return sorted(result, key=lambda item: (item["flow_start"], item["flow_end"]))
