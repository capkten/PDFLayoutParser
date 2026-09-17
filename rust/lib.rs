use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyTuple};

pub mod geometry;
pub mod native_span;
pub mod types;
pub mod wired;
pub mod wireless_structure;

pub use geometry::Line4;
pub use types::Rect4;

#[pyfunction(name = "merge_h_lines")]
fn merge_h_lines_binding(py: Python<'_>, lines: Vec<Line4>, merge_group_tol: f64) -> Vec<Line4> {
    py.allow_threads(move || geometry::merge_h_lines(lines, merge_group_tol))
}

#[pyfunction(name = "merge_v_lines")]
fn merge_v_lines_binding(
    py: Python<'_>,
    lines: Vec<Line4>,
    h_lines: Vec<Line4>,
    merge_group_tol: f64,
    line_tolerance: f64,
) -> Vec<Line4> {
    py.allow_threads(move || {
        geometry::merge_v_lines(lines, &h_lines, merge_group_tol, line_tolerance)
    })
}

#[pyfunction(name = "merge_region_line_coordinates")]
fn merge_region_line_coordinates_binding(
    py: Python<'_>,
    lines: Vec<Line4>,
    horizontal: bool,
    line_tolerance: f64,
) -> Vec<Line4> {
    py.allow_threads(move || {
        geometry::merge_region_line_coordinates(lines, horizontal, line_tolerance)
    })
}

#[pyfunction(name = "lines_intersect")]
fn lines_intersect_binding(_py: Python<'_>, h_line: Line4, v_line: Line4, tolerance: f64) -> bool {
    geometry::lines_intersect(h_line, v_line, tolerance)
}

#[pyfunction(name = "find_table_regions")]
fn find_table_regions_binding<'py>(
    py: Python<'py>,
    h_lines: Vec<Line4>,
    v_lines: Vec<Line4>,
    tolerance: f64,
) -> PyResult<Bound<'py, PyList>> {
    let regions = py.allow_threads(move || wired::find_table_regions(h_lines, v_lines, tolerance));
    let list = PyList::empty_bound(py);
    for (bbox, comp_h, comp_v) in regions {
        let bbox_dict = bbox.to_py(py)?;
        let tuple = PyTuple::new_bound(
            py,
            &[
                bbox_dict.into_any(),
                comp_h.into_py(py).into_bound(py),
                comp_v.into_py(py).into_bound(py),
            ],
        );
        list.append(tuple)?;
    }
    Ok(list)
}

#[pyfunction(name = "snap_coordinates")]
fn snap_coordinates_binding(
    py: Python<'_>,
    coords: Vec<f64>,
    anchor_coords: Vec<f64>,
    tol: f64,
) -> Vec<f64> {
    py.allow_threads(move || geometry::snap_coordinates(coords, &anchor_coords, tol))
}

#[pyfunction(name = "snap_grid_coordinates")]
fn snap_grid_coordinates_binding(
    py: Python<'_>,
    start: f64,
    end: f64,
    orthogonal_start: f64,
    orthogonal_end: f64,
    lines: Vec<Line4>,
    horizontal: bool,
    tolerance: f64,
    merge_group_tol: f64,
) -> Vec<f64> {
    py.allow_threads(move || {
        geometry::snap_grid_coordinates(
            start,
            end,
            orthogonal_start,
            orthogonal_end,
            &lines,
            horizontal,
            tolerance,
            merge_group_tol,
        )
    })
}

#[pyfunction(name = "complete_partial_outer_boundaries")]
fn complete_partial_outer_boundaries_binding<'py>(
    py: Python<'py>,
    bbox: &Bound<'py, PyDict>,
    h_lines: Vec<Line4>,
    v_lines: Vec<Line4>,
    h_ys: Vec<f64>,
    v_xs: Vec<f64>,
    line_tolerance: f64,
    merge_group_tol: f64,
) -> PyResult<(Vec<Line4>, Vec<Line4>)> {
    let rect = Rect4::from_py(bbox)?;
    let res = py.allow_threads(move || {
        wired::complete_partial_outer_boundaries(
            rect,
            h_lines,
            v_lines,
            h_ys,
            v_xs,
            line_tolerance,
            merge_group_tol,
        )
    });
    Ok(res)
}

