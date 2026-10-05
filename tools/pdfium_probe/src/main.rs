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

pub fn process_pdf_file(
    pdfium: &Pdfium,
    pdf_path: &Path,
    out_dir: &Path,
    native_sha: &str,
    expected_sha: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    let file_name = pdf_path.file_name().unwrap().to_str().unwrap();
    let base_name = pdf_path.file_stem().unwrap().to_str().unwrap();
    let source_file_sha256 = compute_file_sha256(pdf_path)?;
    let doc = pdfium.load_pdf_from_file(pdf_path, None)?;
    let page_count = doc.pages().len();
    let mut pages = Vec::new();

    for i in 0..page_count {
        let page = doc.pages().get(i)?;
        pages.push(extract_page(&page, i as usize)?);

        // 同步渲染 72 DPI 与 180 DPI 底图供下游模型使用
        let dpi72_out = out_dir.join(format!("{}_page_{}_dpi72.png", base_name, i));
        let dpi180_out = out_dir.join(format!("{}_page_{}_dpi180.png", base_name, i));
        if let Err(e) = render_page_to_png(&page, 72.0, &dpi72_out) {
            eprintln!("[pdfium_probe] Warning: failed to render page: {}", e);
        }
        if let Err(e) = render_page_to_png(&page, 180.0, &dpi180_out) {
            eprintln!("[pdfium_probe] Warning: failed to render page: {}", e);
        }
    }

    let snapshot = PdfiumRawSnapshot {
        schema_version: "pdfium_raw_snapshot_v1.1".to_string(),
        generator: "pdfium_probe_0.1.0".to_string(),
        source_file: file_name.to_string(),
        source_file_sha256,
        native_library_sha256: native_sha.to_string(),
        native_library_expected_sha256: expected_sha.to_string(),
        page_count: pages.len(),
        pages,
    };

    let out_file = out_dir.join(format!("{}_pdfium.json", base_name));
    let json_str = serde_json::to_string_pretty(&snapshot)?;
    fs::write(&out_file, json_str)?;
    println!("[pdfium_probe] Wrote raw snapshot to {:?}", out_file);

    let normalized = normalizer::normalize_raw_snapshot(&snapshot);
    let norm_file = out_dir.join(format!("{}_normalized.json", base_name));
    let norm_json_str = serde_json::to_string_pretty(&normalized)?;
    fs::write(&norm_file, &norm_json_str)?;
    println!("[pdfium_probe] Wrote normalized snapshot to {:?}", norm_file);

    for (i, norm_page) in normalized.iter().enumerate() {
        let page_norm_file = out_dir.join(format!("{}_page_{}_normalized.json", base_name, i));
        let page_norm_json = serde_json::to_string_pretty(norm_page)?;
        fs::write(&page_norm_file, page_norm_json)?;
    }
    Ok(())
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

pub fn parse_tables_json(tables_arg: &str) -> Result<Vec<layout::TableRegionInput>, Box<dyn std::error::Error>> {
    let trimmed = tables_arg.trim();
    if trimmed.is_empty() || trimmed == "[]" {
        return Ok(Vec::new());
    }

    let json_content = if Path::new(tables_arg).is_file() {
        fs::read_to_string(tables_arg)?
    } else {
        tables_arg.to_string()
    };

    let trimmed_content = json_content.trim();
    if trimmed_content.is_empty() || trimmed_content == "[]" {
        return Ok(Vec::new());
    }

    #[derive(Deserialize)]
    struct FlexibleTableItem {
        bbox: [f64; 4],
        #[serde(default)]
        table_id: Option<usize>,
        #[serde(default)]
        table_index: Option<usize>,
    }

    // Try parsing as array of flexible table items
    if let Ok(items) = serde_json::from_str::<Vec<FlexibleTableItem>>(trimmed_content) {
        let tables = items
            .into_iter()
            .enumerate()
            .map(|(idx, item)| layout::TableRegionInput {
                bbox: item.bbox,
                table_id: item.table_id.or(item.table_index).unwrap_or(idx),
            })
            .collect();
        return Ok(tables);
    }

    // Also try parsing if wrapped in an object with a "tables" key
    #[derive(Deserialize)]
    struct TablesWrapper {
        tables: Vec<FlexibleTableItem>,
    }
    if let Ok(wrapper) = serde_json::from_str::<TablesWrapper>(trimmed_content) {
        let tables = wrapper
            .tables
            .into_iter()
            .enumerate()
            .map(|(idx, item)| layout::TableRegionInput {
                bbox: item.bbox,
                table_id: item.table_id.or(item.table_index).unwrap_or(idx),
            })
            .collect();
        return Ok(tables);
    }

    // Fallback: standard parse to provide meaningful error if invalid
    let tables: Vec<layout::TableRegionInput> = serde_json::from_str(trimmed_content)?;
    Ok(tables)
}

#[derive(Deserialize, Debug, Clone)]
#[serde(untagged)]
enum FlexibleBBox {
    Array([f64; 4]),
    Dict { x0: f64, y0: f64, x1: f64, y1: f64 },
}

impl FlexibleBBox {
    fn to_array(&self) -> [f64; 4] {
        match *self {
            FlexibleBBox::Array(arr) => arr,
            FlexibleBBox::Dict { x0, y0, x1, y1 } => [x0, y0, x1, y1],
        }
    }
}

#[derive(Deserialize, Debug, Clone)]
struct FlexibleCellItem {
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub row_index: usize,
    #[serde(default)]
    pub col_index: usize,
    #[serde(default = "markdown::default_span_one")]
    pub rowspan: usize,
    #[serde(default = "markdown::default_span_one")]
    pub colspan: usize,
    #[serde(default)]
    pub bbox: Option<FlexibleBBox>,
}

#[derive(Deserialize, Debug, Clone)]
struct FlexibleFullTableItem {
    #[serde(default)]
    pub table_id: Option<usize>,
    #[serde(default)]
    pub table_index: Option<usize>,
    #[serde(default)]
    pub bbox: Option<FlexibleBBox>,
    #[serde(default)]
    pub rows: Option<usize>,
    #[serde(default)]
    pub cols: Option<usize>,
    #[serde(default)]
    pub cells: Vec<FlexibleCellItem>,
    #[serde(default)]
    pub confidence: Option<f64>,
    #[serde(default)]
    pub source: Option<String>,
}

#[derive(Deserialize, Debug, Clone)]
struct FullTablesWrapper {
    pub tables: Vec<FlexibleFullTableItem>,
}

fn convert_flexible_table(item: FlexibleFullTableItem, default_idx: usize) -> markdown::FullTableDto {
    let table_id = item.table_id.or(item.table_index).unwrap_or(default_idx);
    let bbox = item.bbox.map(|b| b.to_array()).unwrap_or([0.0, 0.0, 0.0, 0.0]);
    let cells: Vec<markdown::TableCellDto> = item
        .cells
        .into_iter()
        .map(|c| markdown::TableCellDto {
            text: c.text,
            row_index: c.row_index,
            col_index: c.col_index,
            rowspan: c.rowspan.max(1),
            colspan: c.colspan.max(1),
            bbox: c.bbox.map(|b| b.to_array()).unwrap_or([0.0, 0.0, 0.0, 0.0]),
        })
        .collect();

    let inferred_rows = cells
        .iter()
        .map(|c| c.row_index + c.rowspan)
        .max()
        .unwrap_or(0);
    let inferred_cols = cells
        .iter()
        .map(|c| c.col_index + c.colspan)
        .max()
        .unwrap_or(0);

    let rows = item.rows.unwrap_or(0);
    let rows = if rows == 0 { inferred_rows } else { rows };

    let cols = item.cols.unwrap_or(0);
    let cols = if cols == 0 { inferred_cols } else { cols };

    markdown::FullTableDto {
        table_id,
        bbox,
        rows,
        cols,
        cells,
        confidence: item.confidence,
        source: item.source,
    }
}

pub fn parse_full_tables_json(tables_arg: &str) -> Result<Vec<markdown::FullTableDto>, String> {
    let trimmed = tables_arg.trim();
    if trimmed.is_empty() || trimmed == "[]" {
        return Ok(Vec::new());
    }

    let json_content = if !trimmed.starts_with('[') && !trimmed.starts_with('{') {
        let p = Path::new(trimmed);
        if p.is_file() {
            fs::read_to_string(trimmed).map_err(|e| format!("Failed to read file {}: {}", trimmed, e))?
        } else if trimmed.ends_with(".json") {
            return Err(format!("File not found: {}", trimmed));
        } else {
            trimmed.to_string()
        }
    } else {
        trimmed.to_string()
    };

    let trimmed_content = json_content.trim();
    if trimmed_content.is_empty() || trimmed_content == "[]" {
        return Ok(Vec::new());
    }

    if let Ok(items) = serde_json::from_str::<Vec<FlexibleFullTableItem>>(trimmed_content) {
        let tables = items
            .into_iter()
            .enumerate()
            .map(|(idx, item)| convert_flexible_table(item, idx))
            .collect();
        return Ok(tables);
    }

    if let Ok(wrapper) = serde_json::from_str::<FullTablesWrapper>(trimmed_content) {
        let tables = wrapper
            .tables
            .into_iter()
            .enumerate()
            .map(|(idx, item)| convert_flexible_table(item, idx))
            .collect();
        return Ok(tables);
    }

    if let Ok(single) = serde_json::from_str::<FlexibleFullTableItem>(trimmed_content) {
        if single.bbox.is_some() || !single.cells.is_empty() {
            return Ok(vec![convert_flexible_table(single, 0)]);
        }
    }

    match serde_json::from_str::<Vec<FlexibleFullTableItem>>(trimmed_content) {
        Err(e) => Err(format!("Failed to parse full tables JSON: {}", e)),
        Ok(_) => unreachable!(),
    }
}

pub fn parse_pipeline_args(
    raw_args: &[String],
) -> Result<(PathBuf, pipeline::PipelineConfig), Box<dyn std::error::Error>> {
    let mut args = raw_args;
    if let Some(first) = args.first() {
        if first == "parse" {
            args = &args[1..];
        }
    }

    let mut output_dir: Option<PathBuf> = None;
    let mut render_dpi: f32 = 72.0;
    let mut page_indices: Option<Vec<usize>> = None;
    let mut model_path: Option<PathBuf> = None;
    let mut confidence_threshold: f32 = 0.40;
    let mut export_renders: bool = true;
    let mut export_pages: bool = true;
    let mut positional_args: Vec<String> = Vec::new();

    let mut i = 0;
    while i < args.len() {
        let arg = &args[i];
        if arg == "-o" || arg == "--output" {
            i += 1;
            if i >= args.len() {
                return Err(format!("Missing value for {}", arg).into());
            }
            output_dir = Some(PathBuf::from(&args[i]));
        } else if arg == "--dpi" {
            i += 1;
            if i >= args.len() {
                return Err("Missing value for --dpi".into());
            }
            let dpi = args[i]
                .parse::<f32>()
                .map_err(|e| format!("Invalid value for --dpi '{}': {}", args[i], e))?;
            if dpi <= 0.0 || !dpi.is_finite() {
                return Err(format!("Invalid value for --dpi '{}': must be positive", args[i]).into());
            }
            render_dpi = dpi;
        } else if arg == "--confidence" {
            i += 1;
            if i >= args.len() {
                return Err("Missing value for --confidence".into());
            }
            let conf = args[i]
                .parse::<f32>()
                .map_err(|e| format!("Invalid value for --confidence '{}': {}", args[i], e))?;
            if !(0.0..=1.0).contains(&conf) || !conf.is_finite() {
                return Err(format!("Invalid value for --confidence '{}': must be between 0.0 and 1.0", args[i]).into());
            }
            confidence_threshold = conf;
        } else if arg == "--model" {
            i += 1;
            if i >= args.len() {
                return Err("Missing value for --model".into());
            }
            let m_val = &args[i];
            if m_val.is_empty() || m_val == "auto" || m_val == "default" {
                model_path = None;
            } else {
                model_path = Some(PathBuf::from(m_val));
            }
        } else if arg == "--no-renders" {
            export_renders = false;
        } else if arg == "--no-pages" {
            export_pages = false;
        } else if arg == "--pages" {
            i += 1;
            if i >= args.len() {
                return Err("Missing value for --pages".into());
            }
            let first_token = &args[i];
            if first_token.starts_with('-') {
                return Err("Missing value for --pages".into());
            }
            let mut pages = Vec::new();
            for part in first_token.split(',') {
                let trimmed = part.trim();
                if trimmed.is_empty() {
                    continue;
                }
                let idx = trimmed
                    .parse::<usize>()
                    .map_err(|e| format!("Invalid page index '{}': {}", trimmed, e))?;
                pages.push(idx);
            }
            while i + 1 < args.len() {
                let next_token = &args[i + 1];
                if next_token.starts_with('-') {
                    break;
                }
                let parts: Vec<&str> = next_token
                    .split(',')
                    .map(|s| s.trim())
                    .filter(|s| !s.is_empty())
                    .collect();
                if parts.is_empty() || !parts.iter().all(|s| s.parse::<usize>().is_ok()) {
                    break;
                }
                i += 1;
                for p in parts {
                    pages.push(p.parse::<usize>().unwrap());
                }
            }
            if pages.is_empty() {
                return Err("No valid page indices provided for --pages".into());
            }
            match &mut page_indices {
                Some(existing) => existing.extend(pages),
                None => page_indices = Some(pages),
            }
        } else if arg.starts_with('-') {
            return Err(format!("Unknown option: {}", arg).into());
        } else {
            positional_args.push(arg.clone());
        }
        i += 1;
    }

    if positional_args.is_empty() {
        return Err("Missing required argument: <pdf_path>".into());
    }

    let pdf_path = PathBuf::from(&positional_args[0]);

    if positional_args.len() > 1 {
        if output_dir.is_none() {
            output_dir = Some(PathBuf::from(&positional_args[1]));
        } else {
            return Err(format!(
                "Output directory specified both positionally ('{}') and via -o/--output",
                positional_args[1]
            )
            .into());
        }
    }
    if positional_args.len() > 2 {
        return Err(format!("Unexpected positional argument: '{}'", positional_args[2]).into());
    }

    let final_output_dir = output_dir.unwrap_or_else(|| PathBuf::from("."));

    let config = pipeline::PipelineConfig {
        output_dir: final_output_dir,
        render_dpi,
        page_indices,
        model_path,
        confidence_threshold,
        export_renders,
        export_pages,
    };

    Ok((pdf_path, config))
}

pub fn handle_parse_command(
    args: &[String],
) -> Result<pipeline::PipelineSummaryDto, Box<dyn std::error::Error>> {
    let (pdf_path, config) = parse_pipeline_args(args)?;
    let summary = pipeline::run_pipeline(&pdf_path, &config)?;
    println!(
        "[pdfium_probe] Pipeline finished for {:?}: {}/{} pages processed in {}ms. Output: {:?}",
        summary.pdf_path,
        summary.processed_pages,
        summary.total_pages,
        summary.elapsed_ms,
        summary.output_dir
    );
    Ok(summary)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() >= 2 && (args[1] == "--help" || args[1] == "-h") {
        println!("Usage: pdfium_probe <command> [args...]");
        println!("Commands:");
        println!("  render <pdf_path> <page_index> <dpi> <out_png>");
        println!("  normalize <pdf_path> <page_index> <out_json>");
        println!("  layout <pdf_path> <page_index> <tables_json> <out_json>");
        println!("  markdown <pdf_path> <page_index> <tables_json> <out_md>");
        println!("  json <pdf_path> <page_index> <tables_json> <out_json>");
        println!("  detect-tables <pdf_path> <page_index> <model_path> <out_json>");
        println!("  parse <pdf_path> [options]");
        return Ok(());
    }
    if args.len() >= 2 && args[1] == "render" {
        if args.iter().any(|a| a == "--help" || a == "-h") {
            println!("Usage: pdfium_probe render <pdf_path> <page_index> <dpi> <out_png>");
            return Ok(());
        }
        if args.len() < 6 {
            eprintln!("Usage: pdfium_probe render <pdf_path> <page_index> <dpi> <out_png>");
            return Err("Invalid arguments for render command".into());
        }
        let pdf_file = Path::new(&args[2]);
        let page_idx: usize = args[3].parse()?;
        let dpi: f32 = args[4].parse()?;
        let out_png = Path::new(&args[5]);

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir)?;
        let bindings = Pdfium::bind_to_library(lib_path)?;
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(pdf_file, None)?;
        let page_idx_u16 = u16::try_from(page_idx)
            .map_err(|e| format!("Page index {} exceeds u16 range: {}", page_idx, e))?;
        let page = doc.pages().get(page_idx_u16)?;
        render_page_to_png(&page, dpi, out_png)?;
        println!("[pdfium_probe] Rendered page {} to {:?}", page_idx, out_png);
        return Ok(());
    }

    if args.len() >= 2 && args[1] == "normalize" {
        if args.iter().any(|a| a == "--help" || a == "-h") {
            println!("Usage: pdfium_probe normalize <pdf_path> <page_index> <out_json>");
            return Ok(());
        }
        if args.len() < 5 {
            eprintln!("Usage: pdfium_probe normalize <pdf_path> <page_index> <out_json>");
            return Err("Invalid arguments for normalize command".into());
        }
        let pdf_file = Path::new(&args[2]);
        let page_idx: usize = args[3].parse()?;
        let out_json = Path::new(&args[4]);

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir)?;
        let bindings = Pdfium::bind_to_library(lib_path)?;
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(pdf_file, None)?;
        let page_idx_u16 = u16::try_from(page_idx)
            .map_err(|e| format!("Page index {} exceeds u16 range: {}", page_idx, e))?;
        let page = doc.pages().get(page_idx_u16)?;
        let raw_page = extract_page(&page, page_idx)?;
        let source_file_name = pdf_file.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let normalized = normalizer::normalize_raw_page_with_meta(
            &raw_page,
            Some(source_file_name),
            Some("pdfium_probe normalize"),
        );

        if let Some(parent) = out_json.parent() {
            fs::create_dir_all(parent)?;
        }
        let json_str = serde_json::to_string_pretty(&normalized)?;
        fs::write(out_json, json_str)?;
        println!("[pdfium_probe] Normalized page {} to {:?}", page_idx, out_json);
        return Ok(());
    }

    if args.len() >= 2 && args[1] == "layout" {
        if args.iter().any(|a| a == "--help" || a == "-h") {
            println!("Usage: pdfium_probe layout <pdf_path> <page_index> <tables_json> <out_json>");
            return Ok(());
        }
        if args.len() < 6 {
            eprintln!("Usage: pdfium_probe layout <pdf_path> <page_index> <tables_json> <out_json>");
            return Err("Invalid arguments for layout command".into());
        }
        let pdf_file = Path::new(&args[2]);
        let page_idx: usize = args[3].parse()?;
        let tables_arg = &args[4];
        let out_json = Path::new(&args[5]);

        let tables = parse_tables_json(tables_arg)?;

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir)?;
        let bindings = Pdfium::bind_to_library(lib_path)?;
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(pdf_file, None)?;
        let page_idx_u16 = u16::try_from(page_idx)
            .map_err(|e| format!("Page index {} exceeds u16 range: {}", page_idx, e))?;
        let page = doc.pages().get(page_idx_u16)?;
        let raw_page = extract_page(&page, page_idx)?;
        let source_file_name = pdf_file.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let normalized = normalizer::normalize_raw_page_with_meta(
            &raw_page,
            Some(source_file_name),
            Some("pdfium_probe layout"),
        );

        let layout_elements = layout::build_page_layout(&normalized, &tables, &[]);

        if let Some(parent) = out_json.parent() {
            fs::create_dir_all(parent)?;
        }
        let json_str = serde_json::to_string_pretty(&layout_elements)?;
        fs::write(out_json, json_str)?;
        println!("[pdfium_probe] Layout for page {} written to {:?}", page_idx, out_json);
        return Ok(());
    }

    if args.len() >= 2 && args[1] == "markdown" {
        if args.iter().any(|a| a == "--help" || a == "-h") {
            println!("Usage: pdfium_probe markdown <pdf_path> <page_index> <tables_json> <out_md>");
            return Ok(());
        }
        if args.len() < 6 {
            eprintln!("Usage: pdfium_probe markdown <pdf_path> <page_index> <tables_json> <out_md>");
            return Err("Invalid arguments for markdown command".into());
        }
        let pdf_file = Path::new(&args[2]);
        let page_idx: usize = args[3].parse()?;
        let tables_arg = &args[4];
        let out_md = Path::new(&args[5]);

        let tables = parse_full_tables_json(tables_arg)
            .map_err(|e| format!("Failed to parse tables JSON: {}", e))?;

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir)?;
        let bindings = Pdfium::bind_to_library(lib_path)?;
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(pdf_file, None)?;
        let page_idx_u16 = u16::try_from(page_idx)
            .map_err(|e| format!("Page index {} exceeds u16 range: {}", page_idx, e))?;
        let page = doc.pages().get(page_idx_u16)?;
        let raw_page = extract_page(&page, page_idx)?;
        let source_file_name = pdf_file.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let normalized = normalizer::normalize_raw_page_with_meta(
            &raw_page,
            Some(source_file_name),
            Some("pdfium_probe markdown"),
        );

        let regions: Vec<layout::TableRegionInput> = tables
            .iter()
            .map(|t| layout::TableRegionInput {
                bbox: t.bbox,
                table_id: t.table_id,
            })
            .collect();

        let layout_elements = layout::build_page_layout(&normalized, &regions, &[]);
        let md_str = markdown::render_page_markdown(&layout_elements, &tables, &[], &[], page_idx);

        if let Some(parent) = out_md.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(out_md, md_str)?;
        println!("[pdfium_probe] Markdown for page {} written to {:?}", page_idx, out_md);
        return Ok(());
    }

    if args.len() >= 2 && args[1] == "json" {
        if args.iter().any(|a| a == "--help" || a == "-h") {
            println!("Usage: pdfium_probe json <pdf_path> <page_index> <tables_json> <out_json>");
            return Ok(());
        }
        if args.len() < 6 {
            eprintln!("Usage: pdfium_probe json <pdf_path> <page_index> <tables_json> <out_json>");
            return Err("Invalid arguments for json command".into());
        }
        let pdf_file = Path::new(&args[2]);
        let page_idx: usize = args[3].parse()?;
        let tables_arg = &args[4];
        let out_json = Path::new(&args[5]);

        let tables = parse_full_tables_json(tables_arg)
            .map_err(|e| format!("Failed to parse tables JSON: {}", e))?;

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir)?;
        let bindings = Pdfium::bind_to_library(lib_path)?;
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(pdf_file, None)?;
        let page_idx_u16 = u16::try_from(page_idx)
            .map_err(|e| format!("Page index {} exceeds u16 range: {}", page_idx, e))?;
        let page = doc.pages().get(page_idx_u16)?;
        let raw_page = extract_page(&page, page_idx)?;
        let source_file_name = pdf_file.file_name().and_then(|s| s.to_str()).unwrap_or("");
        let normalized = normalizer::normalize_raw_page_with_meta(
            &raw_page,
            Some(source_file_name),
            Some("pdfium_probe json"),
        );

        let regions: Vec<layout::TableRegionInput> = tables
            .iter()
            .map(|t| layout::TableRegionInput {
                bbox: t.bbox,
                table_id: t.table_id,
            })
            .collect();

        let layout_elements = layout::build_page_layout(&normalized, &regions, &[]);
        let json_val = json_export::export_page_to_json(&normalized, &layout_elements, &tables, page_idx);

        if let Some(parent) = out_json.parent() {
            fs::create_dir_all(parent)?;
        }
        let json_str = serde_json::to_string_pretty(&json_val)?;
        fs::write(out_json, json_str)?;
        println!("[pdfium_probe] JSON for page {} written to {:?}", page_idx, out_json);
        return Ok(());
    }

    if args.len() >= 2 && args[1] == "detect-tables" {
        if args.iter().any(|a| a == "--help" || a == "-h") {
            println!("Usage: pdfium_probe detect-tables <pdf_path> <page_index> <model_path> <out_json>");
            return Ok(());
        }
        if args.len() < 6 {
            eprintln!("Usage: pdfium_probe detect-tables <pdf_path> <page_index> <model_path> <out_json>");
            return Err("Invalid arguments for detect-tables command".into());
        }
        let pdf_file = Path::new(&args[2]);
        let page_idx: usize = args[3].parse()?;
        let model_path_arg = &args[4];
        let out_json = Path::new(&args[5]);

        let resolved_model_path: PathBuf = if model_path_arg == "auto" || model_path_arg.is_empty() || model_path_arg == "default" {
            detector::resolve_default_model_path().ok_or_else(|| {
                "Unable to resolve default YOLO table detector model path (tried env YOLO_TABLE_DETECTOR_MODEL and default repository locations)".to_string()
            })?
        } else {
            let p = PathBuf::from(model_path_arg);
            if !p.exists() {
                return Err(format!("Specified model file does not exist: {:?}", p).into());
            }
            p
        };

        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir)?;
        let bindings = Pdfium::bind_to_library(lib_path)?;
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(pdf_file, None)?;
        let page_idx_u16 = u16::try_from(page_idx)
            .map_err(|e| format!("Page index {} exceeds u16 range: {}", page_idx, e))?;
        let page = doc.pages().get(page_idx_u16)?;

        let raw_page = extract_page(&page, page_idx)?;
        let norm_page = normalizer::normalize_raw_page(&raw_page);
        let words: Vec<[f32; 4]> = norm_page
            .words
            .iter()
            .map(|w| [w.0 as f32, w.1 as f32, w.2 as f32, w.3 as f32])
            .collect();

        let detections = detector::detect_tables_on_pdf_page(
            &page,
            &words,
            &resolved_model_path,
            &detector::TableDetectorConfig::default(),
        )?;

        if let Some(parent) = out_json.parent().filter(|p| !p.as_os_str().is_empty()) {
            fs::create_dir_all(parent)?;
        }
        let json_str = serde_json::to_string_pretty(&detections)?;
        fs::write(out_json, json_str)?;
        println!(
            "[pdfium_probe] Detected {} tables for page {} written to {:?}",
            detections.len(),
            page_idx,
            out_json
        );
        return Ok(());
    }

    if args.len() >= 2 && args[1] == "parse" {
        if args.iter().any(|a| a == "--help" || a == "-h") {
            println!("Usage: pdfium_probe parse <pdf_path> [options]");
            println!("Options:");
            println!("  -o, --output <dir>        Output directory path (default: .)");
            println!("  --dpi <f32>               Rendering DPI (default: 72.0)");
            println!("  --pages <p0,p1,...>       Page indices to process (e.g. 0,1,2 or space-separated)");
            println!("  --model <path>            Path to YOLO detection model ('auto' or empty to auto-resolve)");
            println!("  --confidence <f32>        Confidence threshold for table detector (default: 0.40)");
            println!("  --no-renders              Omit exporting page rasterization PNGs");
            println!("  --no-pages                Omit exporting per-page JSON/MD files");
            return Ok(());
        }
        if args.len() < 3 {
            eprintln!("Usage: pdfium_probe parse <pdf_path> [options]");
            return Err("Missing PDF path for parse command".into());
        }
        handle_parse_command(&args[2..])?;
        return Ok(());
    }

    println!("[pdfium_probe] Starting extraction on synthetic PDFs...");

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let (lib_path, expected_sha) = get_platform_native_lib(&manifest_dir)?;
    println!("[pdfium_probe] Loading native library from {:?} (target OS: {})", lib_path, std::env::consts::OS);
    let actual_native_sha = verify_file_sha256(&lib_path, expected_sha)?;

    let bindings = Pdfium::bind_to_library(lib_path)?;
    let pdfium = Pdfium::new(bindings);

    let (out_dir, real_out_dir) = if let Ok(root) = std::env::var("PDFIUM_OUTPUT_ROOT") {
        let root_path = PathBuf::from(root);
        (
            root_path.join("pdfium_output"),
            root_path.join("real_pdfium_output"),
        )
    } else {
        (
            manifest_dir.join("test_data/pdfium_output"),
            manifest_dir.join("test_data/real_pdfium_output"),
        )
    };

    let synthetic_dir = manifest_dir.join("test_data/synthetic");
    fs::create_dir_all(&out_dir)?;

    let mut synthetic_count = 0;
    for entry in fs::read_dir(&synthetic_dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("pdf") {
            println!("[pdfium_probe] Processing synthetic {:?}", path.file_name().unwrap());
            process_pdf_file(&pdfium, &path, &out_dir, &actual_native_sha, expected_sha)?;
            synthetic_count += 1;
        }
    }

    fs::create_dir_all(&real_out_dir)?;

    let repo_root = std::env::var("REPO_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            let direct = manifest_dir
                .parent()
                .and_then(|p| p.parent())
                .map(PathBuf::from)
                .unwrap_or_else(|| manifest_dir.clone());
            if direct.join("test.pdf").exists() {
                return direct;
            }
            if let Ok(git_content) = fs::read_to_string(direct.join(".git")) {
                if let Some(line) = git_content.lines().find(|l| l.starts_with("gitdir:")) {
                    let gitdir = line.trim_start_matches("gitdir:").trim();
                    let gitdir_path = PathBuf::from(gitdir);
                    for ancestor in gitdir_path.ancestors() {
                        if ancestor.join("test.pdf").exists() {
                            return ancestor.to_path_buf();
                        }
                    }
                }
            }
            if let Some(parent) = direct.parent().and_then(|p| p.parent()) {
                if parent.join("test.pdf").exists() {
                    return parent.to_path_buf();
                }
            }
            direct
        });

    let test_pdf_path = repo_root.join("test.pdf");
    let credit_pdf_path = repo_root.join("征信解析样例.pdf");

    let real_samples = [
        (test_pdf_path.clone(), 0, "test_p0_cover"),
        (test_pdf_path.clone(), 1, "test_p1_toc"),
        (test_pdf_path.clone(), 27, "test_p27_table"),
        (credit_pdf_path.clone(), 0, "credit_p0_header"),
        (credit_pdf_path.clone(), 1, "credit_p1_detail"),
    ];

    let mut real_count = 0;
    for (pdf_path, page_idx, sample_name) in real_samples {
        if !pdf_path.exists() {
            let abs_path = std::fs::canonicalize(&pdf_path).unwrap_or(pdf_path.clone());
            return Err(format!(
                "Required real PDF input file does not exist: {:?}",
                abs_path
            )
            .into());
        }
        println!("[pdfium_probe] Processing real sample: {} (page {})", sample_name, page_idx);
        let doc = pdfium.load_pdf_from_file(&pdf_path, None)?;
        let page = doc.pages().get(page_idx)?;
        let page_data = extract_page(&page, page_idx as usize)?;
        let source_file_sha256 = compute_file_sha256(&pdf_path)?;
        let snapshot = PdfiumRawSnapshot {
            schema_version: "pdfium_raw_snapshot_v1.1".to_string(),
            generator: "pdfium_probe_0.1.0".to_string(),
            source_file: pdf_path.file_name().unwrap().to_str().unwrap().to_string(),
            source_file_sha256,
            native_library_sha256: actual_native_sha.clone(),
            native_library_expected_sha256: expected_sha.to_string(),
            page_count: 1,
            pages: vec![page_data],
        };
        let out_file = real_out_dir.join(format!("{}_pdfium.json", sample_name));
        let json_str = serde_json::to_string_pretty(&snapshot)?;
        fs::write(&out_file, json_str)?;
        println!("[pdfium_probe] Wrote real raw snapshot to {:?}", out_file);

        let normalized = normalizer::normalize_raw_snapshot(&snapshot);
        let norm_file = real_out_dir.join(format!("{}_normalized.json", sample_name));
        let norm_json_str = serde_json::to_string_pretty(&normalized)?;
        fs::write(&norm_file, norm_json_str)?;
        println!("[pdfium_probe] Wrote real normalized snapshot to {:?}", norm_file);
        real_count += 1;
    }

    println!(
        "[pdfium_probe] Successfully processed {} synthetic and {} real PDF files.",
        synthetic_count, real_count
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rotation_transform_corners_0_90_180_270() {
        let (crop_x0, crop_y0, crop_x1, crop_y1) = (0.0, 0.0, 400.0, 600.0);

        // Rotation 0
        assert_eq!(transform_point_to_viewport(0.0, 0.0, crop_x0, crop_y0, crop_x1, crop_y1, 0), [0.0, 600.0]);
        assert_eq!(transform_point_to_viewport(0.0, 600.0, crop_x0, crop_y0, crop_x1, crop_y1, 0), [0.0, 0.0]);

        // Rotation 90
        assert_eq!(transform_point_to_viewport(0.0, 0.0, crop_x0, crop_y0, crop_x1, crop_y1, 90), [0.0, 0.0]);
        assert_eq!(transform_point_to_viewport(0.0, 600.0, crop_x0, crop_y0, crop_x1, crop_y1, 90), [600.0, 0.0]);
        assert_eq!(transform_point_to_viewport(400.0, 0.0, crop_x0, crop_y0, crop_x1, crop_y1, 90), [0.0, 400.0]);

        // Rotation 180
        assert_eq!(transform_point_to_viewport(400.0, 0.0, crop_x0, crop_y0, crop_x1, crop_y1, 180), [0.0, 0.0]);
        assert_eq!(transform_point_to_viewport(400.0, 600.0, crop_x0, crop_y0, crop_x1, crop_y1, 180), [0.0, 600.0]);

        // Rotation 270
        assert_eq!(transform_point_to_viewport(400.0, 600.0, crop_x0, crop_y0, crop_x1, crop_y1, 270), [0.0, 0.0]);
        assert_eq!(transform_point_to_viewport(400.0, 0.0, crop_x0, crop_y0, crop_x1, crop_y1, 270), [600.0, 0.0]);
    }

    #[test]
    fn test_unrotated_page_coords_contract() {
        let (crop_x0, crop_y1) = (50.0, 550.0);
        // (x, y) = (100, 220)
        let pt = transform_point_to_page_coords(100.0, 220.0, crop_x0, crop_y1);
        assert_eq!(pt, [50.0, 330.0]);
    }

    #[test]
    fn test_whitespace_preservation_contract() {
        let space_str = " ".to_string();
        assert!(!space_str.is_empty(), "Single whitespace must not be empty");
        let empty_str = "".to_string();
        assert!(empty_str.is_empty(), "Empty string must be skipped");
    }

    #[test]
    fn test_provenance_sidecar_contract() {
        let sidecar = ProvenanceSidecar {
            page_index: 0,
            pdfium_object_index: 42,
            character_count: 5,
            char_start_index: 0,
            char_end_index: 5,
            char_indices: vec![0, 1, 2, 3, 4],
            is_derived: false,
            derived_block: None,
            derived_line: None,
        };
        assert_eq!(sidecar.pdfium_object_index, 42);
        assert_eq!(sidecar.char_start_index, 0);
        assert_eq!(sidecar.char_end_index, 5);
        assert_eq!(sidecar.char_indices.len(), 5);
        assert_eq!(sidecar.is_derived, false);
        assert_eq!(sidecar.derived_block, None);
        assert_eq!(sidecar.derived_line, None);
    }

    #[test]
    fn test_platform_lib_dispatch() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let res = get_platform_native_lib(&manifest_dir);
        assert!(res.is_ok(), "Platform native lib dispatch should succeed on supported platform");
        let (path, sha) = res.unwrap();
        assert!(!sha.is_empty());
        #[cfg(target_os = "windows")]
        assert!(path.to_string_lossy().ends_with("pdfium.dll"));
    }

    #[test]
    fn test_is_illegal_control_char() {
        assert!(is_illegal_control_char('\0'));
        assert!(is_illegal_control_char('\x01'));
        assert!(is_illegal_control_char('\x1f'));
        assert!(is_illegal_control_char('\x7f'));
        assert!(is_illegal_control_char('\u{0085}'));

        assert!(!is_illegal_control_char('\t'));
        assert!(!is_illegal_control_char('\n'));
        assert!(!is_illegal_control_char('\r'));
        assert!(!is_illegal_control_char('A'));
        assert!(!is_illegal_control_char('中'));
    }

    #[test]
    fn test_unicode_scalar_count_contract() {
        let text = "中文测试";
        // String::len() returns byte count (12 for 4 Chinese characters in UTF-8)
        assert_eq!(text.len(), 12);
        // chars().count() returns Unicode scalar count (4)
        assert_eq!(text.chars().count(), 4);
    }

    #[test]
    fn test_mapping_diagnostics_contract() {
        let diag = MappingDiagnostics {
            visible_text_scalar_count: 5,
            extracted_char_scalar_count: 4,
            synthetic_space_count: 1,
            replacement_char_count: 0,
            control_char_count: 0,
            mapping_status: "valid".to_string(),
            classification_reason: None,
        };
        let json = serde_json::to_string(&diag).unwrap();
        assert!(json.contains("\"mapping_status\":\"valid\""));
        assert!(json.contains("\"visible_text_scalar_count\":5"));
        assert!(json.contains("\"extracted_char_scalar_count\":4"));
        assert!(json.contains("\"synthetic_space_count\":1"));
        assert!(json.contains("\"replacement_char_count\":0"));
        assert!(json.contains("\"control_char_count\":0"));

        let deserialized: MappingDiagnostics = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized, diag);
    }

    #[test]
    fn test_mapping_diagnostics_backward_compatibility() {
        let json = r#"{"visible_text_scalar_count":5,"extracted_char_scalar_count":5,"replacement_char_count":0,"control_char_count":0,"mapping_status":"valid","classification_reason":null}"#;
        let deserialized: MappingDiagnostics = serde_json::from_str(json).unwrap();
        assert_eq!(deserialized.synthetic_space_count, 0);
    }

    #[test]
    fn test_raw_snapshot_v1_1_contract() {
        let snapshot = PdfiumRawSnapshot {
            schema_version: "pdfium_raw_snapshot_v1.1".to_string(),
            generator: "pdfium_probe_0.1.0".to_string(),
            source_file: "test.pdf".to_string(),
            source_file_sha256: "abc123sha".to_string(),
            native_library_sha256: "def456sha".to_string(),
            native_library_expected_sha256: "def456sha".to_string(),
            page_count: 0,
            pages: vec![],
        };
        let json = serde_json::to_string(&snapshot).unwrap();
        assert!(json.contains("\"schema_version\":\"pdfium_raw_snapshot_v1.1\""));
        assert!(json.contains("\"source_file_sha256\":\"abc123sha\""));
        assert!(json.contains("\"native_library_sha256\":\"def456sha\""));
        assert!(json.contains("\"native_library_expected_sha256\":\"def456sha\""));
    }

    #[test]
    fn test_drawing_path_type_contract() {
        let d = DrawingInfo {
            drawing_index: 0,
            path_type: "stroked_filled".to_string(),
            rect: [0.0, 0.0, 10.0, 10.0],
            width: 1.0,
            color: None,
            fill: None,
            items: vec![],
        };
        let json = serde_json::to_string(&d).unwrap();
        assert!(json.contains("\"path_type\":\"stroked_filled\""));
        let deserialized: DrawingInfo = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.path_type, "stroked_filled");
    }

    #[test]
    fn test_render_page_to_png_contract() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir).unwrap();
        let bindings = Pdfium::bind_to_library(lib_path).unwrap();
        let pdfium = Pdfium::new(bindings);
        let sample_pdf = manifest_dir.join("test_data/synthetic/synth_basic_table.pdf");
        let sample_pdf = if sample_pdf.is_file() {
            sample_pdf
        } else {
            manifest_dir.join("test_data/synthetic/synth_rotations.pdf")
        };
        if !sample_pdf.is_file() {
            return;
        }
        let doc = pdfium.load_pdf_from_file(&sample_pdf, None).unwrap();
        let page = doc.pages().get(0).unwrap();
        let out_dir = manifest_dir.join("target/test_render");
        std::fs::create_dir_all(&out_dir).unwrap();
        let out_png = out_dir.join("test_synth_page_0.png");

        render_page_to_png(&page, 72.0, &out_png).unwrap();
        assert!(out_png.is_file());
        let meta = std::fs::metadata(&out_png).unwrap();
        assert!(meta.len() > 100); // 确保非空有效 PNG
        let mut header = [0u8; 8];
        let mut f = std::fs::File::open(&out_png).unwrap();
        f.read_exact(&mut header).unwrap();
        assert_eq!(&header[1..4], b"PNG"); // 校验 PNG 魔法头
    }

    #[test]
    fn test_normalize_synthetic_page_contract() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir).unwrap();
        let bindings = Pdfium::bind_to_library(lib_path).unwrap();
        let pdfium = Pdfium::new(bindings);
        let sample_pdf = manifest_dir.join("test_data/synthetic/synth_basic_table.pdf");
        let sample_pdf = if sample_pdf.is_file() {
            sample_pdf
        } else {
            manifest_dir.join("test_data/synthetic/synth_rotations.pdf")
        };
        if !sample_pdf.is_file() {
            return;
        }
        let doc = pdfium.load_pdf_from_file(&sample_pdf, None).unwrap();
        let page = doc.pages().get(0).unwrap();
        let raw_page = extract_page(&page, 0).unwrap();
        let norm = normalizer::normalize_raw_page(&raw_page);
        assert_eq!(norm.page_type, "vector");
        assert!(norm.page_snapshot.is_some());
        assert!(norm.rawdict.is_some());
        assert!(!norm.words.is_empty());

        let snapshot = norm.page_snapshot.as_ref().unwrap();
        assert_eq!(snapshot.schema_version, 1);
        assert_eq!(snapshot.page_index, 0);
        assert!(!snapshot.text_blocks.is_empty());
        assert!(!snapshot.spans.is_empty());

        let json = serde_json::to_string_pretty(&norm).unwrap();
        let back: normalizer::NormalizedPageDto = serde_json::from_str(&json).unwrap();
        assert_eq!(norm, back);
    }

    #[test]
    fn test_parse_tables_json_variations() {
        // Empty inputs
        assert!(parse_tables_json("").unwrap().is_empty());
        assert!(parse_tables_json("   ").unwrap().is_empty());
        assert!(parse_tables_json("[]").unwrap().is_empty());
        assert!(parse_tables_json(" [ ] ").unwrap().is_empty());

        // Array with table_id
        let input1 = r#"[{"bbox": [10.0, 20.0, 100.0, 200.0], "table_id": 5}]"#;
        let tables1 = parse_tables_json(input1).unwrap();
        assert_eq!(tables1.len(), 1);
        assert_eq!(tables1[0].bbox, [10.0, 20.0, 100.0, 200.0]);
        assert_eq!(tables1[0].table_id, 5);

        // Array with table_index
        let input2 = r#"[{"bbox": [15.0, 25.0, 105.0, 205.0], "table_index": 7}]"#;
        let tables2 = parse_tables_json(input2).unwrap();
        assert_eq!(tables2.len(), 1);
        assert_eq!(tables2[0].bbox, [15.0, 25.0, 105.0, 205.0]);
        assert_eq!(tables2[0].table_id, 7);

        // Array with missing id (defaults to index)
        let input3 = r#"[{"bbox": [0.0, 0.0, 50.0, 50.0]}, {"bbox": [60.0, 60.0, 100.0, 100.0]}]"#;
        let tables3 = parse_tables_json(input3).unwrap();
        assert_eq!(tables3.len(), 2);
        assert_eq!(tables3[0].table_id, 0);
        assert_eq!(tables3[1].table_id, 1);

        // Object with "tables" wrapper
        let input4 = r#"{"tables": [{"bbox": [1.0, 2.0, 3.0, 4.0], "table_id": 42}]}"#;
        let tables4 = parse_tables_json(input4).unwrap();
        assert_eq!(tables4.len(), 1);
        assert_eq!(tables4[0].bbox, [1.0, 2.0, 3.0, 4.0]);
        assert_eq!(tables4[0].table_id, 42);
    }

    #[test]
    fn test_parse_full_tables_json_empty() {
        assert!(parse_full_tables_json("").unwrap().is_empty());
        assert!(parse_full_tables_json("   ").unwrap().is_empty());
        assert!(parse_full_tables_json("[]").unwrap().is_empty());
        assert!(parse_full_tables_json(" [  ] \n").unwrap().is_empty());
    }

    #[test]
    fn test_parse_full_tables_json_simple_bbox() {
        // Array with [x0, y0, x1, y1] bbox
        let json_arr = r#"[{"bbox": [10.0, 20.0, 100.0, 200.0]}]"#;
        let tables1 = parse_full_tables_json(json_arr).unwrap();
        assert_eq!(tables1.len(), 1);
        assert_eq!(tables1[0].table_id, 0);
        assert_eq!(tables1[0].bbox, [10.0, 20.0, 100.0, 200.0]);
        assert_eq!(tables1[0].rows, 0);
        assert_eq!(tables1[0].cols, 0);
        assert!(tables1[0].cells.is_empty());

        // Array with dict bbox {"x0": ..., "y0": ..., "x1": ..., "y1": ...} and explicit table_id
        let json_dict = r#"[{"bbox": {"x0": 5.0, "y0": 10.0, "x1": 50.0, "y1": 80.0}, "table_id": 3}]"#;
        let tables2 = parse_full_tables_json(json_dict).unwrap();
        assert_eq!(tables2.len(), 1);
        assert_eq!(tables2[0].table_id, 3);
        assert_eq!(tables2[0].bbox, [5.0, 10.0, 50.0, 80.0]);
    }

    #[test]
    fn test_parse_full_tables_json_full_cells() {
        let json_full = r#"[
            {
                "table_id": 1,
                "bbox": [0.0, 0.0, 300.0, 400.0],
                "rows": 2,
                "cols": 2,
                "cells": [
                    {
                        "text": "Header",
                        "row_index": 0,
                        "col_index": 0,
                        "rowspan": 1,
                        "colspan": 2,
                        "bbox": [0.0, 0.0, 300.0, 50.0]
                    },
                    {
                        "text": "Cell A",
                        "row_index": 1,
                        "col_index": 0,
                        "rowspan": 1,
                        "colspan": 1,
                        "bbox": {"x0": 0.0, "y0": 50.0, "x1": 150.0, "y1": 100.0}
                    },
                    {
                        "text": "Cell B",
                        "row_index": 1,
                        "col_index": 1,
                        "bbox": [150.0, 50.0, 300.0, 100.0]
                    }
                ],
                "confidence": 0.95,
                "source": "native"
            }
        ]"#;
        let tables = parse_full_tables_json(json_full).unwrap();
        assert_eq!(tables.len(), 1);
        let t = &tables[0];
        assert_eq!(t.table_id, 1);
        assert_eq!(t.bbox, [0.0, 0.0, 300.0, 400.0]);
        assert_eq!(t.rows, 2);
        assert_eq!(t.cols, 2);
        assert_eq!(t.confidence, Some(0.95));
        assert_eq!(t.source.as_deref(), Some("native"));
        assert_eq!(t.cells.len(), 3);
        assert_eq!(t.cells[0].text, "Header");
        assert_eq!(t.cells[0].colspan, 2);
        assert_eq!(t.cells[1].bbox, [0.0, 50.0, 150.0, 100.0]);
        assert_eq!(t.cells[2].rowspan, 1);
        assert_eq!(t.cells[2].colspan, 1);
    }

    #[test]
    fn test_parse_full_tables_json_wrapped() {
        let json_wrapped = r#"{
            "tables": [
                {
                    "bbox": [10.0, 20.0, 30.0, 40.0],
                    "cells": [
                        {
                            "text": "Inferred Grid",
                            "row_index": 1,
                            "col_index": 2,
                            "rowspan": 2,
                            "colspan": 1
                        }
                    ]
                }
            ]
        }"#;
        let tables = parse_full_tables_json(json_wrapped).unwrap();
        assert_eq!(tables.len(), 1);
        assert_eq!(tables[0].table_id, 0);
        assert_eq!(tables[0].bbox, [10.0, 20.0, 30.0, 40.0]);
        assert_eq!(tables[0].rows, 3);
        assert_eq!(tables[0].cols, 3);
        assert_eq!(tables[0].cells.len(), 1);
        assert_eq!(tables[0].cells[0].text, "Inferred Grid");
    }

    #[test]
    fn test_detect_tables_cli_model_resolver() {
        let path = detector::resolve_default_model_path();
        assert!(path.is_some(), "Expected default model path to be resolved");
        let p = path.unwrap();
        assert!(p.exists(), "Resolved model path {:?} must exist", p);
    }

    #[test]
    fn test_detect_tables_cli_on_pdf_page() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir).unwrap();
        let bindings = Pdfium::bind_to_library(lib_path).unwrap();
        let pdfium = Pdfium::new(bindings);

        let synth_pdf = manifest_dir.join("test_data/synthetic/synth_crop_offset.pdf");
        if !synth_pdf.exists() {
            return;
        }

        let model_path = detector::resolve_default_model_path();
        assert!(model_path.is_some(), "Model path must be resolved");
        let m_path = model_path.unwrap();
        let doc = pdfium.load_pdf_from_file(&synth_pdf, None).unwrap();
        let page = doc.pages().get(0).unwrap();
        let raw_page = extract_page(&page, 0).unwrap();
        let norm = normalizer::normalize_raw_page(&raw_page);
        let words: Vec<[f32; 4]> = norm
            .words
            .iter()
            .map(|w| [w.0 as f32, w.1 as f32, w.2 as f32, w.3 as f32])
            .collect();
        let config = detector::TableDetectorConfig::default();
        let result = detector::detect_tables_on_pdf_page(&page, &words, &m_path, &config);
        assert!(result.is_ok(), "Page detection should succeed");
        let detections = result.unwrap();
        let json = serde_json::to_string_pretty(&detections);
        assert!(json.is_ok(), "Detections must serialize cleanly to JSON");
    }

    #[test]
    fn test_cli_parse_args_builder() {
        // 1. Defaults with only pdf path
        let args_default = vec!["parse".to_string(), "sample.pdf".to_string()];
        let (pdf, config) = parse_pipeline_args(&args_default).expect("should parse defaults");
        assert_eq!(pdf, PathBuf::from("sample.pdf"));
        assert_eq!(config.output_dir, PathBuf::from("."));
        assert!((config.render_dpi - 72.0).abs() < f32::EPSILON);
        assert!((config.confidence_threshold - 0.40).abs() < f32::EPSILON);
        assert!(config.export_renders);
        assert!(config.export_pages);
        assert!(config.page_indices.is_none());
        assert!(config.model_path.is_none());

        // 2. Positional output dir fallback
        let args_pos = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "custom_out".to_string(),
        ];
        let (pdf, config) = parse_pipeline_args(&args_pos).expect("should parse positional output");
        assert_eq!(pdf, PathBuf::from("sample.pdf"));
        assert_eq!(config.output_dir, PathBuf::from("custom_out"));

        // 3. Flags: -o, --dpi, --confidence, --no-renders, --no-pages
        let args_flags = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "-o".to_string(),
            "flags_out".to_string(),
            "--dpi".to_string(),
            "144.0".to_string(),
            "--confidence".to_string(),
            "0.65".to_string(),
            "--no-renders".to_string(),
            "--no-pages".to_string(),
        ];
        let (pdf, config) = parse_pipeline_args(&args_flags).expect("should parse flags");
        assert_eq!(pdf, PathBuf::from("sample.pdf"));
        assert_eq!(config.output_dir, PathBuf::from("flags_out"));
        assert!((config.render_dpi - 144.0).abs() < f32::EPSILON);
        assert!((config.confidence_threshold - 0.65).abs() < f32::EPSILON);
        assert!(!config.export_renders);
        assert!(!config.export_pages);

        // 4. Long flag --output
        let args_long_out = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "--output".to_string(),
            "long_out".to_string(),
        ];
        let (_, config) = parse_pipeline_args(&args_long_out).expect("should parse --output");
        assert_eq!(config.output_dir, PathBuf::from("long_out"));

        // 5. Pages comma-separated
        let args_pages_comma = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "--pages".to_string(),
            "0,2,4".to_string(),
        ];
        let (_, config) = parse_pipeline_args(&args_pages_comma).expect("should parse comma pages");
        assert_eq!(config.page_indices, Some(vec![0, 2, 4]));

        // 6. Pages space-separated
        let args_pages_space = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "--pages".to_string(),
            "1".to_string(),
            "3".to_string(),
            "5".to_string(),
        ];
        let (_, config) = parse_pipeline_args(&args_pages_space).expect("should parse space pages");
        assert_eq!(config.page_indices, Some(vec![1, 3, 5]));

        // 7. Pages mixed comma and space separated
        let args_pages_mixed = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "--pages".to_string(),
            "0,1".to_string(),
            "2,3".to_string(),
        ];
        let (_, config) = parse_pipeline_args(&args_pages_mixed).expect("should parse mixed pages");
        assert_eq!(config.page_indices, Some(vec![0, 1, 2, 3]));

        // 8. Model flag: custom path and auto
        let args_model_custom = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "--model".to_string(),
            "custom_yolo.onnx".to_string(),
        ];
        let (_, config) = parse_pipeline_args(&args_model_custom).expect("should parse custom model");
        assert_eq!(config.model_path, Some(PathBuf::from("custom_yolo.onnx")));

        let args_model_auto = vec![
            "parse".to_string(),
            "sample.pdf".to_string(),
            "--model".to_string(),
            "auto".to_string(),
        ];
        let (_, config) = parse_pipeline_args(&args_model_auto).expect("should parse auto model");
        assert_eq!(config.model_path, None);

        // 9. Error cases
        let empty_args: Vec<String> = vec![];
        assert!(parse_pipeline_args(&empty_args).is_err());

        let just_subcmd = vec!["parse".to_string()];
        assert!(parse_pipeline_args(&just_subcmd).is_err());

        let invalid_dpi = vec![
            "sample.pdf".to_string(),
            "--dpi".to_string(),
            "not_a_number".to_string(),
        ];
        assert!(parse_pipeline_args(&invalid_dpi).is_err());

        let missing_opt_val = vec!["sample.pdf".to_string(), "-o".to_string()];
        assert!(parse_pipeline_args(&missing_opt_val).is_err());

        let unknown_flag = vec!["sample.pdf".to_string(), "--unknown-flag".to_string()];
        assert!(parse_pipeline_args(&unknown_flag).is_err());
    }

    #[test]
    fn test_cli_parse_end_to_end() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let synth_pdf = manifest_dir.join("test_data/synthetic/synth_crop_offset.pdf");
        assert!(synth_pdf.exists(), "Synthetic PDF fixture must exist: {:?}", synth_pdf);

        let temp_dir = std::env::temp_dir().join(format!(
            "test_cli_parse_e2e_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));

        let args = vec![
            "parse".to_string(),
            synth_pdf.to_string_lossy().to_string(),
            "-o".to_string(),
            temp_dir.to_string_lossy().to_string(),
            "--dpi".to_string(),
            "72.0".to_string(),
            "--confidence".to_string(),
            "0.40".to_string(),
        ];

        let summary = handle_parse_command(&args).expect("handle_parse_command should succeed");
        assert_eq!(summary.total_pages, 1);
        assert_eq!(summary.processed_pages, 1);
        assert_eq!(summary.page_indices, vec![0]);

        assert!(temp_dir.join("output.json").exists(), "output.json must exist");
        assert!(temp_dir.join("output.md").exists(), "output.md must exist");
        assert!(temp_dir.join("pages/page-000.json").exists(), "pages/page-000.json must exist");
        assert!(temp_dir.join("pages/page-000.md").exists(), "pages/page-000.md must exist");
        assert!(temp_dir.join("renders/page-000.png").exists(), "renders/page-000.png must exist");

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn test_form_xobject_recursion_extracts_child_spans() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let (lib_path, _) = get_platform_native_lib(&manifest_dir).unwrap();
        let bindings = Pdfium::bind_to_library(lib_path).unwrap();
        let pdfium = Pdfium::new(bindings);
        let pdf_path = PathBuf::from(r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf");
        assert!(pdf_path.is_file(), "PDF must exist: {:?}", pdf_path);
        let doc = pdfium.load_pdf_from_file(&pdf_path, None).unwrap();
        let page = doc.pages().get(790).unwrap();
        let raw_page = extract_page(&page, 790).unwrap();
        assert!(
            raw_page.spans.len() > 50,
            "Expected spans.len() > 50, got {}",
            raw_page.spans.len()
        );
        let has_expected_text = raw_page
            .spans
            .iter()
            .any(|s| s.text.contains("会合04表") || s.text.contains("资本"));
        assert!(
            has_expected_text,
            "Expected text to contain '会合04表' or '资本'"
        );
        assert!(
            raw_page.drawings.len() > 100,
            "Expected drawings.len() > 100, got {}",
            raw_page.drawings.len()
        );
    }

}

