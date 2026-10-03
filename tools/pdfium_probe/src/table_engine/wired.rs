use crate::table_engine::geometry::{calculate_coverage, lines_intersect, Line4};
use crate::table_engine::types::{
    CellDto, CharacterDto, GridDto, Rect4, RegionDto, WiredRegionInput, WiredRegionOutput, WordDto,
};
use std::collections::{BTreeMap, HashMap, HashSet};

pub fn find_table_regions(
    h_lines: Vec<Line4>,
    v_lines: Vec<Line4>,
    tolerance: f64,
) -> Vec<(Rect4, Vec<Line4>, Vec<Line4>)> {
    if h_lines.len() < 2 || v_lines.is_empty() {
        return Vec::new();
    }

    let mut filtered_h: Vec<Line4> = h_lines
        .into_iter()
        .filter(|&hl| v_lines.iter().any(|&vl| lines_intersect(hl, vl, tolerance)))
        .collect();

    let filtered_v: Vec<Line4> = v_lines
        .into_iter()
        .filter(|&vl| {
            filtered_h
                .iter()
                .any(|&hl| lines_intersect(hl, vl, tolerance))
        })
        .collect();

    filtered_h.retain(|&hl| {
        filtered_v
            .iter()
            .any(|&vl| lines_intersect(hl, vl, tolerance))
    });

    if filtered_h.len() < 2 || filtered_v.is_empty() {
        return Vec::new();
    }

    let h_count = filtered_h.len();
    let v_count = filtered_v.len();

    let mut h_to_v: Vec<Vec<usize>> = vec![Vec::new(); h_count];
    let mut v_to_h: Vec<Vec<usize>> = vec![Vec::new(); v_count];

    for (h_idx, &hl) in filtered_h.iter().enumerate() {
        for (v_idx, &vl) in filtered_v.iter().enumerate() {
            if lines_intersect(hl, vl, tolerance) {
                h_to_v[h_idx].push(v_idx);
                v_to_h[v_idx].push(h_idx);
            }
        }
    }

    let mut visited_h = vec![false; h_count];
    let mut visited_v = vec![false; v_count];
    let mut components = Vec::new();

    for start_h in 0..h_count {
        if visited_h[start_h] {
            continue;
        }

        let mut comp_h = Vec::new();
        let mut comp_v = Vec::new();
        let mut pending: Vec<(bool, usize)> = vec![(true, start_h)];

        while let Some((is_h, idx)) = pending.pop() {
            if is_h {
                if visited_h[idx] {
                    continue;
                }
                visited_h[idx] = true;
                comp_h.push(idx);
                for &v_idx in &h_to_v[idx] {
                    if !visited_v[v_idx] {
                        pending.push((false, v_idx));
                    }
                }
            } else {
                if visited_v[idx] {
                    continue;
                }
                visited_v[idx] = true;
                comp_v.push(idx);
                for &h_idx in &v_to_h[idx] {
                    if !visited_h[h_idx] {
                        pending.push((true, h_idx));
                    }
                }
            }
        }

        if comp_h.len() < 2 || comp_v.is_empty() {
            continue;
        }

        comp_h.sort_unstable();
        comp_v.sort_unstable();

        let comp_h_lines: Vec<Line4> = comp_h.into_iter().map(|idx| filtered_h[idx]).collect();
        let comp_v_lines: Vec<Line4> = comp_v.into_iter().map(|idx| filtered_v[idx]).collect();
        components.push((comp_h_lines, comp_v_lines));
    }

    let mut regions = Vec::new();
    for (comp_h, comp_v) in components {
        let mut min_x = f64::INFINITY;
        let mut max_x = f64::NEG_INFINITY;
        let mut min_y = f64::INFINITY;
        let mut max_y = f64::NEG_INFINITY;

        for l in &comp_h {
            min_x = min_x.min(l.0.min(l.2));
            max_x = max_x.max(l.0.max(l.2));
            min_y = min_y.min(l.1);
            max_y = max_y.max(l.1);
        }
        for l in &comp_v {
            min_x = min_x.min(l.0);
            max_x = max_x.max(l.0);
            min_y = min_y.min(l.1.min(l.3));
            max_y = max_y.max(l.1.max(l.3));
        }

        let bbox = Rect4 {
            schema_version: 1,
            x0: min_x,
            y0: min_y,
            x1: max_x,
            y1: max_y,
        };
        regions.push((bbox, comp_h, comp_v));
    }

    regions.sort_by(|a, b| match a.0.y0.partial_cmp(&b.0.y0) {
        Some(std::cmp::Ordering::Equal) => {
            a.0.x0
                .partial_cmp(&b.0.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        }
        Some(ord) => ord,
        None => std::cmp::Ordering::Equal,
    });

    regions
}

pub fn complete_partial_outer_boundaries(
    bbox: Rect4,
    h_lines: Vec<Line4>,
    v_lines: Vec<Line4>,
    h_ys: Vec<f64>,
    v_xs: Vec<f64>,
    line_tolerance: f64,
    merge_group_tol: f64,
) -> (Vec<Line4>, Vec<Line4>) {
    let tol = line_tolerance;
    let mut effective_h = h_lines.clone();
    let mut effective_v = v_lines.clone();

    if v_xs.len() < 2 || h_ys.len() < 2 {
        return (effective_h, effective_v);
    }

    let endpoint_anchor_tol = merge_group_tol;

    let touches = |val: f64, anchors: &[f64]| -> bool {
        anchors
            .iter()
            .any(|&a| (val - a).abs() <= endpoint_anchor_tol)
    };

    let reaches_outer_endpoint = |start: f64, end: f64, outer_start: f64, outer_end: f64| -> bool {
        (start - outer_start).abs() <= tol || (end - outer_end).abs() <= tol
    };

    let width = v_xs.last().unwrap() - v_xs[0];
    let height = h_ys.last().unwrap() - h_ys[0];
    let full_width = (width - tol).max(width * 0.9);
    let full_height = (height - tol).max(height * 0.9);

    let full_width_levels: Vec<f64> = h_ys
        .iter()
        .copied()
        .filter(|&y| {
            let segs: Vec<(f64, f64)> = h_lines
                .iter()
                .filter(|l| (l.1 - y).abs() <= tol)
                .map(|l| (l.0.min(l.2), l.0.max(l.2)))
                .collect();
            calculate_coverage(&segs, v_xs[0], *v_xs.last().unwrap(), tol) >= full_width
        })
        .collect();

    for &y in &[h_ys[0], *h_ys.last().unwrap()] {
        let boundary: Vec<Line4> = h_lines
            .iter()
            .copied()
            .filter(|l| (l.1 - y).abs() <= tol)
            .collect();
        let boundary_segs: Vec<(f64, f64)> = boundary
            .iter()
            .map(|l| (l.0.min(l.2), l.0.max(l.2)))
            .collect();
        let boundary_coverage =
            calculate_coverage(&boundary_segs, v_xs[0], *v_xs.last().unwrap(), tol);

        if !boundary.is_empty() && boundary_coverage < full_width {
            let supported = full_width_levels
                .iter()
                .filter(|&&level| (level - y).abs() > tol)
                .count()
                >= 2;

            let mid_xs = if v_xs.len() > 2 {
                &v_xs[1..v_xs.len() - 1]
            } else {
                &[]
            };

            let mut covers_grid_column = false;
            for line in &boundary {
                let l_min = line.0.min(line.2);
                let l_max = line.0.max(line.2);
                for (left, right) in v_xs.iter().zip(v_xs.iter().skip(1)) {
                    let col_width = right - left;
                    let req_col_cov = (col_width - tol).max(col_width * 0.9);
                    let seg = [(l_min, l_max)];
                    let seg_cov = calculate_coverage(&seg, *left, *right, tol);
                    if seg_cov >= req_col_cov
                        && (touches(l_min, mid_xs) || touches(l_max, mid_xs))
                        && reaches_outer_endpoint(l_min, l_max, bbox.x0, bbox.x1)
                    {
                        covers_grid_column = true;
                        break;
                    }
                }
                if covers_grid_column {
                    break;
                }
            }

            if supported && covers_grid_column {
                effective_h.push((v_xs[0], y, *v_xs.last().unwrap(), y));
            }
        }
    }

    for &x in &[v_xs[0], *v_xs.last().unwrap()] {
        let boundary: Vec<Line4> = v_lines
            .iter()
            .copied()
            .filter(|l| (l.0 - x).abs() <= tol)
            .collect();
        let boundary_segs: Vec<(f64, f64)> = boundary
            .iter()
            .map(|l| (l.1.min(l.3), l.1.max(l.3)))
            .collect();
        let boundary_coverage =
            calculate_coverage(&boundary_segs, h_ys[0], *h_ys.last().unwrap(), tol);

        if !boundary.is_empty() && boundary_coverage < full_height {
            let supported = full_width_levels.len() >= 3;

            let mid_ys = if h_ys.len() > 2 {
                &h_ys[1..h_ys.len() - 1]
            } else {
                &[]
            };

            let mut covers_grid_row = false;
            for line in &boundary {
                let l_min = line.1.min(line.3);
                let l_max = line.1.max(line.3);
                for (top, bottom) in h_ys.iter().zip(h_ys.iter().skip(1)) {
                    let row_height = bottom - top;
                    let req_row_cov = (row_height - tol).max(row_height * 0.9);
                    let seg = [(l_min, l_max)];
                    let seg_cov = calculate_coverage(&seg, *top, *bottom, tol);
                    if seg_cov >= req_row_cov
                        && (touches(l_min, mid_ys) || touches(l_max, mid_ys))
                        && reaches_outer_endpoint(l_min, l_max, bbox.y0, bbox.y1)
                    {
                        covers_grid_row = true;
                        break;
                    }
                }
                if covers_grid_row {
                    break;
                }
            }

            if supported && covers_grid_row {
                effective_v.push((x, h_ys[0], x, *h_ys.last().unwrap()));
            }
        }
    }

    (effective_h, effective_v)
}

pub fn check_occupancy_conflicts(cells: &[CellDto]) -> Result<(), String> {
    let mut occupied: HashSet<(i64, i64)> = HashSet::new();
    for (idx, cell) in cells.iter().enumerate() {
        let r_span = cell.rowspan.max(1);
        let c_span = cell.colspan.max(1);
        for r in cell.row..(cell.row + r_span) {
            for c in cell.col..(cell.col + c_span) {
                if !occupied.insert((r, c)) {
                    return Err(format!(
                        "Occupancy conflict at row {}, col {} for cell index {}",
                        r, c, idx
                    ));
                }
            }
        }
    }
    Ok(())
}

pub fn build_cells_for_region(
    bbox: Rect4,
    h_lines: Vec<Line4>,
    v_lines: Vec<Line4>,
    line_tolerance: f64,
    merge_group_tol: f64,
) -> Vec<CellDto> {
    let mut existing_v_xs: Vec<f64> = v_lines.iter().map(|l| l.0).collect();
    let mut effective_v_lines = v_lines.clone();

    if !existing_v_xs.is_empty() {
        existing_v_xs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let left_v_x = *existing_v_xs.first().unwrap();

        let mut sorted_h_start = h_lines.clone();
        sorted_h_start.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        let mut start_clusters: Vec<Vec<Line4>> = Vec::new();
        for line in sorted_h_start {
            let mut matched = false;
            for cluster in &mut start_clusters {
                if (cluster[0].0 - line.0).abs() <= line_tolerance {
                    cluster.push(line);
                    matched = true;
                    break;
                }
            }
            if !matched {
                start_clusters.push(vec![line]);
            }
        }

        for cluster in start_clusters {
            let avg_start_x = cluster.iter().map(|l| l.0).sum::<f64>() / cluster.len() as f64;
            if cluster.len() >= 2
                && avg_start_x > bbox.x0 + line_tolerance
                && avg_start_x < left_v_x - line_tolerance
            {
                effective_v_lines.push((avg_start_x, bbox.y0, avg_start_x, bbox.y1));
                break;
            }
        }

        let right_v_x = *existing_v_xs.last().unwrap();
        let mut sorted_h_end = h_lines.clone();
        sorted_h_end.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));
        let mut end_clusters: Vec<Vec<Line4>> = Vec::new();
        for line in sorted_h_end {
            let mut matched = false;
            for cluster in &mut end_clusters {
                if (cluster[0].2 - line.2).abs() <= line_tolerance {
                    cluster.push(line);
                    matched = true;
                    break;
                }
            }
            if !matched {
                end_clusters.push(vec![line]);
            }
        }

        for cluster in end_clusters {
            let avg_end_x = cluster.iter().map(|l| l.2).sum::<f64>() / cluster.len() as f64;
            if cluster.len() >= 2
                && avg_end_x < bbox.x1 - line_tolerance
                && avg_end_x > right_v_x + line_tolerance
            {
                effective_v_lines.push((avg_end_x, bbox.y0, avg_end_x, bbox.y1));
                break;
            }
        }
    }

    let h_ys = crate::table_engine::geometry::snap_grid_coordinates(
        bbox.y0,
        bbox.y1,
        bbox.x0,
        bbox.x1,
        &h_lines,
        true,
        line_tolerance,
        merge_group_tol,
    );
    let v_xs = crate::table_engine::geometry::snap_grid_coordinates(
        bbox.x0,
        bbox.x1,
        bbox.y0,
        bbox.y1,
        &effective_v_lines,
        false,
        line_tolerance,
        merge_group_tol,
    );

    if h_ys.len() < 2 || v_xs.len() < 2 {
        return Vec::new();
    }

    let rows = h_ys.len() - 1;
    let cols = v_xs.len() - 1;

    let (mut eff_h, mut eff_v) = complete_partial_outer_boundaries(
        bbox.clone(),
        h_lines.clone(),
        effective_v_lines,
        h_ys.clone(),
        v_xs.clone(),
        line_tolerance,
        merge_group_tol,
    );

    let first_y = h_ys[0];
    let last_y = *h_ys.last().unwrap();
    let first_x = v_xs[0];
    let last_x = *v_xs.last().unwrap();

    if !h_lines
        .iter()
        .any(|l| (l.1 - first_y).abs() <= line_tolerance)
    {
        eff_h.push((first_x, first_y, last_x, first_y));
    }
    if !h_lines
        .iter()
        .any(|l| (l.1 - last_y).abs() <= line_tolerance)
    {
        eff_h.push((first_x, last_y, last_x, last_y));
    }
    if !v_lines
        .iter()
        .any(|l| (l.0 - first_x).abs() <= line_tolerance)
    {
        eff_v.push((first_x, first_y, first_x, last_y));
    }
    if !v_lines
        .iter()
        .any(|l| (l.0 - last_x).abs() <= line_tolerance)
    {
        eff_v.push((last_x, first_y, last_x, last_y));
    }

    let has_h_segment = |y: f64, x0: f64, x1: f64| -> bool {
        let span = x1 - x0;
        let candidates: Vec<&Line4> = eff_h
            .iter()
            .filter(|l| (l.1 - y).abs() <= line_tolerance)
            .collect();
        if candidates.is_empty() {
            return false;
        }
        let nearest_dist = candidates
            .iter()
            .map(|l| (l.1 - y).abs())
            .fold(f64::INFINITY, f64::min);
        for l in candidates {
            if ((l.1 - y).abs() - nearest_dist).abs() > 1e-6 {
                continue;
            }
            let overlap = l.2.min(x1 + line_tolerance) - l.0.max(x0 - line_tolerance);
            if overlap >= (span - line_tolerance).max(span * 0.9) {
                return true;
            }
        }
        false
    };

    let has_v_segment = |x: f64, y0: f64, y1: f64| -> bool {
        let span = y1 - y0;
        let candidates: Vec<&Line4> = eff_v
            .iter()
            .filter(|l| (l.0 - x).abs() <= line_tolerance)
            .collect();
        if candidates.is_empty() {
            return false;
        }
        let nearest_dist = candidates
            .iter()
            .map(|l| (l.0 - x).abs())
            .fold(f64::INFINITY, f64::min);
        for l in candidates {
            if ((l.0 - x).abs() - nearest_dist).abs() > 1e-6 {
                continue;
            }
            let overlap = l.3.min(y1 + line_tolerance) - l.1.max(y0 - line_tolerance);
            if overlap >= (span - line_tolerance).max(span * 0.9) {
                return true;
            }
        }
        false
    };

    let mut h_edges = vec![vec![false; cols]; rows + 1];
    for r in 0..=rows {
        for c in 0..cols {
            h_edges[r][c] = has_h_segment(h_ys[r], v_xs[c], v_xs[c + 1]);
        }
    }

    let mut v_edges = vec![vec![false; cols + 1]; rows];
    for r in 0..rows {
        for c in 0..=cols {
            v_edges[r][c] = has_v_segment(v_xs[c], h_ys[r], h_ys[r + 1]);
        }
    }

    let mut outside: HashSet<(usize, usize)> = HashSet::new();
    let mut stack: Vec<(usize, usize)> = Vec::new();

    let mark_outside = |r: usize,
                        c: usize,
                        outside: &mut HashSet<(usize, usize)>,
                        stack: &mut Vec<(usize, usize)>| {
        if outside.insert((r, c)) {
            stack.push((r, c));
        }
    };

    for c in 0..cols {
        if !h_edges[0][c] {
            mark_outside(0, c, &mut outside, &mut stack);
        }
        if !h_edges[rows][c] {
            mark_outside(rows - 1, c, &mut outside, &mut stack);
        }
    }
    for r in 0..rows {
        if !v_edges[r][0] {
            mark_outside(r, 0, &mut outside, &mut stack);
        }
        if !v_edges[r][cols] {
            mark_outside(r, cols - 1, &mut outside, &mut stack);
        }
    }

    while let Some((r, c)) = stack.pop() {
        if r > 0 && !h_edges[r][c] {
            mark_outside(r - 1, c, &mut outside, &mut stack);
        }
        if r + 1 < rows && !h_edges[r + 1][c] {
            mark_outside(r + 1, c, &mut outside, &mut stack);
        }
        if c > 0 && !v_edges[r][c] {
            mark_outside(r, c - 1, &mut outside, &mut stack);
        }
        if c + 1 < cols && !v_edges[r][c + 1] {
            mark_outside(r, c + 1, &mut outside, &mut stack);
        }
    }

    let mut inside_cells = Vec::new();
    for r in 0..rows {
        for c in 0..cols {
            if !outside.contains(&(r, c)) {
                inside_cells.push((r, c));
            }
        }
    }

    if inside_cells.is_empty() {
        return Vec::new();
    }

    let mut parent: Vec<usize> = (0..(rows * cols)).collect();
    let cell_id = |r: usize, c: usize| -> usize { r * cols + c };

    fn find(mut i: usize, parent: &mut [usize]) -> usize {
        while parent[i] != i {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        i
    }

    fn union(i: usize, j: usize, parent: &mut [usize]) {
        let ri = find(i, parent);
        let rj = find(j, parent);
        if ri != rj {
            parent[rj] = ri;
        }
    }

    let inside_set: HashSet<(usize, usize)> = inside_cells.iter().copied().collect();
    for &(r, c) in &inside_cells {
        if c + 1 < cols && inside_set.contains(&(r, c + 1)) && !v_edges[r][c + 1] {
            union(cell_id(r, c), cell_id(r, c + 1), &mut parent);
        }
        if r + 1 < rows && inside_set.contains(&(r + 1, c)) && !h_edges[r + 1][c] {
            union(cell_id(r, c), cell_id(r + 1, c), &mut parent);
        }
    }

    let mut components: HashMap<usize, Vec<(usize, usize)>> = HashMap::new();
    for &(r, c) in &inside_cells {
        let root = find(cell_id(r, c), &mut parent);
        components.entry(root).or_default().push((r, c));
    }

    let mut cells: Vec<CellDto> = Vec::new();

    for coords in components.values() {
        let component_set: HashSet<(usize, usize)> = coords.iter().copied().collect();
        let mut rows_with_cells: BTreeMap<usize, Vec<(usize, usize)>> = BTreeMap::new();

        let mut row_set: Vec<usize> = component_set.iter().map(|(r, _)| *r).collect();
        row_set.sort_unstable();
        row_set.dedup();

        for r in row_set {
            let mut columns: Vec<usize> = component_set
                .iter()
                .filter(|(cr, _)| *cr == r)
                .map(|(_, c)| *c)
                .collect();
            columns.sort_unstable();
            if columns.is_empty() {
                continue;
            }

            let mut start_col = columns[0];
            let mut previous_col = columns[0];

            for &c in &columns[1..] {
                if c == previous_col + 1 && !v_edges[r][c] {
                    previous_col = c;
                    continue;
                }
                rows_with_cells
                    .entry(r)
                    .or_default()
                    .push((start_col, previous_col));
                start_col = c;
                previous_col = c;
            }
            rows_with_cells
                .entry(r)
                .or_default()
                .push((start_col, previous_col));
        }

        let mut active: HashMap<(usize, usize), (usize, usize, usize, usize)> = HashMap::new();
        let mut rectangles: Vec<(usize, usize, usize, usize)> = Vec::new();

        for (&r, runs) in &rows_with_cells {
            let mut next_active: HashMap<(usize, usize), (usize, usize, usize, usize)> =
                HashMap::new();
            for &(start_col, end_col) in runs {
                let run = (start_col, end_col);
                if let Some(mut rect) = active.get(&run).copied() {
                    let mut all_no_h = true;
                    for col in start_col..=end_col {
                        if h_edges[r][col] {
                            all_no_h = false;
                            break;
                        }
                    }
                    if all_no_h {
                        rect.2 = r;
                        next_active.insert(run, rect);
                    } else {
                        rectangles.push(rect);
                        let new_rect = (r, start_col, r, end_col);
                        next_active.insert(run, new_rect);
                    }
                } else {
                    let new_rect = (r, start_col, r, end_col);
                    next_active.insert(run, new_rect);
                }
            }
            for (run, rect) in active {
                if !next_active.contains_key(&run) {
                    rectangles.push(rect);
                }
            }
            active = next_active;
        }
        for (_, rect) in active {
            rectangles.push(rect);
        }

        for (start_row, start_col, end_row, end_col) in rectangles {
            cells.push(CellDto {
                schema_version: 1,
                text: String::new(),
                row: start_row as i64,
                col: start_col as i64,
                rect: Rect4 {
                    schema_version: 1,
                    x0: v_xs[start_col],
                    y0: h_ys[start_row],
                    x1: v_xs[end_col + 1],
                    y1: h_ys[end_row + 1],
                },
                rowspan: (end_row - start_row + 1) as i64,
                colspan: (end_col - start_col + 1) as i64,
                source: None,
            });
        }
    }

    if !cells.is_empty() {
        let min_c = cells.iter().map(|c| c.col).min().unwrap_or(0);
        if min_c > 0 {
            for c in &mut cells {
                c.col -= min_c;
            }
        }
    }

    cells.sort_by(|a, b| match a.row.cmp(&b.row) {
        std::cmp::Ordering::Equal => a.col.cmp(&b.col),
        ord => ord,
    });

    let _ = check_occupancy_conflicts(&cells);
    cells
}

