# -*- coding: utf-8 -*-
"""Use the lowest header tiers to infer leaf columns and parent colspans."""

from __future__ import annotations

import re
import statistics
from typing import Any, Sequence

from .columns import assign_column, horizontal_overlap, is_sparse_left_section_title
from hexai_pdf_parser.core.models import BBox


_TEMPORAL_LEAF_HEADER = re.compile(
    r"(?:"
    r"(?:0?[1-9]|[12]\d|3[01])\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"|(?:0?[1-9]|1[0-2])\s*月\s*(?:0?[1-9]|[12]\d|3[01])\s*日"
    r"|[〇零一二三四五六七八九]{4}年"
    r")",
    re.IGNORECASE,
)

# 财报表头常把“年度 / 金额单位”放在正文之前的连续几行；这些行即使没有
# 明显留白，也仍然属于表头。该信号只用于补足普通空白分割失败的场景。
_HEADER_UNIT_TOKEN = re.compile(
    r"(?:HK\$|US\$|RMB|HKD|USD|\$[’']?0{3}|千元|百万元|million|%$)",
    re.IGNORECASE,
)

_NOTE_NUMBER = r"(?:\d+|[零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟]+)"
_NOTE_ENGLISH_REFERENCE = r"(?:[a-z]|[ivxlcdm]+)"
_NOTE_REFERENCE = re.compile(
    rf"^\s*(?:"
    rf"\(?note(?:\s*(?:{_NOTE_NUMBER}|{_NOTE_ENGLISH_REFERENCE}|[（(]\s*{_NOTE_ENGLISH_REFERENCE}\s*[）)]))?\)?"
    rf"|\d+\s*[（(]\s*{_NOTE_ENGLISH_REFERENCE}\s*[）)]"
    rf"|[（(]\s*(?:附註|附注|注)\s*(?:{_NOTE_NUMBER})?\s*[）)]"
    rf"|(?:附註|附注)\s*(?:{_NOTE_NUMBER})?"
    rf")\s*$",
    re.IGNORECASE,
)
_CHECKMARK = re.compile(r"^\s*[\u2713\u2714\u2611]\s*$")
_NUMERIC = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?%?$")
_PLACEHOLDER = re.compile(r"^(?:--+|——+|—+|-+|/|\*+|NA|N/A|\.)$", re.IGNORECASE)


def _is_placeholder(item: dict[str, Any]) -> bool:
    return _PLACEHOLDER.fullmatch(str(item.get("text", "")).strip()) is not None


def _is_temporal_leaf_header(atom: dict[str, Any]) -> bool:
    """年份、日期是叶子列标签，不能被“居中”规则扩成父级跨列。"""
    return bool(_TEMPORAL_LEAF_HEADER.fullmatch(str(atom.get("text", "")).strip()))


def _temporal_leaf_column(atom: dict[str, Any], bands: Sequence[dict[str, Any]]) -> int | None:
    """日期文本碰到相邻列边界时，按其中心点归入唯一叶子列。"""
    if not bands:
        return None
    center = (atom["bbox"][0] + atom["bbox"][2]) / 2.0
    containing = [band for band in bands if band["x0"] <= center <= band["x1"]]
    candidates = containing or list(bands)
    band = min(candidates, key=lambda item: abs(center - (item["x0"] + item["x1"]) / 2.0))
    return int(band["id"])


def _center_y(item: dict[str, Any]) -> float:
    return (item["bbox"][1] + item["bbox"][3]) / 2.0


def _levels(items: Sequence[dict[str, Any]]) -> list[float]:
    groups: list[list[float]] = []
    for value in sorted(_center_y(item) for item in items):
        if groups and value - statistics.mean(groups[-1]) <= 2.4:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [statistics.mean(group) for group in groups]


def _header_cutoff(atoms: Sequence[dict[str, Any]]) -> float | None:
    levels = _levels(atoms)
    if len(levels) < 3:
        return None
    # 多级表头不一定和正文之间留有最大的纵向空白。例如“Level 1 / Level 2”
    # 下一行是单位，紧接着便是只有项目列的首行正文。此时若仍只取最大间隔，
    # 首行正文会混入表头，叶子列就无法按较窄的表头拆开。优先识别连续的
    # 多列表头后出现的稀疏正文行；普通表格则仍回退到原有的最大间隔规则。
    level_counts = [
        sum(abs(_center_y(item) - level) < 0.5 for item in atoms)
        for level in levels
    ]
    gaps = [right - left for left, right in zip(levels, levels[1:])]
    median_gap = statistics.median(gaps)
    early_gap_threshold = max(12.0, min(gaps) * 1.65)
    # 检查清单表中重复出现的对号属于正文记录，而不是多级表头。以第一条
    # 对号记录为正文起点，避免长说明文本把表头下界拖到后续正文行。
    checkmark_levels = sorted({
        round(_center_y(item), 3)
        for item in atoms
        if _CHECKMARK.fullmatch(str(item.get("text", ""))) is not None
    })
    if len(checkmark_levels) >= 2:
        first_checkmark = checkmark_levels[0]
        preceding = [level for level in levels if level < first_checkmark - 1.0]
        if preceding:
            return (preceding[-1] + first_checkmark) / 2.0
    # A wrapped first-column label may be emitted as two consecutive Latin
    # levels before numeric fields begin.  When that pair follows a clearly
    # larger gap than the dense header rhythm, it is body evidence even though
    # neither level contains a number.
    latin_body_indices = {
        index
        for index, level in enumerate(levels)
        if any(
            _is_latin_body_atom(item)
            and not _is_structural_header_atom(item)
            for item in atoms
            if abs(_center_y(item) - level) < 0.5
        )
    }
    for index in sorted(latin_body_indices):
        if (
            index >= 2
            and index + 1 in latin_body_indices
            and gaps[index - 1] >= early_gap_threshold
        ):
            return (levels[index - 1] + levels[index]) / 2.0
    # Repeated non-structural numeric rows are strong body evidence.  A wrapped
    # body note can create a later sparse level and a larger gap, so this must be
    # checked before the generic large-gap heuristic.
    numeric_body_levels = []
    numeric_row_counts = {}
    for index, level in enumerate(levels[1:], 1):
        row = [item for item in atoms if abs(_center_y(item) - level) < 0.5]
        num_count = sum(
            1
            for item in row
            if _is_numeric_body_atom(item)
            and not _is_structural_header_atom(item)
            and not _is_temporal_leaf_header(item)
        )
        if num_count > 0:
            numeric_body_levels.append(index)
            numeric_row_counts[index] = num_count
    if len(numeric_body_levels) >= 2 or (
        len(numeric_body_levels) == 1 and numeric_row_counts[numeric_body_levels[0]] >= 2
    ):
        first_body_index = numeric_body_levels[0]
        return (levels[first_body_index - 1] + levels[first_body_index]) / 2.0
    # In a dense, multi-row header the first large gap is the body boundary.
    # Do not use the globally largest gap: bilingual body rows can create later
    # gaps of the same size and hide a parent header's numeric leaf columns.
    # 四层及以上的密集表头常见于“公司 / 日期 / 年份 / 单位”。其后的正文
    # 间隔未必达到相邻表头行间距的两倍；若仍坚持 2.0，会令后续数值叶子
    # 轨迹完全失效，把同一公司下的两个年份压进同一列带。
    for index, gap in enumerate(gaps):
        if index >= 2 and gap >= early_gap_threshold and sum(count >= 2 for count in level_counts[: index + 1]) >= 2:
            return (levels[index] + levels[index + 1]) / 2.0
    # 稀疏正文首行是没有大空白时的补救规则，不能抢在已识别出的首个
    # 表头/正文大间隔之前。否则正文中后段的空值行会被误当作新的表头边界，
    # 进而触发表头专用的跨叶子列推断。
    for index in range(2, len(levels)):
        if level_counts[index] <= 1 and level_counts[index - 1] >= 2:
            prior_levels = level_counts[:index]
            if sum(count >= 2 for count in prior_levels) >= 2:
                return (levels[index - 1] + levels[index]) / 2.0
    index, gap = max(enumerate(gaps), key=lambda item: item[1])
    minimum_gap = max(12.0, min(gaps) * 1.8) if len(levels) == 3 else max(9.0, median_gap * 2.0)
    if gap < minimum_gap:
        # 有底色或紧凑排版的财报表头常没有足够大的留白。若页首存在横向
        # 重复的单位行，以该单位行的最后一层作为表头下界；不能因正文中
        # 偶发货币符号而触发，因此仅接受位于整体上半部的重复单位层。
        top = min(_center_y(item) for item in atoms)
        bottom = max(_center_y(item) for item in atoms)
        upper_limit = top + (bottom - top) * 0.48
        unit_levels = []
        for level in levels:
            unit_count = sum(
                abs(_center_y(item) - level) < 0.5
                and bool(_HEADER_UNIT_TOKEN.search(str(item.get("text", "")).strip()))
                for item in atoms
            )
            if level <= upper_limit and unit_count >= 2:
                unit_levels.append(level)
        if unit_levels:
            return max(unit_levels) + 1.5
        return None
    return (levels[index] + levels[index + 1]) / 2.0


