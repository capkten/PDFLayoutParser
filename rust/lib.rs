use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyTuple};

pub mod geometry;
pub mod types;
pub mod wired;

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

#[pymodule]
fn _pdf_fast(module: &Bound<'_, PyModule>) -> PyResult<()> {
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
