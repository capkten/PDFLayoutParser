use serde::{Deserialize, Serialize};
use crate::layout::LayoutElementDto;
use crate::markdown::FullTableDto;
use crate::normalizer::NormalizedPageDto;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct BBoxCoordDto {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

impl From<[f64; 4]> for BBoxCoordDto {
    fn from(b: [f64; 4]) -> Self {
        Self {
            x0: b[0],
            y0: b[1],
            x1: b[2],
            y1: b[3],
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PageSizeDto {
    pub width: f64,
    pub height: f64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct DocumentMetaDto {
    pub file_name: String,
    pub page_count: usize,
}

/// Serializes a `FullTableDto` into the unified JSON table structure.
pub fn serialize_table_dto(table: &FullTableDto) -> serde_json::Value {
    let cells: Vec<serde_json::Value> = table
        .cells
        .iter()
        .map(|c| {
            serde_json::json!({
                "text": c.text,
                "row_index": c.row_index,
                "col_index": c.col_index,
                "bbox": BBoxCoordDto::from(c.bbox),
                "rowspan": c.rowspan,
                "colspan": c.colspan,
            })
        })
        .collect();

    serde_json::json!({
        "bbox": BBoxCoordDto::from(table.bbox),
        "rows": table.rows,
        "cols": table.cols,
        "cells": cells,
        "confidence": table.confidence,
        "source": table.source,
    })
}

/// Extracts text blocks from `norm.rawdict` or `norm.page_snapshot`.
fn extract_blocks_json(norm: &NormalizedPageDto) -> Vec<serde_json::Value> {
    if let Some(ref rawdict) = norm.rawdict {
        if !rawdict.blocks.is_empty() {
            return rawdict
                .blocks
                .iter()
                .map(|b| {
                    let mut line_texts = Vec::new();
                    let mut line_objs = Vec::new();
                    for l in &b.lines {
                        let mut line_str = String::new();
                        for s in &l.spans {
                            line_str.push_str(&s.text);
                        }
                        line_objs.push(serde_json::json!({
                            "text": line_str,
                            "bbox": BBoxCoordDto::from(l.bbox),
                            "words": [],
                        }));
                        line_texts.push(line_str);
                    }
                    let block_text = line_texts.join("\n");
                    serde_json::json!({
                        "text": block_text,
                        "bbox": BBoxCoordDto::from(b.bbox),
                        "lines": line_objs,
                    })
                })
                .collect();
        }
    }

    if let Some(ref snapshot) = norm.page_snapshot {
        return snapshot
            .text_blocks
            .iter()
            .map(|b| {
                let mut line_texts = Vec::new();
                let mut line_objs = Vec::new();
                for l in &b.lines {
                    let mut line_str = String::new();
                    for s in &l.spans {
                        line_str.push_str(&s.text);
                    }
                    line_objs.push(serde_json::json!({
                        "text": line_str,
                        "bbox": BBoxCoordDto {
                            x0: l.rect.x0,
                            y0: l.rect.y0,
                            x1: l.rect.x1,
                            y1: l.rect.y1,
                        },
                        "words": [],
                    }));
                    line_texts.push(line_str);
                }
                let block_text = line_texts.join("\n");
                serde_json::json!({
                    "text": block_text,
                    "bbox": BBoxCoordDto {
                        x0: b.rect.x0,
                        y0: b.rect.y0,
                        x1: b.rect.x1,
                        y1: b.rect.y1,
                    },
                    "lines": line_objs,
                })
            })
            .collect();
    }

    Vec::new()
}

/// Exports a single normalized page, its layout elements, and extracted tables to unified page JSON.
pub fn export_page_to_json(
    norm: &NormalizedPageDto,
    elements: &[LayoutElementDto],
    tables: &[FullTableDto],
    page_index: usize,
) -> serde_json::Value {
    let (width, height, rotation) = if let Some(ref snapshot) = norm.page_snapshot {
        (
            snapshot.page.width,
            snapshot.page.height,
            snapshot.page.rotation,
        )
    } else if let Some(ref rawdict) = norm.rawdict {
        (rawdict.width, rawdict.height, 0)
    } else {
        (612.0, 792.0, 0)
    };

    let blocks = extract_blocks_json(norm);
    let tables_json: Vec<serde_json::Value> = tables.iter().map(serialize_table_dto).collect();

    let layout_elements: Vec<serde_json::Value> = elements
        .iter()
        .map(|elem| {
            let mut map = serde_json::Map::new();
            map.insert(
                "type".to_string(),
                serde_json::Value::String(elem.element_type.clone()),
            );
            map.insert(
                "bbox".to_string(),
                serde_json::to_value(BBoxCoordDto::from(elem.bbox)).unwrap(),
            );
            map.insert("order".to_string(), serde_json::json!(elem.order));

            match elem.element_type.as_str() {
                "table" => {
                    let content = if let Some(tbl_id) = elem.table_index {
                        tables
                            .iter()
                            .find(|t| t.table_id == tbl_id)
                            .or_else(|| tables.get(tbl_id))
                            .map(serialize_table_dto)
                            .unwrap_or(serde_json::Value::Null)
                    } else {
                        serde_json::Value::Null
                    };
                    map.insert("content".to_string(), content);
                }
                "text" => {
                    let text_val = elem.text.as_deref().unwrap_or("");
                    map.insert(
                        "content".to_string(),
                        serde_json::Value::String(text_val.to_string()),
                    );
                    if !elem.lines.is_empty() {
                        let lines_val: Vec<serde_json::Value> = elem
                            .lines
                            .iter()
                            .map(|l| {
                                let words_val: Vec<serde_json::Value> =
                                    if !l.word_details.is_empty() {
                                        l.word_details
                                            .iter()
                                            .map(|w| {
                                                serde_json::json!({
                                                    "text": w.text,
                                                    "bbox": BBoxCoordDto::from(w.bbox),
                                                })
                                            })
                                            .collect()
                                    } else {
                                        l.words
                                            .iter()
                                            .map(|w| {
                                                serde_json::json!({
                                                    "text": w,
                                                    "bbox": BBoxCoordDto::from(l.bbox),
                                                })
                                            })
                                            .collect()
                                    };
                                serde_json::json!({
                                    "text": l.text,
                                    "bbox": BBoxCoordDto::from(l.bbox),
                                    "words": words_val,
                                })
                            })
                            .collect();
                        map.insert("lines".to_string(), serde_json::Value::Array(lines_val));
                    }
                }
                _ => {
                    map.insert("content".to_string(), serde_json::Value::Null);
                }
            }

            serde_json::Value::Object(map)
        })
        .collect();

    serde_json::json!({
        "index": page_index,
        "size": PageSizeDto { width, height },
        "rotation": rotation,
        "page_type": norm.page_type,
        "blocks": blocks,
        "tables": tables_json,
        "images": [],
        "seals": [],
        "render": serde_json::Value::Null,
        "layout_elements": layout_elements,
    })
}

/// Exports all page JSONs and document metadata into the unified document JSON structure.
pub fn export_document_to_json(
    file_name: &str,
    pages: Vec<serde_json::Value>,
) -> serde_json::Value {
    let meta = DocumentMetaDto {
        file_name: file_name.to_string(),
        page_count: pages.len(),
    };
    serde_json::json!({
        "document": meta,
        "pages": pages,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clustering::make_rect4;
    use crate::layout::{LayoutTextLine, LayoutWordInfo};
    use crate::markdown::TableCellDto;
    use crate::normalizer::{
        ExtractionOptionsWireDto, PageInfoDto, PageSnapshotWireDto, RawdictBlockWireDto,
        RawdictCharWireDto, RawdictLineWireDto, RawdictSpanWireDto, RawdictWireDto, WireSpanDto,
        WireSpanSourcePositionDto, WireTextBlockDto, WireTextLineDto,
    };

    #[test]
    fn test_json_export_bbox_format() {
        let bbox = BBoxCoordDto::from([10.5, 20.25, 100.0, 200.75]);
        let val = serde_json::to_value(&bbox).unwrap();
        assert_eq!(val["x0"], 10.5);
        assert_eq!(val["y0"], 20.25);
        assert_eq!(val["x1"], 100.0);
        assert_eq!(val["y1"], 200.75);
    }

    #[test]
    fn test_json_export_table() {
        let table = FullTableDto {
            table_id: 0,
            bbox: [50.0, 50.0, 200.0, 150.0],
            rows: 2,
            cols: 2,
            cells: vec![
                TableCellDto {
                    text: "Header 1".to_string(),
                    row_index: 0,
                    col_index: 0,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [50.0, 50.0, 125.0, 100.0],
                },
                TableCellDto {
                    text: "Header 2".to_string(),
                    row_index: 0,
                    col_index: 1,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [125.0, 50.0, 200.0, 100.0],
                },
            ],
            confidence: Some(0.95),
            source: Some("lattice".to_string()),
        };
        let val = serialize_table_dto(&table);
        assert_eq!(val["rows"], 2);
        assert_eq!(val["cols"], 2);
        assert_eq!(val["confidence"], 0.95);
        assert_eq!(val["source"], "lattice");
        assert_eq!(val["bbox"]["x0"], 50.0);
        assert_eq!(val["cells"].as_array().unwrap().len(), 2);
        assert_eq!(val["cells"][0]["text"], "Header 1");
        assert_eq!(val["cells"][0]["row_index"], 0);
        assert_eq!(val["cells"][0]["col_index"], 0);
        assert_eq!(val["cells"][0]["rowspan"], 1);
        assert_eq!(val["cells"][0]["colspan"], 1);
        assert_eq!(val["cells"][0]["bbox"]["x0"], 50.0);
    }

    #[test]
    fn test_json_export_page() {
        let table = FullTableDto {
            table_id: 0,
            bbox: [50.0, 50.0, 200.0, 150.0],
            rows: 1,
            cols: 1,
            cells: vec![TableCellDto {
                text: "Cell 0".to_string(),
                row_index: 0,
                col_index: 0,
                rowspan: 1,
                colspan: 1,
                bbox: [50.0, 50.0, 200.0, 150.0],
            }],
            confidence: Some(1.0),
            source: Some("pdfium".to_string()),
        };

        let norm = NormalizedPageDto {
            page_type: "vector".to_string(),
            page_snapshot: Some(PageSnapshotWireDto {
                schema_version: 1,
                page_index: 0,
                page: PageInfoDto {
                    schema_version: 1,
                    width: 595.0,
                    height: 842.0,
                    rotation: 0,
                },
                text_blocks: vec![WireTextBlockDto {
                    schema_version: 1,
                    block_type: 0,
                    rect: make_rect4(10.0, 10.0, 100.0, 30.0),
                    lines: vec![WireTextLineDto {
                        schema_version: 1,
                        rect: make_rect4(10.0, 10.0, 100.0, 30.0),
                        spans: vec![WireSpanDto {
                            schema_version: 1,
                            text: "Hello Rust".to_string(),
                            rect: make_rect4(10.0, 10.0, 100.0, 30.0),
                            font: Some("Helvetica".to_string()),
                            size: Some(12.0),
                            flags: None,
                            order: 0,
                            characters: vec![],
                            source_position: WireSpanSourcePositionDto {
                                schema_version: 1,
                                block: 0,
                                line: 0,
                            },
                            raw_source_position: vec![0, 0, 0, 0],
                            block: 0,
                            line: 0,
                        }],
                        order: 0,
                        source_position: vec![0, 0],
                        source_order: 0,
                    }],
                    order: 0,
                    source_position: vec![0],
                    source_order: 0,
                }],
                spans: vec![],
                words: vec![],
                drawings: vec![],
                allowed_regions: vec![],
                excluded_regions: vec![],
                extraction_options: ExtractionOptionsWireDto {
                    schema_version: 1,
                    options: serde_json::Map::new(),
                },
            }),
            rawdict: None,
            words: vec![],
            sidecar: serde_json::Value::Null,
            diagnostics: serde_json::Value::Null,
        };

        let elements = vec![
            LayoutElementDto {
                element_type: "text".to_string(),
                bbox: [10.0, 10.0, 100.0, 30.0],
                order: 0,
                text: Some("Hello Rust".to_string()),
                table_index: None,
                image_index: None,
                lines: vec![LayoutTextLine {
                    text: "Hello Rust".to_string(),
                    bbox: [10.0, 10.0, 100.0, 30.0],
                    words: vec!["Hello".to_string(), "Rust".to_string()],
                    word_details: vec![
                        LayoutWordInfo {
                            text: "Hello".to_string(),
                            bbox: [10.0, 10.0, 50.0, 30.0],
                        },
                        LayoutWordInfo {
                            text: "Rust".to_string(),
                            bbox: [55.0, 10.0, 100.0, 30.0],
                        },
                    ],
                }],
            },
            LayoutElementDto {
                element_type: "table".to_string(),
                bbox: [50.0, 50.0, 200.0, 150.0],
                order: 1,
                text: None,
                table_index: Some(0),
                image_index: None,
                lines: vec![],
            },
        ];

        let page_json = export_page_to_json(&norm, &elements, &[table], 0);

        assert_eq!(page_json["index"], 0);
        assert_eq!(page_json["size"]["width"], 595.0);
        assert_eq!(page_json["size"]["height"], 842.0);
        assert_eq!(page_json["rotation"], 0);
        assert_eq!(page_json["page_type"], "vector");
        assert_eq!(page_json["blocks"][0]["text"], "Hello Rust");
        assert_eq!(page_json["blocks"][0]["bbox"]["x0"], 10.0);
        assert_eq!(page_json["tables"].as_array().unwrap().len(), 1);
        assert!(page_json["images"].as_array().unwrap().is_empty());
        assert!(page_json["seals"].as_array().unwrap().is_empty());
        assert!(page_json["render"].is_null());
        assert_eq!(page_json["layout_elements"].as_array().unwrap().len(), 2);
        assert_eq!(page_json["layout_elements"][0]["type"], "text");
        assert_eq!(page_json["layout_elements"][0]["content"], "Hello Rust");
        assert_eq!(
            page_json["layout_elements"][0]["lines"][0]["text"],
            "Hello Rust"
        );
        assert_eq!(
            page_json["layout_elements"][0]["lines"][0]["words"][0]["text"],
            "Hello"
        );
        assert_eq!(page_json["layout_elements"][1]["type"], "table");
        assert_eq!(page_json["layout_elements"][1]["content"]["rows"], 1);
    }

    #[test]
    fn test_json_export_document() {
        let page_val = serde_json::json!({
            "index": 0,
            "size": { "width": 595.0, "height": 842.0 },
            "page_type": "vector",
        });
        let doc_val = export_document_to_json("sample.pdf", vec![page_val]);
        assert_eq!(doc_val["document"]["file_name"], "sample.pdf");
        assert_eq!(doc_val["document"]["page_count"], 1);
        assert_eq!(doc_val["pages"].as_array().unwrap().len(), 1);
        assert_eq!(doc_val["pages"][0]["index"], 0);
    }

    #[test]
    fn test_json_export_rawdict_fallback_and_image_element() {
        let norm = NormalizedPageDto {
            page_type: "scanned".to_string(),
            page_snapshot: None,
            rawdict: Some(RawdictWireDto {
                width: 500.0,
                height: 700.0,
                blocks: vec![RawdictBlockWireDto {
                    block_type: 0,
                    bbox: [0.0, 0.0, 50.0, 20.0],
                    lines: vec![RawdictLineWireDto {
                        bbox: [0.0, 0.0, 50.0, 20.0],
                        spans: vec![RawdictSpanWireDto {
                            bbox: [0.0, 0.0, 50.0, 20.0],
                            text: "Rawdict text".to_string(),
                            font: "Default".to_string(),
                            size: 10.0,
                            flags: 0,
                            chars: vec![RawdictCharWireDto {
                                c: "R".to_string(),
                                bbox: [0.0, 0.0, 10.0, 20.0],
                            }],
                        }],
                    }],
                }],
            }),
            words: vec![],
            sidecar: serde_json::Value::Null,
            diagnostics: serde_json::Value::Null,
        };

        let elements = vec![LayoutElementDto {
            element_type: "image".to_string(),
            bbox: [0.0, 50.0, 100.0, 150.0],
            order: 0,
            text: None,
            table_index: None,
            image_index: Some(1),
            lines: vec![],
        }];

        let page_json = export_page_to_json(&norm, &elements, &[], 2);
        assert_eq!(page_json["index"], 2);
        assert_eq!(page_json["size"]["width"], 500.0);
        assert_eq!(page_json["size"]["height"], 700.0);
        assert_eq!(page_json["rotation"], 0);
        assert_eq!(page_json["page_type"], "scanned");
        assert_eq!(page_json["blocks"][0]["text"], "Rawdict text");
        assert_eq!(page_json["layout_elements"][0]["type"], "image");
        assert!(page_json["layout_elements"][0]["content"].is_null());
    }
}
