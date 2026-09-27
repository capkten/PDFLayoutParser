use crate::types::{
    CellDto, CharacterDto, DrawingDto, LineDto, NativeSpanDto, OwnedValue, PageDto,
    PageSnapshotDto, PersonalCreditInput, PersonalCreditOutput, Rect4, RegionDto, StructureConfig,
    TableCandidateDto, WiredRegionInput, WirelessRecoveryInput,
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
        has_wired_lines: false,
    })
}

fn finite_number(value: &OwnedValue) -> Option<f64> {
    match value {
        OwnedValue::Integer(value) => Some(*value as f64),
        OwnedValue::Float(value) => Some(*value),
        _ => None,
    }
}

fn item_values(value: &OwnedValue) -> Option<&[OwnedValue]> {
    match value {
        OwnedValue::Array(values) => Some(values),
        _ => None,
    }
}

fn item_name(value: &OwnedValue) -> Option<&str> {
    match value {
        OwnedValue::String(value) => Some(value),
        _ => None,
    }
}

fn item_rect(value: &OwnedValue) -> Option<Rect4> {
    let values = item_values(value)?;
    if values.len() < 4 {
        return None;
    }
    Some(rect(
        finite_number(&values[0])?,
        finite_number(&values[1])?,
        finite_number(&values[2])?,
        finite_number(&values[3])?,
    ))
}

fn clipped_axis_line(
    mut line: Rect4,
    horizontal: bool,
    clip: Option<&Rect4>,
    width: Option<f64>,
    source_order: i64,
    h_lines: &mut Vec<LineDto>,
    v_lines: &mut Vec<LineDto>,
) {
    if let Some(clip) = clip {
        if horizontal {
            if line.y0 < clip.y0 || line.y0 > clip.y1 {
                return;
            }
            line.x0 = line.x0.max(clip.x0);
            line.x1 = line.x1.min(clip.x1);
        } else {
            if line.x0 < clip.x0 || line.x0 > clip.x1 {
                return;
            }
            line.y0 = line.y0.max(clip.y0);
            line.y1 = line.y1.min(clip.y1);
        }
    }
    if (horizontal && line.x1 - line.x0 < 3.0) || (!horizontal && line.y1 - line.y0 < 3.0) {
        return;
    }
    let dto = LineDto {
        schema_version: 1,
        rect: line,
        width,
        color: None,
        source_order,
    };
    if horizontal {
        h_lines.push(dto);
    } else {
        v_lines.push(dto);
    }
}

fn append_rectangle_lines(
    bounds: Rect4,
    clip: Option<&Rect4>,
    width: Option<f64>,
    source_order: i64,
    line_tolerance: f64,
    emit_border: bool,
    h_lines: &mut Vec<LineDto>,
    v_lines: &mut Vec<LineDto>,
) {
    let mut bounds = bounds;
    if let Some(clip) = clip {
        bounds.x0 = bounds.x0.max(clip.x0);
        bounds.y0 = bounds.y0.max(clip.y0);
        bounds.x1 = bounds.x1.min(clip.x1);
        bounds.y1 = bounds.y1.min(clip.y1);
        if bounds.x1 <= bounds.x0 || bounds.y1 <= bounds.y0 {
            return;
        }
    }
    let rect_width = bounds.x1 - bounds.x0;
    let rect_height = bounds.y1 - bounds.y0;
    if rect_height <= line_tolerance && rect_width >= 3.0 {
        let center = (bounds.y0 + bounds.y1) / 2.0;
        clipped_axis_line(
            rect(bounds.x0, center, bounds.x1, center),
            true,
            clip,
            width,
            source_order,
            h_lines,
            v_lines,
        );
    } else if rect_width <= line_tolerance && rect_height >= 3.0 {
        let center = (bounds.x0 + bounds.x1) / 2.0;
        clipped_axis_line(
            rect(center, bounds.y0, center, bounds.y1),
            false,
            clip,
            width,
            source_order,
            h_lines,
            v_lines,
        );
    } else if emit_border && rect_width >= 3.0 && rect_height >= 3.0 {
        for y in [bounds.y0, bounds.y1] {
            clipped_axis_line(
                rect(bounds.x0, y, bounds.x1, y),
                true,
                clip,
                width,
                source_order,
                h_lines,
                v_lines,
            );
        }
        for x in [bounds.x0, bounds.x1] {
            clipped_axis_line(
                rect(x, bounds.y0, x, bounds.y1),
                false,
                clip,
                width,
                source_order,
                h_lines,
                v_lines,
            );
        }
    }
}

