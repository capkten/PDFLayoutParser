from typing import Any, Dict, List, Optional, Tuple

from . import _pdf_fast

Line4 = Tuple[float, float, float, float]


def merge_h_lines(lines: List[Line4], merge_group_tol: float) -> List[Line4]:
    owned_lines = [tuple(float(value) for value in line) for line in lines]
    merged_lines = _pdf_fast.merge_h_lines(owned_lines, float(merge_group_tol))
    return [tuple(float(value) for value in line) for line in merged_lines]


def merge_v_lines(
    lines: List[Line4],
    h_lines: Optional[List[Line4]] = None,
    merge_group_tol: float = 0.3,
    line_tolerance: float = 2.3,
) -> List[Line4]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    owned_h = [tuple(float(v) for v in line) for line in (h_lines or [])]
    merged = _pdf_fast.merge_v_lines(
        owned_lines, owned_h, float(merge_group_tol), float(line_tolerance)
    )
    return [tuple(float(v) for v in line) for line in merged]


def merge_region_line_coordinates(
    lines: List[Line4],
    horizontal: bool,
    tolerance: float = 2.3,
) -> List[Line4]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    merged = _pdf_fast.merge_region_line_coordinates(
        owned_lines, bool(horizontal), float(tolerance)
    )
    return [tuple(float(v) for v in line) for line in merged]


def lines_intersect(
    h_line: Line4,
    v_line: Line4,
    tolerance: float = 2.3,
) -> bool:
    return _pdf_fast.lines_intersect(
        tuple(float(v) for v in h_line),
        tuple(float(v) for v in v_line),
        float(tolerance),
    )


def find_table_regions(
    h_lines: List[Line4],
    v_lines: List[Line4],
    tolerance: float = 2.3,
) -> List[Tuple[Dict[str, Any], List[Line4], List[Line4]]]:
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    regions = _pdf_fast.find_table_regions(owned_h, owned_v, float(tolerance))
    res = []
    for bbox, comp_h, comp_v in regions:
        res.append((
            bbox,
            [tuple(float(v) for v in l) for l in comp_h],
            [tuple(float(v) for v in l) for l in comp_v],
        ))
    return res


def snap_coordinates(
    coords: List[float],
    anchor_coords: List[float],
    tol: float = 1.5,
) -> List[float]:
    return _pdf_fast.snap_coordinates(
        [float(c) for c in coords],
        [float(a) for a in anchor_coords],
        float(tol),
    )


def snap_grid_coordinates(
    start: float,
    end: float,
    orthogonal_start: float,
    orthogonal_end: float,
    lines: List[Line4],
    horizontal: bool,
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> List[float]:
    owned_lines = [tuple(float(v) for v in line) for line in lines]
    return _pdf_fast.snap_grid_coordinates(
        float(start),
        float(end),
        float(orthogonal_start),
        float(orthogonal_end),
        owned_lines,
        bool(horizontal),
        float(tolerance),
        float(merge_group_tol),
    )


def complete_partial_outer_boundaries(
    bbox: Dict[str, Any],
    h_lines: List[Line4],
    v_lines: List[Line4],
    h_ys: List[float],
    v_xs: List[float],
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> Tuple[List[Line4], List[Line4]]:
    if "schema_version" not in bbox:
        bbox = {"schema_version": 1, **bbox}
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    eff_h, eff_v = _pdf_fast.complete_partial_outer_boundaries(
        bbox,
        owned_h,
        owned_v,
        [float(y) for y in h_ys],
        [float(x) for x in v_xs],
        float(tolerance),
        float(merge_group_tol),
    )
    return (
        [tuple(float(v) for v in line) for line in eff_h],
        [tuple(float(v) for v in line) for line in eff_v],
    )


def roundtrip_dto(dto_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _pdf_fast.roundtrip_dto(str(dto_type), data)
