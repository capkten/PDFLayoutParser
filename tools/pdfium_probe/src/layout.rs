use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

use crate::clustering::WordTupleDto;
use crate::normalizer::NormalizedPageDto;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct TableRegionInput {
    pub bbox: [f64; 4],
    pub table_id: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct LayoutWordInfo {
    pub text: String,
    pub bbox: [f64; 4],
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct LayoutTextLine {
    pub text: String,
    pub bbox: [f64; 4],
    pub words: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub word_details: Vec<LayoutWordInfo>,
}

/// Join words within a line respecting spacing thresholds.
pub fn join_layout_words(words: &[LayoutWordInfo]) -> String {
    if words.is_empty() {
        return String::new();
    }

    let mut out = words[0].text.clone();
    for pair in words.windows(2) {
        let prev = &pair[0];
        let curr = &pair[1];
        if prev.text.ends_with(' ') || curr.text.starts_with(' ') {
            out.push_str(&curr.text);
        } else {
            let gap = curr.bbox[0] - prev.bbox[2];
            if gap > 1.0 {
                out.push(' ');
            }
            out.push_str(&curr.text);
        }
    }
    out
}

/// Create a `LayoutTextLine` from accumulated word details.
pub fn create_layout_line(word_details: Vec<LayoutWordInfo>) -> LayoutTextLine {
    if word_details.is_empty() {
        return LayoutTextLine {
            text: String::new(),
            bbox: [0.0, 0.0, 0.0, 0.0],
            words: Vec::new(),
            word_details: Vec::new(),
        };
    }

    let min_x0 = word_details
        .iter()
        .map(|w| w.bbox[0])
        .fold(f64::INFINITY, f64::min);
    let min_y0 = word_details
        .iter()
        .map(|w| w.bbox[1])
        .fold(f64::INFINITY, f64::min);
    let max_x1 = word_details
        .iter()
        .map(|w| w.bbox[2])
        .fold(f64::NEG_INFINITY, f64::max);
    let max_y1 = word_details
        .iter()
        .map(|w| w.bbox[3])
        .fold(f64::NEG_INFINITY, f64::max);
    let text = join_layout_words(&word_details);
    let words = word_details.iter().map(|w| w.text.clone()).collect();
    LayoutTextLine {
        text,
        bbox: [min_x0, min_y0, max_x1, max_y1],
        words,
        word_details,
    }
}

/// Merge line blocks that visually belong to the same line.
pub fn merge_same_visual_lines(mut lines: Vec<LayoutTextLine>) -> Vec<LayoutTextLine> {
    if lines.len() <= 1 {
        return lines;
    }

    lines.sort_by(|a, b| {
        a.bbox[1]
            .partial_cmp(&b.bbox[1])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                a.bbox[0]
                    .partial_cmp(&b.bbox[0])
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut merged: Vec<LayoutTextLine> = Vec::with_capacity(lines.len());
    for curr in lines {
        if merged.is_empty() {
            merged.push(curr);
            continue;
        }

        let prev = merged.last().unwrap();
        let gap_x = curr.bbox[0] - prev.bbox[2];
        let overlap_y = prev.bbox[3].min(curr.bbox[3]) - prev.bbox[1].max(curr.bbox[1]);
        let min_h = (prev.bbox[3] - prev.bbox[1]).min(curr.bbox[3] - curr.bbox[1]);

        if min_h > 0.0 && (overlap_y / min_h) >= 0.5 && (-2.0..=40.0).contains(&gap_x) {
            let mut prev = merged.pop().unwrap();
            prev.word_details.extend(curr.word_details);
            prev.words.extend(curr.words);
            prev.bbox[0] = prev.bbox[0].min(curr.bbox[0]);
            prev.bbox[1] = prev.bbox[1].min(curr.bbox[1]);
            prev.bbox[2] = prev.bbox[2].max(curr.bbox[2]);
            prev.bbox[3] = prev.bbox[3].max(curr.bbox[3]);
            if prev.word_details.is_empty() {
                if prev.text.is_empty() {
                    prev.text = curr.text;
                } else if curr.text.is_empty() {
                    // keep prev.text
                } else if prev.text.ends_with(' ') || curr.text.starts_with(' ') {
                    prev.text.push_str(&curr.text);
                } else if gap_x > 1.0 {
                    prev.text.push(' ');
                    prev.text.push_str(&curr.text);
                } else {
                    prev.text.push_str(&curr.text);
                }
            } else {
                prev.text = join_layout_words(&prev.word_details);
            }
            merged.push(prev);
        } else {
            merged.push(curr);
        }
    }
    merged
}

/// Deduct table regions from normalized page words and merge external lines.
pub fn deduct_tables_from_normalized_page(
    norm: &NormalizedPageDto,
    tables: &[TableRegionInput],
) -> Vec<LayoutTextLine> {
    if norm.words.is_empty() {
        return Vec::new();
    }

    // 1. Group words by (block_idx, line_idx)
    let mut lines_map: BTreeMap<(usize, usize), Vec<&WordTupleDto>> = BTreeMap::new();
    for w in &norm.words {
        lines_map
            .entry((w.block_idx(), w.line_idx()))
            .or_default()
            .push(w);
    }

    // 2. Line breaking upon table collision
    let mut line_candidates = Vec::new();
    for (_line_key, mut line_words) in lines_map {
        line_words.sort_by(|a, b| {
            a.word_idx().cmp(&b.word_idx()).then_with(|| {
                a.x0()
                    .partial_cmp(&b.x0())
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
        });

        let mut outside_words: Vec<LayoutWordInfo> = Vec::new();
        for w in line_words {
            let cx = (w.x0() + w.x1()) / 2.0;
            let cy = (w.y0() + w.y1()) / 2.0;
            let in_table = tables
                .iter()
                .any(|t| t.bbox[0] <= cx && cx <= t.bbox[2] && t.bbox[1] <= cy && cy <= t.bbox[3]);

            if in_table {
                if !outside_words.is_empty() {
                    line_candidates.push(create_layout_line(std::mem::take(&mut outside_words)));
                }
            } else {
                outside_words.push(LayoutWordInfo {
                    text: w.text().to_string(),
                    bbox: [w.x0(), w.y0(), w.x1(), w.y1()],
                });
            }
        }

        if !outside_words.is_empty() {
            line_candidates.push(create_layout_line(outside_words));
        }
    }

    // 3. Visual line merging
    merge_same_visual_lines(line_candidates)
}

pub trait HasBBox {
    fn bbox(&self) -> [f64; 4];
}

impl HasBBox for [f64; 4] {
    fn bbox(&self) -> [f64; 4] {
        *self
    }
}

impl HasBBox for LayoutTextLine {
    fn bbox(&self) -> [f64; 4] {
        self.bbox
    }
}

impl<T> HasBBox for (T, [f64; 4]) {
    fn bbox(&self) -> [f64; 4] {
        self.1
    }
}

/// Find split positions between disjoint projection intervals with at least `min_gap` separation.
pub fn find_projection_cuts(intervals: &[[f64; 2]], min_gap: f64) -> Vec<f64> {
    if intervals.is_empty() {
        return Vec::new();
    }

    let mut sorted = intervals.to_vec();
    sorted.sort_by(|a, b| {
        a[0].partial_cmp(&b[0])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a[1].partial_cmp(&b[1]).unwrap_or(std::cmp::Ordering::Equal))
    });

    let mut merged: Vec<[f64; 2]> = Vec::with_capacity(sorted.len());
    for iv in sorted {
        let start = iv[0].min(iv[1]);
        let end = iv[0].max(iv[1]);
        if let Some(prev) = merged.last_mut() {
            if start <= prev[1] {
                prev[1] = prev[1].max(end);
            } else {
                merged.push([start, end]);
            }
        } else {
            merged.push([start, end]);
        }
    }

    let mut cuts = Vec::new();
    for window in merged.windows(2) {
        let prev_end = window[0][1];
        let next_start = window[1][0];
        let gap = next_start - prev_end;
        if gap >= min_gap {
            cuts.push((prev_end + next_start) / 2.0);
        }
    }

    cuts
}

/// Check if any element spans across a significant portion (>= 65%) of the total layout width.
pub fn has_spanning_element(bboxes: &[[f64; 4]]) -> bool {
    if bboxes.is_empty() {
        return false;
    }
    let min_x = bboxes.iter().map(|b| b[0]).fold(f64::INFINITY, f64::min);
    let max_x = bboxes
        .iter()
        .map(|b| b[2])
        .fold(f64::NEG_INFINITY, f64::max);
    let total_w = max_x - min_x;
    if total_w <= 0.0 {
        return false;
    }

    for b in bboxes {
        let w = b[2] - b[0];
        if w >= 0.65 * total_w {
            return true;
        }
    }
    false
}

/// Check if vertical partition forms legitimate multi-column layout rather than inline labels/numbers.
pub fn is_valid_column_partition(cols: &[Vec<usize>], bboxes: &[[f64; 4]], total_w: f64) -> bool {
    if cols.len() < 2 || total_w <= 0.0 {
        return false;
    }

    for col in cols {
        if col.is_empty() {
            return false;
        }
        let mut min_x0 = f64::INFINITY;
        let mut max_x1 = f64::NEG_INFINITY;
        for &idx in col {
            if idx >= bboxes.len() {
                return false;
            }
            let b = &bboxes[idx];
            min_x0 = min_x0.min(b[0]);
            max_x1 = max_x1.max(b[2]);
        }
        let col_w = max_x1 - min_x0;
        if col_w < 30.0 && (col_w / total_w) < 0.15 {
            return false;
        }
    }

    true
}

/// Sort elements in a single column or leaf cluster by row bands, then left-to-right.
pub fn sort_items_by_row_reading_order<T: HasBBox + Clone>(items: &[T]) -> Vec<T> {
    if items.len() <= 1 {
        return items.to_vec();
    }

    // First sort primarily by y0, secondarily by x0
    let mut sorted_candidates = items.to_vec();
    sorted_candidates.sort_by(|a, b| {
        let ba = a.bbox();
        let bb = b.bbox();
        ba[1]
            .partial_cmp(&bb[1])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                ba[0]
                    .partial_cmp(&bb[0])
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    let mut rows: Vec<Vec<T>> = Vec::new();
    let mut current_row: Vec<T> = vec![sorted_candidates[0].clone()];
    let first_bbox = sorted_candidates[0].bbox();
    let mut row_y0 = first_bbox[1];
    let mut row_y1 = first_bbox[3];

    for item in &sorted_candidates[1..] {
        let b = item.bbox();
        let overlap = row_y1.min(b[3]) - row_y0.max(b[1]);
        let h_row = (row_y1 - row_y0).max(1.0);
        let h_item = (b[3] - b[1]).max(1.0);
        let min_h = h_row.min(h_item);
        let max_h = h_row.max(h_item);

        let height_ratio = max_h / min_h;
        let center_y_item = (b[1] + b[3]) / 2.0;
        let center_y_row = (row_y0 + row_y1) / 2.0;

        let is_intersect = height_ratio <= 3.0
            && ((overlap > 0.0 && overlap >= 0.45 * min_h)
                || ((center_y_item - center_y_row).abs() <= 0.35 * min_h));

        if is_intersect {
            current_row.push(item.clone());
            row_y0 = row_y0.min(b[1]);
            row_y1 = row_y1.max(b[3]);
        } else {
            current_row.sort_by(|a, b| {
                a.bbox()[0]
                    .partial_cmp(&b.bbox()[0])
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            rows.push(current_row);
            current_row = vec![item.clone()];
            row_y0 = b[1];
            row_y1 = b[3];
        }
    }

    current_row.sort_by(|a, b| {
        a.bbox()[0]
            .partial_cmp(&b.bbox()[0])
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    rows.push(current_row);

    rows.sort_by(|r1, r2| {
        let min_y1 = r1
            .iter()
            .map(|it| it.bbox()[1])
            .fold(f64::INFINITY, f64::min);
        let min_y2 = r2
            .iter()
            .map(|it| it.bbox()[1])
            .fold(f64::INFINITY, f64::min);
        min_y1
            .partial_cmp(&min_y2)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut out_res = Vec::with_capacity(items.len());
    for r in rows {
        out_res.extend(r);
    }
    out_res
}

/// Sort elements in natural reading order using Recursive XY-Cut.
pub fn recursive_xy_cut<T: HasBBox + Clone>(items: &[T], min_y_gap: f64, min_x_gap: f64) -> Vec<T> {
    if items.len() <= 1 {
        return items.to_vec();
    }

    let bboxes: Vec<[f64; 4]> = items.iter().map(|item| item.bbox()).collect();
    let min_x = bboxes.iter().map(|b| b[0]).fold(f64::INFINITY, f64::min);
    let max_x = bboxes
        .iter()
        .map(|b| b[2])
        .fold(f64::NEG_INFINITY, f64::max);
    let total_w = max_x - min_x;

    let has_spanning = has_spanning_element(&bboxes);

    let x_intervals: Vec<[f64; 2]> = bboxes.iter().map(|b| [b[0], b[2]]).collect();
    let x_cuts = find_projection_cuts(&x_intervals, min_x_gap);

    let partition_columns = |cuts: &[f64]| -> Vec<Vec<usize>> {
        let mut cols: Vec<Vec<usize>> = vec![Vec::new(); cuts.len() + 1];
        for (i, b) in bboxes.iter().enumerate() {
            let mid_x = (b[0] + b[2]) / 2.0;
            let mut assigned = false;
            for (idx, &cut) in cuts.iter().enumerate() {
                if mid_x < cut {
                    cols[idx].push(i);
                    assigned = true;
                    break;
                }
            }
            if !assigned {
                cols.last_mut().unwrap().push(i);
            }
        }
        cols
    };

    // 1. Check if valid multi-column X-cut exists and no spanning elements present
    if !has_spanning && !x_cuts.is_empty() {
        let cols = partition_columns(&x_cuts);
        if is_valid_column_partition(&cols, &bboxes, total_w) {
            let mut result = Vec::with_capacity(items.len());
            for col in cols {
                if !col.is_empty() {
                    let col_items: Vec<T> = col.into_iter().map(|i| items[i].clone()).collect();
                    result.extend(recursive_xy_cut(&col_items, min_y_gap, min_x_gap));
                }
            }
            return result;
        }
    }

    // 2. Try horizontal cut (Y-axis projection / line bands)
    let y_intervals: Vec<[f64; 2]> = bboxes.iter().map(|b| [b[1], b[3]]).collect();
    let y_cuts = find_projection_cuts(&y_intervals, min_y_gap);

    if !y_cuts.is_empty() {
        let mut bands: Vec<Vec<usize>> = vec![Vec::new(); y_cuts.len() + 1];
        for (i, b) in bboxes.iter().enumerate() {
            let mid_y = (b[1] + b[3]) / 2.0;
            let mut assigned = false;
            for (idx, &cut) in y_cuts.iter().enumerate() {
                if mid_y < cut {
                    bands[idx].push(i);
                    assigned = true;
                    break;
                }
            }
            if !assigned {
                bands.last_mut().unwrap().push(i);
            }
        }

        let mut result = Vec::with_capacity(items.len());
        for band in bands {
            if !band.is_empty() {
                let band_items: Vec<T> = band.into_iter().map(|i| items[i].clone()).collect();
                result.extend(recursive_xy_cut(&band_items, min_y_gap, min_x_gap));
            }
        }
        return result;
    }

    // 3. If no horizontal cut possible, try X-Cut ONLY if valid column partition
    if !x_cuts.is_empty() {
        let cols = partition_columns(&x_cuts);
        if is_valid_column_partition(&cols, &bboxes, total_w) {
            let mut result = Vec::with_capacity(items.len());
            for col in cols {
                if !col.is_empty() {
                    let col_items: Vec<T> = col.into_iter().map(|i| items[i].clone()).collect();
                    result.extend(recursive_xy_cut(&col_items, min_y_gap, min_x_gap));
                }
            }
            return result;
        }
    }

    // 4. Fallback: cluster items by row and sort each row left-to-right
    sort_items_by_row_reading_order(items)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[allow(clippy::too_many_arguments)]
    fn make_word(
        x0: f64,
        y0: f64,
        x1: f64,
        y1: f64,
        text: &str,
        block: usize,
        line: usize,
        word: usize,
    ) -> WordTupleDto {
        WordTupleDto::new(x0, y0, x1, y1, text.to_string(), block, line, word)
    }

    fn dummy_norm_page(words: Vec<WordTupleDto>) -> NormalizedPageDto {
        NormalizedPageDto {
            page_type: "vector".to_string(),
            page_snapshot: None,
            rawdict: None,
            words,
            sidecar: serde_json::Value::Null,
            diagnostics: serde_json::Value::Null,
        }
    }

    #[test]
    fn test_table_deduction_filter_inside_table() {
        let words = vec![
            make_word(10.0, 10.0, 30.0, 20.0, "OutsideBefore", 0, 0, 0),
            make_word(50.0, 10.0, 80.0, 20.0, "InsideTable", 0, 0, 1),
            make_word(120.0, 10.0, 150.0, 20.0, "OutsideAfter", 0, 0, 2),
        ];
        let norm = dummy_norm_page(words);
        let tables = vec![TableRegionInput {
            bbox: [40.0, 5.0, 100.0, 25.0],
            table_id: 0,
        }];

        let lines = deduct_tables_from_normalized_page(&norm, &tables);
        assert_eq!(lines.len(), 2);
        assert_eq!(lines[0].text, "OutsideBefore");
        assert_eq!(lines[0].bbox, [10.0, 10.0, 30.0, 20.0]);
        assert_eq!(lines[0].words, vec!["OutsideBefore".to_string()]);

        assert_eq!(lines[1].text, "OutsideAfter");
        assert_eq!(lines[1].bbox, [120.0, 10.0, 150.0, 20.0]);
        assert_eq!(lines[1].words, vec!["OutsideAfter".to_string()]);
    }

    #[test]
    fn test_table_deduction_split_line_on_table_collision() {
        let words = vec![
            make_word(0.0, 10.0, 20.0, 20.0, "Hello", 0, 0, 0),
            make_word(25.0, 10.0, 45.0, 20.0, "World", 0, 0, 1),
            make_word(60.0, 10.0, 80.0, 20.0, "Secret", 0, 0, 2),
            make_word(110.0, 10.0, 130.0, 20.0, "After", 0, 0, 3),
        ];
        let norm = dummy_norm_page(words);
        let tables = vec![TableRegionInput {
            bbox: [50.0, 0.0, 100.0, 30.0],
            table_id: 1,
        }];

        let lines = deduct_tables_from_normalized_page(&norm, &tables);
        assert_eq!(lines.len(), 2);
        assert_eq!(lines[0].text, "Hello World");
        assert_eq!(lines[0].words, vec!["Hello", "World"]);
        assert_eq!(lines[0].bbox, [0.0, 10.0, 45.0, 20.0]);

        assert_eq!(lines[1].text, "After");
        assert_eq!(lines[1].words, vec!["After"]);
        assert_eq!(lines[1].bbox, [110.0, 10.0, 130.0, 20.0]);
    }

    #[test]
    fn test_table_deduction_word_spacing() {
        let words = vec![
            make_word(0.0, 10.0, 20.0, 20.0, "First", 0, 0, 0),
            make_word(20.5, 10.0, 35.0, 20.0, "Second", 0, 0, 1),
            make_word(40.0, 10.0, 60.0, 20.0, "Third", 0, 0, 2),
            make_word(61.0, 10.0, 80.0, 20.0, " Fourth", 0, 0, 3),
        ];
        let norm = dummy_norm_page(words);
        let tables = vec![];

        let lines = deduct_tables_from_normalized_page(&norm, &tables);
        assert_eq!(lines.len(), 1);
        // "First" + "Second" (gap 0.5 <= 1.0) -> "FirstSecond"
        // + " Third" (gap 5.0 > 1.0) -> "FirstSecond Third"
        // + " Fourth" (starts with space) -> "FirstSecond Third Fourth"
        assert_eq!(lines[0].text, "FirstSecond Third Fourth");
    }

    #[test]
    fn test_table_deduction_merge_visual_lines() {
        let line1 = LayoutTextLine {
            text: "Part 1".to_string(),
            bbox: [10.0, 100.0, 50.0, 115.0],
            words: vec!["Part".to_string(), "1".to_string()],
            word_details: vec![
                LayoutWordInfo {
                    text: "Part".to_string(),
                    bbox: [10.0, 100.0, 35.0, 115.0],
                },
                LayoutWordInfo {
                    text: "1".to_string(),
                    bbox: [40.0, 100.0, 50.0, 115.0],
                },
            ],
        };
        let line2 = LayoutTextLine {
            text: "Part 2".to_string(),
            bbox: [60.0, 102.0, 100.0, 117.0],
            words: vec!["Part".to_string(), "2".to_string()],
            word_details: vec![
                LayoutWordInfo {
                    text: "Part".to_string(),
                    bbox: [60.0, 102.0, 85.0, 117.0],
                },
                LayoutWordInfo {
                    text: "2".to_string(),
                    bbox: [90.0, 102.0, 100.0, 117.0],
                },
            ],
        };

        let merged = merge_same_visual_lines(vec![line1, line2]);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].text, "Part 1 Part 2");
        assert_eq!(merged[0].bbox, [10.0, 100.0, 100.0, 117.0]);
        assert_eq!(merged[0].words, vec!["Part", "1", "Part", "2"]);
    }

    #[test]
    fn test_table_deduction_no_merge_exceeding_thresholds() {
        // Case A: gap_x > 40.0
        let line_a1 = LayoutTextLine {
            text: "Left".to_string(),
            bbox: [10.0, 100.0, 50.0, 115.0],
            words: vec!["Left".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "Left".to_string(),
                bbox: [10.0, 100.0, 50.0, 115.0],
            }],
        };
        let line_a2 = LayoutTextLine {
            text: "Right".to_string(),
            bbox: [95.0, 100.0, 140.0, 115.0], // gap_x = 45.0 > 40.0
            words: vec!["Right".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "Right".to_string(),
                bbox: [95.0, 100.0, 140.0, 115.0],
            }],
        };
        let res_a = merge_same_visual_lines(vec![line_a1, line_a2]);
        assert_eq!(res_a.len(), 2);

        // Case B: gap_x < -2.0
        let line_b1 = LayoutTextLine {
            text: "First".to_string(),
            bbox: [10.0, 100.0, 50.0, 115.0],
            words: vec!["First".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "First".to_string(),
                bbox: [10.0, 100.0, 50.0, 115.0],
            }],
        };
        let line_b2 = LayoutTextLine {
            text: "Overlap".to_string(),
            bbox: [45.0, 100.0, 80.0, 115.0], // gap_x = 45 - 50 = -5.0 < -2.0
            words: vec!["Overlap".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "Overlap".to_string(),
                bbox: [45.0, 100.0, 80.0, 115.0],
            }],
        };
        let res_b = merge_same_visual_lines(vec![line_b1, line_b2]);
        assert_eq!(res_b.len(), 2);

        // Case C: vertical overlap < 0.5
        let line_c1 = LayoutTextLine {
            text: "Upper".to_string(),
            bbox: [10.0, 100.0, 50.0, 110.0], // h = 10
            words: vec!["Upper".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "Upper".to_string(),
                bbox: [10.0, 100.0, 50.0, 110.0],
            }],
        };
        let line_c2 = LayoutTextLine {
            text: "Lower".to_string(),
            bbox: [60.0, 107.0, 100.0, 117.0], // h = 10, overlap = 110 - 107 = 3.0, ratio = 0.3 < 0.5
            words: vec!["Lower".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "Lower".to_string(),
                bbox: [60.0, 107.0, 100.0, 117.0],
            }],
        };
        let res_c = merge_same_visual_lines(vec![line_c1, line_c2]);
        assert_eq!(res_c.len(), 2);
    }

    #[test]
    fn test_table_deduction_empty_page() {
        let norm = dummy_norm_page(vec![]);
        let tables = vec![TableRegionInput {
            bbox: [0.0, 0.0, 100.0, 100.0],
            table_id: 0,
        }];
        let lines = deduct_tables_from_normalized_page(&norm, &tables);
        assert!(lines.is_empty());
    }

    #[test]
    fn test_table_deduction_all_words_in_table() {
        let words = vec![
            make_word(10.0, 10.0, 30.0, 20.0, "Inside1", 0, 0, 0),
            make_word(35.0, 10.0, 60.0, 20.0, "Inside2", 0, 0, 1),
        ];
        let norm = dummy_norm_page(words);
        let tables = vec![TableRegionInput {
            bbox: [5.0, 5.0, 100.0, 25.0],
            table_id: 0,
        }];
        let lines = deduct_tables_from_normalized_page(&norm, &tables);
        assert!(lines.is_empty());
    }

    #[test]
    fn test_table_deduction_three_way_visual_merge() {
        let line1 = LayoutTextLine {
            text: "A".to_string(),
            bbox: [10.0, 50.0, 30.0, 65.0],
            words: vec!["A".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "A".to_string(),
                bbox: [10.0, 50.0, 30.0, 65.0],
            }],
        };
        let line2 = LayoutTextLine {
            text: "B".to_string(),
            bbox: [40.0, 50.0, 60.0, 65.0],
            words: vec!["B".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "B".to_string(),
                bbox: [40.0, 50.0, 60.0, 65.0],
            }],
        };
        let line3 = LayoutTextLine {
            text: "C".to_string(),
            bbox: [70.0, 50.0, 90.0, 65.0],
            words: vec!["C".to_string()],
            word_details: vec![LayoutWordInfo {
                text: "C".to_string(),
                bbox: [70.0, 50.0, 90.0, 65.0],
            }],
        };

        let merged = merge_same_visual_lines(vec![line1, line2, line3]);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].text, "A B C");
        assert_eq!(merged[0].bbox, [10.0, 50.0, 90.0, 65.0]);
        assert_eq!(merged[0].words, vec!["A", "B", "C"]);
    }

    #[test]
    fn test_projection_cuts() {
        // Clean non-overlapping intervals
        let ivs = vec![[0.0, 10.0], [20.0, 30.0]];
        let cuts = find_projection_cuts(&ivs, 5.0);
        assert_eq!(cuts, vec![15.0]);

        // Overlapping intervals merged
        let ivs = vec![[0.0, 10.0], [5.0, 15.0], [25.0, 35.0]];
        let cuts = find_projection_cuts(&ivs, 5.0);
        assert_eq!(cuts, vec![20.0]);

        // Gap below min_gap ignored, gap above min_gap kept
        let ivs = vec![[0.0, 10.0], [12.0, 20.0], [30.0, 40.0]];
        let cuts = find_projection_cuts(&ivs, 5.0);
        assert_eq!(cuts, vec![25.0]);

        // Empty intervals
        let empty: Vec<[f64; 2]> = vec![];
        assert!(find_projection_cuts(&empty, 5.0).is_empty());
    }

    #[test]
    fn test_spanning_element_detection() {
        // Total layout width: 0.0 to 100.0 (total_w = 100.0)
        // Two normal blocks of width 40: ratio 40/100 = 0.40 < 0.65 -> false
        let normal_blocks = vec![[0.0, 10.0, 40.0, 20.0], [60.0, 10.0, 100.0, 20.0]];
        assert!(!has_spanning_element(&normal_blocks));

        // Spanning header of width 70: ratio 70/100 = 0.70 >= 0.65 -> true
        let with_spanning = vec![
            [0.0, 0.0, 70.0, 10.0],
            [0.0, 20.0, 40.0, 30.0],
            [60.0, 20.0, 100.0, 30.0],
        ];
        assert!(has_spanning_element(&with_spanning));

        // Empty bboxes
        assert!(!has_spanning_element(&[]));

        // Zero width total
        assert!(!has_spanning_element(&[[10.0, 10.0, 10.0, 20.0]]));
    }

    #[test]
    fn test_valid_column_partition() {
        let total_w = 200.0;
        let bboxes = vec![
            [10.0, 0.0, 90.0, 20.0],   // col 0: w = 80.0
            [110.0, 0.0, 190.0, 20.0], // col 1: w = 80.0
        ];
        let cols = vec![vec![0], vec![1]];
        assert!(is_valid_column_partition(&cols, &bboxes, total_w));

        // Narrow inline column: width < 30.0 AND width / total_w < 0.15
        let total_w_wide = 500.0;
        let bboxes_narrow = vec![
            [10.0, 0.0, 20.0, 20.0],  // col 0: w = 10.0 (< 30.0 and 10/500 = 0.02 < 0.15)
            [50.0, 0.0, 400.0, 20.0], // col 1: w = 350.0
        ];
        let cols_narrow = vec![vec![0], vec![1]];
        assert!(!is_valid_column_partition(
            &cols_narrow,
            &bboxes_narrow,
            total_w_wide
        ));

        // Fewer than 2 columns
        assert!(!is_valid_column_partition(&[vec![0]], &bboxes, total_w));

        // An empty column
        assert!(!is_valid_column_partition(
            &[vec![0], vec![]],
            &bboxes,
            total_w
        ));
    }

    #[test]
    fn test_row_reading_order_jitter() {
        let item_a = ("A", [10.0, 100.0, 50.0, 110.0]);
        let item_b = ("B", [60.0, 102.0, 100.0, 112.0]);
        let item_c = ("C", [110.0, 99.0, 150.0, 109.0]);
        let item_d = ("D", [10.0, 130.0, 50.0, 140.0]);

        let items = vec![item_b, item_d, item_c, item_a];
        let sorted = sort_items_by_row_reading_order(&items);
        let labels: Vec<&str> = sorted.into_iter().map(|(label, _)| label).collect();
        assert_eq!(labels, vec!["A", "B", "C", "D"]);
    }

    #[test]
    fn test_xy_cut_single_column() {
        let p1 = ("p1", [10.0, 10.0, 100.0, 30.0]);
        let p2 = ("p2", [10.0, 50.0, 100.0, 70.0]);
        let p3 = ("p3", [10.0, 90.0, 100.0, 110.0]);

        let items = vec![p2, p3, p1];
        let ordered = recursive_xy_cut(&items, 1.0, 5.0);
        let labels: Vec<&str> = ordered.into_iter().map(|(label, _)| label).collect();
        assert_eq!(labels, vec!["p1", "p2", "p3"]);
    }

    #[test]
    fn test_xy_cut_two_column() {
        let col1_line1 = ("col1_l1", [10.0, 50.0, 90.0, 60.0]);
        let col1_line2 = ("col1_l2", [10.0, 70.0, 90.0, 80.0]);
        let col2_line1 = ("col2_l1", [120.0, 50.0, 200.0, 60.0]);
        let col2_line2 = ("col2_l2", [120.0, 70.0, 200.0, 80.0]);

        let items = vec![col2_line1, col1_line2, col1_line1, col2_line2];
        let ordered = recursive_xy_cut(&items, 1.0, 5.0);
        let labels: Vec<&str> = ordered.into_iter().map(|(label, _)| label).collect();
        assert_eq!(labels, vec!["col1_l1", "col1_l2", "col2_l1", "col2_l2"]);
    }

    #[test]
    fn test_xy_cut_spanning_header() {
        let header = ("header", [10.0, 10.0, 200.0, 30.0]);
        // Left column
        let col1_l1 = ("col1_l1", [10.0, 50.0, 90.0, 80.0]);
        let col1_l2 = ("col1_l2", [10.0, 90.0, 90.0, 120.0]);
        // Right column
        let col2_l1 = ("col2_l1", [120.0, 50.0, 200.0, 90.0]);
        let col2_l2 = ("col2_l2", [120.0, 100.0, 200.0, 120.0]);

        let items = vec![col2_l2, header, col1_l2, col2_l1, col1_l1];
        let ordered = recursive_xy_cut(&items, 1.0, 5.0);
        let labels: Vec<&str> = ordered.into_iter().map(|(label, _)| label).collect();
        assert_eq!(
            labels,
            vec!["header", "col1_l1", "col1_l2", "col2_l1", "col2_l2"]
        );
    }

    #[test]
    fn test_xy_cut_header_twocolumn_footer() {
        let header = ("header", [50.0, 10.0, 400.0, 30.0]);
        let l1 = ("l1", [50.0, 50.0, 200.0, 80.0]);
        let l2 = ("l2", [50.0, 90.0, 200.0, 120.0]);
        let r1 = ("r1", [250.0, 50.0, 400.0, 90.0]);
        let r2 = ("r2", [250.0, 100.0, 400.0, 120.0]);
        let footer = ("footer", [50.0, 150.0, 400.0, 170.0]);

        let items = vec![r2, footer, l1, header, r1, l2];
        let ordered = recursive_xy_cut(&items, 1.0, 5.0);
        let labels: Vec<&str> = ordered.into_iter().map(|(label, _)| label).collect();
        assert_eq!(labels, vec!["header", "l1", "l2", "r1", "r2", "footer"]);
    }

    #[test]
    fn test_xy_cut_with_layout_text_lines() {
        let line1 = LayoutTextLine {
            text: "Header".to_string(),
            bbox: [0.0, 0.0, 200.0, 20.0],
            words: vec!["Header".to_string()],
            word_details: vec![],
        };
        let line2 = LayoutTextLine {
            text: "Left Column".to_string(),
            bbox: [0.0, 30.0, 90.0, 50.0],
            words: vec!["Left".to_string(), "Column".to_string()],
            word_details: vec![],
        };
        let line3 = LayoutTextLine {
            text: "Right Column".to_string(),
            bbox: [110.0, 30.0, 200.0, 50.0],
            words: vec!["Right".to_string(), "Column".to_string()],
            word_details: vec![],
        };

        let items = vec![line3, line2, line1];
        let ordered = recursive_xy_cut(&items, 1.0, 5.0);
        assert_eq!(ordered.len(), 3);
        assert_eq!(ordered[0].text, "Header");
        assert_eq!(ordered[1].text, "Left Column");
        assert_eq!(ordered[2].text, "Right Column");
    }

    #[test]
    fn test_create_layout_line_empty_words() {
        let line = create_layout_line(vec![]);
        assert_eq!(line.text, "");
        assert_eq!(line.bbox, [0.0, 0.0, 0.0, 0.0]);
        assert!(line.words.is_empty());
        assert!(line.word_details.is_empty());
    }

    #[test]
    fn test_merge_same_visual_lines_empty_word_details() {
        let l1 = LayoutTextLine {
            text: "Hello".to_string(),
            bbox: [10.0, 50.0, 50.0, 65.0],
            words: vec![],
            word_details: vec![],
        };
        let l2 = LayoutTextLine {
            text: "World".to_string(),
            bbox: [55.0, 50.0, 95.0, 65.0],
            words: vec![],
            word_details: vec![],
        };
        let merged = merge_same_visual_lines(vec![l1, l2]);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].text, "Hello World");
        assert_eq!(merged[0].bbox, [10.0, 50.0, 95.0, 65.0]);
    }
}