pub fn trim_ghost_edge_rows(cells: Vec<CellDto>, h_lines: &[Line4], tol: f64) -> Vec<CellDto> {
    if cells.is_empty() {
        return cells;
    }

    let mut row_indices: Vec<i64> = cells.iter().map(|c| c.row).collect();
    row_indices.sort_unstable();
    row_indices.dedup();
    if row_indices.is_empty() {
        return cells;
    }

    let mut min_row = row_indices[0];
    let mut max_row = *row_indices.last().unwrap();

    while min_row <= max_row {
        let row_cells: Vec<&CellDto> = cells.iter().filter(|c| c.row == min_row).collect();
        if row_cells.is_empty() {
            min_row += 1;
            continue;
        }
        let has_text = row_cells.iter().any(|c| !c.text.trim().is_empty());
        if has_text {
            break;
        }

        let top_y = row_cells
            .iter()
            .map(|c| c.rect.y0)
            .fold(f64::INFINITY, f64::min);
        let bot_y = row_cells
            .iter()
            .map(|c| c.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max);
        let height = bot_y - top_y;
        let has_real_top_line = h_lines.iter().any(|l| (l.1 - top_y).abs() <= tol);

        if height <= tol || !has_real_top_line {
            min_row += 1;
        } else {
            break;
        }
    }

    while max_row >= min_row {
        let row_cells: Vec<&CellDto> = cells.iter().filter(|c| c.row == max_row).collect();
        if row_cells.is_empty() {
            max_row -= 1;
            continue;
        }
        let has_text = row_cells.iter().any(|c| !c.text.trim().is_empty());
        if has_text {
            break;
        }

        let top_y = row_cells
            .iter()
            .map(|c| c.rect.y0)
            .fold(f64::INFINITY, f64::min);
        let bot_y = row_cells
            .iter()
            .map(|c| c.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max);
        let height = bot_y - top_y;
        let has_real_bot_line = h_lines.iter().any(|l| (l.1 - bot_y).abs() <= tol);

        if height <= tol || !has_real_bot_line {
            max_row -= 1;
        } else {
            break;
        }
    }

    if min_row > max_row {
        return Vec::new();
    }

    let mut trimmed = Vec::new();
    for mut c in cells {
        if c.row >= min_row && c.row <= max_row {
            c.rowspan = c.rowspan.min(max_row - c.row + 1);
            c.row -= min_row;
            trimmed.push(c);
        }
    }

    let _ = check_occupancy_conflicts(&trimmed);
    trimmed
}

