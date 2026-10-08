use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyTuple};

pub mod english_wireless;
pub mod geometry;
pub mod native_span;
pub mod personal_credit;
mod pdfium_api;
pub mod snapshot;
pub mod table_normalization;
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

#[pyfunction(name = "recover_personal_credit_tables")]
fn recover_personal_credit_tables_binding<'py>(
    py: Python<'py>,
    input: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input_dto = types::PersonalCreditInput::from_py(input)?;
    let output_dto = py.allow_threads(move || personal_credit::recover(input_dto));
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

fn canonical_digest<'py>(py: Python<'py>, data: &Bound<'py, PyDict>) -> PyResult<String> {
    let json = PyModule::import_bound(py, "json")?;
    let kwargs = PyDict::new_bound(py);
    kwargs.set_item("ensure_ascii", false)?;
    kwargs.set_item("sort_keys", true)?;
    kwargs.set_item("separators", PyTuple::new_bound(py, [",", ":"]))?;
    kwargs.set_item("allow_nan", false)?;
    let encoded: String = json
        .getattr("dumps")?
        .call((data,), Some(&kwargs))?
        .extract()?;

    let hashlib = PyModule::import_bound(py, "hashlib")?;
    let digest: String = hashlib
        .getattr("sha256")?
        .call1((PyBytes::new_bound(py, encoded.as_bytes()),))?
        .getattr("hexdigest")?
        .call0()?
        .extract()?;
    Ok(digest)
}

fn parse_region_item(item: &Bound<'_, pyo3::PyAny>) -> PyResult<Rect4> {
    if let Ok(dict) = item.downcast::<PyDict>() {
        Rect4::from_py(dict)
    } else if let Ok(tuple) = item.extract::<(f64, f64, f64, f64)>() {
        Ok(Rect4 {
            schema_version: 1,
            x0: tuple.0,
            y0: tuple.1,
            x1: tuple.2,
            y1: tuple.3,
        })
    } else if let (Ok(x0), Ok(y0), Ok(x1), Ok(y1)) = (
        item.getattr("x0").and_then(|v| v.extract::<f64>()),
        item.getattr("y0").and_then(|v| v.extract::<f64>()),
        item.getattr("x1").and_then(|v| v.extract::<f64>()),
        item.getattr("y1").and_then(|v| v.extract::<f64>()),
    ) {
        Ok(Rect4 {
            schema_version: 1,
            x0,
            y0,
            x1,
            y1,
        })
    } else {
        Err(pyo3::exceptions::PyValueError::new_err(
            "Region item must be a dict, 4-tuple, or have x0, y0, x1, y1 attributes",
        ))
    }
}

fn parse_region_list(list_opt: Option<&Bound<'_, PyList>>) -> PyResult<Option<Vec<Rect4>>> {
    match list_opt {
        Some(list) => {
            let mut rects = Vec::with_capacity(list.len());
            for item in list.iter() {
                rects.push(parse_region_item(&item)?);
            }
            Ok(Some(rects))
        }
        None => Ok(None),
    }
}

#[pyfunction(name = "collect_native_spans_from_snapshot")]
#[pyo3(signature = (snapshot_dict, allowed_regions=None, excluded_regions=None))]
fn collect_native_spans_from_snapshot_binding<'py>(
    py: Python<'py>,
    snapshot_dict: &Bound<'py, PyDict>,
    allowed_regions: Option<&Bound<'py, PyList>>,
    excluded_regions: Option<&Bound<'py, PyList>>,
) -> PyResult<Bound<'py, PyList>> {
    let snapshot = types::PageSnapshotDto::from_py(snapshot_dict)?;
    let allowed = parse_region_list(allowed_regions)?;
    let excluded = parse_region_list(excluded_regions)?;

    let spans = snapshot::collect_native_spans_from_snapshot(
        &snapshot,
        allowed.as_deref(),
        excluded.as_deref(),
    );

    let result = PyList::empty_bound(py);
    for s in spans {
        result.append(s.to_py(py)?)?;
    }
    Ok(result)
}

