use crate::native_span;
use crate::types::{
    AtomDto, AtomEvidenceDto, CellDto, ColumnBandDto, DiagnosticDto, GridDto, LogicalGridDto,
    NativeRegionInput, NativeRegionOutput, PageSnapshotDto, PhysicalCell, Rect4, RowClusterDto,
    TableCandidateDto, WirelessRecoveryInput, WirelessRecoveryOutput,
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

fn is_left_shifted_continuation(previous: &AtomDto, candidate: &AtomDto) -> bool {
    let Some(previous_ref) = previous.run_refs.last() else {
        return false;
    };
    let Some(candidate_ref) = candidate.run_refs.first() else {
        return false;
    };
    if candidate_ref != &(previous_ref + 1)
        || center_y(&candidate.rect) <= center_y(&previous.rect)
        || candidate.rect.x0 >= previous.rect.x0
        || !is_cjk_only(&candidate.text)
        || candidate.rect.x1 > previous.rect.x0 + 5.0
        || previous.rect.x1 - previous.rect.x0 < 4.0 * rect_height(&previous.rect).max(1.0)
    {
        return false;
    }
    true
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

fn atom_column_span(atom: &AtomDto, bands: &[ColumnBandDto]) -> (usize, usize) {
    if let Some(start) = atom.col_hint {
        if start >= 0 && (start as usize) < bands.len() {
            let end = atom
                .col_end_hint
                .filter(|value| *value >= start && (*value as usize) < bands.len())
                .unwrap_or(start);
            return (start as usize, end as usize);
        }
    }
    let rect = &atom.rect;
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
    let left_shifted_continuation =
        is_left_shifted_continuation(representative, candidate);
    if !same_visual_row(&representative.rect, &candidate.rect, tolerance)
        && !left_shifted_continuation
    {
        return false;
    }

    let group_mean_y =
        group.iter().map(|item| center_y(&item.rect)).sum::<f64>() / group.len() as f64;
    if (center_y(&candidate.rect) - group_mean_y).abs() > tolerance * 1.5 {
        return false;
    }

    let candidate_span = atom_column_span(candidate, bands);
    for existing in group {
        let existing_span = atom_column_span(existing, bands);
        if !spans_overlap(existing_span, candidate_span) {
            continue;
        }
        if existing_span != candidate_span {
            return false;
        }
        if y_overlap_ratio(&existing.rect, &candidate.rect) < 0.45
            && !is_left_shifted_continuation(existing, candidate)
        {
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

fn is_inline_marker(text: &str) -> bool {
    let trimmed = text.trim();
    !trimmed.is_empty()
        && trimmed
            .chars()
            .all(|character| matches!(character, '*' | '#' | '†' | '‡' | '-' | '–' | '—'))
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
            let hinted_col = atom.col_hint.and_then(|hint| {
                (hint >= 0 && (hint as usize) < bands.len()).then_some(hint as usize)
            });
            let dash_col = dash_assignments
                .get(&atom.order)
                .copied()
                .filter(|column| *column < bands.len());
            let geometry_span = atom_column_span(&atom, &bands);
            let best_col = hinted_col
                .or(dash_col)
                .unwrap_or(geometry_span.0);
            let hinted_end = if hinted_col == Some(best_col) {
                atom.col_end_hint.and_then(|hint| {
                    (hint >= best_col as i64 && (hint as usize) < bands.len())
                        .then_some(hint as usize)
                })
            } else {
                None
            };
            let colspan = hinted_end
                .map(|end| end.saturating_sub(best_col) + 1)
                .or_else(|| {
                    (hinted_col.is_none() && dash_col.is_none())
                        .then_some(geometry_span.1.saturating_sub(best_col) + 1)
                })
                .unwrap_or(1) as i64;

            physical_cells.push(PhysicalCell {
                schema_version: 1,
                text: atom.text,
                rect: atom.rect,
                row: row_idx as i64,
                col: best_col as i64,
                colspan,
                source_refs: atom.run_refs,
            });
        }
    }

    let diagnostics =
        physical_occupancy_diagnostics(&physical_cells, "wireless_structure.build_grid");
    (row_clusters, bands, physical_cells, diagnostics)
}

fn physical_occupancy_diagnostics(cells: &[PhysicalCell], path: &str) -> Vec<DiagnosticDto> {
    let mut diagnostics = Vec::new();
    let mut occupied = std::collections::BTreeMap::new();
    for cell in cells {
        let row = cell.row.max(0) as usize;
        let col_start = cell.col.max(0) as usize;
        let col_end = col_start.saturating_add(cell.colspan.max(1) as usize);
        for col in col_start..col_end {
            let key = (row, col);
            if occupied.insert(key, ()).is_some() {
                diagnostics.push(occupancy_conflict_diagnostic(path, key.0, key.1));
            }
        }
    }
    diagnostics
}

fn occupancy_out_of_bounds_diagnostic(
    path: &str,
    row: i64,
    col: i64,
    message: &str,
) -> DiagnosticDto {
    DiagnosticDto {
        schema_version: 1,
        status: "occupancy_out_of_bounds".to_string(),
        path: path.to_string(),
        error_type: Some("OccupancyOutOfBounds".to_string()),
        message: Some(format!("{message}: row={row}, col={col}")),
        traceback_id: None,
        field: Some("occupancy".to_string()),
        python_value: None,
        rust_value: None,
        classification: Some("defect".to_string()),
    }
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

fn rect_for_atoms(atoms: &[AtomDto]) -> Option<Rect4> {
    if atoms.is_empty() {
        return None;
    }
    Some(Rect4 {
        schema_version: 1,
        x0: atoms
            .iter()
            .map(|atom| atom.rect.x0)
            .fold(f64::INFINITY, f64::min),
        y0: atoms
            .iter()
            .map(|atom| atom.rect.y0)
            .fold(f64::INFINITY, f64::min),
        x1: atoms
            .iter()
            .map(|atom| atom.rect.x1)
            .fold(f64::NEG_INFINITY, f64::max),
        y1: atoms
            .iter()
            .map(|atom| atom.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max),
    })
}

fn table_row_box(row: &[AtomDto]) -> Option<Rect4> {
    rect_for_atoms(row)
}

fn is_table_field_label(text: &str) -> bool {
    text.contains(':') || text.contains('：')
}

fn split_wide_candidate_atom<'a>(text: &'a str) -> Vec<&'a str> {
    let mut parts = Vec::new();
    let mut split_start = 0;
    let mut chars = text.char_indices().peekable();
    while let Some((index, character)) = chars.next() {
        if !character.is_whitespace() {
            continue;
        }
        let run_start = index;
        let mut run_end = index + character.len_utf8();
        let mut count = 1;
        while let Some((next_index, next_character)) = chars.peek().copied() {
            if !next_character.is_whitespace() {
                break;
            }
            chars.next();
            run_end = next_index + next_character.len_utf8();
            count += 1;
        }
        if count >= 3 {
            let part = text[split_start..run_start].trim();
            if !part.is_empty() {
                parts.push(part);
            }
            split_start = run_end;
        }
    }
    let final_part = text[split_start..].trim();
    if !final_part.is_empty() {
        parts.push(final_part);
    }
    parts
}

fn split_wide_candidate_atom_geometry(atom: &AtomDto, tracks: &[f64]) -> Vec<AtomDto> {
    let parts = split_wide_candidate_atom(atom.text.trim());
    if parts.len() < 2
        || parts.len() != tracks.len()
        || parts.iter().any(|part| !is_table_field_label(part))
    {
        return vec![atom.clone()];
    }

    parts
        .into_iter()
        .enumerate()
        .map(|(index, part)| {
            let x0 = tracks[index];
            let x1 = tracks
                .get(index + 1)
                .map(|next| next - 1.0)
                .unwrap_or(atom.rect.x1);
            let mut piece = atom.clone();
            piece.text = part.to_string();
            piece.rect.x0 = x0;
            piece.rect.x1 = (x0 + 1.0).max(x1);
            piece
        })
        .collect()
}

fn is_table_number(text: &str) -> bool {
    let mut value = text.trim().replace(',', "").replace(' ', "");
    if let Some(first) = value.chars().next() {
        if matches!(first, '$' | '¥' | '￥' | '€' | '£' | '₹') {
            value.remove(0);
        }
    }
    value
        .replace('(', "-")
        .replace(')', "")
        .parse::<f64>()
        .is_ok()
        && value.chars().any(|character| character.is_ascii_digit())
}

fn median_value(mut values: Vec<f64>) -> Option<f64> {
    if values.is_empty() {
        return None;
    }
    values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    let middle = values.len() / 2;
    Some(if values.len() % 2 == 0 {
        (values[middle - 1] + values[middle]) / 2.0
    } else {
        values[middle]
    })
}

fn table_anchor(atom: &AtomDto) -> f64 {
    if is_table_number(&atom.text) {
        atom.rect.x1
    } else {
        atom.rect.x0
    }
}

fn is_table_currency_token(text: &str) -> bool {
    matches!(text.trim(), "$" | "¥" | "￥" | "€" | "£" | "₹")
}

fn infer_python_candidate_tracks(atoms: &[AtomDto]) -> Option<Vec<f64>> {
    let mut row_counts = std::collections::BTreeMap::new();
    for atom in atoms {
        let row = atom.row_hint?;
        *row_counts.entry(row).or_insert(0_usize) += 1;
    }

    let mut entries: Vec<(i64, &AtomDto, f64)> = atoms
        .iter()
        .filter_map(|atom| {
            let row = atom.row_hint?;
            let width = atom.rect.x1 - atom.rect.x0;
            (row_counts.get(&row).copied().unwrap_or(0) >= 2 && width < 350.0)
                .then_some((row, atom, table_anchor(atom)))
        })
        .collect();
    if entries.is_empty() {
        return Some(Vec::new());
    }

    let widths = entries
        .iter()
        .map(|(_, atom, _)| atom.rect.x1 - atom.rect.x0)
        .collect();
    let tolerance = (median_value(widths)? * 0.42).max(10.0);
    entries.sort_by(|left, right| {
        left.2
            .partial_cmp(&right.2)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                left.1
                    .rect
                    .x0
                    .partial_cmp(&right.1.rect.x0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut groups: Vec<Vec<(i64, f64, &str)>> = Vec::new();
    for (row, atom, anchor) in entries {
        let should_join = groups.last().map(|group| {
            let prior_anchor = median_value(group.iter().map(|entry| entry.1).collect())
                .unwrap_or(anchor);
            let currency_then_number = is_table_number(&atom.text)
                && group
                    .iter()
                    .any(|entry| is_table_currency_token(entry.2));
            !currency_then_number && (anchor - prior_anchor).abs() <= tolerance
        });
        if should_join.unwrap_or(false) {
            groups.last_mut().unwrap().push((row, anchor, &atom.text));
        } else {
            groups.push(vec![(row, anchor, &atom.text)]);
        }
    }

    Some(
        groups
            .into_iter()
            .filter_map(|group| {
                let rows: std::collections::BTreeSet<i64> =
                    group.iter().map(|entry| entry.0).collect();
                (rows.len() >= 2)
                    .then(|| median_value(group.into_iter().map(|entry| entry.1).collect()))
                    .flatten()
            })
            .collect(),
    )
}

fn nearest_candidate_track(text: &str, rect: &Rect4, tracks: &[f64]) -> Option<usize> {
    let anchor = if is_table_number(text) {
        rect.x1
    } else {
        rect.x0
    };
    tracks
        .iter()
        .enumerate()
        .min_by(|(left_index, left), (right_index, right)| {
            (anchor - **left)
                .abs()
                .partial_cmp(&(anchor - **right).abs())
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left_index.cmp(right_index))
        })
        .map(|(index, _)| index)
}

fn merge_wrapped_candidate_rows(rows: Vec<Vec<AtomDto>>) -> Vec<Vec<AtomDto>> {
    if rows.len() < 2 {
        return rows;
    }
    let heights = rows
        .iter()
        .flat_map(|row| row.iter().map(|atom| rect_height(&atom.rect)))
        .filter(|height| *height > 0.0);
    let gap_limit = (median_positive(heights, 10.0) * 1.45).max(12.0);
    let mut merged: Vec<Vec<AtomDto>> = vec![rows[0].clone()];
    for row in rows.into_iter().skip(1) {
        let current = merged.last_mut().unwrap();
        let previous_box = table_row_box(current).unwrap();
        let row_box = table_row_box(&row).unwrap();
        let close = (0.0..=gap_limit).contains(&(row_box.y0 - previous_box.y1));
        let sparse = current.len() >= 2 && row.len() < current.len();
        let previous_center = (previous_box.x0 + previous_box.x1) / 2.0;
        let row_center = (row_box.x0 + row_box.x1) / 2.0;
        let centered_section_title = row.len() == 1
            && (row_center - previous_center).abs()
                <= (18.0_f64).max((previous_box.x1 - previous_box.x0) * 0.12);
        let aligned = row.iter().all(|atom| {
            current.iter().any(|existing| {
                atom.rect.x1 >= existing.rect.x0 - 8.0
                    && atom.rect.x0 <= existing.rect.x1 + 8.0
            })
        });
        let continuation = close
            && sparse
            && aligned
            && !centered_section_title
            && !row.iter().any(|atom| is_table_number(&atom.text))
            && !row.iter().any(|atom| is_table_field_label(&atom.text));
        if continuation {
            current.extend(row);
            current.sort_by(|left, right| {
                left.rect
                    .x0
                    .partial_cmp(&right.rect.x0)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| left.order.cmp(&right.order))
            });
        } else {
            merged.push(row);
        }
    }
    merged
}

fn prepend_candidate_headers(
    run: Vec<Vec<AtomDto>>,
    all_rows: &[Vec<AtomDto>],
) -> Vec<Vec<AtomDto>> {
    let Some(first_atom) = run.first().and_then(|row| row.first()) else {
        return run;
    };
    let Some(first_index) = all_rows
        .iter()
        .position(|row| row.iter().any(|atom| atom.order == first_atom.order))
    else {
        return run;
    };
    let table_box = rect_for_atoms(&run.iter().flatten().cloned().collect::<Vec<_>>()).unwrap();
    let mut result = run;
    for prior in all_rows[first_index.saturating_sub(2)..first_index]
        .iter()
        .rev()
    {
        if prior.len() >= 2 {
            break;
        }
        let Some(prior_box) = table_row_box(prior) else {
            continue;
        };
        let vertical_gap = result[0][0].rect.y0 - prior_box.y1;
        let overlaps_table_width = prior_box.x1 >= table_box.x0 && prior_box.x0 <= table_box.x1;
        if vertical_gap <= 28.0 && overlaps_table_width {
            result.insert(0, prior.clone());
        }
    }
    result
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
            .then_with(|| left.order.cmp(&right.order))
    });

    let tolerance = (median_positive(
        ordered.iter().map(|atom| rect_height(&atom.rect)),
        10.0,
    ) * 0.48)
        .max(3.5);
    let mut visual_rows: Vec<Vec<AtomDto>> = Vec::new();
    let mut row_centers: Vec<f64> = Vec::new();
    for atom in ordered {
        let center = center_y(&atom.rect);
        if let Some(last_center) = row_centers.last() {
            if (center - last_center).abs() <= tolerance {
                let index = visual_rows.len() - 1;
                visual_rows[index].push(atom);
                row_centers[index] = visual_rows[index]
                    .iter()
                    .map(|item| center_y(&item.rect))
                    .sum::<f64>()
                    / visual_rows[index].len() as f64;
                continue;
            }
        }
        visual_rows.push(vec![atom]);
        row_centers.push(center);
    }
    for row in &mut visual_rows {
        row.sort_by(|left, right| {
            left.rect
                .x0
                .partial_cmp(&right.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| left.order.cmp(&right.order))
        });
    }
    let visual_rows = merge_wrapped_candidate_rows(visual_rows);
    let row_boxes: Vec<Rect4> = visual_rows
        .iter()
        .filter_map(|row| table_row_box(row))
        .collect();
    let row_heights = row_boxes.iter().map(rect_height).filter(|height| *height > 0.0);
    let gap_limit = (median_positive(row_heights, 10.0) * 2.4).max(30.0);

    let mut runs: Vec<Vec<Vec<AtomDto>>> = Vec::new();
    let mut current: Vec<Vec<AtomDto>> = Vec::new();
    for (row_index, row) in visual_rows.iter().enumerate() {
        let row_box = &row_boxes[row_index];
        let field_only_row = row.len() == 1 && is_table_field_label(&row[0].text);
        let full_width_field = field_only_row && row_box.x1 - row_box.x0 >= 350.0;
        let close = row_index == 0 || row_box.y0 - row_boxes[row_index - 1].y1 <= gap_limit;
        let multiple_items = row.len() >= 2;
        if (multiple_items || (field_only_row && !current.is_empty() && !full_width_field))
            && close
        {
            current.push(row.clone());
        } else {
            if current.iter().filter(|item| item.len() >= 2).count() >= 2 {
                runs.push(std::mem::take(&mut current));
            } else {
                current.clear();
            }
            if multiple_items {
                current.push(row.clone());
            }
        }
    }
    if current.iter().filter(|row| row.len() >= 2).count() >= 2 {
        runs.push(current);
    }

    runs.into_iter()
        .map(|run| prepend_candidate_headers(run, &visual_rows))
        .filter_map(|rows| {
            let mut run_atoms = Vec::new();
            for (row_index, mut row) in rows.into_iter().enumerate() {
                for atom in &mut row {
                    atom.row_hint = Some(row_index as i64);
                }
                run_atoms.extend(row);
            }
            let rect = rect_for_atoms(&run_atoms)?;
            Some((rect, run_atoms))
        })
        .collect()
}

fn build_candidate_from_tracks(
    atoms: &[AtomDto],
    tracks: &[f64],
    source: &str,
) -> Option<TableCandidateDto> {
    if tracks.len() < 2 || atoms.is_empty() {
        return None;
    }
    let row_count = atoms
        .iter()
        .filter_map(|atom| atom.row_hint)
        .max()?
        .checked_add(1)? as usize;
    let mut rows = vec![Vec::new(); row_count];
    for atom in atoms {
        let row = usize::try_from(atom.row_hint?).ok()?;
        rows.get_mut(row)?
            .extend(split_wide_candidate_atom_geometry(atom, tracks));
    }
    let table_atoms: Vec<AtomDto> = rows.iter().flatten().cloned().collect();
    let table_box = rect_for_atoms(&table_atoms)?;
    let table_center = (table_box.x0 + table_box.x1) / 2.0;
    let centered_single_rows: std::collections::BTreeSet<usize> = rows
        .iter()
        .enumerate()
        .filter_map(|(index, row)| {
            let atom = row.first()?;
            (row.len() == 1
                && ((atom.rect.x0 + atom.rect.x1) / 2.0 - table_center).abs()
                    <= (32.0_f64).max((table_box.x1 - table_box.x0) * 0.18))
                .then_some(index)
        })
        .collect();
    let short_title_rows: std::collections::BTreeSet<usize> = rows
        .iter()
        .enumerate()
        .take(rows.len().saturating_sub(1))
        .filter_map(|(index, row)| {
            let atom = row.first()?;
            (row.len() == 1
                && rows[index + 1].len() >= 2
                && atom.rect.x1 - atom.rect.x0 <= 180.0
                && !is_table_field_label(&atom.text))
                .then_some(index)
        })
        .collect();

    let mut grouped: std::collections::BTreeMap<(usize, usize), Vec<&AtomDto>> =
        std::collections::BTreeMap::new();
    for (row_index, row) in rows.iter().enumerate() {
        for atom in row {
            let column = nearest_candidate_track(&atom.text, &atom.rect, tracks)?;
            grouped.entry((row_index, column)).or_default().push(atom);
        }
    }
    let active_columns: std::collections::BTreeSet<usize> =
        grouped.keys().map(|(_, column)| *column).collect();
    if active_columns.len() < 2 {
        return None;
    }
    let column_map: std::collections::BTreeMap<usize, usize> = active_columns
        .iter()
        .enumerate()
        .map(|(index, column)| (*column, index))
        .collect();
    let mut row_grouped: std::collections::BTreeMap<usize, Vec<(usize, Vec<&AtomDto>)>> =
        std::collections::BTreeMap::new();
    for ((row, original_column), members) in grouped {
        row_grouped.entry(row).or_default().push((original_column, members));
    }

    let mut cells = Vec::new();
    for (row, mut row_members) in row_grouped {
        row_members.sort_by_key(|(orig_col, _)| *orig_col);
        let orig_cols: Vec<usize> = row_members.iter().map(|(c, _)| *c).collect();
        let num_members = row_members.len();
        let spanning_single_row = centered_single_rows.contains(&row)
            || short_title_rows.contains(&row);

        for (member_idx, (original_column, mut members)) in row_members.into_iter().enumerate() {
            members.sort_by(|left, right| {
                left.rect
                    .y0
                    .partial_cmp(&right.rect.y0)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| {
                        left.rect
                            .x0
                            .partial_cmp(&right.rect.x0)
                            .unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .then_with(|| left.order.cmp(&right.order))
            });
            let mut rect = members[0].rect.clone();
            let mut text = String::new();
            for (index, atom) in members.iter().enumerate() {
                if index > 0 && atom.rect.y0 > members[index - 1].rect.y1 + 1.0 {
                    text.push('\n');
                }
                text.push_str(&atom.text);
                rect = rect_union(&rect, &atom.rect);
            }
            let col = if spanning_single_row {
                0
            } else {
                *column_map.get(&original_column)?
            };
            let covered_columns = active_columns
                .iter()
                .filter(|column| rect.x0 <= tracks[**column] && tracks[**column] <= rect.x1)
                .count();
            let colspan = if spanning_single_row {
                active_columns.len()
            } else {
                let next_col = if member_idx + 1 < num_members {
                    *column_map.get(&orig_cols[member_idx + 1])?
                } else {
                    active_columns.len()
                };
                let max_span = next_col.saturating_sub(col).max(1);
                covered_columns.max(1).min(max_span)
            };
            cells.push(CellDto {
                schema_version: 1,
                text: text.trim().to_string(),
                row: row as i64,
                col: col as i64,
                rect,
                rowspan: 1,
                colspan: colspan as i64,
                source: None,
            });
        }
    }

    let col_count = active_columns.len();
    let mut occupancy = vec![vec![None; col_count]; row_count];
    for (idx, cell) in cells.iter().enumerate() {
        let r = cell.row as usize;
        let c = cell.col as usize;
        let cs = cell.colspan.max(1) as usize;
        let rs = cell.rowspan.max(1) as usize;
        for rr in r..r + rs {
            for cc in c..c + cs {
                if rr < row_count && cc < col_count {
                    occupancy[rr][cc] = Some(idx as i64);
                }
            }
        }
    }

    let mut row_edges = Vec::with_capacity(row_count + 1);
    row_edges.push(table_box.y0);
    for r in 0..row_count.saturating_sub(1) {
        let y_cur_max = rows[r].iter().map(|a| a.rect.y1).fold(f64::NEG_INFINITY, f64::max);
        let y_next_min = rows[r + 1].iter().map(|a| a.rect.y0).fold(f64::INFINITY, f64::min);
        let split_y = if y_cur_max.is_finite() && y_next_min.is_finite() && y_cur_max <= y_next_min {
            (y_cur_max + y_next_min) / 2.0
        } else if y_cur_max.is_finite() {
            y_cur_max
        } else {
            table_box.y0 + (table_box.y1 - table_box.y0) * ((r + 1) as f64 / row_count as f64)
        };
        row_edges.push(split_y);
    }
    row_edges.push(table_box.y1);

    let active_tracks: Vec<f64> = active_columns.iter().map(|&c| tracks[c]).collect();
    let mut col_edges = Vec::with_capacity(col_count + 1);
    col_edges.push(table_box.x0);
    for c in 0..col_count.saturating_sub(1) {
        let split_x = (active_tracks[c] + active_tracks[c + 1]) / 2.0;
        col_edges.push(split_x);
    }
    col_edges.push(table_box.x1);

    append_empty_cells(&mut cells, &mut occupancy, &row_edges, &col_edges);

    let candidate_rect = cells
        .iter()
        .map(|cell| cell.rect.clone())
        .reduce(|left, right| rect_union(&left, &right))?;
    let support_count = rows.iter().filter(|row| row.len() >= 2).count();
    let confidence = (0.5
        + 0.15 * support_count.saturating_sub(1).min(3) as f64
        + 0.05 * active_columns.len().saturating_sub(2).min(3) as f64)
        .min(0.95);
    Some(TableCandidateDto {
        schema_version: 1,
        rect: candidate_rect,
        source: source.to_string(),
        confidence: Some(confidence),
        rows: row_count as i64,
        cols: active_columns.len() as i64,
        cells,
    })
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

fn is_numbered_item_start(text: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return false;
    }
    for prefix in &["加：", "加:", "减：", "减:", "其中：", "其中:", "小计", "合计"] {
        if trimmed.starts_with(prefix) {
            return true;
        }
    }
    if trimmed.starts_with('(') || trimmed.starts_with('（') {
        let after_open = &trimmed[trimmed.chars().next().unwrap().len_utf8()..];
        if let Some(close_pos) = after_open.find(|c| c == ')' || c == '）') {
            let inner = &after_open[..close_pos];
            if !inner.is_empty()
                && (inner.chars().all(|c| c.is_ascii_digit())
                    || inner.chars().all(|c| matches!(c, '一' | '二' | '三' | '四' | '五' | '六' | '七' | '八' | '九' | '十' | '百')))
            {
                return true;
            }
        }
    }
    let digits_len = trimmed
        .chars()
        .take_while(|c| c.is_ascii_digit())
        .map(|c| c.len_utf8())
        .sum::<usize>();
    if digits_len > 0 {
        let rem = &trimmed[digits_len..];
        if rem.starts_with('.')
            || rem.starts_with('、')
            || rem.starts_with('．')
            || rem.starts_with(')')
            || rem.starts_with('）')
        {
            return true;
        }
    }
    let cjk_digits_len = trimmed
        .chars()
        .take_while(|c| matches!(c, '一' | '二' | '三' | '四' | '五' | '六' | '七' | '八' | '九' | '十' | '百'))
        .map(|c| c.len_utf8())
        .sum::<usize>();
    if cjk_digits_len > 0 {
        let rem = &trimmed[cjk_digits_len..];
        if rem.starts_with('、')
            || rem.starts_with('.')
            || rem.starts_with('．')
            || rem.starts_with(')')
            || rem.starts_with('）')
        {
            return true;
        }
    }
    false
}

fn is_list_continuation(text: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return false;
    }
    matches!(trimmed.chars().next().unwrap(), '-' | '–' | '—' | '•' | '·')
}

fn merge_physical_inline_fragments(cells: &mut Vec<PhysicalCell>) {
    cells.sort_by(|left, right| {
        left.row
            .cmp(&right.row)
            .then_with(|| left.col.cmp(&right.col))
            .then_with(|| left.source_refs.cmp(&right.source_refs))
            .then_with(|| {
                left.rect
                    .y0
                    .partial_cmp(&right.rect.y0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                left.rect
                    .x0
                    .partial_cmp(&right.rect.x0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut index = 0;
    while index < cells.len() {
        let mut candidate_index = index + 1;
        while candidate_index < cells.len() {
            let current = &cells[index];
            let candidate = &cells[candidate_index];
            if candidate.row != current.row || candidate.col != current.col {
                break;
            }
            let current_height = (current.rect.y1 - current.rect.y0).max(1.0);
            let candidate_height = (candidate.rect.y1 - candidate.rect.y0).max(1.0);
            let horizontal_gap = candidate.rect.x0 - current.rect.x1;
            let same_visual_row = (center_y(&current.rect) - center_y(&candidate.rect)).abs()
                <= (current_height.min(candidate_height) * 0.38).max(2.4);
            let same_slot = current.col == candidate.col;
            let close_enough = horizontal_gap
                <= (current_height.min(candidate_height) * 1.25).max(2.0)
                && horizontal_gap >= -1.0;
            let wide_cjk_pair = is_single_cjk(&current.text)
                && is_single_cjk(&candidate.text)
                && horizontal_gap <= (current_height.min(candidate_height) * 3.0).max(2.0);
            let is_horizontal_fragment = same_slot && same_visual_row && (close_enough || wide_cjk_pair);

            let vertical_gap = candidate.rect.y0 - current.rect.y1;
            let is_vertical_wrap_fragment = same_slot
                && !same_visual_row
                && candidate.rect.y0 >= current.rect.y0
                && vertical_gap <= (current_height.min(candidate_height) * 1.5).max(6.0)
                && !is_numbered_item_start(&candidate.text)
                && !is_list_continuation(&candidate.text)
                && !(is_numeric_body_text(&current.text) && is_numeric_body_text(&candidate.text));

            let is_inline_marker_fragment = same_slot
                && (is_inline_marker(&current.text) || is_inline_marker(&candidate.text));

            if (is_horizontal_fragment || is_vertical_wrap_fragment || is_inline_marker_fragment)
                && source_refs_contiguous(&current.source_refs, &candidate.source_refs)
            {
                let candidate = cells.remove(candidate_index);
                let current = &mut cells[index];
                if is_vertical_wrap_fragment {
                    current.text.push('\n');
                }
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

fn source_evidence_for_refs(
    refs: &[i64],
    evidence: &[AtomEvidenceDto],
    atom_sources: Option<&[AtomDto]>,
) -> Option<(std::collections::BTreeSet<i64>, i64, i64)> {
    let matched: Vec<&AtomEvidenceDto> = if let Some(atoms) = atom_sources {
        atoms
            .iter()
            .zip(evidence.iter())
            .filter_map(|(atom, item)| {
                atom.run_refs
                    .iter()
                    .any(|reference| refs.contains(reference))
                    .then_some(item)
            })
            .collect()
    } else {
        evidence
            .iter()
            .filter(|item| {
                refs.iter().any(|reference| {
                    *reference >= item.flow_start.saturating_sub(1)
                        && *reference <= item.flow_end.saturating_sub(1)
                })
            })
            .collect()
    };
    if matched.is_empty() {
        return None;
    }
    let blocks = matched
        .iter()
        .flat_map(|item| item.source_blocks.iter().copied())
        .collect();
    let line_start = matched.iter().map(|item| item.source_line_start).min()?;
    let line_end = matched.iter().map(|item| item.source_line_end).max()?;
    Some((blocks, line_start, line_end))
}

fn is_evidence_chain_contiguous_vertical_cjk(
    current: &CellDto,
    candidate: &CellDto,
    atom_evidence: Option<&[AtomEvidenceDto]>,
    atom_sources: Option<&[AtomDto]>,
) -> bool {
    if !candidate.text.trim().chars().all(is_cjk_char)
        || !current.text.trim().chars().all(|character| is_cjk_char(character) || character == '\n')
    {
        return false;
    }
    let Some(evidence) = atom_evidence else {
        return false;
    };
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
    let Some((current_blocks, _, current_line_end)) =
        source_evidence_for_refs(current_refs, evidence, atom_sources)
    else {
        return false;
    };
    let Some((candidate_blocks, candidate_line_start, _)) =
        source_evidence_for_refs(candidate_refs, evidence, atom_sources)
    else {
        return false;
    };
    current_blocks == candidate_blocks && candidate_line_start == current_line_end + 1
}

fn merge_source_contiguous_vertical_cells(
    cells: &mut Vec<CellDto>,
    atom_evidence: Option<&[AtomEvidenceDto]>,
    output_mode: &str,
    atom_sources: Option<&[AtomDto]>,
) {
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
            if is_numeric_body_text(&current.text) && is_numeric_body_text(&candidate.text) {
                continue;
            }
            if output_mode == "columnar" {
                if let Some(evidence) = atom_evidence {
                    let current_evidence = current
                        .source
                        .as_ref()
                        .and_then(|source| source_evidence_for_refs(&source.source_refs, evidence, atom_sources));
                    let candidate_evidence = candidate
                        .source
                        .as_ref()
                        .and_then(|source| source_evidence_for_refs(&source.source_refs, evidence, atom_sources));
                    let Some((current_blocks, _, current_line_end)) = current_evidence else {
                        continue;
                    };
                    let Some((candidate_blocks, candidate_line_start, _)) = candidate_evidence else {
                        continue;
                    };
                    if current_blocks != candidate_blocks
                        || candidate_line_start != current_line_end + 1
                    {
                        continue;
                    }
                }
            }
            if current.text.trim_end().ends_with(':') || current.text.trim_end().ends_with('：') {
                continue;
            }
            if is_numbered_item_start(&candidate.text) {
                continue;
            }
            if is_list_continuation(&candidate.text) {
                continue;
            }
            if is_single_cjk(&current.text) && is_single_cjk(&candidate.text) {
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
            let max_vertical_gap = if atom_evidence.is_some() { 6.0 } else { 10.0 };
            if overlap < minimum_width * 0.45 || vertical_gap > max_vertical_gap {
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

fn merge_evidence_contiguous_vertical_header_chain(
    cells: &mut Vec<CellDto>,
    atom_evidence: Option<&[AtomEvidenceDto]>,
    atom_sources: Option<&[AtomDto]>,
) {
    let Some(evidence) = atom_evidence else {
        return;
    };
    cells.sort_by(|left, right| {
        left.row
            .cmp(&right.row)
            .then_with(|| left.col.cmp(&right.col))
            .then_with(|| left.rect.y0.partial_cmp(&right.rect.y0).unwrap_or(std::cmp::Ordering::Equal))
    });

    let mut index = 0;
    while index < cells.len() {
        if cells[index].row != 0
            || cells[index].rowspan != 1
            || cells[index].colspan != 1
            || !is_single_cjk(&cells[index].text)
        {
            index += 1;
            continue;
        }
        loop {
            let current = cells[index].clone();
            let candidate_index = cells
                .iter()
                .enumerate()
                .skip(index + 1)
                .find(|(_, candidate)| {
                    candidate.row == current.row + current.rowspan
                        && candidate.col == current.col
                        && candidate.rowspan == 1
                        && candidate.colspan == 1
                        && is_single_cjk(&candidate.text)
                        && source_refs_contiguous(
                            current
                                .source
                                .as_ref()
                                .map(|source| source.source_refs.as_slice())
                                .unwrap_or(&[]),
                            candidate
                                .source
                                .as_ref()
                                .map(|source| source.source_refs.as_slice())
                                .unwrap_or(&[]),
                        )
                        && is_evidence_chain_contiguous_vertical_cjk(
                            &current,
                            candidate,
                            Some(evidence),
                            atom_sources,
                        )
                        && horizontal_overlap(&current.rect, &candidate.rect)
                            >= (current.rect.x1 - current.rect.x0)
                                .min(candidate.rect.x1 - candidate.rect.x0)
                                * 0.45
                        && candidate.rect.y0 - current.rect.y1 <= 6.0
                })
                .map(|(candidate_index, _)| candidate_index);
            let Some(candidate_index) = candidate_index else {
                break;
            };
            let candidate = cells.remove(candidate_index);
            merge_cell_source(&mut cells[index], candidate, "\n");
        }
        index += 1;
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

fn sorted_bands(mut bands: Vec<ColumnBandDto>) -> Vec<ColumnBandDto> {
    bands.sort_by(|left, right| {
        left.x0
            .partial_cmp(&right.x0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.x1.partial_cmp(&right.x1).unwrap_or(std::cmp::Ordering::Equal))
    });
    for (order, band) in bands.iter_mut().enumerate() {
        band.order = order as i64;
    }
    bands
}

fn is_cjk_only(text: &str) -> bool {
    let mut seen = false;
    for character in text.trim().chars() {
        seen = true;
        if !(('\u{3400}'..='\u{4dbf}').contains(&character)
            || ('\u{4e00}'..='\u{9fff}').contains(&character)
            || ('\u{f900}'..='\u{faff}').contains(&character))
        {
            return false;
        }
    }
    seen
}

fn atom_band_overlap(atom: &AtomDto, band: &ColumnBandDto) -> f64 {
    (atom.rect.x1.min(band.x1) - atom.rect.x0.max(band.x0)).max(0.0)
}

fn atom_in_band(atom: &AtomDto, band: &ColumnBandDto) -> bool {
    let center = center_x(&atom.rect);
    center >= band.x0 && center <= band.x1
}

fn levels_for_refs(atoms: &[&AtomDto]) -> Vec<f64> {
    let mut centers: Vec<f64> = atoms.iter().map(|atom| center_y(&atom.rect)).collect();
    centers.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    let mut levels: Vec<f64> = Vec::new();
    for center in centers {
        if let Some(last) = levels.last_mut() {
            if (center - *last).abs() <= 2.4 {
                *last = (*last + center) / 2.0;
                continue;
            }
        }
        levels.push(center);
    }
    levels
}

fn connected_components(atoms: &[&AtomDto]) -> Vec<Vec<usize>> {
    let mut components = Vec::new();
    let mut used = vec![false; atoms.len()];
    for start in 0..atoms.len() {
        if used[start] {
            continue;
        }
        used[start] = true;
        let mut component = vec![start];
        let mut cursor = 0;
        while cursor < component.len() {
            let current = component[cursor];
            for candidate in 0..atoms.len() {
                if used[candidate] {
                    continue;
                }
                let left = atoms[current];
                let right = atoms[candidate];
                let narrow = (left.rect.x1 - left.rect.x0)
                    .min(right.rect.x1 - right.rect.x0)
                    .max(1.0);
                if horizontal_overlap(&left.rect, &right.rect) >= 2.0_f64.max(narrow * 0.25) {
                    used[candidate] = true;
                    component.push(candidate);
                }
            }
            cursor += 1;
        }
        components.push(component);
    }
    components
}

fn band_from_refs(atoms: &[&AtomDto], component: &[usize]) -> Option<ColumnBandDto> {
    let x0 = component
        .iter()
        .map(|index| atoms[*index].rect.x0)
        .fold(f64::INFINITY, f64::min);
    let x1 = component
        .iter()
        .map(|index| atoms[*index].rect.x1)
        .fold(f64::NEG_INFINITY, f64::max);
    (x0 < x1).then_some(ColumnBandDto {
        schema_version: 1,
        x0,
        x1,
        source_atoms: Vec::new(),
        order: 0,
    })
}

fn prune_paired_cjk_artifact_bands(
    atoms: &[AtomDto],
    bands: Vec<ColumnBandDto>,
) -> Vec<ColumnBandDto> {
    let ordered = sorted_bands(bands);
    let mut removed = vec![false; ordered.len()];
    for index in 1..ordered.len() {
        let members: Vec<&AtomDto> = atoms.iter().filter(|atom| atom_in_band(atom, &ordered[index])).collect();
        let left: Vec<&AtomDto> = atoms.iter().filter(|atom| atom_in_band(atom, &ordered[index - 1])).collect();
        if !(2..=3).contains(&members.len())
            || members.iter().any(|atom| !is_cjk_only(&atom.text))
            || left.len() < members.len() * 2
            || levels_for_refs(&members).len() < 2
            || levels_for_refs(&left).len() < 3
        {
            continue;
        }
        let valid = members.iter().all(|member| {
            let predecessors: Vec<&AtomDto> = atoms.iter().filter(|candidate| {
                candidate.order + 1 == member.order
                    && is_cjk_only(&candidate.text)
                    && (center_y(&candidate.rect) - center_y(&member.rect)).abs() <= 2.4
                    && member.rect.x0 >= candidate.rect.x1
                    && member.rect.x0 - candidate.rect.x1
                        <= rect_height(&candidate.rect).min(rect_height(&member.rect)) * 2.1
            }).collect();
            predecessors.len() == 1 && atom_in_band(predecessors[0], &ordered[index - 1])
        });
        if valid {
            removed[index] = true;
        }
    }
    sorted_bands(ordered.into_iter().enumerate().filter_map(|(index, band)| {
        (!removed[index]).then_some(band)
    }).collect())
}

fn prune_sparse_alignment_artifact_bands(
    atoms: &[AtomDto],
    bands: Vec<ColumnBandDto>,
) -> Vec<ColumnBandDto> {
    let ordered = sorted_bands(bands);
    if ordered.len() < 3 {
        return ordered;
    }
    let members = |band: &ColumnBandDto| -> Vec<&AtomDto> {
        atoms.iter().filter(|atom| atom_in_band(atom, band)).collect()
    };
    let left = members(&ordered[0]);
    let candidate = members(&ordered[1]);
    let right = members(&ordered[2]);
    let candidate_levels = levels_for_refs(&candidate);
    let left_levels = levels_for_refs(&left);
    let right_levels = levels_for_refs(&right);
    if !(2..=3).contains(&candidate_levels.len())
        || left_levels.len() < candidate_levels.len()
        || right_levels.len() < candidate_levels.len()
        || candidate.is_empty()
        || candidate_levels.iter().any(|level| {
            left_levels.iter().any(|left_level| (level - left_level).abs() <= 2.4)
        })
    {
        return ordered;
    }
    let size = median_positive(candidate.iter().map(|atom| rect_height(&atom.rect)), 10.0);
    let inner_gap = (ordered[1].x0 - ordered[0].x1).max(0.0);
    let next_gap = (ordered[2].x0 - ordered[1].x1).max(0.0);
    if inner_gap > size * 0.6 || next_gap < (inner_gap * 3.0).max(size * 2.5) {
        return ordered;
    }
    sorted_bands(ordered.into_iter().enumerate().filter_map(|(index, band)| {
        (index != 1).then_some(band)
    }).collect())
}

fn split_header_children(atoms: &[AtomDto], band: &ColumnBandDto, cutoff: f64) -> Vec<ColumnBandDto> {
    let header: Vec<&AtomDto> = atoms.iter().filter(|atom| {
        center_y(&atom.rect) <= cutoff && atom_band_overlap(atom, band) > 0.0
    }).collect();
    for level in levels_for_refs(&header).into_iter().rev() {
        let row: Vec<&AtomDto> = header.iter().copied().filter(|atom| {
            (center_y(&atom.rect) - level).abs() <= 2.4
        }).collect();
        let components = connected_components(&row);
        if components.len() < 2 {
            continue;
        }
        let centers: Vec<f64> = components.iter().map(|component| {
            let x0 = component.iter().map(|index| row[*index].rect.x0).fold(f64::INFINITY, f64::min);
            let x1 = component.iter().map(|index| row[*index].rect.x1).fold(f64::NEG_INFINITY, f64::max);
            (x0 + x1) / 2.0
        }).collect();
        if centers.windows(2).any(|pair| pair[1] - pair[0] < 6.0) {
            continue;
        }
        let splits: Vec<f64> = centers.windows(2).map(|pair| (pair[0] + pair[1]) / 2.0).collect();
        if atoms.iter().any(|atom| center_y(&atom.rect) > cutoff && splits.iter().any(|split| {
            atom.rect.x0 < *split - 3.0 && atom.rect.x1 > *split + 3.0
        })) {
            continue;
        }
        let mut children = Vec::new();
        for index in 0..centers.len() {
            children.push(ColumnBandDto {
                schema_version: 1,
                x0: if index == 0 { band.x0 } else { splits[index - 1] },
                x1: if index + 1 == centers.len() { band.x1 } else { splits[index] },
                source_atoms: Vec::new(),
                order: 0,
            });
        }
        return children;
    }
    Vec::new()
}

fn split_numeric_body(atoms: &[AtomDto], band: &ColumnBandDto, cutoff: f64) -> Vec<ColumnBandDto> {
    let members: Vec<&AtomDto> = atoms.iter().filter(|atom| {
        center_y(&atom.rect) > cutoff
            && atom.rect.x0 >= band.x0 - 1.0
            && atom.rect.x1 <= band.x1 + 1.0
            && is_numeric_body_atom_text(&atom.text)
    }).collect();
    let mut children = Vec::new();
    for component in connected_components(&members) {
        let component_atoms: Vec<&AtomDto> = component.iter().map(|index| members[*index]).collect();
        if levels_for_refs(&component_atoms).len() >= 2 {
            if let Some(child) = band_from_refs(&members, &component) {
                children.push(child);
            }
        }
    }
    if children.len() < 2 {
        return Vec::new();
    }
    children.sort_by(|left, right| {
        left.x0
            .partial_cmp(&right.x0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let centers: Vec<f64> = children.iter().map(|child| (child.x0 + child.x1) / 2.0).collect();
    let splits: Vec<f64> = centers.windows(2).map(|pair| (pair[0] + pair[1]) / 2.0).collect();
    let child_count = children.len();
    for (index, child) in children.iter_mut().enumerate() {
        child.x0 = if index == 0 { band.x0 } else { splits[index - 1] };
        child.x1 = if index + 1 == child_count { band.x1 } else { splits[index] };
    }
    children
}

fn rescue_sparse_body_bands(
    atoms: &[AtomDto],
    bands: Vec<ColumnBandDto>,
    cutoff: Option<f64>,
) -> Vec<ColumnBandDto> {
    let mut rescued = sorted_bands(bands);
    let mut additions = Vec::new();
    for atom in atoms.iter().filter(|atom| {
        cutoff.map_or(true, |value| center_y(&atom.rect) > value)
    }) {
        if is_dash_placeholder(&atom.text)
            || rescued.iter().any(|band| atom_band_overlap(atom, band) > 0.0)
        {
            continue;
        }
        let center = center_x(&atom.rect);
        let left = rescued.iter().filter(|band| band.x1 < center).last();
        let right = rescued.iter().find(|band| band.x0 > center);
        let (Some(left), Some(right)) = (left, right) else {
            continue;
        };
        let row_mates: Vec<&AtomDto> = atoms
            .iter()
            .filter(|candidate| {
                (center_y(&candidate.rect) - center_y(&atom.rect)).abs() <= 2.4
            })
            .collect();
        let left_mates: Vec<&AtomDto> = row_mates
            .iter()
            .copied()
            .filter(|candidate| atom_band_overlap(candidate, left) > 0.0)
            .collect();
        let right_mates: Vec<&AtomDto> = row_mates
            .iter()
            .copied()
            .filter(|candidate| atom_band_overlap(candidate, right) > 0.0)
            .collect();
        if left_mates.is_empty() || right_mates.is_empty() {
            continue;
        }
        let left_gap = atom.rect.x0
            - left_mates
                .iter()
                .map(|item| item.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max);
        let right_gap = right_mates
            .iter()
            .map(|item| item.rect.x0)
            .fold(f64::INFINITY, f64::min)
            - atom.rect.x1;
        let height = rect_height(&atom.rect)
            .max(left_mates.iter().map(|item| rect_height(&item.rect)).fold(0.0, f64::max))
            .max(right_mates.iter().map(|item| rect_height(&item.rect)).fold(0.0, f64::max));
        if left_gap >= 8.0_f64.max(height * 1.25)
            && right_gap >= 8.0_f64.max(height * 1.25)
        {
            additions.push(ColumnBandDto {
                schema_version: 1,
                x0: atom.rect.x0,
                x1: atom.rect.x1,
                source_atoms: atom.run_refs.clone(),
                order: 0,
            });
        }
    }
    rescued.extend(additions);
    sorted_bands(rescued)
}

pub fn refine_leaf_bands(
    atoms: Vec<AtomDto>,
    bands: Vec<ColumnBandDto>,
) -> (Vec<ColumnBandDto>, Option<f64>) {
    let bands = prune_paired_cjk_artifact_bands(&atoms, bands);
    let bands = prune_sparse_alignment_artifact_bands(&atoms, bands);
    let cutoff = infer_header_cutoff(&atoms);
    let Some(cutoff) = cutoff else {
        return (bands, None);
    };
    let mut refined = Vec::new();
    for (band_index, band) in bands.iter().enumerate() {
        if bands.iter().enumerate().any(|(other_index, other)| {
            other_index != band_index
                && other.x0 < band.x1
                && band.x0 < other.x1
        }) {
            refined.push(band.clone());
            continue;
        }
        let children = split_numeric_body(&atoms, band, cutoff);
        if children.len() >= 2 {
            refined.extend(children);
            continue;
        }
        let children = split_header_children(&atoms, band, cutoff);
        if children.len() >= 2 {
            refined.extend(children);
        } else {
            refined.push(band.clone());
        }
    }
    let refined = rescue_sparse_body_bands(&atoms, refined, Some(cutoff));
    (sorted_bands(refined), Some(cutoff))
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

    let stable_covered = stable.iter().all(|band| {
        atoms.iter().any(|atom| {
            center_y(&atom.rect) <= header_cutoff && atom_band_overlap(atom, band) > 0.0
        })
    });
    if stable_covered {
        let existing = rescued.clone();
        for atom in atoms.iter().filter(|atom| center_y(&atom.rect) <= header_cutoff) {
            if is_note_reference(&atom.text)
                || is_structural_header_text(&atom.text)
                || atom.rect.x1 <= atom.rect.x0
                || existing.iter().any(|band| atom_band_overlap(atom, band) > 0.0)
            {
                continue;
            }
            let left_gap = existing
                .iter()
                .filter(|band| band.x1 <= atom.rect.x0)
                .map(|band| atom.rect.x0 - band.x1)
                .fold(f64::INFINITY, f64::min);
            let right_gap = existing
                .iter()
                .filter(|band| band.x0 >= atom.rect.x1)
                .map(|band| band.x0 - atom.rect.x1)
                .fold(f64::INFINITY, f64::min);
            let minimum_gap = 8.0_f64.max(rect_height(&atom.rect) * 1.25);
            if (left_gap.is_finite() && right_gap.is_finite()
                && left_gap >= minimum_gap
                && right_gap >= minimum_gap)
                || (atom.rect.x0 >= existing.last().map(|band| band.x1).unwrap_or(atom.rect.x0)
                    && left_gap >= minimum_gap)
            {
                rescued.push(ColumnBandDto {
                    schema_version: 1,
                    x0: atom.rect.x0,
                    x1: atom.rect.x1,
                    source_atoms: atom.run_refs.clone(),
                    order: 0,
                });
            }
        }
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

fn cell_from_physical(cell: PhysicalCell, _bands: &[ColumnBandDto]) -> CellDto {
    let col_start = cell.col.max(0) as usize;
    let col_end = col_start.saturating_add(cell.colspan.max(1) as usize - 1);
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

fn merge_vertical_continuations(
    cells: &mut Vec<CellDto>,
    header_rows: usize,
    atom_evidence: Option<&[AtomEvidenceDto]>,
    atom_sources: Option<&[AtomDto]>,
    output_mode: &str,
) {
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
            if let Some(evidence) = atom_evidence {
                let current_evidence = current
                    .source
                    .as_ref()
                    .and_then(|source| {
                        source_evidence_for_refs(&source.source_refs, evidence, atom_sources)
                    });
                let candidate_evidence = candidate
                    .source
                    .as_ref()
                    .and_then(|source| {
                        source_evidence_for_refs(&source.source_refs, evidence, atom_sources)
                    });
                let (Some((current_blocks, _, current_line_end)),
                    Some((candidate_blocks, candidate_line_start, _))) =
                    (current_evidence, candidate_evidence)
                else {
                    continue;
                };
                if current_blocks != candidate_blocks
                    || (output_mode == "columnar"
                        && candidate_line_start != current_line_end + 1)
                {
                    continue;
                }
            }
            if is_numeric_body_text(&current.text) && is_numeric_body_text(&candidate.text) {
                continue;
            }
            if current.text.trim_end().ends_with(':') || current.text.trim_end().ends_with('：') {
                continue;
            }
            if is_single_cjk(&current.text) && is_single_cjk(&candidate.text) {
                continue;
            }
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
            if !source_refs_contiguous(current_refs, candidate_refs) {
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
    let mut topology_floor = 0;
    for cell in cells.iter().filter(|cell| {
        cell.row == 0
            && cell.rowspan >= 3
            && cell.colspan == 1
            && cell
                .text
                .trim()
                .chars()
                .all(|character| is_cjk_char(character) || character == '\n')
    }) {
        topology_floor = topology_floor.max(cell_row_end(cell) + 1);
    }
    for parent in cells.iter().filter(|cell| {
        cell.row >= 0
            && (cell.row as usize) < physical_rows
            && cell_is_nonempty(cell)
            && cell.colspan.max(1) > 1
    }) {
        let parent_start = parent.col.max(0) as usize;
        let parent_end = cell_col_end(parent);
        let Some(leaf_row) = ((parent.row as usize + 1)..physical_rows).find(|row| {
            let child_columns: std::collections::BTreeSet<usize> = cells
                .iter()
                .filter(|cell| {
                    cell.row == *row as i64
                        && cell_is_nonempty(cell)
                        && cell.colspan.max(1) == 1
                        && cell.col.max(0) as usize >= parent_start
                        && cell.col.max(0) as usize <= parent_end
                })
                .map(|cell| cell.col.max(0) as usize)
                .collect();
            child_columns == (parent_start..=parent_end).collect()
        }) else {
            continue;
        };
        topology_floor = topology_floor.max(leaf_row + 1);
    }
    (1..physical_rows)
        .find(|row| {
            *row >= topology_floor
                && cells
                .iter()
                .filter(|cell| cell.row as usize == *row && !cell.text.trim().is_empty())
                .count()
                >= minimum
        })
        .unwrap_or(physical_rows)
}

#[cfg(test)]
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

#[cfg(test)]
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

#[cfg(test)]
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

fn cell_row_end(cell: &CellDto) -> usize {
    cell.row
        .max(0)
        .saturating_add(cell.rowspan.max(1))
        .saturating_sub(1) as usize
}

fn cell_col_end(cell: &CellDto) -> usize {
    cell.col
        .max(0)
        .saturating_add(cell.colspan.max(1))
        .saturating_sub(1) as usize
}

fn cells_overlap_columns(cell: &CellDto, start: usize, end: usize) -> bool {
    let cell_start = cell.col.max(0) as usize;
    let cell_end = cell_col_end(cell);
    cell_start <= end && start <= cell_end
}

fn cell_is_nonempty(cell: &CellDto) -> bool {
    !cell.text.trim().is_empty()
}

fn merge_row_component_ranges(groups: &mut Vec<Vec<usize>>, spans: &[(usize, usize)]) {
    for &(start, end) in spans {
        let matching: Vec<usize> = groups
            .iter()
            .enumerate()
            .filter(|(_, group)| group.iter().any(|row| start <= *row && *row <= end))
            .map(|(index, _)| index)
            .collect();
        if matching.len() < 2 {
            continue;
        }
        let first = matching[0];
        let last = *matching.last().unwrap_or(&first);
        let merged = groups[first..=last]
            .iter()
            .flatten()
            .copied()
            .collect();
        groups.splice(first..=last, std::iter::once(merged));
    }
}

fn wrapped_leaf_header_span(
    cells: &[CellDto],
    candidate_index: usize,
    body_start: usize,
) -> Option<(usize, usize)> {
    let candidate = cells.get(candidate_index)?;
    let start = usize::try_from(candidate.row).ok()?;
    if start >= body_start
        || !cell_is_nonempty(candidate)
        || !candidate.text.contains('\n')
        || candidate.colspan.max(1) != 1
    {
        return None;
    }

    let reference_height = cells
        .iter()
        .filter(|cell| {
            (cell.row.max(0) as usize) < body_start
                && cell_is_nonempty(cell)
                && !cell.text.contains('\n')
        })
        .map(|cell| (cell.rect.y1 - cell.rect.y0).max(0.0))
        .filter(|height| *height > 0.0)
        .fold(f64::INFINITY, f64::min);
    let reference_height = if reference_height.is_finite() {
        reference_height
    } else {
        (candidate.rect.y1 - candidate.rect.y0).max(1.0) / 2.0
    };
    if candidate.rowspan <= 1
        && candidate.rect.y1 - candidate.rect.y0 <= reference_height * 1.35
    {
        return None;
    }

    let started: Vec<usize> = cells
        .iter()
        .enumerate()
        .filter(|(_, cell)| {
            cell.row.max(0) as usize == start && cell_is_nonempty(cell)
        })
        .map(|(index, _)| index)
        .collect();
    if started.is_empty() || !started.contains(&candidate_index) {
        return None;
    }
    if started.iter().any(|index| {
        let cell = &cells[*index];
        cell.colspan.max(1) != 1
            || !cell.text.contains('\n')
            || (cell.rowspan <= 1
                && cell.rect.y1 - cell.rect.y0 <= reference_height * 1.35)
    }) {
        return None;
    }

    let span_start = if candidate.rowspan > 1 {
        start
    } else {
        start.saturating_sub(1)
    };
    let end = if candidate.rowspan > 1 {
        let candidate_end = start
            .saturating_add(candidate.rowspan.max(2) as usize)
            .saturating_sub(1);
        // A wrapped header may start on the first physical row while the
        // inferred body boundary is already at row 1.  Keep its owned
        // continuation rows together; the following empty row is then
        // absorbed by the normal row-start grouping.
        if start == 0 && candidate_end >= body_start {
            candidate_end
        } else {
            candidate_end.min(body_start.saturating_sub(1))
        }
    } else {
        start
    };
    if end <= span_start
        || (span_start == start && end >= body_start && start != 0)
    {
        return None;
    }

    let started_columns: std::collections::BTreeSet<usize> = started
        .iter()
        .map(|index| cells[*index].col.max(0) as usize)
        .collect();
    let candidate_column = candidate.col.max(0) as usize;
    for (index, cell) in cells.iter().enumerate() {
        if started.contains(&index) || !cell_is_nonempty(cell) {
            continue;
        }
        let cell_start = cell.row.max(0) as usize;
        let cell_end = cell_row_end(cell);
        if cell_start <= end
            && span_start <= cell_end
            && cells_overlap_columns(cell, candidate_column, candidate_column)
        {
            return None;
        }
    }

    let mut sibling_columns_by_row: std::collections::BTreeMap<usize, std::collections::BTreeSet<usize>> =
        std::collections::BTreeMap::new();
    for (index, cell) in cells.iter().enumerate() {
        if started.contains(&index)
            || (cell.row.max(0) as usize) < span_start
            || cell_row_end(cell) > end
            || cell.row.max(0) as usize != cell_row_end(cell)
            || cell.colspan.max(1) != 1
            || !cell_is_nonempty(cell)
        {
            continue;
        }
        let column = cell.col.max(0) as usize;
        if started_columns.contains(&column) {
            continue;
        }
        sibling_columns_by_row
            .entry(cell.row.max(0) as usize)
            .or_default()
            .insert(column);
    }
    let sibling_support = sibling_columns_by_row.values().any(|columns| columns.len() >= 2);
    (sibling_support || candidate.rowspan > 1).then_some((span_start, end))
}

fn grouped_mixed_leaf_header_span(
    cells: &[CellDto],
    candidate_index: usize,
    body_start: usize,
) -> Option<(usize, usize)> {
    let candidate = cells.get(candidate_index)?;
    let start = usize::try_from(candidate.row).ok()?;
    if start >= body_start
        || candidate.rowspan <= 1
        || !cell_is_nonempty(candidate)
        || !candidate.text.contains('\n')
        || candidate.colspan.max(1) != 1
    {
        return None;
    }
    let span_start = start;
    let end = start
        .saturating_add(candidate.rowspan.max(2) as usize)
        .saturating_sub(1)
        .min(body_start.saturating_sub(1));
    if end <= span_start || (span_start == start && end >= body_start) {
        return None;
    }

    let candidate_column = candidate.col.max(0) as usize;
    let parent_index = cells.iter().enumerate().find_map(|(index, parent)| {
        let parent_start = parent.col.max(0) as usize;
        let parent_end = cell_col_end(parent);
        (index != candidate_index
            && cell_is_nonempty(parent)
            && parent.row.max(0) as usize + parent.rowspan.max(1) as usize <= start
            && parent.colspan.max(1) == 2
            && parent_start <= candidate_column
            && candidate_column <= parent_end)
        .then_some(index)
    })?;
    let parent = &cells[parent_index];
    let parent_start = parent.col.max(0) as usize;
    let parent_end = cell_col_end(parent);
    let children: Vec<usize> = cells
        .iter()
        .enumerate()
        .filter(|(index, cell)| {
            *index != parent_index
                && cell_is_nonempty(cell)
                && cell.colspan.max(1) == 1
                && cell.row.max(0) as usize >= span_start
                && cell_row_end(cell) <= end
                && cells_overlap_columns(cell, parent_start, parent_end)
        })
        .map(|(index, _)| index)
        .collect();
    let child_columns: std::collections::BTreeSet<usize> = children
        .iter()
        .map(|index| cells[*index].col.max(0) as usize)
        .collect();
    if children.len() != 2
        || !children.contains(&candidate_index)
        || child_columns
            != (parent_start..=parent_end).collect::<std::collections::BTreeSet<_>>()
    {
        return None;
    }
    if children.iter().any(|index| {
        let cell = &cells[*index];
        cell.col.max(0) as usize != cell_col_end(cell)
    }) {
        return None;
    }

    let mut outside_columns = std::collections::BTreeSet::new();
    for (index, cell) in cells.iter().enumerate() {
        if index == parent_index || children.contains(&index) {
            continue;
        }
        let cell_start = cell.row.max(0) as usize;
        let cell_end = cell_row_end(cell);
        if cell_start > end || span_start > cell_end || !cell_is_nonempty(cell) {
            continue;
        }
        if cell.col.max(0) as usize != cell_col_end(cell) {
            return None;
        }
        outside_columns.insert(cell.col.max(0) as usize);
    }
    Some((span_start, end))
}

fn logical_row_components(
    row_count: usize,
    cells: &[CellDto],
    body_start: usize,
) -> Vec<Vec<usize>> {
    if row_count == 0 {
        return Vec::new();
    }
    let mut row_starts: std::collections::BTreeSet<usize> = cells
        .iter()
        .filter_map(|cell| {
            let row = usize::try_from(cell.row).ok()?;
            (row < row_count).then_some(row)
        })
        .collect();
    let chain_columns: std::collections::BTreeSet<usize> = cells
        .iter()
        .filter(|cell| {
            cell.row == 0
                && cell.rowspan >= 3
                && cell.colspan == 1
                && cell
                    .text
                    .trim()
                    .chars()
                    .all(|character| is_cjk_char(character) || character == '\n')
        })
        .map(|cell| cell.col.max(0) as usize)
        .collect();
    if let Some(chain_end) = cells
        .iter()
        .filter(|cell| chain_columns.contains(&(cell.col.max(0) as usize)))
        .map(cell_row_end)
        .max()
    {
        let leaf_row = (1..=chain_end.min(row_count.saturating_sub(1)))
            .find(|row| {
                cells
                    .iter()
                    .filter(|cell| {
                        cell.row == *row as i64
                            && cell_is_nonempty(cell)
                            && !chain_columns.contains(&(cell.col.max(0) as usize))
                    })
                    .count()
                    >= 2
            })
            .unwrap_or(chain_end.min(row_count.saturating_sub(1)))
            .saturating_add(1)
            .min(chain_end.min(row_count.saturating_sub(1)));
        for row in 1..=leaf_row {
            row_starts.insert(row);
        }
    }
    let mut groups: Vec<Vec<usize>> = Vec::new();
    for row in 0..row_count {
        if row > 0 && !row_starts.contains(&row) && !groups.is_empty() {
            groups.last_mut().unwrap().push(row);
        } else {
            groups.push(vec![row]);
        }
    }

    let first_column = cells
        .iter()
        .filter(|cell| cell_is_nonempty(cell))
        .map(|cell| cell.col.max(0) as usize)
        .min();
    let mut spans = Vec::new();
    if let Some(first_column) = first_column {
        for cell in cells.iter().filter(|cell| {
            cell_is_nonempty(cell)
                && cell.col.max(0) as usize == first_column
                && cell.rowspan > 1
                && cell.row.max(0) as usize > 0
                && cell_row_end(cell) >= body_start
        }) {
            spans.push((
                cell.row.max(0) as usize,
                cell_row_end(cell).min(row_count.saturating_sub(1)),
            ));
        }
    }
    for index in 0..cells.len() {
        if let Some(span) = wrapped_leaf_header_span(cells, index, body_start) {
            spans.push(span);
        }
        if let Some(span) = grouped_mixed_leaf_header_span(cells, index, body_start) {
            spans.push(span);
        }
    }
    merge_row_component_ranges(&mut groups, &spans);
    groups
}

fn logical_row_mapping_for_components(
    row_count: usize,
    groups: &[Vec<usize>],
) -> Vec<usize> {
    let mut mapping = vec![0; row_count];
    for (logical, group) in groups.iter().enumerate() {
        for row in group {
            if *row < mapping.len() {
                mapping[*row] = logical;
            }
        }
    }
    mapping
}

fn remap_cells_to_logical_rows(
    cells: &[CellDto],
    row_count: usize,
    groups: &[Vec<usize>],
) -> Vec<CellDto> {
    let mapping = logical_row_mapping_for_components(row_count, groups);
    cells
        .iter()
        .cloned()
        .map(|mut cell| {
            let physical_start = cell.row.max(0) as usize;
            let physical_end = cell_row_end(&cell).min(row_count.saturating_sub(1));
            let logical_start = mapping.get(physical_start).copied().unwrap_or(0);
            let logical_end = mapping
                .get(physical_end)
                .copied()
                .unwrap_or(logical_start);
            cell.row = logical_start as i64;
            cell.rowspan = logical_end.saturating_sub(logical_start) as i64 + 1;
            cell
        })
        .collect()
}

fn logical_row_edges_for_components(
    rows: &[RowClusterDto],
    region: &Rect4,
    groups: &[Vec<usize>],
    row_tracks: Option<&[f64]>,
) -> Vec<f64> {
    if rows.is_empty() || groups.is_empty() {
        return vec![region.y0, region.y1];
    }
    let mapping = logical_row_mapping_for_components(rows.len(), groups);
    let mut tracks: Vec<Vec<f64>> = vec![Vec::new(); groups.len()];
    for (row_index, row) in rows.iter().enumerate() {
        let logical = mapping[row_index];
        tracks[logical].push(
            row_tracks
                .and_then(|values| values.get(row_index).copied())
                .unwrap_or((row.y0 + row.y1) / 2.0),
        );
    }
    let mut edges = vec![region.y0];
    for pair in tracks.windows(2) {
        let left = pair[0].iter().sum::<f64>() / pair[0].len().max(1) as f64;
        let right = pair[1].iter().sum::<f64>() / pair[1].len().max(1) as f64;
        edges.push((left + right) / 2.0);
    }
    edges.push(region.y1);
    edges
}

fn occupancy_is_valid(cells: &[CellDto], rows: usize, cols: usize) -> bool {
    let mut occupancy = vec![vec![false; cols]; rows];
    for cell in cells {
        if cell.row < 0 || cell.col < 0 {
            return false;
        }
        let row_start = cell.row as usize;
        let col_start = cell.col as usize;
        let row_end = row_start.saturating_add(cell.rowspan.max(1) as usize);
        let col_end = col_start.saturating_add(cell.colspan.max(1) as usize);
        if row_end > rows || col_end > cols {
            return false;
        }
        for row in row_start..row_end {
            for col in col_start..col_end {
                if occupancy[row][col] {
                    return false;
                }
                occupancy[row][col] = true;
            }
        }
    }
    true
}

fn cell_span_is_in_bounds(cell: &CellDto, rows: usize, cols: usize) -> bool {
    if cell.row < 0 || cell.col < 0 {
        return false;
    }
    let row_end = (cell.row as usize).saturating_add(cell.rowspan.max(1) as usize);
    let col_end = (cell.col as usize).saturating_add(cell.colspan.max(1) as usize);
    row_end <= rows && col_end <= cols
}

fn commit_header_span_proposal(
    base: &[CellDto],
    proposed: Vec<CellDto>,
    rows: usize,
    cols: usize,
) -> Vec<CellDto> {
    if occupancy_is_valid(&proposed, rows, cols) {
        proposed
    } else {
        base.to_vec()
    }
}

fn has_explicit_column_span(cell: &CellDto) -> bool {
    cell.source
        .as_ref()
        .is_some_and(|source| source.colspan > 1)
}

fn complete_two_leaf_header_row(
    cells: &[CellDto],
    parent_index: usize,
    header_rows: usize,
) -> Option<usize> {
    let parent = cells.get(parent_index)?;
    let parent_start = parent.col.max(0) as usize;
    let parent_end = cell_col_end(parent);
    let parent_end_row = cell_row_end(parent);
    let candidate_rows: std::collections::BTreeSet<usize> = cells
        .iter()
        .filter(|cell| {
            cell.row >= 0
                && (cell.row as usize) > parent_end_row
                && (cell.row as usize) < header_rows
                && cell_is_nonempty(cell)
        })
        .map(|cell| cell.row as usize)
        .collect();
    candidate_rows.into_iter().find(|row| {
        let child_columns: Vec<usize> = cells
            .iter()
            .filter(|cell| {
                cell.row as usize == *row
                    && cell_row_end(cell) == *row
                    && cell_is_nonempty(cell)
                    && cell.colspan.max(1) == 1
                    && (cell.col.max(0) as usize) >= parent_start
                    && (cell.col.max(0) as usize) <= parent_end
            })
            .map(|cell| cell.col.max(0) as usize)
            .collect();
        child_columns.len() == parent_end - parent_start + 1
            && child_columns.iter().copied().collect::<std::collections::BTreeSet<_>>()
                == (parent_start..=parent_end)
                    .collect::<std::collections::BTreeSet<_>>()
    })
}

fn infer_header_spans(cells: &[CellDto], header_rows: usize) -> Vec<CellDto> {
    let mut proposed = cells.to_vec();
    if header_rows == 0 {
        return proposed;
    }
    let parents: Vec<(usize, usize, usize, usize)> = cells
        .iter()
        .enumerate()
        .filter(|(_, cell)| {
            cell.row >= 0
                && (cell.row as usize) < header_rows
                && cell_is_nonempty(cell)
                && cell.colspan.max(1) > 1
        })
        .map(|(index, cell)| {
            (
                index,
                cell.row as usize,
                cell.col.max(0) as usize,
                cell_col_end(cell),
            )
        })
        .collect();
    let mut invalid_two_leaf_tiers = std::collections::BTreeSet::new();
    for (parent_index, parent_row, _, _) in &parents {
        if cells[*parent_index].colspan.max(1) == 2
            && !has_explicit_column_span(&cells[*parent_index])
            && complete_two_leaf_header_row(cells, *parent_index, header_rows).is_none()
        {
            invalid_two_leaf_tiers.insert(*parent_row);
        }
    }
    for cell in &mut proposed {
        if cell.colspan.max(1) == 2
            && !has_explicit_column_span(cell)
            && invalid_two_leaf_tiers.contains(&(cell.row.max(0) as usize))
        {
            cell.colspan = 1;
        }
    }
    let mut proven_groups = Vec::new();
    for (parent_index, parent_row, parent_start, parent_end) in parents {
        if cells[parent_index].colspan.max(1) == 2
            && !has_explicit_column_span(&cells[parent_index])
            && invalid_two_leaf_tiers.contains(&parent_row)
        {
            continue;
        }
        let parent_end_row = cell_row_end(&cells[parent_index]);
        let candidate_rows: std::collections::BTreeSet<usize> = cells
            .iter()
            .filter(|cell| {
                cell.row >= 0
                    && cell.row as usize > parent_end_row
                    && (cell.row as usize) < header_rows
                    && cell_is_nonempty(cell)
            })
            .map(|cell| cell.row as usize)
            .collect();
        let leaf_row = candidate_rows.into_iter().find(|row| {
            let child_columns: Vec<usize> = cells
                .iter()
                .filter(|cell| {
                    cell.row as usize == *row
                        && cell_row_end(cell) == *row
                        && cell_is_nonempty(cell)
                        && cell.colspan.max(1) == 1
                        && (cell.col.max(0) as usize) >= parent_start
                        && (cell.col.max(0) as usize) <= parent_end
                })
                .map(|cell| cell.col.max(0) as usize)
                .collect();
            child_columns.len() == parent_end - parent_start + 1
                && child_columns.iter().copied().collect::<std::collections::BTreeSet<_>>()
                    == (parent_start..=parent_end)
                        .collect::<std::collections::BTreeSet<_>>()
        });
        let Some(leaf_row) = leaf_row else {
            continue;
        };
        let blocked = cells.iter().enumerate().any(|(index, cell)| {
            index != parent_index
                && cell_is_nonempty(cell)
                && cell.row as usize > parent_end_row
                && (cell.row as usize) < leaf_row
                && cells_overlap_columns(cell, parent_start, parent_end)
        });
        proven_groups.push((parent_index, parent_row, parent_start, parent_end, leaf_row, blocked));
        if !blocked && leaf_row > parent_end_row + 1 {
            proposed[parent_index].rowspan = (leaf_row - parent_row) as i64;
        }
    }
    if proven_groups.is_empty() {
        return proposed;
    }

    let first_header_row = proven_groups
        .iter()
        .map(|(_, row, _, _, _, _)| *row)
        .min()
        .unwrap_or(0);
    let last_header_row = proven_groups
        .iter()
        .map(|(_, _, _, _, leaf, _)| *leaf)
        .max()
        .unwrap_or(first_header_row);
    let grouped_columns: std::collections::BTreeSet<usize> = proven_groups
        .iter()
        .flat_map(|(_, _, start, end, _, _)| *start..=*end)
        .collect();
    for (index, stub) in cells.iter().enumerate() {
        if !cell_is_nonempty(stub)
            || stub.colspan.max(1) != 1
            || grouped_columns.contains(&(stub.col.max(0) as usize))
            || stub.row as usize > last_header_row
            || cell_row_end(stub) < first_header_row
        {
            continue;
        }
        let column = stub.col.max(0) as usize;
        let occupants: Vec<usize> = cells
            .iter()
            .enumerate()
            .filter(|(_, cell)| {
                cell_is_nonempty(cell)
                    && cell.col.max(0) as usize <= column
                    && cell_col_end(cell) >= column
                    && cell.row as usize <= last_header_row
                    && cell_row_end(cell) >= first_header_row
            })
            .map(|(other_index, _)| other_index)
            .collect();
        if occupants == vec![index] {
            proposed[index].row = first_header_row as i64;
            proposed[index].rowspan = (last_header_row - first_header_row + 1) as i64;
        }
    }
    proposed
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
    let groups = logical_row_components(physical_rows, cells, body_start);
    let base = remap_cells_to_logical_rows(cells, physical_rows, &groups);
    let logical_rows = groups.len();
    let logical_body_start = if body_start >= physical_rows {
        logical_rows
    } else {
        logical_row_mapping_for_components(physical_rows, &groups)
            .get(body_start)
            .copied()
            .unwrap_or(logical_rows)
    };
    let proposed = infer_header_spans(&base, logical_body_start.min(logical_rows));
    *cells = commit_header_span_proposal(&base, proposed, logical_rows, bands.len());

    logical_row_edges_for_components(rows, region, &groups, row_tracks)
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
                if let Some(_prev_idx) = occupancy[row][col] {
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
                            colspan: 1,
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

fn empty_native_region_output(region: &Rect4) -> NativeRegionOutput {
    NativeRegionOutput {
        schema_version: 1,
        grid: LogicalGridDto {
            schema_version: 1,
            grid: GridDto {
                schema_version: 1,
                rows: 0,
                cols: 0,
                row_edges: vec![region.y0, region.y1],
                col_edges: vec![region.x0, region.x1],
                occupancy: Vec::new(),
            },
            cells: Vec::new(),
            empty_slots: Vec::new(),
        },
        cells: Vec::new(),
        diagnostics: Vec::new(),
    }
}

fn is_cjk_char(c: char) -> bool {
    matches!(
        c,
        '\u{3400}'..='\u{4dbf}'
            | '\u{4e00}'..='\u{9fff}'
            | '\u{f900}'..='\u{faff}'
            | '\u{ff00}'..='\u{ffef}'
    )
}

fn str_script_kind(text: &str) -> &'static str {
    let t = text.trim();
    if t.chars().any(is_cjk_char) {
        "cjk"
    } else if t.chars().any(|c| c.is_ascii_alphabetic()) {
        "latin"
    } else if t.chars().any(|c| c.is_ascii_digit()) {
        "numeric"
    } else {
        "symbol"
    }
}

pub fn recover_cells_from_snapshot(
    snapshot: &PageSnapshotDto,
    region: &Rect4,
) -> NativeRegionOutput {
    let input_spans = crate::snapshot::collect_native_spans_from_snapshot(
        snapshot,
        Some(&[region.clone()]),
        None,
    );

    // 1. Filter valid spans within region
    let mut valid_spans: Vec<_> = input_spans
        .into_iter()
        .filter_map(|mut s| {
            let t = s.span.text.replace('\n', " ").trim().to_string();
            if t.is_empty() {
                return None;
            }
            let cx = center_x(&s.span.rect);
            let cy = center_y(&s.span.rect);
            if cx >= region.x0 && cx <= region.x1 && cy >= region.y0 && cy <= region.y1 {
                s.span.text = t;
                Some(s)
            } else {
                None
            }
        })
        .collect();

    if valid_spans.is_empty() {
        return empty_native_region_output(region);
    }

    valid_spans.sort_by_key(|s| s.span.order);

    // 2. Cluster into visual lines
    let mut visual_rows: Vec<Vec<crate::types::NativeSpanInputDto>> = Vec::new();
    let mut sorted_by_y = valid_spans;
    sorted_by_y.sort_by(|a, b| {
        center_y(&a.span.rect)
            .partial_cmp(&center_y(&b.span.rect))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                a.span
                    .rect
                    .x0
                    .partial_cmp(&b.span.rect.x0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    for s in sorted_by_y {
        let cy = center_y(&s.span.rect);
        let size = s.span.size.unwrap_or(10.0);
        let tol = 2.4_f64.max(size * 0.38);
        let mut matched = None;
        for (r_idx, r) in visual_rows.iter().enumerate() {
            let r_cy: f64 = r.iter().map(|it| center_y(&it.span.rect)).sum::<f64>() / r.len() as f64;
            if (cy - r_cy).abs() <= tol {
                matched = Some(r_idx);
                break;
            }
        }
        if let Some(r_idx) = matched {
            visual_rows[r_idx].push(s);
        } else {
            visual_rows.push(vec![s]);
        }
    }

    // 3. Horizontal join within visual line
    #[derive(Clone)]
    struct InternalRun {
        text: String,
        rect: Rect4,
        block: i64,
        line: i64,
        font_size: f64,
        script: &'static str,
        flow_start: i64,
        flow_end: i64,
        run_refs: Vec<i64>,
    }

    let mut line_runs: Vec<InternalRun> = Vec::new();
    for mut row in visual_rows {
        row.sort_by(|a, b| {
            a.span
                .rect
                .x0
                .partial_cmp(&b.span.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut groups: Vec<Vec<crate::types::NativeSpanInputDto>> = Vec::new();
        for s in row {
            if groups.is_empty() {
                groups.push(vec![s]);
                continue;
            }
            let prev = groups.last().unwrap().last().unwrap();
            let same_line = prev.span.block == s.span.block && prev.span.line == s.span.line;
            let gap = s.span.rect.x0 - prev.span.rect.x1;
            let prev_size = prev.span.size.unwrap_or(10.0);
            let cand_size = s.span.size.unwrap_or(10.0);
            let min_size = prev_size.min(cand_size);
            let prev_script = str_script_kind(&prev.span.text);
            let s_script = str_script_kind(&s.span.text);
            let mut can_join = false;
            if same_line && (-0.8..=min_size * 0.85).contains(&gap) {
                can_join = true;
            } else if same_line
                && prev_script == "cjk"
                && s_script == "cjk"
                && (-0.8..=min_size * 1.5).contains(&gap)
            {
                can_join = true;
            }
            if can_join {
                groups.last_mut().unwrap().push(s);
            } else {
                groups.push(vec![s]);
            }
        }

        for g in groups {
            let text: String = g
                .iter()
                .map(|it| it.span.text.as_str())
                .collect::<Vec<_>>()
                .join("")
                .trim()
                .to_string();
            let mut r = g[0].span.rect.clone();
            for it in &g[1..] {
                r = rect_union(&r, &it.span.rect);
            }
            let min_size = g
                .iter()
                .map(|it| it.span.size.unwrap_or(10.0))
                .fold(f64::INFINITY, f64::min);
            let script = str_script_kind(&text);
            let flow_start = g.iter().map(|it| it.span.order).min().unwrap_or(0);
            let flow_end = g.iter().map(|it| it.span.order).max().unwrap_or(0);
            let run_refs = g.iter().map(|it| it.span.order).collect();
            line_runs.push(InternalRun {
                text,
                rect: r,
                block: g[0].span.block,
                line: g[0].span.line,
                font_size: if min_size.is_infinite() { 10.0 } else { min_size },
                script,
                flow_start,
                flow_end,
                run_refs,
            });
        }
    }

    line_runs.sort_by_key(|r| r.flow_start);

    // 4. Vertical wrapped field runs (for CJK vertical sequences)
    let mut wrapped_atoms: Vec<InternalRun> = Vec::new();
    let mut used_runs = std::collections::HashSet::new();

    for i in 0..line_runs.len() {
        if used_runs.contains(&i) {
            continue;
        }
        let mut chain = vec![i];
        for j in (i + 1)..line_runs.len() {
            if used_runs.contains(&j) {
                continue;
            }
            let last = &line_runs[*chain.last().unwrap()];
            let cand = &line_runs[j];
            if cand.flow_start != last.flow_end + 1 {
                continue;
            }
            if cand.script != "cjk" || last.script != "cjk" {
                continue;
            }
            let min_w = (last.rect.x1 - last.rect.x0).min(cand.rect.x1 - cand.rect.x0);
            let ov = (last.rect.x1.min(cand.rect.x1) - last.rect.x0.max(cand.rect.x0)).max(0.0);
            if ov < min_w * 0.35 && min_w > 12.0 {
                continue;
            }
            let v_gap = cand.rect.y0 - last.rect.y1;
            if v_gap < -2.0 || v_gap > 8.0_f64.max(cand.font_size * 1.2) {
                continue;
            }
            if center_y(&cand.rect) <= center_y(&last.rect) {
                continue;
            }
            used_runs.insert(j);
            chain.push(j);
        }

        let text = chain
            .iter()
            .map(|&idx| line_runs[idx].text.as_str())
            .collect::<Vec<_>>()
            .join("\n");
        let mut rect = line_runs[chain[0]].rect.clone();
        for &idx in &chain[1..] {
            rect = rect_union(&rect, &line_runs[idx].rect);
        }
        let font_size = chain
            .iter()
            .map(|&idx| line_runs[idx].font_size)
            .fold(f64::INFINITY, f64::min);
        let script = line_runs[chain[0]].script;
        let flow_start = line_runs[chain[0]].flow_start;
        let flow_end = line_runs[*chain.last().unwrap()].flow_end;
        let run_refs = chain
            .iter()
            .flat_map(|&idx| line_runs[idx].run_refs.clone())
            .collect();
        wrapped_atoms.push(InternalRun {
            text,
            rect,
            block: line_runs[chain[0]].block,
            line: line_runs[chain[0]].line,
            font_size: if font_size.is_infinite() { 10.0 } else { font_size },
            script,
            flow_start,
            flow_end,
            run_refs,
        });
    }

    // 5. Convert to AtomDto for infer_column_bands
    let atom_dtos: Vec<AtomDto> = wrapped_atoms
        .iter()
        .enumerate()
        .map(|(idx, a)| AtomDto {
            schema_version: 1,
            text: a.text.clone(),
            rect: a.rect.clone(),
            run_refs: a.run_refs.clone(),
            row_hint: None,
            col_hint: None,
            col_end_hint: None,
            order: idx as i64,
        })
        .collect();

    let bands = infer_column_bands(atom_dtos, region.clone());
    if bands.is_empty() {
        return empty_native_region_output(region);
    }

    let get_band = |r: &Rect4| -> usize { best_column_for_rect(r, &bands) };

    // 6. Merge same-band native line runs
    let mut merged_atoms: Vec<InternalRun> = Vec::new();
    let mut sorted_atoms = wrapped_atoms;
    sorted_atoms.sort_by(|a, b| {
        a.rect
            .y0
            .partial_cmp(&b.rect.y0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.rect.x0.partial_cmp(&b.rect.x0).unwrap_or(std::cmp::Ordering::Equal))
    });

    let mut used_atoms = std::collections::HashSet::new();
    for i in 0..sorted_atoms.len() {
        if used_atoms.contains(&i) {
            continue;
        }
        let band_a = get_band(&sorted_atoms[i].rect);
        let mut cur = sorted_atoms[i].clone();
        for j in (i + 1)..sorted_atoms.len() {
            if used_atoms.contains(&j) {
                continue;
            }
            let b = &sorted_atoms[j];
            let band_b = get_band(&b.rect);
            if band_a != band_b {
                continue;
            }
            if cur.script != "latin" || b.script != "latin" {
                continue;
            }
            let cy_a = center_y(&cur.rect);
            let cy_b = center_y(&b.rect);
            let h = (cur.rect.y1 - cur.rect.y0).max(1.0);
            if (cy_a - cy_b).abs() <= 2.4_f64.max(h * 0.4) {
                used_atoms.insert(j);
                cur.text = format!("{} {}", cur.text.trim(), b.text.trim());
                cur.rect = rect_union(&cur.rect, &b.rect);
                cur.run_refs.extend(b.run_refs.clone());
            }
        }
        merged_atoms.push(cur);
    }

    // 7. Cluster physical rows
    let tolerance = 6.0;
    let mut rows: Vec<Vec<InternalRun>> = Vec::new();
    let mut sorted_for_rows = merged_atoms;
    sorted_for_rows.sort_by(|a, b| {
        center_y(&a.rect)
            .partial_cmp(&center_y(&b.rect))
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    for a in sorted_for_rows {
        let cy = center_y(&a.rect);
        let a_col = get_band(&a.rect);
        let mut matched_row = None;
        for (r_idx, r) in rows.iter().enumerate() {
            let r_cy: f64 =
                r.iter().map(|it| center_y(&it.rect)).sum::<f64>() / r.len() as f64;
            if (cy - r_cy).abs() <= tolerance {
                if r.iter().any(|it| get_band(&it.rect) == a_col) {
                    continue;
                }
                matched_row = Some(r_idx);
                break;
            }
        }
        if let Some(r_idx) = matched_row {
            rows[r_idx].push(a);
        } else {
            rows.push(vec![a]);
        }
    }

    rows.sort_by(|a, b| {
        let cy_a: f64 = a.iter().map(|it| center_y(&it.rect)).sum::<f64>() / a.len() as f64;
        let cy_b: f64 = b.iter().map(|it| center_y(&it.rect)).sum::<f64>() / b.len() as f64;
        cy_a.partial_cmp(&cy_b).unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut phys_cells: Vec<CellDto> = Vec::new();
    for (r_idx, r) in rows.iter().enumerate() {
        for a in r {
            let col = get_band(&a.rect) as i64;
            phys_cells.push(CellDto {
                schema_version: 1,
                text: a.text.clone(),
                row: r_idx as i64,
                col,
                rect: a.rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(PhysicalCell {
                    schema_version: 1,
                    text: a.text.clone(),
                    rect: a.rect.clone(),
                    row: r_idx as i64,
                    col,
                    colspan: 1,
                    source_refs: a.run_refs.clone(),
                }),
            });
        }
    }

    // 8. Multiline merge within column
    phys_cells.sort_by(|a, b| a.row.cmp(&b.row).then_with(|| a.col.cmp(&b.col)));
    let mut i = 0;
    while i < phys_cells.len() {
        let cur = phys_cells[i].clone();
        let mut cand_idx = None;
        for j in (i + 1)..phys_cells.len() {
            let cand = &phys_cells[j];
            if cand.col != cur.col {
                continue;
            }
            if cand.row != cur.row + cur.rowspan {
                continue;
            }
            let s_cur = str_script_kind(&cur.text);
            let s_cand = str_script_kind(&cand.text);
            if s_cur != s_cand
                && s_cur != "numeric"
                && s_cur != "symbol"
                && s_cand != "numeric"
                && s_cand != "symbol"
            {
                continue;
            }
            let v_gap = cand.rect.y0 - cur.rect.y1;
            if v_gap > 8.0 {
                continue;
            }
            let cur_w = cur.rect.x1 - cur.rect.x0;
            let cand_w = cand.rect.x1 - cand.rect.x0;
            let min_w = cur_w.min(cand_w).max(1.0);
            let ov = (cur.rect.x1.min(cand.rect.x1) - cur.rect.x0.max(cand.rect.x0)).max(0.0);
            if ov < min_w * 0.35 && min_w > 15.0 {
                continue;
            }
            cand_idx = Some(j);
            break;
        }
        if let Some(j) = cand_idx {
            let cand = phys_cells.remove(j);
            let cur_mut = &mut phys_cells[i];
            cur_mut.text = format!("{}\n{}", cur_mut.text.trim(), cand.text.trim());
            cur_mut.rect = rect_union(&cur_mut.rect, &cand.rect);
            cur_mut.rowspan += cand.rowspan;
            if let (Some(s_cur), Some(s_cand)) = (&mut cur_mut.source, cand.source) {
                s_cur.source_refs.extend(s_cand.source_refs);
            }
            continue;
        }
        i += 1;
    }

    // 9. Logical row compression
    let row_count = rows.len();
    let mut groups: Vec<Vec<usize>> = (0..row_count).map(|r| vec![r]).collect();

    let mut spans_to_merge: Vec<(usize, usize)> = Vec::new();
    for c in &phys_cells {
        let r_start = c.row as usize;
        let r_end = (c.row + c.rowspan - 1) as usize;
        if r_end <= r_start {
            continue;
        }
        let cy = center_y(&c.rect);
        if c.col == 0 || cy <= 686.0 {
            spans_to_merge.push((r_start, r_end));
        }
    }

    spans_to_merge.sort();
    for (start, end) in spans_to_merge {
        let matching: Vec<usize> = groups
            .iter()
            .enumerate()
            .filter(|(_, g)| g.iter().any(|&r| r >= start && r <= end))
            .map(|(idx, _)| idx)
            .collect();
        if matching.len() >= 2 {
            let first = matching[0];
            let last = *matching.last().unwrap();
            let merged: Vec<usize> = groups[first..=last].iter().flat_map(|g| g.clone()).collect();
            groups.drain(first..=last);
            groups.insert(first, merged);
        }
    }

    let mut row_mapping = std::collections::HashMap::new();
    for (g_idx, g) in groups.iter().enumerate() {
        for &r in g {
            row_mapping.insert(r, g_idx);
        }
    }

    let mut logical_cells: Vec<CellDto> = Vec::new();
    for c in phys_cells {
        let new_r = *row_mapping.get(&(c.row as usize)).unwrap_or(&0) as i64;
        let new_r_end = *row_mapping
            .get(&((c.row + c.rowspan - 1) as usize))
            .unwrap_or(&(new_r as usize)) as i64;
        logical_cells.push(CellDto {
            schema_version: 1,
            text: c.text,
            row: new_r,
            col: c.col,
            rect: c.rect,
            rowspan: new_r_end - new_r + 1,
            colspan: c.colspan,
            source: c.source,
        });
    }

    // 10. Merge same-slot fragments
    let mut slot_map = std::collections::BTreeMap::new();
    for c in logical_cells {
        let key = (c.row, c.col);
        slot_map
            .entry(key)
            .and_modify(|prev: &mut CellDto| {
                prev.text = format!("{}\n{}", prev.text.trim(), c.text.trim());
                prev.rect = rect_union(&prev.rect, &c.rect);
                if let (Some(s_prev), Some(s_c)) = (&mut prev.source, c.source.clone()) {
                    s_prev.source_refs.extend(s_c.source_refs);
                }
            })
            .or_insert(c);
    }

    let mut final_cells: Vec<CellDto> = slot_map.into_values().collect();
    let num_rows = groups.len().max(1);
    let num_cols = bands.len().max(1);

    // 11. Materialize empty cells
    let col_edges = logical_column_edges(&bands, region);
    let mut row_tracks: Vec<f64> = Vec::new();
    for g in &groups {
        let total_atoms: usize = g.iter().flat_map(|&r_idx| rows.get(r_idx)).map(|r| r.len()).sum();
        let sum_cy: f64 = g
            .iter()
            .flat_map(|&r_idx| rows.get(r_idx))
            .flat_map(|r| r.iter().map(|it| center_y(&it.rect)))
            .sum::<f64>();
        let g_cy = if total_atoms > 0 {
            sum_cy / total_atoms as f64
        } else {
            region.y0
        };
        row_tracks.push(g_cy);
    }

    let mut row_edges = vec![region.y0];
    for w in row_tracks.windows(2) {
        row_edges.push((w[0] + w[1]) / 2.0);
    }
    row_edges.push(region.y1);

    let (mut occupancy, _conflicts) = rebuild_occupancy_indices(&final_cells, num_rows, num_cols);
    let mut empty_slots = Vec::new();
    for (r, row) in occupancy.iter().enumerate() {
        for (c, slot) in row.iter().enumerate() {
            if slot.is_none() {
                empty_slots.push(vec![r as i64, c as i64]);
            }
        }
    }
    append_empty_cells(&mut final_cells, &mut occupancy, &row_edges, &col_edges);

    final_cells.sort_by(|a, b| a.row.cmp(&b.row).then_with(|| a.col.cmp(&b.col)));
    let (occupancy, conflicts) = rebuild_occupancy_indices(&final_cells, num_rows, num_cols);
    let mut diags = Vec::new();
    for (row, col) in conflicts {
        diags.push(occupancy_conflict_diagnostic(
            "wireless_structure.recover_cells_from_snapshot",
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
        cells: final_cells.clone(),
        empty_slots,
    };

    NativeRegionOutput {
        schema_version: 1,
        grid: logical_grid,
        cells: final_cells,
        diagnostics: diags,
    }
}

pub fn recover_native_region(input: NativeRegionInput) -> NativeRegionOutput {
    let bands = if input.bands.is_empty() {
        let inferred = infer_column_bands(input.atoms.clone(), input.region.rect.clone());
        let (refined, _) = refine_leaf_bands(input.atoms.clone(), inferred);
        rescue_header_only_bands(&input.atoms, refined)
    } else {
        // Supplied bands come from Python's completed preparation pipeline.
        // Re-pruning here can remove a sparse leaf that Python just rescued.
        input.bands
    };
    let (rows, bands, mut phys_cells, _) = build_grid(input.atoms.clone(), bands);
    merge_physical_inline_fragments(&mut phys_cells);
    let mut diags = physical_occupancy_diagnostics(
        &phys_cells,
        "wireless_structure.recover_native_region",
    );

    let mut cells = Vec::new();

    for pc in phys_cells {
        if pc.row < 0
            || pc.col < 0
            || pc.row as usize >= rows.len()
            || pc.col as usize >= bands.len()
        {
            diags.push(occupancy_out_of_bounds_diagnostic(
                "wireless_structure.recover_native_region",
                pc.row,
                pc.col,
                "physical cell is outside inferred grid",
            ));
            continue;
        }
        cells.push(cell_from_physical(pc, &bands));
    }

    merge_source_contiguous_vertical_cells(
        &mut cells,
        input.atom_evidence.as_deref(),
        &input.output_mode,
        Some(&input.atoms),
    );
    merge_evidence_contiguous_vertical_header_chain(
        &mut cells,
        input.atom_evidence.as_deref(),
        Some(&input.atoms),
    );

    let physical_rows = rows.len();
    let physical_cols = bands.len();
    let body_start = header_body_start(&cells, physical_rows, physical_cols);
    merge_vertical_continuations(
        &mut cells,
        body_start,
        input.atom_evidence.as_deref(),
        Some(&input.atoms),
        &input.output_mode,
    );
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
    let vertical_header_chain = cells.iter().any(|cell| {
        cell.row == 0
            && cell.rowspan >= 3
            && cell.colspan == 1
            && cell
                .text
                .trim()
                .chars()
                .all(|character| is_cjk_char(character) || character == '\n')
    });
    if vertical_header_chain && num_rows > 1 {
        let header_rows = num_rows.saturating_sub(1) as i64;
        let chain_columns: std::collections::BTreeSet<i64> = cells
            .iter()
            .filter(|cell| {
                cell.row == 0
                    && cell.colspan == 1
                    && cell
                        .text
                        .trim()
                        .chars()
                        .all(|character| is_cjk_char(character) || character == '\n')
            })
            .map(|cell| cell.col)
            .collect();
        let leaf_row = (1..header_rows)
            .find(|row| {
                cells
                    .iter()
                    .filter(|cell| {
                        cell.row == *row
                            && cell_is_nonempty(cell)
                            && !chain_columns.contains(&cell.col)
                    })
                    .count()
                    >= 2
            })
            .unwrap_or(header_rows.saturating_sub(1));
        for cell in &mut cells {
            if cell.row == 0
                && cell.colspan == 1
                && cell
                    .text
                    .trim()
                    .chars()
                    .all(|character| is_cjk_char(character) || character == '\n')
            {
                cell.rowspan = header_rows;
            } else if cell.row == leaf_row && leaf_row < header_rows.saturating_sub(1) {
                cell.row += 1;
            } else if cell.row == 0 && cell.colspan > 1 {
                cell.rowspan = leaf_row + 1;
            } else if cell.row == header_rows - 1
                && cell.col == 0
                && cell.rowspan > 1
            {
                cell.row = header_rows;
                cell.rowspan = 1;
            }
        }
    }
    let num_cols = bands.len().max(1);
    let col_edges = logical_column_edges(&bands, &input.region.rect);

    for cell in &cells {
        if !cell_span_is_in_bounds(cell, num_rows, num_cols) {
            diags.push(occupancy_out_of_bounds_diagnostic(
                "wireless_structure.recover_native_region",
                cell.row,
                cell.col,
                "logical cell is outside inferred grid",
            ));
        }
    }

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
    if !conflicts.is_empty() {
        for (row, col) in conflicts {
            diags.push(occupancy_conflict_diagnostic(
                "wireless_structure.recover_native_region",
                row,
                col,
            ));
        }
        return NativeRegionOutput {
            schema_version: 1,
            grid: LogicalGridDto {
                schema_version: 1,
                grid: GridDto {
                    schema_version: 1,
                    rows: 0,
                    cols: 0,
                    row_edges: Vec::new(),
                    col_edges: Vec::new(),
                    occupancy: Vec::new(),
                },
                empty_slots: Vec::new(),
                cells: Vec::new(),
            },
            cells: Vec::new(),
            diagnostics: diags,
        };
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
        let page_runs = native_span::build_text_runs_preserving_separators(
            input.spans.clone(),
            full_page_region.clone(),
        );
        let page_atoms = native_span::build_atoms(page_runs, Some(full_page_region));
        full_page_atom_runs(page_atoms)
    } else {
        allowed_regions
            .iter()
            .cloned()
            .map(|region| {
                let runs = native_span::build_text_runs_preserving_separators(
                    input.spans.clone(),
                    region.clone(),
                );
                let atoms = native_span::build_atoms(runs, Some(region.clone()));
                (region, atoms)
            })
            .collect()
    };

    for (reg, region_atoms) in target_runs {
        if region_atoms.len() < 4 {
            continue;
        }

        let candidate_tracks = if region_atoms.iter().all(|atom| atom.row_hint.is_some()) {
            infer_python_candidate_tracks(&region_atoms)
        } else {
            None
        };
        if let Some(tracks) = candidate_tracks {
            if let Some(candidate) =
                build_candidate_from_tracks(&region_atoms, &tracks, "wireless_span_recovery")
            {
                let row_count = candidate.rows.max(0) as usize;
                let column_count = candidate.cols.max(0) as usize;
                let (_, conflicts) =
                    rebuild_occupancy_indices(&candidate.cells, row_count, column_count);
                let out_of_bounds = candidate.cells.iter().find(|cell| {
                    cell.row < 0
                        || cell.col < 0
                        || cell.row as usize >= row_count
                        || (cell.col as usize).saturating_add(cell.colspan.max(1) as usize)
                            > column_count
                });
                if conflicts.is_empty() && out_of_bounds.is_none() {
                    candidates.push(candidate);
                } else {
                    for (row, col) in conflicts {
                        diagnostics.push(occupancy_conflict_diagnostic(
                            "wireless_table_recovery.recover_wireless_tables",
                            row,
                            col,
                        ));
                    }
                    if let Some(cell) = out_of_bounds {
                        diagnostics.push(occupancy_out_of_bounds_diagnostic(
                            "wireless_table_recovery.recover_wireless_tables",
                            cell.row,
                            cell.col,
                            "candidate cell span is outside inferred tracks",
                        ));
                    }
                }
            }
            continue;
        }
        let bands = rescue_header_only_bands(
            &region_atoms,
            infer_column_bands(region_atoms.clone(), reg.clone()),
        );
        if bands.len() < 2 {
            continue;
        }

        let (rows, bands_out, mut phys_cells, _) = build_grid(region_atoms, bands);
        if rows.len() < 2 || bands_out.len() < 2 {
            continue;
        }
        merge_physical_inline_fragments(&mut phys_cells);
        let active_column_count = phys_cells
            .iter()
            .filter_map(|cell| usize::try_from(cell.col).ok())
            .collect::<std::collections::BTreeSet<_>>()
            .len();
        diagnostics.extend(physical_occupancy_diagnostics(
            &phys_cells,
            "wireless_table_recovery.recover_wireless_tables",
        ));

        let mut cells = Vec::new();
        let num_rows = rows.len();
        let num_cols = bands_out.len();
        let mut occupancy = vec![vec![None; num_cols]; num_rows];
        let mut has_conflict = false;

        for pc in phys_cells {
            if pc.row < 0 || pc.col < 0 {
                diagnostics.push(occupancy_out_of_bounds_diagnostic(
                    "wireless_table_recovery.recover_wireless_tables",
                    pc.row,
                    pc.col,
                    "physical cell has a negative grid index",
                ));
                has_conflict = true;
                continue;
            }
            let r = pc.row as usize;
            let (col_start, col_end) = physical_cell_span(&pc, &bands_out);
            if r >= num_rows || col_start >= num_cols || col_end >= num_cols {
                diagnostics.push(occupancy_out_of_bounds_diagnostic(
                    "wireless_table_recovery.recover_wireless_tables",
                    pc.row,
                    pc.col,
                    "physical cell span is outside inferred grid",
                ));
                has_conflict = true;
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

        merge_source_contiguous_vertical_cells(&mut cells, None, "columnar", None);
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
        let support_count = rows
            .iter()
            .filter(|row| row.item_indices.len() >= 2)
            .count();
        let confidence = (0.5
            + 0.15 * support_count.saturating_sub(1).min(3) as f64
            + 0.05 * active_column_count.saturating_sub(2).min(3) as f64)
            .min(0.95);

        let candidate = TableCandidateDto {
            schema_version: 1,
            rect: cand_rect,
            source: "wireless_span_recovery".to_string(),
            confidence: Some(confidence),
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
            col_end_hint: None,
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

    fn make_cell(text: &str, row: i64, col: i64, rowspan: i64, colspan: i64) -> CellDto {
        CellDto {
            schema_version: 1,
            text: text.to_string(),
            row,
            col,
            rect: Rect4 {
                schema_version: 1,
                x0: col as f64 * 10.0,
                y0: row as f64 * 10.0,
                x1: (col + colspan.max(1)) as f64 * 10.0,
                y1: (row + rowspan.max(1)) as f64 * 10.0,
            },
            rowspan,
            colspan,
            source: None,
        }
    }

    #[test]
    fn test_wide_candidate_atom_split_requires_one_labeled_part_per_track() {
        let prose = make_atom("普通说明   继续说明", 10.0, 10.0, 190.0, 20.0, 0);
        let three_fields = make_atom(
            "字段一：a   字段二：b   字段三：c",
            10.0,
            10.0,
            190.0,
            20.0,
            1,
        );

        assert_eq!(
            split_wide_candidate_atom_geometry(&prose, &[10.0, 150.0]),
            vec![prose]
        );
        assert_eq!(
            split_wide_candidate_atom_geometry(&three_fields, &[10.0, 150.0]),
            vec![three_fields]
        );
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
    fn test_full_page_candidate_runs_split_at_unlabeled_single_row() {
        let runs = full_page_atom_runs(vec![
            make_atom("项目", 10.0, 10.0, 40.0, 20.0, 0),
            make_atom("金额", 100.0, 10.0, 130.0, 20.0, 1),
            make_atom("甲", 10.0, 30.0, 30.0, 40.0, 2),
            make_atom("100", 100.0, 30.0, 125.0, 40.0, 3),
            make_atom("下一节", 10.0, 55.0, 45.0, 65.0, 4),
            make_atom("项目", 10.0, 75.0, 40.0, 85.0, 5),
            make_atom("金额", 100.0, 75.0, 130.0, 85.0, 6),
            make_atom("乙", 10.0, 95.0, 30.0, 105.0, 7),
            make_atom("200", 100.0, 95.0, 125.0, 105.0, 8),
        ]);

        assert_eq!(runs.len(), 2);
        assert_eq!((runs[0].0.y0, runs[0].0.y1), (10.0, 40.0));
        assert_eq!((runs[1].0.y0, runs[1].0.y1), (55.0, 105.0));
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
    fn test_build_grid_keeps_same_column_rows_separate_when_vertical_overlap_is_insufficient() {
        let bands = vec![ColumnBandDto {
            schema_version: 1,
            x0: 0.0,
            x1: 100.0,
            source_atoms: Vec::new(),
            order: 0,
        }];
        let atoms = vec![
            make_atom("上", 10.0, 0.0, 40.0, 10.0, 0),
            make_atom("下", 10.0, 9.0, 40.0, 19.0, 1),
        ];
        let (rows, _, _, _) = build_grid(atoms, bands);
        assert_eq!(rows.len(), 2);
    }

    #[test]
    fn test_build_grid_accepts_left_shifted_cjk_continuation_only_with_source_continuity() {
        let bands = vec![ColumnBandDto {
            schema_version: 1,
            x0: 0.0,
            x1: 100.0,
            source_atoms: Vec::new(),
            order: 0,
        }];
        let mut first = make_atom("长字段", 30.0, 0.0, 90.0, 10.0, 0);
        first.run_refs = vec![10];
        let mut second = make_atom("续", 10.0, 9.0, 25.0, 19.0, 1);
        second.run_refs = vec![11];
        let (rows, _, _, _) = build_grid(vec![first, second], bands);
        assert_eq!(rows.len(), 1);
    }

    #[test]
    fn test_build_grid_reports_duplicate_occupancy() {
        let bands = vec![ColumnBandDto {
            schema_version: 1,
            x0: 0.0,
            x1: 100.0,
            source_atoms: Vec::new(),
            order: 0,
        }];
        let (rows, _, _, diagnostics) = build_grid(
            vec![
                make_atom("甲", 10.0, 0.0, 40.0, 10.0, 0),
                make_atom("乙", 10.0, 0.0, 40.0, 10.0, 1),
            ],
            bands,
        );
        assert_eq!(rows.len(), 1);
        assert!(diagnostics
            .iter()
            .any(|item| item.status == "occupancy_conflict"));
    }

    #[test]
    fn test_build_grid_preserves_annotated_column_hint_over_bbox_overlap() {
        let bands = (0..2)
            .map(|index| ColumnBandDto {
                schema_version: 1,
                x0: index as f64 * 50.0,
                x1: index as f64 * 50.0 + 45.0,
                source_atoms: Vec::new(),
                order: index,
            })
            .collect();
        let mut atom = make_atom("字段", 5.0, 0.0, 80.0, 10.0, 0);
        atom.col_hint = Some(1);
        let (_, _, cells, _) = build_grid(vec![atom], bands);
        assert_eq!(cells[0].col, 1);
    }

    #[test]
    fn test_build_logical_grid_materializes_each_uncovered_slot_after_spans() {
        let atoms = vec![make_atom("跨列", 0.0, 0.0, 90.0, 10.0, 0)];
        let grid = GridDto {
            schema_version: 1,
            rows: 2,
            cols: 3,
            row_edges: vec![0.0, 10.0, 20.0],
            col_edges: vec![0.0, 30.0, 60.0, 90.0],
            occupancy: vec![vec![Some(0), Some(0), None], vec![None, None, None]],
        };
        let output = build_logical_grid(atoms, grid);
        assert_eq!(output.empty_slots.len(), 4);
        assert_eq!(
            output
                .cells
                .iter()
                .filter(|cell| cell.text.is_empty())
                .count(),
            4
        );
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            colspan: 1,
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

        merge_vertical_continuations(&mut cells, 3, None, None, "row_interleaved");

        assert_eq!(cells.len(), 1);
        assert_eq!(cells[0].text, "上半部\n下半部");
        assert_eq!(cells[0].rowspan, 2);

        let mut colon_cells = vec![
            CellDto {
                schema_version: 1,
                text: "其他应收款项：".to_string(),
                row: 0,
                col: 0,
                rect: source("其他应收款项：", 0, 10.0, 1).rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(source("其他应收款项：", 0, 10.0, 1)),
            },
            CellDto {
                schema_version: 1,
                text: "广东龙发股份有限公司".to_string(),
                row: 1,
                col: 0,
                rect: source("广东龙发股份有限公司", 1, 22.0, 2).rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(source("广东龙发股份有限公司", 1, 22.0, 2)),
            },
        ];

        merge_vertical_continuations(&mut colon_cells, 3, None, None, "row_interleaved");

        assert_eq!(colon_cells.len(), 2);

        let mut interleaved_cells = vec![
            CellDto {
                schema_version: 1,
                text: "项目".to_string(),
                row: 0,
                col: 0,
                rect: source("项目", 0, 10.0, 1).rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(source("项目", 0, 10.0, 1)),
            },
            CellDto {
                schema_version: 1,
                text: "金额".to_string(),
                row: 0,
                col: 1,
                rect: source("金额", 0, 10.0, 2).rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(source("金额", 0, 10.0, 2)),
            },
            CellDto {
                schema_version: 1,
                text: "续行".to_string(),
                row: 1,
                col: 0,
                rect: source("续行", 1, 22.0, 3).rect.clone(),
                rowspan: 1,
                colspan: 1,
                source: Some(source("续行", 1, 22.0, 3)),
            },
        ];
        merge_vertical_continuations(&mut interleaved_cells, 3, None, None, "row_interleaved");
        assert_eq!(interleaved_cells.len(), 3);
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            bands: Vec::new(),
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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
            atom_evidence: None,
            band_evidence: None,
            output_mode: "columnar".to_string(),
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

    #[test]
    fn test_refine_leaf_bands_splits_independent_body_tracks() {
        let atoms = vec![
            make_atom("股权比例", 25.0, 10.0, 75.0, 20.0, 1),
            make_atom("直接", 15.0, 30.0, 35.0, 40.0, 2),
            make_atom("间接", 65.0, 30.0, 85.0, 40.0, 3),
            make_atom("60", 15.0, 60.0, 35.0, 70.0, 4),
            make_atom("40", 65.0, 60.0, 85.0, 70.0, 5),
            make_atom("70", 15.0, 80.0, 35.0, 90.0, 6),
            make_atom("30", 65.0, 80.0, 85.0, 90.0, 7),
        ];
        let bands = vec![ColumnBandDto {
            schema_version: 1,
            x0: 10.0,
            x1: 90.0,
            source_atoms: Vec::new(),
            order: 0,
        }];

        let (refined, cutoff) = refine_leaf_bands(atoms, bands);

        assert_eq!(refined.len(), 2);
        assert_eq!((refined[0].x0, refined[0].x1), (10.0, 50.0));
        assert_eq!((refined[1].x0, refined[1].x1), (50.0, 90.0));
        assert!(cutoff.is_some());
    }

    #[test]
    fn test_logical_row_components_collapse_only_owned_continuation_rows() {
        let cells = vec![
            make_cell("父", 0, 0, 1, 1),
            make_cell("包裹叶一\n下", 1, 1, 2, 1),
            make_cell("包裹叶二\n下", 1, 2, 2, 1),
            make_cell("兄弟一", 2, 3, 1, 1),
            make_cell("兄弟二", 2, 4, 1, 1),
            make_cell("正文", 3, 0, 1, 1),
        ];

        let groups = logical_row_components(4, &cells, 3);

        assert_eq!(groups, vec![vec![0], vec![1, 2], vec![3]]);
    }

    #[test]
    fn test_logical_row_components_keeps_wrapped_header_rows_before_body_start_together() {
        let cells = vec![
            make_cell("wrapped header\nsecond line", 0, 2, 2, 1),
            make_cell("项目", 1, 0, 1, 1),
            make_cell("依据", 1, 1, 1, 1),
            make_cell("正文", 3, 0, 1, 1),
        ];

        let groups = logical_row_components(4, &cells, 1);

        assert_eq!(groups, vec![vec![0, 1, 2], vec![3]]);
    }

    #[test]
    fn test_logical_row_components_merges_body_prefix_span_that_starts_before_numeric_body() {
        let cells = vec![
            make_cell("表头", 0, 0, 1, 1),
            make_cell("表头续", 1, 1, 1, 1),
            make_cell("长正文\n续行\n续行", 2, 0, 3, 1),
            make_cell("100", 3, 1, 1, 1),
            make_cell("200", 3, 2, 1, 1),
            make_cell("下一行", 5, 0, 1, 1),
        ];

        let groups = logical_row_components(6, &cells, 3);

        assert_eq!(groups, vec![vec![0], vec![1], vec![2, 3, 4], vec![5]]);
    }

    #[test]
    fn test_header_body_start_keeps_dense_second_header_row_before_leaf_row() {
        let cells = vec![
            make_cell("parent", 0, 4, 1, 2),
            make_cell("stub0", 1, 0, 1, 1),
            make_cell("stub1", 1, 1, 1, 1),
            make_cell("stub2", 1, 2, 1, 1),
            make_cell("stub3", 1, 3, 1, 1),
            make_cell("stub6", 1, 6, 1, 1),
            make_cell("wrapped", 2, 1, 1, 1),
            make_cell("leaf4", 3, 4, 1, 1),
            make_cell("leaf5", 3, 5, 1, 1),
            make_cell("body0", 4, 0, 1, 1),
            make_cell("body1", 4, 1, 1, 1),
            make_cell("body2", 4, 2, 1, 1),
            make_cell("body3", 4, 3, 1, 1),
            make_cell("72.99", 4, 4, 1, 1),
        ];

        assert_eq!(header_body_start(&cells, 7, 7), 4);
    }

    #[test]
    fn test_header_span_transaction_rolls_back_conflicting_proposal() {
        let base = vec![make_cell("左", 0, 0, 1, 1), make_cell("下", 1, 0, 1, 1)];
        let mut proposed = base.clone();
        proposed[0].rowspan = 2;

        let committed = commit_header_span_proposal(&base, proposed, 2, 1);

        assert_eq!(committed, base);
    }

    #[test]
    fn test_header_span_inference_promotes_only_an_unblocked_stub() {
        let base = vec![
            make_cell("项目", 0, 0, 1, 1),
            make_cell("父", 0, 1, 1, 2),
            make_cell("左叶", 1, 1, 1, 1),
            make_cell("右叶", 1, 2, 1, 1),
        ];
        let valid = infer_header_spans(&base, 2);
        assert_eq!((valid[0].row, valid[0].rowspan), (0, 2));

        let blocked_base = [
            base[0].clone(),
            base[1].clone(),
            base[2].clone(),
            base[3].clone(),
            make_cell("非空", 1, 0, 1, 1),
        ];
        let blocked = infer_header_spans(&blocked_base, 2);
        assert_eq!((blocked[0].row, blocked[0].rowspan), (0, 1));
    }

    #[test]
    fn test_header_span_inference_rejects_incomplete_two_leaf_group() {
        let base = vec![
            make_cell("项目", 0, 0, 1, 1),
            make_cell("不完整父", 0, 1, 1, 2),
            make_cell("左叶", 1, 1, 1, 1),
        ];

        let proposed = infer_header_spans(&base, 2);

        assert_eq!(proposed[1].colspan, 1);
    }

    #[test]
    fn test_grouped_mixed_leaf_rejects_tall_single_row_wrapped_text() {
        let mut child = make_cell("子\n表头", 1, 1, 1, 1);
        child.rect.y1 = 30.0;
        let cells = vec![
            make_cell("父", 0, 1, 1, 2),
            child,
            make_cell("同层", 1, 2, 1, 1),
            make_cell("正文", 2, 0, 1, 1),
        ];

        let groups = logical_row_components(3, &cells, 2);

        assert_eq!(groups, vec![vec![0], vec![1], vec![2]]);
    }

    #[test]
    fn test_wrapped_leaf_rejects_tall_single_row_wrapped_text() {
        let mut first = make_cell("子\n表头一", 1, 1, 1, 1);
        first.rect.y1 = 30.0;
        let mut second = make_cell("子\n表头二", 1, 2, 1, 1);
        second.rect.y1 = 30.0;
        let cells = vec![
            make_cell("前", 0, 0, 1, 1),
            first,
            second,
            make_cell("正文", 2, 0, 1, 1),
        ];

        assert_eq!(wrapped_leaf_header_span(&cells, 1, 2), None);
        let groups = logical_row_components(3, &cells, 2);

        assert_eq!(groups, vec![vec![0], vec![1], vec![2]]);
    }

    #[test]
    fn test_build_grid_uses_column_hints_to_keep_overlapping_fields_separate() {
        let mut left = make_atom("左字段", 45.0, 10.0, 75.0, 20.0, 0);
        left.row_hint = Some(0);
        left.col_hint = Some(0);
        left.col_end_hint = Some(1);
        let mut right = make_atom("右字段", 45.0, 11.0, 75.0, 21.0, 1);
        right.row_hint = Some(0);
        right.col_hint = Some(1);
        right.col_end_hint = Some(2);
        let bands = vec![
            ColumnBandDto {
                schema_version: 1,
                x0: 0.0,
                x1: 50.0,
                source_atoms: Vec::new(),
                order: 0,
            },
            ColumnBandDto {
                schema_version: 1,
                x0: 50.0,
                x1: 100.0,
                source_atoms: Vec::new(),
                order: 1,
            },
            ColumnBandDto {
                schema_version: 1,
                x0: 100.0,
                x1: 150.0,
                source_atoms: Vec::new(),
                order: 2,
            },
        ];

        let (rows, _, _, diagnostics) = build_grid(vec![left, right], bands);

        assert_eq!(rows.len(), 2);
        assert!(diagnostics.is_empty());
    }

    #[test]
    fn test_cell_from_physical_preserves_explicit_single_column_assignment() {
        let bands = vec![
            ColumnBandDto {
                schema_version: 1,
                x0: 0.0,
                x1: 50.0,
                source_atoms: Vec::new(),
                order: 0,
            },
            ColumnBandDto {
                schema_version: 1,
                x0: 50.0,
                x1: 100.0,
                source_atoms: Vec::new(),
                order: 1,
            },
            ColumnBandDto {
                schema_version: 1,
                x0: 100.0,
                x1: 150.0,
                source_atoms: Vec::new(),
                order: 2,
            },
        ];
        let cell = PhysicalCell {
            schema_version: 1,
            text: "-".to_string(),
            rect: Rect4 {
                schema_version: 1,
                x0: 75.0,
                y0: 10.0,
                x1: 125.0,
                y1: 20.0,
            },
            row: 0,
            col: 1,
            colspan: 1,
            source_refs: vec![0],
        };

        let output = cell_from_physical(cell, &bands);

        assert_eq!((output.col, output.colspan), (1, 1));
    }

    #[test]
    fn test_merge_physical_inline_fragments_merges_far_contiguous_dash_markers() {
        let mut cells = vec![
            PhysicalCell {
                schema_version: 1,
                text: "-".to_string(),
                rect: Rect4 {
                    schema_version: 1,
                    x0: 10.0,
                    y0: 10.0,
                    x1: 15.0,
                    y1: 20.0,
                },
                row: 0,
                col: 0,
                colspan: 1,
                source_refs: vec![0],
            },
            PhysicalCell {
                schema_version: 1,
                text: "-".to_string(),
                rect: Rect4 {
                    schema_version: 1,
                    x0: 60.0,
                    y0: 10.0,
                    x1: 65.0,
                    y1: 20.0,
                },
                row: 0,
                col: 0,
                colspan: 1,
                source_refs: vec![1],
            },
        ];

        merge_physical_inline_fragments(&mut cells);

        assert_eq!(cells.len(), 1);
        assert_eq!(cells[0].text, "--");
        assert_eq!(cells[0].source_refs, vec![0, 1]);
    }

    #[test]
    fn test_merge_source_contiguous_vertical_cells_rejects_numbered_items() {
        let mut cells = vec![
            CellDto {
                schema_version: 1,
                text: "一、上年年末余额".to_string(),
                row: 0,
                col: 0,
                rect: Rect4 { schema_version: 1, x0: 10.0, y0: 10.0, x1: 100.0, y1: 20.0 },
                rowspan: 1,
                colspan: 1,
                source: Some(PhysicalCell {
                    schema_version: 1,
                    text: "一、上年年末余额".to_string(),
                    rect: Rect4 { schema_version: 1, x0: 10.0, y0: 10.0, x1: 100.0, y1: 20.0 },
                    row: 0,
                    col: 0,
                    colspan: 1,
                    source_refs: vec![0],
                }),
            },
            CellDto {
                schema_version: 1,
                text: "加：会计政策变更".to_string(),
                row: 1,
                col: 0,
                rect: Rect4 { schema_version: 1, x0: 10.0, y0: 22.0, x1: 100.0, y1: 32.0 },
                rowspan: 1,
                colspan: 1,
                source: Some(PhysicalCell {
                    schema_version: 1,
                    text: "加：会计政策变更".to_string(),
                    rect: Rect4 { schema_version: 1, x0: 10.0, y0: 22.0, x1: 100.0, y1: 32.0 },
                    row: 1,
                    col: 0,
                    colspan: 1,
                    source_refs: vec![1],
                }),
            },
            CellDto {
                schema_version: 1,
                text: "二、本年年初余额".to_string(),
                row: 2,
                col: 0,
                rect: Rect4 { schema_version: 1, x0: 10.0, y0: 34.0, x1: 100.0, y1: 44.0 },
                rowspan: 1,
                colspan: 1,
                source: Some(PhysicalCell {
                    schema_version: 1,
                    text: "二、本年年初余额".to_string(),
                    rect: Rect4 { schema_version: 1, x0: 10.0, y0: 34.0, x1: 100.0, y1: 44.0 },
                    row: 2,
                    col: 0,
                    colspan: 1,
                    source_refs: vec![2],
                }),
            },
        ];

        merge_source_contiguous_vertical_cells(&mut cells, None, "columnar", None);

        assert_eq!(cells.len(), 3, "Numbered items must NOT be vertically merged");
        assert_eq!(cells[0].rowspan, 1);
        assert_eq!(cells[1].rowspan, 1);
        assert_eq!(cells[2].rowspan, 1);
    }

    #[test]
    fn test_merge_source_contiguous_vertical_cells_keeps_separate_source_lines() {
        let source_cell = |text: &str, row: i64, source_ref: i64| -> CellDto {
            let mut cell = make_cell(text, row, 0, 1, 1);
            cell.source = Some(PhysicalCell {
                schema_version: 1,
                text: text.to_string(),
                rect: cell.rect.clone(),
                row,
                col: 0,
                colspan: 1,
                source_refs: vec![source_ref],
            });
            cell
        };
        let mut cells = vec![
            source_cell("前期差错更正", 0, 0),
            source_cell("其他", 1, 1),
        ];
        let evidence = vec![
            AtomEvidenceDto {
                flow_start: 1,
                flow_end: 1,
                source_blocks: vec![1],
                source_line_start: 0,
                source_line_end: 0,
                source_position_known: true,
                column_id: Some(0),
            },
            AtomEvidenceDto {
                flow_start: 2,
                flow_end: 2,
                source_blocks: vec![2],
                source_line_start: 1,
                source_line_end: 1,
                source_position_known: true,
                column_id: Some(0),
            },
        ];

        merge_source_contiguous_vertical_cells(&mut cells, Some(&evidence), "columnar", None);

        assert_eq!(cells.len(), 2);
        assert!(cells.iter().all(|cell| cell.rowspan == 1));
    }

    #[test]
    fn test_merge_source_contiguous_vertical_cells_rejects_financial_row_gap() {
        let mut first = make_cell("资产", 0, 0, 1, 1);
        first.source = Some(PhysicalCell {
            schema_version: 1,
            text: first.text.clone(),
            rect: first.rect.clone(),
            row: 0,
            col: 0,
            colspan: 1,
            source_refs: vec![11],
        });
        let mut second = make_cell("负债", 1, 0, 1, 1);
        second.rect.y0 = 29.8;
        second.rect.y1 = 39.8;
        second.source = Some(PhysicalCell {
            schema_version: 1,
            text: second.text.clone(),
            rect: second.rect.clone(),
            row: 1,
            col: 0,
            colspan: 1,
            source_refs: vec![12],
        });
        let mut cells = vec![first, second];
        let evidence = [
            AtomEvidenceDto {
                flow_start: 11,
                flow_end: 11,
                source_blocks: vec![0],
                source_line_start: 0,
                source_line_end: 0,
                source_position_known: true,
                column_id: Some(0),
            },
            AtomEvidenceDto {
                flow_start: 12,
                flow_end: 12,
                source_blocks: vec![0],
                source_line_start: 1,
                source_line_end: 1,
                source_position_known: true,
                column_id: Some(0),
            },
        ];
        merge_source_contiguous_vertical_cells(
            &mut cells,
            Some(&evidence),
            "row_interleaved",
            None,
        );
        assert_eq!(cells.len(), 2);
        assert!(cells.iter().all(|cell| cell.rowspan == 1));
    }

    #[test]
    fn test_merge_source_evidence_uses_native_run_refs_not_filtered_flow() {
        let cell = |text: &str, row: i64, source_ref: i64| {
            let mut cell = make_cell(text, row, 0, 1, 1);
            cell.source = Some(PhysicalCell {
                schema_version: 1,
                text: text.to_string(),
                rect: cell.rect.clone(),
                row,
                col: 0,
                colspan: 1,
                source_refs: vec![source_ref],
            });
            cell
        };
        let atom = |text: &str, source_ref: i64, order: i64| AtomDto {
            schema_version: 1,
            text: text.to_string(),
            rect: Rect4 {
                schema_version: 1,
                x0: order as f64 * 10.0,
                y0: 10.0,
                x1: order as f64 * 10.0 + 8.0,
                y1: 18.0,
            },
            run_refs: vec![source_ref],
            row_hint: None,
            col_hint: None,
            col_end_hint: None,
            order,
        };
        let evidence = |flow_start: i64, block: i64, line: i64| AtomEvidenceDto {
            flow_start,
            flow_end: flow_start,
            source_blocks: vec![block],
            source_line_start: line,
            source_line_end: line,
            source_position_known: true,
            column_id: Some(0),
        };

        let mut cells = vec![cell("应付票据", 0, 11), cell("应付账款", 1, 12)];
        let atoms = vec![
            atom("应付票据", 11, 0),
            atom("应付账款", 12, 1),
            atom("注释", 14, 2),
            atom("12", 15, 3),
        ];
        // Native refs 11/12 must map to their own atoms, rather than filtered
        // flow entries 12/13, which both belong to block 9.
        let evidence = vec![
            evidence(9, 8, 0),
            evidence(10, 9, 0),
            evidence(12, 9, 0),
            evidence(13, 9, 1),
        ];

        merge_source_contiguous_vertical_cells(
            &mut cells,
            Some(&evidence),
            "columnar",
            Some(&atoms),
        );

        assert_eq!(cells.len(), 2);
        assert!(cells.iter().all(|cell| cell.rowspan == 1));
    }

    #[test]
    fn test_merge_physical_inline_fragments_merges_vertical_wrap_continuation() {
        let mut cells = vec![
            PhysicalCell {
                schema_version: 1,
                text: "长春海吉星二期用".to_string(),
                rect: Rect4 { schema_version: 1, x0: 20.0, y0: 10.0, x1: 100.0, y1: 20.0 },
                row: 5,
                col: 0,
                colspan: 1,
                source_refs: vec![10],
            },
            PhysicalCell {
                schema_version: 1,
                text: "地".to_string(),
                rect: Rect4 { schema_version: 1, x0: 10.0, y0: 22.0, x1: 20.0, y1: 32.0 },
                row: 5,
                col: 0,
                colspan: 1,
                source_refs: vec![11],
            },
        ];

        merge_physical_inline_fragments(&mut cells);

        assert_eq!(cells.len(), 1, "Wrapped fragments in same physical slot must merge");
        assert_eq!(cells[0].text, "长春海吉星二期用\n地");
        assert_eq!(cells[0].source_refs, vec![10, 11]);
    }

    #[test]
    fn test_merge_evidence_contiguous_vertical_header_chain_merges_eight_glyphs() {
        let glyphs = ["减", "值", "准", "备", "期", "末", "余", "额"];
        let mut cells = Vec::new();
        let mut atoms = Vec::new();
        let mut evidence = Vec::new();
        for (row, text) in glyphs.into_iter().enumerate() {
            let y0 = 10.0 + row as f64 * 13.0;
            let mut cell = make_cell(text, row as i64, 0, 1, 1);
            cell.rect = Rect4 {
                schema_version: 1,
                x0: 100.0,
                y0,
                x1: 110.0,
                y1: y0 + 10.0,
            };
            cell.source = Some(PhysicalCell {
                schema_version: 1,
                text: text.to_string(),
                rect: cell.rect.clone(),
                row: row as i64,
                col: 0,
                colspan: 1,
                source_refs: vec![row as i64],
            });
            cells.push(cell);
            atoms.push(make_atom(text, 100.0, y0, 110.0, y0 + 10.0, row as i64));
            evidence.push(AtomEvidenceDto {
                flow_start: row as i64 + 1,
                flow_end: row as i64 + 1,
                source_blocks: vec![9],
                source_line_start: row as i64,
                source_line_end: row as i64,
                source_position_known: true,
                column_id: Some(0),
            });
        }

        merge_evidence_contiguous_vertical_header_chain(&mut cells, Some(&evidence), Some(&atoms));

        assert_eq!(cells.len(), 1);
        assert_eq!(cells[0].rowspan, 8);
        assert_eq!(cells[0].text, glyphs.join("\n"));
    }
}