pub fn merge_oversegmented_line_columns(cells: Vec<CellDto>, line_tolerance: f64) -> Vec<CellDto> {
    if cells.is_empty() {
        return cells;
    }

    let mut cols: HashMap<i64, Vec<&CellDto>> = HashMap::new();
    for c in &cells {
        cols.entry(c.col).or_default().push(c);
    }

    let mut col_has_text: HashMap<i64, bool> = HashMap::new();
    for (&ci, c_list) in &cols {
        let has_text = c_list.iter().any(|c| !c.text.trim().is_empty());
        col_has_text.insert(ci, has_text);
    }

    if col_has_text.values().all(|&v| v) {
        return cells;
    }

    let mut text_coverage: HashMap<i64, HashSet<i64>> = HashMap::new();
    for cell in &cells {
        if cell.text.trim().is_empty() {
            continue;
        }
        let r_end = cell.row + cell.rowspan.max(1);
        let c_end = cell.col + cell.colspan.max(1);
        for row_index in cell.row..r_end {
            for col_index in cell.col..c_end {
                text_coverage
                    .entry(col_index)
                    .or_default()
                    .insert(row_index);
            }
        }
    }

    let mut columns_to_remove: HashSet<i64> = HashSet::new();
    for (&ci, column_cells) in &cols {
        if col_has_text.get(&ci).copied().unwrap_or(false) {
            continue;
        }

        let widths: Vec<f64> = column_cells.iter().map(|c| c.rect.x1 - c.rect.x0).collect();
        let average_width = if !widths.is_empty() {
            widths.iter().sum::<f64>() / widths.len() as f64
        } else {
            0.0
        };

        let is_thin_border_fragment = average_width < line_tolerance;
        let covered_rows = text_coverage.get(&ci);
        let is_covered_by_text = !column_cells.is_empty()
            && column_cells.iter().all(|c| {
                covered_rows
                    .map(|set| set.contains(&c.row))
                    .unwrap_or(false)
            });

        if is_thin_border_fragment || is_covered_by_text {
            columns_to_remove.insert(ci);
        }
    }

    let mut sorted_cols: Vec<i64> = cols.keys().copied().collect();
    sorted_cols.sort_unstable();

    let mut new_ci = 0i64;
    let mut ci_map: HashMap<i64, i64> = HashMap::new();
    for ci in sorted_cols {
        if !columns_to_remove.contains(&ci) {
            ci_map.insert(ci, new_ci);
            new_ci += 1;
        } else {
            ci_map.insert(ci, -1);
        }
    }

    let mut pruned = Vec::new();
    for mut c in cells {
        let new_start = ci_map.get(&c.col).copied().unwrap_or(-1);
        if new_start == -1 {
            continue;
        }

        let original_span = c.col..(c.col + c.colspan.max(1));
        let kept_span = original_span
            .filter(|old_ci| ci_map.get(old_ci).copied().unwrap_or(-1) != -1)
            .count() as i64;

        c.col = new_start;
        c.colspan = kept_span.max(1);
        pruned.push(c);
    }

    let _ = check_occupancy_conflicts(&pruned);
    pruned
}