fn drawing_lines(
    drawings: &[DrawingDto],
    page: &PageDto,
    line_tolerance: f64,
) -> (Vec<LineDto>, Vec<LineDto>) {
    let page_area = page.width * page.height;
    let mut h_lines = Vec::new();
    let mut v_lines = Vec::new();
    let mut next_source = 0_i64;
    for drawing in drawings {
        if drawing.opacity.is_some_and(|opacity| opacity <= 0.0) {
            continue;
        }
        let clip = drawing.clip.as_ref();
        if drawing.kind == "f" {
            append_rectangle_lines(
                drawing.rect.clone(),
                clip,
                drawing.width,
                next_source,
                line_tolerance,
                false,
                &mut h_lines,
                &mut v_lines,
            );
            next_source += 1;
        }

        if let Some(items) = &drawing.items {
            for item in items {
                let Some(values) = item_values(item) else {
                    continue;
                };
                let Some(kind) = values.first().and_then(item_name) else {
                    continue;
                };
                if kind == "l" && drawing.kind != "f" && values.len() == 3 {
                    let (Some(start), Some(end)) = (item_values(&values[1]), item_values(&values[2])) else {
                        continue;
                    };
                    if start.len() != 2 || end.len() != 2 {
                        continue;
                    }
                    let (Some(x0), Some(y0), Some(x1), Some(y1)) = (
                        finite_number(&start[0]),
                        finite_number(&start[1]),
                        finite_number(&end[0]),
                        finite_number(&end[1]),
                    ) else {
                        continue;
                    };
                    if (y1 - y0).abs() <= line_tolerance && (x1 - x0).abs() >= 3.0 {
                        let y = (y0 + y1) / 2.0;
                        clipped_axis_line(
                            rect(x0.min(x1), y, x0.max(x1), y),
                            true,
                            clip,
                            drawing.width,
                            next_source,
                            &mut h_lines,
                            &mut v_lines,
                        );
                    } else if (x1 - x0).abs() <= line_tolerance && (y1 - y0).abs() >= 3.0 {
                        let x = (x0 + x1) / 2.0;
                        clipped_axis_line(
                            rect(x, y0.min(y1), x, y0.max(y1)),
                            false,
                            clip,
                            drawing.width,
                            next_source,
                            &mut h_lines,
                            &mut v_lines,
                        );
                    }
                } else if kind == "re" && values.len() >= 2 {
                    let Some(bounds) = item_rect(&values[1]) else {
                        continue;
                    };
                    let stroked = drawing.kind == "s"
                        || drawing.kind == "fs"
                        || drawing.color.as_ref().is_some_and(|color| !matches!(color, OwnedValue::Null));
                    let border_area = (bounds.x1 - bounds.x0) * (bounds.y1 - bounds.y0);
                    append_rectangle_lines(
                        bounds,
                        clip,
                        drawing.width,
                        next_source,
                        line_tolerance,
                        stroked && border_area < page_area * 0.5,
                        &mut h_lines,
                        &mut v_lines,
                    );
                }
                next_source += 1;
            }
        } else {
            for line in &drawing.lines {
                if (line.rect.y1 - line.rect.y0).abs() <= line_tolerance {
                    clipped_axis_line(
                        rect(line.rect.x0, line.rect.y0, line.rect.x1, line.rect.y0),
                        true,
                        clip,
                        line.width,
                        next_source,
                        &mut h_lines,
                        &mut v_lines,
                    );
                } else if (line.rect.x1 - line.rect.x0).abs() <= line_tolerance {
                    clipped_axis_line(
                        rect(line.rect.x0, line.rect.y0, line.rect.x0, line.rect.y1),
                        false,
                        clip,
                        line.width,
                        next_source,
                        &mut h_lines,
                        &mut v_lines,
                    );
                }
                next_source += 1;
            }
        }
    }
    (h_lines, v_lines)
}