#[pyfunction(name = "build_cells_for_region")]
fn build_cells_for_region_binding<'py>(
    py: Python<'py>,
    bbox: &Bound<'py, PyDict>,
    h_lines: Vec<Line4>,
    v_lines: Vec<Line4>,
    line_tolerance: f64,
    merge_group_tol: f64,
) -> PyResult<Bound<'py, PyList>> {
    let rect = Rect4::from_py(bbox)?;
    let cells = py.allow_threads(move || {
        wired::build_cells_for_region(rect, h_lines, v_lines, line_tolerance, merge_group_tol)
    });
    let list = PyList::empty_bound(py);
    for cell in cells {
        list.append(cell.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "trim_ghost_edge_rows")]
fn trim_ghost_edge_rows_binding<'py>(
    py: Python<'py>,
    cells: &Bound<'py, PyList>,
    h_lines: Vec<Line4>,
    tol: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_cells = Vec::new();
    for item in cells.iter() {
        rust_cells.push(types::CellDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }
    let trimmed = py.allow_threads(move || wired::trim_ghost_edge_rows(rust_cells, &h_lines, tol));
    let list = PyList::empty_bound(py);
    for cell in trimmed {
        list.append(cell.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "merge_oversegmented_line_columns")]
fn merge_oversegmented_line_columns_binding<'py>(
    py: Python<'py>,
    cells: &Bound<'py, PyList>,
    line_tolerance: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_cells = Vec::new();
    for item in cells.iter() {
        rust_cells.push(types::CellDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }
    let merged = py
        .allow_threads(move || wired::merge_oversegmented_line_columns(rust_cells, line_tolerance));
    let list = PyList::empty_bound(py);
    for cell in merged {
        list.append(cell.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "assign_text_to_line_cells")]
fn assign_text_to_line_cells_binding<'py>(
    py: Python<'py>,
    cells: &Bound<'py, PyList>,
    words: &Bound<'py, PyList>,
    chars: &Bound<'py, PyList>,
    tolerance: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_cells = Vec::new();
    for item in cells.iter() {
        rust_cells.push(types::CellDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }
    let mut rust_words = Vec::new();
    for item in words.iter() {
        rust_words.push(types::WordDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }
    let mut rust_chars = Vec::new();
    for item in chars.iter() {
        rust_chars.push(types::CharacterDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }

    let assigned = py.allow_threads(move || {
        wired::assign_text_to_line_cells(rust_cells, &rust_words, &rust_chars, tolerance)
    });
    let list = PyList::empty_bound(py);
    for cell in assigned {
        list.append(cell.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "extract_wired_region")]
fn extract_wired_region_binding<'py>(
    py: Python<'py>,
    input: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input_dto = types::WiredRegionInput::from_py(input)?;
    let output_dto = py.allow_threads(move || wired::extract_wired_region(input_dto));
    output_dto.to_py(py)
}

#[pyfunction(name = "roundtrip_dto")]
fn roundtrip_dto_binding<'py>(
    py: Python<'py>,
    dto_type: &str,
    data: &Bound<'py, pyo3::types::PyDict>,
) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
    types::roundtrip_dto_py(py, dto_type, data)
}

#[pyfunction(name = "rect_overlap")]
fn rect_overlap_binding<'py>(
    _py: Python<'py>,
    a: &Bound<'py, PyDict>,
    b: &Bound<'py, PyDict>,
    strict: bool,
) -> PyResult<bool> {
    let ra = Rect4::from_py(a)?;
    let rb = Rect4::from_py(b)?;
    Ok(geometry::rect_overlap(&ra, &rb, strict))
}

#[pyfunction(name = "filter_regions")]
fn filter_regions_binding<'py>(
    py: Python<'py>,
    regions: &Bound<'py, PyList>,
    excluded: &Bound<'py, PyList>,
    allowed: &Bound<'py, PyList>,
) -> PyResult<Bound<'py, PyList>> {
    let mut reg_vec = Vec::with_capacity(regions.len());
    for item in regions.iter() {
        reg_vec.push(Rect4::from_py(&item.downcast::<PyDict>()?.clone())?);
    }
    let mut ex_vec = Vec::with_capacity(excluded.len());
    for item in excluded.iter() {
        ex_vec.push(Rect4::from_py(&item.downcast::<PyDict>()?.clone())?);
    }
    let mut al_vec = Vec::with_capacity(allowed.len());
    for item in allowed.iter() {
        al_vec.push(Rect4::from_py(&item.downcast::<PyDict>()?.clone())?);
    }
    let res = py.allow_threads(move || geometry::filter_regions(reg_vec, ex_vec, al_vec));
    let list = PyList::empty_bound(py);
    for r in res {
        list.append(r.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "cluster_rows")]
