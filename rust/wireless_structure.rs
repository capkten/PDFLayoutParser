use crate::native_span;
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

fn rect_height(r: &Rect4) -> f64 {
    (r.y1 - r.y0).max(0.0)
}

fn vertical_overlap(left: &Rect4, right: &Rect4) -> f64 {
    (left.y1.min(right.y1) - left.y0.max(right.y0)).max(0.0)
}

fn y_overlap_ratio(left: &Rect4, right: &Rect4) -> f64 {
    let taller_height = rect_height(left).max(rect_height(right));
    if taller_height <= 0.0 {
        return 0.0;
    }
    vertical_overlap(left, right) / taller_height
}

fn same_visual_row(left: &Rect4, right: &Rect4, tolerance: f64) -> bool {
    if (center_y(left) - center_y(right)).abs() <= tolerance {
        return true;
    }
    let left_height = rect_height(left);
    let right_height = rect_height(right);
    vertical_overlap(left, right) >= left_height.min(right_height) * 0.45
        && (left.y0 - right.y0).abs() <= 2.4_f64.max(left_height.min(right_height) * 0.4)
}

fn atom_column_span(rect: &Rect4, bands: &[ColumnBandDto]) -> (usize, usize) {
    let primary = best_column_for_rect(rect, bands).min(bands.len().saturating_sub(1));
    if bands.len() < 2 {
        return (primary, primary);
    }

    let width = (rect.x1 - rect.x0).max(1.0);
    let minimum_side = (width * 0.35).max(2.0);
    let mut start = primary;
    let mut end = primary;
    for boundary_index in 0..bands.len() - 1 {
        let boundary = (bands[boundary_index].x1 + bands[boundary_index + 1].x0) / 2.0;
        if rect.x0 >= boundary || rect.x1 <= boundary {
            continue;
        }
        let left_side = boundary - rect.x0;
        let right_side = rect.x1 - boundary;
        if left_side < minimum_side || right_side < minimum_side {
            continue;
        }
        if boundary_index < primary {
            start = start.min(boundary_index);
        } else {
            end = end.max(boundary_index + 1);
        }
    }
    (start, end)
}

fn spans_overlap(left: (usize, usize), right: (usize, usize)) -> bool {
    left.0 <= right.1 && right.0 <= left.1
}

fn median_positive(values: impl IntoIterator<Item = f64>, fallback: f64) -> f64 {
    let mut values: Vec<f64> = values.into_iter().filter(|value| *value > 0.0).collect();
    if values.is_empty() {
        return fallback;
    }
    values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    values[values.len() / 2]
}

fn can_join_visual_row(
    group: &[AtomDto],
    candidate: &AtomDto,
    bands: &[ColumnBandDto],
    tolerance: f64,
) -> bool {
    let Some(representative) = group.iter().min_by(|left, right| {
        (center_y(&left.rect) - center_y(&candidate.rect))
            .abs()
            .partial_cmp(&(center_y(&right.rect) - center_y(&candidate.rect)).abs())
            .unwrap_or(std::cmp::Ordering::Equal)
    }) else {
        return false;
    };
    if !same_visual_row(&representative.rect, &candidate.rect, tolerance) {
        return false;
    }

    let group_mean_y =
        group.iter().map(|item| center_y(&item.rect)).sum::<f64>() / group.len() as f64;
    if (center_y(&candidate.rect) - group_mean_y).abs() > tolerance * 1.5 {
        return false;
    }

    let candidate_span = atom_column_span(&candidate.rect, bands);
    for existing in group {
        let existing_span = atom_column_span(&existing.rect, bands);
        if !spans_overlap(existing_span, candidate_span) {
            continue;
        }
        if existing_span != candidate_span {
            return false;
        }
        if y_overlap_ratio(&existing.rect, &candidate.rect) < 0.45 {
            return false;
        }
    }
    true
}

fn horizontal_overlap(a: &Rect4, b: &Rect4) -> f64 {
    (a.x1.min(b.x1) - a.x0.max(b.x0)).max(0.0)
}

fn is_dash_placeholder(text: &str) -> bool {
    let trimmed = text.trim();
    !trimmed.is_empty()
        && trimmed
            .chars()
            .all(|character| matches!(character, '-' | '—' | '–' | '−'))
}

fn has_numeric_character(text: &str) -> bool {
    text.chars().any(|character| character.is_ascii_digit())
}

fn is_bare_year(text: &str) -> bool {
    let trimmed = text.trim();
    trimmed.len() == 4
        && trimmed.chars().all(|character| character.is_ascii_digit())
        && (trimmed.starts_with("19") || trimmed.starts_with("20"))
}

fn is_temporal_leaf_header(text: &str) -> bool {
    let trimmed = text.trim();
    trimmed.ends_with('年')
        && trimmed
            .chars()
            .take(trimmed.chars().count().saturating_sub(1))
            .all(|character| {
                character.is_ascii_digit() || "〇零一二三四五六七八九".contains(character)
            })
}

fn is_structural_header_text(text: &str) -> bool {
    let trimmed = text.trim();
    if is_bare_year(trimmed) || is_temporal_leaf_header(trimmed) {
        return true;
    }
    let lower = trimmed.to_ascii_lowercase();
    lower.contains("hk$")
        || lower.contains("us$")
        || lower.contains("rmb")
        || lower.contains("hkd")
        || lower.contains("usd")
        || lower.contains("million")
        || trimmed.contains("千元")
        || trimmed.contains("百万元")
        || trimmed.ends_with('%')
}

fn is_latin_body_text(text: &str) -> bool {
    let has_latin = text
        .chars()
        .any(|character| character.is_ascii_alphabetic());
    let has_cjk = text.chars().any(|character| {
        ('\u{3400}'..='\u{9fff}').contains(&character)
            || ('\u{f900}'..='\u{faff}').contains(&character)
    });
    has_latin && !has_cjk
}

fn is_numeric_body_atom_text(text: &str) -> bool {
    has_numeric_character(text)
        && !is_structural_header_text(text)
        && text.trim().chars().all(|character| {
            character.is_ascii_digit()
                || matches!(
                    character,
                    ',' | '.' | '%' | '+' | '-' | '(' | ')' | '（' | '）' | '—' | '–' | '−'
                )
        })
}

fn best_column_for_rect(rect: &Rect4, bands: &[ColumnBandDto]) -> usize {
    let mut best_col = 0;
    let mut max_overlap = -1.0;
    for (col_idx, band) in bands.iter().enumerate() {
        let overlap = horizontal_overlap(
            rect,
            &Rect4 {
                schema_version: 1,
                x0: band.x0,
                y0: 0.0,
                x1: band.x1,
                y1: 1.0,
            },
        );
        if overlap > max_overlap {
            max_overlap = overlap;
            best_col = col_idx;
        }
    }
    if max_overlap > 0.0 {
        return best_col;
    }
    let center = center_x(rect);
    bands
        .iter()
        .enumerate()
        .min_by(|(_, left), (_, right)| {
            let left_distance = (center - (left.x0 + left.x1) / 2.0).abs();
            let right_distance = (center - (right.x0 + right.x1) / 2.0).abs();
            left_distance
                .partial_cmp(&right_distance)
                .unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(index, _)| index)
        .unwrap_or(0)
}

fn dash_track_assignments(
    atoms: &[AtomDto],
    bands: &[ColumnBandDto],
    header_cutoff: Option<f64>,
) -> std::collections::BTreeMap<i64, usize> {
    let Some(cutoff) = header_cutoff else {
        return std::collections::BTreeMap::new();
    };

    let mut anchors: std::collections::BTreeMap<usize, Vec<f64>> =
        std::collections::BTreeMap::new();
    for atom in atoms {
        if center_y(&atom.rect) <= cutoff
            || !has_numeric_character(&atom.text)
            || is_dash_placeholder(&atom.text)
        {
            continue;
        }
        let column = best_column_for_rect(&atom.rect, bands);
        anchors.entry(column).or_default().push(atom.rect.x1);
    }

    let right_edges: std::collections::BTreeMap<usize, f64> = anchors
        .into_iter()
        .filter_map(|(column, mut values)| {
            if values.len() < 2 {
                return None;
            }
            values.sort_by(|left, right| {
                left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal)
            });
            Some((column, values[values.len() / 2]))
        })
        .collect();

    let mut assignments = std::collections::BTreeMap::new();
    for atom in atoms {
        if center_y(&atom.rect) <= cutoff || !is_dash_placeholder(&atom.text) {
            continue;
        }
        let Some((column, distance)) = right_edges
            .iter()
            .map(|(column, right_edge)| (*column, (atom.rect.x1 - right_edge).abs()))
            .min_by(|(_, left), (_, right)| {
                left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal)
            })
        else {
            continue;
        };
        if distance <= 3.0 + 1e-6 {
            assignments.insert(atom.order, column);
        }
    }
    assignments
}

fn is_spanning_header(atom: &AtomDto, atoms: &[AtomDto], region: &Rect4) -> bool {
    let region_h = (region.y1 - region.y0).max(1.0);
    if atom.rect.y0 - region.y0 > region_h * 0.45 {
        return false;
    }
    let region_w = (region.x1 - region.x0).max(1.0);
    let atom_width = atom.rect.x1 - atom.rect.x0;
    if atom_width >= region_w * 0.85 {
        return false;
    }
    let atom_center_y = center_y(&atom.rect);
    let overlapping_below: Vec<&AtomDto> = atoms
        .iter()
        .filter(|candidate| center_y(&candidate.rect) > atom_center_y + 4.0)
        .filter(|candidate| horizontal_overlap(&candidate.rect, &atom.rect) > 2.0)
        .collect();
    for left in &overlapping_below {
        for right in &overlapping_below {
            if left.rect.x1 + 2.0 <= right.rect.x0
                && horizontal_overlap(&left.rect, &atom.rect) >= 5.0
                && horizontal_overlap(&right.rect, &atom.rect) >= 5.0
            {
                return true;
            }
        }
    }
    false
}

fn is_wide_header(atom: &AtomDto, atoms: &[AtomDto], region: &Rect4) -> bool {
    let region_w = (region.x1 - region.x0).max(1.0);
    let item_width = atom.rect.x1 - atom.rect.x0;
    if item_width < region_w * 0.28 || atom.rect.x0 < region.x0 + region_w * 0.18 {
        return false;
    }

    let y_support = atoms
        .iter()
        .filter(|candidate| {
            horizontal_overlap(&candidate.rect, &atom.rect)
                >= item_width.min(1.0_f64.max(candidate.rect.x1 - candidate.rect.x0)) * 0.25
        })
        .map(|candidate| (center_y(&candidate.rect) / 8.0).round() as i64)
        .collect::<std::collections::BTreeSet<_>>();
    y_support.len() < 2
}