#[pyfunction(name = "collect_native_spans_from_rawdict")]
#[pyo3(signature = (rawdict, page_height, page_y0=0.0, allowed_regions=None, excluded_regions=None))]
fn collect_native_spans_from_rawdict_binding<'py>(
    py: Python<'py>,
    rawdict: &Bound<'py, PyDict>,
    page_height: f64,
    page_y0: f64,
    allowed_regions: Option<&Bound<'py, PyList>>,
    excluded_regions: Option<&Bound<'py, PyList>>,
) -> PyResult<Bound<'py, PyList>> {
    let allowed = parse_region_list(allowed_regions)?;
    let excluded = parse_region_list(excluded_regions)?;

    let spans = snapshot::collect_native_spans_from_rawdict(
        rawdict,
        page_height,
        page_y0,
        allowed.as_deref(),
        excluded.as_deref(),
    )?;

    let result = PyList::empty_bound(py);
    for s in spans {
        result.append(s.to_py(py)?)?;
    }
    Ok(result)
}

#[pyfunction(name = "recover_wireless_tables_from_rawdict")]
#[pyo3(signature = (rawdict, page_info, page_y0=0.0, allowed_regions=None, excluded_regions=None, config=None))]
fn recover_wireless_tables_from_rawdict_binding<'py>(
    py: Python<'py>,
    rawdict: &Bound<'py, PyDict>,
    page_info: (f64, f64, i64),
    page_y0: f64,
    allowed_regions: Option<&Bound<'py, PyList>>,
    excluded_regions: Option<&Bound<'py, PyList>>,
    config: Option<(f64, f64, f64, f64, f64)>,
) -> PyResult<Bound<'py, PyDict>> {
    let allowed = parse_region_list(allowed_regions)?;
    let excluded = parse_region_list(excluded_regions)?;

    let page_width = page_info.0;
    let page_height = page_info.1;
    let rotation = page_info.2;

    let spans_input = snapshot::collect_native_spans_from_rawdict(
        rawdict,
        page_height,
        page_y0,
        allowed.as_deref(),
        excluded.as_deref(),
    )?;

    let page = types::PageDto {
        schema_version: 1,
        width: page_width,
        height: page_height,
        rotation,
    };

    let spans: Vec<types::NativeSpanDto> = spans_input.into_iter().map(|item| item.span).collect();

    let mut regions = Vec::new();
    if let Some(ref al) = allowed {
        for (idx, r) in al.iter().enumerate() {
            regions.push(types::RegionDto {
                schema_version: 1,
                rect: r.clone(),
                source_order: idx as i64,
                allowed: true,
            });
        }
    }
    if let Some(ref ex) = excluded {
        let base_idx = regions.len();
        for (idx, r) in ex.iter().enumerate() {
            regions.push(types::RegionDto {
                schema_version: 1,
                rect: r.clone(),
                source_order: (base_idx + idx) as i64,
                allowed: false,
            });
        }
    }

    let cfg = match config {
        Some(c) => types::StructureConfig {
            schema_version: 1,
            line_tolerance: c.0,
            row_tolerance: c.1,
            column_tolerance: c.2,
            span_tolerance: c.3,
            numeric_tolerance: c.4,
        },
        None => types::StructureConfig {
            schema_version: 1,
            line_tolerance: 2.0,
            row_tolerance: 2.0,
            column_tolerance: 2.0,
            span_tolerance: 2.0,
            numeric_tolerance: 2.0,
        },
    };

    let input = types::WirelessRecoveryInput {
        schema_version: 1,
        page,
        spans,
        regions,
        config: cfg,
    };

    let output = py.allow_threads(move || wireless_structure::recover_wireless_tables(input));
    output.to_py(py)
}

#[pyfunction(name = "recover_cells_from_snapshot")]
fn recover_cells_from_snapshot_binding<'py>(
    py: Python<'py>,
    snapshot_dict: &Bound<'py, PyDict>,
    region_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let snapshot = types::PageSnapshotDto::from_py(snapshot_dict)?;
    let region = types::Rect4::from_py(region_dict)?;
    let output = wireless_structure::recover_cells_from_snapshot(&snapshot, &region);
    output.to_py(py)
}

