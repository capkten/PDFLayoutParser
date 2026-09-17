use crate::types::{
    AtomDto, NativeRecoveryInput, NativeRecoveryOutput, NativeSpanDto, OutputOrderMode, Rect4,
    TableCandidateDto, TextRunDto,
};

const SPACED_CJK_WORD_WHITELIST: &[(&str, &str)] = &[
    ("合", "计"),
    ("小", "计"),
    ("总", "计"),
    ("共", "计"),
    ("类", "别"),
    ("税", "种"),
    ("项", "目"),
    ("名", "称"),
    ("金", "额"),
    ("单", "位"),
    ("备", "注"),
    ("比", "例"),
    ("期", "初"),
    ("期", "末"),
    ("年", "初"),
    ("年", "末"),
    ("本", "年"),
    ("上", "年"),
    ("折", "旧"),
    ("残", "值"),
];

fn is_cjk_char(c: char) -> bool {
    ('\u{3400}'..='\u{9fff}').contains(&c)
}

fn is_single_cjk(s: &str) -> bool {
    let trimmed = s.trim();
    trimmed.chars().count() == 1 && is_cjk_char(trimmed.chars().next().unwrap())
}

fn is_whitelisted_cjk_pair(prev: &str, cand: &str) -> bool {
    let p = prev.trim();
    let c = cand.trim();
    SPACED_CJK_WORD_WHITELIST
        .iter()
        .any(|&(w1, w2)| w1 == p && w2 == c)
}

fn center_y(r: &Rect4) -> f64 {
    (r.y0 + r.y1) / 2.0
}

fn center_x(r: &Rect4) -> f64 {
    (r.x0 + r.x1) / 2.0
}

fn is_separator_span(text: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return false;
    }
    trimmed.chars().all(|c| {
        matches!(
            c,
            '-' | '_' | '=' | '—' | '–' | '─' | '━' | '＝' | '□' | '■' | '▪' | '▫'
        )
    })
}

