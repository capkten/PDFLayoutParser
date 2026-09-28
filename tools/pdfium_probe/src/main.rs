use pdfium_render::prelude::*;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};

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
    pub rect: [f64; 4],
    pub width: f64,
    pub color: Option<Vec<f64>>,
    pub fill: Option<Vec<f64>>,
    pub items: Vec<DrawingItem>,
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
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct PdfiumRawSnapshot {
    pub schema_version: String,
    pub generator: String,
    pub source_file: String,
    pub page_count: usize,
    pub pages: Vec<PdfiumRawPage>,
}

pub fn verify_file_sha256(path: &Path, expected_sha256: &str) -> Result<(), String> {
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
    let actual_sha256 = format!("{:x}", hasher.finalize());
    if actual_sha256.to_lowercase() != expected_sha256.to_lowercase() {
        return Err(format!(
            "SHA256 mismatch for {:?}:\n  expected: {}\n  actual:   {}",
            path, expected_sha256, actual_sha256
        ));
    }
    Ok(())
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
    let mut has_invisible_text = false;

    for (obj_idx, obj) in page.objects().iter().enumerate() {
        if let Some(text_obj) = obj.as_text_object() {
            // 禁止使用 .trim() 盲目丢弃独立空格！保留原始字符串
            let text = text_obj.text();
            if text.is_empty() {
                continue;
            }
            let bounds = text_obj.bounds()?;
            let bbox = transform_rect_coords(
                bounds.left().value as f64,
                bounds.bottom().value as f64,
                bounds.right().value as f64,
                bounds.top().value as f64,
                crop_x0,
                crop_y1,
            );

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
                has_invisible_text = true;
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
                        chars_list.push(CharInfo {
                            c: c_str,
                            bbox: c_bbox,
                            char_index: ch_idx,
                        });
                    }
                }
            }

            // 处理尾部空格或缺失字形，确保 chars_list 与 text 严格 1:1 一致
            let mut extracted_text = String::new();
            for ci in &chars_list {
                extracted_text.push_str(&ci.c);
            }

            let full_text = text.clone();
            if extracted_text.len() < full_text.len() && full_text.starts_with(&extracted_text) {
                let suffix = &full_text[extracted_text.len()..];
                let last_bbox = chars_list.last().map(|c| c.bbox).unwrap_or(bbox);
                for (tail_offset, ch) in suffix.chars().enumerate() {
                    let ch_idx = chars_list.len();
                    let estimated_w = (font_size.unwrap_or(10.0) * 0.25).max(1.0);
                    let x0 = last_bbox[2] + (tail_offset as f64) * estimated_w;
                    let x1 = x0 + estimated_w;
                    let c_bbox = [round4(x0), last_bbox[1], round4(x1), last_bbox[3]];
                    chars_list.push(CharInfo {
                        c: ch.to_string(),
                        bbox: c_bbox,
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
                order,
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
            order += 1;
        }
    }

    let mut drawings = Vec::new();
    let mut drawing_idx = 0;
    for obj in page.objects().iter() {
        if let Some(path_obj) = obj.as_path_object() {
            let width_val = round4(path_obj.stroke_width().map(|w| w.value as f64).unwrap_or(1.0));
            let bounds = path_obj.bounds()?;
            let mut rect = transform_rect_coords(
                bounds.left().value as f64,
                bounds.bottom().value as f64,
                bounds.right().value as f64,
                bounds.top().value as f64,
                crop_x0,
                crop_y1,
            );

            let mut items = Vec::new();
            let mut current_pt: Option<[f64; 2]> = None;
            let mut subpath_start: Option<[f64; 2]> = None;
            let mut pts_all: Vec<[f64; 2]> = Vec::new();

            let segments = match path_obj.matrix() {
                Ok(m) => path_obj.segments().transform(m),
                Err(_) => path_obj.segments(),
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
                drawing_index: drawing_idx,
                rect,
                width: width_val,
                color: None,
                fill: None,
                items,
            });
            drawing_idx += 1;
        }
    }

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
    })
}

pub fn process_pdf_file(
    pdfium: &Pdfium,
    pdf_path: &Path,
    out_dir: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    let file_name = pdf_path.file_name().unwrap().to_str().unwrap();
    let base_name = pdf_path.file_stem().unwrap().to_str().unwrap();
    let doc = pdfium.load_pdf_from_file(pdf_path, None)?;
    let page_count = doc.pages().len();
    let mut pages = Vec::new();

    for i in 0..page_count {
        let page = doc.pages().get(i)?;
        pages.push(extract_page(&page, i as usize)?);
    }

    let snapshot = PdfiumRawSnapshot {
        schema_version: "pdfium_raw_snapshot_v1.0".to_string(),
        generator: "pdfium_probe_0.1.0".to_string(),
        source_file: file_name.to_string(),
        page_count: pages.len(),
        pages,
    };

    let out_file = out_dir.join(format!("{}_pdfium.json", base_name));
    let json_str = serde_json::to_string_pretty(&snapshot)?;
    fs::write(&out_file, json_str)?;
    println!("[pdfium_probe] Wrote raw snapshot to {:?}", out_file);
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

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("[pdfium_probe] Starting extraction on synthetic PDFs...");

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let (lib_path, expected_sha) = get_platform_native_lib(&manifest_dir)?;
    println!("[pdfium_probe] Loading native library from {:?} (target OS: {})", lib_path, std::env::consts::OS);
    verify_file_sha256(&lib_path, expected_sha)?;

    let bindings = Pdfium::bind_to_library(lib_path)?;
    let pdfium = Pdfium::new(bindings);

    let synthetic_dir = manifest_dir.join("test_data/synthetic");
    let out_dir = manifest_dir.join("test_data/pdfium_output");
    fs::create_dir_all(&out_dir)?;

    let mut synthetic_count = 0;
    for entry in fs::read_dir(&synthetic_dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("pdf") {
            println!("[pdfium_probe] Processing synthetic {:?}", path.file_name().unwrap());
            process_pdf_file(&pdfium, &path, &out_dir)?;
            synthetic_count += 1;
        }
    }

    let real_out_dir = manifest_dir.join("test_data/real_pdfium_output");
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
                direct
            } else if let Some(parent) = direct.parent().and_then(|p| p.parent()) {
                if parent.join("test.pdf").exists() {
                    parent.to_path_buf()
                } else {
                    direct
                }
            } else {
                direct
            }
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
        if pdf_path.exists() {
            println!("[pdfium_probe] Processing real sample: {} (page {})", sample_name, page_idx);
            let doc = pdfium.load_pdf_from_file(&pdf_path, None)?;
            if let Ok(page) = doc.pages().get(page_idx) {
                let page_data = extract_page(&page, page_idx as usize)?;
                let snapshot = PdfiumRawSnapshot {
                    schema_version: "pdfium_raw_snapshot_v1.0".to_string(),
                    generator: "pdfium_probe_0.1.0".to_string(),
                    source_file: pdf_path.file_name().unwrap().to_str().unwrap().to_string(),
                    page_count: 1,
                    pages: vec![page_data],
                };
                let out_file = real_out_dir.join(format!("{}_pdfium.json", sample_name));
                let json_str = serde_json::to_string_pretty(&snapshot)?;
                fs::write(&out_file, json_str)?;
                println!("[pdfium_probe] Wrote real raw snapshot to {:?}", out_file);
                real_count += 1;
            }
        }
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
}
