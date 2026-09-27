use crate::types::{
    CellDto, PersonalCreditInput, PersonalCreditOutput, Rect4, TableCandidateDto,
};

const QUERY_HEADERS: [&str; 4] = ["编号", "查询日期", "查询机构", "查询原因"];
const QUERY_TITLES: [&str; 3] = ["机构查询记录明细", "个人查询记录明细", "本人查询记录明细"];

#[derive(Clone)]
struct QueryItem {
    text: String,
    rect: Rect4,
    order: i64,
}

fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> Rect4 {
    Rect4 {
        schema_version: 1,
        x0,
        y0,
        x1,
        y1,
    }
}

fn union_rect<'a>(items: impl IntoIterator<Item = &'a Rect4>) -> Option<Rect4> {
    let mut values = items.into_iter();
    let first = values.next()?;
    let mut result = first.clone();
    for value in values {
        result.x0 = result.x0.min(value.x0);
        result.y0 = result.y0.min(value.y0);
        result.x1 = result.x1.max(value.x1);
        result.y1 = result.y1.max(value.y1);
    }
    Some(result)
}

fn flush_character_run(run: &mut Vec<&crate::types::CharacterDto>, output: &mut Vec<QueryItem>) {
    if run.is_empty() {
        return;
    }
    let text = run.iter().map(|character| character.text.as_str()).collect();
    let bounds = union_rect(run.iter().map(|character| &character.rect)).unwrap();
    let order = run[0].order;
    output.push(QueryItem {
        text,
        rect: bounds,
        order,
    });
    run.clear();
}

fn query_items(input: &PersonalCreditInput) -> Vec<QueryItem> {
    let mut items = Vec::new();
    for span in &input.snapshot.spans {
        let mut run = Vec::new();
        for character in &span.span.characters {
            if character.text.chars().all(char::is_whitespace) {
                flush_character_run(&mut run, &mut items);
            } else {
                run.push(character);
            }
        }
        flush_character_run(&mut run, &mut items);
    }

    if items.is_empty() {
        items.extend(input.snapshot.words.iter().filter_map(|word| {
            let text = word.text.trim();
            (!text.is_empty()).then(|| QueryItem {
                text: text.to_string(),
                rect: word.rect.clone(),
                order: word.order,
            })
        }));
    }
    items.sort_by_key(|item| item.order);
    items
}

fn center_x(rect: &Rect4) -> f64 {
    (rect.x0 + rect.x1) / 2.0
}

fn center_y(rect: &Rect4) -> f64 {
    (rect.y0 + rect.y1) / 2.0
}

