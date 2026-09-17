use crate::types::{
    AtomDto, BackgroundDto, CellDto, ColumnBandDto, EnglishGridInput, GeneralWirelessInput,
    LegacyAlignmentInput, Rect4, RowBandDto, WordDto, ZebraInput,
};

fn center_x(r: &Rect4) -> f64 {
    (r.x0 + r.x1) / 2.0
}

fn center_y(r: &Rect4) -> f64 {
    (r.y0 + r.y1) / 2.0
}

fn is_white_bg(b: &BackgroundDto) -> bool {
    match b.color {
        Some(c) => c >= 0.98,
        None => false,
    }
}

pub fn group_backgrounds(
    mut backgrounds: Vec<BackgroundDto>,
    gap_threshold: f64,
) -> Vec<Vec<BackgroundDto>> {
    if backgrounds.is_empty() {
        return Vec::new();
    }
    backgrounds.sort_by(|a, b| {
        a.rect
            .y0
            .partial_cmp(&b.rect.y0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let mut tables = Vec::new();
    let mut current_table = vec![backgrounds[0].clone()];

    for bg in backgrounds.into_iter().skip(1) {
        let prev_y1 = current_table.last().unwrap().rect.y1;
        let gap = bg.rect.y0 - prev_y1;
        if gap > gap_threshold {
            if current_table.len() >= 2 {
                tables.push(current_table);
            }
            current_table = vec![bg];
        } else {
            current_table.push(bg);
        }
    }
    if current_table.len() >= 2 {
        tables.push(current_table);
    }
    tables
}

pub fn detect_zebra_rows(input: &ZebraInput) -> Vec<RowBandDto> {
    if input.backgrounds.is_empty() {
        return Vec::new();
    }

    let has_region = input.region.rect.y1 > input.region.rect.y0;
    let filtered_bgs: Vec<BackgroundDto> = if has_region {
        input
            .backgrounds
            .iter()
            .filter(|bg| {
                let not_outside = !(bg.rect.y1 <= input.region.rect.y0 + 2.0
                    || bg.rect.y0 >= input.region.rect.y1 - 2.0);
                let not_trailing_white =
                    !(bg.rect.y1 > input.region.rect.y1 + 15.0 && is_white_bg(bg));
                not_outside && not_trailing_white
            })
            .cloned()
            .collect()
    } else {
        input.backgrounds.clone()
    };

    if filtered_bgs.is_empty() {
        return Vec::new();
    }

    // Merge adjacent backgrounds within region if gap <= 60.0 and has words in between
    let mut merged_bgs = Vec::new();
    for bg in filtered_bgs {
        if merged_bgs.is_empty() {
            merged_bgs.push(bg);
        } else {
            let prev_y1 = merged_bgs.last().unwrap().rect.y1;
            let cur_y0 = bg.rect.y0;
            let gap = cur_y0 - prev_y1;
            if gap > 0.0 && gap <= 60.0 {
                let has_text = input.words.iter().any(|w| {
                    let w_mid_y = center_y(&w.rect);
                    let w_mid_x = center_x(&w.rect);
                    prev_y1 - 1.0 <= w_mid_y
                        && w_mid_y <= cur_y0 + 1.0
                        && (!has_region
                            || (input.region.rect.x0 - 5.0 <= w_mid_x
                                && w_mid_x <= input.region.rect.x1 + 5.0))
                });
                if has_text {
                    let mut white_bg = bg.clone();
                    white_bg.rect.y0 = prev_y1;
                    white_bg.rect.y1 = cur_y0;
                    white_bg.color = Some(1.0);
                    merged_bgs.push(white_bg);
                }
            }
            merged_bgs.push(bg);
        }
    }

    let tables_bg = group_backgrounds(merged_bgs, 30.0);
    let mut result_rows = Vec::new();

    for bg_group in tables_bg {
        let colored_bgs: Vec<&BackgroundDto> =
            bg_group.iter().filter(|b| !is_white_bg(b)).collect();
        if colored_bgs.is_empty() {
            continue;
        }

        let last_colored_y = colored_bgs
            .iter()
            .map(|b| b.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max);
        let max_allowed_bottom = if has_region {
            input.region.rect.y1 + 5.0
        } else {
            last_colored_y + 15.0
        };

        let data_bgs: Vec<BackgroundDto> = bg_group
            .into_iter()
            .filter(|b| {
                b.rect.y0 < (last_colored_y + 1.0).max(max_allowed_bottom - 2.0)
                    && b.rect.y1 <= max_allowed_bottom
            })
            .collect();
        if data_bgs.is_empty() {
            continue;
        }

        let mut filled_bgs: Vec<BackgroundDto> = Vec::new();
        for (i, bg) in data_bgs.into_iter().enumerate() {
            if i > 0 {
                let prev_y1 = filled_bgs.last().unwrap().rect.y1;
                let cur_y0 = bg.rect.y0;
                let gap = cur_y0 - prev_y1;
                if gap >= 3.5 && gap <= 25.0 {
                    let mut white_bg = bg.clone();
                    white_bg.rect.y0 = prev_y1;
                    white_bg.rect.y1 = cur_y0;
                    white_bg.color = Some(1.0);
                    filled_bgs.push(white_bg);
                } else if gap > 25.0 {
                    // Check gap words
                    let gap_words: Vec<&WordDto> = input
                        .words
                        .iter()
                        .filter(|w| {
                            let yc = center_y(&w.rect);
                            let _xc = center_x(&w.rect);
                            prev_y1 + 1.0 <= yc
                                && yc <= cur_y0 - 1.0
                                && (!has_region
                                    || (w.rect.x1 >= input.region.rect.x0 - 5.0
                                        && w.rect.x0 <= input.region.rect.x1 + 5.0))
                        })
                        .collect();
                    if gap_words.is_empty() {
                        let mut white_bg = bg.clone();
                        white_bg.rect.y0 = prev_y1;
                        white_bg.rect.y1 = cur_y0;
                        white_bg.color = Some(1.0);
                        filled_bgs.push(white_bg);
                    } else {
                        // Cluster gap words by y
                        let mut text_rows: Vec<f64> = Vec::new();
                        for w in gap_words {
                            let yc = center_y(&w.rect);
                            if !text_rows.iter().any(|&ty| (yc - ty).abs() <= 3.5) {
                                text_rows.push(yc);
                            }
                        }
                        text_rows
                            .sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
                        if text_rows.len() <= 1 {
                            let mut white_bg = bg.clone();
                            white_bg.rect.y0 = prev_y1;
                            white_bg.rect.y1 = cur_y0;
                            white_bg.color = Some(1.0);
                            filled_bgs.push(white_bg);
                        } else {
                            let mut boundaries = vec![prev_y1];
                            for k in 0..text_rows.len() - 1 {
                                boundaries.push((text_rows[k] + text_rows[k + 1]) / 2.0);
                            }
                            boundaries.push(cur_y0);
                            for k in 0..boundaries.len() - 1 {
                                let mut white_bg = bg.clone();
                                white_bg.rect.y0 = boundaries[k];
                                white_bg.rect.y1 = boundaries[k + 1];
                                white_bg.color = Some(1.0);
                                filled_bgs.push(white_bg);
                            }
                        }
                    }
                }
            }
            filled_bgs.push(bg);
        }

        let last_filled_y1 = filled_bgs
            .last()
            .map(|b| b.rect.y1)
            .unwrap_or(last_colored_y);
        if has_region && input.region.rect.y1 > last_filled_y1 + 4.0 {
            let has_bot_words = input.words.iter().any(|w| {
                let yc = center_y(&w.rect);
                last_filled_y1 + 2.0 <= yc && yc <= input.region.rect.y1 + 2.0
            });
            if has_bot_words {
                let mut white_bg = filled_bgs.last().unwrap().clone();
                white_bg.rect.y0 = last_filled_y1;
                white_bg.rect.y1 = input.region.rect.y1;
                white_bg.color = Some(1.0);
                filled_bgs.push(white_bg);
            }
        }

        for (idx, bg) in filled_bgs.into_iter().enumerate() {
            result_rows.push(RowBandDto {
                schema_version: 1,
                rect: bg.rect,
                row_index: idx as i64,
                source_backgrounds: vec![bg.source_order],
                words: Vec::new(),
                cells: Vec::new(),
            });
        }
    }

    result_rows
}

pub fn assign_words_to_zebra_rows(
    words: Vec<WordDto>,
    mut rows: Vec<RowBandDto>,
    row_tol: f64,
) -> Vec<RowBandDto> {
    let mut row_words: Vec<Vec<WordDto>> = vec![Vec::new(); rows.len()];
    let mut unassigned: Vec<WordDto> = Vec::new();

    for w in words {
        let w_yc = center_y(&w.rect);
        let mut matched = None;
        for (idx, r) in rows.iter().enumerate() {
            if r.rect.y0 - row_tol <= w_yc && w_yc <= r.rect.y1 + row_tol {
                matched = Some(idx);
                break;
            }
        }
        if let Some(idx) = matched {
            row_words[idx].push(w);
        } else {
            unassigned.push(w);
        }
    }

    for (idx, r) in rows.iter_mut().enumerate() {
        r.words = std::mem::take(&mut row_words[idx]);
    }

    if !unassigned.is_empty() {
        let mut clusters: Vec<(f64, Vec<WordDto>)> = Vec::new();
        for w in unassigned {
            let mid_y = center_y(&w.rect);
            let mut found = false;
            for (cy, cwords) in clusters.iter_mut() {
                if (mid_y - *cy).abs() <= 3.5 {
                    cwords.push(w.clone());
                    found = true;
                    break;
                }
            }
            if !found {
                clusters.push((mid_y, vec![w]));
            }
        }

        for (_, mut cwords) in clusters {
            cwords.sort_by(|a, b| {
                a.rect
                    .x0
                    .partial_cmp(&b.rect.x0)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            let y0 = cwords
                .iter()
                .map(|w| w.rect.y0)
                .fold(f64::INFINITY, f64::min);
            let y1 = cwords
                .iter()
                .map(|w| w.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max);
            let x0 = cwords
                .iter()
                .map(|w| w.rect.x0)
                .fold(f64::INFINITY, f64::min);
            let x1 = cwords
                .iter()
                .map(|w| w.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max);
            rows.push(RowBandDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0,
                    y0,
                    x1,
                    y1,
                },
                row_index: 0,
                source_backgrounds: Vec::new(),
                words: cwords,
                cells: Vec::new(),
            });
        }

        rows.sort_by(|a, b| {
            a.rect
                .y0
                .partial_cmp(&b.rect.y0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    }

    for (idx, r) in rows.iter_mut().enumerate() {
        r.row_index = idx as i64;
    }

    rows
}

pub fn infer_english_columns(input: &EnglishGridInput) -> Vec<ColumnBandDto> {
    if input.words.is_empty() {
        return Vec::new();
    }

    // Cluster words into rows by center_y
    let mut rows_by_y: Vec<(f64, Vec<&WordDto>)> = Vec::new();
    for w in &input.words {
        let mid_y = center_y(&w.rect);
        let mut found = false;
        for (ey, rwords) in rows_by_y.iter_mut() {
            if (mid_y - *ey).abs() <= 3.5 {
                rwords.push(w);
                found = true;
                break;
            }
        }
        if !found {
            rows_by_y.push((mid_y, vec![w]));
        }
    }

    let mut all_row_segs: Vec<(f64, Vec<(f64, f64)>)> = Vec::new();
    for (ry, mut rwords) in rows_by_y {
        rwords.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut cur: Vec<&WordDto> = Vec::new();
        let mut row_segs: Vec<(f64, f64)> = Vec::new();

        for w in rwords {
            if cur.is_empty() {
                cur.push(w);
            } else {
                let prev = cur.last().unwrap();
                let gap = w.rect.x0 - prev.rect.x1;
                let is_new_currency = (w.text.starts_with('$') || w.text.trim() == "$")
                    && !prev.text.starts_with('$');
                if is_new_currency || gap > 6.0 {
                    let seg_x0 = cur
                        .iter()
                        .map(|item| item.rect.x0)
                        .fold(f64::INFINITY, f64::min);
                    let seg_x1 = cur
                        .iter()
                        .map(|item| item.rect.x1)
                        .fold(f64::NEG_INFINITY, f64::max);
                    row_segs.push((seg_x0, seg_x1));
                    cur = vec![w];
                } else {
                    cur.push(w);
                }
            }
        }
        if !cur.is_empty() {
            let seg_x0 = cur
                .iter()
                .map(|item| item.rect.x0)
                .fold(f64::INFINITY, f64::min);
            let seg_x1 = cur
                .iter()
                .map(|item| item.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max);
            row_segs.push((seg_x0, seg_x1));
        }
        all_row_segs.push((ry, row_segs));
    }

    let mut line_segments: Vec<(f64, f64)> = Vec::new();
    for (ry, r_segs) in &all_row_segs {
        for s in r_segs {
            let mut spanning_count = 0;
            for (other_ry, other_r_segs) in &all_row_segs {
                if (other_ry - ry).abs() < 1e-4 {
                    continue;
                }
                let overlapping_count = other_r_segs
                    .iter()
                    .filter(|os| (s.1.min(os.1) - s.0.max(os.0)) >= 2.0)
                    .count();
                if overlapping_count >= 2 {
                    spanning_count += 1;
                }
            }
            if spanning_count >= 2 {
                continue;
            }
            line_segments.push(*s);
        }
    }

    line_segments.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut col_spans: Vec<(f64, f64)> = Vec::new();
    for s in line_segments {
        if col_spans.is_empty() {
            col_spans.push(s);
        } else {
            let mut merged = false;
            for cs in col_spans.iter_mut() {
                if !(s.1 < cs.0 || s.0 > cs.1) {
                    cs.0 = cs.0.min(s.0);
                    cs.1 = cs.1.max(s.1);
                    merged = true;
                    break;
                }
            }
            if !merged {
                col_spans.push(s);
            }
        }
    }

    col_spans.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    if col_spans.len() < 2 {
        let min_x = input
            .words
            .iter()
            .map(|w| w.rect.x0)
            .fold(f64::INFINITY, f64::min);
        let max_x = input
            .words
            .iter()
            .map(|w| w.rect.x1)
            .fold(f64::NEG_INFINITY, f64::max);
        return vec![ColumnBandDto {
            schema_version: 1,
            x0: min_x,
            x1: max_x,
            source_atoms: Vec::new(),
            order: 0,
        }];
    }

    let has_region = input.region.rect.x1 > input.region.rect.x0;
    let table_x0 = if has_region {
        input.region.rect.x0
    } else {
        input
            .words
            .iter()
            .map(|w| w.rect.x0)
            .fold(f64::INFINITY, f64::min)
    };
    let table_x1 = if has_region {
        input.region.rect.x1
    } else {
        input
            .words
            .iter()
            .map(|w| w.rect.x1)
            .fold(f64::NEG_INFINITY, f64::max)
    };

    let mut boundaries = Vec::new();
    for k in 0..col_spans.len() - 1 {
        let prev_end = col_spans[k].1;
        let next_start = col_spans[k + 1].0;
        let bk = if prev_end < next_start {
            (prev_end + next_start) / 2.0
        } else {
            prev_end + 1.5
        };
        boundaries.push(bk);
    }

    let mut columns: Vec<(f64, f64)> = Vec::new();
    let mut curr_x = table_x0;
    for b in boundaries {
        columns.push((curr_x, b));
        curr_x = b;
    }
    columns.push((curr_x, table_x1));

    // Currency adjust
    let dollar_words: Vec<&WordDto> = input
        .words
        .iter()
        .filter(|w| w.text.starts_with('$') || w.text.trim() == "$")
        .collect();
    for dollar in dollar_words {
        let x0 = dollar.rect.x0;
        for ci in 1..columns.len() {
            let (cx0, cx1) = columns[ci];
            let (prev_x0, _) = columns[ci - 1];
            if prev_x0 < x0 && x0 < cx0 && (cx0 - x0).abs() <= 6.0 {
                columns[ci - 1] = (prev_x0, x0);
                columns[ci] = (x0, cx1);
            }
        }
    }

    columns
        .into_iter()
        .enumerate()
        .map(|(order, (x0, x1))| ColumnBandDto {
            schema_version: 1,
            x0,
            x1,
            source_atoms: Vec::new(),
            order: order as i64,
        })
        .collect()
}

pub fn build_english_cells(input: &EnglishGridInput) -> Vec<CellDto> {
    if input.words.is_empty() {
        return Vec::new();
    }

    let columns = infer_english_columns(input);
    if columns.is_empty() {
        return Vec::new();
    }

    // Cluster words into rows by y
    let mut row_clusters: Vec<(f64, Vec<&WordDto>)> = Vec::new();
    for w in &input.words {
        let yc = center_y(&w.rect);
        let mut found = false;
        for (ry, rwords) in row_clusters.iter_mut() {
            if (yc - *ry).abs() <= 4.0 {
                rwords.push(w);
                found = true;
                break;
            }
        }
        if !found {
            row_clusters.push((yc, vec![w]));
        }
    }
    row_clusters.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let _num_rows = row_clusters.len();
    let num_cols = columns.len();
    let mut cells = Vec::new();

    for (row_idx, (_, mut rwords)) in row_clusters.into_iter().enumerate() {
        rwords.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        // Group into phrases
        let mut phrases: Vec<Vec<&WordDto>> = Vec::new();
        for w in rwords {
            if phrases.is_empty() {
                phrases.push(vec![w]);
            } else {
                let prev = phrases.last().unwrap().last().unwrap();
                let gap = w.rect.x0 - prev.rect.x1;
                if gap <= 10.0 {
                    phrases.last_mut().unwrap().push(w);
                } else {
                    phrases.push(vec![w]);
                }
            }
        }

        // Single phrase covering multiple columns check (spanning header)
        if phrases.len() == 1 {
            let p = &phrases[0];
            let px0 = p.iter().map(|w| w.rect.x0).fold(f64::INFINITY, f64::min);
            let px1 = p
                .iter()
                .map(|w| w.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max);
            let covered_cols: Vec<usize> = columns
                .iter()
                .enumerate()
                .filter(|(_, col)| (px1.min(col.x1) - px0.max(col.x0)) >= 2.0)
                .map(|(ci, _)| ci)
                .collect();
            if covered_cols.len() >= 2 {
                let sc = *covered_cols.first().unwrap();
                let ec = *covered_cols.last().unwrap();
                let text = p
                    .iter()
                    .map(|w| w.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ");
                let y0 = p.iter().map(|w| w.rect.y0).fold(f64::INFINITY, f64::min);
                let y1 = p
                    .iter()
                    .map(|w| w.rect.y1)
                    .fold(f64::NEG_INFINITY, f64::max);

                for col_idx in 0..sc {
                    cells.push(CellDto {
                        schema_version: 1,
                        text: String::new(),
                        row: row_idx as i64,
                        col: col_idx as i64,
                        rect: Rect4 {
                            schema_version: 1,
                            x0: columns[col_idx].x0,
                            y0,
                            x1: columns[col_idx].x1,
                            y1,
                        },
                        rowspan: 1,
                        colspan: 1,
                        source: None,
                    });
                }
                cells.push(CellDto {
                    schema_version: 1,
                    text,
                    row: row_idx as i64,
                    col: sc as i64,
                    rect: Rect4 {
                        schema_version: 1,
                        x0: columns[sc].x0,
                        y0,
                        x1: columns[ec].x1,
                        y1,
                    },
                    rowspan: 1,
                    colspan: (ec - sc + 1) as i64,
                    source: None,
                });
                for col_idx in (ec + 1)..num_cols {
                    cells.push(CellDto {
                        schema_version: 1,
                        text: String::new(),
                        row: row_idx as i64,
                        col: col_idx as i64,
                        rect: Rect4 {
                            schema_version: 1,
                            x0: columns[col_idx].x0,
                            y0,
                            x1: columns[col_idx].x1,
                            y1,
                        },
                        rowspan: 1,
                        colspan: 1,
                        source: None,
                    });
                }
                continue;
            }
        }

        // Standard column assignment
        let mut col_words: Vec<Vec<&WordDto>> = vec![Vec::new(); num_cols];
        for p in phrases {
            let px_mid = p.iter().map(|w| center_x(&w.rect)).sum::<f64>() / p.len() as f64;
            let mut assigned_col = 0;
            for (ci, col) in columns.iter().enumerate() {
                if col.x0 <= px_mid && px_mid < col.x1 {
                    assigned_col = ci;
                    break;
                } else if ci == columns.len() - 1 && px_mid >= col.x0 {
                    assigned_col = ci;
                }
            }
            col_words[assigned_col].extend(p);
        }

        let y0 = if !col_words.iter().all(|cw| cw.is_empty()) {
            col_words
                .iter()
                .flat_map(|cw| cw.iter())
                .map(|w| w.rect.y0)
                .fold(f64::INFINITY, f64::min)
        } else {
            0.0
        };
        let y1 = if !col_words.iter().all(|cw| cw.is_empty()) {
            col_words
                .iter()
                .flat_map(|cw| cw.iter())
                .map(|w| w.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max)
        } else {
            y0 + 15.0
        };

        for col_idx in 0..num_cols {
            let ws = &col_words[col_idx];
            let text = if ws.is_empty() {
                String::new()
            } else {
                ws.iter()
                    .map(|w| w.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            };
            cells.push(CellDto {
                schema_version: 1,
                text,
                row: row_idx as i64,
                col: col_idx as i64,
                rect: Rect4 {
                    schema_version: 1,
                    x0: columns[col_idx].x0,
                    y0,
                    x1: columns[col_idx].x1,
                    y1,
                },
                rowspan: 1,
                colspan: 1,
                source: None,
            });
        }
    }

    cells
}

pub fn build_general_wireless_cells(input: &GeneralWirelessInput) -> Vec<CellDto> {
    if input.atoms.is_empty() || input.bands.is_empty() {
        return Vec::new();
    }

    // Cluster atoms by y
    let mut row_clusters: Vec<(f64, Vec<&AtomDto>)> = Vec::new();
    for atom in &input.atoms {
        let yc = center_y(&atom.rect);
        let mut found = false;
        for (ry, ratoms) in row_clusters.iter_mut() {
            if (yc - *ry).abs() <= input.config.row_tolerance.max(3.5) {
                ratoms.push(atom);
                found = true;
                break;
            }
        }
        if !found {
            row_clusters.push((yc, vec![atom]));
        }
    }
    row_clusters.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));

    let _num_rows = row_clusters.len();
    let num_cols = input.bands.len();
    let mut cells = Vec::new();

    for (r, (_, mut ratoms)) in row_clusters.into_iter().enumerate() {
        ratoms.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut col_atoms: Vec<Vec<&AtomDto>> = vec![Vec::new(); num_cols];

        for atom in ratoms {
            let xc = center_x(&atom.rect);
            let mut assigned_col = 0;
            for (ci, band) in input.bands.iter().enumerate() {
                if band.x0 <= xc && xc < band.x1 {
                    assigned_col = ci;
                    break;
                } else if ci == input.bands.len() - 1 && xc >= band.x0 {
                    assigned_col = ci;
                }
            }
            col_atoms[assigned_col].push(atom);
        }

        let y0 = if !col_atoms.iter().all(|ca| ca.is_empty()) {
            col_atoms
                .iter()
                .flat_map(|ca| ca.iter())
                .map(|a| a.rect.y0)
                .fold(f64::INFINITY, f64::min)
        } else {
            0.0
        };
        let y1 = if !col_atoms.iter().all(|ca| ca.is_empty()) {
            col_atoms
                .iter()
                .flat_map(|ca| ca.iter())
                .map(|a| a.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max)
        } else {
            y0 + 15.0
        };

        for c in 0..num_cols {
            let ca = &col_atoms[c];
            let text = if ca.is_empty() {
                String::new()
            } else {
                ca.iter()
                    .map(|a| a.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            };
            cells.push(CellDto {
                schema_version: 1,
                text,
                row: r as i64,
                col: c as i64,
                rect: Rect4 {
                    schema_version: 1,
                    x0: input.bands[c].x0,
                    y0,
                    x1: input.bands[c].x1,
                    y1,
                },
                rowspan: 1,
                colspan: 1,
                source: None,
            });
        }
    }

    cells
}

pub fn build_legacy_text_alignment(input: &LegacyAlignmentInput) -> Vec<CellDto> {
    if input.words.len() < 4 {
        return Vec::new();
    }

    // Cluster tokens by y (tolerance 17.0)
    let mut row_clusters: Vec<(f64, Vec<&WordDto>)> = Vec::new();
    for w in &input.words {
        let yc = center_y(&w.rect);
        let mut found = false;
        for (ry, rwords) in row_clusters.iter_mut() {
            if (yc - *ry).abs() <= 17.0 {
                rwords.push(w);
                found = true;
                break;
            }
        }
        if !found {
            row_clusters.push((yc, vec![w]));
        }
    }
    row_clusters.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    if row_clusters.len() < 2 {
        return Vec::new();
    }

    // Filter out obvious multi-column spans when inferring column bands
    let mut words_sorted_x: Vec<&WordDto> = input
        .words
        .iter()
        .filter(|w| {
            let t = &w.text;
            !t.contains("本年金额")
                && !t.contains("上年金额")
                && !t.contains("本期金额")
                && !t.contains("上期金额")
        })
        .collect();
    if words_sorted_x.is_empty() {
        words_sorted_x = input.words.iter().collect();
    }
    words_sorted_x.sort_by(|a, b| {
        center_x(&a.rect)
            .partial_cmp(&center_x(&b.rect))
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut col_clusters: Vec<Vec<&WordDto>> = Vec::new();
    let col_tol = 30.0;
    for w in words_sorted_x {
        let xc = center_x(&w.rect);
        if col_clusters.is_empty() {
            col_clusters.push(vec![w]);
        } else {
            let cur_center = col_clusters
                .last()
                .unwrap()
                .iter()
                .map(|item| center_x(&item.rect))
                .sum::<f64>()
                / col_clusters.last().unwrap().len() as f64;
            if (xc - cur_center).abs() <= col_tol {
                col_clusters.last_mut().unwrap().push(w);
            } else {
                col_clusters.push(vec![w]);
            }
        }
    }
    if col_clusters.len() < 2 {
        return Vec::new();
    }

    let col_centers: Vec<f64> = col_clusters
        .iter()
        .map(|grp| grp.iter().map(|item| center_x(&item.rect)).sum::<f64>() / grp.len() as f64)
        .collect();
    let mut col_boundaries = Vec::new();
    for i in 0..col_centers.len() - 1 {
        col_boundaries.push((col_centers[i] + col_centers[i + 1]) / 2.0);
    }
    let total_cols = col_boundaries.len() + 1;

    let mut cells = Vec::new();
    for (row_idx, (_, mut rwords)) in row_clusters.into_iter().enumerate() {
        rwords.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut cell_words: Vec<Vec<&WordDto>> = vec![Vec::new(); total_cols];

        for w in rwords {
            let xc = center_x(&w.rect);
            let mut col_idx = total_cols - 1;
            for (ci, bound) in col_boundaries.iter().enumerate() {
                if xc < *bound {
                    col_idx = ci;
                    break;
                }
            }
            cell_words[col_idx].push(w);
        }

        let y0 = if !cell_words.iter().all(|cw| cw.is_empty()) {
            cell_words
                .iter()
                .flat_map(|cw| cw.iter())
                .map(|w| w.rect.y0)
                .fold(f64::INFINITY, f64::min)
        } else {
            0.0
        };
        let y1 = if !cell_words.iter().all(|cw| cw.is_empty()) {
            cell_words
                .iter()
                .flat_map(|cw| cw.iter())
                .map(|w| w.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max)
        } else {
            y0 + 15.0
        };

        // Check group header row in row 0
        let non_empty_cols: Vec<usize> = cell_words
            .iter()
            .enumerate()
            .filter(|(_, cw)| !cw.is_empty())
            .map(|(ci, _)| ci)
            .collect();
        if row_idx == 0 && non_empty_cols.len() == 1 {
            let col_idx = non_empty_cols[0];
            let all_w: Vec<&WordDto> = cell_words[col_idx].clone();
            let start_x0 = all_w
                .iter()
                .map(|w| w.rect.x0)
                .fold(f64::INFINITY, f64::min);
            let mut true_col_idx = 0;
            for (ci, bound) in col_boundaries.iter().enumerate() {
                if start_x0 >= *bound {
                    true_col_idx = ci + 1;
                }
            }
            let text = all_w
                .iter()
                .map(|w| w.text.as_str())
                .collect::<Vec<_>>()
                .join(" ");
            let is_group = text.contains("本年金额")
                || text.contains("上年金额")
                || text.contains("本期金额")
                || text.contains("上期金额")
                || text.contains("\u{672c}\u{5e74}\u{91d1}\u{989d}")
                || text.contains("\u{4e0a}\u{5e74}\u{91d1}\u{989d}")
                || text.contains("\u{672c}\u{671f}\u{91d1}\u{989d}")
                || text.contains("\u{4e0a}\u{671f}\u{91d1}\u{989d}")
                || text.contains("Year End Amount")
                || non_empty_cols.len() == 1;
            if is_group {
                let start_col = true_col_idx.max(1);
                let colspan = (total_cols - start_col).max(1);
                cells.push(CellDto {
                    schema_version: 1,
                    text,
                    row: 0,
                    col: start_col as i64,
                    rect: Rect4 {
                        schema_version: 1,
                        x0: if start_col > 0 {
                            col_boundaries[start_col - 1]
                        } else {
                            input.region.rect.x0
                        },
                        y0,
                        x1: input.region.rect.x1,
                        y1,
                    },
                    rowspan: 1,
                    colspan: colspan as i64,
                    source: None,
                });
                continue;
            }
        }

        for col_idx in 0..total_cols {
            let cw = &cell_words[col_idx];
            let text = if cw.is_empty() {
                String::new()
            } else {
                cw.iter()
                    .map(|w| w.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            };
            let x0 = if col_idx == 0 {
                input.region.rect.x0
            } else {
                col_boundaries[col_idx - 1]
            };
            let x1 = if col_idx == total_cols - 1 {
                input.region.rect.x1
            } else {
                col_boundaries[col_idx]
            };
            cells.push(CellDto {
                schema_version: 1,
                text,
                row: row_idx as i64,
                col: col_idx as i64,
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

    cells
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::StructureConfig;

    fn make_bg(y0: f64, y1: f64, color: Option<f64>, order: i64) -> BackgroundDto {
        BackgroundDto {
            schema_version: 1,
            rect: Rect4 {
                schema_version: 1,
                x0: 50.0,
                y0,
                x1: 500.0,
                y1,
            },
            color,
            opacity: None,
            source_order: order,
        }
    }

    fn make_word(text: &str, x0: f64, y0: f64, x1: f64, y1: f64) -> WordDto {
        WordDto {
            schema_version: 1,
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            text: text.to_string(),
            order: 0,
            block: None,
            line: None,
        }
    }

    #[test]
    fn test_group_backgrounds() {
        let bgs = vec![
            make_bg(10.0, 25.0, Some(0.9), 0),
            make_bg(30.0, 45.0, Some(1.0), 1),
            make_bg(50.0, 65.0, Some(0.9), 2),
            make_bg(150.0, 165.0, Some(0.9), 3),
            make_bg(170.0, 185.0, Some(1.0), 4),
        ];
        let groups = group_backgrounds(bgs, 30.0);
        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].len(), 3);
        assert_eq!(groups[1].len(), 2);
    }

    #[test]
    fn test_assign_words_to_zebra_rows() {
        let rows = vec![
            RowBandDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: 50.0,
                    y0: 10.0,
                    x1: 500.0,
                    y1: 25.0,
                },
                row_index: 0,
                source_backgrounds: vec![0],
                words: Vec::new(),
                cells: Vec::new(),
            },
            RowBandDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: 50.0,
                    y0: 30.0,
                    x1: 500.0,
                    y1: 45.0,
                },
                row_index: 1,
                source_backgrounds: vec![1],
                words: Vec::new(),
                cells: Vec::new(),
            },
        ];
        let words = vec![
            make_word("Header", 60.0, 12.0, 100.0, 22.0),
            make_word("Data", 60.0, 32.0, 100.0, 42.0),
        ];
        let assigned = assign_words_to_zebra_rows(words, rows, 2.0);
        assert_eq!(assigned.len(), 2);
        assert_eq!(assigned[0].words.len(), 1);
        assert_eq!(assigned[0].words[0].text, "Header");
        assert_eq!(assigned[1].words.len(), 1);
        assert_eq!(assigned[1].words[0].text, "Data");
    }

    #[test]
    fn test_infer_english_columns_currency() {
        let words = vec![
            make_word("Revenue", 50.0, 10.0, 100.0, 20.0),
            make_word("$", 200.0, 10.0, 205.0, 20.0),
            make_word("500", 210.0, 10.0, 230.0, 20.0),
            make_word("Cost", 50.0, 30.0, 90.0, 40.0),
            make_word("$", 200.0, 30.0, 205.0, 40.0),
            make_word("300", 210.0, 30.0, 230.0, 40.0),
        ];
        let input = EnglishGridInput {
            schema_version: 1,
            region: crate::types::RegionDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: 40.0,
                    y0: 0.0,
                    x1: 300.0,
                    y1: 50.0,
                },
                source_order: 0,
                allowed: true,
            },
            words,
            backgrounds: Vec::new(),
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };
        let cols = infer_english_columns(&input);
        assert!(cols.len() >= 2);
        // Column boundary adjusted to dollar position
        assert!(cols[0].x1 <= 200.0);
    }
}