fn cluster_rows_binding<'py>(
    py: Python<'py>,
    items: &Bound<'py, PyList>,
    tolerance: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut item_vec = Vec::with_capacity(items.len());
    for item in items.iter() {
        item_vec.push(types::OrderedRectDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }
    let clusters = py.allow_threads(move || geometry::cluster_rows(item_vec, tolerance));
    let list = PyList::empty_bound(py);
    for c in clusters {
        list.append(c.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "cluster_columns")]
fn cluster_columns_binding<'py>(
    py: Python<'py>,
    items: &Bound<'py, PyList>,
    tolerance: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut item_vec = Vec::with_capacity(items.len());
    for item in items.iter() {
        item_vec.push(types::OrderedRectDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }
    let clusters = py.allow_threads(move || geometry::cluster_columns(item_vec, tolerance));
    let list = PyList::empty_bound(py);
    for c in clusters {
        list.append(c.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "stable_output_order")]
fn stable_output_order_binding<'py>(
    py: Python<'py>,
    tables: &Bound<'py, PyList>,
) -> PyResult<Bound<'py, PyList>> {
    let mut table_vec = Vec::with_capacity(tables.len());
    for item in tables.iter() {
        table_vec.push(types::TableCandidateDto::from_py(
            &item.downcast::<PyDict>()?.clone(),
        )?);
    }
    let ordered = py.allow_threads(move || geometry::stable_output_order(table_vec));
    let list = PyList::empty_bound(py);
    for t in ordered {
        list.append(t.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "build_text_runs")]
fn build_text_runs_binding<'py>(
    py: Python<'py>,
    spans: &Bound<'py, PyList>,
    region: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_spans = Vec::with_capacity(spans.len());
    for s in spans.iter() {
        rust_spans.push(types::NativeSpanDto::from_py(
            &s.downcast::<PyDict>()?.clone(),
        )?);
    }
    let rust_region = Rect4::from_py(region)?;
    let runs = py.allow_threads(move || native_span::build_text_runs(rust_spans, rust_region));
    let list = PyList::empty_bound(py);
    for r in runs {
        list.append(r.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "build_atoms")]
#[pyo3(signature = (runs, region=None))]
fn build_atoms_binding<'py>(
    py: Python<'py>,
    runs: &Bound<'py, PyList>,
    region: Option<&Bound<'py, PyDict>>,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_runs = Vec::with_capacity(runs.len());
    for r in runs.iter() {
        rust_runs.push(types::TextRunDto::from_py(
            &r.downcast::<PyDict>()?.clone(),
        )?);
    }
    let rust_region = match region {
        Some(dict) => Some(Rect4::from_py(dict)?),
        None => None,
    };
    let atoms = py.allow_threads(move || native_span::build_atoms(rust_runs, rust_region));
    let list = PyList::empty_bound(py);
    for a in atoms {
        list.append(a.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "merge_wrapped_rows")]
#[pyo3(signature = (atoms, tolerance=5.0))]
fn merge_wrapped_rows_binding<'py>(
    py: Python<'py>,
    atoms: &Bound<'py, PyList>,
    tolerance: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_atoms = Vec::with_capacity(atoms.len());
    for a in atoms.iter() {
        rust_atoms.push(types::AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
    }
    let merged = py.allow_threads(move || native_span::merge_wrapped_rows(rust_atoms, tolerance));
    let list = PyList::empty_bound(py);
    for a in merged {
        list.append(a.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "infer_output_order_mode")]
fn infer_output_order_mode_binding<'py>(
    py: Python<'py>,
    items: &Bound<'py, PyList>,
) -> PyResult<Bound<'py, PyDict>> {
    let mut rust_atoms = Vec::with_capacity(items.len());
    for item in items.iter() {
        let dict = item.downcast::<PyDict>()?;
        let rect = Rect4::from_py(&types::get_req(dict, "rect")?.downcast::<PyDict>()?.clone())?;
        let order: i64 = types::get_req(dict, "order")?.extract()?;
        rust_atoms.push(types::AtomDto {
            schema_version: 1,
            text: String::new(),
            rect,
            run_refs: Vec::new(),
            row_hint: None,
            col_hint: None,
            order,
        });
    }
    let mode = py.allow_threads(move || native_span::infer_output_order_mode(rust_atoms));
    mode.to_py(py)
}