#[pyfunction(name = "page_snapshot_digest")]
fn page_snapshot_digest_binding<'py>(
    py: Python<'py>,
    data: &Bound<'py, PyDict>,
) -> PyResult<String> {
    types::PageSnapshotDto::from_py(data)?;
    canonical_digest(py, data)
}

#[pyfunction(name = "stage_input_digest")]
fn stage_input_digest_binding<'py>(
    py: Python<'py>,
    data: &Bound<'py, PyDict>,
) -> PyResult<String> {
    types::OwnedValue::from_py(data.as_any(), "stage")?;
    canonical_digest(py, data)
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
    let runs_for_build = rust_runs.clone();
    let atoms = py.allow_threads(move || native_span::build_atoms(runs_for_build, rust_region));
    let list = PyList::empty_bound(py);
    for (a, run) in atoms.into_iter().zip(rust_runs.iter()) {
        let atom = a.to_py(py)?;
        if let (Some(flow_start), Some(flow_end), Some(evidence)) = (
            run.flow_start,
            run.flow_end,
            run.evidence.as_ref(),
        ) {
            if !evidence.source_positions.is_empty() {
                let mut source_blocks: Vec<i64> = evidence
                    .source_positions
                    .iter()
                    .map(|position| position.block)
                    .collect();
                source_blocks.sort_unstable();
                source_blocks.dedup();
                let source_line_start = evidence
                    .source_positions
                    .iter()
                    .map(|position| position.line)
                    .min()
                    .unwrap();
                let source_line_end = evidence
                    .source_positions
                    .iter()
                    .map(|position| position.line)
                    .max()
                    .unwrap();
                atom.set_item("flow_start", flow_start)?;
                atom.set_item("flow_end", flow_end)?;
                atom.set_item("source_blocks", source_blocks)?;
                atom.set_item("source_line_start", source_line_start)?;
                atom.set_item("source_line_end", source_line_end)?;
                atom.set_item("source_position_known", true)?;
            }
        }
        list.append(atom)?;
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
            col_end_hint: None,
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

#[pyfunction(name = "recover_wireless_tables_packed")]
#[pyo3(signature = (page_info, regions_flat, config, spans_num, spans_text, spans_font, chars_num, chars_text=None))]
fn recover_wireless_tables_packed_binding<'py>(
    py: Python<'py>,
    page_info: (f64, f64, i64),
    regions_flat: Vec<(f64, f64, f64, f64, bool)>,
    config: (f64, f64, f64, f64, f64),
    spans_num: Vec<f64>,
    spans_text: Vec<String>,
    spans_font: Vec<Option<String>>,
    chars_num: Vec<f64>,
    chars_text: Option<Vec<String>>,
) -> PyResult<Bound<'py, PyDict>> {
    let page = types::PageDto {
        schema_version: 1,
        width: page_info.0,
        height: page_info.1,
        rotation: page_info.2,
    };
    let mut regions = Vec::with_capacity(regions_flat.len());
    for (idx, (x0, y0, x1, y1, allowed)) in regions_flat.into_iter().enumerate() {
        regions.push(types::RegionDto {
            schema_version: 1,
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            source_order: idx as i64,
            allowed,
        });
    }
    let config = types::StructureConfig {
        schema_version: 1,
        line_tolerance: config.0,
        row_tolerance: config.1,
        column_tolerance: config.2,
        span_tolerance: config.3,
        numeric_tolerance: config.4,
    };
    let span_count = spans_num.len() / 10;
    let mut spans = Vec::with_capacity(span_count);
    for i in 0..span_count {
        let base = i * 10;
        let x0 = spans_num[base];
        let y0 = spans_num[base + 1];
        let x1 = spans_num[base + 2];
        let y1 = spans_num[base + 3];
        let size = spans_num[base + 4];
        let order = spans_num[base + 5] as i64;
        let block = spans_num[base + 6] as i64;
        let line = spans_num[base + 7] as i64;
        let char_start = spans_num[base + 8] as usize;
        let char_count = spans_num[base + 9] as usize;

        let text = spans_text.get(i).cloned().unwrap_or_default();
        let font = spans_font.get(i).cloned().flatten();
        let char_chars: Vec<char> = text.chars().collect();

        let mut characters = Vec::with_capacity(char_count);
        for c_idx in 0..char_count {
            let c_base = (char_start + c_idx) * 5;
            if c_base + 4 < chars_num.len() {
                let cx0 = chars_num[c_base];
                let cy0 = chars_num[c_base + 1];
                let cx1 = chars_num[c_base + 2];
                let cy1 = chars_num[c_base + 3];
                let c_order = chars_num[c_base + 4] as i64;
                let c_text = if let Some(ref ct) = chars_text {
                    ct.get(char_start + c_idx).cloned().unwrap_or_default()
                } else if c_idx < char_chars.len() {
                    char_chars[c_idx].to_string()
                } else {
                    String::new()
                };
                characters.push(types::CharacterDto {
                    schema_version: 1,
                    text: c_text,
                    rect: Rect4 {
                        schema_version: 1,
                        x0: cx0,
                        y0: cy0,
                        x1: cx1,
                        y1: cy1,
                    },
                    order: c_order,
                });
            }
        }
        spans.push(types::NativeSpanDto {
            schema_version: 1,
            text,
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            font,
            size: if size > 0.0 { Some(size) } else { None },
            flags: Some(0),
            order,
            characters,
            source_position: types::SourcePositionDto {
                schema_version: 1,
                block,
                line,
            },
            block,
            line,
        });
    }
    let input = types::WirelessRecoveryInput {
        schema_version: 1,
        page,
        spans,
        regions,
        config,
    };
    let output = py.allow_threads(move || wireless_structure::recover_wireless_tables(input));
    output.to_py(py)
}

