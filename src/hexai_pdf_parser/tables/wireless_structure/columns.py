"""Stable x-column tracks for the isolated wireless recovery algorithms."""

from __future__ import annotations

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
