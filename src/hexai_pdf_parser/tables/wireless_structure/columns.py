"""Stable x-column tracks for the isolated wireless recovery algorithms."""

from __future__ import annotations

import re
import statistics
from typing import Any, Sequence

from hexai_pdf_parser.core.models import BBox


def _horizontal_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    return max(0.0, min(left["bbox"][2], right["bbox"][2]) - max(left["bbox"][0], right["bbox"][0]))


def horizontal_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Return the real horizontal overlap between two bbox-bearing objects."""
    return _horizontal_overlap(left, right)


def is_sparse_left_section_title(
    item: dict[str, Any], atoms: Sequence[dict[str, Any]], region: BBox
) -> bool:
    """Identify a left-aligned section title that must not bridge data columns."""
    item_center = (item["bbox"][1] + item["bbox"][3]) / 2.0
    same_row = [
        candidate
        for candidate in atoms
        if abs((candidate["bbox"][1] + candidate["bbox"][3]) / 2.0 - item_center) <= 2.4
    ]
    return (
        len(same_row) == 1
        and item["bbox"][0] <= region.x0 + 16.0
        and item["bbox"][2] - item["bbox"][0] >= (region.x1 - region.x0) * 0.25
    )


def _compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    overlap = _horizontal_overlap(left, right)
    narrow = max(
        1.0,
        min(left["bbox"][2] - left["bbox"][0], right["bbox"][2] - right["bbox"][0]),
    )
    return overlap >= max(2.0, narrow * 0.25)


def _is_wide_header(item: dict[str, Any], region: BBox) -> bool:
    width = max(1.0, region.x1 - region.x0)
    item_width = item["bbox"][2] - item["bbox"][0]
    return item_width >= width * 0.28 and item["bbox"][0] >= region.x0 + width * 0.18


def infer_column_bands(atoms: Sequence[dict[str, Any]], region: BBox) -> list[dict[str, Any]]:
    """Build column bands from repeated x-overlap components."""
    candidates = [
        item
        for item in atoms
        if item["bbox"][2] - item["bbox"][0] < (region.x1 - region.x0) * 0.86
        and not _is_wide_header(item, region)
    ]
    components: list[list[dict[str, Any]]] = []
    for atom in sorted(candidates, key=lambda item: item["bbox"][0]):
        matched = [
            component
            for component in components
            if any(_compatible(atom, member) for member in component)
        ]
        if not matched:
            components.append([atom])
            continue
        merged = [atom]
        for component in matched:
            merged.extend(component)
            components.remove(component)
        components.append(merged)

    bands = []
    for component in components:
        y_support = {
            round(((item["bbox"][1] + item["bbox"][3]) / 2.0) / 8.0)
            for item in component
        }
        if len(component) < 2 or len(y_support) < 2:
            continue
        bands.append(
            {
                "x0": min(item["bbox"][0] for item in component),
                "x1": max(item["bbox"][2] for item in component),
                "support": len(component),
                "y_support": len(y_support),
            }
        )

    bands.sort(key=lambda item: item["x0"])
    for index, band in enumerate(bands, 1):
        band["id"] = index
    return bands


def assign_column(atom: dict[str, Any], bands: Sequence[dict[str, Any]]) -> int | None:
    """Assign a text run to the band with the greatest x overlap."""
    if not bands:
        return None
    overlaps = [
        max(0.0, min(atom["bbox"][2], band["x1"]) - max(atom["bbox"][0], band["x0"]))
        for band in bands
    ]
    if max(overlaps) > 0:
        return int(bands[overlaps.index(max(overlaps))]["id"])
    center = (atom["bbox"][0] + atom["bbox"][2]) / 2.0
    return int(min(bands, key=lambda band: abs(center - (band["x0"] + band["x1"]) / 2.0))["id"])


def prune_paired_cjk_artifact_bands(
    atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Remove a weak band formed only by second characters of sparse labels."""
    if len(bands) < 2:
        return [dict(band) for band in bands]

    ordered_bands = sorted((dict(band) for band in bands), key=lambda item: item["id"])
    removed_ids: set[int] = set()
    for band in ordered_bands:
        if not (2 <= int(band.get("support", 0)) <= 3 and int(band.get("y_support", 0)) >= 2):
            continue
        members = [
            atom
            for atom in atoms
            if band["x0"] <= (atom["bbox"][0] + atom["bbox"][2]) / 2.0 <= band["x1"]
        ]
        if len(members) != int(band["support"]) or not all(
            re.fullmatch(r"[\u3400-\u9fff]", str(atom.get("text", "")))
            for atom in members
        ):
            continue

        predecessor_columns: list[int] = []
        for member in members:
            predecessors = [
                atom
                for atom in atoms
                if atom.get("flow_end", -2) + 1 == member.get("flow_start", -1)
                and atom.get("source_blocks") == member.get("source_blocks")
                and atom.get("source_line_start") == member.get("source_line_start")
                and re.fullmatch(r"[\u3400-\u9fff]", str(atom.get("text", "")))
                and abs(
                    (atom["bbox"][1] + atom["bbox"][3]) / 2.0
                    - (member["bbox"][1] + member["bbox"][3]) / 2.0
                )
                <= max(2.0, min(atom["font_size"], member["font_size"]) * 0.35)
                and 0.0 <= member["bbox"][0] - atom["bbox"][2]
                <= min(atom["font_size"], member["font_size"]) * 2.1
            ]
            if len(predecessors) != 1:
                predecessor_columns = []
                break
            predecessor_column = assign_column(predecessors[0], ordered_bands)
            if predecessor_column is None:
                predecessor_columns = []
                break
            predecessor_columns.append(predecessor_column)

        if not predecessor_columns or len(set(predecessor_columns)) != 1:
            continue
        left_id = predecessor_columns[0]
        if left_id != int(band["id"]) - 1:
            continue
        left_band = next(item for item in ordered_bands if int(item["id"]) == left_id)
        if (
            int(left_band.get("support", 0)) < max(4, int(band["support"]) * 2)
            or int(left_band.get("y_support", 0)) < 3
        ):
            continue
        removed_ids.add(int(band["id"]))

    result = [band for band in ordered_bands if int(band["id"]) not in removed_ids]
    for index, band in enumerate(result, 1):
        band["id"] = index
    return result