pub fn build_text_runs(spans: Vec<NativeSpanDto>, region: Rect4) -> Vec<TextRunDto> {
    if spans.is_empty() {
        return Vec::new();
    }

    // 1. 过滤中心点在 region 范围内的非空 span，并排除长度大于 3 的纯线分隔符
    let mut valid_spans: Vec<NativeSpanDto> = spans
        .into_iter()
        .filter(|s| {
            let t = s.text.trim();
            if t.is_empty() {
                return false;
            }
            let cx = center_x(&s.rect);
            let cy = center_y(&s.rect);
            if cx < region.x0 || cx > region.x1 || cy < region.y0 || cy > region.y1 {
                return false;
            }
            let is_sep = is_separator_span(t);
            if is_sep && t.chars().count() > 3 {
                return false;
            }
            true
        })
        .collect();

    if valid_spans.is_empty() {
        return Vec::new();
    }

    // 2. 按视觉行分组（y-center 容差聚类）
    valid_spans.sort_by(
        |a, b| match center_y(&a.rect).partial_cmp(&center_y(&b.rect)) {
            Some(std::cmp::Ordering::Equal) => match a.rect.x0.partial_cmp(&b.rect.x0) {
                Some(std::cmp::Ordering::Equal) => a.order.cmp(&b.order),
                Some(ord) => ord,
                None => std::cmp::Ordering::Equal,
            },
            Some(ord) => ord,
            None => std::cmp::Ordering::Equal,
        },
    );

    let mut rows: Vec<Vec<NativeSpanDto>> = Vec::new();
    let mut row_centers: Vec<f64> = Vec::new();

    for span in valid_spans {
        let cy = center_y(&span.rect);
        let size = span.size.unwrap_or(10.0);
        let tol = 2.4_f64.max(size * 0.38);

        let mut matched = false;
        for (r_idx, center) in row_centers.iter().enumerate().rev() {
            if (cy - center).abs() <= tol {
                rows[r_idx].push(span.clone());
                let count = rows[r_idx].len() as f64;
                let sum_cy: f64 = rows[r_idx].iter().map(|s| center_y(&s.rect)).sum();
                row_centers[r_idx] = sum_cy / count;
                matched = true;
                break;
            }
        }
        if !matched {
            rows.push(vec![span]);
            row_centers.push(cy);
        }
    }

    // 3. 行内成词（基于 can_join 与白名单逻辑）
    let mut runs: Vec<TextRunDto> = Vec::new();
    let mut run_order = 0;

    for mut row in rows {
        row.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut groups: Vec<Vec<NativeSpanDto>> = Vec::new();
        for span in row {
            if groups.is_empty() {
                groups.push(vec![span]);
                continue;
            }

            let can_join = {
                let prev = groups.last().unwrap().last().unwrap();
                let gap = span.rect.x0 - prev.rect.x1;
                let prev_size = prev.size.unwrap_or(10.0);
                let cand_size = span.size.unwrap_or(10.0);
                let min_size = prev_size.min(cand_size);
                let same_line =
                    prev.block == span.block && prev.line == span.line && span.order >= prev.order;

                if prev.text == "$" || span.text == "$" {
                    false
                } else if (center_y(&prev.rect) - center_y(&span.rect)).abs()
                    > 2.4_f64.max(min_size * 0.38)
                {
                    false
                } else if is_whitelisted_cjk_pair(&prev.text, &span.text) {
                    same_line && (-0.8..=min_size * 2.5).contains(&gap)
                } else if is_single_cjk(&prev.text) && is_single_cjk(&span.text) {
                    same_line && (-0.8..=min_size * 1.25).contains(&gap)
                } else if same_line && (-0.8..=min_size * 0.8).contains(&gap) {
                    true
                } else {
                    false
                }
            };

            if can_join {
                groups.last_mut().unwrap().push(span);
            } else {
                groups.push(vec![span]);
            }
        }

        for group in groups {
            let joined_text = group
                .iter()
                .map(|s| s.text.as_str())
                .collect::<Vec<_>>()
                .join("");
            let x0 = group
                .iter()
                .map(|s| s.rect.x0)
                .fold(f64::INFINITY, f64::min);
            let y0 = group
                .iter()
                .map(|s| s.rect.y0)
                .fold(f64::INFINITY, f64::min);
            let x1 = group
                .iter()
                .map(|s| s.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max);
            let y1 = group
                .iter()
                .map(|s| s.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max);
            let span_refs = group.iter().map(|s| s.order).collect();
            let source_start = group.iter().map(|s| s.order).min().unwrap_or(0);
            let source_end = group.iter().map(|s| s.order).max().unwrap_or(0);

            runs.push(TextRunDto {
                schema_version: 1,
                text: joined_text,
                rect: Rect4 {
                    schema_version: 1,
                    x0,
                    y0,
                    x1,
                    y1,
                },
                span_refs,
                source_start,
                source_end,
                order: run_order,
            });
            run_order += 1;
        }
    }

    runs
}

pub fn build_atoms(runs: Vec<TextRunDto>, _region: Option<Rect4>) -> Vec<AtomDto> {
    runs.into_iter()
        .map(|run| AtomDto {
            schema_version: 1,
            text: run.text,
            rect: run.rect,
            run_refs: vec![run.order],
            row_hint: None,
            col_hint: None,
            order: run.order,
        })
        .collect()
}

pub fn merge_wrapped_rows(atoms: Vec<AtomDto>, tolerance: f64) -> Vec<AtomDto> {
    if atoms.len() < 2 {
        return atoms;
    }

    let mut result: Vec<AtomDto> = Vec::new();
    for atom in atoms {
        if let Some(prev) = result.last_mut() {
            let vertical_gap = atom.rect.y0 - prev.rect.y1;
            let overlap_x = prev.rect.x1.min(atom.rect.x1) - prev.rect.x0.max(atom.rect.x0);
            let prev_w = prev.rect.x1 - prev.rect.x0;

            if vertical_gap >= 0.0
                && vertical_gap <= tolerance
                && overlap_x > 0.0
                && overlap_x >= prev_w * 0.4
            {
                prev.text.push_str(&atom.text);
                prev.rect.y1 = prev.rect.y1.max(atom.rect.y1);
                prev.rect.x0 = prev.rect.x0.min(atom.rect.x0);
                prev.rect.x1 = prev.rect.x1.max(atom.rect.x1);
                prev.run_refs.extend(atom.run_refs);
                continue;
            }
        }
        result.push(atom);
    }
    result
}