fn is_sparse_left_section_title(atom: &AtomDto, atoms: &[AtomDto], region: &Rect4) -> bool {
    let same_row = atoms
        .iter()
        .filter(|candidate| (center_y(&candidate.rect) - center_y(&atom.rect)).abs() <= 2.4)
        .count();
    same_row == 1
        && atom.rect.x0 <= region.x0 + 16.0
        && atom.rect.x1 - atom.rect.x0 >= (region.x1 - region.x0) * 0.25
}

pub fn infer_column_bands(atoms: Vec<AtomDto>, region: Rect4) -> Vec<ColumnBandDto> {
    if atoms.is_empty() {
        return Vec::new();
    }
    let region_w = (region.x1 - region.x0).max(1.0);
    // 过滤宽度过大的跨列表头
    let mut candidates: Vec<AtomDto> = atoms
        .iter()
        .filter(|atom| (atom.rect.x1 - atom.rect.x0) < region_w * 0.86)
        .filter(|atom| !is_wide_header(atom, &atoms, &region))
        .filter(|atom| !is_spanning_header(atom, &atoms, &region))
        .filter(|atom| !is_sparse_left_section_title(atom, &atoms, &region))
        .cloned()
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
                ov >= 2.0_f64.max(narrow * 0.25)
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
        if comp.len() < 2 {
            continue;
        }
        let mut y_slots: Vec<i64> = comp
            .iter()
            .map(|a| (center_y(&a.rect) / 8.0).round() as i64)
            .collect();
        y_slots.sort();
        y_slots.dedup();
        if y_slots.len() < 2 {
            continue;
        }
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

    let dash_assignments =
        dash_track_assignments(&sorted_atoms, &bands, infer_header_cutoff(&sorted_atoms));

    let row_tolerance = (median_positive(
        sorted_atoms.iter().map(|atom| rect_height(&atom.rect)),
        10.0,
    ) * 0.70)
        .max(3.0);
    let mut rows: Vec<Vec<AtomDto>> = Vec::new();
    let mut row_centers: Vec<f64> = Vec::new();

    for atom in sorted_atoms {
        let last_index = rows.len().checked_sub(1);
        if let Some(last_index) = last_index {
            if can_join_visual_row(&rows[last_index], &atom, &bands, row_tolerance) {
                rows[last_index].push(atom);
                let count = rows[last_index].len() as f64;
                let sum: f64 = rows[last_index].iter().map(|a| center_y(&a.rect)).sum();
                row_centers[last_index] = sum / count;
                continue;
            }
        }
        let cy = center_y(&atom.rect);
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
            let best_col = dash_assignments
                .get(&atom.order)
                .copied()
                .unwrap_or_else(|| best_column_for_rect(&atom.rect, &bands));

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

fn occupancy_conflict_diagnostic(path: &str, row: usize, col: usize) -> DiagnosticDto {
    DiagnosticDto {
        schema_version: 1,
        status: "occupancy_conflict".to_string(),
        path: path.to_string(),
        error_type: Some("OccupancyConflict".to_string()),
        message: Some(format!("multiple cells claim slot ({row}, {col})")),
        traceback_id: None,
        field: Some("occupancy".to_string()),
        python_value: None,
        rust_value: None,
        classification: Some("defect".to_string()),
    }
}

fn full_page_atom_runs(atoms: Vec<AtomDto>) -> Vec<(Rect4, Vec<AtomDto>)> {
    if atoms.is_empty() {
        return Vec::new();
    }

    let mut ordered = atoms;
    ordered.sort_by(|left, right| {
        center_y(&left.rect)
            .partial_cmp(&center_y(&right.rect))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                left.rect
                    .x0
                    .partial_cmp(&right.rect.x0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut rows: Vec<Vec<AtomDto>> = Vec::new();
    let mut row_centers: Vec<f64> = Vec::new();
    for atom in ordered {
        let center = center_y(&atom.rect);
        if let Some(last_center) = row_centers.last() {
            if (center - last_center).abs() <= 3.5 {
                let index = rows.len() - 1;
                rows[index].push(atom);
                row_centers[index] = rows[index]
                    .iter()
                    .map(|item| center_y(&item.rect))
                    .sum::<f64>()
                    / rows[index].len() as f64;
                continue;
            }
        }
        rows.push(vec![atom]);
        row_centers.push(center);
    }

    let row_heights: Vec<f64> = rows
        .iter()
        .map(|row| {
            row.iter()
                .map(|atom| atom.rect.y1 - atom.rect.y0)
                .fold(0.0, f64::max)
        })
        .filter(|height| *height > 0.0)
        .collect();
    let median_height = if row_heights.is_empty() {
        10.0
    } else {
        let mut sorted = row_heights;
        sorted.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
        sorted[sorted.len() / 2]
    };
    let gap_limit = (median_height * 2.4).max(30.0);

    let mut runs: Vec<Vec<Vec<AtomDto>>> = Vec::new();
    let mut current: Vec<Vec<AtomDto>> = Vec::new();
    for (row_index, row) in rows.into_iter().enumerate() {
        let row_y0 = row
            .iter()
            .map(|atom| atom.rect.y0)
            .fold(f64::INFINITY, f64::min);
        let row_y1 = row
            .iter()
            .map(|atom| atom.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max);
        let previous_y1 = current.last().map(|previous| {
            previous
                .iter()
                .map(|atom| atom.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max)
        });
        let close = row_index == 0
            || previous_y1
                .map(|y1| row_y0 - y1 <= gap_limit)
                .unwrap_or(false);
        let multiple = row.len() >= 2;
        let full_width_single = row.len() == 1 && row_y1 - row_y0 > median_height * 2.5;

        if close && (multiple || (!full_width_single && !current.is_empty())) {
            current.push(row);
        } else {
            if current
                .iter()
                .filter(|candidate| candidate.len() >= 2)
                .count()
                >= 2
            {
                runs.push(std::mem::take(&mut current));
            } else {
                current.clear();
            }
            if multiple {
                current.push(row);
            }
        }
    }
    if current.iter().filter(|row| row.len() >= 2).count() >= 2 {
        runs.push(current);
    }

    runs.into_iter()
        .filter_map(|rows| {
            let run_atoms = rows.into_iter().flatten().collect::<Vec<_>>();
            if run_atoms.is_empty() {
                return None;
            }
            let rect = Rect4 {
                schema_version: 1,
                x0: run_atoms
                    .iter()
                    .map(|atom| atom.rect.x0)
                    .fold(f64::INFINITY, f64::min),
                y0: run_atoms
                    .iter()
                    .map(|atom| atom.rect.y0)
                    .fold(f64::INFINITY, f64::min),
                x1: run_atoms
                    .iter()
                    .map(|atom| atom.rect.x1)
                    .fold(f64::NEG_INFINITY, f64::max),
                y1: run_atoms
                    .iter()
                    .map(|atom| atom.rect.y1)
                    .fold(f64::NEG_INFINITY, f64::max),
            };
            Some((rect, run_atoms))
        })
        .collect()
}

fn append_empty_cells(
    cells: &mut Vec<CellDto>,
    occupancy: &mut [Vec<Option<i64>>],
    row_edges: &[f64],
    col_edges: &[f64],
) {
    for r in 0..occupancy.len() {
        for c in 0..occupancy[r].len() {
            if occupancy[r][c].is_some() {
                continue;
            }
            let x0 = col_edges.get(c).copied().unwrap_or(0.0);
            let x1 = col_edges.get(c + 1).copied().unwrap_or(x0 + 10.0);
            let y0 = row_edges.get(r).copied().unwrap_or(0.0);
            let y1 = row_edges.get(r + 1).copied().unwrap_or(y0 + 10.0);
            occupancy[r][c] = Some(cells.len() as i64);
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

fn logical_column_edges(bands: &[ColumnBandDto], region: &Rect4) -> Vec<f64> {
    if bands.is_empty() {
        return vec![region.x0, region.x1];
    }
    let mut edges = vec![region.x0];
    for pair in bands.windows(2) {
        edges.push((pair[0].x1 + pair[1].x0) / 2.0);
    }
    edges.push(region.x1);
    edges
}

fn rect_union(left: &Rect4, right: &Rect4) -> Rect4 {
    Rect4 {
        schema_version: 1,
        x0: left.x0.min(right.x0),
        y0: left.y0.min(right.y0),
        x1: left.x1.max(right.x1),
        y1: left.y1.max(right.y1),
    }
}

fn source_refs_contiguous(left: &[i64], right: &[i64]) -> bool {
    match (left.last(), right.first()) {
        (Some(left_end), Some(right_start)) => *right_start == *left_end + 1,
        _ => false,
    }
}

fn source_refs_contiguous_in_interleaved_row(
    cells: &[CellDto],
    current_index: usize,
    candidate_index: usize,
) -> bool {
    let current = &cells[current_index];
    let candidate = &cells[candidate_index];
    let current_refs = current
        .source
        .as_ref()
        .map(|source| source.source_refs.as_slice())
        .unwrap_or(&[]);
    let candidate_refs = candidate
        .source
        .as_ref()
        .map(|source| source.source_refs.as_slice())
        .unwrap_or(&[]);
    if source_refs_contiguous(current_refs, candidate_refs) {
        return true;
    }

    let (Some(left_end), Some(right_start)) = (current_refs.last(), candidate_refs.first()) else {
        return false;
    };
    if *right_start <= *left_end + 1 {
        return false;
    }

    let intervening_refs: std::collections::BTreeSet<i64> = cells
        .iter()
        .filter(|cell| cell.row == current.row)
        .filter_map(|cell| cell.source.as_ref())
        .flat_map(|source| source.source_refs.iter().copied())
        .filter(|source_ref| *left_end < *source_ref && *source_ref < *right_start)
        .collect();
    ((*left_end + 1)..*right_start).all(|source_ref| intervening_refs.contains(&source_ref))
}

fn is_single_cjk(text: &str) -> bool {
    let mut chars = text.trim().chars();
    let Some(character) = chars.next() else {
        return false;
    };
    chars.next().is_none()
        && matches!(
            character,
            '\u{3400}'..='\u{4dbf}'
                | '\u{4e00}'..='\u{9fff}'
                | '\u{f900}'..='\u{faff}'
                | '\u{ff00}'..='\u{ffef}'
        )
}

fn merge_physical_inline_fragments(cells: &mut Vec<PhysicalCell>) {
    cells.sort_by(|left, right| {
        left.row
            .cmp(&right.row)
            .then_with(|| left.col.cmp(&right.col))
            .then_with(|| {
                left.rect
                    .x0
                    .partial_cmp(&right.rect.x0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| left.source_refs.cmp(&right.source_refs))
    });

    let mut index = 0;
    while index < cells.len() {
        let mut candidate_index = index + 1;
        while candidate_index < cells.len() {
            let current = &cells[index];
            let candidate = &cells[candidate_index];
            let current_height = (current.rect.y1 - current.rect.y0).max(1.0);
            let candidate_height = (candidate.rect.y1 - candidate.rect.y0).max(1.0);
            let horizontal_gap = candidate.rect.x0 - current.rect.x1;
            let same_visual_row = current.row == candidate.row
                && (center_y(&current.rect) - center_y(&candidate.rect)).abs()
                    <= (current_height.min(candidate_height) * 0.38).max(2.4);
            let same_slot = current.col == candidate.col;
            let close_enough = horizontal_gap
                <= (current_height.min(candidate_height) * 1.25).max(2.0)
                && horizontal_gap >= -1.0;
            let wide_cjk_pair = is_single_cjk(&current.text)
                && is_single_cjk(&candidate.text)
                && horizontal_gap <= (current_height.min(candidate_height) * 3.0).max(2.0);
            if same_visual_row
                && same_slot
                && (close_enough || wide_cjk_pair)
                && source_refs_contiguous(&current.source_refs, &candidate.source_refs)
            {
                let candidate = cells.remove(candidate_index);
                let current = &mut cells[index];
                current.text.push_str(&candidate.text);
                current.rect = rect_union(&current.rect, &candidate.rect);
                current.source_refs.extend(candidate.source_refs);
                continue;
            }
            candidate_index += 1;
        }
        index += 1;
    }
}

fn merge_cell_source(current: &mut CellDto, candidate: CellDto, joiner: &str) {
    current.text = format!("{}{}{}", current.text.trim(), joiner, candidate.text.trim());
    current.rect = rect_union(&current.rect, &candidate.rect);
    current.rowspan = candidate.row + candidate.rowspan - current.row;
    if let Some(source) = current.source.as_mut() {
        if let Some(candidate_source) = candidate.source {
            source.text = current.text.clone();
            source.rect = rect_union(&source.rect, &candidate_source.rect);
            source.source_refs.extend(candidate_source.source_refs);
        }
    }
}

fn merge_source_contiguous_vertical_cells(cells: &mut Vec<CellDto>) {
    cells.sort_by(|left, right| {
        left.row
            .cmp(&right.row)
            .then_with(|| left.col.cmp(&right.col))
            .then_with(|| {
                left.rect
                    .y0
                    .partial_cmp(&right.rect.y0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut index = 0;
    while index < cells.len() {
        let current = &cells[index];
        let current_source_refs = current
            .source
            .as_ref()
            .map(|source| source.source_refs.clone())
            .unwrap_or_default();
        let mut candidate_index = None;
        for (other_index, candidate) in cells.iter().enumerate().skip(index + 1) {
            if candidate.row != current.row + current.rowspan
                || candidate.col != current.col
                || candidate.colspan != current.colspan
                || candidate.rowspan != 1
                || candidate.text.trim().is_empty()
            {
                continue;
            }
            let candidate_source_refs = candidate
                .source
                .as_ref()
                .map(|source| source.source_refs.as_slice())
                .unwrap_or(&[]);
            if !source_refs_contiguous(&current_source_refs, candidate_source_refs) {
                continue;
            }
            let minimum_width = (current.rect.x1 - current.rect.x0)
                .min(candidate.rect.x1 - candidate.rect.x0)
                .max(1.0);
            let overlap = horizontal_overlap(&current.rect, &candidate.rect);
            let vertical_gap = candidate.rect.y0 - current.rect.y1;
            if overlap < minimum_width * 0.45 || vertical_gap > 6.0 {
                continue;
            }
            candidate_index = Some(other_index);
            break;
        }

        let Some(other_index) = candidate_index else {
            index += 1;
            continue;
        };
        let candidate = cells.remove(other_index);
        let current = &mut cells[index];
        merge_cell_source(current, candidate, "\n");
    }
}

fn physical_cell_span(cell: &PhysicalCell, bands: &[ColumnBandDto]) -> (usize, usize) {
    let primary = (cell.col.max(0) as usize).min(bands.len().saturating_sub(1));
    if bands.len() < 2 {
        return (primary, primary);
    }
    let cell_width = (cell.rect.x1 - cell.rect.x0).max(1.0);
    let minimum_side = (cell_width * 0.35).max(2.0);
    let mut start = primary;
    let mut end = primary;
    for boundary_index in 0..bands.len() - 1 {
        let boundary = (bands[boundary_index].x1 + bands[boundary_index + 1].x0) / 2.0;
        if cell.rect.x0 >= boundary || cell.rect.x1 <= boundary {
            continue;
        }
        let left_side = boundary - cell.rect.x0;
        let right_side = cell.rect.x1 - boundary;
        if left_side < minimum_side || right_side < minimum_side {
            continue;
        }
        if boundary_index < primary {
            start = start.min(boundary_index);
        } else {
            end = end.max(boundary_index + 1);
        }
    }
    (start, end)
}

fn is_note_reference(text: &str) -> bool {
    let trimmed = text.trim();
    let lower = trimmed.to_ascii_lowercase();
    if lower == "note"
        || lower.starts_with("note ")
        || trimmed.starts_with("附注")
        || trimmed.starts_with("附註")
    {
        return true;
    }
    let chars: Vec<char> = trimmed.chars().collect();
    if chars.len() < 4 {
        return false;
    }
    let open = chars.iter().position(|ch| *ch == '(' || *ch == '（');
    let close = chars.iter().rposition(|ch| *ch == ')' || *ch == '）');
    let (Some(open), Some(close)) = (open, close) else {
        return false;
    };
    open > 0
        && close > open + 1
        && chars[..open].iter().all(|ch| ch.is_ascii_digit())
        && chars[open + 1..close]
            .iter()
            .all(|ch| ch.is_ascii_alphabetic())
}

fn row_levels(atoms: &[AtomDto]) -> Vec<f64> {
    let mut levels: Vec<f64> = Vec::new();
    for atom in atoms {
        let cy = center_y(&atom.rect);
        if let Some(last) = levels.last_mut() {
            if (cy - *last).abs() <= 2.4 {
                *last = (*last + cy) / 2.0;
                continue;
            }
        }
        levels.push(cy);
    }
    levels
}

fn infer_header_cutoff(atoms: &[AtomDto]) -> Option<f64> {
    if atoms.is_empty() {
        return None;
    }
    let mut ordered = atoms.to_vec();
    ordered.sort_by(|left, right| {
        center_y(&left.rect)
            .partial_cmp(&center_y(&right.rect))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let levels = row_levels(&ordered);
    if levels.len() < 3 {
        return None;
    }

    let level_counts: Vec<usize> = levels
        .iter()
        .map(|level| {
            ordered
                .iter()
                .filter(|atom| (center_y(&atom.rect) - level).abs() < 0.5)
                .count()
        })
        .collect();
    let gaps: Vec<f64> = levels.windows(2).map(|pair| pair[1] - pair[0]).collect();
    let median_gap = median_positive(gaps.iter().copied(), 0.0);
    let minimum_gap = gaps.iter().copied().fold(f64::INFINITY, f64::min);
    let early_gap_threshold = 12.0_f64.max(minimum_gap * 1.65);

    let checkmark_levels: Vec<f64> = levels
        .iter()
        .copied()
        .filter(|level| {
            ordered.iter().any(|atom| {
                (center_y(&atom.rect) - level).abs() < 0.5
                    && matches!(atom.text.trim(), "✓" | "✔" | "☑")
            })
        })
        .collect();
    if checkmark_levels.len() >= 2 {
        let first_checkmark = checkmark_levels[0];
        if let Some(previous) = levels
            .iter()
            .copied()
            .filter(|level| *level < first_checkmark - 1.0)
            .last()
        {
            return Some((previous + first_checkmark) / 2.0);
        }
    }

    let latin_body_indices: Vec<usize> = levels
        .iter()
        .enumerate()
        .filter_map(|(index, level)| {
            let is_body = ordered.iter().any(|atom| {
                (center_y(&atom.rect) - level).abs() < 0.5
                    && is_latin_body_text(&atom.text)
                    && !is_structural_header_text(&atom.text)
            });
            is_body.then_some(index)
        })
        .collect();
    for &index in &latin_body_indices {
        if index >= 2
            && latin_body_indices.contains(&(index + 1))
            && gaps[index - 1] >= early_gap_threshold
        {
            return Some((levels[index - 1] + levels[index]) / 2.0);
        }
    }

    let numeric_body: Vec<(usize, usize)> = levels
        .iter()
        .enumerate()
        .skip(1)
        .filter_map(|(index, level)| {
            let count = ordered
                .iter()
                .filter(|atom| (center_y(&atom.rect) - level).abs() < 0.5)
                .filter(|atom| is_numeric_body_atom_text(&atom.text))
                .count();
            (count > 0).then_some((index, count))
        })
        .collect();
    if numeric_body.len() >= 2 || (numeric_body.len() == 1 && numeric_body[0].1 >= 2) {
        let mut first_body_index = numeric_body[0].0;
        if first_body_index >= 2 {
            let dash_count = ordered
                .iter()
                .filter(|atom| {
                    (center_y(&atom.rect) - levels[first_body_index - 1]).abs() < 0.5
                        && is_dash_placeholder(&atom.text)
                })
                .count();
            if dash_count >= 2 {
                first_body_index -= 1;
            }
        }
        return Some((levels[first_body_index - 1] + levels[first_body_index]) / 2.0);
    }

    for (index, gap) in gaps.iter().copied().enumerate() {
        let repeated_header_levels = level_counts[..=index]
            .iter()
            .filter(|count| **count >= 2)
            .count();
        if index >= 2 && gap >= early_gap_threshold && repeated_header_levels >= 2 {
            return Some((levels[index] + levels[index + 1]) / 2.0);
        }
    }

    for index in 2..levels.len() {
        if level_counts[index] <= 1
            && level_counts[index - 1] >= 2
            && level_counts[..index]
                .iter()
                .filter(|count| **count >= 2)
                .count()
                >= 2
        {
            return Some((levels[index - 1] + levels[index]) / 2.0);
        }
    }

    let (index, gap) = gaps
        .iter()
        .copied()
        .enumerate()
        .max_by(|(_, left), (_, right)| {
            left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal)
        })?;
    let minimum_gap = if levels.len() == 3 {
        12.0_f64.max(minimum_gap * 1.8)
    } else {
        9.0_f64.max(median_gap * 2.0)
    };
    if gap < minimum_gap {
        let top = levels[0];
        let bottom = *levels.last()?;
        let upper_limit = top + (bottom - top) * 0.48;
        let unit_levels: Vec<f64> = levels
            .iter()
            .copied()
            .filter(|level| {
                *level <= upper_limit
                    && ordered
                        .iter()
                        .filter(|atom| (center_y(&atom.rect) - level).abs() < 0.5)
                        .filter(|atom| is_structural_header_text(&atom.text))
                        .count()
                        >= 2
            })
            .collect();
        if let Some(level) = unit_levels.last() {
            return Some(*level + 1.5);
        }
        return None;
    }
    Some((levels[index] + levels[index + 1]) / 2.0)
}

fn rescue_header_only_bands(atoms: &[AtomDto], bands: Vec<ColumnBandDto>) -> Vec<ColumnBandDto> {
    let Some(header_cutoff) = infer_header_cutoff(atoms) else {
        return bands;
    };
    let mut rescued = bands;
    let mut stable = rescued.clone();
    stable.sort_by(|left, right| {
        left.x0
            .partial_cmp(&right.x0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if stable.len() < 2 {
        return stable;
    }

    let left = &stable[0];
    let right = &stable[1];
    let header_atoms: Vec<&AtomDto> = atoms
        .iter()
        .filter(|atom| center_y(&atom.rect) <= header_cutoff)
        .collect();
    let has_left = header_atoms.iter().any(|atom| {
        horizontal_overlap(
            &atom.rect,
            &Rect4 {
                schema_version: 1,
                x0: left.x0,
                y0: 0.0,
                x1: left.x1,
                y1: 1.0,
            },
        ) >= 5.5
    });
    let has_right = header_atoms.iter().any(|atom| {
        horizontal_overlap(
            &atom.rect,
            &Rect4 {
                schema_version: 1,
                x0: right.x0,
                y0: 0.0,
                x1: right.x1,
                y1: 1.0,
            },
        ) >= 5.5
    });
    if !has_left || !has_right {
        return stable;
    }

    for atom in header_atoms {
        if !is_note_reference(&atom.text)
            || atom.rect.x0 < left.x1
            || atom.rect.x1 > right.x0
            || atom.rect.x1 <= atom.rect.x0
        {
            continue;
        }
        let overlaps_existing = rescued
            .iter()
            .any(|band| (atom.rect.x1.min(band.x1) - atom.rect.x0.max(band.x0)).max(0.0) > 0.0);
        if overlaps_existing {
            continue;
        }
        rescued.push(ColumnBandDto {
            schema_version: 1,
            x0: atom.rect.x0,
            x1: atom.rect.x1,
            source_atoms: vec![atom.order],
            order: 0,
        });
    }

    rescued.sort_by(|left, right| {
        left.x0
            .partial_cmp(&right.x0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    for (order, band) in rescued.iter_mut().enumerate() {
        band.order = order as i64;
    }
    rescued
}

fn cell_from_physical(cell: PhysicalCell, bands: &[ColumnBandDto]) -> CellDto {
    let (col_start, col_end) = physical_cell_span(&cell, bands);
    CellDto {
        schema_version: 1,
        text: cell.text.clone(),
        row: cell.row,
        col: col_start as i64,
        rect: Rect4 {
            schema_version: 1,
            x0: cell.rect.x0,
            y0: cell.rect.y0,
            x1: cell.rect.x1,
            y1: cell.rect.y1,
        },
        rowspan: 1,
        colspan: (col_end - col_start + 1) as i64,
        source: Some(cell),
    }
}

fn merge_vertical_continuations(cells: &mut Vec<CellDto>, header_rows: usize) {
    cells.sort_by(|left, right| {
        left.row
            .cmp(&right.row)
            .then_with(|| left.col.cmp(&right.col))
            .then_with(|| {
                left.rect
                    .y0
                    .partial_cmp(&right.rect.y0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut index = 0;
    while index < cells.len() {
        if cells[index].row as usize >= header_rows
            || cells[index].text.trim().is_empty()
            || cells[index].colspan != 1
            || cells[index].rowspan != 1
        {
            index += 1;
            continue;
        }

        let current = cells[index].clone();
        let mut candidate_index = None;
        for (other_index, candidate) in cells.iter().enumerate().skip(index + 1) {
            if candidate.row as usize >= header_rows
                || candidate.text.trim().is_empty()
                || candidate.col != current.col
                || candidate.colspan != 1
                || candidate.row != current.row + current.rowspan
            {
                continue;
            }
            if !source_refs_contiguous_in_interleaved_row(cells, index, other_index) {
                continue;
            }
            let overlap = horizontal_overlap(&current.rect, &candidate.rect);
            let minimum_width = (current.rect.x1 - current.rect.x0)
                .min(candidate.rect.x1 - candidate.rect.x0)
                .max(1.0);
            let vertical_gap = candidate.rect.y0 - current.rect.y1;
            if overlap < minimum_width * 0.45 || vertical_gap > 6.0 {
                continue;
            }
            let blocked = cells.iter().enumerate().any(|(blocked_index, middle)| {
                blocked_index != index
                    && blocked_index != other_index
                    && !middle.text.trim().is_empty()
                    && middle.col == current.col
                    && middle.rect.y0 >= current.rect.y1
                    && middle.rect.y1 <= candidate.rect.y0
            });
            if !blocked {
                candidate_index = Some(other_index);
                break;
            }
        }

        let Some(other_index) = candidate_index else {
            index += 1;
            continue;
        };

        let candidate = cells.remove(other_index);
        let current = &mut cells[index];
        current.text = format!("{}\n{}", current.text.trim(), candidate.text.trim());
        current.rect = rect_union(&current.rect, &candidate.rect);
        current.rowspan = candidate.row + candidate.rowspan - current.row;
        if let Some(source) = current.source.as_mut() {
            if let Some(candidate_source) = candidate.source {
                source.text = current.text.clone();
                source.rect = rect_union(&source.rect, &candidate_source.rect);
                source.source_refs.extend(candidate_source.source_refs);
            }
        }
    }
}

fn cell_overlaps_column(cell: &CellDto, col: usize) -> bool {
    let start = cell.col.max(0) as usize;
    let end = start.saturating_add(cell.colspan.max(1) as usize);
    start <= col && col < end
}

fn is_numeric_body_text(text: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return false;
    }
    let mut has_digit = false;
    for character in trimmed.chars() {
        if character.is_ascii_digit() {
            has_digit = true;
            continue;
        }
        if matches!(
            character,
            ',' | '.' | '%' | '+' | '-' | '(' | ')' | '（' | '）' | '—' | '–' | '−'
        ) {
            continue;
        }
        return false;
    }
    has_digit
        || trimmed
            .chars()
            .all(|character| matches!(character, '-' | '—' | '–' | '−'))
}

fn header_body_start(cells: &[CellDto], physical_rows: usize, columns: usize) -> usize {
    if physical_rows <= 2 {
        return physical_rows;
    }
    let minimum = (columns * 3 / 4).max(2);
    if let Some(row) = (1..physical_rows).find(|row| {
        cells
            .iter()
            .filter(|cell| cell.row as usize == *row && is_numeric_body_text(&cell.text))
            .count()
            >= 2
    }) {
        return row;
    }
    (1..physical_rows)
        .find(|row| {
            cells
                .iter()
                .filter(|cell| cell.row as usize == *row && !cell.text.trim().is_empty())
                .count()
                >= minimum
        })
        .unwrap_or(physical_rows)
}

fn find_wrapped_header_row(cells: &[CellDto], body_start: usize) -> Option<usize> {
    if body_start < 3 {
        return None;
    }
    for row in 1..body_start.saturating_sub(1) {
        let current: Vec<&CellDto> = cells
            .iter()
            .filter(|cell| cell.row as usize == row && !cell.text.trim().is_empty())
            .collect();
        let next: Vec<&CellDto> = cells
            .iter()
            .filter(|cell| cell.row as usize == row + 1 && !cell.text.trim().is_empty())
            .collect();
        if current.len() < 2 || next.len() < 2 {
            continue;
        }
        let wrapped = next
            .iter()
            .filter(|cell| {
                cell.text.contains('\n')
                    && cell.rect.y1 - cell.rect.y0
                        > current
                            .iter()
                            .map(|item| item.rect.y1 - item.rect.y0)
                            .fold(0.0, f64::max)
                            * 1.35
            })
            .count();
        if wrapped < 2 {
            continue;
        }
        let disjoint = next.iter().all(|candidate| {
            !current.iter().any(|parent| {
                parent.col <= candidate.col + candidate.colspan.max(1) - 1
                    && candidate.col <= parent.col + parent.colspan.max(1) - 1
            })
        });
        if disjoint {
            return Some(row + 1);
        }
    }
    None
}

fn mapped_header_row(
    row: usize,
    body_start: usize,
    leaf_row: usize,
    collapse: bool,
    wrapped_row: Option<usize>,
) -> usize {
    if let Some(collapsed_row) = wrapped_row {
        return row.saturating_sub(usize::from(row >= collapsed_row));
    }
    logical_row_mapping(row, body_start, leaf_row, collapse)
}

fn logical_row_mapping(row: usize, body_start: usize, leaf_row: usize, collapse: bool) -> usize {
    if !collapse {
        return row;
    }
    if row < leaf_row {
        0
    } else if row == leaf_row {
        1
    } else {
        2 + row.saturating_sub(body_start)
    }
}

fn physical_row_tracks(rows: &[RowClusterDto], atoms: &[AtomDto]) -> Vec<f64> {
    rows.iter()
        .map(|row| {
            let centers: Vec<f64> = row
                .item_indices
                .iter()
                .filter_map(|order| {
                    atoms
                        .iter()
                        .find(|atom| atom.order == *order)
                        .map(|atom| center_y(&atom.rect))
                })
                .collect();
            if centers.is_empty() {
                return (row.y0 + row.y1) / 2.0;
            }
            let mean = centers.iter().sum::<f64>() / centers.len() as f64;
            (mean * 100.0).round() / 100.0
        })
        .collect()
}

fn logical_row_edges(
    rows: &[RowClusterDto],
    region: &Rect4,
    body_start: usize,
    leaf_row: usize,
    collapse: bool,
    wrapped_row: Option<usize>,
    row_tracks: Option<&[f64]>,
) -> Vec<f64> {
    if rows.is_empty() {
        return vec![region.y0, region.y1];
    }
    let logical_count = if wrapped_row.is_some() {
        rows.len().saturating_sub(1)
    } else if collapse {
        2 + rows.len().saturating_sub(body_start)
    } else {
        rows.len()
    };
    let mut ranges = vec![(f64::INFINITY, f64::NEG_INFINITY); logical_count];
    for (row_index, row) in rows.iter().enumerate() {
        let logical = mapped_header_row(row_index, body_start, leaf_row, collapse, wrapped_row);
        if logical >= ranges.len() {
            continue;
        }
        ranges[logical].0 = ranges[logical].0.min(row.y0);
        ranges[logical].1 = ranges[logical].1.max(row.y1);
    }

    let mut tracks: Vec<Vec<f64>> = vec![Vec::new(); ranges.len()];
    for (row_index, row) in rows.iter().enumerate() {
        let logical = mapped_header_row(row_index, body_start, leaf_row, collapse, wrapped_row);
        if logical < tracks.len() {
            tracks[logical].push(
                row_tracks
                    .and_then(|values| values.get(row_index).copied())
                    .unwrap_or((row.y0 + row.y1) / 2.0),
            );
        }
    }

    let mut edges = vec![region.y0];
    for index in 0..ranges.len().saturating_sub(1) {
        let left = tracks[index]
            .iter()
            .copied()
            .reduce(|sum, value| sum + value)
            .map(|sum| sum / tracks[index].len() as f64)
            .or_else(|| ranges[index].1.is_finite().then_some(ranges[index].1))
            .unwrap_or(region.y0);
        let right = tracks[index + 1]
            .iter()
            .copied()
            .reduce(|sum, value| sum + value)
            .map(|sum| sum / tracks[index + 1].len() as f64)
            .or_else(|| {
                ranges[index + 1]
                    .0
                    .is_finite()
                    .then_some(ranges[index + 1].0)
            })
            .unwrap_or(left);
        edges.push((left + right) / 2.0);
    }
    edges.push(region.y1);
    edges
}

fn normalize_header_layout(
    cells: &mut Vec<CellDto>,
    rows: &[RowClusterDto],
    bands: &[ColumnBandDto],
    region: &Rect4,
    row_tracks: Option<&[f64]>,
) -> Vec<f64> {
    let physical_rows = rows.len();
    if physical_rows == 0 || bands.is_empty() {
        return vec![region.y0, region.y1];
    }
    let body_start = header_body_start(cells, physical_rows, bands.len());
    let leaf_row = (0..body_start)
        .rev()
        .find(|row| {
            cells
                .iter()
                .filter(|cell| cell.row as usize == *row && !cell.text.trim().is_empty())
                .count()
                >= 2
        })
        .unwrap_or(body_start.saturating_sub(1));

    let wrapped_row = find_wrapped_header_row(cells, body_start);
    let collapse = wrapped_row.is_none()
        && body_start < physical_rows
        && leaf_row >= 2
        && cells
            .iter()
            .filter(|cell| {
                cell.row as usize == leaf_row.saturating_sub(1) && !cell.text.trim().is_empty()
            })
            .count()
            >= 2;
    for cell in cells.iter_mut() {
        let physical_start = cell.row.max(0) as usize;
        let physical_end = physical_start
            .saturating_add(cell.rowspan.max(1) as usize)
            .saturating_sub(1);
        let logical_start =
            mapped_header_row(physical_start, body_start, leaf_row, collapse, wrapped_row);
        let logical_end = mapped_header_row(
            physical_end.min(physical_rows.saturating_sub(1)),
            body_start,
            leaf_row,
            collapse,
            wrapped_row,
        );
        cell.row = logical_start as i64;
        cell.rowspan = logical_end.saturating_sub(logical_start) as i64 + 1;
    }

    let logical_rows = if wrapped_row.is_some() {
        physical_rows.saturating_sub(1)
    } else if collapse {
        2 + physical_rows.saturating_sub(body_start)
    } else {
        physical_rows
    };
    if collapse && logical_rows >= 2 {
        for index in 0..cells.len() {
            if cells[index].row != 0 || cells[index].text.trim().is_empty() {
                continue;
            }
            let end = cells[index].col.saturating_add(cells[index].colspan.max(1));
            let has_child = cells.iter().enumerate().any(|(other_index, child)| {
                other_index != index
                    && child.row == 1
                    && !child.text.trim().is_empty()
                    && (cells[index].col..end)
                        .any(|column| cell_overlaps_column(child, column.max(0) as usize))
            });
            if !has_child && cells[index].rowspan == 1 {
                cells[index].rowspan = 2;
            }
        }
    }

    if logical_rows >= 2 {
        let header_rows = if let Some(collapsed_row) = wrapped_row {
            body_start.saturating_sub(usize::from(collapsed_row < body_start))
        } else {
            mapped_header_row(body_start, body_start, leaf_row, collapse, wrapped_row)
        };
        let parents: Vec<(usize, usize, usize)> = cells
            .iter()
            .filter(|cell| cell.row >= 0 && (cell.row as usize) < header_rows && cell.colspan > 1)
            .map(|cell| {
                (
                    cell.row as usize,
                    cell.col.max(0) as usize,
                    cell.col.saturating_add(cell.colspan.max(1)) as usize,
                )
            })
            .collect();
        for (parent_row, parent_start, parent_end) in parents {
            let Some(leaf_row) = (parent_row + 1..header_rows).find(|row| {
                let child_columns: Vec<usize> = cells
                    .iter()
                    .filter(|cell| {
                        cell.row as usize == *row
                            && !cell.text.trim().is_empty()
                            && cell.colspan == 1
                            && (cell.col as usize) >= parent_start
                            && (cell.col as usize) < parent_end
                    })
                    .map(|cell| cell.col as usize)
                    .collect();
                child_columns.len() == parent_end - parent_start
                    && child_columns
                        .iter()
                        .copied()
                        .collect::<std::collections::BTreeSet<_>>()
                        .len()
                        == child_columns.len()
            }) else {
                continue;
            };
            let grouped_columns: std::collections::BTreeSet<usize> =
                (parent_start..parent_end).collect();
            let snapshot = cells.clone();
            for index in 0..cells.len() {
                let cell = &snapshot[index];
                if cell.text.trim().is_empty()
                    || cell.colspan != 1
                    || cell.row as usize >= header_rows
                    || grouped_columns.contains(&(cell.col.max(0) as usize))
                {
                    continue;
                }
                let column = cell.col.max(0) as usize;
                let only_occupant = snapshot.iter().enumerate().all(|(other_index, other)| {
                    other_index == index
                        || other.text.trim().is_empty()
                        || other.col as usize > column
                        || other.col.saturating_add(other.colspan.max(1)) as usize <= column
                        || other.row as usize > leaf_row
                        || other.row.saturating_add(other.rowspan.max(1)) as usize <= parent_row
                });
                if only_occupant {
                    cells[index].row = parent_row as i64;
                    cells[index].rowspan = (leaf_row - parent_row + 1) as i64;
                }
            }
        }
    }

    logical_row_edges(
        rows,
        region,
        body_start,
        leaf_row,
        collapse,
        wrapped_row,
        row_tracks,
    )
}

fn rebuild_occupancy_indices(
    cells: &[CellDto],
    rows: usize,
    cols: usize,
) -> (Vec<Vec<Option<i64>>>, Vec<(usize, usize)>) {
    let mut occupancy = vec![vec![None; cols]; rows];
    let mut conflicts = Vec::new();

    for (cell_index, cell) in cells.iter().enumerate() {
        let row_start = cell.row.max(0) as usize;
        let col_start = cell.col.max(0) as usize;
        let row_end = row_start.saturating_add(cell.rowspan.max(1) as usize);
        let col_end = col_start.saturating_add(cell.colspan.max(1) as usize);
        for row in row_start..row_end {
            for col in col_start..col_end {
                if row >= rows || col >= cols {
                    continue;
                }
                if occupancy[row][col].is_some() {
                    conflicts.push((row, col));
                    continue;
                }
                occupancy[row][col] = Some(cell_index as i64);
            }
        }
    }

    (occupancy, conflicts)
}

pub fn build_logical_grid(atoms: Vec<AtomDto>, grid: GridDto) -> LogicalGridDto {
    let mut grid = grid;
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
    let (occupancy, _) = rebuild_occupancy_indices(&cells, rows, cols);
    grid.occupancy = occupancy;

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
    let bands = rescue_header_only_bands(&input.atoms, bands);

    let (rows, bands, mut phys_cells, mut diags) = build_grid(input.atoms.clone(), bands);
    merge_physical_inline_fragments(&mut phys_cells);

    let mut cells = Vec::new();

    for pc in phys_cells {
        let r = pc.row.max(0) as usize;
        let c = pc.col.max(0) as usize;
        if r >= rows.len() || c >= bands.len() {
            continue;
        }
        cells.push(cell_from_physical(pc, &bands));
    }

    merge_source_contiguous_vertical_cells(&mut cells);

    let physical_rows = rows.len();
    let physical_cols = bands.len();
    let body_start = header_body_start(&cells, physical_rows, physical_cols);
    merge_vertical_continuations(&mut cells, body_start);
    let row_tracks = physical_row_tracks(&rows, &input.atoms);
    let row_edges = normalize_header_layout(
        &mut cells,
        &rows,
        &bands,
        &input.region.rect,
        Some(&row_tracks),
    );
    let num_rows = if row_edges.len() > 1 {
        row_edges.len() - 1
    } else {
        1
    };
    let num_cols = bands.len().max(1);
    let col_edges = logical_column_edges(&bands, &input.region.rect);

    let (mut occupancy, conflicts) = rebuild_occupancy_indices(&cells, num_rows, num_cols);
    for (row, col) in conflicts {
        diags.push(occupancy_conflict_diagnostic(
            "wireless_structure.recover_native_region",
            row,
            col,
        ));
    }
    let mut empty_slots = Vec::new();
    for (r, row) in occupancy.iter().enumerate() {
        for (c, slot) in row.iter().enumerate() {
            if slot.is_none() {
                empty_slots.push(vec![r as i64, c as i64]);
            }
        }
    }
    append_empty_cells(&mut cells, &mut occupancy, &row_edges, &col_edges);

    cells.sort_by(|a, b| match a.row.cmp(&b.row) {
        std::cmp::Ordering::Equal => a.col.cmp(&b.col),
        other => other,
    });
    let (occupancy, conflicts) = rebuild_occupancy_indices(&cells, num_rows, num_cols);
    for (row, col) in conflicts {
        diags.push(occupancy_conflict_diagnostic(
            "wireless_structure.recover_native_region",
            row,
            col,
        ));
    }

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
    let mut diagnostics = Vec::new();

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

    let full_page_region = Rect4 {
        schema_version: 1,
        x0: 0.0,
        y0: 0.0,
        x1: input.page.width,
        y1: input.page.height,
    };

    let target_runs: Vec<(Rect4, Vec<AtomDto>)> = if allowed_regions.is_empty() {
        let page_runs = native_span::build_text_runs(input.spans.clone(), full_page_region.clone());
        let page_atoms = native_span::build_atoms(page_runs, Some(full_page_region));
        full_page_atom_runs(page_atoms)
    } else {
        allowed_regions
            .iter()
            .cloned()
            .map(|region| {
                let runs = native_span::build_text_runs(input.spans.clone(), region.clone());
                let atoms = native_span::build_atoms(runs, Some(region.clone()));
                (region, atoms)
            })
            .collect()
    };

    for (reg, region_atoms) in target_runs {
        if region_atoms.len() < 4 {
            continue;
        }

        let bands = rescue_header_only_bands(
            &region_atoms,
            infer_column_bands(region_atoms.clone(), reg.clone()),
        );
        if bands.len() < 2 {
            continue;
        }

        let (rows, bands_out, mut phys_cells, mut region_diags) = build_grid(region_atoms, bands);
        diagnostics.append(&mut region_diags);
        if rows.len() < 2 || bands_out.len() < 2 {
            continue;
        }

        merge_physical_inline_fragments(&mut phys_cells);

        let mut cells = Vec::new();
        let num_rows = rows.len();
        let num_cols = bands_out.len();
        let mut occupancy = vec![vec![None; num_cols]; num_rows];
        let mut has_conflict = false;

        for pc in phys_cells {
            let r = pc.row as usize;
            let (col_start, col_end) = physical_cell_span(&pc, &bands_out);
            if r >= num_rows || col_start >= num_cols || col_end >= num_cols {
                continue;
            }
            let mut cell_conflict = false;
            for column in col_start..=col_end {
                if occupancy[r][column].is_some() {
                    cell_conflict = true;
                    diagnostics.push(occupancy_conflict_diagnostic(
                        "wireless_table_recovery.recover_wireless_tables",
                        r,
                        column,
                    ));
                }
            }
            if cell_conflict {
                has_conflict = true;
                continue;
            }
            let cell_index = cells.len() as i64;
            for column in col_start..=col_end {
                occupancy[r][column] = Some(cell_index);
            }
            cells.push(cell_from_physical(pc, &bands_out));
        }

        if has_conflict {
            continue;
        }

        merge_source_contiguous_vertical_cells(&mut cells);
        let (rebuilt_occupancy, conflicts) = rebuild_occupancy_indices(&cells, num_rows, num_cols);
        if !conflicts.is_empty() {
            for (row, col) in conflicts {
                diagnostics.push(occupancy_conflict_diagnostic(
                    "wireless_table_recovery.recover_wireless_tables",
                    row,
                    col,
                ));
            }
            continue;
        }
        occupancy = rebuilt_occupancy;

        let x0 = bands_out.iter().map(|b| b.x0).fold(f64::INFINITY, f64::min);
        let x1 = bands_out
            .iter()
            .map(|b| b.x1)
            .fold(f64::NEG_INFINITY, f64::max);
        let y0 = rows.iter().map(|r| r.y0).fold(f64::INFINITY, f64::min);
        let y1 = rows.iter().map(|r| r.y1).fold(f64::NEG_INFINITY, f64::max);

        append_empty_cells(
            &mut cells,
            &mut occupancy,
            &rows
                .iter()
                .map(|row| row.y0)
                .chain(std::iter::once(y1))
                .collect::<Vec<_>>(),
            &logical_column_edges(&bands_out, &reg),
        );

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
        diagnostics,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{
        CharacterDto, NativeSpanDto, PageDto, RegionDto, SourcePositionDto, StructureConfig,
    };

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

    fn make_span(
        text: &str,
        x0: f64,
        y0: f64,
        x1: f64,
        y1: f64,
        order: i64,
        line: i64,
    ) -> NativeSpanDto {
        NativeSpanDto {
            schema_version: 1,
            text: text.to_string(),
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            font: Some("SimSun".to_string()),
            size: Some(10.0),
            flags: Some(0),
            order,
            characters: vec![CharacterDto {
                schema_version: 1,
                text: text.to_string(),
                rect: Rect4 {
                    schema_version: 1,
                    x0,
                    y0,
                    x1,
                    y1,
                },
                order,
            }],
            source_position: SourcePositionDto {
                schema_version: 1,
                block: 0,
                line,
            },
            block: 0,
            line,
        }
    }

    #[test]
    fn test_recover_wireless_tables_normalizes_split_native_spans_before_grid() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 180.0,
            y1: 50.0,
        };
        let input = WirelessRecoveryInput {
            schema_version: 1,
            page: PageDto {
                schema_version: 1,
                width: 180.0,
                height: 50.0,
                rotation: 0,
            },
            spans: vec![
                make_span("合", 10.0, 10.0, 20.0, 20.0, 0, 0),
                make_span("计", 25.0, 10.0, 35.0, 20.0, 1, 0),
                make_span("金额", 100.0, 10.0, 140.0, 20.0, 2, 0),
                make_span("项目", 10.0, 30.0, 40.0, 40.0, 3, 1),
                make_span("500", 100.0, 30.0, 130.0, 40.0, 4, 1),
            ],
            regions: vec![RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            }],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_wireless_tables(input);

        assert_eq!(output.candidates.len(), 1);
        assert!(output.candidates[0]
            .cells
            .iter()
            .any(|cell| cell.text == "合计"));
    }

    #[test]
    fn test_recover_wireless_tables_splits_separated_full_page_runs() {
        let input = WirelessRecoveryInput {
            schema_version: 1,
            page: PageDto {
                schema_version: 1,
                width: 220.0,
                height: 240.0,
                rotation: 0,
            },
            spans: vec![
                make_span("左上", 10.0, 10.0, 40.0, 20.0, 0, 0),
                make_span("右上", 100.0, 10.0, 130.0, 20.0, 1, 0),
                make_span("左下", 10.0, 30.0, 40.0, 40.0, 2, 1),
                make_span("右下", 100.0, 30.0, 130.0, 40.0, 3, 1),
                make_span("第二左上", 10.0, 160.0, 50.0, 170.0, 4, 2),
                make_span("第二右上", 100.0, 160.0, 150.0, 170.0, 5, 2),
                make_span("第二左下", 10.0, 180.0, 50.0, 190.0, 6, 3),
                make_span("第二右下", 100.0, 180.0, 150.0, 190.0, 7, 3),
            ],
            regions: Vec::new(),
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_wireless_tables(input);

        assert_eq!(output.candidates.len(), 2);
        assert_eq!(
            output
                .candidates
                .iter()
                .map(|candidate| candidate.rows)
                .collect::<Vec<_>>(),
            vec![2, 2]
        );
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

    #[test]
    fn test_build_grid_clusters_short_and_wrapped_headers_in_one_visual_row() {
        let bands = (0..5)
            .map(|index| ColumnBandDto {
                schema_version: 1,
                x0: index as f64 * 90.0,
                x1: index as f64 * 90.0 + 70.0,
                source_atoms: Vec::new(),
                order: index,
            })
            .collect();
        let atoms = vec![
            make_atom("阶段一", 100.0, 347.9, 148.0, 359.9, 0),
            make_atom("阶段二", 190.0, 347.9, 238.0, 359.9, 1),
            make_atom("阶段三", 280.0, 347.9, 328.0, 359.9, 2),
            make_atom("坏账准备", 10.0, 371.2, 58.0, 383.2, 3),
            make_atom("未来12个月\n预期信用损失", 100.0, 371.0, 172.0, 399.5, 4),
            make_atom(
                "整个存续期预\n期信用损失(未\n发生信用减值)",
                185.0,
                364.1,
                263.0,
                408.2,
                5,
            ),
            make_atom(
                "整个存续期预\n期信用损失(已\n发生信用减值)",
                275.0,
                364.1,
                353.0,
                408.2,
                6,
            ),
            make_atom("合计", 365.0, 371.2, 389.0, 383.2, 7),
            make_atom("期初余额", 10.0, 412.0, 58.0, 424.0, 8),
            make_atom("667,671.47", 100.0, 411.0, 152.0, 424.7, 9),
            make_atom("--", 190.0, 411.0, 199.0, 424.7, 10),
            make_atom("--", 280.0, 411.0, 289.0, 424.7, 11),
            make_atom("667,671.47", 370.0, 411.0, 420.0, 424.7, 12),
        ];

        let (rows, _, cells, diagnostics) = build_grid(atoms, bands);

        assert_eq!(rows.len(), 3);
        assert_eq!(cells.len(), 13);
        assert!(diagnostics.is_empty());
    }

    #[test]
    fn test_recover_native_region_does_not_merge_header_across_empty_physical_slot() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 120.0,
        };
        let bands = (0..5)
            .map(|index| ColumnBandDto {
                schema_version: 1,
                x0: index as f64 * 100.0,
                x1: index as f64 * 100.0 + 80.0,
                source_atoms: Vec::new(),
                order: index,
            })
            .collect();
        let atoms = vec![
            make_atom("阶段一", 110.0, 5.0, 150.0, 15.0, 0),
            make_atom("阶段二", 210.0, 5.0, 250.0, 15.0, 1),
            make_atom("阶段三", 310.0, 5.0, 350.0, 15.0, 2),
            make_atom("坏账准备", 10.0, 25.0, 55.0, 35.0, 3),
            make_atom("未来12个月\n预期信用损失", 110.0, 25.0, 175.0, 53.0, 4),
            make_atom(
                "整个存续期预\n期信用损失(未\n发生信用减值)",
                210.0,
                21.0,
                275.0,
                61.0,
                5,
            ),
            make_atom(
                "整个存续期预\n期信用损失(已\n发生信用减值)",
                310.0,
                21.0,
                375.0,
                61.0,
                6,
            ),
            make_atom("合计", 410.0, 25.0, 445.0, 35.0, 7),
            make_atom("期初余额", 10.0, 70.0, 55.0, 80.0, 8),
            make_atom("100", 110.0, 70.0, 145.0, 80.0, 9),
            make_atom("--", 210.0, 70.0, 225.0, 80.0, 10),
            make_atom("--", 310.0, 70.0, 325.0, 80.0, 11),
            make_atom("100", 410.0, 70.0, 445.0, 80.0, 12),
        ];
        let output = recover_native_region(NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms,
            bands,
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        });

        let stage_two = output
            .cells
            .iter()
            .find(|cell| cell.text.starts_with("阶段二"))
            .expect("stage-two header must remain a separate cell");
        let child = output
            .cells
            .iter()
            .find(|cell| cell.text.starts_with("整个存续期预"));
        assert!(
            child.is_some(),
            "wrapped child header must remain visible: {:?}",
            output
                .cells
                .iter()
                .map(|cell| (cell.row, cell.col, cell.rowspan, cell.text.clone()))
                .collect::<Vec<_>>()
        );
        let child = child.unwrap();
        assert_eq!((stage_two.row, stage_two.rowspan), (0, 1));
        assert_eq!(child.row, 1);
        assert!(!output
            .diagnostics
            .iter()
            .any(|item| item.status == "occupancy_conflict"));
    }

    #[test]
    fn test_merge_vertical_continuation_requires_adjacent_contiguous_source() {
        let source = |text: &str, row: i64, y0: f64, source_ref: i64| PhysicalCell {
            schema_version: 1,
            text: text.to_string(),
            rect: Rect4 {
                schema_version: 1,
                x0: 10.0,
                y0,
                x1: 70.0,
                y1: y0 + 10.0,
            },
            row,
            col: 0,
            source_refs: vec![source_ref],
        };
        let mut cells = vec![
            CellDto {
                schema_version: 1,
                text: "上半部".to_string(),
                row: 0,
                col: 0,
                rect: source("上半部", 0, 10.0, 1).rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(source("上半部", 0, 10.0, 1)),
            },
            CellDto {
                schema_version: 1,
                text: "下半部".to_string(),
                row: 1,
                col: 0,
                rect: source("下半部", 1, 22.0, 2).rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(source("下半部", 1, 22.0, 2)),
            },
        ];

        merge_vertical_continuations(&mut cells, 3);

        assert_eq!(cells.len(), 1);
        assert_eq!(cells[0].text, "上半部\n下半部");
        assert_eq!(cells[0].rowspan, 2);
    }

    #[test]
    fn test_infer_column_bands_ignores_singleton_artifact_atoms() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 300.0,
            y1: 100.0,
        };
        let atoms = vec![
            make_atom("left", 10.0, 10.0, 40.0, 20.0, 0),
            make_atom("left2", 10.0, 40.0, 40.0, 50.0, 1),
            make_atom("middle", 100.0, 10.0, 130.0, 20.0, 2),
            make_atom("middle2", 100.0, 40.0, 130.0, 50.0, 3),
            make_atom("right", 200.0, 10.0, 230.0, 20.0, 4),
            make_atom("right2", 200.0, 40.0, 230.0, 50.0, 5),
            make_atom("artifact", 55.0, 40.0, 65.0, 50.0, 6),
        ];

        let bands = infer_column_bands(atoms, region);

        assert_eq!(bands.len(), 3);
    }

    #[test]
    fn test_recover_native_region_assigns_dash_to_right_aligned_numeric_track() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 100.0,
            y1: 100.0,
        };
        let input = NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("项目", 5.0, 5.0, 20.0, 15.0, 0),
                make_atom("金额", 44.0, 5.0, 52.0, 15.0, 1),
                make_atom("项目", 5.0, 20.0, 20.0, 30.0, 2),
                make_atom("金额", 44.0, 20.0, 52.0, 30.0, 3),
                make_atom("100", 44.0, 50.0, 52.0, 60.0, 4),
                make_atom("200", 44.0, 70.0, 52.0, 80.0, 5),
                make_atom("-", 49.0, 90.0, 55.0, 100.0, 6),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 0.0,
                    x1: 50.0,
                    source_atoms: vec![0, 2],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 48.0,
                    x1: 55.0,
                    source_atoms: vec![1, 3],
                    order: 1,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_native_region(input);
        let dash = output
            .cells
            .iter()
            .find(|cell| cell.text == "-")
            .expect("dash cell");
        assert_eq!(dash.col, 0);
    }

    #[test]
    fn test_recover_native_region_keeps_single_stub_header_row() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 120.0,
        };
        let bands = (0..5)
            .map(|index| ColumnBandDto {
                schema_version: 1,
                x0: index as f64 * 100.0,
                x1: index as f64 * 100.0 + 80.0,
                source_atoms: Vec::new(),
                order: index,
            })
            .collect();
        let atoms = vec![
            make_atom("年末数", 110.0, 5.0, 150.0, 15.0, 0),
            make_atom("年初数", 310.0, 5.0, 350.0, 15.0, 1),
            make_atom("（1）项目", 5.0, 25.0, 70.0, 35.0, 2),
            make_atom("金额", 110.0, 45.0, 150.0, 55.0, 3),
            make_atom("跌价准备", 210.0, 45.0, 270.0, 55.0, 4),
            make_atom("金额", 310.0, 45.0, 350.0, 55.0, 5),
            make_atom("跌价准备", 410.0, 45.0, 470.0, 55.0, 6),
            make_atom("开发成本", 5.0, 65.0, 70.0, 75.0, 7),
            make_atom("100", 110.0, 65.0, 150.0, 75.0, 8),
            make_atom("---", 210.0, 65.0, 240.0, 75.0, 9),
            make_atom("98", 310.0, 65.0, 350.0, 75.0, 10),
            make_atom("---", 410.0, 65.0, 440.0, 75.0, 11),
            make_atom("合计", 5.0, 85.0, 45.0, 95.0, 12),
            make_atom("100", 110.0, 85.0, 150.0, 95.0, 13),
            make_atom("---", 210.0, 85.0, 240.0, 95.0, 14),
            make_atom("98", 310.0, 85.0, 350.0, 95.0, 15),
            make_atom("---", 410.0, 85.0, 440.0, 95.0, 16),
        ];
        let output = recover_native_region(NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms,
            bands,
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        });

        assert_eq!((output.grid.grid.rows, output.grid.grid.cols), (5, 5));
        let stub = output
            .cells
            .iter()
            .find(|cell| cell.text == "（1）项目")
            .expect("single stub header");
        assert_eq!((stub.row, stub.rowspan), (1, 1));
    }

    #[test]
    fn test_recover_native_region_rebuilds_occupancy_after_cell_sort() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 200.0,
            y1: 40.0,
        };
        let input = NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region.clone(),
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("right", 100.0, 10.0, 140.0, 20.0, 0),
                make_atom("left", 10.0, 10.0, 40.0, 20.0, 1),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 0.0,
                    x1: 60.0,
                    source_atoms: vec![1],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 80.0,
                    x1: 160.0,
                    source_atoms: vec![0],
                    order: 1,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_native_region(input);

        for (row_index, row) in output.grid.grid.occupancy.iter().enumerate() {
            for (col_index, cell_index) in row.iter().enumerate() {
                let cell = &output.cells[cell_index.unwrap() as usize];
                assert_eq!(cell.row, row_index as i64);
                assert_eq!(cell.col, col_index as i64);
                assert_eq!(cell.rowspan, 1);
                assert_eq!(cell.colspan, 1);
            }
        }
    }

    #[test]
    fn test_recover_native_region_does_not_promote_edge_overlap_to_colspan() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 220.0,
            y1: 50.0,
        };
        let input = NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("left", 10.0, 5.0, 30.0, 15.0, 0),
                make_atom("edge", 122.0, 5.0, 145.0, 15.0, 1),
                make_atom("right", 150.0, 5.0, 180.0, 15.0, 2),
                make_atom("left2", 10.0, 25.0, 30.0, 35.0, 3),
                make_atom("middle2", 90.0, 25.0, 115.0, 35.0, 4),
                make_atom("right2", 150.0, 25.0, 180.0, 35.0, 5),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 0.0,
                    x1: 80.0,
                    source_atoms: vec![0, 3],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 75.0,
                    x1: 140.0,
                    source_atoms: vec![1, 4],
                    order: 1,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 135.0,
                    x1: 210.0,
                    source_atoms: vec![2, 5],
                    order: 2,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_native_region(input);

        let edge = output
            .cells
            .iter()
            .find(|cell| cell.text == "edge")
            .expect("edge cell");
        assert_eq!((edge.row, edge.col, edge.colspan), (0, 1, 1));
        assert!(!output
            .diagnostics
            .iter()
            .any(|item| item.status == "occupancy_conflict"));
    }

    #[test]
    fn test_recover_native_region_merges_source_contiguous_same_slot_fragments() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 200.0,
            y1: 50.0,
        };
        let input = NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("合", 10.0, 5.0, 20.0, 15.0, 0),
                make_atom("计", 40.0, 5.0, 50.0, 15.0, 1),
                make_atom("金额", 110.0, 5.0, 140.0, 15.0, 2),
                make_atom("项目", 10.0, 25.0, 40.0, 35.0, 3),
                make_atom("500", 110.0, 25.0, 140.0, 35.0, 4),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 0.0,
                    x1: 80.0,
                    source_atoms: vec![0, 1, 3],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 100.0,
                    x1: 160.0,
                    source_atoms: vec![2, 4],
                    order: 1,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_native_region(input);

        let merged = output
            .cells
            .iter()
            .find(|cell| cell.text == "合计")
            .expect("merged same-slot fragment");
        assert_eq!((merged.row, merged.col, merged.colspan), (0, 0, 1));
        assert!(!output
            .diagnostics
            .iter()
            .any(|item| item.status == "occupancy_conflict"));
    }

    #[test]
    fn test_recover_native_region_merges_source_contiguous_multiline_body_cell() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 200.0,
            y1: 70.0,
        };
        let input = NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("长标题", 10.0, 5.0, 55.0, 15.0, 0),
                make_atom("续行", 10.0, 20.0, 35.0, 30.0, 1),
                make_atom("100", 110.0, 5.0, 140.0, 15.0, 2),
                make_atom("200", 110.0, 20.0, 140.0, 30.0, 3),
                make_atom("项目", 10.0, 35.0, 40.0, 45.0, 4),
                make_atom("300", 110.0, 35.0, 140.0, 45.0, 5),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 0.0,
                    x1: 80.0,
                    source_atoms: vec![0, 1, 4],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 100.0,
                    x1: 160.0,
                    source_atoms: vec![2, 3, 5],
                    order: 1,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_native_region(input);

        let merged = output
            .cells
            .iter()
            .find(|cell| cell.text == "长标题\n续行")
            .expect("merged multiline body cell");
        assert_eq!((merged.row, merged.col, merged.rowspan), (0, 0, 2));
    }

    #[test]
    fn test_recover_native_region_rescues_header_only_note_band_between_stable_columns() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 300.0,
            y1: 70.0,
        };
        let input = NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("项目", 10.0, 5.0, 40.0, 15.0, 0),
                make_atom("45(b)", 120.0, 5.0, 145.0, 15.0, 1),
                make_atom("金额", 210.0, 5.0, 250.0, 15.0, 2),
                make_atom("甲", 10.0, 30.0, 30.0, 40.0, 3),
                make_atom("100", 210.0, 30.0, 245.0, 40.0, 4),
                make_atom("乙", 10.0, 50.0, 30.0, 60.0, 5),
                make_atom("200", 210.0, 50.0, 245.0, 60.0, 6),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 0.0,
                    x1: 90.0,
                    source_atoms: vec![0, 3, 5],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 190.0,
                    x1: 280.0,
                    source_atoms: vec![2, 4, 6],
                    order: 1,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = recover_native_region(input);

        assert_eq!(output.grid.grid.cols, 3);
        let note = output
            .cells
            .iter()
            .find(|cell| cell.text == "45(b)")
            .expect("rescued header-only note");
        assert_eq!(
            (note.row, note.col, note.rowspan, note.colspan),
            (0, 1, 1, 1)
        );
        assert!(!output
            .diagnostics
            .iter()
            .any(|item| item.status == "occupancy_conflict"));
    }

    #[test]
    fn test_sparse_parent_and_wrapped_leaf_headers_share_one_logical_row() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 120.0,
        };
        let bands = (0..5)
            .map(|index| ColumnBandDto {
                schema_version: 1,
                x0: index as f64 * 100.0,
                x1: index as f64 * 100.0 + 80.0,
                source_atoms: Vec::new(),
                order: index,
            })
            .collect();
        let atoms = vec![
            make_atom("阶段一", 110.0, 5.0, 150.0, 15.0, 0),
            make_atom("阶段二", 210.0, 5.0, 250.0, 15.0, 1),
            make_atom("阶段三", 310.0, 5.0, 350.0, 15.0, 2),
            make_atom("分组", 10.0, 25.0, 45.0, 35.0, 3),
            make_atom("合计", 410.0, 25.0, 450.0, 35.0, 4),
            make_atom("子\n表头一", 110.0, 35.0, 180.0, 57.0, 5),
            make_atom("子\n表头二", 210.0, 35.0, 280.0, 57.0, 6),
            make_atom("子\n表头三", 310.0, 35.0, 380.0, 57.0, 7),
            make_atom("项目一", 10.0, 70.0, 60.0, 80.0, 8),
            make_atom("100", 110.0, 70.0, 140.0, 80.0, 9),
            make_atom("--", 210.0, 70.0, 230.0, 80.0, 10),
            make_atom("--", 310.0, 70.0, 330.0, 80.0, 11),
            make_atom("100", 410.0, 70.0, 440.0, 80.0, 12),
            make_atom("项目二", 10.0, 90.0, 60.0, 100.0, 13),
            make_atom("200", 110.0, 90.0, 140.0, 100.0, 14),
            make_atom("--", 210.0, 90.0, 230.0, 100.0, 15),
            make_atom("--", 310.0, 90.0, 330.0, 100.0, 16),
            make_atom("200", 410.0, 90.0, 440.0, 100.0, 17),
        ];
        let output = recover_native_region(NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms,
            bands,
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        });

        assert_eq!((output.grid.grid.rows, output.grid.grid.cols), (4, 5));
        let logical_header: Vec<String> = output
            .cells
            .iter()
            .filter(|cell| cell.row == 1)
            .map(|cell| cell.text.clone())
            .collect();
        assert_eq!(
            logical_header,
            vec![
                "分组".to_string(),
                "子\n表头一".to_string(),
                "子\n表头二".to_string(),
                "子\n表头三".to_string(),
                "合计".to_string(),
            ]
        );
    }

    #[test]
    fn test_financial_header_promotes_only_uncovered_stub_columns() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 100.0,
        };
        let bands = (0..7)
            .map(|index| ColumnBandDto {
                schema_version: 1,
                x0: index as f64 * 70.0,
                x1: index as f64 * 70.0 + 50.0,
                source_atoms: Vec::new(),
                order: index,
            })
            .collect();
        let atoms = vec![
            make_atom("项目", 10.0, 5.0, 40.0, 15.0, 0),
            make_atom("本期增减变动", 280.0, 5.0, 390.0, 15.0, 1),
            make_atom("追加投资", 220.0, 20.0, 260.0, 30.0, 2),
            make_atom("减少投资", 290.0, 20.0, 340.0, 30.0, 3),
            make_atom("计提减值准备", 350.0, 20.0, 410.0, 30.0, 4),
            make_atom("其他", 420.0, 20.0, 450.0, 30.0, 5),
            make_atom("项目一", 10.0, 45.0, 50.0, 55.0, 6),
            make_atom("100", 220.0, 45.0, 250.0, 55.0, 7),
            make_atom("200", 290.0, 45.0, 320.0, 55.0, 8),
            make_atom("300", 350.0, 45.0, 380.0, 55.0, 9),
            make_atom("400", 420.0, 45.0, 450.0, 55.0, 10),
        ];
        let output = recover_native_region(NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms,
            bands,
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        });

        let additional = output
            .cells
            .iter()
            .find(|cell| cell.text == "追加投资")
            .expect("追加投资 header");
        let other = output
            .cells
            .iter()
            .find(|cell| cell.text == "其他")
            .expect("其他 header");
        assert_eq!((additional.row, additional.rowspan), (0, 2));
        assert_eq!((other.row, other.rowspan), (0, 2));
        assert!(!output
            .diagnostics
            .iter()
            .any(|item| item.status == "occupancy_conflict"));
    }

    #[test]
    fn test_nonempty_cells_keep_native_geometry_while_empty_slots_use_grid_edges() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 200.0,
            y1: 60.0,
        };
        let output = recover_native_region(NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("项目", 10.0, 5.0, 35.0, 15.0, 0),
                make_atom("金额", 110.0, 5.0, 140.0, 15.0, 1),
                make_atom("甲", 10.0, 30.0, 25.0, 40.0, 2),
                make_atom("100", 110.0, 30.0, 140.0, 40.0, 3),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 0.0,
                    x1: 80.0,
                    source_atoms: vec![0, 2],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 100.0,
                    x1: 180.0,
                    source_atoms: vec![1, 3],
                    order: 1,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        });

        let amount = output
            .cells
            .iter()
            .find(|cell| cell.text == "金额")
            .expect("金额 cell");
        assert_eq!(
            (
                amount.rect.x0,
                amount.rect.y0,
                amount.rect.x1,
                amount.rect.y1
            ),
            (110.0, 5.0, 140.0, 15.0)
        );
    }

    #[test]
    fn test_empty_slots_use_region_edges_outside_native_column_bands() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 200.0,
            y1: 60.0,
        };
        let output = recover_native_region(NativeRegionInput {
            schema_version: 1,
            region: RegionDto {
                schema_version: 1,
                rect: region,
                source_order: 0,
                allowed: true,
            },
            atoms: vec![
                make_atom("项目", 10.0, 5.0, 35.0, 15.0, 0),
                make_atom("金额", 110.0, 5.0, 140.0, 15.0, 1),
                make_atom("甲", 10.0, 30.0, 25.0, 40.0, 2),
            ],
            bands: vec![
                ColumnBandDto {
                    schema_version: 1,
                    x0: 10.0,
                    x1: 80.0,
                    source_atoms: vec![0, 2],
                    order: 0,
                },
                ColumnBandDto {
                    schema_version: 1,
                    x0: 100.0,
                    x1: 180.0,
                    source_atoms: vec![1],
                    order: 1,
                },
            ],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        });

        let empty = output
            .cells
            .iter()
            .find(|cell| cell.text.is_empty() && cell.row == 1 && cell.col == 1)
            .expect("tail empty slot");
        assert_eq!((empty.rect.x0, empty.rect.x1), (90.0, 200.0));
    }

    #[test]
    fn test_empty_slot_row_edges_follow_physical_row_centers() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 200.0,
            y1: 60.0,
        };
        let rows = vec![
            RowClusterDto {
                schema_version: 1,
                row_index: 0,
                y0: 5.0,
                y1: 15.0,
                item_indices: vec![0],
            },
            RowClusterDto {
                schema_version: 1,
                row_index: 1,
                y0: 20.0,
                y1: 50.0,
                item_indices: vec![1],
            },
        ];

        let edges = logical_row_edges(&rows, &region, 2, 1, false, None, None);

        assert_eq!(edges, vec![0.0, 22.5, 60.0]);
    }

    #[test]
    fn test_empty_slot_row_edges_use_mean_atom_centers_when_row_heights_differ() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 200.0,
            y1: 60.0,
        };
        let rows = vec![
            RowClusterDto {
                schema_version: 1,
                row_index: 0,
                y0: 0.0,
                y1: 20.0,
                item_indices: vec![0, 1],
            },
            RowClusterDto {
                schema_version: 1,
                row_index: 1,
                y0: 25.0,
                y1: 35.0,
                item_indices: vec![2],
            },
        ];

        let edges = logical_row_edges(&rows, &region, 2, 1, false, None, Some(&[7.5, 30.0]));

        assert_eq!(edges, vec![0.0, 18.75, 60.0]);
    }

    #[test]
    fn test_header_cutoff_uses_first_repeated_numeric_body_level() {
        let mut atoms = Vec::new();
        for (order, y) in [100.0, 107.0, 114.0, 122.0].into_iter().enumerate() {
            atoms.push(make_atom(
                "表头",
                10.0 + order as f64 * 20.0,
                y - 5.0,
                25.0 + order as f64 * 20.0,
                y + 5.0,
                order as i64,
            ));
        }
        for (offset, y) in [156.0, 197.0, 238.0].into_iter().enumerate() {
            atoms.push(make_atom(
                "100",
                100.0,
                y - 5.0,
                140.0,
                y + 5.0,
                (offset + 4) as i64,
            ));
        }

        let cutoff = infer_header_cutoff(&atoms).expect("header cutoff");

        assert!((cutoff - 139.0).abs() < 0.01, "cutoff={cutoff}");
    }
}
