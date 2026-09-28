use pdfium_render::prelude::*;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};

#[derive(Serialize)]
struct CharInfo {
    c: String,
    bbox: [f64; 4],
}

#[derive(Serialize)]
struct SpanInfo {
    order: i64,
    text: String,
    bbox: [f64; 4],
    font: Option<String>,
    size: Option<f64>,
    flags: Option<i64>,
    source_position: [i64; 3], // [derived_block, derived_line, derived_span]
    characters: Vec<CharInfo>,
}

#[derive(Serialize)]
struct DrawingItem {
    cmd: String,
    points: Vec<[f64; 2]>,
}

#[derive(Serialize)]
struct DrawingInfo {
    drawing_index: usize,
    rect: [f64; 4],
    width: f64,
    color: Option<Vec<f64>>,
    fill: Option<Vec<f64>>,
    items: Vec<DrawingItem>,
}

#[derive(Serialize)]
struct PageInfo {
    page_index: usize,
    width: f64,
    height: f64,
    rotation: i64,
    crop_box: [f64; 4],
    media_box: [f64; 4],
    spans: Vec<SpanInfo>,
    drawings: Vec<DrawingInfo>,
}

#[derive(Serialize)]
struct DocumentSnapshot {
    generator: String,
    source_file: String,
    page_count: usize,
    pages: Vec<PageInfo>,
}

