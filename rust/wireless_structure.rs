use crate::types::{
    AtomDto, CellDto, ColumnBandDto, DiagnosticDto, GridDto, LogicalGridDto, NativeRegionInput,
    NativeRegionOutput, PhysicalCell, Rect4, RowClusterDto, TableCandidateDto,
    WirelessRecoveryInput, WirelessRecoveryOutput,
};

fn center_x(r: &Rect4) -> f64 {
    (r.x0 + r.x1) / 2.0
}

fn center_y(r: &Rect4) -> f64 {
    (r.y0 + r.y1) / 2.0
}

fn horizontal_overlap(a: &Rect4, b: &Rect4) -> f64 {
    (a.x1.min(b.x1) - a.x0.max(b.x0)).max(0.0)
}

pub fn infer_column_bands(atoms: Vec<AtomDto>, region: Rect4) -> Vec<ColumnBandDto> {
    if atoms.is_empty() {
        return Vec::new();
    }
    let region_w = (region.x1 - region.x0).max(1.0);
    // 过滤宽度过大的跨列表头
    let mut candidates: Vec<AtomDto> = atoms
        .into_iter()
        .filter(|a| (a.rect.x1 - a.rect.x0) < region_w * 0.85)
        .collect();

    candidates.sort_by(|a, b| {
        a.rect
            .x0
            .partial_cmp(&b.rect.x0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut components: Vec<Vec<AtomDto>> = Vec::new();
    for atom in candidates {
        let mut matched_indices = Vec::new();
        for (idx, comp) in components.iter().enumerate() {
            let matches = comp.iter().any(|member| {
                let ov = horizontal_overlap(&atom.rect, &member.rect);
                let narrow = (atom.rect.x1 - atom.rect.x0)
                    .min(member.rect.x1 - member.rect.x0)
                    .max(1.0);
                ov >= 2.0 || ov >= narrow * 0.25
            });
            if matches {
                matched_indices.push(idx);
            }
        }

        if matched_indices.is_empty() {
            components.push(vec![atom]);
        } else {
            let mut merged = vec![atom];
            for &idx in matched_indices.iter().rev() {
                let comp = components.remove(idx);
                merged.extend(comp);
            }
            components.push(merged);
        }
    }

    let mut bands = Vec::new();
    for comp in components {
        let mut y_slots: Vec<i64> = comp
            .iter()
            .map(|a| (center_y(&a.rect) / 8.0).round() as i64)
            .collect();
        y_slots.sort();
        y_slots.dedup();
        let x0 = comp.iter().map(|a| a.rect.x0).fold(f64::INFINITY, f64::min);
        let x1 = comp
            .iter()
            .map(|a| a.rect.x1)
            .fold(f64::NEG_INFINITY, f64::max);
        let source_atoms = comp.iter().map(|a| a.order).collect();
        bands.push((x0, x1, source_atoms));
    }

    bands.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    bands
        .into_iter()
        .enumerate()
        .map(|(order, (x0, x1, source_atoms))| ColumnBandDto {
            schema_version: 1,
            x0,
            x1,
            source_atoms,
            order: order as i64,
        })
        .collect()
}

pub fn refine_leaf_bands(
    _atoms: Vec<AtomDto>,
    bands: Vec<ColumnBandDto>,
) -> (Vec<ColumnBandDto>, Option<f64>) {
    (bands, None)
}

pub fn build_grid(
    atoms: Vec<AtomDto>,
    bands: Vec<ColumnBandDto>,
) -> (
    Vec<RowClusterDto>,
    Vec<ColumnBandDto>,
    Vec<PhysicalCell>,
    Vec<DiagnosticDto>,
) {
    if atoms.is_empty() || bands.is_empty() {
        return (Vec::new(), bands, Vec::new(), Vec::new());
    }

    // 1. 行聚类
    let mut sorted_atoms = atoms;
    sorted_atoms.sort_by(|a, b| {
        center_y(&a.rect)
            .partial_cmp(&center_y(&b.rect))
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut rows: Vec<Vec<AtomDto>> = Vec::new();
    let mut row_centers: Vec<f64> = Vec::new();
    let row_tolerance = 3.5;

    for atom in sorted_atoms {
        let cy = center_y(&atom.rect);
        if let Some(last_center) = row_centers.last() {
            if (cy - last_center).abs() <= row_tolerance {
                let last_idx = rows.len() - 1;
                rows[last_idx].push(atom);
                let count = rows[last_idx].len() as f64;
                let sum: f64 = rows[last_idx].iter().map(|a| center_y(&a.rect)).sum();
                row_centers[last_idx] = sum / count;
                continue;
            }
        }
        row_centers.push(cy);
        rows.push(vec![atom]);
    }

    let mut row_clusters = Vec::new();
    let mut physical_cells = Vec::new();

    for (row_idx, row_atoms) in rows.into_iter().enumerate() {
        let y0 = row_atoms
            .iter()
            .map(|a| a.rect.y0)
            .fold(f64::INFINITY, f64::min);
        let y1 = row_atoms
            .iter()
            .map(|a| a.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max);
        let item_indices = row_atoms.iter().map(|a| a.order).collect();
        row_clusters.push(RowClusterDto {
            schema_version: 1,
            row_index: row_idx as i64,
            y0,
            y1,
            item_indices,
        });

        for atom in row_atoms {
            let mut best_col = 0;
            let mut max_ov = -1.0;
            for (col_idx, band) in bands.iter().enumerate() {
                let ov = (atom.rect.x1.min(band.x1) - atom.rect.x0.max(band.x0)).max(0.0);
                if ov > max_ov {
                    max_ov = ov;
                    best_col = col_idx;
                }
            }
            if max_ov <= 0.0 {
                let cx = center_x(&atom.rect);
                best_col = bands
                    .iter()
                    .enumerate()
                    .min_by(|(_, b1), (_, b2)| {
                        let d1 = (cx - (b1.x0 + b1.x1) / 2.0).abs();
                        let d2 = (cx - (b2.x0 + b2.x1) / 2.0).abs();
                        d1.partial_cmp(&d2).unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .map(|(idx, _)| idx)
                    .unwrap_or(0);
            }

            physical_cells.push(PhysicalCell {
                schema_version: 1,
                text: atom.text,
                rect: atom.rect,
                row: row_idx as i64,
                col: best_col as i64,
                source_refs: atom.run_refs,
            });
        }
    }

    (row_clusters, bands, physical_cells, Vec::new())
}

pub fn build_logical_grid(atoms: Vec<AtomDto>, grid: GridDto) -> LogicalGridDto {
    let mut cells = Vec::new();
    let rows = grid.rows as usize;
    let cols = grid.cols as usize;
    let mut occupied = vec![vec![false; cols]; rows];

    for (r, row_occ) in grid.occupancy.iter().enumerate() {
        if r >= rows {
            break;
        }
        for (c, slot) in row_occ.iter().enumerate() {
            if c >= cols {
                break;
            }
            if let Some(idx) = slot {
                let r_idx = *idx as usize;
                if r_idx < atoms.len() {
                    let atom = &atoms[r_idx];
                    occupied[r][c] = true;
                    cells.push(CellDto {
                        schema_version: 1,
                        text: atom.text.clone(),
                        row: r as i64,
                        col: c as i64,
                        rect: atom.rect.clone(),
                        rowspan: 1,
                        colspan: 1,
                        source: Some(PhysicalCell {
                            schema_version: 1,
                            text: atom.text.clone(),
                            rect: atom.rect.clone(),
                            row: r as i64,
                            col: c as i64,
                            source_refs: atom.run_refs.clone(),
                        }),
                    });
                }
            }
        }
    }

    let mut empty_slots = Vec::new();
    for r in 0..rows {
        for c in 0..cols {
            if !occupied[r][c] {
                empty_slots.push(vec![r as i64, c as i64]);
                let x0 = if c < grid.col_edges.len() {
                    grid.col_edges[c]
                } else {
                    0.0
                };
                let x1 = if c + 1 < grid.col_edges.len() {
                    grid.col_edges[c + 1]
                } else {
                    x0 + 10.0
                };
                let y0 = if r < grid.row_edges.len() {
                    grid.row_edges[r]
                } else {
                    0.0
                };
                let y1 = if r + 1 < grid.row_edges.len() {
                    grid.row_edges[r + 1]
                } else {
                    y0 + 10.0
                };

                cells.push(CellDto {
                    schema_version: 1,
                    text: String::new(),
                    row: r as i64,
                    col: c as i64,
                    rect: Rect4 {
                        schema_version: 1,
                        x0,
                        y0,
                        x1,
                        y1,
                    },
                    rowspan: 1,
                    colspan: 1,
                    source: None,
                });
            }
        }
    }

    cells.sort_by(|a, b| match a.row.cmp(&b.row) {
        std::cmp::Ordering::Equal => a.col.cmp(&b.col),
        other => other,
    });

    LogicalGridDto {
        schema_version: 1,
        grid,
        cells,
        empty_slots,
    }
}

pub fn recover_native_region(input: NativeRegionInput) -> NativeRegionOutput {
    let bands = if input.bands.is_empty() {
        infer_column_bands(input.atoms.clone(), input.region.rect.clone())
    } else {
        input.bands
    };

    let (rows, bands, phys_cells, diags) = build_grid(input.atoms.clone(), bands);

    let num_rows = rows.len().max(1);
    let num_cols = bands.len().max(1);

    let mut row_edges = Vec::new();
    for r in &rows {
        row_edges.push(r.y0);
    }
    if let Some(last) = rows.last() {
        row_edges.push(last.y1);
    } else {
        row_edges.push(input.region.rect.y0);
        row_edges.push(input.region.rect.y1);
    }

    let mut col_edges = Vec::new();
    for b in &bands {
        col_edges.push(b.x0);
    }
    if let Some(last) = bands.last() {
        col_edges.push(last.x1);
    } else {
        col_edges.push(input.region.rect.x0);
        col_edges.push(input.region.rect.x1);
    }

    let mut occupancy = vec![vec![None; num_cols]; num_rows];
    let mut cells = Vec::new();

    for pc in phys_cells {
        let r = pc.row as usize;
        let c = pc.col as usize;
        if r < num_rows && c < num_cols {
            occupancy[r][c] = Some(cells.len() as i64);
        }
        cells.push(CellDto {
            schema_version: 1,
            text: pc.text.clone(),
            row: pc.row,
            col: pc.col,
            rect: pc.rect.clone(),
            rowspan: 1,
            colspan: 1,
            source: Some(pc),
        });
    }

    let mut empty_slots = Vec::new();
    for r in 0..num_rows {
        for c in 0..num_cols {
            if occupancy[r][c].is_none() {
                empty_slots.push(vec![r as i64, c as i64]);
                let x0 = if c < col_edges.len() {
                    col_edges[c]
                } else {
                    0.0
                };
                let x1 = if c + 1 < col_edges.len() {
                    col_edges[c + 1]
                } else {
                    x0 + 10.0
                };
                let y0 = if r < row_edges.len() {
                    row_edges[r]
                } else {
                    0.0
                };
                let y1 = if r + 1 < row_edges.len() {
                    row_edges[r + 1]
                } else {
                    y0 + 10.0
                };

                cells.push(CellDto {
                    schema_version: 1,
                    text: String::new(),
                    row: r as i64,
                    col: c as i64,
                    rect: Rect4 {
                        schema_version: 1,
                        x0,
                        y0,
                        x1,
                        y1,
                    },
                    rowspan: 1,
                    colspan: 1,
                    source: None,
                });
            }
        }
    }

    cells.sort_by(|a, b| match a.row.cmp(&b.row) {
        std::cmp::Ordering::Equal => a.col.cmp(&b.col),
        other => other,
    });

    let grid_dto = GridDto {
        schema_version: 1,
        rows: num_rows as i64,
        cols: num_cols as i64,
        row_edges,
        col_edges,
        occupancy,
    };

    let logical_grid = LogicalGridDto {
        schema_version: 1,
        grid: grid_dto,
        cells: cells.clone(),
        empty_slots,
    };

    NativeRegionOutput {
        schema_version: 1,
        grid: logical_grid,
        cells,
        diagnostics: diags,
    }
}

pub fn table_quality(candidate: &TableCandidateDto) -> f64 {
    let conf = candidate.confidence.unwrap_or(0.5);
    let populated = candidate
        .cells
        .iter()
        .filter(|c| !c.text.trim().is_empty())
        .count() as f64;
    let size = (candidate.rows * candidate.cols) as f64;
    conf * 1_000_000.0 + populated * 1000.0 + size
}

pub fn select_candidates(
    candidates: Vec<TableCandidateDto>,
    excluded: Vec<Rect4>,
    allowed: Vec<Rect4>,
) -> Vec<TableCandidateDto> {
    let mut filtered = Vec::new();
    for cand in candidates {
        let is_excluded = excluded.iter().any(|ex| {
            let w = cand.rect.x1.min(ex.x1) - cand.rect.x0.max(ex.x0);
            let h = cand.rect.y1.min(ex.y1) - cand.rect.y0.max(ex.y0);
            w > 0.0 && h > 0.0
        });
        if is_excluded {
            continue;
        }
        if !allowed.is_empty() {
            let is_allowed = allowed.iter().any(|al| {
                let w = cand.rect.x1.min(al.x1) - cand.rect.x0.max(al.x0);
                let h = cand.rect.y1.min(al.y1) - cand.rect.y0.max(al.y0);
                w > 0.0 && h > 0.0
            });
            if !is_allowed {
                continue;
            }
        }
        filtered.push(cand);
    }

    let mut accepted: Vec<TableCandidateDto> = Vec::new();
    for cand in filtered {
        let mut overlapping_indices = Vec::new();
        for (idx, old) in accepted.iter().enumerate() {
            let w = cand.rect.x1.min(old.rect.x1) - cand.rect.x0.max(old.rect.x0);
            let h = cand.rect.y1.min(old.rect.y1) - cand.rect.y0.max(old.rect.y0);
            if w > 0.0 && h > 0.0 {
                let overlap = w * h;
                let a1 = (cand.rect.x1 - cand.rect.x0) * (cand.rect.y1 - cand.rect.y0);
                let a2 = (old.rect.x1 - old.rect.x0) * (old.rect.y1 - old.rect.y0);
                if overlap / a1.min(a2).max(1.0) >= 0.20 {
                    overlapping_indices.push(idx);
                }
            }
        }

        let cand_q = table_quality(&cand);
        if !overlapping_indices.is_empty() {
            let all_worse = overlapping_indices
                .iter()
                .all(|&idx| cand_q > table_quality(&accepted[idx]));
            if all_worse {
                for &idx in overlapping_indices.iter().rev() {
                    accepted.remove(idx);
                }
                accepted.push(cand);
            }
        } else {
            accepted.push(cand);
        }
    }
    accepted
}

pub fn recover_wireless_tables(input: WirelessRecoveryInput) -> WirelessRecoveryOutput {
    let mut candidates = Vec::new();

    let excluded_regions: Vec<Rect4> = input
        .regions
        .iter()
        .filter(|r| !r.allowed)
        .map(|r| r.rect.clone())
        .collect();

    let allowed_regions: Vec<Rect4> = input
        .regions
        .iter()
        .filter(|r| r.allowed)
        .map(|r| r.rect.clone())
        .collect();

    let target_regions = if allowed_regions.is_empty() {
        vec![Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: input.page.width,
            y1: input.page.height,
        }]
    } else {
        allowed_regions.clone()
    };

    for reg in target_regions {
        let mut region_atoms = Vec::new();
        for span in &input.spans {
            let cx = (span.rect.x0 + span.rect.x1) / 2.0;
            let cy = (span.rect.y0 + span.rect.y1) / 2.0;
            if cx >= reg.x0 && cx <= reg.x1 && cy >= reg.y0 && cy <= reg.y1 {
                region_atoms.push(AtomDto {
                    schema_version: 1,
                    text: span.text.clone(),
                    rect: span.rect.clone(),
                    run_refs: vec![span.order],
                    row_hint: None,
                    col_hint: None,
                    order: span.order,
                });
            }
        }

        if region_atoms.len() < 4 {
            continue;
        }

        let bands = infer_column_bands(region_atoms.clone(), reg.clone());
        if bands.len() < 2 {
            continue;
        }

        let (rows, bands_out, phys_cells, _diags) = build_grid(region_atoms, bands);
        if rows.len() < 2 || bands_out.len() < 2 {
            continue;
        }

        let mut cells = Vec::new();
        let num_rows = rows.len();
        let num_cols = bands_out.len();
        let mut occupancy = vec![vec![None; num_cols]; num_rows];

        for pc in phys_cells {
            let r = pc.row as usize;
            let c = pc.col as usize;
            if r < num_rows && c < num_cols {
                occupancy[r][c] = Some(cells.len());
            }
            cells.push(CellDto {
                schema_version: 1,
                text: pc.text.clone(),
                row: pc.row,
                col: pc.col,
                rect: pc.rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(pc),
            });
        }

        let x0 = bands_out.iter().map(|b| b.x0).fold(f64::INFINITY, f64::min);
        let x1 = bands_out
            .iter()
            .map(|b| b.x1)
            .fold(f64::NEG_INFINITY, f64::max);
        let y0 = rows.iter().map(|r| r.y0).fold(f64::INFINITY, f64::min);
        let y1 = rows.iter().map(|r| r.y1).fold(f64::NEG_INFINITY, f64::max);

        let cand_rect = Rect4 {
            schema_version: 1,
            x0,
            y0,
            x1,
            y1,
        };

        let candidate = TableCandidateDto {
            schema_version: 1,
            rect: cand_rect,
            source: "wireless_span_recovery".to_string(),
            confidence: Some(0.90),
            rows: num_rows as i64,
            cols: num_cols as i64,
            cells,
        };
        candidates.push(candidate);
    }

    let selected = select_candidates(candidates, excluded_regions, allowed_regions);

    WirelessRecoveryOutput {
        schema_version: 1,
        candidates: selected,
        diagnostics: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_atom(text: &str, x0: f64, y0: f64, x1: f64, y1: f64, order: i64) -> AtomDto {
        AtomDto {
            schema_version: 1,
            text: text.to_string(),
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            run_refs: vec![order],
            row_hint: None,
            col_hint: None,
            order,
        }
    }

    #[test]
    fn test_infer_column_bands() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 500.0,
        };
        let atoms = vec![
            make_atom("项目", 10.0, 10.0, 40.0, 20.0, 0),
            make_atom("金额", 100.0, 10.0, 140.0, 20.0, 1),
            make_atom("营收", 10.0, 30.0, 40.0, 40.0, 2),
            make_atom("500", 100.0, 30.0, 130.0, 40.0, 3),
        ];
        let bands = infer_column_bands(atoms, region);
        assert_eq!(bands.len(), 2);
    }
}
