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

fn has_digit(text: &str) -> bool {
    text.chars().any(|ch| ch.is_ascii_digit())
}

fn is_currency_token(text: &str) -> bool {
    let trimmed = text.trim();
    trimmed == "$" || trimmed.starts_with('$')
}

fn is_percentage_token(text: &str) -> bool {
    text.contains('%') && has_digit(text)
}

fn amount_dollar_is_pure(dollar: &WordDto, row_words: &[&WordDto]) -> bool {
    if !dollar.text.contains('$') {
        return false;
    }
    let same_row: Vec<&WordDto> = row_words
        .iter()
        .copied()
        .filter(|word| (center_y(&word.rect) - center_y(&dollar.rect)).abs() <= 3.5)
        .collect();
    if has_digit(&dollar.text) {
        return true;
    }
    let dollar_index = same_row.iter().position(|word| std::ptr::eq(*word, dollar));
    let Some(index) = dollar_index else {
        return false;
    };
    same_row
        .iter()
        .skip(index + 1)
        .any(|word| word.rect.x0 - dollar.rect.x1 <= 45.0 && has_digit(&word.text))
}

fn cluster_word_rows<'a>(words: &'a [WordDto], tolerance: f64) -> Vec<(f64, Vec<&'a WordDto>)> {
    let mut rows: Vec<(f64, Vec<&WordDto>)> = Vec::new();
    for word in words {
        let word_y = center_y(&word.rect);
        if let Some((_row_y, row_words)) = rows
            .iter_mut()
            .find(|(row_y, _)| (word_y - *row_y).abs() <= tolerance)
        {
            row_words.push(word);
        } else {
            rows.push((word_y, vec![word]));
        }
    }
    rows.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    rows
}

