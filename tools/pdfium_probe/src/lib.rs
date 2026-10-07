use pdfium_render::prelude::*;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};

pub mod classifier;
pub mod clustering;
pub mod detector;
pub mod drawings;
pub mod json_export;
pub mod layout;
pub mod markdown;
pub mod normalizer;
pub mod pipeline;
pub mod public_api;
pub mod table_engine;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct CharInfo {
    pub c: String,
    pub bbox: [f64; 4],
    pub char_index: usize, // 字符在当前原子 TextObject 内的 0-indexed 局部位置
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct ProvenanceSidecar {
    pub page_index: usize,
    pub pdfium_object_index: usize, // 在 page.objects() 中的真实原始序号
    pub character_count: usize,
    pub char_start_index: usize,    // 当前 TextObject 字符起止范围 [start, end)
    pub char_end_index: usize,
    pub char_indices: Vec<usize>,   // 每个字符的局部索引序列
    pub is_derived: bool,           // 原生探针输出固定为 false
    pub derived_block: Option<i64>, // 未做 block 聚类，诚实标记为 None
    pub derived_line: Option<i64>,  // 未做 line 聚类，诚实标记为 None
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct SpanInfo {
    pub order: i64,
    pub text: String,
    pub bbox: [f64; 4],
    pub font: Option<String>,
    pub size: Option<f64>,
    pub flags: Option<i64>, // PDFium 原生 TextObject 无 PyMuPDF 风格 flags，显式为 None
    pub render_mode: i32,
    pub is_invisible: bool,
    pub provenance: ProvenanceSidecar,
    pub characters: Vec<CharInfo>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct DrawingItem {
    pub cmd: String,
    pub points: Vec<[f64; 2]>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct DrawingInfo {
    pub drawing_index: usize,
    pub path_type: String,
    pub rect: [f64; 4],
    pub width: f64,
    pub color: Option<Vec<f64>>,
    pub fill: Option<Vec<f64>>,
    pub items: Vec<DrawingItem>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct MappingDiagnostics {
    pub visible_text_scalar_count: usize,
    pub extracted_char_scalar_count: usize,
    #[serde(default)]
    pub synthetic_space_count: usize,
    pub replacement_char_count: usize,
    pub control_char_count: usize,
    pub mapping_status: String,
    pub classification_reason: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PdfiumRawPage {
    pub schema_version: String,
    pub page_index: usize,
    pub width: f64,
    pub height: f64,
    pub rotation: i64,
    pub crop_box: [f64; 4],
    pub media_box: [f64; 4],
    pub has_invisible_text: bool,
    pub spans: Vec<SpanInfo>,
    pub drawings: Vec<DrawingInfo>,
    pub mapping_diagnostics: MappingDiagnostics,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PdfiumRawSnapshot {
    pub schema_version: String,
    pub generator: String,
    pub source_file: String,
    pub source_file_sha256: String,
    pub native_library_sha256: String,
    pub native_library_expected_sha256: String,
    pub page_count: usize,
    pub pages: Vec<PdfiumRawPage>,
}

pub fn is_illegal_control_char(c: char) -> bool {
    (c < ' ' && c != '\n' && c != '\r' && c != '\t') || c == '\0' || ('\u{007F}'..='\u{009F}').contains(&c)
}

pub fn compute_file_sha256(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|e| format!("Failed to open {:?}: {}", path, e))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 8192];
    loop {
        let bytes_read = file.read(&mut buffer).map_err(|e| format!("Read error: {}", e))?;
        if bytes_read == 0 {
            break;
        }
        hasher.update(&buffer[..bytes_read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

pub fn verify_file_sha256(path: &Path, expected_sha256: &str) -> Result<String, String> {
    let actual_sha256 = compute_file_sha256(path)?;
    if actual_sha256.to_lowercase() != expected_sha256.to_lowercase() {
        return Err(format!(
            "SHA256 mismatch for {:?}:\n  expected: {}\n  actual:   {}",
            path, expected_sha256, actual_sha256
        ));
    }
    Ok(actual_sha256)
}

pub fn round4(v: f64) -> f64 {
    (v * 10000.0).round() / 10000.0
}

/// 将 PDF 原始用户空间点映射到未旋转局部页面坐标系（以 CropBox 左上角为原点，自顶向下）。
/// 契约说明：与 PyMuPDF rawdict 及现有生产 NativeSpanDto 严格对齐——保留局部坐标系，不随 page.rotation 交换轴向。
pub fn transform_point_to_page_coords(
    x: f64,
    y: f64,
    crop_x0: f64,
    crop_y1: f64,
) -> [f64; 2] {
    [round4(x - crop_x0), round4(crop_y1 - y)]
}

/// 将 PDF 原始用户空间点映射到视口坐标系（考虑 page.rotation 顺时针旋转后，以视口左上角为原点）。
pub fn transform_point_to_viewport(
    x: f64,
    y: f64,
    crop_x0: f64,
    crop_y0: f64,
    crop_x1: f64,
    crop_y1: f64,
    rotation: i64,
) -> [f64; 2] {
    let x_crop = x - crop_x0;
    let y_crop = y - crop_y0;

    let (vx, vy) = match rotation {
        90 => (y_crop, x_crop),
        180 => (crop_x1 - x, y_crop),
        270 => (crop_y1 - y, crop_x1 - x),
        _ => (x_crop, crop_y1 - y),
    };
    [round4(vx), round4(vy)]
}

pub fn transform_rect_coords(
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
    crop_x0: f64,
    crop_y1: f64,
) -> [f64; 4] {
    let p0 = transform_point_to_page_coords(x0, y0, crop_x0, crop_y1);
    let p1 = transform_point_to_page_coords(x1, y1, crop_x0, crop_y1);
    let min_x = p0[0].min(p1[0]);
    let min_y = p0[1].min(p1[1]);
    let max_x = p0[0].max(p1[0]);
    let max_y = p0[1].max(p1[1]);
    [round4(min_x), round4(min_y), round4(max_x), round4(max_y)]
}

pub fn transform_quad_with_matrix_to_page_coords(
    left: PdfPoints,
    bottom: PdfPoints,
    right: PdfPoints,
    top: PdfPoints,
    parent_matrix: PdfMatrix,
    crop_x0: f64,
    crop_y1: f64,
) -> [f64; 4] {
    let p1 = parent_matrix.apply_to_points(left, bottom);
    let p2 = parent_matrix.apply_to_points(left, top);
    let p3 = parent_matrix.apply_to_points(right, top);
    let p4 = parent_matrix.apply_to_points(right, bottom);
    let min_x = (p1.0.value as f64).min(p2.0.value as f64).min(p3.0.value as f64).min(p4.0.value as f64);
    let min_y = (p1.1.value as f64).min(p2.1.value as f64).min(p3.1.value as f64).min(p4.1.value as f64);
    let max_x = (p1.0.value as f64).max(p2.0.value as f64).max(p3.0.value as f64).max(p4.0.value as f64);
    let max_y = (p1.1.value as f64).max(p2.1.value as f64).max(p3.1.value as f64).max(p4.1.value as f64);
    transform_rect_coords(min_x, min_y, max_x, max_y, crop_x0, crop_y1)
}

fn process_page_object_text_recursive(
    obj: &PdfPageObject,
    parent_matrix: PdfMatrix,
    depth: usize,
    page_text: Option<&PdfPageText>,
    page_index: usize,
    crop_x0: f64,
    crop_y1: f64,
    order: &mut i64,
    obj_counter: &mut usize,
    spans: &mut Vec<SpanInfo>,
    visible_text_scalar_count: &mut usize,
    extracted_char_scalar_count: &mut usize,
    synthetic_space_count: &mut usize,
    replacement_char_count: &mut usize,
    control_char_count: &mut usize,
    has_invisible_text: &mut bool,
    has_char_mismatch: &mut bool,
    has_invalid_geometry: &mut bool,
) -> Result<(), Box<dyn std::error::Error>> {
    if depth > 16 {
        return Ok(());
    }

    if let Some(form) = obj.as_x_object_form_object() {
        let form_matrix = form.matrix().unwrap_or(PdfMatrix::IDENTITY);
        let child_parent_matrix = form_matrix.multiply(parent_matrix);
        for child in form.iter() {
            process_page_object_text_recursive(
                &child,
                child_parent_matrix,
                depth + 1,
                page_text,
                page_index,
                crop_x0,
                crop_y1,
                order,
                obj_counter,
                spans,
                visible_text_scalar_count,
                extracted_char_scalar_count,
                synthetic_space_count,
                replacement_char_count,
                control_char_count,
                has_invisible_text,
                has_char_mismatch,
                has_invalid_geometry,
            )?;
        }
        return Ok(());
    }

    let obj_idx = *obj_counter;
    *obj_counter += 1;

    if let Some(text_obj) = obj.as_text_object() {
        // 禁止使用 .trim() 盲目丢弃独立空格！保留原始字符串
        let text = text_obj.text();
        if text.is_empty() {
            return Ok(());
        }
        let bounds = text_obj.bounds()?;
        let bbox = transform_quad_with_matrix_to_page_coords(
            bounds.left(),
            bounds.bottom(),
            bounds.right(),
            bounds.top(),
            parent_matrix,
            crop_x0,
            crop_y1,
        );
        if !bbox[0].is_finite()
            || !bbox[1].is_finite()
            || !bbox[2].is_finite()
            || !bbox[3].is_finite()
            || bbox[0] > bbox[2]
            || bbox[1] > bbox[3]
        {
            *has_invalid_geometry = true;
        }

        for ch in text.chars() {
            *visible_text_scalar_count += 1;
            if ch == '\u{FFFD}' {
                *replacement_char_count += 1;
            } else if is_illegal_control_char(ch) {
                *control_char_count += 1;
            }
        }

        let font_name = Some(text_obj.font().name());
        let font_size = Some(round4(text_obj.unscaled_font_size().value as f64));

        let render_mode = text_obj.render_mode();
        let is_invisible = matches!(render_mode, PdfPageTextRenderMode::Invisible);
        let render_mode_int = match render_mode {
            PdfPageTextRenderMode::Unknown => -1,
            PdfPageTextRenderMode::FilledUnstroked => 0,
            PdfPageTextRenderMode::StrokedUnfilled => 1,
            PdfPageTextRenderMode::FilledThenStroked => 2,
            PdfPageTextRenderMode::Invisible => 3,
            _ => 0,
        };

        if is_invisible {
            *has_invisible_text = true;
        }

        let flags: Option<i64> = None; // 严禁伪造 PyMuPDF 的 64 位 flags，诚实标记为 None

        let mut chars_list = Vec::new();
        if let Some(ref pt) = page_text {
            if let Ok(chars) = text_obj.chars(pt) {
                for (ch_idx, ch) in chars.iter().enumerate() {
                    let c_str = ch.unicode_string().unwrap_or_default();
                    let c_bbox = if let Ok(b) = ch.loose_bounds() {
                        transform_rect_coords(
                            b.left().value as f64,
                            b.bottom().value as f64,
                            b.right().value as f64,
                            b.top().value as f64,
                            crop_x0,
                            crop_y1,
                        )
                    } else {
                        [0.0, 0.0, 0.0, 0.0]
                    };
                    if !c_bbox[0].is_finite()
                        || !c_bbox[1].is_finite()
                        || !c_bbox[2].is_finite()
                        || !c_bbox[3].is_finite()
                        || c_bbox[0] > c_bbox[2]
                        || c_bbox[1] > c_bbox[3]
                    {
                        *has_invalid_geometry = true;
                    }
                    *extracted_char_scalar_count += c_str.chars().count();
                    chars_list.push(CharInfo {
                        c: c_str,
                        bbox: c_bbox,
                        char_index: ch_idx,
                    });
                }
            } else {
                *has_char_mismatch = true;
            }
        } else {
            *has_char_mismatch = true;
        }

        // 映射不完整只保留诊断，不再合成估算尾部字符
        let mut extracted_text = String::new();
        for ci in &chars_list {
            extracted_text.push_str(&ci.c);
        }
        if extracted_text == text {
            // 完全一致
        } else if text.trim_end_matches(' ') == extracted_text {
            // TextPage 在对象边界合成的末尾空格，不视为字符映射缺失
            *synthetic_space_count += text.chars().count().saturating_sub(extracted_text.chars().count());
        } else {
            *has_char_mismatch = true;
        }

        // 若 TextPage 在对象边界合成了末尾空格且 chars_list 未包含，物化该空格为 CharInfo
        // 保证 downstream derive_words 识别到字符级边界空格
        let chars_end_with_space = chars_list
            .last()
            .map(|ci| ci.c.ends_with(' '))
            .unwrap_or(false);
        if text.ends_with(' ') && !chars_end_with_space {
            let missing_spaces = text.chars().rev().take_while(|&c| c == ' ').count();
            let space_w = font_size.unwrap_or(10.0).max(1.0) * 0.25;
            let mut cur_x1 = chars_list.last().map(|c| c.bbox[2]).unwrap_or(bbox[0]);
            let y0 = chars_list.last().map(|c| c.bbox[1]).unwrap_or(bbox[1]);
            let y1 = chars_list.last().map(|c| c.bbox[3]).unwrap_or(bbox[3]);
            for _ in 0..missing_spaces {
                let sp_bbox = [cur_x1, y0, cur_x1 + space_w, y1];
                cur_x1 += space_w;
                let ch_idx = chars_list.len();
                chars_list.push(CharInfo {
                    c: " ".to_string(),
                    bbox: sp_bbox,
                    char_index: ch_idx,
                });
            }
        }

        let total_chars_count = chars_list.len();
        let provenance = ProvenanceSidecar {
            page_index,
            pdfium_object_index: obj_idx,
            character_count: total_chars_count,
            char_start_index: 0,
            char_end_index: total_chars_count,
            char_indices: (0..total_chars_count).collect(),
            is_derived: false,
            derived_block: None,
            derived_line: None,
        };

        spans.push(SpanInfo {
            order: *order,
            text,
            bbox,
            font: font_name,
            size: font_size,
            flags,
            render_mode: render_mode_int,
            is_invisible,
            provenance,
            characters: chars_list,
        });
        *order += 1;
    }

    Ok(())
}

fn process_page_object_drawing_recursive(
    obj: &PdfPageObject,
    parent_matrix: PdfMatrix,
    depth: usize,
    crop_x0: f64,
    crop_y1: f64,
    drawing_idx: &mut usize,
    drawings: &mut Vec<DrawingInfo>,
) -> Result<(), Box<dyn std::error::Error>> {
    if depth > 16 {
        return Ok(());
    }

    if let Some(form) = obj.as_x_object_form_object() {
        let form_matrix = form.matrix().unwrap_or(PdfMatrix::IDENTITY);
        let child_parent_matrix = form_matrix.multiply(parent_matrix);
        for child in form.iter() {
            process_page_object_drawing_recursive(
                &child,
                child_parent_matrix,
                depth + 1,
                crop_x0,
                crop_y1,
                drawing_idx,
                drawings,
            )?;
        }
        return Ok(());
    }

    if let Some(path_obj) = obj.as_path_object() {
        let width_val = round4(path_obj.stroke_width().map(|w| w.value as f64).unwrap_or(1.0));
        let bounds = path_obj.bounds()?;
        let mut rect = transform_quad_with_matrix_to_page_coords(
            bounds.left(),
            bounds.bottom(),
            bounds.right(),
            bounds.top(),
            parent_matrix,
            crop_x0,
            crop_y1,
        );

        let path_type = match (path_obj.is_stroked(), path_obj.fill_mode()) {
            (Ok(is_stroked), Ok(fill_mode)) => {
                let is_filled = fill_mode != PdfPathFillMode::None;
                match (is_stroked, is_filled) {
                    (true, true) => "stroked_filled",
                    (true, false) => "stroked",
                    (false, true) => "filled",
                    (false, false) => "unknown",
                }
            }
            _ => "unknown",
        }
        .to_string();

        let mut items = Vec::new();
        let mut current_pt: Option<[f64; 2]> = None;
        let mut subpath_start: Option<[f64; 2]> = None;
        let mut pts_all: Vec<[f64; 2]> = Vec::new();

        let segments = match path_obj.matrix() {
            Ok(m) => path_obj.segments().transform(m.multiply(parent_matrix)),
            Err(_) => {
                if parent_matrix != PdfMatrix::IDENTITY {
                    path_obj.segments().transform(parent_matrix)
                } else {
                    path_obj.segments()
                }
            }
        };

        for seg in segments.iter() {
            let (pt_x, pt_y) = seg.point();
            let raw_x = pt_x.value as f64;
            let raw_y = pt_y.value as f64;
            let [vx, vy] = transform_point_to_page_coords(raw_x, raw_y, crop_x0, crop_y1);
            pts_all.push([vx, vy]);

            match seg.segment_type() {
                PdfPathSegmentType::MoveTo => {
                    current_pt = Some([vx, vy]);
                    subpath_start = Some([vx, vy]);
                }
                PdfPathSegmentType::LineTo => {
                    let p0 = current_pt.unwrap_or([vx, vy]);
                    items.push(DrawingItem {
                        cmd: "l".to_string(),
                        points: vec![p0, [vx, vy]],
                    });
                    current_pt = Some([vx, vy]);
                }
                PdfPathSegmentType::BezierTo => {
                    let p0 = current_pt.unwrap_or([vx, vy]);
                    items.push(DrawingItem {
                        cmd: "c".to_string(),
                        points: vec![p0, [vx, vy]],
                    });
                    current_pt = Some([vx, vy]);
                }
                _ => {}
            }

            if seg.is_close() {
                if let (Some(p0), Some(start)) = (current_pt, subpath_start) {
                    if p0 != start {
                        items.push(DrawingItem {
                            cmd: "l".to_string(),
                            points: vec![p0, start],
                        });
                    }
                }
            }
        }

        if !pts_all.is_empty() {
            let min_x = pts_all.iter().map(|p| p[0]).fold(f64::INFINITY, f64::min);
            let min_y = pts_all.iter().map(|p| p[1]).fold(f64::INFINITY, f64::min);
            let max_x = pts_all.iter().map(|p| p[0]).fold(f64::NEG_INFINITY, f64::max);
            let max_y = pts_all.iter().map(|p| p[1]).fold(f64::NEG_INFINITY, f64::max);
            rect = [round4(min_x), round4(min_y), round4(max_x), round4(max_y)];
        }

        drawings.push(DrawingInfo {
            drawing_index: *drawing_idx,
            path_type,
            rect,
            width: width_val,
            color: path_obj.stroke_color().ok().map(|c| vec![c.red() as f64 / 255.0, c.green() as f64 / 255.0, c.blue() as f64 / 255.0]),
            fill: path_obj.fill_color().ok().map(|c| vec![c.red() as f64 / 255.0, c.green() as f64 / 255.0, c.blue() as f64 / 255.0]),
            items,
        });
        *drawing_idx += 1;
    }

    Ok(())
}

pub fn extract_page(page: &PdfPage, page_index: usize) -> Result<PdfiumRawPage, Box<dyn std::error::Error>> {
    let width = round4(page.width().value as f64);
    let height = round4(page.height().value as f64);
    let rotation = match page.rotation()? {
        PdfPageRenderRotation::None => 0,
        PdfPageRenderRotation::Degrees90 => 90,
        PdfPageRenderRotation::Degrees180 => 180,
        PdfPageRenderRotation::Degrees270 => 270,
    };

    let crop_bounds = page
        .boundaries()
        .crop()
        .map(|b| b.bounds)
        .or_else(|_| page.boundaries().media().map(|b| b.bounds))?;
    let media_bounds = page
        .boundaries()
        .media()
        .map(|b| b.bounds)
        .unwrap_or(crop_bounds);

    let crop_x0 = crop_bounds.left().value as f64;
    let crop_y0 = crop_bounds.bottom().value as f64;
    let crop_x1 = crop_bounds.right().value as f64;
    let crop_y1 = crop_bounds.top().value as f64;

    let media_x0 = media_bounds.left().value as f64;
    let media_y0 = media_bounds.bottom().value as f64;
    let media_x1 = media_bounds.right().value as f64;
    let media_y1 = media_bounds.top().value as f64;

    let crop_box = [round4(crop_x0), round4(crop_y0), round4(crop_x1), round4(crop_y1)];
    let media_box = [round4(media_x0), round4(media_y0), round4(media_x1), round4(media_y1)];

    let page_text = page.text().ok();
    let mut spans = Vec::new();
    let mut order = 0i64;
    let mut obj_counter = 0usize;
    let mut has_invisible_text = false;

    let mut visible_text_scalar_count = 0usize;
    let mut extracted_char_scalar_count = 0usize;
    let mut synthetic_space_count = 0usize;
    let mut replacement_char_count = 0usize;
    let mut control_char_count = 0usize;
    let mut has_char_mismatch = false;
    let mut has_invalid_geometry = false;

    for obj in page.objects().iter() {
        process_page_object_text_recursive(
            &obj,
            PdfMatrix::IDENTITY,
            0,
            page_text.as_ref(),
            page_index,
            crop_x0,
            crop_y1,
            &mut order,
            &mut obj_counter,
            &mut spans,
            &mut visible_text_scalar_count,
            &mut extracted_char_scalar_count,
            &mut synthetic_space_count,
            &mut replacement_char_count,
            &mut control_char_count,
            &mut has_invisible_text,
            &mut has_char_mismatch,
            &mut has_invalid_geometry,
        )?;
    }

    let mut drawings = Vec::new();
    let mut drawing_idx = 0;
    for obj in page.objects().iter() {
        process_page_object_drawing_recursive(
            &obj,
            PdfMatrix::IDENTITY,
            0,
            crop_x0,
            crop_y1,
            &mut drawing_idx,
            &mut drawings,
        )?;
    }


    let (mapping_status, classification_reason) = if page_text.is_none() {
        ("unknown".to_string(), Some("unknown_unicode_mapping".to_string()))
    } else if replacement_char_count > 0 || control_char_count > 0 {
        ("invalid".to_string(), Some("invalid_unicode".to_string()))
    } else if visible_text_scalar_count != (extracted_char_scalar_count + synthetic_space_count) || has_char_mismatch {
        ("invalid".to_string(), Some("invalid_unicode_mapping".to_string()))
    } else if has_invalid_geometry {
        ("invalid".to_string(), Some("invalid_geometry".to_string()))
    } else {
        ("valid".to_string(), None)
    };

    let mapping_diagnostics = MappingDiagnostics {
        visible_text_scalar_count,
        extracted_char_scalar_count,
        synthetic_space_count,
        replacement_char_count,
        control_char_count,
        mapping_status,
        classification_reason,
    };

    Ok(PdfiumRawPage {
        schema_version: "pdfium_raw_page_v1.0".to_string(),
        page_index,
        width,
        height,
        rotation,
        crop_box,
        media_box,
        has_invisible_text,
        spans,
        drawings,
        mapping_diagnostics,
    })
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &byte in data {
        crc ^= byte as u32;
        for _ in 0..8 {
            if crc & 1 != 0 {
                crc = (crc >> 1) ^ 0xEDB8_8320;
            } else {
                crc >>= 1;
            }
        }
    }
    !crc
}

fn adler32(data: &[u8]) -> u32 {
    let mut s1 = 1u32;
    let mut s2 = 0u32;
    for &b in data {
        s1 = (s1 + b as u32) % 65521;
        s2 = (s2 + s1) % 65521;
    }
    (s2 << 16) | s1
}

fn write_png_chunk(out: &mut Vec<u8>, chunk_type: &[u8; 4], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    let crc_start = out.len();
    out.extend_from_slice(chunk_type);
    out.extend_from_slice(data);
    let crc = crc32(&out[crc_start..]);
    out.extend_from_slice(&crc.to_be_bytes());
}

pub fn save_rgba_as_png(
    width: u32,
    height: u32,
    rgba_data: &[u8],
    out_path: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(parent) = out_path.parent() {
        fs::create_dir_all(parent)?;
    }

    let mut raw_scanlines = Vec::with_capacity((height as usize) * (1 + (width as usize) * 4));
    let stride = (width as usize) * 4;
    for y in 0..(height as usize) {
        raw_scanlines.push(0u8); // Filter: None
        let start = y * stride;
        let end = (start + stride).min(rgba_data.len());
        if start < rgba_data.len() {
            raw_scanlines.extend_from_slice(&rgba_data[start..end]);
        }
    }

    let adler = adler32(&raw_scanlines);

    // Build zlib / deflate stream using uncompressed blocks (RFC 1950 + RFC 1951)
    let mut zlib_data = Vec::new();
    zlib_data.push(0x78); // CMF: Deflate, 32K window
    zlib_data.push(0x01); // FLG: No preset dict, check bits

    const CHUNK_SIZE: usize = 65535;
    let chunks: Vec<&[u8]> = raw_scanlines.chunks(CHUNK_SIZE).collect();
    if chunks.is_empty() {
        // Empty block
        zlib_data.push(0x01); // bfinal = 1, btype = 00
        zlib_data.extend_from_slice(&0u16.to_le_bytes());
        zlib_data.extend_from_slice(&(!0u16).to_le_bytes());
    } else {
        for (idx, chunk) in chunks.iter().enumerate() {
            let is_last = idx + 1 == chunks.len();
            let bfinal_btype: u8 = if is_last { 0x01 } else { 0x00 };
            zlib_data.push(bfinal_btype);
            let len = chunk.len() as u16;
            let nlen = !len;
            zlib_data.extend_from_slice(&len.to_le_bytes());
            zlib_data.extend_from_slice(&nlen.to_le_bytes());
            zlib_data.extend_from_slice(chunk);
        }
    }
    zlib_data.extend_from_slice(&adler.to_be_bytes());

    let mut png_bytes = Vec::new();
    // 1. PNG Header
    png_bytes.extend_from_slice(&[0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);

    // 2. IHDR Chunk
    let mut ihdr = Vec::with_capacity(13);
    ihdr.extend_from_slice(&width.to_be_bytes());
    ihdr.extend_from_slice(&height.to_be_bytes());
    ihdr.push(8); // Bit depth: 8
    ihdr.push(6); // Color type: 6 (RGBA)
    ihdr.push(0); // Compression method: 0 (deflate)
    ihdr.push(0); // Filter method: 0 (standard)
    ihdr.push(0); // Interlace method: 0 (no interlace)
    write_png_chunk(&mut png_bytes, b"IHDR", &ihdr);

    // 3. IDAT Chunk
    write_png_chunk(&mut png_bytes, b"IDAT", &zlib_data);

    // 4. IEND Chunk
    write_png_chunk(&mut png_bytes, b"IEND", &[]);

    fs::write(out_path, png_bytes)?;
    Ok(())
}

pub fn render_page_to_image(
    page: &PdfPage,
    dpi: f32,
) -> Result<image::DynamicImage, Box<dyn std::error::Error>> {
    let scale = (dpi / 72.0).max(0.1);
    let mut target_w = (page.width().value * scale).round() as i32;
    let mut target_h = (page.height().value * scale).round() as i32;
    target_w = target_w.max(1);
    target_h = target_h.max(1);

    let render_config = PdfRenderConfig::new()
        .set_target_width(target_w)
        .set_target_height(target_h);

    let bitmap = page.render_with_config(&render_config)?;
    Ok(bitmap.as_image())
}

pub fn save_image_to_png(
    img: &image::DynamicImage,
    out_path: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let rgba = img.to_rgba8();
    save_rgba_as_png(rgba.width(), rgba.height(), rgba.as_raw(), out_path)
}

pub fn render_page_to_png(
    page: &PdfPage,
    dpi: f32,
    out_path: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let img = render_page_to_image(page, dpi)?;
    save_image_to_png(&img, out_path)
}

pub fn get_platform_native_lib(manifest_dir: &Path) -> Result<(PathBuf, &'static str), String> {
    if cfg!(target_os = "windows") && cfg!(target_arch = "x86_64") {
        Ok((
            manifest_dir.join("native/win-x64/pdfium.dll"),
            "d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b",
        ))
    } else if cfg!(target_os = "linux") && cfg!(target_arch = "x86_64") {
        Ok((
            manifest_dir.join("native/linux-x64/libpdfium.so"),
            "f9d6c4c5970cffaa72eb995a1ee594b9f2d1e21b8f041ff91b17a1a45749f997",
        ))
    } else if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
        Ok((
            manifest_dir.join("native/mac-arm64/libpdfium.dylib"),
            "134c44ec94b29bb80cb8c0a875a746522ae5746b14644aee50b86b5d92df9eb7",
        ))
    } else if cfg!(target_os = "macos") && cfg!(target_arch = "x86_64") {
        Ok((
            manifest_dir.join("native/mac-x64/libpdfium.dylib"),
            "16dbd78c3937ca8d269894e43f5509dfbafe9b177d40a14922ca058fe64b18c6",
        ))
    } else {
        Err(format!(
            "Unsupported target platform: {} {}",
            std::env::consts::OS,
            std::env::consts::ARCH
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn library_exports_pdfium_manifest_resolver() {
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (path, _) = get_platform_native_lib(&root).expect("manifest should resolve");
        assert!(path.ends_with("pdfium.dll")
            || path.ends_with("libpdfium.so")
            || path.ends_with("libpdfium.dylib"));
    }
}