def infer_header_cutoff(atoms: Sequence[dict[str, Any]]) -> float | None:
    """Public compatibility name for the branch's header cutoff helper."""
    return _header_cutoff(atoms)


def _compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    overlap = horizontal_overlap(left, right)
    narrow = min(left["bbox"][2] - left["bbox"][0], right["bbox"][2] - right["bbox"][0])
    return overlap >= max(2.0, narrow * 0.25)


def _components(items: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    components: list[list[dict[str, Any]]] = []
    for atom in sorted(items, key=lambda item: item["bbox"][0]):
        matches = [group for group in components if any(_compatible(atom, member) for member in group)]
        if not matches:
            components.append([atom])
            continue
        merged = [atom]
        for group in matches:
            merged.extend(group)
            components.remove(group)
        components.append(merged)
    return components


def _header_intersects(atom: dict[str, Any], band: dict[str, Any]) -> bool:
    overlap = horizontal_overlap(atom, {"bbox": [band["x0"], 0.0, band["x1"], 1.0]})
    if overlap > 0:
        return True
    return min(abs(atom["bbox"][2] - band["x0"]), abs(atom["bbox"][0] - band["x1"])) <= 1.0


def _meaningful_header_band_overlap(atom: dict[str, Any], band: dict[str, Any]) -> bool:
    """Ignore a wide header's tiny touch on the neighbouring leaf band.

    Header text may slightly cross a column boundary because of glyph bearings or
    centre alignment.  A few points of overlap are not enough evidence for a
    colspan: the text must occupy a material part of both the text run and the
    candidate leaf band.  True parent headers still overlap each child band by a
    substantial width and remain colspans.
    """
    overlap = horizontal_overlap(atom, {"bbox": [band["x0"], 0.0, band["x1"], 1.0]})
    if overlap <= 0:
        return False
    text_width = atom["bbox"][2] - atom["bbox"][0]
    band_width = band["x1"] - band["x0"]
    # ``4pt`` was still too permissive for compact financial-table headers:
    # a unit such as ``RMB'000`` or a note marker can graze its neighbour by
    # four to five points without being a parent header.  Require a visibly
    # material overlap.  Wide real parent headers still clear this threshold
    # on every covered leaf band.
    return overlap >= max(5.5, min(text_width, band_width) * 0.20)


def _is_bare_year_parent_header(atom: dict[str, Any]) -> bool:
    """Return whether a compact four-digit year may be a parent header.

    Bare years commonly sit above two child leaves such as ``Sales`` and
    ``Purchases``.  They need the original intersection rule, unlike generic
    digit-bearing text (currency units, notes and values).
    """
    return bool(re.fullmatch(r"(?:19|20)\d{2}", str(atom.get("text", "")).strip()))


def _is_structural_header_atom(atom: dict[str, Any]) -> bool:
    """Years and unit labels describe hierarchy, rather than a child column name."""
    text = str(atom.get("text", "")).strip()
    if _is_bare_year_parent_header(atom):
        return True
    if text.endswith("%") and text not in {"%", "(%)", "（%）"}:
        return False
    return bool(_HEADER_UNIT_TOKEN.search(text))


def _is_note_reference_atom(atom: dict[str, Any]) -> bool:
    """附注/引用是窄列的真实内容，不能被主表头列带规则改写。"""
    return bool(_NOTE_REFERENCE.match(str(atom.get("text", ""))))


def _is_numeric_body_atom(item: dict[str, Any]) -> bool:
    """金额、百分比和年份等数值对象可作为叶子数值列的稳定锚点。"""
    return any(char.isdigit() for char in item["text"])


def _is_latin_body_atom(item: dict[str, Any]) -> bool:
    text = str(item.get("text", ""))
    return bool(re.search(r"[A-Za-z]", text)) and not bool(
        re.search(r"[\u3400-\u9fff]", text)
    )


def _split_by_numeric_body_alignment(
    atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]], cutoff: float | None
) -> list[dict[str, Any]]:
    """用正文的重复数值 x 轨迹拆开被父表头桥接的叶子列。"""
    if cutoff is None:
        return [dict(band) for band in bands]
    refined: list[dict[str, Any]] = []
    for band in bands:
        members = [
            item for item in atoms
            if _center_y(item) > cutoff
            and _is_numeric_body_atom(item)
            and item["bbox"][0] >= band["x0"] - 1.0
            and item["bbox"][2] <= band["x1"] + 1.0
        ]
        children = []
        for group in _components(members):
            y_support = len(_levels(group))
            if y_support >= 2:
                children.append({
                    "x0": min(item["bbox"][0] for item in group),
                    "x1": max(item["bbox"][2] for item in group),
                    "support": len(group),
                    "y_support": y_support,
                })
        if len(children) >= 2:
            children.sort(key=lambda item: item["x0"])
            for child in children:
                child["kind"] = "numeric_leaf"
                child["parent_x0"] = band["x0"]
                child["parent_x1"] = band["x1"]
                child["parent_leaf_count"] = len(children)
            refined.extend(children)
        else:
            refined.append(dict(band))
    refined.sort(key=lambda item: item["x0"])
    for index, band in enumerate(refined, 1):
        band["id"] = index
    return refined


def _remove_empty_overlapping_leaf_bands(
    atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]], cutoff: float | None
) -> list[dict[str, Any]]:
    """删除多级表头细化时产生的空窄重叠带。

    有些父表头同时被年份、单位和正文数值轨迹切分，可能产生一个夹在两个
    实际叶子列之间的很窄区间。若正文没有任何对象以它为中心，这不是独立
    列，而是两套切分证据重叠留下的伪列；保留它会让后续行列编号错位。
    """
    if cutoff is None or len(bands) < 3:
        return [dict(band) for band in bands]

    ordered = [dict(band) for band in sorted(bands, key=lambda item: item["x0"])]
    kept: list[dict[str, Any]] = []
    for index, band in enumerate(ordered):
        if index == 0 or index == len(ordered) - 1:
            kept.append(band)
            continue
        left, right = ordered[index - 1], ordered[index + 1]
        width = band["x1"] - band["x0"]
        neighbor_width = min(left["x1"] - left["x0"], right["x1"] - right["x0"])
        overlaps_neighbor = band["x0"] < left["x1"] or band["x1"] > right["x0"]
        body_anchor = any(
            _center_y(atom) > cutoff
            and band["x0"] <= (atom["bbox"][0] + atom["bbox"][2]) / 2.0 <= band["x1"]
            for atom in atoms
        )
        if width < neighbor_width * 0.55 and overlaps_neighbor and not body_anchor:
            continue
        kept.append(band)
    for index, band in enumerate(kept, 1):
        band["id"] = index
    return kept


