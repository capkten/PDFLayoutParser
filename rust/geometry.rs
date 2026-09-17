pub type Line4 = (f64, f64, f64, f64);

pub fn round_one_decimal(value: f64) -> f64 {
    format!("{value:.1}").parse().unwrap_or(value)
}

pub fn lines_intersect(h_line: Line4, v_line: Line4, tolerance: f64) -> bool {
    let h_min_x = h_line.0.min(h_line.2);
    let h_max_x = h_line.0.max(h_line.2);
    let v_min_y = v_line.1.min(v_line.3);
    let v_max_y = v_line.1.max(v_line.3);
    let vx = v_line.0;
    let hy = h_line.1;
    (h_min_x - tolerance <= vx && vx <= h_max_x + tolerance)
        && (v_min_y - tolerance <= hy && hy <= v_max_y + tolerance)
}

pub fn merge_h_lines(mut lines: Vec<Line4>, merge_group_tol: f64) -> Vec<Line4> {
    lines.sort_by(|left, right| {
        match round_one_decimal(left.1).partial_cmp(&round_one_decimal(right.1)) {
            Some(std::cmp::Ordering::Equal) => left
                .0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal),
            Some(ordering) => ordering,
            None => std::cmp::Ordering::Equal,
        }
    });

    let mut groups: Vec<Vec<Line4>> = Vec::new();
    for line in lines {
        if let Some(group) = groups
            .iter_mut()
            .find(|group| (group[0].1 - line.1).abs() <= merge_group_tol)
        {
            group.push(line);
        } else {
            groups.push(vec![line]);
        }
    }

    let mut merged = Vec::new();
    for group in groups {
        let avg_y = group.iter().map(|line| line.1).sum::<f64>() / group.len() as f64;
        let mut segments: Vec<(f64, f64)> = group
            .iter()
            .map(|line| (line.0.min(line.2), line.0.max(line.2)))
            .collect();
        segments.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut segments = segments.into_iter();
        if let Some((mut cur_x0, mut cur_x1)) = segments.next() {
            for (seg_x0, seg_x1) in segments {
                if seg_x0 <= cur_x1 + 3.0 {
                    cur_x1 = cur_x1.max(seg_x1);
                } else {
                    merged.push((cur_x0, avg_y, cur_x1, avg_y));
                    cur_x0 = seg_x0;
                    cur_x1 = seg_x1;
                }
            }
            merged.push((cur_x0, avg_y, cur_x1, avg_y));
        }
    }

    merged
}

pub fn merge_v_lines(
    mut lines: Vec<Line4>,
    _h_lines: &[Line4],
    merge_group_tol: f64,
    line_tolerance: f64,
) -> Vec<Line4> {
    if lines.is_empty() {
        return Vec::new();
    }

    lines.sort_by(|left, right| {
        match round_one_decimal(left.0).partial_cmp(&round_one_decimal(right.0)) {
            Some(std::cmp::Ordering::Equal) => left
                .1
                .partial_cmp(&right.1)
                .unwrap_or(std::cmp::Ordering::Equal),
            Some(ordering) => ordering,
            None => std::cmp::Ordering::Equal,
        }
    });

    let mut groups: Vec<Vec<Line4>> = Vec::new();
    for line in lines {
        let x = line.0;
        let mut matched = false;
        for group in &mut groups {
            if (group[0].0 - x).abs() <= merge_group_tol {
                group.push(line);
                matched = true;
                break;
            }
        }
        if !matched {
            groups.push(vec![line]);
        }
    }

    let mut merged = Vec::new();
    for group in groups {
        let avg_x = group.iter().map(|l| l.0).sum::<f64>() / group.len() as f64;
        let mut segs: Vec<(f64, f64)> =
            group.iter().map(|l| (l.1.min(l.3), l.1.max(l.3))).collect();
        segs.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut seg_iter = segs.into_iter();
        if let Some((mut cur_y0, mut cur_y1)) = seg_iter.next() {
            for (s_y0, s_y1) in seg_iter {
                let gap = s_y0 - cur_y1;
                if gap <= line_tolerance {
                    cur_y1 = cur_y1.max(s_y1);
                } else {
                    merged.push((avg_x, cur_y0, avg_x, cur_y1));
                    cur_y0 = s_y0;
                    cur_y1 = s_y1;
                }
            }
            merged.push((avg_x, cur_y0, avg_x, cur_y1));
        }
    }

    merged
}

