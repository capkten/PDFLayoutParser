use pyo3::prelude::*;
use pyo3::types::PyModule;

pub type Line4 = (f64, f64, f64, f64);

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
        let mut segments: Vec<(f64, f64)> = group.iter().map(|line| (line.0, line.2)).collect();
        segments.sort_by(|left, right| {
            left.0
                .partial_cmp(&right.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut segments = segments.into_iter();
        let (mut cur_x0, mut cur_x1) = segments.next().unwrap();
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

    merged
}

fn round_one_decimal(value: f64) -> f64 {
    format!("{value:.1}").parse().unwrap_or(value)
}

pub mod types;

#[pyfunction(name = "merge_h_lines")]
fn merge_h_lines_binding(py: Python<'_>, lines: Vec<Line4>, merge_group_tol: f64) -> Vec<Line4> {
    py.allow_threads(move || merge_h_lines(lines, merge_group_tol))
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
    module.add_function(wrap_pyfunction!(roundtrip_dto_binding, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::merge_h_lines;

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