def _split_by_lowest_header_children(
    header: Sequence[dict[str, Any]],
    band: dict[str, Any],
    atoms: Sequence[dict[str, Any]] | None = None,
    cutoff: float | None = None,
) -> list[dict[str, Any]]:
    """Use sibling labels on one lowest header row as leaf-column evidence.

    A parent header can be followed by just one row of children (for example
    ``Directly`` / ``Indirectly``).  Such a row is enough to prove two leaves;
    requiring the children themselves to occupy two y-levels loses this common
    financial-statement layout.
    """
    for level in reversed(_levels(header)):
        row = [
            item for item in header
            if abs(_center_y(item) - level) <= max(1.5, item.get("font_size", 10.0) * 0.15)
            and _meaningful_header_band_overlap(item, band)
        ]
        groups = _components(row)
        if len(groups) < 2:
            continue

        centers = [
            (min(item["bbox"][0] for item in group) + max(item["bbox"][2] for item in group)) / 2.0
            for group in groups
        ]
        if any(right - left < 6.0 for left, right in zip(centers, centers[1:])):
            continue

        if atoms is not None and cutoff is not None:
            body_atoms = [
                item for item in atoms
                if _center_y(item) > cutoff
                and item["bbox"][0] >= band["x0"] - 2.0
                and item["bbox"][2] <= band["x1"] + 2.0
            ]
            has_crossing = False
            for index in range(len(groups) - 1):
                split_x = (centers[index] + centers[index + 1]) / 2.0
                for body_atom in body_atoms:
                    if (
                        body_atom["bbox"][0] < split_x - 3.0
                        and body_atom["bbox"][2] > split_x + 3.0
                    ):
                        has_crossing = True
                        break
                if has_crossing:
                    break
            if has_crossing:
                continue

        children: list[dict[str, Any]] = []
        for index, group in enumerate(groups):
            left = band["x0"] if index == 0 else (centers[index - 1] + centers[index]) / 2.0
            right = band["x1"] if index == len(groups) - 1 else (centers[index] + centers[index + 1]) / 2.0
            children.append({
                "x0": left,
                "x1": right,
                "support": len(group),
                "y_support": 1,
                "kind": "header_leaf",
                "parent_x0": band["x0"],
                "parent_x1": band["x1"],
                "parent_leaf_count": len(groups),
                "leaf_header_y": level,
            })
        return children
    return []


def refine_leaf_bands(atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None]:
    """Split a parent band only when its lowest two header rows prove multiple children."""
    cutoff = _header_cutoff(atoms)
    if cutoff is None:
        return [dict(band) for band in bands], None
    header = [item for item in atoms if _center_y(item) <= cutoff]
    # 附注行属于叶子列内容而非叶子列定义；否则同一附注被 PDF 拆成几段会反过来改变列带。
    header_without_notes = [item for item in header if not _is_note_reference_atom(item)]
    levels = _levels(header_without_notes)[-2:]
    leaf_atoms = [
        item
        for item in header_without_notes
        if any(
            abs(_center_y(item) - level) <= max(1.5, item.get("font_size", 10.0) * 0.15)
            for level in levels
        )
    ]
    refined: list[dict[str, Any]] = []
    for band in bands:
        members = [item for item in leaf_atoms if horizontal_overlap(item, {"bbox": [band["x0"], 0.0, band["x1"], 1.0]}) > 0]
        children = []
        for group in _components(members):
            support = len(_levels(group))
            if support >= 2:
                children.append({"x0": min(item["bbox"][0] for item in group), "x1": max(item["bbox"][2] for item in group), "support": len(group), "y_support": support})
        if len(children) >= 2:
            refined.extend(sorted(children, key=lambda item: item["x0"]))
            continue
        # Some multi-level headers expose their leaf labels on a single row.
        # Split those leaves before falling back to repeated numeric body values.
        header_children = _split_by_lowest_header_children(header, band, atoms=atoms, cutoff=cutoff)
        refined.extend(header_children if len(header_children) >= 2 else [dict(band)])
    refined.sort(key=lambda item: item["x0"])
    for index, band in enumerate(refined, 1):
        band["id"] = index
    refined = _split_by_numeric_body_alignment(atoms, refined, cutoff)
    refined = _remove_empty_overlapping_leaf_bands(atoms, refined, cutoff)
    refined = _coalesce_right_aligned_sibling_leaves(atoms, refined, cutoff)
    refined = _coalesce_pure_header_and_body_leaf_bands(atoms, refined, cutoff)
    for index, band in enumerate(refined, 1):
        band["id"] = index
    return refined, cutoff


def _coalesce_pure_header_and_body_leaf_bands(
    atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]], cutoff: float | None
) -> list[dict[str, Any]]:
    """将有实质水平重叠且互补的表头/正文片段合并为单一物理列。"""
    if cutoff is None or len(bands) < 2:
        return [dict(band) for band in bands]
    merged: list[dict[str, Any]] = []
    i = 0
    while i < len(bands):
        curr = dict(bands[i])
        if i + 1 < len(bands):
            nxt = dict(bands[i + 1])
            gap = nxt["x0"] - curr["x1"]
            overlap = min(curr["x1"], nxt["x1"]) - max(curr["x0"], nxt["x0"])
            narrow_width = min(
                curr["x1"] - curr["x0"],
                nxt["x1"] - nxt["x0"],
            )
            if gap <= 3.5:
                curr_atoms = [
                    a for a in atoms
                    if curr["x0"] - 1.0 <= (a["bbox"][0] + a["bbox"][2]) / 2.0 <= curr["x1"] + 1.0
                ]
                nxt_atoms = [
                    a for a in atoms
                    if nxt["x0"] - 1.0 <= (a["bbox"][0] + a["bbox"][2]) / 2.0 <= nxt["x1"] + 1.0
                ]
                curr_head = any(_center_y(a) <= cutoff for a in curr_atoms)
                curr_body = any(_center_y(a) > cutoff for a in curr_atoms)
                nxt_head = any(_center_y(a) <= cutoff for a in nxt_atoms)
                nxt_body = any(_center_y(a) > cutoff for a in nxt_atoms)
                complementary = (curr_head and not curr_body and not nxt_head and nxt_body) or (
                    not curr_head and curr_body and nxt_head and not nxt_body
                )
                if complementary:
                    body_band = curr if curr_body else nxt
                    header_band = nxt if curr_body else curr
                    body_atoms = [
                        a for a in (curr_atoms if curr_body else nxt_atoms)
                        if _center_y(a) > cutoff
                    ]
                    body_width = body_band["x1"] - body_band["x0"]
                    header_width = header_band["x1"] - header_band["x0"]
                    substantial_overlap = overlap >= max(1.0, narrow_width * 0.25)
                    terminal_placeholder_track = (
                        (i == 0 or i + 1 == len(bands) - 1)
                        and len({_center_y(a) for a in body_atoms}) >= 3
                        and all(_is_placeholder(a) for a in body_atoms)
                        and body_width <= header_width * 0.5
                        and gap <= max(1.0, body_width * 0.25)
                    )
                if complementary and (substantial_overlap or terminal_placeholder_track):
                    combined = {
                        **curr,
                        "x0": min(curr["x0"], nxt["x0"]),
                        "x1": max(curr["x1"], nxt["x1"]),
                        "support": curr.get("support", 1) + nxt.get("support", 1),
                        "y_support": curr.get("y_support", 1) + nxt.get("y_support", 1),
                        "kind": curr.get("kind") or nxt.get("kind"),
                    }
                    merged.append(combined)
                    i += 2
                    continue
        merged.append(curr)
        i += 1
    for index, band in enumerate(merged, 1):
        band["id"] = index
    return merged