#[pyfunction(name = "recover_native_candidates")]
fn recover_native_candidates_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input = types::NativeRecoveryInput::from_py(input_dict)?;
    let output = py.allow_threads(move || native_span::recover_native_candidates(input));
    output.to_py(py)
}

#[pyfunction(name = "infer_column_bands")]
fn infer_column_bands_binding<'py>(
    py: Python<'py>,
    atoms: &Bound<'py, PyList>,
    region: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_atoms = Vec::with_capacity(atoms.len());
    for a in atoms.iter() {
        rust_atoms.push(types::AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
    }
    let rust_region = Rect4::from_py(region)?;
    let bands =
        py.allow_threads(move || wireless_structure::infer_column_bands(rust_atoms, rust_region));
    let list = PyList::empty_bound(py);
    for b in bands {
        list.append(b.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "refine_leaf_bands")]
fn refine_leaf_bands_binding<'py>(
    py: Python<'py>,
    atoms: &Bound<'py, PyList>,
    bands: &Bound<'py, PyList>,
) -> PyResult<(Bound<'py, PyList>, Option<f64>)> {
    let mut rust_atoms = Vec::with_capacity(atoms.len());
    for a in atoms.iter() {
        rust_atoms.push(types::AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
    }
    let mut rust_bands = Vec::with_capacity(bands.len());
    for b in bands.iter() {
        rust_bands.push(types::ColumnBandDto::from_py(
            &b.downcast::<PyDict>()?.clone(),
        )?);
    }
    let (refined, cutoff) =
        py.allow_threads(move || wireless_structure::refine_leaf_bands(rust_atoms, rust_bands));
    let list = PyList::empty_bound(py);
    for b in refined {
        list.append(b.to_py(py)?)?;
    }
    Ok((list, cutoff))
}

#[pyfunction(name = "build_grid")]
fn build_grid_binding<'py>(
    py: Python<'py>,
    atoms: &Bound<'py, PyList>,
    bands: &Bound<'py, PyList>,
) -> PyResult<(
    Bound<'py, PyList>,
    Bound<'py, PyList>,
    Bound<'py, PyList>,
    Bound<'py, PyList>,
)> {
    let mut rust_atoms = Vec::with_capacity(atoms.len());
    for a in atoms.iter() {
        rust_atoms.push(types::AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
    }
    let mut rust_bands = Vec::with_capacity(bands.len());
    for b in bands.iter() {
        rust_bands.push(types::ColumnBandDto::from_py(
            &b.downcast::<PyDict>()?.clone(),
        )?);
    }
    let (rows, bands_out, cells, diags) =
        py.allow_threads(move || wireless_structure::build_grid(rust_atoms, rust_bands));
    let rows_list = PyList::empty_bound(py);
    for r in rows {
        rows_list.append(r.to_py(py)?)?;
    }
    let bands_list = PyList::empty_bound(py);
    for b in bands_out {
        bands_list.append(b.to_py(py)?)?;
    }
    let cells_list = PyList::empty_bound(py);
    for c in cells {
        cells_list.append(c.to_py(py)?)?;
    }
    let diags_list = PyList::empty_bound(py);
    for d in diags {
        diags_list.append(d.to_py(py)?)?;
    }
    Ok((rows_list, bands_list, cells_list, diags_list))
}

#[pyfunction(name = "build_logical_grid")]
fn build_logical_grid_binding<'py>(
    py: Python<'py>,
    atoms: &Bound<'py, PyList>,
    grid: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let mut rust_atoms = Vec::with_capacity(atoms.len());
    for a in atoms.iter() {
        rust_atoms.push(types::AtomDto::from_py(&a.downcast::<PyDict>()?.clone())?);
    }
    let rust_grid = types::GridDto::from_py(grid)?;
    let logical =
        py.allow_threads(move || wireless_structure::build_logical_grid(rust_atoms, rust_grid));
    logical.to_py(py)
}