fn verify_file_sha256(path: &Path, expected_sha256: &str) -> Result<(), String> {
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

fn round4(v: f64) -> f64 {
    (v * 10000.0).round() / 10000.0
}

fn extract_page(page: &PdfPage, page_index: usize) -> Result<PageInfo, Box<dyn std::error::Error>> {
    let width = round4(page.width().value as f64);
    let height = round4(page.height().value as f64);
    let rotation = match page.rotation()? {
        PdfPageRenderRotation::None => 0,
        PdfPageRenderRotation::Degrees90 => 90,
        PdfPageRenderRotation::Degrees180 => 180,
        PdfPageRenderRotation::Degrees270 => 270,
    };

    // 读取真实的 CropBox 与 MediaBox
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

    // 坐标变换闭包：将 PDFium 原始图元坐标（自底向上）映射到视口坐标（以 CropBox 左上角为原点，自顶向下）
    // 注意：与 PyMuPDF rawdict 契约严格对齐——保留页面局部坐标系，不随 page rotation 交换轴向
    let transform_rect = |b: PdfQuadPoints| -> [f64; 4] {
        let raw_x0 = b.left().value as f64;
        let raw_y0 = b.bottom().value as f64;
        let raw_x1 = b.right().value as f64;
        let raw_y1 = b.top().value as f64;

        let vx0 = raw_x0 - crop_x0;
        let vy0 = crop_y1 - raw_y1;
        let vx1 = raw_x1 - crop_x0;
        let vy1 = crop_y1 - raw_y0;

        [
            round4(vx0.min(vx1)),
            round4(vy0.min(vy1)),
            round4(vx0.max(vx1)),
            round4(vy0.max(vy1)),
        ]
    };

    let page_text = page.text().ok();
    let mut spans = Vec::new();
    let mut order = 0i64;

    for obj in page.objects().iter() {
        if let Some(text_obj) = obj.as_text_object() {
            let text = text_obj.text().trim().to_string();
            if text.is_empty() {
                continue;
            }
            let bounds = text_obj.bounds()?;
            let bbox = transform_rect(bounds);

            let font_name = Some(text_obj.font().name());
            let font_size = Some(round4(text_obj.unscaled_font_size().value as f64));

            let mut chars_list = Vec::new();
            if let Some(ref pt) = page_text {
                if let Ok(chars) = text_obj.chars(pt) {
                    for ch in chars.iter() {
                        if let Some(c_str) = ch.unicode_string() {
                            if let Ok(b) = ch.loose_bounds() {
                                let raw_x0 = b.left().value as f64;
                                let raw_y0 = b.bottom().value as f64;
                                let raw_x1 = b.right().value as f64;
                                let raw_y1 = b.top().value as f64;
                                let vx0 = raw_x0 - crop_x0;
                                let vy0 = crop_y1 - raw_y1;
                                let vx1 = raw_x1 - crop_x0;
                                let vy1 = crop_y1 - raw_y0;
                                chars_list.push(CharInfo {
                                    c: c_str,
                                    bbox: [
                                        round4(vx0.min(vx1)),
                                        round4(vy0.min(vy1)),
                                        round4(vx0.max(vx1)),
                                        round4(vy0.max(vy1)),
                                    ],
                                });
                            }
                        }
                    }
                }
            }

            spans.push(SpanInfo {
                order,
                text,
                bbox,
                font: font_name,
                size: font_size,
                flags: None,
                source_position: [0, 0, order],
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
            let mut rect = transform_rect(bounds);

            let mut items = Vec::new();
            let mut current_pt: Option<[f64; 2]> = None;
            let mut subpath_start: Option<[f64; 2]> = None;
            let mut pts_all: Vec<[f64; 2]> = Vec::new();

            for seg in path_obj.segments().iter() {
                let (pt_x, pt_y) = seg.point();
                let raw_x = pt_x.value as f64;
                let raw_y = pt_y.value as f64;
                let vx = round4(raw_x - crop_x0);
                let vy = round4(crop_y1 - raw_y);
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

    Ok(PageInfo {
        page_index,
        width,
        height,
        rotation,
        crop_box,
        media_box,
        spans,
        drawings,
    })
}

fn process_pdf_file(
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

    let snapshot = DocumentSnapshot {
        generator: "pdfium_probe_0.1.0".to_string(),
        source_file: file_name.to_string(),
        page_count: pages.len(),
        pages,
    };

    let out_file = out_dir.join(format!("{}_pdfium.json", base_name));
    let json_str = serde_json::to_string_pretty(&snapshot)?;
    fs::write(&out_file, json_str)?;
    println!("[pdfium_probe] Wrote snapshot to {:?}", out_file);
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("[pdfium_probe] Starting extraction on synthetic PDFs...");

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let lib_path = manifest_dir.join("native/win-x64/pdfium.dll");
    let expected_dll_sha256 = "d42c452a4cf8ca19a87e9c659d4e05035be742c21696ac13431cf73ac1bbf14b";
    verify_file_sha256(&lib_path, expected_dll_sha256)?;

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

    // 增加真实代表页提取
    let real_out_dir = manifest_dir.join("test_data/real_pdfium_output");
    fs::create_dir_all(&real_out_dir)?;

    let real_samples = [
        ("d:/codes/PDFLayoutParser/test.pdf", 0, "test_p0_cover"),
        ("d:/codes/PDFLayoutParser/test.pdf", 1, "test_p1_toc"),
        ("d:/codes/PDFLayoutParser/test.pdf", 27, "test_p27_table"),
        ("d:/codes/PDFLayoutParser/征信解析样例.pdf", 0, "credit_p0_header"),
    ];

    let mut real_count = 0;
    for (pdf_path_str, page_idx, sample_name) in real_samples {
        let p = Path::new(pdf_path_str);
        if p.exists() {
            println!("[pdfium_probe] Processing real sample: {} (page {})", sample_name, page_idx);
            let doc = pdfium.load_pdf_from_file(p, None)?;
            if let Ok(page) = doc.pages().get(page_idx) {
                let page_data = extract_page(&page, page_idx as usize)?;
                let snapshot = DocumentSnapshot {
                    generator: "pdfium_probe_0.1.0".to_string(),
                    source_file: p.file_name().unwrap().to_str().unwrap().to_string(),
                    page_count: 1,
                    pages: vec![page_data],
                };
                let out_file = real_out_dir.join(format!("{}_pdfium.json", sample_name));
                let json_str = serde_json::to_string_pretty(&snapshot)?;
                fs::write(&out_file, json_str)?;
                println!("[pdfium_probe] Wrote real snapshot to {:?}", out_file);
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
