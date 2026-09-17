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


def build_cells_for_region(
    bbox: Dict[str, Any],
    h_lines: List[Line4],
    v_lines: List[Line4],
    tolerance: float = 2.3,
    merge_group_tol: float = 0.3,
) -> List[Dict[str, Any]]:
    if "schema_version" not in bbox:
        bbox = {"schema_version": 1, **bbox}
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    owned_v = [tuple(float(v) for v in line) for line in v_lines]
    return _pdf_fast.build_cells_for_region(
        bbox,
        owned_h,
        owned_v,
        float(tolerance),
        float(merge_group_tol),
    )


def trim_ghost_edge_rows(
    cells: List[Dict[str, Any]],
    h_lines: List[Line4],
    tol: float = 2.0,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)
    owned_h = [tuple(float(v) for v in line) for line in h_lines]
    return _pdf_fast.trim_ghost_edge_rows(owned_cells, owned_h, float(tol))


def merge_oversegmented_line_columns(
    cells: List[Dict[str, Any]],
    tolerance: float = 2.3,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)
    return _pdf_fast.merge_oversegmented_line_columns(owned_cells, float(tolerance))


def assign_text_to_line_cells(
    cells: List[Dict[str, Any]],
    words: List[Dict[str, Any]],
    chars: Optional[List[Dict[str, Any]]] = None,
    tolerance: float = 2.3,
) -> List[Dict[str, Any]]:
    owned_cells = []
    for c in cells:
        cell_dict = dict(c)
        if "schema_version" not in cell_dict:
            cell_dict["schema_version"] = 1
        if "source" not in cell_dict:
            cell_dict["source"] = None
        rect = cell_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            cell_dict["rect"] = {"schema_version": 1, **rect}
        owned_cells.append(cell_dict)

    owned_words = []
    for w in words:
        w_dict = dict(w)
        if "schema_version" not in w_dict:
            w_dict["schema_version"] = 1
        rect = w_dict["rect"]
        if isinstance(rect, dict) and "schema_version" not in rect:
            w_dict["rect"] = {"schema_version": 1, **rect}
        owned_words.append(w_dict)

    owned_chars = []
    if chars:
        for ch in chars:
            ch_dict = dict(ch)
            if "schema_version" not in ch_dict:
                ch_dict["schema_version"] = 1
            rect = ch_dict["rect"]
            if isinstance(rect, dict) and "schema_version" not in rect:
                ch_dict["rect"] = {"schema_version": 1, **rect}
            owned_chars.append(ch_dict)

    return _pdf_fast.assign_text_to_line_cells(
        owned_cells,
        owned_words,
        owned_chars,
        float(tolerance),
    )


def extract_wired_region(input_data: Dict[str, Any]) -> Dict[str, Any]:
    if "schema_version" not in input_data:
        input_data = {"schema_version": 1, **input_data}
    return _pdf_fast.extract_wired_region(input_data)