pub fn assign_text_to_line_cells(
    mut cells: Vec<CellDto>,
    words: &[WordDto],
    chars: &[CharacterDto],
    _tolerance: f64,
) -> Vec<CellDto> {
    if cells.is_empty() || words.is_empty() {
        return cells;
    }

    // Keep text-row assignment aligned with Python's
    // _assign_text_to_line_cells_python, which uses a fixed 2.0pt text
    // tolerance independently of the 2.3pt geometric line tolerance.
    let text_tolerance = 2.0_f64;

    let overlapping_cells = |w: &WordDto, cells_ref: &[CellDto]| -> Vec<usize> {
        let wyc = (w.rect.y0 + w.rect.y1) / 2.0;
        let mut res = Vec::new();
        for (idx, cell) in cells_ref.iter().enumerate() {
            if cell.rect.y0 - text_tolerance <= wyc
                && wyc <= cell.rect.y1 + text_tolerance
                && cell.rect.x1.min(w.rect.x1) > cell.rect.x0.max(w.rect.x0)
            {
                res.push(idx);
            }
        }
        res
    };

    let split_word = |w: &WordDto,
                      candidates: &[usize],
                      cells_ref: &[CellDto]|
     -> Option<Vec<(usize, String)>> {
        if candidates.len() < 2 || chars.is_empty() {
            return None;
        }
        let word_text = w.text.trim();
        let expected_text = word_text.replace(" ", "");

        let mut matching_chars: Vec<&CharacterDto> = chars
            .iter()
            .filter(|c| {
                let xc = (c.rect.x0 + c.rect.x1) / 2.0;
                let yc = (c.rect.y0 + c.rect.y1) / 2.0;
                w.rect.x0 - 0.5 <= xc
                    && xc <= w.rect.x1 + 0.5
                    && w.rect.y0 - 0.5 <= yc
                    && yc <= w.rect.y1 + 0.5
            })
            .collect();

        matching_chars.sort_by(|a, b| match a.rect.y0.partial_cmp(&b.rect.y0) {
            Some(std::cmp::Ordering::Equal) => a
                .rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal),
            Some(ord) => ord,
            None => std::cmp::Ordering::Equal,
        });

        let chars_concat: String = matching_chars
            .iter()
            .filter(|c| !c.text.trim().is_empty())
            .map(|c| c.text.as_str())
            .collect();
        if chars_concat != expected_text {
            return None;
        }

        let mut fragments: HashMap<usize, String> = HashMap::new();
        for c in matching_chars {
            let xc = (c.rect.x0 + c.rect.x1) / 2.0;
            let yc = (c.rect.y0 + c.rect.y1) / 2.0;
            let mut matched_idx = None;
            for &idx in candidates {
                let cell = &cells_ref[idx];
                if cell.rect.x0 - text_tolerance <= xc
                    && xc <= cell.rect.x1 + text_tolerance
                    && cell.rect.y0 - text_tolerance <= yc
                    && yc <= cell.rect.y1 + text_tolerance
                {
                    matched_idx = Some(idx);
                    break;
                }
            }
            if let Some(idx) = matched_idx {
                fragments.entry(idx).or_default().push_str(&c.text);
            } else {
                return None;
            }
        }

        let mut pieces: Vec<(usize, String)> = fragments
            .into_iter()
            .map(|(idx, s)| (idx, s.trim().to_string()))
            .filter(|(_, s)| !s.is_empty())
            .collect();
        if pieces.len() < 2 {
            return None;
        }

        pieces.sort_by(|a, b| {
            cells_ref[a.0]
                .rect
                .x0
                .partial_cmp(&cells_ref[b.0].rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let pieces_concat: String = pieces.iter().map(|(_, s)| s.as_str()).collect();
        if pieces_concat != expected_text {
            return None;
        }

        Some(pieces)
    };

    let mut cell_words: HashMap<usize, Vec<(f64, f64, String)>> = HashMap::new();

    for w in words {
        let wyc = (w.rect.y0 + w.rect.y1) / 2.0;
        let candidates = overlapping_cells(w, &cells);
        let pieces = split_word(w, &candidates, &cells);

        if let Some(pcs) = pieces {
            for (idx, text) in pcs {
                cell_words
                    .entry(idx)
                    .or_default()
                    .push((wyc, w.rect.x0, text));
            }
            continue;
        }

        let wxc = (w.rect.x0 + w.rect.x1) / 2.0;
        let mut matched_idx = None;
        for (idx, c) in cells.iter().enumerate() {
            if c.rect.x0 - text_tolerance <= wxc
                && wxc <= c.rect.x1 + text_tolerance
                && c.rect.y0 - text_tolerance <= wyc
                && wyc <= c.rect.y1 + text_tolerance
            {
                matched_idx = Some(idx);
                break;
            }
        }

        if let Some(idx) = matched_idx {
            cell_words
                .entry(idx)
                .or_default()
                .push((wyc, w.rect.x0, w.text.trim().to_string()));
        }
    }

    for (idx, mut tokens) in cell_words {
        tokens.sort_by(|a, b| {
            let key_a_row = (a.0 / 4.0).round_ties_even();
            let key_b_row = (b.0 / 4.0).round_ties_even();
            match key_a_row.partial_cmp(&key_b_row) {
                Some(std::cmp::Ordering::Equal) => {
                    a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal)
                }
                Some(ord) => ord,
                None => std::cmp::Ordering::Equal,
            }
        });
        let joined: String = tokens
            .iter()
            .map(|t| t.2.as_str())
            .filter(|s| !s.is_empty())
            .collect::<Vec<&str>>()
            .join(" ")
            .trim()
            .to_string();
        cells[idx].text = joined;
    }

    cells
}

pub fn extract_wired_region(input: WiredRegionInput) -> WiredRegionOutput {
    let tol = input.tolerance;
    let merge_group_tol = 0.3;

    let h_lines_input: Vec<Line4> = input
        .h_lines
        .iter()
        .map(|l| (l.rect.x0, l.rect.y0, l.rect.x1, l.rect.y1))
        .collect();
    let v_lines_input: Vec<Line4> = input
        .v_lines
        .iter()
        .map(|l| (l.rect.x0, l.rect.y0, l.rect.x1, l.rect.y1))
        .collect();

    if h_lines_input.len() < 2 || v_lines_input.is_empty() {
        return WiredRegionOutput {
            schema_version: 1,
            regions: Vec::new(),
            grids: Vec::new(),
            cells: Vec::new(),
            diagnostics: Vec::new(),
        };
    }

    let h_merged = crate::table_engine::geometry::merge_h_lines(h_lines_input, merge_group_tol);
    let v_merged = crate::table_engine::geometry::merge_v_lines(v_lines_input, &h_merged, merge_group_tol, tol);

    if h_merged.len() < 2 || v_merged.is_empty() {
        return WiredRegionOutput {
            schema_version: 1,
            regions: Vec::new(),
            grids: Vec::new(),
            cells: Vec::new(),
            diagnostics: Vec::new(),
        };
    }

    let raw_regions = find_table_regions(h_merged, v_merged, tol);

    let mut out_regions = Vec::new();
    let mut out_grids = Vec::new();
    let mut all_cells = Vec::new();

    for (order_idx, (reg_bbox, reg_h, reg_v)) in raw_regions.into_iter().enumerate() {
        let reg_h_clean = crate::table_engine::geometry::merge_region_line_coordinates(reg_h, true, tol);
        let reg_v_clean = crate::table_engine::geometry::merge_region_line_coordinates(reg_v, false, tol);

        let mut cells = build_cells_for_region(
            reg_bbox.clone(),
            reg_h_clean.clone(),
            reg_v_clean.clone(),
            tol,
            merge_group_tol,
        );
        if cells.is_empty() {
            continue;
        }

        cells = assign_text_to_line_cells(cells, &input.words, &[], tol);
        cells = merge_oversegmented_line_columns(cells, tol);
        cells = trim_ghost_edge_rows(cells, &reg_h_clean, tol);

        if cells.is_empty() {
            continue;
        }
        if cells.len() == 1 && cells[0].rowspan == 1 && cells[0].colspan == 1 {
            continue;
        }

        let non_empty_text_count = cells.iter().filter(|c| !c.text.trim().is_empty()).count();
        let max_col = cells.iter().map(|c| c.col).max().unwrap_or(0);
        if non_empty_text_count <= 1 && max_col == 0 {
            continue;
        }

        let row_count = cells.iter().map(|c| c.row).max().unwrap_or(-1) + 1;
        let col_count = cells.iter().map(|c| c.col).max().unwrap_or(-1) + 1;

        if row_count >= 1 && col_count >= 1 {
            let actual_y0 = cells
                .iter()
                .map(|c| c.rect.y0)
                .fold(f64::INFINITY, f64::min);
            let actual_y1 = cells
                .iter()
                .map(|c| c.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max);
            let table_height = actual_y1 - actual_y0;
            if non_empty_text_count == 0 && (table_height < 6.0 || row_count * col_count <= 1) {
                continue;
            }

            out_regions.push(RegionDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: reg_bbox.x0,
                    y0: actual_y0,
                    x1: reg_bbox.x1,
                    y1: actual_y1,
                },
                source_order: order_idx as i64,
                allowed: true,
            });

            out_grids.push(GridDto {
                schema_version: 1,
                rows: row_count,
                cols: col_count,
                row_edges: Vec::new(),
                col_edges: Vec::new(),
                occupancy: Vec::new(),
            });

            all_cells.extend(cells);
        }
    }

    WiredRegionOutput {
        schema_version: 1,
        regions: out_regions,
        grids: out_grids,
        cells: all_cells,
        diagnostics: Vec::new(),
    }
}