fn cluster_english_rows<'a>(input: &'a EnglishGridInput) -> Vec<(f64, Vec<&'a WordDto>)> {
    let colored_backgrounds: Vec<(usize, &BackgroundDto)> = input
        .backgrounds
        .iter()
        .enumerate()
        .filter(|(_, background)| background.color.is_some())
        .collect();
    if colored_backgrounds.is_empty() {
        return cluster_word_rows(&input.words, 4.0);
    }

    let mut rows: Vec<(f64, Vec<&'a WordDto>)> = colored_backgrounds
        .iter()
        .map(|(_, background)| {
            (
                (background.rect.y0 + background.rect.y1) / 2.0,
                Vec::new(),
            )
        })
        .collect();
    let mut assigned = vec![false; input.words.len()];

    for (word_index, word) in input.words.iter().enumerate() {
        let center = center_y(&word.rect);
        let target = colored_backgrounds
            .iter()
            .enumerate()
            .filter(|(_, (_, background))| {
                center >= background.rect.y0 - 0.01 && center <= background.rect.y1 + 0.01
            })
            .min_by(|(_, (_, left)), (_, (_, right))| {
                let left_distance = (center - (left.rect.y0 + left.rect.y1) / 2.0).abs();
                let right_distance = (center - (right.rect.y0 + right.rect.y1) / 2.0).abs();
                left_distance
                    .partial_cmp(&right_distance)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .map(|(index, _)| index);
        if let Some(row_index) = target {
            rows[row_index].1.push(word);
            assigned[word_index] = true;
        }
    }

    let unassigned: Vec<&'a WordDto> = input
        .words
        .iter()
        .enumerate()
        .filter_map(|(index, word)| (!assigned[index]).then_some(word))
        .collect();
    let mut fallback: Vec<(f64, Vec<&'a WordDto>)> = Vec::new();
    for word in unassigned {
        let center = center_y(&word.rect);
        if let Some((_row_y, row_words)) = fallback
            .iter_mut()
            .find(|(row_y, _)| (center - *row_y).abs() <= 4.0)
        {
            row_words.push(word);
        } else {
            fallback.push((center, vec![word]));
        }
    }
    rows.extend(fallback);
    rows.retain(|(_, words)| !words.is_empty());
    rows.sort_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    rows
}
fn phrase_bounds(words: &[WordDto]) -> Vec<(f64, f64)> {
    let mut phrases = Vec::new();
    for (_, mut row_words) in cluster_word_rows(words, 3.5) {
        row_words.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut current: Vec<&WordDto> = Vec::new();
        for word in row_words {
            let joins = current
                .last()
                .map(|previous| word.rect.x0 - previous.rect.x1 <= 5.0)
                .unwrap_or(false);
            if !joins && !current.is_empty() {
                phrases.push((
                    current
                        .iter()
                        .map(|item| item.rect.x0)
                        .fold(f64::INFINITY, f64::min),
                    current
                        .iter()
                        .map(|item| item.rect.x1)
                        .fold(f64::NEG_INFINITY, f64::max),
                ));
                current.clear();
            }
            current.push(word);
        }
        if !current.is_empty() {
            phrases.push((
                current
                    .iter()
                    .map(|item| item.rect.x0)
                    .fold(f64::INFINITY, f64::min),
                current
                    .iter()
                    .map(|item| item.rect.x1)
                    .fold(f64::NEG_INFINITY, f64::max),
            ));
        }
    }
    phrases
}

fn prune_english_columns(
    mut columns: Vec<(f64, f64)>,
    words: &[WordDto],
    table_x0: f64,
    table_x1: f64,
) -> Vec<(f64, f64)> {
    if columns.len() <= 2 {
        return columns;
    }

    loop {
        if columns.len() <= 2 {
            break;
        }
        let counts: Vec<usize> = columns
            .iter()
            .map(|(x0, x1)| {
                words
                    .iter()
                    .filter(|word| {
                        let x = center_x(&word.rect);
                        *x0 - 2.0 <= x && x <= *x1 + 2.0
                    })
                    .count()
            })
            .collect();
        let empty_index = counts.iter().position(|count| *count == 0);
        let Some(index) = empty_index else {
            break;
        };
        if index == 0 {
            let left = columns[index].0;
            columns[index + 1].0 = left;
        } else {
            let right = columns[index].1;
            columns[index - 1].1 = right;
        }
        columns.remove(index);
    }

    let phrases = phrase_bounds(words);
    let mut index = 0;
    while index < columns.len() && columns.len() > 2 {
        let (x0, x1) = columns[index];
        let width = x1 - x0;
        let contained = phrases
            .iter()
            .filter(|(px0, px1)| *px0 >= x0 - 3.0 && *px1 <= x1 + 3.0)
            .count();
        let spanning = phrases
            .iter()
            .filter(|(px0, px1)| *px0 < x0 + 3.0 && *px1 > x1 - 3.0 && (*px1 - *px0) > width * 1.3)
            .count();
        if contained == 0 || (contained <= 1 && spanning >= 3) {
            if index == 0 {
                columns[index + 1].0 = x0;
            } else {
                columns[index - 1].1 = x1;
            }
            columns.remove(index);
        } else {
            index += 1;
        }
    }

    if let Some(first) = columns.first_mut() {
        first.0 = table_x0;
    }
    if let Some(last) = columns.last_mut() {
        last.1 = table_x1;
    }
    for index in 1..columns.len() {
        let boundary = columns[index].0;
        columns[index - 1].1 = boundary;
    }
    columns.retain(|(x0, x1)| x0 < x1);
    columns
}

fn make_english_cell(
    text: String,
    row: usize,
    col: usize,
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    rowspan: usize,
    colspan: usize,
) -> CellDto {
    CellDto {
        schema_version: 1,
        text,
        row: row as i64,
        col: col as i64,
        rect: Rect4 {
            schema_version: 1,
            x0,
            y0,
            x1,
            y1,
        },
        rowspan: rowspan as i64,
        colspan: colspan as i64,
        source: None,
    }
}

fn merge_wrapped_header_rows(row_cells: &mut [Vec<CellDto>], header_rows: usize, row_groups: &[usize]) {
    for row_index in 0..header_rows.saturating_sub(1) {
        let mut cell_index = 0;
        while cell_index < row_cells[row_index].len() {
            if row_cells[row_index][cell_index].text.trim().is_empty() {
                cell_index += 1;
                continue;
            }
            let mut next_row = row_index + 1;
            while next_row < header_rows {
                let top = row_cells[row_index][cell_index].clone();
                let repeats_header_text = row_cells[next_row]
                    .iter()
                    .any(|candidate| candidate.text.trim() == top.text.trim());
                if row_groups.get(row_index) != row_groups.get(next_row) && !repeats_header_text {
                    break;
                }
                let target = row_cells[next_row].iter().position(|candidate| {
                    !candidate.text.trim().is_empty()
                        && candidate.col == top.col
                        && candidate.colspan == top.colspan
                        && candidate.row == next_row as i64
                });
                let Some(target_index) = target else {
                    let blocked = row_cells[next_row].iter().any(|candidate| {
                        !candidate.text.trim().is_empty()
                            && candidate.col < top.col + top.colspan
                            && candidate.col + candidate.colspan > top.col
                    });
                    if blocked {
                        break;
                    }
                    next_row += 1;
                    continue;
                };

                let top_has_stub = row_cells[row_index]
                    .iter()
                    .any(|cell| cell.col == 0 && !cell.text.trim().is_empty());
                if next_row > row_index + 1
                    && header_rows < 4
                    && (row_groups.get(row_index) != row_groups.get(next_row) || top_has_stub) {
                    break;
                }

                let bottom = row_cells[next_row][target_index].clone();
                if top.text.trim() != bottom.text.trim() {
                    row_cells[row_index][cell_index].text =
                        format!("{} {}", top.text.trim(), bottom.text.trim());
                }
                row_cells[row_index][cell_index].rect = Rect4 {
                    schema_version: 1,
                    x0: top.rect.x0.min(bottom.rect.x0),
                    y0: top.rect.y0.min(bottom.rect.y0),
                    x1: top.rect.x1.max(bottom.rect.x1),
                    y1: top.rect.y1.max(bottom.rect.y1),
                };
                row_cells[next_row][target_index].text.clear();
                next_row += 1;
            }
            cell_index += 1;
        }
    }
}

fn compress_english_header_rows(mut row_cells: Vec<Vec<CellDto>>, row_bounds: Vec<(f64, f64)>, header_rows: usize, row_groups: &[usize]) -> (Vec<Vec<CellDto>>, Vec<(f64, f64)>, usize) {
    merge_wrapped_header_rows(&mut row_cells, header_rows, row_groups);

    if header_rows >= 4 && !row_cells.is_empty() {
        let mut promote = Vec::new();
        for row_index in 1..header_rows.min(row_cells.len()) {
            for cell_index in 0..row_cells[row_index].len() {
                let cell = &row_cells[row_index][cell_index];
                if cell.text.trim().is_empty() {
                    continue;
                }
                let cell_end = cell.col + cell.colspan;
                let has_top_parent = row_cells[0].iter().any(|top| {
                    !top.text.trim().is_empty()
                        && top.col < cell_end
                        && top.col + top.colspan > cell.col
                });
                if has_top_parent {
                    continue;
                }
                let has_other_header_support = row_cells
                    .iter()
                    .enumerate()
                    .take(header_rows.min(row_cells.len()))
                    .any(|(other_row, cells)| {
                        cells.iter().enumerate().any(|(other_index, other)| {
                            (other_row != row_index || other_index != cell_index)
                                && !other.text.trim().is_empty()
                                && other.col < cell_end
                                && other.col + other.colspan > cell.col
                        })
                    });
                if !has_other_header_support {
                    promote.push((row_index, cell_index));
                }
            }
        }

        for (row_index, cell_index) in promote.into_iter().rev() {
            let mut cell = row_cells[row_index].remove(cell_index);
            cell.row = 0;
            if let Some((y0, _)) = row_bounds.first() {
                cell.rect.y0 = *y0;
            }
            if let Some((_, y1)) = row_bounds.get(header_rows.saturating_sub(1)) {
                cell.rect.y1 = *y1;
            }
            row_cells[0].push(cell);
        }
    }

    let mut compacted_cells = Vec::with_capacity(row_cells.len());
    let mut compacted_bounds = Vec::with_capacity(row_bounds.len());
    let mut compacted_header_rows = 0;
    for (row_index, mut cells) in row_cells.into_iter().enumerate() {
        let removed =
            row_index < header_rows && cells.iter().all(|cell| cell.text.trim().is_empty());
        if removed {
            continue;
        }
        let new_row = compacted_cells.len() as i64;
        for cell in &mut cells {
            cell.row = new_row;
        }
        if row_index < header_rows {
            compacted_header_rows += 1;
        }
        compacted_bounds.push(row_bounds[row_index]);
        compacted_cells.push(cells);
    }
    (compacted_cells, compacted_bounds, compacted_header_rows)
}

pub fn infer_english_columns(input: &EnglishGridInput) -> Vec<ColumnBandDto> {
    if input.words.is_empty() {
        return Vec::new();
    }

    let rows = cluster_word_rows(&input.words, 3.5);
    let mut row_segments: Vec<(f64, Vec<(f64, f64)>)> = Vec::new();
    for (row_y, mut row_words) in rows {
        row_words.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut segments = Vec::new();
        let mut current: Vec<&WordDto> = Vec::new();
        for word in row_words {
            let starts_currency = is_currency_token(&word.text);
            let starts_percentage = is_percentage_token(&word.text);
            let joins = current.last().map(|previous| {
                let gap = word.rect.x0 - previous.rect.x1;
                gap <= 6.0
                    && !(starts_currency && !is_currency_token(&previous.text))
                    && !(starts_percentage && gap > 2.0 && !is_percentage_token(&previous.text))
            });
            if !joins.unwrap_or(false) && !current.is_empty() {
                segments.push((
                    current
                        .iter()
                        .map(|item| item.rect.x0)
                        .fold(f64::INFINITY, f64::min),
                    current
                        .iter()
                        .map(|item| item.rect.x1)
                        .fold(f64::NEG_INFINITY, f64::max),
                ));
                current.clear();
            }
            current.push(word);
        }
        if !current.is_empty() {
            segments.push((
                current
                    .iter()
                    .map(|item| item.rect.x0)
                    .fold(f64::INFINITY, f64::min),
                current
                    .iter()
                    .map(|item| item.rect.x1)
                    .fold(f64::NEG_INFINITY, f64::max),
            ));
        }
        row_segments.push((row_y, segments));
    }

    let mut line_segments = Vec::new();
    for (row_y, segments) in &row_segments {
        for segment in segments {
            let spans_two_columns_in_two_rows =
                row_segments.iter().any(|(other_y, other_segments)| {
                    (other_y - row_y).abs() >= 1e-4
                        && other_segments
                            .iter()
                            .filter(|other| {
                                (segment.1.min(other.1) - segment.0.max(other.0)) >= 2.0
                            })
                            .count()
                            >= 2
                });
            if !spans_two_columns_in_two_rows {
                line_segments.push(*segment);
            }
        }
    }

    line_segments.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut col_spans: Vec<(f64, f64)> = Vec::new();
    for segment in line_segments {
        if let Some(last) = col_spans.last_mut() {
            if segment.0 <= last.1 {
                last.1 = last.1.max(segment.1);
                continue;
            }
        }
        col_spans.push(segment);
    }

    let min_word_x = input
        .words
        .iter()
        .map(|word| word.rect.x0)
        .fold(f64::INFINITY, f64::min);
    let max_word_x = input
        .words
        .iter()
        .map(|word| word.rect.x1)
        .fold(f64::NEG_INFINITY, f64::max);
    let table_x0 = if input.region.rect.x1 > input.region.rect.x0 {
        input.region.rect.x0
    } else {
        min_word_x
    };
    let table_x1 = if input.region.rect.x1 > input.region.rect.x0 {
        input.region.rect.x1
    } else {
        max_word_x
    };

    if col_spans.len() < 2 {
        return vec![ColumnBandDto {
            schema_version: 1,
            x0: table_x0,
            x1: table_x1,
            source_atoms: Vec::new(),
            order: 0,
        }];
    }

    let mut columns = Vec::new();
    let mut current_x = table_x0;
    for pair in col_spans.windows(2) {
        let mut boundary = if pair[0].1 < pair[1].0 {
            (pair[0].1 + pair[1].0) / 2.0
        } else {
            pair[0].1 + 1.5
        };
        boundary = boundary.max(current_x).min(table_x1);
        if boundary > current_x + 1e-6 {
            columns.push((current_x, boundary));
            current_x = boundary;
        }
    }
    if table_x1 > current_x + 1e-6 {
        columns.push((current_x, table_x1));
    }

    columns = prune_english_columns(columns, &input.words, table_x0, table_x1);

    for dollar in input.words.iter().filter(|word| word.text.trim() == "$") {
        let row_words = cluster_word_rows(&input.words, 3.5)
            .into_iter()
            .find(|(_, words)| words.iter().any(|word| std::ptr::eq(*word, dollar)))
            .map(|(_, words)| words)
            .unwrap_or_default();
        if !amount_dollar_is_pure(dollar, &row_words) {
            continue;
        }
        if let Some(index) = columns
            .iter()
            .position(|(x0, x1)| *x0 <= dollar.rect.x0 && dollar.rect.x0 < *x1)
        {
            if index > 0 && dollar.rect.x0 > columns[index - 1].0 + 1e-6 {
                let boundary = dollar.rect.x0.min(columns[index].1 - 1e-6);
                columns[index - 1].1 = boundary;
                columns[index].0 = boundary;
            }
        }
    }

    for index in 1..columns.len() {
        let boundary = columns[index].0;
        columns[index - 1].1 = boundary;
    }
    columns.retain(|(x0, x1)| x0 < x1);
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

fn collapse_single_background_header_rows(mut rows: Vec<Vec<CellDto>>, bounds: Vec<(f64, f64)>, header_rows: usize) -> (Vec<Vec<CellDto>>, Vec<(f64, f64)>, usize) {
    if header_rows <= 1 || rows.is_empty() { return (rows, bounds, header_rows); }
    let end = header_rows.min(rows.len());
    let y0 = bounds.first().map(|b| b.0).unwrap_or(0.0);
    let y1 = bounds.get(end.saturating_sub(1)).map(|b| b.1).unwrap_or(y0);
    let mut header = rows[0].clone();
    for row in 1..end {
        for mut child in rows[row].drain(..) {
            if child.text.trim().is_empty() { continue; }
            if let Some(parent) = header.iter_mut().find(|parent| {
                parent.col < child.col + child.colspan && child.col < parent.col + parent.colspan
            }) {
                if !parent.text.trim().is_empty() { parent.text.push(' '); }
                parent.text.push_str(child.text.trim());
                parent.rect.y1 = y1;
            } else {
                child.row = 0; child.rect.y0 = y0; child.rect.y1 = y1; header.push(child);
            }
        }
    }
    for cell in &mut header { cell.row = 0; cell.rect.y0 = y0; cell.rect.y1 = y1; cell.rowspan = 1; }
    let removed = end.saturating_sub(1);
    let mut compacted = vec![header];
    for mut row in rows.into_iter().skip(end) {
        for cell in &mut row { cell.row = cell.row.saturating_sub(removed as i64); }
        compacted.push(row);
    }
    let mut new_bounds = vec![(y0, y1)];
    new_bounds.extend(bounds.into_iter().skip(end));
    (compacted, new_bounds, 1)
}
pub fn build_english_cells(input: &EnglishGridInput) -> Vec<CellDto> {
    if input.words.is_empty() {
        return Vec::new();
    }
    let columns = infer_english_columns(input);
    if columns.is_empty() {
        return Vec::new();
    }

    let row_clusters = cluster_english_rows(input);
    let num_cols = columns.len();
    let row_bounds: Vec<(f64, f64)> = row_clusters
        .iter()
        .map(|(_, words)| {
            (
                words
                    .iter()
                    .map(|word| word.rect.y0)
                    .fold(f64::INFINITY, f64::min),
                words
                    .iter()
                    .map(|word| word.rect.y1)
                    .fold(f64::NEG_INFINITY, f64::max),
            )
        })
        .collect();

    let mut row_cells: Vec<Vec<CellDto>> = Vec::new();
    for (row_index, (_, row_words_ref)) in row_clusters.iter().enumerate() {
        let mut row_words = row_words_ref.clone();
        row_words.sort_by(|a, b| {
            a.rect
                .x0
                .partial_cmp(&b.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut phrases: Vec<Vec<&WordDto>> = Vec::new();
        for word in row_words {
            let joins = phrases
                .last()
                .and_then(|phrase| phrase.last())
                .map(|previous| word.rect.x0 - previous.rect.x1 <= 6.0)
                .unwrap_or(false);
            if joins {
                phrases.last_mut().unwrap().push(word);
            } else {
                phrases.push(vec![word]);
            }
        }

        let mut cells = Vec::new();
        for phrase in phrases {
            let phrase_x0 = phrase
                .iter()
                .map(|word| word.rect.x0)
                .fold(f64::INFINITY, f64::min);
            let phrase_x1 = phrase
                .iter()
                .map(|word| word.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max);
            let covered_cols: Vec<usize> = columns
                .iter()
                .enumerate()
                .filter(|(_, column)| (phrase_x1.min(column.x1) - phrase_x0.max(column.x0)) >= 2.0)
                .map(|(index, _)| index)
                .collect();
            if covered_cols.is_empty() {
                continue;
            }
            let start_col = *covered_cols.first().unwrap();
            let end_col = *covered_cols.last().unwrap();
            let center =
                phrase.iter().map(|word| center_x(&word.rect)).sum::<f64>() / phrase.len() as f64;
            let (start_col, end_col) = if covered_cols.len() >= 2 {
                (start_col, end_col)
            } else {
                let assigned = columns
                    .iter()
                    .enumerate()
                    .find(|(_, column)| column.x0 <= center && center < column.x1)
                    .map(|(index, _)| index)
                    .unwrap_or(num_cols - 1);
                (assigned, assigned)
            };
            let text = phrase
                .iter()
                .map(|word| word.text.trim())
                .filter(|text| !text.is_empty())
                .collect::<Vec<_>>()
                .join(" ")
                .replace("$ ", "$")
                .replace("% ", "%");
            cells.push(make_english_cell(
                text,
                row_index,
                start_col,
                columns[start_col].x0,
                row_bounds[row_index].0,
                columns[end_col].x1,
                row_bounds[row_index].1,
                1,
                end_col - start_col + 1,
            ));
        }
        cells.sort_by_key(|cell| (cell.col, cell.text.clone()));
        row_cells.push(cells);
    }

    let header_end = input
        .backgrounds
        .iter()
        .take_while(|background| background.color.is_none())
        .map(|background| background.rect.y1)
        .last();
    let header_rows = header_end
        .map(|end| {
            row_bounds
                .iter()
                .take_while(|(y0, _)| *y0 <= end + 2.0)
                .count()
        })
        .unwrap_or(0)
        .min(row_cells.len());

    let source_header_rows = header_rows;
    let background_header_rows = input
        .backgrounds
        .iter()
        .take_while(|background| background.color.is_none())
        .count();
    let header_row_groups: Vec<usize> = row_bounds
        .iter()
        .enumerate()
        .map(|(row, (y0, y1))| {
            let center = (y0 + y1) / 2.0;
            input
                .backgrounds
                .iter()
                .enumerate()
                .take_while(|(_, background)| background.color.is_none())
                .find(|(_, background)| {
                    center >= background.rect.y0 - 0.01 && center <= background.rect.y1 + 0.01
                })
                .map(|(index, _)| index)
                .unwrap_or(input.backgrounds.len() + row)
        })
        .collect();
    let (mut row_cells, mut row_bounds, mut header_rows) =
        compress_english_header_rows(row_cells, row_bounds, header_rows, &header_row_groups);
    if background_header_rows == 1 && header_rows >= 2 && !row_cells[0].iter().any(|cell| cell.col == 0 && !cell.text.trim().is_empty()) {
        (row_cells, row_bounds, header_rows) =
            collapse_single_background_header_rows(row_cells, row_bounds, header_rows);
    }

    for row_index in 0..header_rows {
        for cell_index in 0..row_cells[row_index].len() {
            let mut rowspan = 1usize;
            let col_start = row_cells[row_index][cell_index].col as usize;
            let col_end = col_start + row_cells[row_index][cell_index].colspan as usize;
            while row_index + rowspan < header_rows {
                let occupied_by_child = row_cells[row_index + rowspan].iter().any(|child| {
                    let child_start = child.col as usize;
                    let child_end = child_start + child.colspan as usize;
                    !child.text.trim().is_empty() && child_start < col_end && child_end > col_start
                });
                if occupied_by_child {
                    break;
                }
                rowspan += 1;
            }
            if rowspan > 1 {
                row_cells[row_index][cell_index].rowspan = rowspan as i64;
                row_cells[row_index][cell_index].rect.y1 = row_bounds[row_index + rowspan - 1].1;
            }
        }
    }

    let mut cells = row_cells.into_iter().flatten().collect::<Vec<_>>();
    for row in 0..row_bounds.len() {
        for col in 0..num_cols {
            let occupied = cells.iter().any(|cell| {
                let row_start = cell.row as usize;
                let row_end = row_start + cell.rowspan as usize;
                let col_start = cell.col as usize;
                let col_end = col_start + cell.colspan as usize;
                row_start <= row && row < row_end && col_start <= col && col < col_end
            });
            if !occupied {
                cells.push(make_english_cell(
                    String::new(),
                    row,
                    col,
                    columns[col].x0,
                    row_bounds[row].0,
                    columns[col].x1,
                    row_bounds[row].1,
                    1,
                    1,
                ));
            }
        }
    }

    // Python closes the physical rows into a table grid after header
    // normalization: the region edges are the outer bounds and every inner
    // edge is the midpoint between adjacent row intervals.  Word bboxes are
    // only used to discover rows; using them directly here makes a Rust Cell
    // stop at the glyphs instead of at the same logical row boundary as
    // Python, especially for zebra/general wireless tables.
    let mut row_intervals = Vec::with_capacity(row_bounds.len());
    for row in 0..header_rows {
        if let Some(background) = input.backgrounds.get(row) {
            row_intervals.push((background.rect.y0, background.rect.y1));
        } else if let Some(bounds) = row_bounds.get(row) {
            row_intervals.push(*bounds);
        }
    }
    for row in header_rows..row_bounds.len() {
        let source_row = if input.backgrounds.is_empty() {
            source_header_rows.saturating_add(row - header_rows)
        } else {
            background_header_rows.saturating_add(row - header_rows)
        };
        if let Some(background) = input.backgrounds.get(source_row) {
            row_intervals.push((background.rect.y0, background.rect.y1));
        } else if let Some(bounds) = row_bounds.get(row) {
            row_intervals.push(*bounds);
        }
    }
    if row_intervals.len() != row_bounds.len() {
        row_intervals = row_bounds.clone();
    }

    let round_tenth = |value: f64| (value * 10.0).round() / 10.0;
    let mut row_edges = vec![input.region.rect.y0];
    for pair in row_intervals.windows(2) {
        let midpoint = (pair[0].1 + pair[1].0) / 2.0;
        let minimum = row_edges.last().copied().unwrap_or(input.region.rect.y0) + 2.0;
        let snapped = input
            .horizontal_lines
            .iter()
            .copied()
            .filter(|line| *line >= minimum && (*line - midpoint).abs() <= 4.0)
            .min_by(|left, right| {
                (left - midpoint)
                    .abs()
                    .partial_cmp(&(right - midpoint).abs())
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .unwrap_or(midpoint.max(minimum));
        row_edges.push(round_tenth(snapped));
    }
    row_edges.push(round_tenth(input.region.rect.y1));

    for cell in &mut cells {
        let row = cell.row.max(0) as usize;
        let end_row = row.saturating_add(cell.rowspan.max(1) as usize);
        if row < row_edges.len().saturating_sub(1) && end_row < row_edges.len() {
            cell.rect.y0 = row_edges[row];
            cell.rect.y1 = row_edges[end_row];
        }
    }

    cells.sort_by(|a, b| {
        (a.row, a.col)
            .cmp(&(b.row, b.col))
            .then_with(|| a.text.cmp(&b.text))
    });
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
            horizontal_lines: Vec::new(),
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

    #[test]
    fn test_infer_english_columns_keeps_intermediate_percentage_column_without_empty_band() {
        let words = vec![
            make_word("Revenue", 10.0, 10.0, 55.0, 20.0),
            make_word("12%", 105.0, 10.0, 130.0, 20.0),
            make_word("$", 205.0, 10.0, 210.0, 20.0),
            make_word("1,000", 213.0, 10.0, 250.0, 20.0),
            make_word("Margin", 10.0, 30.0, 55.0, 40.0),
            make_word("8%", 105.0, 30.0, 125.0, 40.0),
            make_word("$", 205.0, 30.0, 210.0, 40.0),
            make_word("900", 213.0, 30.0, 245.0, 40.0),
        ];
        let input = EnglishGridInput {
            schema_version: 1,
            region: crate::types::RegionDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: 0.0,
                    y0: 0.0,
                    x1: 300.0,
                    y1: 50.0,
                },
                source_order: 0,
                allowed: true,
            },
            words,
            backgrounds: Vec::new(),
            horizontal_lines: Vec::new(),
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

        assert_eq!(cols.len(), 3);
        for pair in cols.windows(2) {
            assert!(pair[0].x0 < pair[0].x1);
            assert!(pair[0].x1 <= pair[1].x0);
        }
        assert!(cols[1].x0 < 105.0);
        assert_eq!(cols[1].x1, 205.0);
        assert_eq!(cols[2].x0, 205.0);
    }

    #[test]
    fn test_build_english_cells_restores_header_spans_rowspan_and_empty_slots() {
        let input = EnglishGridInput {
            schema_version: 1,
            region: crate::types::RegionDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: 0.0,
                    y0: 0.0,
                    x1: 240.0,
                    y1: 50.0,
                },
                source_order: 0,
                allowed: true,
            },
            words: vec![
                make_word("Item", 10.0, 5.0, 45.0, 15.0),
                make_word("Portfolio", 100.0, 5.0, 195.0, 15.0),
                make_word("Amount", 100.0, 22.0, 135.0, 32.0),
                make_word("Rate", 165.0, 22.0, 195.0, 32.0),
                make_word("Alpha", 10.0, 39.0, 45.0, 49.0),
                make_word("100", 100.0, 39.0, 130.0, 49.0),
            ],
            backgrounds: vec![
                make_bg(0.0, 18.0, None, 0),
                make_bg(18.0, 35.0, None, 1),
                make_bg(35.0, 50.0, Some(0.5), 2),
            ],
            horizontal_lines: Vec::new(),
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let cells = build_english_cells(&input);

        let item = cells
            .iter()
            .find(|cell| cell.text == "Item")
            .expect("label header cell");
        let portfolio = cells
            .iter()
            .find(|cell| cell.text == "Portfolio")
            .expect("group header cell");
        assert_eq!(
            (item.row, item.col, item.rowspan, item.colspan),
            (0, 0, 2, 1)
        );
        assert_eq!((item.rect.y0, item.rect.y1), (0.0, 35.0));
        assert_eq!(
            (
                portfolio.row,
                portfolio.col,
                portfolio.rowspan,
                portfolio.colspan
            ),
            (0, 1, 1, 2)
        );
        assert_eq!((portfolio.rect.y0, portfolio.rect.y1), (0.0, 18.0));

        let occupied = cells
            .iter()
            .flat_map(|cell| {
                (cell.row..cell.row + cell.rowspan).flat_map(move |row| {
                    (cell.col..cell.col + cell.colspan).map(move |col| (row, col))
                })
            })
            .collect::<std::collections::HashSet<_>>();
        assert_eq!(occupied.len(), 9);
        assert!(cells
            .iter()
            .any(|cell| cell.text.is_empty() && cell.row == 2 && cell.col == 2));
    }

    #[test]
    fn test_build_english_cells_compresses_same_span_wrapped_header_rows() {
        let input = EnglishGridInput {
            schema_version: 1,
            region: crate::types::RegionDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: 0.0,
                    y0: 0.0,
                    x1: 240.0,
                    y1: 70.0,
                },
                source_order: 0,
                allowed: true,
            },
            words: vec![
                make_word("Item", 10.0, 5.0, 45.0, 15.0),
                make_word("Interest", 100.0, 5.0, 140.0, 15.0),
                make_word("Variance", 100.0, 20.0, 145.0, 30.0),
                make_word("Amount", 100.0, 35.0, 130.0, 45.0),
                make_word("Rate", 160.0, 35.0, 190.0, 45.0),
                make_word("Alpha", 10.0, 50.0, 45.0, 60.0),
                make_word("100", 100.0, 50.0, 130.0, 60.0),
                make_word("5%", 160.0, 50.0, 180.0, 60.0),
            ],
            backgrounds: vec![
                make_bg(0.0, 47.0, None, 0),
                make_bg(47.0, 65.0, Some(0.5), 1),
            ],
            horizontal_lines: Vec::new(),
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let cells = build_english_cells(&input);

        assert!(cells.iter().any(|cell| cell.text == "Interest Variance"));
        assert!(!cells.iter().any(|cell| cell.text == "Variance"));
        assert_eq!(
            cells
                .iter()
                .map(|cell| cell.row)
                .max()
                .expect("non-empty cells"),
            2
        );
        let occupied = cells
            .iter()
            .flat_map(|cell| {
                (cell.row..cell.row + cell.rowspan).flat_map(move |row| {
                    (cell.col..cell.col + cell.colspan).map(move |col| (row, col))
                })
            })
            .collect::<std::collections::HashSet<_>>();
        assert_eq!(occupied.len(), 9);
    }

    #[test]
    fn test_merge_wrapped_header_rows_skips_cleared_intermediate_rows() {
        let mut rows = vec![
            vec![make_english_cell(
                "Three months".to_string(),
                0,
                1,
                0.0,
                0.0,
                100.0,
                10.0,
                1,
                1,
            )],
            vec![make_english_cell(
                "ended".to_string(),
                1,
                1,
                0.0,
                10.0,
                100.0,
                20.0,
                1,
                1,
            )],
            vec![make_english_cell(
                "31 Mar 2011".to_string(),
                2,
                1,
                0.0,
                20.0,
                100.0,
                30.0,
                1,
                1,
            )],
            vec![make_english_cell(
                "$m".to_string(),
                3,
                1,
                0.0,
                30.0,
                100.0,
                40.0,
                1,
                1,
            )],
        ];

        merge_wrapped_header_rows(&mut rows, 4, &[]);

        assert_eq!(rows[0][0].text, "Three months ended 31 Mar 2011 $m");
        assert!(rows[1][0].text.is_empty());
        assert!(rows[2][0].text.is_empty());
        assert!(rows[3][0].text.is_empty());
    }

    #[test]
    fn test_compress_english_header_rows_promotes_isolated_bottom_header() {
        let rows = vec![
            vec![make_english_cell(
                "Three months".to_string(),
                0,
                1,
                0.0,
                0.0,
                100.0,
                10.0,
                1,
                1,
            )],
            vec![make_english_cell(
                "ended".to_string(),
                1,
                1,
                0.0,
                10.0,
                100.0,
                20.0,
                1,
                1,
            )],
            vec![make_english_cell(
                "31 Mar 2011".to_string(),
                2,
                1,
                0.0,
                20.0,
                100.0,
                30.0,
                1,
                1,
            )],
            vec![
                make_english_cell("$m".to_string(), 3, 1, 0.0, 30.0, 100.0, 40.0, 1, 1),
                make_english_cell("Change".to_string(), 3, 3, 200.0, 30.0, 300.0, 40.0, 1, 1),
            ],
        ];
        let (compacted, bounds, compacted_header_rows) = compress_english_header_rows(
            rows,
            vec![(0.0, 10.0), (10.0, 20.0), (20.0, 30.0), (30.0, 40.0)],
            4,
            &[],
        );

        assert_eq!(compacted_header_rows, 1);
        assert_eq!(bounds.len(), 1);
        assert!(compacted[0].iter().any(|cell| cell.text == "Change"));
    }

    #[test]
    fn test_build_english_cells_snaps_row_edge_to_horizontal_line() {
        let input = EnglishGridInput {
            schema_version: 1,
            region: crate::types::RegionDto {
                schema_version: 1,
                rect: Rect4 {
                    schema_version: 1,
                    x0: 0.0,
                    y0: 0.0,
                    x1: 180.0,
                    y1: 55.0,
                },
                source_order: 0,
                allowed: true,
            },
            words: vec![
                make_word("A", 10.0, 5.0, 30.0, 15.0),
                make_word("100", 100.0, 5.0, 130.0, 15.0),
                make_word("B", 10.0, 20.0, 30.0, 30.0),
                make_word("200", 100.0, 20.0, 130.0, 30.0),
                make_word("C", 10.0, 38.0, 30.0, 48.0),
                make_word("300", 100.0, 38.0, 130.0, 48.0),
            ],
            backgrounds: Vec::new(),
            horizontal_lines: vec![17.0],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let cells = build_english_cells(&input);
        let second_row = cells
            .iter()
            .find(|cell| cell.text == "B")
            .expect("second-row label cell");
        assert_eq!(second_row.rect.y0, 17.0);
    }
}