def roundtrip_dto(dto_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _pdf_fast.roundtrip_dto(str(dto_type), data)


def rect_overlap(
    a: Dict[str, Any],
    b: Dict[str, Any],
    strict: bool = True,
) -> bool:
    a_dict = dict(a)
    if "schema_version" not in a_dict:
        a_dict["schema_version"] = 1
    b_dict = dict(b)
    if "schema_version" not in b_dict:
        b_dict["schema_version"] = 1
    return _pdf_fast.rect_overlap(a_dict, b_dict, bool(strict))


def filter_regions(
    regions: List[Dict[str, Any]],
    excluded: Optional[List[Dict[str, Any]]] = None,
    allowed: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    owned_regions = []
    for r in regions:
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_regions.append(d)
    owned_excluded = []
    for r in (excluded or []):
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_excluded.append(d)
    owned_allowed = []
    for r in (allowed or []):
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        owned_allowed.append(d)
    return _pdf_fast.filter_regions(owned_regions, owned_excluded, owned_allowed)


def cluster_rows(
    items: List[Dict[str, Any]],
    tolerance: float,
) -> List[Dict[str, Any]]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.cluster_rows(owned_items, float(tolerance))


def cluster_columns(
    items: List[Dict[str, Any]],
    tolerance: float,
) -> List[Dict[str, Any]]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.cluster_columns(owned_items, float(tolerance))


def stable_output_order(
    tables: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    owned_tables = []
    for t in tables:
        d = dict(t)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        cells = d.get("cells", [])
        owned_cells = []
        for c in cells:
            cd = dict(c)
            if "schema_version" not in cd:
                cd["schema_version"] = 1
            cr = cd.get("rect")
            if isinstance(cr, dict) and "schema_version" not in cr:
                cd["rect"] = {"schema_version": 1, **cr}
            owned_cells.append(cd)
        d["cells"] = owned_cells
        owned_tables.append(d)
    return _pdf_fast.stable_output_order(owned_tables)


def build_text_runs(
    spans: List[Dict[str, Any]],
    region: Dict[str, Any],
) -> List[Dict[str, Any]]:
    owned_region = dict(region)
    if "schema_version" not in owned_region:
        owned_region["schema_version"] = 1
    owned_spans = []
    for s in spans:
        d = dict(s)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        sp = d.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            d["source_position"] = {"schema_version": 1, **sp}
        chars = d.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        d["characters"] = owned_chars
        owned_spans.append(d)
    return _pdf_fast.build_text_runs(owned_spans, owned_region)


def build_atoms(
    runs: List[Dict[str, Any]],
    region: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    owned_runs = []
    for r in runs:
        d = dict(r)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_runs.append(d)
    owned_region = None
    if region is not None:
        owned_region = dict(region)
        if "schema_version" not in owned_region:
            owned_region["schema_version"] = 1
    return _pdf_fast.build_atoms(owned_runs, owned_region)


def merge_wrapped_rows(
    atoms: List[Dict[str, Any]],
    tolerance: float = 5.0,
) -> List[Dict[str, Any]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    return _pdf_fast.merge_wrapped_rows(owned_atoms, float(tolerance))


def infer_output_order_mode(
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    owned_items = []
    for it in items:
        d = dict(it)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_items.append(d)
    return _pdf_fast.infer_output_order_mode(owned_items)


def recover_native_candidates(
    input_dto: Dict[str, Any],
) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    page = dict(d["page"])
    if "schema_version" not in page:
        page["schema_version"] = 1
    d["page"] = page
    region = dict(d["region"])
    if "schema_version" not in region:
        region["schema_version"] = 1
    r_rect = region.get("rect")
    if isinstance(r_rect, dict) and "schema_version" not in r_rect:
        region["rect"] = {"schema_version": 1, **r_rect}
    d["region"] = region
    config = dict(d["config"])
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config
    owned_spans = []
    for s in d.get("spans", []):
        sd = dict(s)
        if "schema_version" not in sd:
            sd["schema_version"] = 1
        rect = sd.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            sd["rect"] = {"schema_version": 1, **rect}
        sp = sd.get("source_position")
        if isinstance(sp, dict) and "schema_version" not in sp:
            sd["source_position"] = {"schema_version": 1, **sp}
        chars = sd.get("characters", [])
        owned_chars = []
        for ch in chars:
            ch_d = dict(ch)
            if "schema_version" not in ch_d:
                ch_d["schema_version"] = 1
            ch_rect = ch_d.get("rect")
            if isinstance(ch_rect, dict) and "schema_version" not in ch_rect:
                ch_d["rect"] = {"schema_version": 1, **ch_rect}
            owned_chars.append(ch_d)
        sd["characters"] = owned_chars
        owned_spans.append(sd)
    d["spans"] = owned_spans
    return _pdf_fast.recover_native_candidates(d)


def infer_column_bands(
    atoms: List[Dict[str, Any]],
    region: Dict[str, Any],
) -> List[Dict[str, Any]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    r = dict(region)
    if "schema_version" not in r:
        r["schema_version"] = 1
    return _pdf_fast.infer_column_bands(owned_atoms, r)


def refine_leaf_bands(
    atoms: List[Dict[str, Any]],
    bands: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    owned_bands = []
    for b in bands:
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        owned_bands.append(bd)
    return _pdf_fast.refine_leaf_bands(owned_atoms, owned_bands)


def build_grid(
    atoms: List[Dict[str, Any]],
    bands: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    owned_bands = []
    for b in bands:
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        owned_bands.append(bd)
    return _pdf_fast.build_grid(owned_atoms, owned_bands)


def build_logical_grid(
    atoms: List[Dict[str, Any]],
    grid: Dict[str, Any],
) -> Dict[str, Any]:
    owned_atoms = []
    for a in atoms:
        d = dict(a)
        if "schema_version" not in d:
            d["schema_version"] = 1
        rect = d.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            d["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(d)
    g = dict(grid)
    if "schema_version" not in g:
        g["schema_version"] = 1
    return _pdf_fast.build_logical_grid(owned_atoms, g)


def recover_native_region(
    input_dto: Dict[str, Any],
) -> Dict[str, Any]:
    d = dict(input_dto)
    if "schema_version" not in d:
        d["schema_version"] = 1
    region = dict(d["region"])
    if "schema_version" not in region:
        region["schema_version"] = 1
    r_rect = region.get("rect")
    if isinstance(r_rect, dict) and "schema_version" not in r_rect:
        region["rect"] = {"schema_version": 1, **r_rect}
    d["region"] = region
    config = dict(d["config"])
    if "schema_version" not in config:
        config["schema_version"] = 1
    d["config"] = config
    owned_atoms = []
    for a in d.get("atoms", []):
        ad = dict(a)
        if "schema_version" not in ad:
            ad["schema_version"] = 1
        rect = ad.get("rect")
        if isinstance(rect, dict) and "schema_version" not in rect:
            ad["rect"] = {"schema_version": 1, **rect}
        owned_atoms.append(ad)
    d["atoms"] = owned_atoms
    owned_bands = []
    for b in d.get("bands", []):
        bd = dict(b)
        if "schema_version" not in bd:
            bd["schema_version"] = 1
        owned_bands.append(bd)
    d["bands"] = owned_bands
    return _pdf_fast.recover_native_region(d)