#[pyfunction(name = "recover_native_region")]
fn recover_native_region_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input = types::NativeRegionInput::from_py(input_dict)?;
    let output = py.allow_threads(move || wireless_structure::recover_native_region(input));
    output.to_py(py)
}

#[pyfunction(name = "table_quality")]
fn table_quality_binding<'py>(_py: Python<'py>, candidate: &Bound<'py, PyDict>) -> PyResult<f64> {
    let cand = types::TableCandidateDto::from_py(candidate)?;
    Ok(wireless_structure::table_quality(&cand))
}

#[pyfunction(name = "select_candidates")]
fn select_candidates_binding<'py>(
    py: Python<'py>,
    candidates: &Bound<'py, PyList>,
    excluded: &Bound<'py, PyList>,
    allowed: &Bound<'py, PyList>,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_candidates = Vec::with_capacity(candidates.len());
    for c in candidates.iter() {
        rust_candidates.push(types::TableCandidateDto::from_py(
            &c.downcast::<PyDict>()?.clone(),
        )?);
    }
    let mut rust_excluded = Vec::with_capacity(excluded.len());
    for e in excluded.iter() {
        rust_excluded.push(types::Rect4::from_py(&e.downcast::<PyDict>()?.clone())?);
    }
    let mut rust_allowed = Vec::with_capacity(allowed.len());
    for a in allowed.iter() {
        rust_allowed.push(types::Rect4::from_py(&a.downcast::<PyDict>()?.clone())?);
    }
    let selected = py.allow_threads(move || {
        wireless_structure::select_candidates(rust_candidates, rust_excluded, rust_allowed)
    });
    let list = PyList::empty_bound(py);
    for s in selected {
        list.append(s.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "recover_wireless_tables")]
fn recover_wireless_tables_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input = types::WirelessRecoveryInput::from_py(input_dict)?;
    let output = py.allow_threads(move || wireless_structure::recover_wireless_tables(input));
    output.to_py(py)
}