fn query_rows(items: &[QueryItem]) -> Vec<Vec<QueryItem>> {
    let mut rows: Vec<Vec<QueryItem>> = Vec::new();
    for item in items {
        let center = center_y(&item.rect);
        if let Some(row) = rows.iter_mut().find(|row| {
            let reference = center_y(&row[0].rect);
            (reference - center).abs() <= 4.5
        }) {
            row.push(item.clone());
        } else {
            rows.push(vec![item.clone()]);
        }
    }
    for row in &mut rows {
        row.sort_by(|left, right| {
            left.rect
                .x0
                .partial_cmp(&right.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    }
    rows.sort_by(|left, right| {
        left[0]
            .rect
            .y0
            .partial_cmp(&right[0].rect.y0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    rows
}

fn row_text(row: &[QueryItem]) -> String {
    row.iter().map(|item| item.text.as_str()).collect()
}

fn has_all_headers(text: &str) -> bool {
    QUERY_HEADERS.iter().all(|header| text.contains(header))
}

fn is_query_title(text: &str) -> bool {
    QUERY_TITLES.iter().any(|title| text.contains(title))
}

fn digits_only(text: &str) -> bool {
    !text.is_empty() && text.chars().all(|character| character.is_ascii_digit())
}

fn is_query_record(row: &[QueryItem]) -> bool {
    let has_number = row
        .iter()
        .any(|item| item.rect.x0 < 110.0 && digits_only(item.text.trim()));
    let has_date = row
        .iter()
        .any(|item| item.rect.x0 < 240.0 && item.text.contains('年'));
    let has_reason = row.iter().any(|item| item.rect.x0 >= 340.0);
    has_number && has_date && has_reason
}

fn column_for_item(item: &QueryItem, boundaries: &[f64; 3]) -> usize {
    let center = center_x(&item.rect);
    if digits_only(item.text.trim()) && item.rect.x0 < boundaries[0] {
        0
    } else if center < boundaries[0] {
        0
    } else if center < boundaries[1] {
        1
    } else if center < boundaries[2] {
        2
    } else {
        3
    }
}

fn join_query_items(items: &[QueryItem]) -> String {
    let mut result = String::new();
    for (index, item) in items.iter().enumerate() {
        if index > 0 {
            let previous = &items[index - 1];
            if previous.text.ends_with(' ') || item.text.starts_with(' ') {
                result.push_str(&item.text);
                continue;
            }
            if item.rect.x0 - previous.rect.x1 > 1.0 {
                result.push(' ');
            }
        }
        result.push_str(&item.text);
    }
    normalize_date_spacing(&result)
}

fn normalize_date_spacing(text: &str) -> String {
    let characters: Vec<char> = text.chars().collect();
    let mut result = String::with_capacity(text.len());
    let mut index = 0;
    while index < characters.len() {
        if characters[index].is_whitespace()
            && result.chars().last().is_some_and(|character| character.is_ascii_digit())
        {
            let mut next = index;
            while next < characters.len() && characters[next].is_whitespace() {
                next += 1;
            }
            let is_year = next + 3 < characters.len()
                && characters[next..next + 3]
                    .iter()
                    .all(|character| character.is_ascii_digit())
                && characters[next + 3] == '年';
            if is_year {
                index = next;
                continue;
            }
        }
        result.push(characters[index]);
        index += 1;
    }
    result
}

fn cell(text: String, row: i64, col: i64, rect: Rect4, colspan: i64) -> CellDto {
    CellDto {
        schema_version: 1,
        text,
        row,
        col,
        rect,
        rowspan: 1,
        colspan,
        source: None,
    }
}

fn candidate_from_cells(cells: Vec<CellDto>, rows: i64, source: &str) -> Option<TableCandidateDto> {
    let bounds = union_rect(cells.iter().map(|cell| &cell.rect))?;
    Some(TableCandidateDto {
        schema_version: 1,
        rect: bounds,
        source: source.to_string(),
        confidence: Some(0.95),
        rows,
        cols: 4,
        cells,
    })
}

fn recover_query_table(
    rows: &[Vec<QueryItem>],
    header_index: usize,
    end_index: usize,
    section_index: Option<usize>,
    page_width: f64,
) -> Option<TableCandidateDto> {
    let header_row = rows.get(header_index)?;
    let mut header_items: [Vec<QueryItem>; 4] = std::array::from_fn(|_| Vec::new());
    for item in header_row {
        let center = center_x(&item.rect);
        let column = if center < 105.0 {
            0
        } else if center < 240.0 {
            1
        } else if center < 440.0 {
            2
        } else {
            3
        };
        header_items[column].push(item.clone());
    }
    let header_cells: Vec<CellDto> = (0..4)
        .filter_map(|column| {
            let bounds = union_rect(header_items[column].iter().map(|item| &item.rect))?;
            Some(cell(
                QUERY_HEADERS[column].to_string(),
                0,
                column as i64,
                bounds,
                1,
            ))
        })
        .collect();

    let boundaries = if header_cells.len() == 4 {
        let mut centers: Vec<f64> = header_cells.iter().map(|item| center_x(&item.rect)).collect();
        centers.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
        [
            (centers[0] + centers[1]) / 2.0,
            (centers[1] + centers[2]) / 2.0,
            (centers[2] + centers[3]) / 2.0,
        ]
    } else {
        [105.0, 240.0, 440.0]
    };

    let section_row = section_index.and_then(|index| rows.get(index));
    let section_text = section_row.map(|row| row_text(row));
    let section_rect = section_row.and_then(|row| union_rect(row.iter().map(|item| &item.rect)));
    let has_section_title = section_text.as_deref().is_some_and(is_query_title);
    let mut merged_rows: Vec<Vec<QueryItem>> = rows
        .iter()
        .filter(|row| {
            row.iter().any(|item| {
                let center_y = center_y(&item.rect);
                let top = section_rect
                    .as_ref()
                    .map(|rect| rect.y0)
                    .unwrap_or_else(|| rows[header_index][0].rect.y0);
                let bottom = rows
                    .get(end_index.saturating_sub(1))
                    .and_then(|last| union_rect(last.iter().map(|item| &item.rect)))
                    .map(|rect| rect.y1)
                    .unwrap_or(f64::NEG_INFINITY);
                top <= center_y && center_y <= bottom
            })
        })
        .cloned()
        .collect();
    merged_rows.sort_by(|left, right| {
        left[0]
            .rect
            .y0
            .partial_cmp(&right[0].rect.y0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let merged_header = merged_rows.iter().position(|row| has_all_headers(&row_text(row)))?;

    let mut recovered_rows = Vec::new();
    for row in merged_rows.iter().skip(merged_header + 1) {
        let text = row_text(row);
        if text.contains('页') && text.contains('第') {
            break;
        }
        if is_query_record(row) {
            recovered_rows.push(row.clone());
        } else if !recovered_rows.is_empty()
            && row.iter().any(|item| center_x(&item.rect) >= boundaries[1])
        {
            recovered_rows.push(row.clone());
        }
    }

    let section_title = section_text.filter(|text| is_query_title(text));
    if recovered_rows.is_empty() {
        if !has_section_title || header_cells.len() != 4 {
            return None;
        }
        let (Some(title), Some(section_box), Some(header_box)) = (
            section_title,
            section_rect,
            union_rect(header_cells.iter().map(|cell| &cell.rect)),
        ) else {
            return None;
        };
        let mut cells = vec![cell(
            title,
            0,
            0,
            rect(header_box.x0, section_box.y0, header_box.x1, section_box.y1),
            4,
        )];
        for mut header in header_cells {
            header.row = 1;
            cells.push(header);
        }
        return candidate_from_cells(cells, 2, "personal_query_recovery");
    }

    let mut cells = Vec::new();
    let mut current_row = 0_i64;
    if let (Some(title), Some(section_box)) = (section_title, section_rect) {
        let mut title_x0 = recovered_rows
            .iter()
            .flat_map(|row| row.iter().map(|item| item.rect.x0))
            .fold(f64::INFINITY, f64::min);
        let mut title_x1 = recovered_rows
            .iter()
            .flat_map(|row| row.iter().map(|item| item.rect.x1))
            .fold(f64::NEG_INFINITY, f64::max);
        if let Some(header_box) = union_rect(header_cells.iter().map(|cell| &cell.rect)) {
            title_x0 = title_x0.min(header_box.x0);
            title_x1 = title_x1.max(header_box.x1);
        }
        cells.push(cell(
            title,
            0,
            0,
            rect(title_x0, section_box.y0, title_x1, section_box.y1),
            4,
        ));
        current_row = 1;
    }
    for mut header in header_cells {
        header.row = current_row;
        cells.push(header);
    }
    current_row += 1;

    for row in recovered_rows {
        let mut by_column: [Vec<QueryItem>; 4] = std::array::from_fn(|_| Vec::new());
        for item in row {
            let column = column_for_item(&item, &boundaries);
            by_column[column].push(item);
        }

        if by_column[0].is_empty() {
            if current_row <= 1 {
                continue;
            }
            for column in [2, 3] {
                if by_column[column].is_empty() {
                    continue;
                }
                let continuation = join_query_items(&by_column[column]);
                if let Some(previous) = cells
                    .iter_mut()
                    .rev()
                    .find(|cell| cell.row == current_row - 1 && cell.col == column as i64)
                {
                    previous.text.push_str(&continuation);
                    if let Some(bounds) = union_rect(by_column[column].iter().map(|item| &item.rect)) {
                        previous.rect.x1 = previous.rect.x1.max(bounds.x1);
                        previous.rect.y1 = previous.rect.y1.max(bounds.y1);
                    }
                }
            }
            continue;
        }

        let row_box = union_rect(by_column.iter().flatten().map(|item| &item.rect))?;
        for column in 0..4 {
            if by_column[column].is_empty() {
                let x0 = if column == 0 { 0.0 } else { boundaries[column - 1] };
                let x1 = if column < 3 { boundaries[column] } else { page_width };
                cells.push(cell(
                    String::new(),
                    current_row,
                    column as i64,
                    rect(x0, row_box.y0, x1, row_box.y1),
                    1,
                ));
            } else {
                let bounds = union_rect(by_column[column].iter().map(|item| &item.rect))?;
                cells.push(cell(
                    join_query_items(&by_column[column]),
                    current_row,
                    column as i64,
                    bounds,
                    1,
                ));
            }
        }
        current_row += 1;
    }

    let minimum_rows = if has_section_title { 3 } else { 2 };
    if current_row < minimum_rows {
        return None;
    }
    let retain_through = if cells.first().is_some_and(|cell| cell.colspan == 4) {
        1
    } else {
        0
    };
    cells.retain(|cell| !cell.text.is_empty() || cell.row <= retain_through);
    candidate_from_cells(cells, current_row, "personal_query_recovery")
}

fn recover_headerless_query_table(
    rows: &[Vec<QueryItem>],
    page_width: f64,
) -> Option<TableCandidateDto> {
    let record_indices: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter_map(|(index, row)| is_query_record(row).then_some(index))
        .collect();
    let start_index = *record_indices.first()?;
    let last_record = *record_indices.last()?;
    let mut actual_end = last_record + 1;
    while actual_end < rows.len() {
        let row = &rows[actual_end];
        let text = row_text_without_ascii_spaces(row);
        if (text.contains('页') && text.contains('第')) || is_query_title(&text) {
            break;
        }
        if row.iter().any(|item| center_x(&item.rect) >= 220.0) {
            actual_end += 1;
        } else {
            break;
        }
    }

    let selected_rows = &rows[start_index..actual_end];
    let mut recovered_rows = Vec::new();
    for row in selected_rows.iter().skip(start_index) {
        let text = row_text(row);
        if text.contains('页') && text.contains('第') {
            break;
        }
        if is_query_record(row) {
            recovered_rows.push(row.clone());
        } else if !recovered_rows.is_empty()
            && row.iter().any(|item| center_x(&item.rect) >= 240.0)
        {
            recovered_rows.push(row.clone());
        }
    }
    if !recovered_rows.iter().any(|row| is_query_record(row)) {
        return None;
    }

    let boundaries = [105.0, 240.0, 440.0];
    let mut cells: Vec<CellDto> = Vec::new();
    let mut current_row = 0_i64;
    for row in recovered_rows {
        let mut by_column: [Vec<QueryItem>; 4] = std::array::from_fn(|_| Vec::new());
        for item in row {
            by_column[column_for_item(&item, &boundaries)].push(item);
        }
        if by_column[0].is_empty() {
            if current_row <= 0 {
                continue;
            }
            for column in [2, 3] {
                if by_column[column].is_empty() {
                    continue;
                }
                let continuation = join_query_items(&by_column[column]);
                if let Some(previous) = cells
                    .iter_mut()
                    .rev()
                    .find(|cell| cell.row == current_row - 1 && cell.col == column as i64)
                {
                    previous.text.push_str(&continuation);
                    if let Some(bounds) = union_rect(by_column[column].iter().map(|item| &item.rect)) {
                        previous.rect.x1 = previous.rect.x1.max(bounds.x1);
                        previous.rect.y1 = previous.rect.y1.max(bounds.y1);
                    }
                }
            }
            continue;
        }

        let row_box = union_rect(by_column.iter().flatten().map(|item| &item.rect))?;
        for column in 0..4 {
            if by_column[column].is_empty() {
                let x0 = if column == 0 { 0.0 } else { boundaries[column - 1] };
                let x1 = if column < 3 { boundaries[column] } else { page_width };
                cells.push(cell(
                    String::new(),
                    current_row,
                    column as i64,
                    rect(x0, row_box.y0, x1, row_box.y1),
                    1,
                ));
            } else {
                let bounds = union_rect(by_column[column].iter().map(|item| &item.rect))?;
                cells.push(cell(
                    join_query_items(&by_column[column]),
                    current_row,
                    column as i64,
                    bounds,
                    1,
                ));
            }
        }
        current_row += 1;
    }
    if current_row == 0 {
        return None;
    }
    cells.retain(|cell| !cell.text.is_empty() || cell.row == 0);
    candidate_from_cells(cells, current_row, "personal_query_recovery")
}

fn row_text_without_ascii_spaces(row: &[QueryItem]) -> String {
    row_text(row).replace(' ', "")
}

pub fn recover(input: PersonalCreditInput) -> PersonalCreditOutput {
    let items = query_items(&input);
    let rows = query_rows(&items);
    let header_indices: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter_map(|(index, row)| has_all_headers(&row_text(row)).then_some(index))
        .collect();
    let section_indices: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter_map(|(index, row)| is_query_title(&row_text(row)).then_some(index))
        .collect();

    let mut tables = Vec::new();
    if header_indices.is_empty() {
        if let Some(table) = recover_headerless_query_table(&rows, input.snapshot.page.width) {
            tables.push(table);
        }
    }
    for (position, header_index) in header_indices.iter().copied().enumerate() {
        let previous_header = header_indices[..position].last().copied();
        let section_index = section_indices
            .iter()
            .copied()
            .filter(|index| Some(*index) > previous_header && *index < header_index)
            .last();
        let end_index = rows
            .iter()
            .enumerate()
            .filter(|(index, _)| {
                *index > header_index
                    && (header_indices.contains(index) || section_indices.contains(index))
            })
            .map(|(index, _)| index)
            .min()
            .unwrap_or(rows.len());
        if let Some(table) = recover_query_table(
            &rows,
            header_index,
            end_index,
            section_index,
            input.snapshot.page.width,
        ) {
            tables.push(table);
        }
    }

    tables.sort_by(|left, right| {
        left.rect
            .y0
            .partial_cmp(&right.rect.y0)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    PersonalCreditOutput {
        schema_version: 1,
        tables,
        diagnostics: Vec::new(),
    }
}