pub fn merge_region_line_coordinates(
    lines: Vec<Line4>,
    horizontal: bool,
    line_tolerance: f64,
) -> Vec<Line4> {
    if lines.is_empty() {
        return Vec::new();
    }

    let coordinate_tolerance = 1.0;

    let mut sorted_lines = lines;
    sorted_lines.sort_by(|a, b| {
        let a_coord = if horizontal { a.1 } else { a.0 };
        let b_coord = if horizontal { b.1 } else { b.0 };
        let a_start = if horizontal {
            a.0.min(a.2)
        } else {
            a.1.min(a.3)
        };
        let b_start = if horizontal {
            b.0.min(b.2)
        } else {
            b.1.min(b.3)
        };
        match a_coord.partial_cmp(&b_coord) {
            Some(std::cmp::Ordering::Equal) => a_start
                .partial_cmp(&b_start)
                .unwrap_or(std::cmp::Ordering::Equal),
            Some(ord) => ord,
            None => std::cmp::Ordering::Equal,
        }
    });

    let mut groups: Vec<Vec<Line4>> = Vec::new();
    for line in sorted_lines {
        let line_start = if horizontal {
            line.0.min(line.2)
        } else {
            line.1.min(line.3)
        };
        let line_end = if horizontal {
            line.0.max(line.2)
        } else {
            line.1.max(line.3)
        };
        let line_coord = if horizontal { line.1 } else { line.0 };

        if groups.is_empty() {
            groups.push(vec![line]);
            continue;
        }

        let last_group = groups.last_mut().unwrap();
        let group_coord = if horizontal {
            last_group[0].1
        } else {
            last_group[0].0
        };
        let group_start = last_group
            .iter()
            .map(|l| {
                if horizontal {
                    l.0.min(l.2)
                } else {
                    l.1.min(l.3)
                }
            })
            .fold(f64::INFINITY, f64::min);
        let group_end = last_group
            .iter()
            .map(|l| {
                if horizontal {
                    l.0.max(l.2)
                } else {
                    l.1.max(l.3)
                }
            })
            .fold(f64::NEG_INFINITY, f64::max);

        if (group_coord - line_coord).abs() <= coordinate_tolerance
            && line_start <= group_end + line_tolerance
            && line_end >= group_start - line_tolerance
        {
            last_group.push(line);
        } else {
            groups.push(vec![line]);
        }
    }

    let mut merged = Vec::new();
    for group in groups {
        let coordinate = group
            .iter()
            .map(|l| if horizontal { l.1 } else { l.0 })
            .sum::<f64>()
            / group.len() as f64;
        let start = group
            .iter()
            .map(|l| {
                if horizontal {
                    l.0.min(l.2)
                } else {
                    l.1.min(l.3)
                }
            })
            .fold(f64::INFINITY, f64::min);
        let end = group
            .iter()
            .map(|l| {
                if horizontal {
                    l.0.max(l.2)
                } else {
                    l.1.max(l.3)
                }
            })
            .fold(f64::NEG_INFINITY, f64::max);
        if horizontal {
            merged.push((start, coordinate, end, coordinate));
        } else {
            merged.push((coordinate, start, coordinate, end));
        }
    }

    merged
}

