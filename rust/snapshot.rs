use crate::types::{
    CharacterDto, NativeSpanDto, NativeSpanInputDto, PageSnapshotDto, Rect4, SourcePositionDto,
};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

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

pub fn collect_native_spans_from_rawdict(
    rawdict: &Bound<'_, PyDict>,
    page_height: f64,
    page_y0: f64,
    allowed_regions: Option<&[Rect4]>,
    excluded_regions: Option<&[Rect4]>,
) -> PyResult<Vec<NativeSpanInputDto>> {
    let blocks_val = match rawdict.get_item("blocks")? {
        Some(b) => b,
        None => return Ok(Vec::new()),
    };
    let blocks = match blocks_val.downcast::<PyList>() {
        Ok(l) => l,
        Err(_) => return Ok(Vec::new()),
    };

    let mut spans: Vec<NativeSpanInputDto> = Vec::new();
    let mut order: i64 = 0;

    for (block_index, block_item) in blocks.iter().enumerate() {
        let block = match block_item.downcast::<PyDict>() {
            Ok(d) => d,
            Err(_) => continue,
        };
        let btype = match block.get_item("type")? {
            Some(t) => t.extract::<i64>().unwrap_or(-1),
            None => -1,
        };
        if btype != 0 {
            continue;
        }

        let lines_val = match block.get_item("lines")? {
            Some(l) => l,
            None => continue,
        };
        let lines = match lines_val.downcast::<PyList>() {
            Ok(l) => l,
            Err(_) => continue,
        };

        for (line_index, line_item) in lines.iter().enumerate() {
            let line = match line_item.downcast::<PyDict>() {
                Ok(d) => d,
                Err(_) => continue,
            };

            let line_bbox = match line.get_item("bbox")? {
                Some(b) => match b.extract::<(f64, f64, f64, f64)>() {
                    Ok(t) => Rect4 {
                        schema_version: 1,
                        x0: t.0,
                        y0: t.1,
                        x1: t.2,
                        y1: t.3,
                    },
                    Err(_) => continue,
                },
                None => continue,
            };

            let spans_val = match line.get_item("spans")? {
                Some(s) => s,
                None => continue,
            };
            let line_spans = match spans_val.downcast::<PyList>() {
                Ok(s) => s,
                Err(_) => continue,
            };

            // 1. 拼接整行文本以检测页脚页码
            let mut line_text = String::new();
            for span_item in line_spans.iter() {
                if let Ok(span_dict) = span_item.downcast::<PyDict>() {
                    if let Some(chars_val) = span_dict.get_item("chars")? {
                        if let Ok(chars_list) = chars_val.downcast::<PyList>() {
                            for char_item in chars_list.iter() {
                                if let Ok(char_dict) = char_item.downcast::<PyDict>() {
                                    if let Some(c_val) = char_dict.get_item("c")? {
                                        if let Ok(c_str) = c_val.extract::<String>() {
                                            line_text.push_str(&c_str);
                                        }
                                    }
                                }
                            }
                        }
                    } else if let Some(text_val) = span_dict.get_item("text")? {
                        if let Ok(t_str) = text_val.extract::<String>() {
                            line_text.push_str(&t_str);
                        }
                    }
                }
            }

            if is_footer_page_number(&line_text) && line_bbox.y0 >= page_y0 + page_height * 0.85 {
                continue;
            }

            // 2. 遍历各个 span
            for (span_index, span_item) in line_spans.iter().enumerate() {
                let span = match span_item.downcast::<PyDict>() {
                    Ok(d) => d,
                    Err(_) => continue,
                };

                let font = span.get_item("font")?.and_then(|v| v.extract::<String>().ok());
                let size = span.get_item("size")?.and_then(|v| v.extract::<f64>().ok());
                let flags = span.get_item("flags")?.and_then(|v| v.extract::<i64>().ok());

                let span_rect = match span.get_item("bbox")? {
                    Some(b) => match b.extract::<(f64, f64, f64, f64)>() {
                        Ok(t) => Rect4 {
                            schema_version: 1,
                            x0: t.0,
                            y0: t.1,
                            x1: t.2,
                            y1: t.3,
                        },
                        Err(_) => continue,
                    },
                    None => continue,
                };

                let mut span_text = String::new();
                let mut characters: Vec<CharacterDto> = Vec::new();
                let mut char_raw_positions: Vec<Vec<i64>> = Vec::new();

                if let Some(chars_val) = span.get_item("chars")? {
                    if let Ok(chars_list) = chars_val.downcast::<PyList>() {
                        for (char_index, char_item) in chars_list.iter().enumerate() {
                            if let Ok(char_dict) = char_item.downcast::<PyDict>() {
                                let c_str = match char_dict.get_item("c")? {
                                    Some(v) => match v.extract::<String>() {
                                        Ok(s) => s,
                                        Err(_) => continue,
                                    },
                                    None => continue,
                                };
                                if c_str.is_empty() {
                                    continue;
                                }
                                let char_rect = match char_dict.get_item("bbox")? {
                                    Some(b) => match b.extract::<(f64, f64, f64, f64)>() {
                                        Ok(t) => Rect4 {
                                            schema_version: 1,
                                            x0: t.0,
                                            y0: t.1,
                                            x1: t.2,
                                            y1: t.3,
                                        },
                                        Err(_) => Rect4 {
                                            schema_version: 1,
                                            x0: 0.0,
                                            y0: 0.0,
                                            x1: 0.0,
                                            y1: 0.0,
                                        },
                                    },
                                    None => Rect4 {
                                        schema_version: 1,
                                        x0: 0.0,
                                        y0: 0.0,
                                        x1: 0.0,
                                        y1: 0.0,
                                    },
                                };
                                span_text.push_str(&c_str);
                                characters.push(CharacterDto {
                                    schema_version: 1,
                                    text: c_str,
                                    rect: char_rect,
                                    order: char_index as i64,
                                });
                                char_raw_positions.push(vec![
                                    block_index as i64,
                                    line_index as i64,
                                    span_index as i64,
                                    char_index as i64,
                                ]);
                            }
                        }
                    }
                } else if let Some(text_val) = span.get_item("text")? {
                    if let Ok(t_str) = text_val.extract::<String>() {
                        span_text = t_str;
                    }
                }

                if span_text.trim().is_empty() {
                    continue;
                }

                let raw_pos = vec![block_index as i64, line_index as i64, span_index as i64];
                let native_span = NativeSpanDto {
                    schema_version: 1,
                    text: span_text,
                    rect: span_rect,
                    font,
                    size,
                    flags,
                    order,
                    characters,
                    source_position: SourcePositionDto {
                        schema_version: 1,
                        block: block_index as i64,
                        line: line_index as i64,
                    },
                    block: block_index as i64,
                    line: line_index as i64,
                };

                spans.push(NativeSpanInputDto {
                    span: native_span,
                    raw_source_position: raw_pos,
                    character_raw_source_positions: char_raw_positions,
                });

                order += 1;
            }
        }
    }

    // 空间过滤
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

    Ok(filtered)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_footer_page_number() {
        assert!(is_footer_page_number("第 1 页 / 共 5 页"));
        assert!(is_footer_page_number("第1页/共5页"));
        assert!(is_footer_page_number("  第  12  页  /  共  100  页  "));
        assert!(!is_footer_page_number("第 1 页"));
        assert!(!is_footer_page_number("正文说明：第 1 页 / 共 5 页 见附注"));
        assert!(!is_footer_page_number("第 1 页 / 共 页"));
    }
}