#[pyfunction(name = "group_backgrounds")]
fn group_backgrounds_binding<'py>(
    py: Python<'py>,
    backgrounds: &Bound<'py, PyList>,
    gap_threshold: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_bgs = Vec::with_capacity(backgrounds.len());
    for b in backgrounds.iter() {
        rust_bgs.push(types::BackgroundDto::from_py(
            &b.downcast::<PyDict>()?.clone(),
        )?);
    }
    let groups =
        py.allow_threads(move || english_wireless::group_backgrounds(rust_bgs, gap_threshold));
    let outer_list = PyList::empty_bound(py);
    for group in groups {
        let inner_list = PyList::empty_bound(py);
        for bg in group {
            inner_list.append(bg.to_py(py)?)?;
        }
        outer_list.append(inner_list)?;
    }
    Ok(outer_list)
}

#[pyfunction(name = "detect_zebra_rows")]
fn detect_zebra_rows_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    let input = types::ZebraInput::from_py(input_dict)?;
    let rows = py.allow_threads(move || english_wireless::detect_zebra_rows(&input));
    let list = PyList::empty_bound(py);
    for r in rows {
        list.append(r.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "assign_words_to_zebra_rows")]
fn assign_words_to_zebra_rows_binding<'py>(
    py: Python<'py>,
    words: &Bound<'py, PyList>,
    rows: &Bound<'py, PyList>,
    row_tol: f64,
) -> PyResult<Bound<'py, PyList>> {
    let mut rust_words = Vec::with_capacity(words.len());
    for w in words.iter() {
        rust_words.push(types::WordDto::from_py(&w.downcast::<PyDict>()?.clone())?);
    }
    let mut rust_rows = Vec::with_capacity(rows.len());
    for r in rows.iter() {
        rust_rows.push(types::RowBandDto::from_py(
            &r.downcast::<PyDict>()?.clone(),
        )?);
    }
    let assigned = py.allow_threads(move || {
        english_wireless::assign_words_to_zebra_rows(rust_words, rust_rows, row_tol)
    });
    let list = PyList::empty_bound(py);
    for r in assigned {
        list.append(r.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "infer_english_columns")]