pub fn infer_output_order_mode(atoms: Vec<AtomDto>) -> OutputOrderMode {
    if atoms.len() < 4 {
        return OutputOrderMode {
            schema_version: 1,
            value: "row_interleaved".to_string(),
        };
    }

    let mut row_interleaved_votes = 0;
    let mut columnar_votes = 0;

    for window in atoms.windows(2) {
        let a = &window[0];
        let b = &window[1];
        let dy = (center_y(&b.rect) - center_y(&a.rect)).abs();
        let dx = (center_x(&b.rect) - center_x(&a.rect)).abs();
        if dx > dy * 1.5 {
            row_interleaved_votes += 1;
        } else if dy > dx * 1.5 {
            columnar_votes += 1;
        }
    }

    let value = if columnar_votes > row_interleaved_votes * 2 {
        "columnar".to_string()
    } else {
        "row_interleaved".to_string()
    };

    OutputOrderMode {
        schema_version: 1,
        value,
    }
}

pub fn recover_native_candidates(input: NativeRecoveryInput) -> NativeRecoveryOutput {
    let runs = build_text_runs(input.spans, input.region.rect.clone());
    let atoms = build_atoms(runs, Some(input.region.rect.clone()));

    if atoms.len() < 4 {
        return NativeRecoveryOutput {
            schema_version: 1,
            candidates: Vec::new(),
            atoms,
            diagnostics: Vec::new(),
        };
    }

    // 简单行/列分布检测
    let mut y_coords: Vec<f64> = atoms.iter().map(|a| center_y(&a.rect)).collect();
    y_coords.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mut rows = 1;
    for w in y_coords.windows(2) {
        if w[1] - w[0] > input.config.row_tolerance {
            rows += 1;
        }
    }

    let mut x_coords: Vec<f64> = atoms.iter().map(|a| center_x(&a.rect)).collect();
    x_coords.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mut cols = 1;
    for w in x_coords.windows(2) {
        if w[1] - w[0] > input.config.column_tolerance * 5.0 {
            cols += 1;
        }
    }

    let mut candidates = Vec::new();
    if rows >= 2 && cols >= 2 {
        let x0 = atoms
            .iter()
            .map(|a| a.rect.x0)
            .fold(f64::INFINITY, f64::min);
        let y0 = atoms
            .iter()
            .map(|a| a.rect.y0)
            .fold(f64::INFINITY, f64::min);
        let x1 = atoms
            .iter()
            .map(|a| a.rect.x1)
            .fold(f64::NEG_INFINITY, f64::max);
        let y1 = atoms
            .iter()
            .map(|a| a.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max);

        candidates.push(TableCandidateDto {
            schema_version: 1,
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            source: "wireless_native_recovery".to_string(),
            confidence: Some(0.9),
            rows: rows as i64,
            cols: cols as i64,
            cells: Vec::new(),
        });
    }

    NativeRecoveryOutput {
        schema_version: 1,
        candidates,
        atoms,
        diagnostics: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{CharacterDto, Rect4, SourcePositionDto};

    fn make_span(text: &str, x0: f64, y0: f64, x1: f64, y1: f64, order: i64) -> NativeSpanDto {
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
                line: 0,
            },
            block: 0,
            line: 0,
        }
    }

    #[test]
    fn test_whitelist_cjk_merge() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 500.0,
        };
        let spans = vec![
            make_span("合", 10.0, 10.0, 20.0, 20.0, 0),
            make_span("计", 40.0, 10.0, 50.0, 20.0, 1),
        ];
        let runs = build_text_runs(spans, region);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].text, "合计");
    }

    #[test]
    fn test_non_whitelist_cjk_separated() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 500.0,
        };
        let spans = vec![
            make_span("男", 10.0, 10.0, 20.0, 20.0, 0),
            make_span("女", 35.0, 10.0, 45.0, 20.0, 1),
        ];
        let runs = build_text_runs(spans, region);
        assert_eq!(runs.len(), 2);
        assert_eq!(runs[0].text, "男");
        assert_eq!(runs[1].text, "女");
    }
}