def _coalesce_right_aligned_sibling_leaves(
    atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]], cutoff: float
) -> list[dict[str, Any]]:
    """同一父表头内，右边界一致的稀疏数值轨道只保留一个叶子列。"""
    siblings: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for band in bands:
        if band.get("kind") != "header_leaf":
            continue
        key = (band.get("parent_x0"), band.get("parent_x1"))
        if None not in key:
            siblings.setdefault(key, []).append(band)

    replacements: dict[int, dict[str, Any]] = {}
    removed: set[int] = set()
    for (parent_x0, parent_x1), group in siblings.items():
        if len(group) < 2:
            continue
        values = [
            atom for atom in atoms
            if _center_y(atom) > cutoff
            and re.search(r"\d", str(atom.get("text", "")))
            and atom["bbox"][0] >= parent_x0 - 1.0
            and atom["bbox"][2] <= parent_x1 + 1.0
        ]
        if len({_center_y(atom) for atom in values}) < 2:
            continue
        right_edges = [atom["bbox"][2] for atom in values]
        if max(right_edges) - min(right_edges) > 2.0:
            continue
        first_leaf = min(group, key=lambda band: band["x0"])
        non_first_leaves = [b for b in group if b is not first_leaf]
        has_non_first_data = any(
            _center_y(atom) > cutoff
            and str(atom.get("text", "")).strip()
            and any(
                b["x0"] - 1.0 <= (atom["bbox"][0] + atom["bbox"][2]) / 2.0 <= b["x1"] + 1.0
                for b in non_first_leaves
            )
            for atom in atoms
        )
        if has_non_first_data:
            continue
        first = first_leaf
        replacements[id(first)] = {
            **first,
            "x0": parent_x0,
            "x1": parent_x1,
            "kind": "right_aligned_leaf",
            "support": len(values),
            "y_support": len({_center_y(atom) for atom in values}),
        }
        removed.update(id(band) for band in group if band is not first)
    return sorted(
        [replacements.get(id(band), band) for band in bands if id(band) not in removed],
        key=lambda band: band["x0"],
    )


def rescue_sparse_body_bands(atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]], header_cutoff: float | None) -> list[dict[str, Any]]:
    """Keep a sparse inner column when its visual row proves tracks on both sides.

    A note/reference column can occur in the last header-like row (for example
    ``45(b)`` between an item label and two amount columns).  It must remain a
    leaf column even if the header/body cutoff happens to fall below that row.
    """
    if len(bands) < 2:
        return [dict(band) for band in bands]
    rescued = [dict(band) for band in bands]
    # 宽列内若破折号和右侧数值在多行中持续形成两条轨道，破折号就是独立
    # 窄列，而不是金额空值。金额空值会与已有数值右边缘对齐，且通常落在
    # 列带边界外；这里仅处理两条轨道都位于同一宽列内部的情形。
    split_bands: list[dict[str, Any]] = []
    for band in rescued:
        inside = [
            atom for atom in atoms
            if atom["bbox"][0] >= band["x0"] - 1.0 and atom["bbox"][2] <= band["x1"] + 1.0
        ]
        symbols = [
            atom for atom in inside
            if re.fullmatch(r"[\s\-\u2013\u2014\u2212]+", str(atom.get("text", "")))
        ]
        if len({_center_y(atom) for atom in symbols}) < 3:
            split_bands.append(band)
            continue
        symbol_right = statistics.median(atom["bbox"][2] for atom in symbols)
        symbol_rows = [_center_y(atom) for atom in symbols]
        right_values = [
            atom for atom in inside
            if re.search(r"\d", str(atom.get("text", "")))
            and atom["bbox"][0] >= symbol_right + 8.0
            and any(abs(_center_y(atom) - row_y) <= 2.4 for row_y in symbol_rows)
        ]
        if len({_center_y(atom) for atom in right_values}) < 3:
            split_bands.append(band)
            continue
        split_x = (symbol_right + min(atom["bbox"][0] for atom in right_values)) / 2.0
        if split_x <= band["x0"] + 4.0 or split_x >= band["x1"] - 4.0:
            split_bands.append(band)
            continue
        split_bands.extend((
            {**band, "x1": split_x, "kind": "symbol_leaf"},
            {**band, "x0": split_x, "kind": "numeric_leaf"},
        ))
    rescued = split_bands
    body_atoms = [
        atom for atom in atoms
        if header_cutoff is None or _center_y(atom) > header_cutoff
    ]
    for atom in body_atoms:
        # 破折号是金额列的空值表示。它可落在相邻列边界附近，但单独不能
        # 证明存在一条新的逻辑列；否则会把同一金额列拆成极窄的伪列带。
        if re.fullmatch(r"[\s\-\u2013\u2014\u2212]+", str(atom.get("text", ""))):
            continue
        if any(horizontal_overlap(atom, {"bbox": [band["x0"], 0.0, band["x1"], 1.0]}) > 0 for band in rescued):
            continue
        center_x = (atom["bbox"][0] + atom["bbox"][2]) / 2.0
        left = [band for band in rescued if band["x1"] < center_x]
        right = [band for band in rescued if band["x0"] > center_x]
        if not left or not right:
            continue
        nearest_left = max(left, key=lambda band: band["x1"])
        nearest_right = min(right, key=lambda band: band["x0"])
        row_mates = [item for item in atoms if abs(_center_y(item) - _center_y(atom)) <= 2.4]
        left_mates = [item for item in row_mates if horizontal_overlap(item, {"bbox": [nearest_left["x0"], 0.0, nearest_left["x1"], 1.0]}) > 0]
        right_mates = [item for item in row_mates if horizontal_overlap(item, {"bbox": [nearest_right["x0"], 0.0, nearest_right["x1"], 1.0]}) > 0]
        if not left_mates or not right_mates:
            continue
        left_gap = atom["bbox"][0] - max(item["bbox"][2] for item in left_mates)
        right_gap = min(item["bbox"][0] for item in right_mates) - atom["bbox"][2]
        line_height = max(
            float(item.get("font_size") or 0.0)
            for item in [atom, *left_mates, *right_mates]
        )
        line_height = max(
            line_height,
            max(item["bbox"][3] - item["bbox"][1] for item in left_mates + right_mates),
        )
        # This is a column-gap test, not a column-count heuristic.  Prevent
        # nearby words in one text run from being promoted to a fake column.
        if left_gap >= max(8.0, line_height * 1.25) and right_gap >= max(8.0, line_height * 1.25):
            rescued.append({"x0": atom["bbox"][0], "x1": atom["bbox"][2], "support": 1, "y_support": 1, "kind": "sparse_body"})
    rescued.sort(key=lambda item: item["x0"])
    for index, band in enumerate(rescued, 1):
        band["id"] = index
    return rescued



