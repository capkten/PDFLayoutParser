use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};

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
            prev.text = join_layout_words(&prev.word_details);
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
            a.word_idx()
                .cmp(&b.word_idx())
                .then_with(|| a.x0().partial_cmp(&b.x0()).unwrap_or(std::cmp::Ordering::Equal))
        });

        let mut outside_words: Vec<LayoutWordInfo> = Vec::new();
        for w in line_words {
            let cx = (w.x0() + w.x1()) / 2.0;
            let cy = (w.y0() + w.y1()) / 2.0;
            let in_table = tables.iter().any(|t| {
                t.bbox[0] <= cx && cx <= t.bbox[2] && t.bbox[1] <= cy && cy <= t.bbox[3]
            });

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

#[cfg(test)]
mod tests {
    use super::*;

    fn make_word(x0: f64, y0: f64, x1: f64, y1: f64, text: &str, block: usize, line: usize, word: usize) -> WordTupleDto {
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
                LayoutWordInfo { text: "Part".to_string(), bbox: [10.0, 100.0, 35.0, 115.0] },
                LayoutWordInfo { text: "1".to_string(), bbox: [40.0, 100.0, 50.0, 115.0] },
            ],
        };
        let line2 = LayoutTextLine {
            text: "Part 2".to_string(),
            bbox: [60.0, 102.0, 100.0, 117.0],
            words: vec!["Part".to_string(), "2".to_string()],
            word_details: vec![
                LayoutWordInfo { text: "Part".to_string(), bbox: [60.0, 102.0, 85.0, 117.0] },
                LayoutWordInfo { text: "2".to_string(), bbox: [90.0, 102.0, 100.0, 117.0] },
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
            word_details: vec![LayoutWordInfo { text: "Left".to_string(), bbox: [10.0, 100.0, 50.0, 115.0] }],
        };
        let line_a2 = LayoutTextLine {
            text: "Right".to_string(),
            bbox: [95.0, 100.0, 140.0, 115.0], // gap_x = 45.0 > 40.0
            words: vec!["Right".to_string()],
            word_details: vec![LayoutWordInfo { text: "Right".to_string(), bbox: [95.0, 100.0, 140.0, 115.0] }],
        };
        let res_a = merge_same_visual_lines(vec![line_a1, line_a2]);
        assert_eq!(res_a.len(), 2);

        // Case B: gap_x < -2.0
        let line_b1 = LayoutTextLine {
            text: "First".to_string(),
            bbox: [10.0, 100.0, 50.0, 115.0],
            words: vec!["First".to_string()],
            word_details: vec![LayoutWordInfo { text: "First".to_string(), bbox: [10.0, 100.0, 50.0, 115.0] }],
        };
        let line_b2 = LayoutTextLine {
            text: "Overlap".to_string(),
            bbox: [45.0, 100.0, 80.0, 115.0], // gap_x = 45 - 50 = -5.0 < -2.0
            words: vec!["Overlap".to_string()],
            word_details: vec![LayoutWordInfo { text: "Overlap".to_string(), bbox: [45.0, 100.0, 80.0, 115.0] }],
        };
        let res_b = merge_same_visual_lines(vec![line_b1, line_b2]);
        assert_eq!(res_b.len(), 2);

        // Case C: vertical overlap < 0.5
        let line_c1 = LayoutTextLine {
            text: "Upper".to_string(),
            bbox: [10.0, 100.0, 50.0, 110.0], // h = 10
            words: vec!["Upper".to_string()],
            word_details: vec![LayoutWordInfo { text: "Upper".to_string(), bbox: [10.0, 100.0, 50.0, 110.0] }],
        };
        let line_c2 = LayoutTextLine {
            text: "Lower".to_string(),
            bbox: [60.0, 107.0, 100.0, 117.0], // h = 10, overlap = 110 - 107 = 3.0, ratio = 0.3 < 0.5
            words: vec!["Lower".to_string()],
            word_details: vec![LayoutWordInfo { text: "Lower".to_string(), bbox: [60.0, 107.0, 100.0, 117.0] }],
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
            word_details: vec![LayoutWordInfo { text: "A".to_string(), bbox: [10.0, 50.0, 30.0, 65.0] }],
        };
        let line2 = LayoutTextLine {
            text: "B".to_string(),
            bbox: [40.0, 50.0, 60.0, 65.0],
            words: vec!["B".to_string()],
            word_details: vec![LayoutWordInfo { text: "B".to_string(), bbox: [40.0, 50.0, 60.0, 65.0] }],
        };
        let line3 = LayoutTextLine {
            text: "C".to_string(),
            bbox: [70.0, 50.0, 90.0, 65.0],
            words: vec!["C".to_string()],
            word_details: vec![LayoutWordInfo { text: "C".to_string(), bbox: [70.0, 50.0, 90.0, 65.0] }],
        };

        let merged = merge_same_visual_lines(vec![line1, line2, line3]);
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].text, "A B C");
        assert_eq!(merged[0].bbox, [10.0, 50.0, 90.0, 65.0]);
        assert_eq!(merged[0].words, vec!["A", "B", "C"]);
    }
}
