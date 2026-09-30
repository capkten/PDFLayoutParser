use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PageClassification {
    pub page_type: String, // "vector" | "scanned"
    pub reason: Option<String>,
    pub mapping_status: String, // "valid" | "invalid" | "unknown"
    pub evidence: serde_json::Value,
}

pub fn is_vector_page(c: &PageClassification) -> bool {
    c.page_type == "vector" && c.mapping_status == "valid"
}

fn is_valid_bbox(bbox: &[f64; 4]) -> bool {
    bbox.iter().all(|v| v.is_finite()) && bbox[0] <= bbox[2] && bbox[1] <= bbox[3]
}

pub fn classify_raw_page(raw_page: &crate::PdfiumRawPage) -> PageClassification {
    // 1. 无可见文本 -> empty_text
    let all_text: String = raw_page.spans.iter().map(|s| s.text.as_str()).collect();
    let clean_text = all_text.trim();
    let diag_visible_scalars = raw_page.mapping_diagnostics.visible_text_scalar_count;

    if raw_page.spans.is_empty() || clean_text.is_empty() {
        let diag_status = &raw_page.mapping_diagnostics.mapping_status;
        let mapping_status = if diag_status == "valid" {
            "valid".to_string()
        } else {
            "unknown".to_string()
        };
        return PageClassification {
            page_type: "scanned".to_string(),
            reason: Some("empty_text".to_string()),
            mapping_status,
            evidence: serde_json::json!({
                "visible_text_scalar_count": diag_visible_scalars,
                "text_length": all_text.chars().count(),
                "clean_text_length": clean_text.chars().count(),
                "span_count": raw_page.spans.len(),
            }),
        };
    }

    // 2. 替换或控制字符 -> invalid_unicode
    let mut replacement_count = raw_page.mapping_diagnostics.replacement_char_count;
    let mut control_count = raw_page.mapping_diagnostics.control_char_count;
    if raw_page.mapping_diagnostics.classification_reason.as_deref() == Some("invalid_unicode")
        && replacement_count == 0
    {
        replacement_count = 1;
    }

    for span in &raw_page.spans {
        for ch in span.text.chars() {
            if ch == '\u{FFFD}' {
                replacement_count += 1;
            } else if crate::is_illegal_control_char(ch) {
                control_count += 1;
            }
        }
        for c_info in &span.characters {
            for ch in c_info.c.chars() {
                if ch == '\u{FFFD}' {
                    replacement_count += 1;
                } else if crate::is_illegal_control_char(ch) {
                    control_count += 1;
                }
            }
        }
    }

    if replacement_count > 0 || control_count > 0 {
        return PageClassification {
            page_type: "scanned".to_string(),
            reason: Some("invalid_unicode".to_string()),
            mapping_status: "invalid".to_string(),
            evidence: serde_json::json!({
                "replacement_char_count": replacement_count,
                "control_char_count": control_count,
            }),
        };
    }

    // 3. 文本和字符序列不一致 -> invalid_unicode_mapping
    let v_count = raw_page.mapping_diagnostics.visible_text_scalar_count;
    let e_count = raw_page.mapping_diagnostics.extracted_char_scalar_count;
    let s_count = raw_page.mapping_diagnostics.synthetic_space_count;
    let mut has_mapping_mismatch = false;
    let mut mismatch_evidence = serde_json::Map::new();

    if v_count != (e_count + s_count) {
        has_mapping_mismatch = true;
        mismatch_evidence.insert("visible_text_scalar_count".to_string(), serde_json::json!(v_count));
        mismatch_evidence.insert("extracted_char_scalar_count".to_string(), serde_json::json!(e_count));
        mismatch_evidence.insert("synthetic_space_count".to_string(), serde_json::json!(s_count));
    }
    if raw_page.mapping_diagnostics.classification_reason.as_deref() == Some("invalid_unicode_mapping") {
        has_mapping_mismatch = true;
    }

    for span in &raw_page.spans {
        let char_text: String = span.characters.iter().map(|c| c.c.as_str()).collect();
        if char_text == span.text || char_text == span.text.trim_end_matches(' ') {
            continue;
        }
        has_mapping_mismatch = true;
        mismatch_evidence.insert("span_order".to_string(), serde_json::json!(span.order));
        mismatch_evidence.insert("expected_text".to_string(), serde_json::json!(span.text));
        mismatch_evidence.insert("extracted_char_text".to_string(), serde_json::json!(char_text));
        mismatch_evidence.insert("text_length".to_string(), serde_json::json!(span.text.chars().count()));
        mismatch_evidence.insert("char_count".to_string(), serde_json::json!(span.characters.len()));
        break;
    }

    if has_mapping_mismatch {
        return PageClassification {
            page_type: "scanned".to_string(),
            reason: Some("invalid_unicode_mapping".to_string()),
            mapping_status: "invalid".to_string(),
            evidence: serde_json::Value::Object(mismatch_evidence),
        };
    }

    // 4. 非有限、倒置或缺失字符 bbox -> invalid_geometry
    let mut has_geom_error = false;
    let mut geom_evidence = serde_json::Map::new();

    if raw_page.mapping_diagnostics.classification_reason.as_deref() == Some("invalid_geometry") {
        has_geom_error = true;
    }

    for span in &raw_page.spans {
        if !is_valid_bbox(&span.bbox) {
            has_geom_error = true;
            geom_evidence.insert("invalid_span_bbox".to_string(), serde_json::json!(span.bbox));
            geom_evidence.insert("span_order".to_string(), serde_json::json!(span.order));
            break;
        }

        for ch in &span.characters {
            if !is_valid_bbox(&ch.bbox) {
                has_geom_error = true;
                geom_evidence.insert("invalid_character_bbox".to_string(), serde_json::json!(ch.bbox));
                geom_evidence.insert("char_index".to_string(), serde_json::json!(ch.char_index));
                break;
            }
        }
        if has_geom_error {
            break;
        }
    }

    if has_geom_error {
        return PageClassification {
            page_type: "scanned".to_string(),
            reason: Some("invalid_geometry".to_string()),
            mapping_status: "invalid".to_string(),
            evidence: serde_json::Value::Object(geom_evidence),
        };
    }

    // 5. 缺少 mapping_diagnostics 或状态为 unknown -> unknown_unicode_mapping
    let diag_status = raw_page.mapping_diagnostics.mapping_status.as_str();
    if diag_status == "unknown" || !matches!(diag_status, "valid" | "invalid" | "empty") {
        return PageClassification {
            page_type: "scanned".to_string(),
            reason: Some("unknown_unicode_mapping".to_string()),
            mapping_status: "unknown".to_string(),
            evidence: serde_json::json!({
                "has_mapping_diagnostics": true,
                "mapping_diagnostics": serde_json::to_value(&raw_page.mapping_diagnostics).unwrap_or_default(),
            }),
        };
    }

    // Extra gate: if mapping diagnostics explicitly marked invalid
    if diag_status == "invalid" {
        let reason = raw_page
            .mapping_diagnostics
            .classification_reason
            .clone()
            .unwrap_or_else(|| "invalid_unicode_mapping".to_string());
        return PageClassification {
            page_type: "scanned".to_string(),
            reason: Some(reason),
            mapping_status: "invalid".to_string(),
            evidence: serde_json::json!({
                "diagnostics": serde_json::to_value(&raw_page.mapping_diagnostics).unwrap_or_default(),
            }),
        };
    }

    // 6. 其余 -> vector/valid
    PageClassification {
        page_type: "vector".to_string(),
        reason: None,
        mapping_status: "valid".to_string(),
        evidence: serde_json::json!({
            "visible_text_scalar_count": raw_page.mapping_diagnostics.visible_text_scalar_count,
            "extracted_char_scalar_count": raw_page.mapping_diagnostics.extracted_char_scalar_count,
            "span_count": raw_page.spans.len(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{CharInfo, MappingDiagnostics, PdfiumRawPage, ProvenanceSidecar, SpanInfo};

    fn make_test_page(text: &str) -> PdfiumRawPage {
        let chars: Vec<CharInfo> = text
            .chars()
            .enumerate()
            .map(|(i, c)| CharInfo {
                c: c.to_string(),
                bbox: [0.0, 0.0, 1.0, 1.0],
                char_index: i,
            })
            .collect();
        let scalar_count = text.chars().count();
        let replacement_count = text.chars().filter(|&c| c == '\u{FFFD}').count();
        let control_count = text.chars().filter(|&c| crate::is_illegal_control_char(c)).count();

        let span = SpanInfo {
            order: 0,
            text: text.to_string(),
            bbox: [0.0, 0.0, 10.0, 10.0],
            font: Some("TestFont".to_string()),
            size: Some(12.0),
            flags: None,
            render_mode: 0,
            is_invisible: false,
            provenance: ProvenanceSidecar {
                page_index: 0,
                pdfium_object_index: 0,
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

        PdfiumRawPage {
            schema_version: "1.1".to_string(),
            page_index: 0,
            width: 100.0,
            height: 100.0,
            rotation: 0,
            crop_box: [0.0, 0.0, 100.0, 100.0],
            media_box: [0.0, 0.0, 100.0, 100.0],
            has_invisible_text: false,
            spans: vec![span],
            drawings: vec![],
            mapping_diagnostics: MappingDiagnostics {
                visible_text_scalar_count: scalar_count,
                extracted_char_scalar_count: scalar_count,
                synthetic_space_count: 0,
                replacement_char_count: replacement_count,
                control_char_count: control_count,
                mapping_status: "valid".to_string(),
                classification_reason: None,
            },
        }
    }

    #[test]
    fn test_clean_page_is_vector() {
        let page = make_test_page("Hello");
        let result = classify_raw_page(&page);
        assert_eq!(result.page_type, "vector");
        assert_eq!(result.reason, None);
        assert_eq!(result.mapping_status, "valid");
        assert!(is_vector_page(&result));
    }

    #[test]
    fn test_empty_text_fails_closed_as_scanned() {
        let page = make_test_page("");
        let result = classify_raw_page(&page);
        assert_eq!(result.page_type, "scanned");
        assert_eq!(result.reason.as_deref(), Some("empty_text"));
        assert_eq!(result.mapping_status, "valid");
        assert!(!is_vector_page(&result));

        let ws_page = make_test_page("   \n\t  \r\n");
        let ws_result = classify_raw_page(&ws_page);
        assert_eq!(ws_result.page_type, "scanned");
        assert_eq!(ws_result.reason.as_deref(), Some("empty_text"));
        assert!(!is_vector_page(&ws_result));

        let mut no_spans = make_test_page("A");
        no_spans.spans.clear();
        let no_spans_result = classify_raw_page(&no_spans);
        assert_eq!(no_spans_result.page_type, "scanned");
        assert_eq!(no_spans_result.reason.as_deref(), Some("empty_text"));
        assert!(!is_vector_page(&no_spans_result));
    }

    #[test]
    fn test_invalid_unicode_chars_and_controls() {
        let page = make_test_page("正常\u{FFFD}文本");
        let result = classify_raw_page(&page);
        assert_eq!(result.page_type, "scanned");
        assert_eq!(result.reason.as_deref(), Some("invalid_unicode"));
        assert_eq!(result.mapping_status, "invalid");
        assert!(!is_vector_page(&result));

        let null_page = make_test_page("Hello\0World");
        let null_result = classify_raw_page(&null_page);
        assert_eq!(null_result.page_type, "scanned");
        assert_eq!(null_result.reason.as_deref(), Some("invalid_unicode"));
        assert_eq!(null_result.mapping_status, "invalid");

        let bell_page = make_test_page("Hello\x07World");
        let bell_result = classify_raw_page(&bell_page);
        assert_eq!(bell_result.page_type, "scanned");
        assert_eq!(bell_result.reason.as_deref(), Some("invalid_unicode"));

        // Legal whitespace controls are allowed
        let ws_allowed = make_test_page("Hello\tWorld\nLine2\r\nLine3");
        let ws_res = classify_raw_page(&ws_allowed);
        assert_eq!(ws_res.page_type, "vector");
        assert_eq!(ws_res.mapping_status, "valid");
        assert!(is_vector_page(&ws_res));
    }

    #[test]
    fn test_invalid_unicode_mapping_mismatch() {
        let mut page = make_test_page("中文");
        page.spans[0].characters = vec![CharInfo {
            c: "中".to_string(),
            bbox: [0.0, 0.0, 1.0, 1.0],
            char_index: 0,
        }];
        let result = classify_raw_page(&page);
        assert_eq!(result.page_type, "scanned");
        assert_eq!(result.reason.as_deref(), Some("invalid_unicode_mapping"));
        assert_eq!(result.mapping_status, "invalid");
        assert!(!is_vector_page(&result));

        // Content mismatch even if length matches
        let mut page2 = make_test_page("AB");
        page2.spans[0].characters[1].c = "C".to_string();
        let result2 = classify_raw_page(&page2);
        assert_eq!(result2.page_type, "scanned");
        assert_eq!(result2.reason.as_deref(), Some("invalid_unicode_mapping"));

        // Synthetic space count handling
        let mut page3 = make_test_page("正常文本 ");
        page3.spans[0].characters = "正常文本"
            .chars()
            .enumerate()
            .map(|(i, c)| CharInfo {
                c: c.to_string(),
                bbox: [0.0, 0.0, 1.0, 1.0],
                char_index: i,
            })
            .collect();
        page3.mapping_diagnostics.visible_text_scalar_count = 5;
        page3.mapping_diagnostics.extracted_char_scalar_count = 4;
        page3.mapping_diagnostics.synthetic_space_count = 1;
        let result3 = classify_raw_page(&page3);
        assert_eq!(result3.page_type, "vector");
        assert_eq!(result3.reason, None);
        assert_eq!(result3.mapping_status, "valid");
        assert!(is_vector_page(&result3));
    }

    #[test]
    fn test_invalid_geometry() {
        // Inverted x
        let mut page1 = make_test_page("A");
        page1.spans[0].characters[0].bbox = [2.0, 0.0, 1.0, 1.0];
        let res1 = classify_raw_page(&page1);
        assert_eq!(res1.page_type, "scanned");
        assert_eq!(res1.reason.as_deref(), Some("invalid_geometry"));
        assert_eq!(res1.mapping_status, "invalid");
        assert!(!is_vector_page(&res1));

        // Inverted y
        let mut page2 = make_test_page("A");
        page2.spans[0].characters[0].bbox = [0.0, 10.0, 5.0, 2.0];
        let res2 = classify_raw_page(&page2);
        assert_eq!(res2.page_type, "scanned");
        assert_eq!(res2.reason.as_deref(), Some("invalid_geometry"));

        // NaN
        let mut page3 = make_test_page("A");
        page3.spans[0].characters[0].bbox = [f64::NAN, 0.0, 5.0, 10.0];
        let res3 = classify_raw_page(&page3);
        assert_eq!(res3.page_type, "scanned");
        assert_eq!(res3.reason.as_deref(), Some("invalid_geometry"));

        // Inf
        let mut page4 = make_test_page("A");
        page4.spans[0].characters[0].bbox = [0.0, 0.0, f64::INFINITY, 10.0];
        let res4 = classify_raw_page(&page4);
        assert_eq!(res4.page_type, "scanned");
        assert_eq!(res4.reason.as_deref(), Some("invalid_geometry"));

        // Span bbox invalid
        let mut page5 = make_test_page("A");
        page5.spans[0].bbox = [10.0, 0.0, 5.0, 10.0];
        let res5 = classify_raw_page(&page5);
        assert_eq!(res5.page_type, "scanned");
        assert_eq!(res5.reason.as_deref(), Some("invalid_geometry"));
    }

    #[test]
    fn test_unknown_or_invalid_diagnostics() {
        let mut page1 = make_test_page("Hello");
        page1.mapping_diagnostics.mapping_status = "unknown".to_string();
        let res1 = classify_raw_page(&page1);
        assert_eq!(res1.page_type, "scanned");
        assert_eq!(res1.reason.as_deref(), Some("unknown_unicode_mapping"));
        assert_eq!(res1.mapping_status, "unknown");
        assert!(!is_vector_page(&res1));

        let mut page2 = make_test_page("Hello");
        page2.mapping_diagnostics.mapping_status = "corrupted".to_string();
        let res2 = classify_raw_page(&page2);
        assert_eq!(res2.page_type, "scanned");
        assert_eq!(res2.reason.as_deref(), Some("unknown_unicode_mapping"));
        assert_eq!(res2.mapping_status, "unknown");

        let mut page3 = make_test_page("Hello");
        page3.mapping_diagnostics.mapping_status = "invalid".to_string();
        page3.mapping_diagnostics.classification_reason = Some("custom_error".to_string());
        let res3 = classify_raw_page(&page3);
        assert_eq!(res3.page_type, "scanned");
        assert_eq!(res3.reason.as_deref(), Some("custom_error"));
        assert_eq!(res3.mapping_status, "invalid");
    }

    #[test]
    fn test_precedence_order_enforced() {
        // 1. empty text vs invalid unicode: empty text comes first
        let mut page1 = make_test_page("");
        page1.mapping_diagnostics.replacement_char_count = 1;
        let res1 = classify_raw_page(&page1);
        assert_eq!(res1.reason.as_deref(), Some("empty_text"));

        // 2. invalid unicode vs invalid mapping: invalid unicode comes first
        let mut page2 = make_test_page("A\u{FFFD}B");
        page2.spans[0].characters = vec![CharInfo {
            c: "A".to_string(),
            bbox: [0.0, 0.0, 1.0, 1.0],
            char_index: 0,
        }];
        let res2 = classify_raw_page(&page2);
        assert_eq!(res2.reason.as_deref(), Some("invalid_unicode"));

        // 3. invalid mapping vs invalid geometry: invalid mapping comes first
        let mut page3 = make_test_page("AB");
        page3.spans[0].characters = vec![CharInfo {
            c: "A".to_string(),
            bbox: [5.0, 0.0, 1.0, 1.0], // inverted
            char_index: 0,
        }];
        let res3 = classify_raw_page(&page3);
        assert_eq!(res3.reason.as_deref(), Some("invalid_unicode_mapping"));

        // 4. invalid geometry vs unknown mapping: invalid geometry comes first
        let mut page4 = make_test_page("A");
        page4.spans[0].characters[0].bbox = [5.0, 0.0, 1.0, 1.0];
        page4.mapping_diagnostics.mapping_status = "unknown".to_string();
        let res4 = classify_raw_page(&page4);
        assert_eq!(res4.reason.as_deref(), Some("invalid_geometry"));
    }

    #[test]
    fn test_is_vector_page_matrix() {
        let valid_vector = PageClassification {
            page_type: "vector".to_string(),
            reason: None,
            mapping_status: "valid".to_string(),
            evidence: serde_json::json!({}),
        };
        assert!(is_vector_page(&valid_vector));

        let invalid_vector = PageClassification {
            page_type: "vector".to_string(),
            reason: None,
            mapping_status: "invalid".to_string(),
            evidence: serde_json::json!({}),
        };
        assert!(!is_vector_page(&invalid_vector));

        let unknown_vector = PageClassification {
            page_type: "vector".to_string(),
            reason: None,
            mapping_status: "unknown".to_string(),
            evidence: serde_json::json!({}),
        };
        assert!(!is_vector_page(&unknown_vector));

        let scanned = PageClassification {
            page_type: "scanned".to_string(),
            reason: Some("empty_text".to_string()),
            mapping_status: "valid".to_string(),
            evidence: serde_json::json!({}),
        };
        assert!(!is_vector_page(&scanned));
    }
}