fn wired_candidates(input: &PersonalCreditInput) -> Vec<TableCandidateDto> {
    let (h_lines, v_lines) = drawing_lines(
        &input.snapshot.drawings,
        &input.snapshot.page,
        input.wired_line_tolerance,
    );
    let output = crate::wired::extract_wired_region(WiredRegionInput {
        schema_version: 1,
        page: input.snapshot.page.clone(),
        h_lines,
        v_lines,
        words: input.snapshot.words.clone(),
        tolerance: input.wired_line_tolerance,
    });
    let characters: Vec<CharacterDto> = input
        .snapshot
        .spans
        .iter()
        .flat_map(|span| span.span.characters.iter().cloned())
        .collect();
    let cells = crate::wired::assign_text_to_line_cells(
        output.cells,
        &input.snapshot.words,
        &characters,
        input.wired_line_tolerance,
    );

    output
        .regions
        .iter()
        .filter_map(|region| {
            let cells: Vec<CellDto> = cells
                .iter()
                .filter(|cell| {
                    let x = center_x(&cell.rect);
                    let y = center_y(&cell.rect);
                    region.rect.x0 <= x
                        && x <= region.rect.x1
                        && region.rect.y0 <= y
                        && y <= region.rect.y1
                })
                .cloned()
                .collect();
            if cells.is_empty() {
                return None;
            }
            let y0 = cells
                .iter()
                .map(|cell| cell.rect.y0)
                .fold(f64::INFINITY, f64::min);
            let y1 = cells
                .iter()
                .map(|cell| cell.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max);
            Some(TableCandidateDto {
                schema_version: 1,
                rect: rect(region.rect.x0, y0, region.rect.x1, y1),
                source: "line_projection".to_string(),
                confidence: Some(0.9),
                rows: cells.iter().map(|cell| cell.row).max().unwrap_or(-1) + 1,
                cols: cells.iter().map(|cell| cell.col).max().unwrap_or(-1) + 1,
                cells,
                has_wired_lines: false,
            })
        })
        .collect()
}

fn wireless_candidates(input: &PersonalCreditInput, wired: &[TableCandidateDto]) -> Vec<TableCandidateDto> {
    let mut regions = input.snapshot.allowed_regions.clone();
    regions.extend(input.snapshot.excluded_regions.clone());
    let first_added_order = regions.len() as i64;
    regions.extend(
        wired
            .iter()
            .filter(|table| table_is_wired(table))
            .map(|table| RegionDto {
                schema_version: 1,
                rect: table.rect.clone(),
                source_order: first_added_order,
                allowed: false,
            }),
    );
    let spans: Vec<NativeSpanDto> = crate::snapshot::collect_native_spans_from_snapshot(
        &input.snapshot,
        None,
        None,
    )
    .into_iter()
    .map(|span| span.span)
    .collect();
    let mut config = StructureConfig::default();
    config.line_tolerance = 2.3;
    crate::wireless_structure::recover_wireless_tables(WirelessRecoveryInput {
        schema_version: 1,
        page: input.snapshot.page.clone(),
        spans,
        regions,
        config,
    })
    .candidates
}

fn tables_overlap(left: &TableCandidateDto, right: &TableCandidateDto) -> bool {
    !(left.rect.x1 < right.rect.x0
        || right.rect.x1 < left.rect.x0
        || left.rect.y1 < right.rect.y0
        || right.rect.y1 < left.rect.y0)
}

fn numbered_row(text: &str) -> bool {
    let characters: Vec<char> = text.chars().collect();
    let digit_count = characters
        .iter()
        .take_while(|character| character.is_ascii_digit())
        .count();
    digit_count > 0
        && characters
            .get(digit_count)
            .is_some_and(|character| *character == '.' || *character == '、')
}