def prune_sparse_alignment_artifact_bands(
    atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Remove a leading weak band caused only by centered outer-row labels."""
    ordered_bands = sorted((dict(band) for band in bands), key=lambda item: item["id"])
    if len(ordered_bands) < 3:
        return ordered_bands

    left, candidate, right = ordered_bands[:3]
    if not (2 <= int(candidate.get("y_support", 0)) <= 3):
        return ordered_bands
    if int(left.get("y_support", 0)) < max(2, int(candidate.get("y_support", 0))):
        return ordered_bands
    if int(right.get("y_support", 0)) < int(candidate.get("y_support", 0)):
        return ordered_bands

    left_members = [
        atom for atom in atoms if assign_column(atom, ordered_bands) == int(left["id"])
    ]
    candidate_members = [
        atom
        for atom in atoms
        if assign_column(atom, ordered_bands) == int(candidate["id"])
    ]
    if not left_members or not candidate_members:
        return ordered_bands

    center_y = lambda atom: (atom["bbox"][1] + atom["bbox"][3]) / 2.0
    left_y = [center_y(atom) for atom in left_members]
    candidate_y = [center_y(atom) for atom in candidate_members]
    if any(
        abs(left_level - candidate_level) <= 2.4
        for left_level in left_y
        for candidate_level in candidate_y
    ):
        return ordered_bands
    if not all(
        level < min(left_y) - 2.4 or level > max(left_y) + 2.4
        for level in candidate_y
    ):
        return ordered_bands

    font_sizes = [
        float(atom["font_size"])
        for atom in [*left_members, *candidate_members]
        if float(atom.get("font_size", 0.0)) > 0.0
    ]
    if not font_sizes:
        return ordered_bands
    font_size = statistics.median(font_sizes)
    inner_gap = max(0.0, float(candidate["x0"]) - float(left["x1"]))
    next_gap = max(0.0, float(right["x0"]) - float(candidate["x1"]))
    if inner_gap > font_size * 0.6:
        return ordered_bands
    if next_gap < max(inner_gap * 3.0, font_size * 2.5):
        return ordered_bands

    result = [band for band in ordered_bands if int(band["id"]) != int(candidate["id"])]
    for index, band in enumerate(result, 1):
        band["id"] = index
    return result
