use crate::table_engine::types::{
    CharacterDto, NativeSpanDto, NativeSpanInputDto, PageSnapshotDto, Rect4, SourcePositionDto,
};

pub fn is_footer_page_number(text: &str) -> bool {
    let trimmed = text.trim();
    if !trimmed.starts_with('第') || !trimmed.ends_with('页') {
        return false;
    }
    let compact: String = trimmed.chars().filter(|c| !c.is_whitespace()).collect();
    if !compact.starts_with('第') || !compact.ends_with('页') {
        return false;
    }
    let parts: Vec<&str> = compact.split('/').collect();
    if parts.len() != 2 {
        return false;
    }
    let p0 = parts[0];
    if !p0.starts_with('第') || !p0.ends_with('页') {
        return false;
    }
    let digits0 = &p0['第'.len_utf8()..p0.len() - '页'.len_utf8()];
    if digits0.is_empty() || !digits0.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let p1 = parts[1];
    if !p1.starts_with('共') || !p1.ends_with('页') {
        return false;
    }
    let digits1 = &p1['共'.len_utf8()..p1.len() - '页'.len_utf8()];
    if digits1.is_empty() || !digits1.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    true
}

pub fn collect_native_spans_from_snapshot(
    snapshot: &PageSnapshotDto,
    allowed_regions: Option<&[Rect4]>,
    excluded_regions: Option<&[Rect4]>,
) -> Vec<NativeSpanInputDto> {
    let page_height = snapshot.page.height;
    let page_y0 = snapshot.page_y0;

    let mut spans: Vec<NativeSpanInputDto> = Vec::new();
    let mut order: i64 = 0;

    for (block_index, block) in snapshot.text_blocks.iter().enumerate() {
        if block.block_type != Some(0) {
            continue;
        }
        for (line_index, line) in block.lines.iter().enumerate() {
            // Reconstruct line text
            let mut line_text = String::new();
            for item in &line.spans {
                for c in &item.span.characters {
                    line_text.push_str(&c.text);
                }
            }

            if is_footer_page_number(&line_text) && line.rect.y0 >= page_y0 + page_height * 0.85 {
                continue;
            }

            for (span_index, item) in line.spans.iter().enumerate() {
                let text: String = item
                    .span
                    .characters
                    .iter()
                    .map(|character| character.text.as_str())
                    .collect();

                if text.trim().is_empty() {
                    continue;
                }

                let raw_pos = if item.raw_source_position.len() >= 3 {
                    item.raw_source_position.clone()
                } else {
                    vec![block_index as i64, line_index as i64, span_index as i64]
                };

                let characters: Vec<CharacterDto> = item
                    .span
                    .characters
                    .iter()
                    .filter(|c| !c.text.is_empty())
                    .cloned()
                    .collect();

                let native_span = NativeSpanDto {
                    schema_version: 1,
                    text,
                    rect: item.span.rect.clone(),
                    font: item.span.font.clone(),
                    size: item.span.size,
                    flags: item.span.flags,
                    order,
                    characters,
                    source_position: SourcePositionDto {
                        schema_version: 1,
                        block: raw_pos[0],
                        line: raw_pos[1],
                    },
                    block: raw_pos[0],
                    line: raw_pos[1],
                };

                spans.push(NativeSpanInputDto {
                    span: native_span,
                    raw_source_position: raw_pos,
                    character_raw_source_positions: item.character_raw_source_positions.clone(),
                });

                order += 1;
            }
        }
    }

    // Spatial filter
    let filtered: Vec<NativeSpanInputDto> = spans
        .into_iter()
        .filter(|item| {
            let cx = (item.span.rect.x0 + item.span.rect.x1) / 2.0;
            let cy = (item.span.rect.y0 + item.span.rect.y1) / 2.0;

            if let Some(allowed) = allowed_regions {
                if !allowed.is_empty()
                    && !allowed
                        .iter()
                        .any(|r| r.x0 <= cx && cx <= r.x1 && r.y0 <= cy && cy <= r.y1)
                {
                    return false;
                }
            }

            if let Some(excluded) = excluded_regions {
                if excluded
                    .iter()
                    .any(|r| r.x0 <= cx && cx <= r.x1 && r.y0 <= cy && cy <= r.y1)
                {
                    return false;
                }
            }

            true
        })
        .collect();

    filtered
}