def rescue_header_only_note_bands(
    atoms: Sequence[dict[str, Any]],
    bands: Sequence[dict[str, Any]],
    header_cutoff: float | None,
) -> list[dict[str, Any]]:
    """Recover a header-only note column from the first stable-band gap."""
    rescued = [dict(band) for band in bands]
    if header_cutoff is None:
        return rescued

    stable = sorted(
        (
            band
            for band in rescued
            if band.get("kind") not in {"sparse_body", "header_only_note"}
        ),
        key=lambda band: band["x0"],
    )
    if len(stable) < 2:
        return rescued

    left, right = stable[0], stable[1]
    for atom in atoms:
        if _center_y(atom) > header_cutoff or not _is_note_reference_atom(atom):
            continue
        x0, x1 = atom["bbox"][0], atom["bbox"][2]
        if x1 <= x0 or x0 < left["x1"] or x1 > right["x0"]:
            continue
        if any(
            horizontal_overlap(atom, {"bbox": [band["x0"], 0.0, band["x1"], 1.0]}) > 0
            for band in rescued
        ):
            continue
        candidate = {
            "x0": x0,
            "x1": x1,
            "support": 1,
            "y_support": 1,
            "kind": "header_only_note",
        }
        if any(
            horizontal_overlap(
                {"bbox": [candidate["x0"], 0.0, candidate["x1"], 1.0]},
                {"bbox": [band["x0"], 0.0, band["x1"], 1.0]},
            ) > 0
            for band in rescued
        ):
            continue
        rescued.append(candidate)

    rescued.sort(key=lambda band: band["x0"])
    for index, band in enumerate(rescued, 1):
        band["id"] = index
    return rescued


def rescue_header_only_leaf_bands(
    atoms: Sequence[dict[str, Any]],
    bands: Sequence[dict[str, Any]],
    header_cutoff: float | None,
) -> list[dict[str, Any]]:
    """Recover isolated leaf headers only when their row proves every stable band."""
    rescued = [dict(band) for band in bands]
    if header_cutoff is None:
        return rescued

    stable = sorted(
        (
            band
            for band in rescued
            if band.get("kind")
            not in {"sparse_body", "header_only_note", "header_only_leaf"}
        ),
        key=lambda band: band["x0"],
    )
    if len(stable) < 2:
        return rescued

    stable_ids = {int(band["id"]) for band in stable}
    header_atoms = [
        atom for atom in atoms if _center_y(atom) <= header_cutoff
    ]
    levels = _levels(header_atoms)
    eligible_levels: list[
        tuple[float, list[dict[str, Any]], list[dict[str, Any]], bool]
    ] = []
    stable_id_order = [int(band["id"]) for band in stable]
    for level_index, level in enumerate(levels):
        row = [
            atom
            for atom in header_atoms
            if abs(_center_y(atom) - level) <= 2.4
        ]
        covered_ids: set[int] = set()
        candidates: list[dict[str, Any]] = []
        has_parent = False
        for atom in row:
            overlaps = [
                band
                for band in stable
                if _meaningful_header_band_overlap(atom, band)
            ]
            if len(overlaps) == 1:
                covered_ids.add(int(overlaps[0]["id"]))
            elif len(overlaps) > 1:
                has_parent = True
            else:
                candidates.append(atom)
        if has_parent:
            continue
        if covered_ids == stable_ids and candidates:
            eligible_levels.append((level, row, candidates, False))
            continue
        if len(candidates) < 2 or len(covered_ids) < 2 or level_index == 0:
            continue

        covered_order = [
            band_id for band_id in stable_id_order if band_id in covered_ids
        ]
        suffix_start = len(stable_id_order) - len(covered_order)
        if covered_order != stable_id_order[suffix_start:] or suffix_start == 0:
            continue

        missing_prefix = stable[:suffix_start]
        previous_level = levels[level_index - 1]
        previous_row = [
            atom
            for atom in header_atoms
            if abs(_center_y(atom) - previous_level) <= 2.4
        ]
        prefix_is_proven = all(
            any(
                [
                    int(overlap["id"])
                    for overlap in stable
                    if _meaningful_header_band_overlap(atom, overlap)
                ]
                == [int(band["id"])]
                for atom in previous_row
            )
            for band in missing_prefix
        )
        first_covered = stable[suffix_start]
        last_covered = stable[-1]
        candidates_are_bounded = all(
            first_covered["x0"] <= atom["bbox"][0]
            and atom["bbox"][2] <= last_covered["x1"]
            for atom in candidates
        )
        if prefix_is_proven and candidates_are_bounded:
            eligible_levels.append((level, row, candidates, True))

    if not eligible_levels:
        return rescued
    _, row, candidates, require_complete_group = max(
        eligible_levels, key=lambda item: item[0]
    )
    additions: list[dict[str, Any]] = []
    for atom in candidates:
        text = str(atom.get("text", "")).strip()
        if _is_structural_header_atom(atom):
            if require_complete_group:
                return rescued
            continue
        if require_complete_group and (
            _is_note_reference_atom(atom)
            or _NUMERIC.fullmatch(text)
            or _is_placeholder(atom)
        ):
            return rescued
        if any(
            horizontal_overlap(
                atom,
                {"bbox": [band["x0"], 0.0, band["x1"], 1.0]},
            )
            > 0
            for band in [*rescued, *additions]
        ):
            if require_complete_group:
                return rescued
            continue

        x0, x1 = atom["bbox"][0], atom["bbox"][2]
        left = [item for item in row if item is not atom and item["bbox"][2] <= x0]
        right = [item for item in row if item is not atom and item["bbox"][0] >= x1]
        if not left and not right:
            if require_complete_group:
                return rescued
            continue
        neighbors = [
            item
            for item in (
                [max(left, key=lambda item: item["bbox"][2])] if left else []
            )
            + ([min(right, key=lambda item: item["bbox"][0])] if right else [])
        ]
        line_height = max(
            [
                float(atom.get("font_size") or 0.0),
                atom["bbox"][3] - atom["bbox"][1],
            ]
            + [
                max(
                    float(item.get("font_size") or 0.0),
                    item["bbox"][3] - item["bbox"][1],
                )
                for item in neighbors
            ]
        )
        minimum_gap = max(8.0, line_height * 1.25)
        if left and x0 - max(item["bbox"][2] for item in left) < minimum_gap:
            if require_complete_group:
                return rescued
            continue
        if right and min(item["bbox"][0] for item in right) - x1 < minimum_gap:
            if require_complete_group:
                return rescued
            continue

        additions.append(
            {
                "x0": x0,
                "x1": x1,
                "support": 1,
                "y_support": 1,
                "kind": "header_only_leaf",
            }
        )

    rescued.extend(additions)

    rescued.sort(key=lambda band: band["x0"])
    for index, band in enumerate(rescued, 1):
        band["id"] = index
    return rescued