#[pymodule]
fn _pdf_fast(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(rect_overlap_binding, module)?)?;
    module.add_function(wrap_pyfunction!(filter_regions_binding, module)?)?;
    module.add_function(wrap_pyfunction!(cluster_rows_binding, module)?)?;
    module.add_function(wrap_pyfunction!(cluster_columns_binding, module)?)?;
    module.add_function(wrap_pyfunction!(stable_output_order_binding, module)?)?;
    module.add_function(wrap_pyfunction!(build_text_runs_binding, module)?)?;
    module.add_function(wrap_pyfunction!(build_atoms_binding, module)?)?;
    module.add_function(wrap_pyfunction!(merge_wrapped_rows_binding, module)?)?;
    module.add_function(wrap_pyfunction!(infer_output_order_mode_binding, module)?)?;
    module.add_function(wrap_pyfunction!(recover_native_candidates_binding, module)?)?;
    module.add_function(wrap_pyfunction!(infer_column_bands_binding, module)?)?;
    module.add_function(wrap_pyfunction!(refine_leaf_bands_binding, module)?)?;
    module.add_function(wrap_pyfunction!(build_grid_binding, module)?)?;
    module.add_function(wrap_pyfunction!(build_logical_grid_binding, module)?)?;
    module.add_function(wrap_pyfunction!(recover_native_region_binding, module)?)?;
    module.add_function(wrap_pyfunction!(table_quality_binding, module)?)?;
    module.add_function(wrap_pyfunction!(select_candidates_binding, module)?)?;
    module.add_function(wrap_pyfunction!(recover_wireless_tables_binding, module)?)?;
    module.add_function(wrap_pyfunction!(merge_h_lines_binding, module)?)?;
    module.add_function(wrap_pyfunction!(merge_v_lines_binding, module)?)?;
    module.add_function(wrap_pyfunction!(
        merge_region_line_coordinates_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(lines_intersect_binding, module)?)?;
    module.add_function(wrap_pyfunction!(find_table_regions_binding, module)?)?;
    module.add_function(wrap_pyfunction!(snap_coordinates_binding, module)?)?;
    module.add_function(wrap_pyfunction!(snap_grid_coordinates_binding, module)?)?;
    module.add_function(wrap_pyfunction!(
        complete_partial_outer_boundaries_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(build_cells_for_region_binding, module)?)?;
    module.add_function(wrap_pyfunction!(trim_ghost_edge_rows_binding, module)?)?;
    module.add_function(wrap_pyfunction!(
        merge_oversegmented_line_columns_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(assign_text_to_line_cells_binding, module)?)?;
    module.add_function(wrap_pyfunction!(extract_wired_region_binding, module)?)?;
    module.add_function(wrap_pyfunction!(roundtrip_dto_binding, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::geometry::merge_h_lines;

    #[test]
    fn groups_nearby_lines_and_merges_segments() {
        assert_eq!(
            merge_h_lines(vec![(0.0, 10.0, 10.0, 10.0), (10.5, 10.2, 20.0, 10.2)], 0.3),
            vec![(0.0, 10.1, 20.0, 10.1)]
        );
    }

    #[test]
    fn keeps_segments_separated_by_more_than_three_points() {
        assert_eq!(
            merge_h_lines(vec![(0.0, 10.0, 10.0, 10.0), (14.0, 10.0, 20.0, 10.0)], 0.3),
            vec![(0.0, 10.0, 10.0, 10.0), (14.0, 10.0, 20.0, 10.0)]
        );
    }

    #[test]
    fn returns_empty_for_empty_input() {
        assert_eq!(merge_h_lines(vec![], 0.3), vec![]);
    }

    #[test]
    fn uses_python_decimal_rounding_for_sort_keys() {
        assert_eq!(
            merge_h_lines(vec![(10.0, 1.15, 11.0, 1.15), (0.0, 1.2, 1.0, 1.2)], 0.0),
            vec![(10.0, 1.15, 11.0, 1.15), (0.0, 1.2, 1.0, 1.2)]
        );
    }

    #[test]
    fn preserves_python_half_value_sort_order() {
        assert_eq!(
            merge_h_lines(vec![(10.0, 2.25, 11.0, 2.25), (0.0, 2.3, 1.0, 2.3)], 0.0),
            vec![(10.0, 2.25, 11.0, 2.25), (0.0, 2.3, 1.0, 2.3)]
        );
    }

    #[test]
    fn preserves_input_order_when_rounded_y_comparison_is_nan() {
        let output = merge_h_lines(
            vec![(10.0, f64::NAN, 11.0, f64::NAN), (0.0, 1.2, 1.0, 1.2)],
            0.0,
        );

        assert_eq!(output.len(), 2);
        assert_eq!(output[0].0, 10.0);
        assert!(output[0].1.is_nan());
        assert_eq!(output[1].0, 0.0);
        assert_eq!(output[1].1, 1.2);
    }
}