pub fn collect_native_spans_from_wire(
    norm_page: &crate::normalizer::PageSnapshotWireDto,
    allowed_regions: Option<&[Rect4]>,
    excluded_regions: Option<&[Rect4]>,
) -> Vec<NativeSpanInputDto> {
    let page_height = norm_page.page.height;
    let page_y0 = 0.0;

    let mut spans: Vec<NativeSpanInputDto> = Vec::new();
    let mut order: i64 = 0;

    for (block_index, block) in norm_page.text_blocks.iter().enumerate() {
        if block.block_type != 0 {
            continue;
        }
        for (line_index, line) in block.lines.iter().enumerate() {
            // Reconstruct line text
            let mut line_text = String::new();
            for item in &line.spans {
                for c in &item.characters {
                    line_text.push_str(&c.text);
                }
            }

            if is_footer_page_number(&line_text) && line.rect.y0 >= page_y0 + page_height * 0.85 {
                continue;
            }

            for (span_index, item) in line.spans.iter().enumerate() {
                let text: String = item
                    .characters
                    .iter()
                    .map(|character| character.text.as_str())
                    .collect();

                if text.trim().is_empty() {
                    continue;
                }

                let raw_pos = if item.raw_source_position.len() >= 3 {
                    item.raw_source_position.clone()
                } else {
                    vec![block_index as i64, line_index as i64, span_index as i64]
                };

                let characters: Vec<CharacterDto> = item
                    .characters
                    .iter()
                    .filter(|c| !c.text.is_empty())
                    .map(|c| CharacterDto {
                        schema_version: 1,
                        text: c.text.clone(),
                        rect: Rect4 {
                            schema_version: 1,
                            x0: c.rect.x0,
                            y0: c.rect.y0,
                            x1: c.rect.x1,
                            y1: c.rect.y1,
                        },
                        order: c.order as i64,
                    })
                    .collect();

                let native_span = NativeSpanDto {
                    schema_version: 1,
                    text,
                    rect: Rect4 {
                        schema_version: 1,
                        x0: item.rect.x0,
                        y0: item.rect.y0,
                        x1: item.rect.x1,
                        y1: item.rect.y1,
                    },
                    font: item.font.clone(),
                    size: item.size,
                    flags: item.flags,
                    order,
                    characters,
                    source_position: SourcePositionDto {
                        schema_version: 1,
                        block: raw_pos[0],
                        line: raw_pos[1],
                    },
                    block: raw_pos[0],
                    line: raw_pos[1],
                };

                let char_raw_positions: Vec<Vec<i64>> = item
                    .characters
                    .iter()
                    .map(|c| c.raw_source_position.clone())
                    .collect();

                spans.push(NativeSpanInputDto {
                    span: native_span,
                    raw_source_position: raw_pos,
                    character_raw_source_positions: char_raw_positions,
                });

                order += 1;
            }
        }
    }

    // Spatial filter
    let filtered: Vec<NativeSpanInputDto> = spans
        .into_iter()
        .filter(|item| {
            let cx = (item.span.rect.x0 + item.span.rect.x1) / 2.0;
            let cy = (item.span.rect.y0 + item.span.rect.y1) / 2.0;

            if let Some(allowed) = allowed_regions {
                if !allowed.is_empty()
                    && !allowed
                        .iter()
                        .any(|r| r.x0 <= cx && cx <= r.x1 && r.y0 <= cy && cy <= r.y1)
                {
                    return false;
                }
            }

            if let Some(excluded) = excluded_regions {
                if excluded
                    .iter()
                    .any(|r| r.x0 <= cx && cx <= r.x1 && r.y0 <= cy && cy <= r.y1)
                {
                    return false;
                }
            }

            true
        })
        .collect();

    filtered
}