def _infer_centered_parent_span(
    atom: dict[str, Any], atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]], header_cutoff: float
) -> list[int]:
    """Infer a centred parent-header span from the immediately lower header tier.

    PDF authors commonly centre a parent title over a wide group of leaves.  Its
    glyph bbox therefore covers only the middle leaves and cannot itself define
    the colspan.  We only accept a span when a contiguous lower header tier
    supports it and the inferred group's centre agrees with the title centre.
    """
    if _is_temporal_leaf_header(atom) or _is_bare_year_parent_header(atom):
        return []
    atom_center = (atom["bbox"][0] + atom["bbox"][2]) / 2.0
    atom_width = atom["bbox"][2] - atom["bbox"][0]
    header_bands = _header_leaf_bands(bands)
    lower = [
        item for item in atoms
        if _center_y(item) > _center_y(atom) + 4.0
        and _center_y(item) <= header_cutoff
        and not _is_temporal_leaf_header(item)
        and not _is_structural_header_atom(item)
    ]
    if len(lower) < 3:
        return []
    # 同一父表头的末级标签有时分两行排版（例如 ``Subtotal`` 单独下沉）。
    # 除逐层尝试外，再汇总所有下方非结构标签，避免只取第一层而截掉两端叶子列。
    viable: list[tuple[float, list[int]]] = []
    for level in _levels(lower) + [None]:
        tier = lower if level is None else [item for item in lower if abs(_center_y(item) - level) < 1.2]
        leaf_ids = sorted(
            {
                assign_column(item, header_bands)
                for item in tier
                if assign_column(item, header_bands) is not None
            }
        )
        if len(leaf_ids) < 3:
            continue
        candidates: list[list[int]] = []
        for start_index in range(len(leaf_ids)):
            for end_index in range(start_index + 2, len(leaf_ids)):
                leaf_span = leaf_ids[start_index : end_index + 1]
                span = list(range(leaf_span[0], leaf_span[-1] + 1))
                skipped = [
                    band
                    for band in bands
                    if band["id"] in span and band["id"] not in leaf_span
                ]
                # 附注/稀疏正文列保留在物理网格中，但不能切断主表头叶子列。
                if any(band.get("kind") != "sparse_body" for band in skipped):
                    continue
                candidates.append(span)
        for span in candidates:
            first = next(band for band in bands if band["id"] == span[0])
            last = next(band for band in bands if band["id"] == span[-1])
            width = last["x1"] - first["x0"]
            centre = (first["x0"] + last["x1"]) / 2.0
            if width < atom_width * 1.55 or width > atom_width * 3.05:
                continue
            if abs(centre - atom_center) <= max(4.0, width * 0.08):
                viable.append((abs(centre - atom_center), span))
    if viable:
        viable.sort(key=lambda item: (item[0], -len(item[1])))
        return viable[0][1]
    return []


def _infer_complete_physical_leaf_span(
    atom: dict[str, Any],
    atoms: Sequence[dict[str, Any]],
    bands: Sequence[dict[str, Any]],
    header_cutoff: float,
) -> list[int]:
    """Infer a parent span from a complete physical leaf tier."""
    if _is_temporal_leaf_header(atom) or _is_structural_header_atom(atom):
        return []

    physical_bands = sorted(
        (
            band
            for band in bands
            if band.get("kind") != "header_only_note"
        ),
        key=lambda band: band["x0"],
    )
    if len(physical_bands) < 3:
        return []

    parent_column = assign_column(atom, physical_bands)
    if parent_column is None:
        return []

    parent_level = _center_y(atom)
    lower = [
        item
        for item in atoms
        if parent_level + 4.0 < _center_y(item) <= header_cutoff
        and str(item.get("text", "")).strip()
        and not _is_structural_header_atom(item)
        and not _is_note_reference_atom(item)
    ]
    if not lower:
        return []

    band_by_id = {int(band["id"]): band for band in physical_bands}
    same_level_peers = [
        peer
        for peer in atoms
        if peer is not atom
        and abs(_center_y(peer) - parent_level) <= 2.4
        and not _is_note_reference_atom(peer)
    ]
    candidates: list[tuple[float, list[int]]] = []
    for level in _levels(lower):
        tier = [item for item in lower if abs(_center_y(item) - level) < 1.2]
        if any(_is_placeholder(item) or _NUMERIC.fullmatch(str(item.get("text", "")).strip()) for item in tier):
            continue
        assigned: list[tuple[dict[str, Any], int]] = []
        for item in tier:
            overlaps = [
                int(band["id"])
                for band in physical_bands
                if _meaningful_header_band_overlap(item, band)
            ]
            if len(overlaps) != 1:
                assigned = []
                break
            assigned.append((item, overlaps[0]))
        if not assigned:
            continue

        leaf_columns = [column for _item, column in assigned]
        if len(set(leaf_columns)) != len(leaf_columns):
            continue
        ordered_columns = sorted(leaf_columns)
        runs: list[list[int]] = []
        for column in ordered_columns:
            if not runs or column != runs[-1][-1] + 1:
                runs.append([column])
            else:
                runs[-1].append(column)
        for run in runs:
            if len(run) < 3 or parent_column not in run:
                continue
            for start_idx in range(len(run)):
                for end_idx in range(start_idx + 2, len(run)):
                    sub_run = run[start_idx : end_idx + 1]
                    if parent_column not in sub_run:
                        continue
                    if not all(column in band_by_id for column in sub_run):
                        continue
                    first, last = band_by_id[sub_run[0]], band_by_id[sub_run[-1]]
                    group_width = last["x1"] - first["x0"]
                    group_center = (first["x0"] + last["x1"]) / 2.0
                    parent_center = (atom["bbox"][0] + atom["bbox"][2]) / 2.0
                    error = abs(group_center - parent_center)
                    narrowest_band_width = min(
                        band["x1"] - band["x0"]
                        for band in (band_by_id[column] for column in sub_run)
                    )
                    if error > max(4.0, narrowest_band_width * 0.50):
                        continue
                    candidate_x0, candidate_x1 = first["x0"], last["x1"]
                    if any(
                        horizontal_overlap(
                            peer, {"bbox": [candidate_x0, 0.0, candidate_x1, 1.0]}
                        ) > 0
                        for peer in same_level_peers
                    ):
                        continue
                    candidates.append((error, sub_run))

    if not candidates:
        return []
    unique_candidates = {
        tuple(span): error
        for error, span in candidates
    }
    longest_length = max(len(span) for span in unique_candidates)
    longest = [
        (error, list(span))
        for span, error in unique_candidates.items()
        if len(span) == longest_length
    ]
    if len(longest) != 1:
        return []
    return longest[0][1]


def _infer_wrapped_two_leaf_parent_spans(
    header: Sequence[dict[str, Any]],
    bands: Sequence[dict[str, Any]],
    assignment_bands: Sequence[dict[str, Any]],
    parent_level: float,
    parents: Sequence[dict[str, Any]],
) -> dict[int, list[int]]:
    """Pair parents when a child label is split across vertical header atoms.

    A wrapped child can occupy two nearby y-levels, so requiring all child
    labels to share one exact level makes an otherwise complete 1:2 tier look
    incomplete.  Grouping evidence by already inferred leaf column keeps this
    fallback geometric and leaves the final text merge to the normal cell
    pipeline.
    """
    if not parents:
        return {}

    atoms_by_column: dict[int, list[dict[str, Any]]] = {}
    for atom in header:
        if _center_y(atom) <= parent_level + 2.4:
            continue
        if _is_structural_header_atom(atom) or _is_note_reference_atom(atom):
            continue
        column = assign_column(atom, assignment_bands)
        if column is not None:
            atoms_by_column.setdefault(int(column), []).append(atom)

    available_columns = sorted(atoms_by_column)
    expected_leaf_count = len(parents) * 2
    band_by_id = {int(band["id"]): band for band in bands}
    assignment_ids = {int(band["id"]) for band in assignment_bands}
    if expected_leaf_count < 2:
        return {}

    parent_columns = [assign_column(parent, assignment_bands) for parent in parents]
    if any(column is None for column in parent_columns):
        return {}

    for start in range(len(available_columns) - expected_leaf_count + 1):
        candidate = available_columns[start : start + expected_leaf_count]
        if candidate != list(range(candidate[0], candidate[-1] + 1)):
            continue
        if not all(column in assignment_ids and column in band_by_id for column in candidate):
            continue

        pairs = [candidate[index : index + 2] for index in range(0, len(candidate), 2)]
        if any(parent_column not in pair for parent_column, pair in zip(parent_columns, pairs)):
            continue

        inferred: dict[int, list[int]] = {}
        for parent, pair in zip(parents, pairs):
            first = band_by_id[pair[0]]
            last = band_by_id[pair[-1]]
            group_width = last["x1"] - first["x0"]
            group_center = (first["x0"] + last["x1"]) / 2.0
            parent_center = (parent["bbox"][0] + parent["bbox"][2]) / 2.0
            if abs(group_center - parent_center) > max(4.0, group_width * 0.10):
                break
            if any(not atoms_by_column.get(column) for column in pair):
                break
            inferred[id(parent)] = pair
        else:
            return inferred
    return {}