fn infer_english_columns_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    let input = types::EnglishGridInput::from_py(input_dict)?;
    let cols = py.allow_threads(move || english_wireless::infer_english_columns(&input));
    let list = PyList::empty_bound(py);
    for c in cols {
        list.append(c.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "build_english_cells")]
fn build_english_cells_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    let input = types::EnglishGridInput::from_py(input_dict)?;
    let cells = py.allow_threads(move || english_wireless::build_english_cells(&input));
    let list = PyList::empty_bound(py);
    for c in cells {
        list.append(c.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "build_general_wireless_cells")]
fn build_general_wireless_cells_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    let input = types::GeneralWirelessInput::from_py(input_dict)?;
    let cells = py.allow_threads(move || english_wireless::build_general_wireless_cells(&input));
    let list = PyList::empty_bound(py);
    for c in cells {
        list.append(c.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "build_legacy_text_alignment")]
fn build_legacy_text_alignment_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyList>> {
    let input = types::LegacyAlignmentInput::from_py(input_dict)?;
    let cells = py.allow_threads(move || english_wireless::build_legacy_text_alignment(&input));
    let list = PyList::empty_bound(py);
    for c in cells {
        list.append(c.to_py(py)?)?;
    }
    Ok(list)
}

#[pyfunction(name = "infer_header_structure")]
fn infer_header_structure_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input = types::HeaderGridInput::from_py(input_dict)?;
    let output = py.allow_threads(move || table_normalization::infer_header_structure(input));
    output.to_py(py)
}

#[pyfunction(name = "merge_header_spans")]
fn merge_header_spans_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input = types::HeaderGridInput::from_py(input_dict)?;
    let output = py.allow_threads(move || table_normalization::merge_header_spans(input));
    output.to_py(py)
}

#[pyfunction(name = "normalize_financial_header_tokens")]
fn normalize_financial_header_tokens_binding<'py>(
    py: Python<'py>,
    input_dict: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyDict>> {
    let input = types::HeaderTokenInput::from_py(input_dict)?;
    let output =
        py.allow_threads(move || table_normalization::normalize_financial_header_tokens(input));
    output.to_py(py)
}

#[pymodule]
fn _pdf_fast(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(pdfium_api::run_public_pdf_api, module)?)?;
    module.add_function(wrap_pyfunction!(pdfium_api::classify_page_from_bytes, module)?)?;
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
    module.add_function(wrap_pyfunction!(recover_wireless_tables_packed_binding, module)?)?;
    module.add_function(wrap_pyfunction!(group_backgrounds_binding, module)?)?;
    module.add_function(wrap_pyfunction!(detect_zebra_rows_binding, module)?)?;
    module.add_function(wrap_pyfunction!(
        assign_words_to_zebra_rows_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(infer_english_columns_binding, module)?)?;
    module.add_function(wrap_pyfunction!(build_english_cells_binding, module)?)?;
    module.add_function(wrap_pyfunction!(
        build_general_wireless_cells_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        build_legacy_text_alignment_binding,
        module
    )?)?;
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
    module.add_function(wrap_pyfunction!(
        recover_personal_credit_tables_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(roundtrip_dto_binding, module)?)?;
    module.add_function(wrap_pyfunction!(
        collect_native_spans_from_snapshot_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        collect_native_spans_from_rawdict_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        recover_wireless_tables_from_rawdict_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        recover_cells_from_snapshot_binding,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(page_snapshot_digest_binding, module)?)?;
    module.add_function(wrap_pyfunction!(stage_input_digest_binding, module)?)?;
    module.add_function(wrap_pyfunction!(infer_header_structure_binding, module)?)?;
    module.add_function(wrap_pyfunction!(merge_header_spans_binding, module)?)?;
    module.add_function(wrap_pyfunction!(
        normalize_financial_header_tokens_binding,
        module
    )?)?;
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
