use crate::geometry::{calculate_coverage, lines_intersect, Line4};
use crate::types::Rect4;

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
