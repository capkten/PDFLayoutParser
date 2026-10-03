pub mod geometry;
pub mod native_span;
pub mod snapshot;
pub mod types;
pub mod wired;
pub mod wireless_structure;

pub use geometry::Line4;
pub use types::*;

/// Recovers table structure for a detected table bounding box from page normalizer data.
/// Tries wired extraction first if vector lines exist; falls back to native-span wireless recovery.
pub fn recover_table_in_region(
    norm_page: &crate::normalizer::NormalizedPageDto,
    bbox: [f64; 4],
    confidence: Option<f64>,
    _label: &str,
    table_id: usize,
) -> Option<crate::markdown::FullTableDto> {
    let snapshot = norm_page.page_snapshot.as_ref()?;
    let tol = 2.3;

    // 1. Try wired table extraction if line drawings intersect the region
    let mut h_lines = Vec::new();
    let mut v_lines = Vec::new();

    for drawing in &snapshot.drawings {
        for line in &drawing.lines {
            let r = &line.rect;
            if r.x1 >= bbox[0] - tol
                && r.x0 <= bbox[2] + tol
                && r.y1 >= bbox[1] - tol
                && r.y0 <= bbox[3] + tol
            {
                let dx = (r.x1 - r.x0).abs();
                let dy = (r.y1 - r.y0).abs();
                if dx >= 1.0 && dy <= 3.0 {
                    h_lines.push(LineDto {
                        schema_version: 1,
                        rect: Rect4 {
                            schema_version: 1,
                            x0: r.x0,
                            y0: r.y0,
                            x1: r.x1,
                            y1: r.y1,
                        },
                        width: line.width,
                        color: line.color,
                        source_order: line.source_order as i64,
                    });
                } else if dy >= 1.0 && dx <= 3.0 {
                    v_lines.push(LineDto {
                        schema_version: 1,
                        rect: Rect4 {
                            schema_version: 1,
                            x0: r.x0,
                            y0: r.y0,
                            x1: r.x1,
                            y1: r.y1,
                        },
                        width: line.width,
                        color: line.color,
                        source_order: line.source_order as i64,
                    });
                }
            }
        }
    }

    if h_lines.len() >= 2 && !v_lines.is_empty() {
        let mut words = Vec::new();
        for (w_idx, w) in norm_page.words.iter().enumerate() {
            let wx0 = w.x0();
            let wy0 = w.y0();
            let wx1 = w.x1();
            let wy1 = w.y1();
            let cx = (wx0 + wx1) / 2.0;
            let cy = (wy0 + wy1) / 2.0;
            if cx >= bbox[0] && cx <= bbox[2] && cy >= bbox[1] && cy <= bbox[3] {
                words.push(WordDto {
                    schema_version: 1,
                    text: w.text().to_string(),
                    rect: Rect4 {
                        schema_version: 1,
                        x0: wx0,
                        y0: wy0,
                        x1: wx1,
                        y1: wy1,
                    },
                    order: w_idx as i64,
                    block: Some(w.block_idx() as i64),
                    line: Some(w.line_idx() as i64),
                });
            }
        }

        let wired_input = WiredRegionInput {
            schema_version: 1,
            page: PageDto {
                schema_version: 1,
                width: snapshot.page.width,
                height: snapshot.page.height,
                rotation: snapshot.page.rotation,
            },
            h_lines,
            v_lines,
            words,
            tolerance: tol,
        };

        let wired_output = wired::extract_wired_region(wired_input);
        let region_cells: Vec<_> = wired_output
            .cells
            .into_iter()
            .filter(|c| {
                let cx = (c.rect.x0 + c.rect.x1) / 2.0;
                let cy = (c.rect.y0 + c.rect.y1) / 2.0;
                cx >= bbox[0] - tol
                    && cx <= bbox[2] + tol
                    && cy >= bbox[1] - tol
                    && cy <= bbox[3] + tol
            })
            .collect();

        if !region_cells.is_empty() && region_cells.iter().any(|c| !c.text.trim().is_empty()) {
            let num_rows = region_cells
                .iter()
                .map(|c| (c.row + c.rowspan) as usize)
                .max()
                .unwrap_or(0);
            let num_cols = region_cells
                .iter()
                .map(|c| (c.col + c.colspan) as usize)
                .max()
                .unwrap_or(0);
            if num_rows >= 1 && num_cols >= 1 {
                let table_cells: Vec<crate::markdown::TableCellDto> = region_cells
                    .into_iter()
                    .map(|c| crate::markdown::TableCellDto {
                        text: c.text,
                        row_index: c.row as usize,
                        col_index: c.col as usize,
                        rowspan: c.rowspan.max(1) as usize,
                        colspan: c.colspan.max(1) as usize,
                        bbox: [c.rect.x0, c.rect.y0, c.rect.x1, c.rect.y1],
                    })
                    .collect();

                return Some(crate::markdown::FullTableDto {
                    table_id,
                    bbox,
                    rows: num_rows,
                    cols: num_cols,
                    cells: table_cells,
                    confidence,
                    source: Some("wired_table_recovery".to_string()),
                });
            }
        }
    }

    // 2. Wireless native-span table recovery
    let region_rect = Rect4 {
        schema_version: 1,
        x0: bbox[0],
        y0: bbox[1],
        x1: bbox[2],
        y1: bbox[3],
    };

    let raw_input_spans = snapshot::collect_native_spans_from_wire(
        snapshot,
        Some(&[region_rect.clone()]),
        None,
    );

    if !raw_input_spans.is_empty() {
        let span_dtos: Vec<NativeSpanDto> = raw_input_spans.iter().map(|s| s.span.clone()).collect();
        let runs = native_span::build_text_runs(span_dtos, region_rect.clone());
        let atoms = native_span::build_atoms(runs, Some(region_rect.clone()));

        let mut candidate_cells = Vec::new();

        if !atoms.is_empty() {
            let native_input = NativeRegionInput {
                schema_version: 1,
                region: RegionDto {
                    schema_version: 1,
                    rect: region_rect.clone(),
                    source_order: 0,
                    allowed: true,
                },
                atoms,
                bands: Vec::new(),
                atom_evidence: None,
                band_evidence: None,
                output_mode: "zh".to_string(),
                config: StructureConfig::default(),
            };
            let native_output = wireless_structure::recover_native_region(native_input);
            if !native_output.cells.is_empty()
                && native_output.cells.iter().any(|c| !c.text.trim().is_empty())
            {
                candidate_cells = native_output.cells;
            }
        }

        if candidate_cells.is_empty() {
            let wireless_output =
                wireless_structure::recover_cells_from_spans(raw_input_spans, &region_rect);
            if !wireless_output.cells.is_empty()
                && wireless_output.cells.iter().any(|c| !c.text.trim().is_empty())
            {
                candidate_cells = wireless_output.cells;
            }
        }

        if !candidate_cells.is_empty() {
            let num_rows = candidate_cells
                .iter()
                .map(|c| (c.row + c.rowspan) as usize)
                .max()
                .unwrap_or(0);
            let num_cols = candidate_cells
                .iter()
                .map(|c| (c.col + c.colspan) as usize)
                .max()
                .unwrap_or(0);
            if num_rows >= 1 && num_cols >= 1 {
                let table_cells: Vec<crate::markdown::TableCellDto> = candidate_cells
                    .into_iter()
                    .map(|c| crate::markdown::TableCellDto {
                        text: c.text,
                        row_index: c.row as usize,
                        col_index: c.col as usize,
                        rowspan: c.rowspan.max(1) as usize,
                        colspan: c.colspan.max(1) as usize,
                        bbox: [c.rect.x0, c.rect.y0, c.rect.x1, c.rect.y1],
                    })
                    .collect();

                return Some(crate::markdown::FullTableDto {
                    table_id,
                    bbox,
                    rows: num_rows,
                    cols: num_cols,
                    cells: table_cells,
                    confidence,
                    source: Some("wireless_span_recovery".to_string()),
                });
            }
        }
    }

    None
}