pub fn snap_coordinates(coords: Vec<f64>, anchor_coords: &[f64], tol: f64) -> Vec<f64> {
    let mut snapped = Vec::with_capacity(coords.len());
    for c in coords {
        let mut matched = Vec::new();
        for &a in anchor_coords {
            if (a - c).abs() <= tol {
                matched.push(a);
            }
        }
        if !matched.is_empty() {
            matched.sort_by(|&a, &b| {
                (a - c)
                    .abs()
                    .partial_cmp(&(b - c).abs())
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            snapped.push(round_one_decimal(matched[0]));
        } else {
            snapped.push(round_one_decimal(c));
        }
    }
    snapped.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    snapped.dedup();

    let mut merged: Vec<f64> = Vec::new();
    for val in snapped {
        if merged.is_empty() {
            merged.push(val);
        } else {
            let last_val = *merged.last().unwrap();
            if val - last_val <= tol {
                let curr_is_anchor = anchor_coords.iter().any(|&a| (a - val).abs() <= 0.05);
                let prev_is_anchor = anchor_coords.iter().any(|&a| (a - last_val).abs() <= 0.05);
                if curr_is_anchor && !prev_is_anchor {
                    *merged.last_mut().unwrap() = val;
                }
            } else {
                merged.push(val);
            }
        }
    }
    merged
}

pub fn calculate_coverage(intervals: &[(f64, f64)], start: f64, end: f64, tol: f64) -> f64 {
    let mut clipped: Vec<(f64, f64)> = intervals
        .iter()
        .filter_map(|&(left, right)| {
            let l = left.min(right);
            let r = left.max(right);
            let c_left = start.max(l);
            let c_right = end.min(r);
            if c_right > c_left {
                Some((c_left, c_right))
            } else {
                None
            }
        })
        .collect();
    clipped.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut total = 0.0;
    let mut current: Option<(f64, f64)> = None;
    for (left, right) in clipped {
        match current {
            None => current = Some((left, right)),
            Some((c_l, c_r)) => {
                if left <= c_r + tol {
                    current = Some((c_l, c_r.max(right)));
                } else {
                    total += c_r - c_l;
                    current = Some((left, right));
                }
            }
        }
    }
    if let Some((c_l, c_r)) = current {
        total += c_r - c_l;
    }
    total
}

pub fn snap_grid_coordinates(
    start: f64,
    end: f64,
    orthogonal_start: f64,
    orthogonal_end: f64,
    lines: &[Line4],
    horizontal: bool,
    tol: f64,
    merge_group_tol: f64,
) -> Vec<f64> {
    let mut coordinate_spans: Vec<(f64, f64, f64)> = lines
        .iter()
        .map(|l| {
            if horizontal {
                (l.1, l.0.min(l.2), l.0.max(l.2))
            } else {
                (l.0, l.1.min(l.3), l.1.max(l.3))
            }
        })
        .collect();
    coordinate_spans.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let mut clusters: Vec<Vec<(f64, f64, f64)>> = Vec::new();
    for item in coordinate_spans {
        if let Some(last_cluster) = clusters.last_mut() {
            if item.0 - last_cluster.last().unwrap().0 <= merge_group_tol {
                last_cluster.push(item);
                continue;
            }
        }
        clusters.push(vec![item]);
    }

    let orthogonal_span = orthogonal_end - orthogonal_start;
    let required_coverage = (orthogonal_span - tol).max(orthogonal_span * 0.9);

    let mut cluster_data = Vec::new();
    for cluster in clusters {
        let coord = cluster.iter().map(|c| c.0).sum::<f64>() / cluster.len() as f64;
        let intervals: Vec<(f64, f64)> = cluster.iter().map(|c| (c.1, c.2)).collect();
        let cov = calculate_coverage(&intervals, orthogonal_start, orthogonal_end, tol);
        cluster_data.push((coord, cov));
    }

    let mut start_coord = start;
    let mut end_coord = end;

    for (is_start, boundary) in [(true, start), (false, end)] {
        let mut supported: Vec<(f64, f64)> = cluster_data
            .iter()
            .filter(|&&(coord, cov)| (coord - boundary).abs() <= tol && cov >= required_coverage)
            .map(|&(coord, _)| ((coord - boundary).abs(), coord))
            .collect();
        if !supported.is_empty() {
            supported.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            let best_coord = supported[0].1;
            if is_start {
                start_coord = best_coord;
            } else {
                end_coord = best_coord;
            }
        }
    }

    let mut result_coords: Vec<f64> =
        vec![round_one_decimal(start_coord), round_one_decimal(end_coord)];
    for &(coord, _) in &cluster_data {
        result_coords.push(round_one_decimal(coord));
    }
    result_coords.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    result_coords.dedup();
    result_coords
}
