use crate::classifier;
use crate::clustering::{make_rect4, Rect4Dto, WireWordDto, WordTupleDto};
use crate::drawings::WireDrawingDto;
use crate::font_mapping::Type3GlyphMap;
use crate::{clustering, drawings, PdfiumRawPage, PdfiumRawSnapshot, SpanInfo};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PageInfoDto {
    pub schema_version: i64,
    pub width: f64,
    pub height: f64,
    pub rotation: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct ExtractionOptionsWireDto {
    pub schema_version: i64,
    pub options: serde_json::Map<String, serde_json::Value>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireCharDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4Dto,
    pub order: usize,
    pub raw_source_position: Vec<i64>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireSpanSourcePositionDto {
    pub schema_version: i64,
    pub block: usize,
    pub line: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireSpanDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4Dto,
    pub font: Option<String>,
    pub size: Option<f64>,
    pub flags: Option<i64>,
    pub order: usize,
    pub characters: Vec<WireCharDto>,
    pub source_position: WireSpanSourcePositionDto,
    pub raw_source_position: Vec<i64>,
    pub block: usize,
    pub line: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireTextLineDto {
    pub schema_version: i64,
    pub rect: Rect4Dto,
    pub spans: Vec<WireSpanDto>,
    pub order: usize,
    pub source_position: Vec<i64>,
    pub source_order: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireTextBlockDto {
    pub schema_version: i64,
    #[serde(rename = "type")]
    pub block_type: i64,
    pub rect: Rect4Dto,
    pub lines: Vec<WireTextLineDto>,
    pub order: usize,
    pub source_position: Vec<i64>,
    pub source_order: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PageSnapshotWireDto {
    pub schema_version: i64,
    pub page_index: i64,
    pub page: PageInfoDto,
    pub text_blocks: Vec<WireTextBlockDto>,
    pub spans: Vec<WireSpanDto>,
    pub words: Vec<WireWordDto>,
    pub drawings: Vec<WireDrawingDto>,
    pub allowed_regions: Vec<serde_json::Value>,
    pub excluded_regions: Vec<serde_json::Value>,
    pub extraction_options: ExtractionOptionsWireDto,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct RawdictCharWireDto {
    pub c: String,
    pub bbox: [f64; 4],
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct RawdictSpanWireDto {
    pub bbox: [f64; 4],
    pub text: String,
    pub font: String,
    pub size: f64,
    pub flags: i64,
    pub chars: Vec<RawdictCharWireDto>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct RawdictLineWireDto {
    pub bbox: [f64; 4],
    pub spans: Vec<RawdictSpanWireDto>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct RawdictBlockWireDto {
    #[serde(rename = "type")]
    pub block_type: i64,
    pub bbox: [f64; 4],
    pub lines: Vec<RawdictLineWireDto>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct RawdictWireDto {
    pub width: f64,
    pub height: f64,
    pub blocks: Vec<RawdictBlockWireDto>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct NormalizedPageDto {
    pub page_type: String,
    pub page_snapshot: Option<PageSnapshotWireDto>,
    pub rawdict: Option<RawdictWireDto>,
    pub words: Vec<WordTupleDto>,
    pub sidecar: serde_json::Value,
    pub diagnostics: serde_json::Value,
}

fn repair_invalid_unicode_spans(
    spans: &[SpanInfo],
    numeric_type3_glyph_map: Option<&Type3GlyphMap>,
) -> Vec<SpanInfo> {
    if numeric_type3_glyph_map.is_none() {
        return repair_invalid_unicode_spans_without_type3_map(spans);
    }

    let mut repaired_spans = Vec::new();
    for span in spans {
        for mut character in span.characters.iter().cloned() {
                let mapped_character = if character.text_layout.is_some() {
                    let mut source_chars = character.c.chars();
                    source_chars
                        .next()
                        .filter(|_| source_chars.next().is_none())
                        .and_then(|source| {
                            numeric_type3_glyph_map?
                                .characters
                                .get(&(source as u32))
                                .copied()
                        })
                } else {
                    None
                };
                if mapped_character.is_some()
                    && character.text_layout.as_ref().is_some_and(|layout| {
                        layout.horizontal_scale.abs() < 0.001
                            || (layout.y_bounds[1] - layout.y_bounds[0]).abs() < 0.001
                    })
                {
                    continue;
                }
                let decoded_text = mapped_character
                    .map(|mapped| mapped.to_string())
                    .unwrap_or_else(|| character.c.clone());
                let visible_text: String = decoded_text
                    .chars()
                    .filter(|ch| !crate::is_illegal_control_char(*ch))
                    .collect();
                if visible_text.is_empty() {
                    continue;
                }

                if visible_text.chars().any(|ch| !ch.is_whitespace()) {
                    if let Some(layout) = &character.text_layout {
                        let x0 = layout.origin[0] as f32;
                        let x1 = x0 + layout.horizontal_scale as f32;
                        if layout.horizontal_scale.is_finite()
                            && layout.font_size.is_finite()
                            && layout.font_size > 0.0
                            && layout.y_bounds.iter().all(|value| value.is_finite())
                        {
                            let y_bounds = numeric_type3_glyph_map
                                .and_then(|glyph_map| type3_y_bounds(layout, glyph_map))
                                .unwrap_or(layout.y_bounds);
                            character.bbox = [
                                x0.min(x1) as f64,
                                y_bounds[0],
                                x0.max(x1) as f64,
                                y_bounds[1],
                            ];
                        }
                    }
                }

                character.c = visible_text.clone();
                let mut repaired = span.clone();
                repaired.text = visible_text;
                repaired.bbox = character.bbox;
                repaired.characters = vec![character.clone()];
                repaired.provenance.character_count = 1;
                repaired.provenance.char_start_index = character.char_index;
                repaired.provenance.char_end_index = character.char_index.saturating_add(1);
                repaired.provenance.char_indices = vec![character.char_index];
                if let Some(layout) = &character.text_layout {
                    if layout.font_size.is_finite() && layout.font_size > 0.0 {
                        repaired.size = Some(layout.font_size);
                    }
                }
                repaired_spans.push(repaired);
        }
    }
    repaired_spans
}

fn repair_invalid_unicode_spans_without_type3_map(spans: &[SpanInfo]) -> Vec<SpanInfo> {
    spans
        .iter()
        .filter_map(|span| {
            let mut repaired = span.clone();
            let mut text = String::new();
            let mut characters = Vec::with_capacity(span.characters.len());
            let mut font_size = None;

            for mut character in repaired.characters.drain(..) {
                let visible_text: String = character
                    .c
                    .chars()
                    .filter(|ch| !crate::is_illegal_control_char(*ch))
                    .collect();
                if visible_text.is_empty() {
                    continue;
                }

                if visible_text.chars().any(|ch| !ch.is_whitespace()) {
                    if let Some(layout) = &character.text_layout {
                        let x_end = layout.origin[0] + layout.horizontal_scale;
                        if layout.horizontal_scale.is_finite()
                            && layout.font_size.is_finite()
                            && layout.font_size > 0.0
                            && layout.y_bounds.iter().all(|value| value.is_finite())
                        {
                            character.bbox = [
                                layout.origin[0].min(x_end),
                                layout.y_bounds[0],
                                layout.origin[0].max(x_end),
                                layout.y_bounds[1],
                            ];
                            font_size.get_or_insert(layout.font_size);
                        }
                    }
                }

                character.c = visible_text.clone();
                text.push_str(&visible_text);
                characters.push(character);
            }

            if text.is_empty() {
                return None;
            }
            repaired.text = text;
            repaired.characters = characters;
            if let Some(font_size) = font_size {
                repaired.size = Some(font_size);
            }
            Some(repaired)
        })
        .collect()
}

fn type3_y_bounds(layout: &crate::TextCharLayout, glyph_map: &Type3GlyphMap) -> Option<[f64; 2]> {
    if glyph_map
        .font_matrix
        .iter()
        .any(|value| !value.is_finite())
    {
        return None;
    }
    let [_, b, _, d, _, f] = glyph_map.font_matrix;

    let [x0, y0, x1, y1] = glyph_map.font_bbox;
    let transformed_y = [
        b * x0 + d * y0 + f,
        b * x0 + d * y1 + f,
        b * x1 + d * y0 + f,
        b * x1 + d * y1 + f,
    ];
    let lower = transformed_y.iter().copied().fold(f64::INFINITY, f64::min);
    let upper = transformed_y
        .iter()
        .copied()
        .fold(f64::NEG_INFINITY, f64::max);
    if !lower.is_finite()
        || !upper.is_finite()
        || !layout.origin[1].is_finite()
        || !layout.font_size.is_finite()
        || layout.font_size <= 0.0
    {
        return None;
    }

    let origin_y = layout.origin[1] as f32;
    let font_size = layout.font_size as f32;
    let upper_extent = upper as f32 * font_size;
    let lower_extent = lower as f32 * font_size;
    let bounds = [
        (origin_y - upper_extent) as f64,
        (origin_y - lower_extent) as f64,
    ];
    ((bounds[0] - layout.y_bounds[0])
        .abs()
        .max((bounds[1] - layout.y_bounds[1]).abs())
        <= 0.01)
        .then_some(bounds)
}

pub fn normalize_raw_page(raw_page: &PdfiumRawPage) -> NormalizedPageDto {
    normalize_raw_page_with_meta_options(raw_page, None, None, false, None)
}

/// Includes native text views for standalone APIs while retaining the scanned classification.
pub fn normalize_raw_page_for_public_api(raw_page: &PdfiumRawPage) -> NormalizedPageDto {
    normalize_raw_page_for_public_api_with_glyph_map(raw_page, None)
}

pub fn normalize_raw_page_for_public_api_with_glyph_map(
    raw_page: &PdfiumRawPage,
    numeric_type3_glyph_map: Option<&Type3GlyphMap>,
) -> NormalizedPageDto {
    normalize_raw_page_with_meta_options(raw_page, None, None, true, numeric_type3_glyph_map)
}

pub fn normalize_raw_page_with_meta(
    raw_page: &PdfiumRawPage,
    source_file: Option<&str>,
    generator: Option<&str>,
) -> NormalizedPageDto {
    normalize_raw_page_with_meta_options(raw_page, source_file, generator, false, None)
}

fn normalize_raw_page_with_meta_options(
    raw_page: &PdfiumRawPage,
    source_file: Option<&str>,
    generator: Option<&str>,
    retain_scanned_text_views: bool,
    numeric_type3_glyph_map: Option<&Type3GlyphMap>,
) -> NormalizedPageDto {
    let classification = classifier::classify_raw_page(raw_page);

    let is_scanned = !classifier::is_vector_page(&classification);
    if is_scanned && !retain_scanned_text_views {
        let class_json = serde_json::to_value(&classification).unwrap_or(serde_json::Value::Null);
        return NormalizedPageDto {
            page_type: "scanned".to_string(),
            page_snapshot: None,
            rawdict: None,
            words: Vec::new(),
            sidecar: serde_json::json!({
                "classification": class_json,
            }),
            diagnostics: class_json,
        };
    }

    let use_baseline_text_layout = retain_scanned_text_views
        && is_scanned
        && raw_page.mapping_diagnostics.classification_reason.as_deref() == Some("invalid_unicode")
        && raw_page.mapping_diagnostics.control_char_count > 0;
    let repaired_spans = use_baseline_text_layout
        .then(|| repair_invalid_unicode_spans(&raw_page.spans, numeric_type3_glyph_map));
    let spans = repaired_spans.as_deref().unwrap_or(&raw_page.spans);
    let blocks = if use_baseline_text_layout {
        clustering::cluster_spans_into_blocks_by_baseline(spans, raw_page.page_index)
    } else {
        clustering::cluster_spans_into_blocks(spans, raw_page.page_index)
    };
    let (words_tuples, wire_words) = clustering::derive_words(&blocks, raw_page.page_index);
    let (wire_drawings, drawings_diagnostics) = drawings::normalize_drawings(&raw_page.drawings);

    let mut wire_blocks = Vec::with_capacity(blocks.len());
    let mut rawdict_blocks = Vec::with_capacity(blocks.len());
    let mut flat_spans = Vec::new();

    let mut global_span_order: usize = 0;
    let mut global_char_order: usize = 0;

    for (block_idx, block) in blocks.iter().enumerate() {
        let mut wire_lines = Vec::with_capacity(block.lines.len());
        let mut rawdict_lines = Vec::with_capacity(block.lines.len());

        for (line_idx, line) in block.lines.iter().enumerate() {
            let mut wire_line_spans = Vec::with_capacity(line.spans.len());
            let mut rawdict_line_spans = Vec::with_capacity(line.spans.len());

            for span in &line.spans {
                let mut wire_chars = Vec::with_capacity(span.characters.len());
                let mut rawdict_chars = Vec::with_capacity(span.characters.len());

                for ch in &span.characters {
                    let char_raw_pos = vec![
                        ch.page_index as i64,
                        ch.pdfium_object_index as i64,
                        ch.char_index as i64,
                        ch.char_index as i64,
                    ];

                    wire_chars.push(WireCharDto {
                        schema_version: 1,
                        text: ch.c.clone(),
                        rect: make_rect4(ch.bbox[0], ch.bbox[1], ch.bbox[2], ch.bbox[3]),
                        order: global_char_order,
                        raw_source_position: char_raw_pos,
                    });

                    rawdict_chars.push(RawdictCharWireDto {
                        c: ch.c.clone(),
                        bbox: ch.bbox,
                    });

                    global_char_order += 1;
                }

                let span_raw_pos = if let (Some(first), Some(last)) =
                    (span.characters.first(), span.characters.last())
                {
                    vec![
                        first.page_index as i64,
                        first.pdfium_object_index as i64,
                        first.char_index as i64,
                        last.char_index as i64,
                    ]
                } else {
                    vec![
                        raw_page.page_index as i64,
                        span.provenance.pdfium_object_index as i64,
                        0,
                        0,
                    ]
                };

                let wire_span = WireSpanDto {
                    schema_version: 1,
                    text: span.text.clone(),
                    rect: make_rect4(span.x0(), span.y0(), span.x1(), span.y1()),
                    font: span.font.clone(),
                    size: Some(span.size),
                    flags: span.flags,
                    order: global_span_order,
                    characters: wire_chars,
                    source_position: WireSpanSourcePositionDto {
                        schema_version: 1,
                        block: block_idx,
                        line: line_idx,
                    },
                    raw_source_position: span_raw_pos,
                    block: block_idx,
                    line: line_idx,
                };

                wire_line_spans.push(wire_span.clone());
                flat_spans.push(wire_span);

                rawdict_line_spans.push(RawdictSpanWireDto {
                    bbox: [span.x0(), span.y0(), span.x1(), span.y1()],
                    text: span.text.clone(),
                    font: span.font.clone().unwrap_or_default(),
                    size: span.size,
                    flags: span.flags.unwrap_or(0),
                    chars: rawdict_chars,
                });

                global_span_order += 1;
            }

            wire_lines.push(WireTextLineDto {
                schema_version: 1,
                rect: make_rect4(line.x0(), line.y0, line.x1(), line.y1),
                spans: wire_line_spans,
                order: line_idx,
                source_position: vec![block_idx as i64, line_idx as i64],
                source_order: line_idx,
            });

            rawdict_lines.push(RawdictLineWireDto {
                bbox: [line.x0(), line.y0, line.x1(), line.y1],
                spans: rawdict_line_spans,
            });
        }

        wire_blocks.push(WireTextBlockDto {
            schema_version: 1,
            block_type: 0,
            rect: make_rect4(block.x0(), block.y0(), block.x1(), block.y1()),
            lines: wire_lines,
            order: block_idx,
            source_position: vec![block_idx as i64],
            source_order: block_idx,
        });

        rawdict_blocks.push(RawdictBlockWireDto {
            block_type: 0,
            bbox: [block.x0(), block.y0(), block.x1(), block.y1()],
            lines: rawdict_lines,
        });
    }

    let page_snapshot = PageSnapshotWireDto {
        schema_version: 1,
        page_index: raw_page.page_index as i64,
        page: PageInfoDto {
            schema_version: 1,
            width: raw_page.width,
            height: raw_page.height,
            rotation: raw_page.rotation,
        },
        text_blocks: wire_blocks,
        spans: flat_spans,
        words: wire_words,
        drawings: wire_drawings,
        allowed_regions: Vec::new(),
        excluded_regions: Vec::new(),
        extraction_options: ExtractionOptionsWireDto {
            schema_version: 1,
            options: serde_json::Map::new(),
        },
    };

    let rawdict = RawdictWireDto {
        width: raw_page.width,
        height: raw_page.height,
        blocks: rawdict_blocks,
    };

    let mut class_val = serde_json::to_value(&classification).unwrap_or(serde_json::Value::Null);
    if !drawings_diagnostics.is_empty() {
        if let serde_json::Value::Object(ref mut map) = class_val {
            map.insert(
                "drawings_diagnostics".to_string(),
                serde_json::Value::Array(drawings_diagnostics.clone()),
            );
        }
    }

    let mut raw_prov = serde_json::Map::new();
    raw_prov.insert(
        "source_file".to_string(),
        source_file
            .map(|s| serde_json::Value::String(s.to_string()))
            .unwrap_or(serde_json::Value::Null),
    );
    raw_prov.insert(
        "generator".to_string(),
        generator
            .map(|s| serde_json::Value::String(s.to_string()))
            .unwrap_or(serde_json::Value::Null),
    );
    raw_prov.insert(
        "spans_count".to_string(),
        serde_json::json!(raw_page.spans.len()),
    );
    raw_prov.insert(
        "drawings_count".to_string(),
        serde_json::json!(raw_page.drawings.len()),
    );

    let mut sidecar_map = serde_json::Map::new();
    sidecar_map.insert("classification".to_string(), class_val.clone());
    sidecar_map.insert("raw_provenance".to_string(), serde_json::Value::Object(raw_prov));
    if !drawings_diagnostics.is_empty() {
        sidecar_map.insert(
            "drawings_diagnostics".to_string(),
            serde_json::Value::Array(drawings_diagnostics),
        );
    }

    let sidecar = serde_json::Value::Object(sidecar_map);
    let diagnostics = class_val;

    NormalizedPageDto {
        page_type: if is_scanned { "scanned" } else { "vector" }.to_string(),
        page_snapshot: Some(page_snapshot),
        rawdict: Some(rawdict),
        words: words_tuples,
        sidecar,
        diagnostics,
    }
}

pub fn normalize_raw_snapshot(snapshot: &PdfiumRawSnapshot) -> Vec<NormalizedPageDto> {
    snapshot
        .pages
        .iter()
        .map(|page| {
            normalize_raw_page_with_meta(
                page,
                Some(&snapshot.source_file),
                Some(&snapshot.generator),
            )
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{CharInfo, DrawingInfo, DrawingItem, MappingDiagnostics, ProvenanceSidecar, SpanInfo};

    fn make_test_vector_page(text: &str) -> PdfiumRawPage {
        let chars: Vec<CharInfo> = text
            .chars()
            .enumerate()
            .map(|(i, c)| CharInfo {
                c: c.to_string(),
                bbox: [10.0 + i as f64 * 10.0, 10.0, 20.0 + i as f64 * 10.0, 25.0],
                char_index: i,
                text_layout: None,
            })
            .collect();
        let scalar_count = text.chars().count();

        let span = SpanInfo {
            order: 0,
            text: text.to_string(),
            bbox: [10.0, 10.0, 10.0 + scalar_count as f64 * 10.0, 25.0],
            font: Some("TestFont".to_string()),
            size: Some(15.0),
            flags: None,
            render_mode: 0,
            is_invisible: false,
            provenance: ProvenanceSidecar {
                page_index: 0,
                pdfium_object_index: 1,
                character_count: chars.len(),
                char_start_index: 0,
                char_end_index: chars.len(),
                char_indices: (0..chars.len()).collect(),
                is_derived: false,
                derived_block: None,
                derived_line: None,
            },
            characters: chars,
        };

        let drawing = DrawingInfo {
            drawing_index: 0,
            path_type: "stroked".to_string(),
            rect: [10.0, 30.0, 100.0, 31.0],
            width: 1.0,
            color: Some(vec![0.0]),
            fill: None,
            items: vec![DrawingItem {
                cmd: "l".to_string(),
                points: vec![[10.0, 30.0], [100.0, 30.0]],
            }],
        };

        PdfiumRawPage {
            schema_version: "pdfium_raw_page_v1.1".to_string(),
            page_index: 0,
            width: 612.0,
            height: 792.0,
            rotation: 0,
            crop_box: [0.0, 0.0, 612.0, 792.0],
            media_box: [0.0, 0.0, 612.0, 792.0],
            has_invisible_text: false,
            spans: vec![span],
            drawings: vec![drawing],
            mapping_diagnostics: MappingDiagnostics {
                visible_text_scalar_count: scalar_count,
                extracted_char_scalar_count: scalar_count,
                synthetic_space_count: 0,
                replacement_char_count: 0,
                control_char_count: 0,
                mapping_status: "valid".to_string(),
                classification_reason: None,
            },
        }
    }

    fn make_test_scanned_page() -> PdfiumRawPage {
        let span = SpanInfo {
            order: 0,
            text: "Bad\u{FFFD}Text".to_string(),
            bbox: [0.0, 0.0, 10.0, 10.0],
            font: Some("TestFont".to_string()),
            size: Some(10.0),
            flags: None,
            render_mode: 0,
            is_invisible: false,
            provenance: ProvenanceSidecar {
                page_index: 0,
                pdfium_object_index: 1,
                character_count: 8,
                char_start_index: 0,
                char_end_index: 8,
                char_indices: (0..8).collect(),
                is_derived: false,
                derived_block: None,
                derived_line: None,
            },
            characters: vec![],
        };

        PdfiumRawPage {
            schema_version: "pdfium_raw_page_v1.1".to_string(),
            page_index: 0,
            width: 612.0,
            height: 792.0,
            rotation: 0,
            crop_box: [0.0, 0.0, 612.0, 792.0],
            media_box: [0.0, 0.0, 612.0, 792.0],
            has_invisible_text: false,
            spans: vec![span],
            drawings: vec![],
            mapping_diagnostics: MappingDiagnostics {
                visible_text_scalar_count: 8,
                extracted_char_scalar_count: 8,
                synthetic_space_count: 0,
                replacement_char_count: 1,
                control_char_count: 0,
                mapping_status: "invalid".to_string(),
                classification_reason: Some("invalid_unicode".to_string()),
            },
        }
    }

    #[test]
    fn test_normalizer_vector_page_generates_full_dto() {
        let raw_page = make_test_vector_page("Sample text");
        let norm = normalize_raw_page(&raw_page);

        assert_eq!(norm.page_type, "vector");
        assert!(norm.page_snapshot.is_some());
        assert!(norm.rawdict.is_some());
        assert!(!norm.words.is_empty());

        let snapshot = norm.page_snapshot.as_ref().unwrap();
        assert_eq!(snapshot.schema_version, 1);
        assert_eq!(snapshot.page_index, 0);
        assert_eq!(snapshot.page.width, 612.0);
        assert_eq!(snapshot.page.height, 792.0);
        assert_eq!(snapshot.text_blocks.len(), 1);
        assert_eq!(snapshot.spans.len(), 1);
        assert_eq!(snapshot.words.len(), 2);
        assert_eq!(snapshot.drawings.len(), 1);
        assert!(snapshot.allowed_regions.is_empty());
        assert!(snapshot.excluded_regions.is_empty());
        assert_eq!(snapshot.extraction_options.schema_version, 1);

        let rawdict = norm.rawdict.as_ref().unwrap();
        assert_eq!(rawdict.width, 612.0);
        assert_eq!(rawdict.height, 792.0);
        assert_eq!(rawdict.blocks.len(), 1);
        assert_eq!(rawdict.blocks[0].lines[0].spans[0].text, "Sample text");
        assert_eq!(rawdict.blocks[0].lines[0].spans[0].chars.len(), 11);
    }

    #[test]
    fn test_normalizer_scanned_page_returns_empty_views() {
        let raw_page = make_test_scanned_page();
        let norm = normalize_raw_page(&raw_page);

        assert_eq!(norm.page_type, "scanned");
        assert!(norm.page_snapshot.is_none());
        assert!(norm.rawdict.is_none());
        assert!(norm.words.is_empty());
        assert_eq!(norm.sidecar["classification"]["page_type"], "scanned");
        assert_eq!(norm.diagnostics["page_type"], "scanned");
    }

    #[test]
    fn public_api_scanned_normalization_retains_native_text_views() {
        let raw_page = make_test_scanned_page();
        let norm = normalize_raw_page_for_public_api(&raw_page);

        assert_eq!(norm.page_type, "scanned");
        assert!(norm.page_snapshot.is_some());
        assert!(norm.rawdict.is_some());
        assert!(!norm.words.is_empty());
        assert_eq!(norm.page_snapshot.as_ref().unwrap().spans[0].text, "Bad\u{FFFD}Text");
        assert_eq!(norm.diagnostics["page_type"], "scanned");
    }

    #[test]
    fn test_normalizer_multi_page_snapshot() {
        let p0 = make_test_vector_page("Page zero");
        let mut p1 = make_test_vector_page("Page one");
        p1.page_index = 1;

        let snapshot = PdfiumRawSnapshot {
            schema_version: "pdfium_raw_snapshot_v1.1".to_string(),
            generator: "pdfium_probe_test".to_string(),
            source_file: "test.pdf".to_string(),
            source_file_sha256: "abc".to_string(),
            native_library_sha256: "def".to_string(),
            native_library_expected_sha256: "def".to_string(),
            page_count: 2,
            pages: vec![p0, p1],
        };

        let normalized = normalize_raw_snapshot(&snapshot);
        assert_eq!(normalized.len(), 2);
        assert_eq!(normalized[0].page_snapshot.as_ref().unwrap().page_index, 0);
        assert_eq!(normalized[1].page_snapshot.as_ref().unwrap().page_index, 1);
        assert_eq!(
            normalized[0].sidecar["raw_provenance"]["source_file"],
            "test.pdf"
        );
    }

    #[test]
    fn test_normalizer_json_roundtrip() {
        let raw_page = make_test_vector_page("Roundtrip test");
        let norm = normalize_raw_page(&raw_page);

        let json_str = serde_json::to_string(&norm).expect("Serialization failed");
        let deserialized: NormalizedPageDto =
            serde_json::from_str(&json_str).expect("Deserialization failed");

        assert_eq!(norm, deserialized);

        let v: serde_json::Value = serde_json::from_str(&json_str).unwrap();
        assert_eq!(v["page_type"], "vector");
        let snap = &v["page_snapshot"];
        assert_eq!(snap["schema_version"], 1);
        assert!(snap["text_blocks"].is_array());
        assert!(snap["spans"].is_array());
        assert!(snap["words"].is_array());
        assert!(snap["drawings"].is_array());
        assert!(snap["allowed_regions"].is_array());
        assert!(snap["excluded_regions"].is_array());
        assert!(snap["extraction_options"]["options"].is_object());
    }
}