def _infer_complete_child_group_span(
    atom: dict[str, Any],
    atoms: Sequence[dict[str, Any]],
    assignment_bands: Sequence[dict[str, Any]],
    header_cutoff: float,
    inferred_spans: dict[int, list[int]],
) -> list[int]:
    """Infer a wide parent from complete mixed child coverage.

    A child is not required to have a colspan: a terminal header such as a
    vertically centred ``账面价值`` still contributes one column.  Known
    grouped children are kept as units, while uncovered single-column header
    evidence becomes terminal units.  Only complete, contiguous unit runs
    whose overall centre uniquely matches the parent are accepted.
    """
    if _is_temporal_leaf_header(atom) or _is_structural_header_atom(atom):
        return []

    parent_center_y = _center_y(atom)
    lower = [
        item
        for item in atoms
        if parent_center_y + 4.0 < _center_y(item) <= header_cutoff
        and not _is_structural_header_atom(item)
        and not _is_note_reference_atom(item)
    ]
    if len(lower) < 2:
        return []

    band_by_id = {int(band["id"]): band for band in assignment_bands}
    parent_column = assign_column(atom, assignment_bands)
    if parent_column is None:
        return []

    grouped_units: list[list[int]] = []
    grouped_columns: set[int] = set()
    for child in lower:
        span = sorted({int(column) for column in inferred_spans.get(id(child), [])})
        if not span or span != list(range(span[0], span[-1] + 1)):
            continue
        if not all(column in band_by_id for column in span):
            continue
        grouped_units.append(span)
        grouped_columns.update(span)

    ordered_grouped_units = sorted(grouped_units, key=lambda span: span[0])
    if not ordered_grouped_units:
        return []
    if any(
        right[0] <= left[-1]
        for left, right in zip(ordered_grouped_units, ordered_grouped_units[1:])
    ):
        return []

    terminal_columns: set[int] = set()
    for child in lower:
        column = assign_column(child, assignment_bands)
        if column is not None and column not in grouped_columns:
            terminal_columns.add(int(column))
    units = [*ordered_grouped_units, *([column] for column in sorted(terminal_columns))]
    units.sort(key=lambda span: span[0])
    if len(units) < 2 or any(
        right[0] <= left[-1] for left, right in zip(units, units[1:])
    ):
        return []

    viable: list[tuple[float, int, list[int]]] = []
    for start in range(len(units)):
        end = start
        while end < len(units):
            if end > start and units[end][0] != units[end - 1][-1] + 1:
                break
            if end - start + 1 >= 2:
                span = list(range(units[start][0], units[end][-1] + 1))
                if len(span) >= 3 and parent_column in span:
                    first = band_by_id[span[0]]
                    last = band_by_id[span[-1]]
                    group_width = last["x1"] - first["x0"]
                    group_center = (first["x0"] + last["x1"]) / 2.0
                    parent_center = (atom["bbox"][0] + atom["bbox"][2]) / 2.0
                    error = abs(group_center - parent_center)
                    if error > max(4.0, group_width * 0.10):
                        end += 1
                        continue
                    occupied_by_peer = False
                    for peer in atoms:
                        if peer is atom or abs(_center_y(peer) - parent_center_y) > 2.4:
                            continue
                        if _is_note_reference_atom(peer):
                            continue
                        peer_span = sorted(
                            {
                                int(column)
                                for column in inferred_spans.get(id(peer), [])
                            }
                        )
                        if not peer_span:
                            peer_span = [
                                int(band["id"])
                                for band in assignment_bands
                                if _meaningful_header_band_overlap(peer, band)
                            ]
                        if not peer_span:
                            peer_column = assign_column(peer, assignment_bands)
                            peer_span = [] if peer_column is None else [peer_column]
                        if set(span).intersection(peer_span):
                            occupied_by_peer = True
                            break
                    if not occupied_by_peer:
                        viable.append((error, -len(span), span))
            end += 1

    if not viable:
        return []
    viable.sort(key=lambda item: (item[0], item[1]))
    if len(viable) > 1 and viable[1][0] - viable[0][0] <= 4.0:
        return []
    return viable[0][2]


def _infer_two_leaf_parent_spans(
    atoms: Sequence[dict[str, Any]],
    bands: Sequence[dict[str, Any]],
    header_cutoff: float,
) -> dict[int, list[int]]:
    """Map a complete parent tier to non-overlapping two-leaf groups."""
    header = [
        atom
        for atom in atoms
        if _center_y(atom) <= header_cutoff and not _is_note_reference_atom(atom)
    ]
    levels = _levels(header)
    assignment_bands = _header_leaf_bands(bands)
    inferred: dict[int, list[int]] = {}

    for parent_index, parent_level in enumerate(levels[:-1]):
        parents = sorted(
            (
                atom
                for atom in header
                if abs(_center_y(atom) - parent_level) < 1.2
                and not _is_temporal_leaf_header(atom)
            ),
            key=lambda atom: atom["bbox"][0],
        )
        parent_columns = [assign_column(atom, assignment_bands) for atom in parents]
        if (
            not parents
            or any(column is None for column in parent_columns)
            or len(set(parent_columns)) != len(parent_columns)
        ):
            continue

        tier_inferred = False
        for leaf_level in levels[parent_index + 1 :]:
            leaves = [
                atom
                for atom in header
                if abs(_center_y(atom) - leaf_level) < 1.2
                and not _is_structural_header_atom(atom)
            ]
            leaf_columns = [assign_column(atom, assignment_bands) for atom in leaves]
            if (
                len(leaves) != len(parents) * 2
                or any(column is None for column in leaf_columns)
                or len(set(leaf_columns)) != len(leaf_columns)
            ):
                continue
            leaf_ids = sorted(int(column) for column in leaf_columns if column is not None)
            if leaf_ids != list(range(leaf_ids[0], leaf_ids[-1] + 1)):
                continue

            pairs = [
                leaf_ids[index : index + 2]
                for index in range(0, len(leaf_ids), 2)
            ]
            tier_mapping: dict[int, list[int]] = {}
            for parent, parent_column, pair in zip(parents, parent_columns, pairs):
                if parent_column not in pair:
                    break
                first = next(band for band in bands if band["id"] == pair[0])
                last = next(band for band in bands if band["id"] == pair[-1])
                group_width = last["x1"] - first["x0"]
                group_center = (first["x0"] + last["x1"]) / 2.0
                parent_center = (parent["bbox"][0] + parent["bbox"][2]) / 2.0
                direct = {
                    int(band["id"])
                    for band in assignment_bands
                    if _meaningful_header_band_overlap(parent, band)
                }
                aligned = abs(group_center - parent_center) <= max(
                    4.0, group_width * 0.08
                )
                if not aligned and not set(pair).issubset(direct):
                    break
                tier_mapping[id(parent)] = pair
            else:
                inferred.update(tier_mapping)
                tier_inferred = True
                break
        if not tier_inferred:
            inferred.update(
                _infer_wrapped_two_leaf_parent_spans(
                    header,
                    bands,
                    assignment_bands,
                    parent_level,
                    parents,
                )
            )
    return inferred



