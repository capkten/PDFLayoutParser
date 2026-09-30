use crate::clustering::{make_rect4, Rect4Dto};
use crate::DrawingInfo;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireDrawingLine {
    pub schema_version: i64, // 固定 1
    pub rect: Rect4Dto,
    pub width: Option<f64>,
    pub color: Option<f64>,
    pub source_order: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireDrawingDto {
    pub schema_version: i64, // 固定 1
    pub kind: String,        // "s" | "f" | "fs" | "unknown"
    pub path_type: String,   // "stroked" | "filled" | "stroked_filled" | ...
    pub lines: Vec<WireDrawingLine>,
    pub rect: Rect4Dto,
    pub fill: Option<Vec<f64>>,
    pub stroke: Option<Vec<f64>>,
    pub clip: Option<Rect4Dto>,
    pub source_order: usize,
    pub raw_source_position: Vec<i64>,
    pub color: Option<Vec<f64>>,
    pub width: Option<f64>,
    pub items: Vec<serde_json::Value>, // 例如 ["l", [x0, y0], [x1, y1]]
}

/// 规范化原始 PDFium 绘图对象至与 PyMuPDF / rust_adapter 兼容的绘图结构及诊断信息。
///
/// 路径类型映射：
/// - "stroked" -> "s"
/// - "filled" -> "f"
/// - "stroked_filled" -> "fs"
/// - 其他 -> "unknown"
///
/// 指令解析与线段提取：
/// - "l"：构造 `["l", p0, p1]`，并提取轴对齐包围盒计入 `lines`
/// - "re"：构造 `["re", [rx0, ry0, rx1, ry1]]`，并提取包围盒计入 `lines`
/// - "c"：构造 `["c", p0, p1, ...]`，不生成 line
///
/// 诊断收集：
/// - `path_type == "unknown"` 或 `kind == "unknown"`：记录 `unknown_path_type`
/// - 指令包含 `"c"`：记录 `curve_item_ignored`
pub fn normalize_drawings(
    raw_drawings: &[DrawingInfo],
) -> (Vec<WireDrawingDto>, Vec<serde_json::Value>) {
    let mut wire_drawings = Vec::with_capacity(raw_drawings.len());
    let mut diagnostics = Vec::new();

    for raw_d in raw_drawings {
        let (norm_type, is_unknown) = match raw_d.path_type.as_str() {
            "stroked" => ("s", false),
            "filled" => ("f", false),
            "stroked_filled" => ("fs", false),
            _ => ("unknown", true),
        };

        if is_unknown {
            diagnostics.push(serde_json::json!({
                "type": "unknown_path_type",
                "drawing_index": raw_d.drawing_index,
                "path_type": raw_d.path_type,
            }));
        }

        let line_color = raw_d
            .color
            .as_ref()
            .and_then(|c| if c.len() == 1 { Some(c[0]) } else { None });

        let mut items = Vec::new();
        let mut lines = Vec::new();

        for (item_idx, item) in raw_d.items.iter().enumerate() {
            match item.cmd.as_str() {
                "l" => {
                    if item.points.len() >= 2 {
                        let p0 = item.points[0];
                        let p1 = item.points[1];
                        items.push(serde_json::json!(["l", [p0[0], p0[1]], [p1[0], p1[1]]]));
                        let min_x = p0[0].min(p1[0]);
                        let min_y = p0[1].min(p1[1]);
                        let max_x = p0[0].max(p1[0]);
                        let max_y = p0[1].max(p1[1]);
                        lines.push(WireDrawingLine {
                            schema_version: 1,
                            rect: make_rect4(min_x, min_y, max_x, max_y),
                            width: Some(raw_d.width),
                            color: line_color,
                            source_order: item_idx,
                        });
                    }
                }
                "re" => {
                    let (rx0, ry0, rx1, ry1) = if item.points.len() >= 2 {
                        let rx0 = item.points.iter().map(|p| p[0]).fold(f64::INFINITY, f64::min);
                        let ry0 = item.points.iter().map(|p| p[1]).fold(f64::INFINITY, f64::min);
                        let rx1 = item.points.iter().map(|p| p[0]).fold(f64::NEG_INFINITY, f64::max);
                        let ry1 = item.points.iter().map(|p| p[1]).fold(f64::NEG_INFINITY, f64::max);
                        (rx0, ry0, rx1, ry1)
                    } else {
                        (raw_d.rect[0], raw_d.rect[1], raw_d.rect[2], raw_d.rect[3])
                    };
                    items.push(serde_json::json!(["re", [rx0, ry0, rx1, ry1]]));
                    lines.push(WireDrawingLine {
                        schema_version: 1,
                        rect: make_rect4(rx0, ry0, rx1, ry1),
                        width: Some(raw_d.width),
                        color: line_color,
                        source_order: item_idx,
                    });
                }
                "c" => {
                    let mut c_arr = Vec::with_capacity(item.points.len() + 1);
                    c_arr.push(serde_json::Value::String("c".to_string()));
                    for pt in &item.points {
                        c_arr.push(serde_json::json!([pt[0], pt[1]]));
                    }
                    items.push(serde_json::Value::Array(c_arr));

                    diagnostics.push(serde_json::json!({
                        "type": "curve_item_ignored",
                        "drawing_index": raw_d.drawing_index,
                    }));
                }
                _ => {}
            }
        }

        let wire_rect = make_rect4(
            raw_d.rect[0],
            raw_d.rect[1],
            raw_d.rect[2],
            raw_d.rect[3],
        );

        wire_drawings.push(WireDrawingDto {
            schema_version: 1,
            kind: norm_type.to_string(),
            path_type: raw_d.path_type.clone(),
            lines,
            rect: wire_rect,
            fill: raw_d.fill.clone(),
            stroke: None,
            clip: None,
            source_order: raw_d.drawing_index,
            raw_source_position: vec![raw_d.drawing_index as i64],
            color: raw_d.color.clone(),
            width: Some(raw_d.width),
            items,
        });
    }

    (wire_drawings, diagnostics)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::DrawingItem;
    use serde_json::json;

    #[test]
    fn test_drawings_stroked_line() {
        let raw = vec![DrawingInfo {
            drawing_index: 0,
            path_type: "stroked".to_string(),
            rect: [0.0, 0.0, 100.0, 0.0],
            width: 1.5,
            color: Some(vec![0.0, 0.0, 0.0]),
            fill: None,
            items: vec![DrawingItem {
                cmd: "l".to_string(),
                points: vec![[0.0, 0.0], [100.0, 0.0]],
            }],
        }];

        let (dtos, diags) = normalize_drawings(&raw);
        assert_eq!(dtos.len(), 1);
        assert!(diags.is_empty());

        let dto = &dtos[0];
        assert_eq!(dto.schema_version, 1);
        assert_eq!(dto.kind, "s");
        assert_eq!(dto.path_type, "stroked");
        assert_eq!(dto.width, Some(1.5));
        assert_eq!(dto.source_order, 0);
        assert_eq!(dto.raw_source_position, vec![0]);
        assert_eq!(dto.rect, make_rect4(0.0, 0.0, 100.0, 0.0));
        assert_eq!(dto.items.len(), 1);
        assert_eq!(dto.items[0], json!(["l", [0.0, 0.0], [100.0, 0.0]]));

        assert_eq!(dto.lines.len(), 1);
        let line = &dto.lines[0];
        assert_eq!(line.schema_version, 1);
        assert_eq!(line.rect, make_rect4(0.0, 0.0, 100.0, 0.0));
        assert_eq!(line.width, Some(1.5));
        assert_eq!(line.color, None); // RGB vector -> scalar color is None
        assert_eq!(line.source_order, 0);
    }

    #[test]
    fn test_drawings_filled_rect() {
        let raw = vec![DrawingInfo {
            drawing_index: 1,
            path_type: "filled".to_string(),
            rect: [10.0, 20.0, 50.0, 60.0],
            width: 0.0,
            color: None,
            fill: Some(vec![0.8, 0.8, 0.8]),
            items: vec![DrawingItem {
                cmd: "re".to_string(),
                points: vec![[10.0, 20.0], [50.0, 60.0]],
            }],
        }];

        let (dtos, diags) = normalize_drawings(&raw);
        assert_eq!(dtos.len(), 1);
        assert!(diags.is_empty());

        let dto = &dtos[0];
        assert_eq!(dto.kind, "f");
        assert_eq!(dto.path_type, "filled");
        assert_eq!(dto.items.len(), 1);
        assert_eq!(dto.items[0], json!(["re", [10.0, 20.0, 50.0, 60.0]]));
        assert_eq!(dto.lines.len(), 1);
        assert_eq!(dto.lines[0].rect, make_rect4(10.0, 20.0, 50.0, 60.0));
        assert_eq!(dto.lines[0].source_order, 0);
    }

    #[test]
    fn test_drawings_path_type_mappings() {
        let cases = vec![
            ("stroked", "s", false),
            ("filled", "f", false),
            ("stroked_filled", "fs", false),
            ("unknown", "unknown", true),
            ("other_custom", "unknown", true),
        ];

        for (idx, (p_type, expected_kind, has_diag)) in cases.into_iter().enumerate() {
            let raw = vec![DrawingInfo {
                drawing_index: idx,
                path_type: p_type.to_string(),
                rect: [0.0, 0.0, 10.0, 10.0],
                width: 1.0,
                color: None,
                fill: None,
                items: vec![],
            }];

            let (dtos, diags) = normalize_drawings(&raw);
            assert_eq!(dtos.len(), 1);
            assert_eq!(dtos[0].kind, expected_kind);
            assert_eq!(dtos[0].path_type, p_type);
            if has_diag {
                assert_eq!(diags.len(), 1);
                assert_eq!(diags[0]["type"], "unknown_path_type");
                assert_eq!(diags[0]["drawing_index"], idx);
                assert_eq!(diags[0]["path_type"], p_type);
            } else {
                assert!(diags.is_empty());
            }
        }
    }

    #[test]
    fn test_drawings_diagnostics_unknown_path_and_curve() {
        let raw = vec![
            DrawingInfo {
                drawing_index: 5,
                path_type: "unknown".to_string(),
                rect: [0.0, 0.0, 20.0, 20.0],
                width: 1.0,
                color: None,
                fill: None,
                items: vec![DrawingItem {
                    cmd: "l".to_string(),
                    points: vec![[0.0, 0.0], [20.0, 20.0]],
                }],
            },
            DrawingInfo {
                drawing_index: 6,
                path_type: "stroked".to_string(),
                rect: [10.0, 10.0, 30.0, 30.0],
                width: 2.0,
                color: None,
                fill: None,
                items: vec![DrawingItem {
                    cmd: "c".to_string(),
                    points: vec![
                        [10.0, 10.0],
                        [15.0, 20.0],
                        [25.0, 20.0],
                        [30.0, 30.0],
                    ],
                }],
            },
            DrawingInfo {
                drawing_index: 7,
                path_type: "mystery".to_string(),
                rect: [0.0, 0.0, 50.0, 50.0],
                width: 1.0,
                color: None,
                fill: None,
                items: vec![DrawingItem {
                    cmd: "c".to_string(),
                    points: vec![[0.0, 0.0], [10.0, 10.0]],
                }],
            },
        ];

        let (dtos, diags) = normalize_drawings(&raw);
        assert_eq!(dtos.len(), 3);
        assert_eq!(diags.len(), 4);

        // Drawing 5: unknown_path_type
        assert_eq!(diags[0]["type"], "unknown_path_type");
        assert_eq!(diags[0]["drawing_index"], 5);
        assert_eq!(diags[0]["path_type"], "unknown");

        // Drawing 6: curve_item_ignored
        assert_eq!(diags[1]["type"], "curve_item_ignored");
        assert_eq!(diags[1]["drawing_index"], 6);
        assert_eq!(
            dtos[1].items[0],
            json!(["c", [10.0, 10.0], [15.0, 20.0], [25.0, 20.0], [30.0, 30.0]])
        );
        // Drawing 6 has curve, so lines must be empty
        assert!(dtos[1].lines.is_empty());

        // Drawing 7: unknown_path_type AND curve_item_ignored
        assert_eq!(diags[2]["type"], "unknown_path_type");
        assert_eq!(diags[2]["drawing_index"], 7);
        assert_eq!(diags[3]["type"], "curve_item_ignored");
        assert_eq!(diags[3]["drawing_index"], 7);
    }

    #[test]
    fn test_drawings_grayscale_scalar_color() {
        let raw = vec![
            DrawingInfo {
                drawing_index: 0,
                path_type: "stroked".to_string(),
                rect: [0.0, 0.0, 10.0, 0.0],
                width: 1.0,
                color: Some(vec![0.5]), // scalar grayscale
                fill: None,
                items: vec![DrawingItem {
                    cmd: "l".to_string(),
                    points: vec![[0.0, 0.0], [10.0, 0.0]],
                }],
            },
            DrawingInfo {
                drawing_index: 1,
                path_type: "stroked".to_string(),
                rect: [0.0, 0.0, 10.0, 0.0],
                width: 1.0,
                color: Some(vec![0.2, 0.4, 0.6]), // 3-element RGB
                fill: None,
                items: vec![DrawingItem {
                    cmd: "l".to_string(),
                    points: vec![[0.0, 0.0], [10.0, 0.0]],
                }],
            },
        ];

        let (dtos, _) = normalize_drawings(&raw);
        assert_eq!(dtos[0].lines[0].color, Some(0.5));
        assert_eq!(dtos[1].lines[0].color, None);
    }

    #[test]
    fn test_drawings_wire_dto_serialization_contract() {
        let line = WireDrawingLine {
            schema_version: 1,
            rect: make_rect4(1.0, 2.0, 3.0, 4.0),
            width: Some(1.0),
            color: None,
            source_order: 0,
        };
        let dto = WireDrawingDto {
            schema_version: 1,
            kind: "s".to_string(),
            path_type: "stroked".to_string(),
            lines: vec![line],
            rect: make_rect4(1.0, 2.0, 3.0, 4.0),
            fill: None,
            stroke: None,
            clip: None,
            source_order: 0,
            raw_source_position: vec![0],
            color: None,
            width: Some(1.0),
            items: vec![json!(["l", [1.0, 2.0], [3.0, 4.0]])],
        };

        let json_str = serde_json::to_string(&dto).unwrap();
        assert!(json_str.contains("\"schema_version\":1"));
        assert!(json_str.contains("\"kind\":\"s\""));
        assert!(json_str.contains("\"path_type\":\"stroked\""));

        let deserialized: WireDrawingDto = serde_json::from_str(&json_str).unwrap();
        assert_eq!(deserialized, dto);
    }
}