fn is_numbered_prose_candidate(table: &TableCandidateDto) -> bool {
    if table.cols > 2 {
        return false;
    }
    let all_text = table
        .cells
        .iter()
        .map(|cell| cell.text.as_str())
        .collect::<Vec<_>>()
        .join(" ");
    if ["查询原因", "查询机构", "查询日期"]
        .iter()
        .any(|marker| all_text.contains(marker))
    {
        return false;
    }

    let mut rows: std::collections::BTreeMap<i64, Vec<&str>> =
        std::collections::BTreeMap::new();
    for cell in &table.cells {
        let text = cell.text.trim();
        if !text.is_empty() {
            rows.entry(cell.row).or_default().push(text);
        }
    }
    let long_numbered_rows = rows
        .values()
        .filter(|parts| {
            let text = parts.concat();
            numbered_row(&text) && text.chars().count() >= 40
        })
        .count();
    let has_prose_lead = all_text.contains("明细如下");
    (has_prose_lead && long_numbered_rows >= 1) || long_numbered_rows >= 2
}

fn is_report_metadata_candidate(table: &TableCandidateDto) -> bool {
    let text = table
        .cells
        .iter()
        .map(|cell| cell.text.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    ["报告编号", "报告时间", "证件号码", "其他证件信息"]
        .iter()
        .filter(|marker| text.contains(**marker))
        .count()
        >= 2
}

fn trim_query_table(mut table: TableCandidateDto) -> TableCandidateDto {
    let header_row = (0..table.rows).find(|row| {
        let row_text = table
            .cells
            .iter()
            .filter(|cell| cell.row == *row)
            .map(|cell| cell.text.replace(' ', ""))
            .collect::<String>();
        has_all_headers(&row_text)
    });
    let Some(header_row) = header_row else {
        return table;
    };
    if header_row == 0 {
        return table;
    }

    let keep_from_row = if header_row == 1 {
        let first_row = table
            .cells
            .iter()
            .filter(|cell| cell.row == 0)
            .map(|cell| cell.text.replace(' ', ""))
            .collect::<String>();
        if is_query_title(&first_row) {
            0
        } else {
            header_row
        }
    } else {
        header_row
    };
    if keep_from_row == 0 {
        return table;
    }

    table.cells.retain_mut(|cell| {
        if cell.row < keep_from_row {
            return false;
        }
        cell.row -= keep_from_row;
        true
    });
    table.rows -= keep_from_row;
    if let Some(bounds) = union_rect(table.cells.iter().map(|cell| &cell.rect)) {
        table.rect = bounds;
    }
    table
}

fn split_repeated_records(table: TableCandidateDto) -> Vec<TableCandidateDto> {
    let starts: Vec<i64> = table
        .cells
        .iter()
        .filter(|cell| cell.col == 0)
        .filter(|cell| {
            let text = cell.text.trim();
            ["处罚机构", "立案法院", "执行法院"]
                .iter()
                .any(|prefix| text.starts_with(prefix))
        })
        .map(|cell| cell.row)
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    if starts.len() < 2 {
        return vec![table];
    }

    let mut boundaries = vec![0_i64];
    boundaries.extend(starts.iter().skip(1).copied());
    boundaries.push(table.rows);
    boundaries
        .windows(2)
        .filter_map(|range| {
            let start = range[0];
            let end = range[1];
            let cells: Vec<CellDto> = table
                .cells
                .iter()
                .filter(|cell| start <= cell.row && cell.row < end)
                .cloned()
                .map(|mut cell| {
                    cell.row -= start;
                    cell
                })
                .collect();
            let bounds = union_rect(cells.iter().map(|cell| &cell.rect))?;
            Some(TableCandidateDto {
                schema_version: 1,
                rect: bounds,
                source: table.source.clone(),
                confidence: table.confidence,
                rows: end - start,
                cols: table.cols,
                cells,
                has_wired_lines: table.has_wired_lines,
            })
        })
        .collect()
}

fn without_whitespace(text: &str) -> String {
    text.chars().filter(|character| !character.is_whitespace()).collect()
}

fn native_character_bounds(
    cell: &CellDto,
    snapshot: &PageSnapshotDto,
) -> Option<Rect4> {
    if cell.text.trim().is_empty() {
        return None;
    }
    let mut characters: Vec<&CharacterDto> = snapshot
        .spans
        .iter()
        .flat_map(|span| span.span.characters.iter())
        .filter(|character| {
            let x = center_x(&character.rect);
            let y = center_y(&character.rect);
            cell.rect.x0 - 0.5 <= x
                && x <= cell.rect.x1 + 0.5
                && cell.rect.y0 - 0.5 <= y
                && y <= cell.rect.y1 + 0.5
                && !character.text.chars().all(char::is_whitespace)
        })
        .collect();
    characters.sort_by_key(|character| character.order);
    let text: String = characters
        .iter()
        .map(|character| character.text.as_str())
        .collect();
    if without_whitespace(&text) != without_whitespace(&cell.text) {
        return None;
    }
    union_rect(characters.iter().map(|character| &character.rect))
}

fn rounded_rect(mut bounds: Rect4) -> Rect4 {
    bounds.x0 = crate::geometry::round_one_decimal(bounds.x0);
    bounds.y0 = crate::geometry::round_one_decimal(bounds.y0);
    bounds.x1 = crate::geometry::round_one_decimal(bounds.x1);
    bounds.y1 = crate::geometry::round_one_decimal(bounds.y1);
    bounds
}

fn round_grid_boundary(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

fn normalize_wireless_cell_geometry(
    mut table: TableCandidateDto,
    snapshot: &PageSnapshotDto,
) -> TableCandidateDto {
    if table.source != "wireless_span_recovery" || table.rows <= 0 || table.cols <= 0 {
        return table;
    }
    let precise_bounds: Vec<Option<Rect4>> = table
        .cells
        .iter()
        .map(|cell| native_character_bounds(cell, snapshot))
        .collect();
    for (cell, bounds) in table.cells.iter_mut().zip(&precise_bounds) {
        if cell.colspan > 1 {
            if let Some(bounds) = bounds {
                let close = (cell.rect.x0 - bounds.x0).abs() <= 1.0
                    && (cell.rect.y0 - bounds.y0).abs() <= 1.0
                    && (cell.rect.x1 - bounds.x1).abs() <= 1.0
                    && (cell.rect.y1 - bounds.y1).abs() <= 1.0;
                if close {
                    cell.rect = rounded_rect(bounds.clone());
                }
            }
        }
    }

    let nonempty: Vec<CellDto> = table
        .cells
        .iter()
        .filter(|cell| !cell.text.trim().is_empty())
        .cloned()
        .collect();
    let Some(content_bounds) = union_rect(nonempty.iter().map(|cell| &cell.rect)) else {
        return table;
    };
    let edge_cells = nonempty.clone();

    let columns = table.cols as usize;
    let rows = table.rows as usize;
    let mut column_edges = vec![None; columns + 1];
    column_edges[0] = Some(content_bounds.x0);
    column_edges[columns] = Some(content_bounds.x1);
    for boundary in 1..columns {
        let left = edge_cells
            .iter()
            .filter(|cell| cell.colspan == 1 && cell.col + cell.colspan <= boundary as i64)
            .map(|cell| cell.rect.x1)
            .reduce(f64::max);
        let right = edge_cells
            .iter()
            .filter(|cell| cell.colspan == 1 && cell.col >= boundary as i64)
            .map(|cell| cell.rect.x0)
            .reduce(f64::min);
        if let (Some(left), Some(right)) = (left, right) {
            column_edges[boundary] = Some(round_grid_boundary((left + right) / 2.0));
        }
    }

    let mut row_centers = vec![None; rows];
    for row in 0..rows {
        let centers: Vec<f64> = edge_cells
            .iter()
            .filter(|cell| cell.row == row as i64 && cell.rowspan == 1)
            .map(|cell| center_y(&cell.rect))
            .collect();
        if !centers.is_empty() {
            row_centers[row] = Some(centers.iter().sum::<f64>() / centers.len() as f64);
        }
    }
    let mut row_edges = vec![None; rows + 1];
    row_edges[0] = Some(content_bounds.y0);
    row_edges[rows] = Some(content_bounds.y1);
    for boundary in 1..rows {
        if let (Some(above), Some(below)) = (row_centers[boundary - 1], row_centers[boundary]) {
            row_edges[boundary] = Some(crate::geometry::round_one_decimal((above + below) / 2.0));
        }
    }

    for cell in &mut table.cells {
        if !cell.text.trim().is_empty() || cell.row < 0 || cell.col < 0 {
            continue;
        }
        let col = cell.col as usize;
        let row = cell.row as usize;
        let col_end = col.saturating_add(cell.colspan.max(1) as usize).min(columns);
        let row_end = row.saturating_add(cell.rowspan.max(1) as usize).min(rows);
        if col_end <= columns {
            if let (Some(x0), Some(x1)) = (column_edges[col], column_edges[col_end]) {
                cell.rect.x0 = if col == 0 || (cell.rect.x0 - x0).abs() > 0.5 {
                    x0
                } else {
                    cell.rect.x0
                };
                cell.rect.x1 = if col_end == columns || (cell.rect.x1 - x1).abs() > 0.5 {
                    x1
                } else {
                    cell.rect.x1
                };
            }
        }
        if row_end <= rows {
            if let (Some(y0), Some(y1)) = (row_edges[row], row_edges[row_end]) {
                cell.rect.y0 = if row == 0 || (cell.rect.y0 - y0).abs() > 0.5 {
                    y0
                } else {
                    cell.rect.y0
                };
                cell.rect.y1 = if row_end == rows || (cell.rect.y1 - y1).abs() > 0.5 {
                    y1
                } else {
                    cell.rect.y1
                };
            }
        }
    }
    if let Some(bounds) = union_rect(table.cells.iter().map(|cell| &cell.rect)) {
        table.rect = bounds;
    }
    table
}

fn apply_personal_credit_rules(
    tables: Vec<TableCandidateDto>,
    snapshot: &PageSnapshotDto,
) -> Vec<TableCandidateDto> {
    let mut filtered = Vec::new();
    for table in tables {
        let table = trim_query_table(table);
        if is_numbered_prose_candidate(&table) {
            continue;
        }
        let is_wired = table_is_wired(&table);
        if !is_wired && is_report_metadata_candidate(&table) {
            continue;
        }
        filtered.extend(
            split_repeated_records(table)
                .into_iter()
                .map(|table| normalize_wireless_cell_geometry(table, snapshot)),
        );
    }
    filtered
}

fn is_wired_source(source: &str) -> bool {
    matches!(
        source,
        "line_projection" | "hybrid_line_span_recovery" | "PyMuPDF.find_tables"
    )
}

fn table_is_wired(table: &TableCandidateDto) -> bool {
    table.has_wired_lines || is_wired_source(&table.source)
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
    let has_upstream_candidates = input.candidate_tables.is_some();
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

    let mut tables = if let Some(candidates) = input.candidate_tables.clone() {
        let mut tables = candidates;
        if input.supplement_rust_candidates {
            let supplemental = wireless_candidates(&input, &tables);
            for candidate in supplemental {
                if !tables
                    .iter()
                    .any(|existing| tables_overlap(existing, &candidate))
                {
                    tables.push(candidate);
                }
            }
        }
        tables
    } else {
        let mut wired = wired_candidates(&input);
        let wireless = wireless_candidates(&input, &wired);
        wired.extend(wireless);
        wired
    };
    if let Some(first_header) = header_indices.first().copied() {
        let first_bound = section_indices
            .iter()
            .copied()
            .filter(|index| *index < first_header)
            .min()
            .unwrap_or(first_header);
        if first_bound > 0 {
            if let Some(table) = recover_headerless_query_table(
                &rows[..first_bound],
                input.snapshot.page.width,
            ) {
                tables.push(table);
            }
        }
    }
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

    let query_tables: Vec<TableCandidateDto> = tables
        .iter()
        .filter(|table| table.source == "personal_query_recovery")
        .cloned()
        .collect();
    tables.retain(|table| {
        table.source == "personal_query_recovery"
            || !query_tables.iter().any(|query| tables_overlap(table, query))
    });
    let mut tables = apply_personal_credit_rules(tables, &input.snapshot);

    if !has_upstream_candidates {
        tables.sort_by(|left, right| {
            left.rect
                .y0
                .partial_cmp(&right.rect.y0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    }
    PersonalCreditOutput {
        schema_version: 1,
        tables,
        diagnostics: Vec::new(),
    }
}