def _header_leaf_bands(bands: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回可定义表头叶子列的列带，保留附注窄列的物理网格位置。"""
    primary = [
        band
        for band in bands
        if band.get("kind") not in {"sparse_body", "header_only_note"}
    ]
    if primary:
        return primary
    non_note = [band for band in bands if band.get("kind") != "header_only_note"]
    return non_note or list(bands)


def _assign_dash_body_atoms_to_right_aligned_tracks(atoms: Sequence[dict[str, Any]], header_cutoff: float | None) -> None:
    """将正文破折号按同列金额的右边缘归属，避免窄表头带误分配。"""
    if header_cutoff is None:
        return
    anchors: dict[int, list[float]] = {}
    for atom in atoms:
        if _center_y(atom) <= header_cutoff or not re.search(r"\d", str(atom.get("text", ""))):
            continue
        column_id = atom.get("column_id")
        if column_id is not None:
            anchors.setdefault(int(column_id), []).append(float(atom["bbox"][2]))
    right_edges = {column_id: statistics.median(values) for column_id, values in anchors.items() if len(values) >= 2}
    for atom in atoms:
        if _center_y(atom) <= header_cutoff or not re.fullmatch(r"[\s\-\u2013\u2014\u2212]+", str(atom.get("text", ""))):
            continue
        right_edge = float(atom["bbox"][2])
        candidates = [(abs(right_edge - anchor), column_id) for column_id, anchor in right_edges.items()]
        if not candidates:
            continue
        distance, column_id = min(candidates)
        if distance <= 3.0:
            atom["column_id"] = column_id
            atom["column_start"] = column_id
            atom["column_end"] = column_id


def annotate_columns(atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]], header_cutoff: float | None, region: BBox | None = None) -> None:
    """Attach leaf column positions; header atoms intersecting multiple leaves become colspans."""
    two_leaf_parent_spans = (
        _infer_two_leaf_parent_spans(atoms, bands, header_cutoff)
        if header_cutoff is not None
        else {}
    )
    for atom in atoms:
        in_header = header_cutoff is not None and _center_y(atom) <= header_cutoff
        assignment_bands = _header_leaf_bands(bands) if in_header and not _is_note_reference_atom(atom) else bands
        column_id = assign_column(atom, assignment_bands)
        if _is_temporal_leaf_header(atom):
            column_id = _temporal_leaf_column(atom, bands)
        elif in_header:
            material_bands = [
                int(band["id"])
                for band in bands
                if _meaningful_header_band_overlap(atom, band)
            ]
            if len(material_bands) == 1:
                column_id = material_bands[0]
        atom["column_id"] = column_id
        atom["column_start"] = column_id
        atom["column_end"] = column_id
        atom["colspan"] = 1
        section_title = region is not None and is_sparse_left_section_title(atom, atoms, region)
        if column_id is None or (not section_title and (header_cutoff is None or _center_y(atom) > header_cutoff)):
            continue
        # Do not turn a leaf header into a parent just because its glyph box
        # touches the adjacent band by a few points.  This is common for a
        # wrapped title such as ``Remuneration / committee / meetings``.
        # Bare years are structural parent headers: their short glyph boxes may
        # sit close to a leaf boundary even when they intentionally cover a
        # whole period group.  Do not extend this exception to every digit-
        # bearing run: ``RMB'000`` and ``(note (i))`` are leaf labels.
        header_structure = _is_bare_year_parent_header(atom)
        direct = [
            int(band["id"])
            for band in assignment_bands
            if (
                horizontal_overlap(atom, {"bbox": [band["x0"], 0.0, band["x1"], 1.0]}) > 0
                if header_structure
                else _meaningful_header_band_overlap(atom, band)
            )
        ]
        intersecting = [column_id] if _is_temporal_leaf_header(atom) and column_id is not None else list(direct)
        # A single material overlap is stronger evidence than a closest-centre
        # assignment when compact header bands are adjacent.  This prevents the
        # right-side unit of a repeated pair from inheriting the left column.
        if len(direct) == 1 and not _is_temporal_leaf_header(atom):
            column_id = direct[0]
            atom["column_id"] = column_id
            atom["column_start"] = column_id
            atom["column_end"] = column_id
        # 数值正文已把一个父带拆成多个叶子列时，居中的年份/期间表头不一定
        # 真正覆盖每个叶子带。仍按其相对父带中心恢复 colspan，不能误判成首列。
        inferred_parent_span = two_leaf_parent_spans.get(id(atom), [])
        if not inferred_parent_span and header_cutoff is not None:
            inferred_parent_span = _infer_complete_physical_leaf_span(
                atom, atoms, bands, header_cutoff
            )
        if not inferred_parent_span and header_cutoff is not None:
            inferred_parent_span = _infer_centered_parent_span(
                atom, atoms, bands, header_cutoff
            )
        if not inferred_parent_span and header_cutoff is not None:
            inferred_parent_span = _infer_complete_child_group_span(
                atom,
                atoms,
                assignment_bands,
                header_cutoff,
                two_leaf_parent_spans,
            )
        if inferred_parent_span:
            intersecting = inferred_parent_span
        parent_band = next((band for band in bands if band["id"] == column_id), None)
        if not inferred_parent_span and parent_band is not None and "parent_x0" in parent_band:
            siblings = [
                band for band in bands
                if band.get("parent_x0") == parent_band["parent_x0"]
                and band.get("parent_x1") == parent_band["parent_x1"]
            ]
            parent_center = (parent_band["parent_x0"] + parent_band["parent_x1"]) / 2.0
            atom_center = (atom["bbox"][0] + atom["bbox"][2]) / 2.0
            leaf_header_y = min(
                (float(band["leaf_header_y"]) for band in siblings if "leaf_header_y" in band),
                default=None,
            )
            # 只有位于叶子表头之上的标题才能覆盖整个父带。年份、Directly 等
            # 叶子层标签即使恰好位于父带中心，也不能被误扩成整段 colspan。
            is_parent_level = leaf_header_y is None or _center_y(atom) < leaf_header_y - 1.2
            if (
                is_parent_level
                and not _is_temporal_leaf_header(atom)
                and len(siblings) >= 2
                # A parent must materially cover at least two leaf bands.
                # Do not promote a wrapped leaf label solely because its
                # centre happens to be near the parent-band centre.
                and len(direct) >= 2
                and abs(atom_center - parent_center) <= max(4.0, (parent_band["parent_x1"] - parent_band["parent_x0"]) * 0.10)
            ):
                intersecting = [int(band["id"]) for band in siblings]
        # 不再用“距相邻列边界不足 1pt”补成 colspan。PDF 字形外接框常会
        # 轻微越界，尤其是中文储备类表头；把这种贴边解释为跨列会把
        # “重估储备 / 匯兌儲備”误写进同一列组。真实父表头已经由 direct
        # 的双列实质重叠和上面的 parent_band 规则覆盖。
        if len(intersecting) >= 2:
            atom["column_start"] = min(intersecting)
            atom["column_end"] = max(intersecting)
            atom["column_id"] = atom["column_start"]
            atom["colspan"] = atom["column_end"] - atom["column_start"] + 1

    _assign_dash_body_atoms_to_right_aligned_tracks(atoms, header_cutoff)
