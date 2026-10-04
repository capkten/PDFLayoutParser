use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use pdfium_render::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineConfig {
    pub output_dir: PathBuf,
    pub render_dpi: f32,
    pub page_indices: Option<Vec<usize>>,
    pub model_path: Option<PathBuf>,
    pub confidence_threshold: f32,
    pub export_renders: bool,
    pub export_pages: bool,
}

impl Default for PipelineConfig {
    fn default() -> Self {
        Self {
            output_dir: PathBuf::from("."),
            render_dpi: 72.0,
            page_indices: None,
            model_path: None,
            confidence_threshold: 0.40,
            export_renders: true,
            export_pages: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PipelineSummaryDto {
    pub pdf_path: String,
    pub output_dir: String,
    pub total_pages: usize,
    pub processed_pages: usize,
    pub page_indices: Vec<usize>,
    pub elapsed_ms: u64,
}

pub fn run_pipeline(
    pdf_path: &Path,
    config: &PipelineConfig,
) -> Result<PipelineSummaryDto, Box<dyn std::error::Error>> {
    let start_time = Instant::now();

    // 1. Validate pdf_path exists. Ensure output directories exist.
    if !pdf_path.exists() {
        return Err(format!("PDF file does not exist: {:?}", pdf_path).into());
    }

    fs::create_dir_all(&config.output_dir)?;
    let pages_dir = config.output_dir.join("pages");
    let renders_dir = config.output_dir.join("renders");
    fs::create_dir_all(&pages_dir)?;
    fs::create_dir_all(&renders_dir)?;

    // 2. Load PDFium library using platform library loader and open pdf_path.
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let (mut lib_path, _) = crate::get_platform_native_lib(&manifest_dir)
        .map_err(|e| format!("Platform native lib error: {}", e))?;

    if !lib_path.exists() {
        let candidates = [
            Path::new("."),
            Path::new("tools/pdfium_probe"),
        ];
        for base in candidates {
            if let Ok((p, _)) = crate::get_platform_native_lib(base) {
                if p.exists() {
                    lib_path = p;
                    break;
                }
            }
        }
    }

    let bindings = if lib_path.exists() {
        Pdfium::bind_to_library(lib_path)?
    } else {
        Pdfium::bind_to_system_library()?
    };
    let pdfium = Pdfium::new(bindings);
    let doc = pdfium.load_pdf_from_file(pdf_path, None)?;

    // 3. Determine target pages.
    let total_pages = doc.pages().len() as usize;
    let target_pages: Vec<usize> = match &config.page_indices {
        Some(indices) => {
            for &idx in indices {
                if idx >= total_pages {
                    return Err(format!(
                        "Requested page index {} exceeds total pages count {}",
                        idx, total_pages
                    )
                    .into());
                }
            }
            indices.clone()
        }
        None => (0..total_pages).collect(),
    };

    // 4. Resolve model_path and initialize YoloTableDetector once for the entire document.
    let model_path: Option<PathBuf> = match &config.model_path {
        Some(p) => {
            if !p.exists() {
                return Err(format!("Specified model path does not exist: {:?}", p).into());
            }
            Some(p.clone())
        }
        None => crate::detector::resolve_default_model_path(),
    };

    let mut table_detector = if let Some(ref m_path) = model_path {
        let detector_config = crate::detector::TableDetectorConfig {
            confidence_threshold: config.confidence_threshold,
            render_dpi: config.render_dpi,
            ..Default::default()
        };
        Some(crate::detector::YoloTableDetector::new(m_path, detector_config)?)
    } else {
        None
    };

    let mut all_page_mds: Vec<String> = Vec::with_capacity(target_pages.len());
    let mut all_page_jsons: Vec<serde_json::Value> = Vec::with_capacity(target_pages.len());

    // 5. For each page in target_pages.
    for &page_idx in &target_pages {
        let page_idx_u16 = u16::try_from(page_idx)
            .map_err(|e| format!("Page index {} exceeds u16 range: {}", page_idx, e))?;
        let page = doc.pages().get(page_idx_u16)?;

        // Stage 1: extract_page & normalize_raw_page_with_meta
        let raw_page = crate::extract_page(&page, page_idx)?;
        let file_name = pdf_path.file_name().and_then(|s| s.to_str());
        let norm_page = crate::normalizer::normalize_raw_page_with_meta(
            &raw_page,
            file_name,
            Some("pdfium_probe pipeline"),
        );

        // Unified Rasterization (Stage 2 export & Stage 3 detection shared)
        let needs_raster = config.export_renders || table_detector.is_some();
        let page_image = if needs_raster {
            Some(crate::render_page_to_image(&page, config.render_dpi)?)
        } else {
            None
        };

        // Stage 2: native page rasterization export
        if config.export_renders {
            if let Some(ref img) = page_image {
                let png_path = renders_dir.join(format!("page-{:03}.png", page_idx));
                crate::save_image_to_png(img, &png_path)?;
            }
        }

        // Stage 3: table detection & conversion (reusing detector session)
        let tables: Vec<crate::markdown::FullTableDto> = if let Some(ref mut detector) = table_detector {
            let words: Vec<[f32; 4]> = norm_page
                .words
                .iter()
                .map(|w| [w.0 as f32, w.1 as f32, w.2 as f32, w.3 as f32])
                .collect();
            let page_size = (page.width().value, page.height().value);
            let detections = if let Some(ref img) = page_image {
                detector.detect_from_image(img, &words, page_size)?
            } else {
                Vec::new()
            };
            let mut recovered_tables = Vec::with_capacity(detections.len());
            for (idx, d) in detections.into_iter().enumerate() {
                let bbox = [d.x0 as f64, d.y0 as f64, d.x1 as f64, d.y1 as f64];
                let recovered = crate::table_engine::recover_table_in_region(
                    &norm_page,
                    bbox,
                    Some(d.score as f64),
                    &d.label,
                    idx,
                );
                if let Some(table) = recovered {
                    recovered_tables.push(table);
                } else {
                    recovered_tables.push(crate::markdown::FullTableDto {
                        table_id: idx,
                        bbox,
                        rows: 0,
                        cols: 0,
                        cells: Vec::new(),
                        confidence: Some(d.score as f64),
                        source: Some(d.label),
                    });
                }
            }
            recovered_tables
        } else {
            Vec::new()
        };

        // Stage 4: layout assembly via recursive XY-Cut
        // Only deduct tables with non-empty recovered cells so unrecovered tables don't swallow page text
        let table_regions: Vec<crate::layout::TableRegionInput> = tables
            .iter()
            .filter(|t| !t.cells.is_empty())
            .map(|t| crate::layout::TableRegionInput {
                bbox: t.bbox,
                table_id: t.table_id,
            })
            .collect();
        let layout_elements = crate::layout::build_page_layout(&norm_page, &table_regions, &[]);

        // Stage 5: page markdown & json export
        let page_md = crate::markdown::render_page_markdown(
            &layout_elements,
            &tables,
            &[],
            &[],
            page_idx,
        );
        let page_json = crate::json_export::export_page_to_json(
            &norm_page,
            &layout_elements,
            &tables,
            page_idx,
        );

        if config.export_pages {
            let md_path = pages_dir.join(format!("page-{:03}.md", page_idx));
            fs::write(&md_path, &page_md)?;

            let json_path = pages_dir.join(format!("page-{:03}.json", page_idx));
            let json_str = serde_json::to_string_pretty(&page_json)?;
            fs::write(&json_path, json_str)?;
        }

        all_page_mds.push(page_md);
        all_page_jsons.push(page_json);
    }

    // 6. Write top-level document products.
    let file_name_str = pdf_path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("");
    let doc_json = crate::json_export::export_document_to_json(file_name_str, all_page_jsons);
    let doc_json_str = serde_json::to_string_pretty(&doc_json)?;
    fs::write(config.output_dir.join("output.json"), doc_json_str)?;

    let output_md = all_page_mds.join("\n\n---\n\n");
    fs::write(config.output_dir.join("output.md"), output_md)?;

    // 7. Return PipelineSummaryDto.
    let elapsed_ms = start_time.elapsed().as_millis() as u64;

    Ok(PipelineSummaryDto {
        pdf_path: pdf_path.to_string_lossy().to_string(),
        output_dir: config.output_dir.to_string_lossy().to_string(),
        total_pages,
        processed_pages: target_pages.len(),
        page_indices: target_pages,
        elapsed_ms,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pipeline_config_defaults() {
        let config = PipelineConfig::default();
        assert_eq!(config.output_dir, PathBuf::from("."));
        assert!((config.render_dpi - 72.0).abs() < f32::EPSILON);
        assert!(config.page_indices.is_none());
        assert!(config.model_path.is_none());
        assert!((config.confidence_threshold - 0.40).abs() < f32::EPSILON);
        assert!(config.export_renders);
        assert!(config.export_pages);
    }

    #[test]
    fn test_pipeline_engine_on_synthetic_pdf() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let synth_pdf = manifest_dir.join("test_data/synthetic/synth_crop_offset.pdf");
        assert!(synth_pdf.exists(), "Synthetic PDF fixture must exist: {:?}", synth_pdf);

        let temp_dir = std::env::temp_dir().join(format!(
            "test_pipeline_engine_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));

        let config = PipelineConfig {
            output_dir: temp_dir.clone(),
            render_dpi: 72.0,
            page_indices: Some(vec![0]),
            model_path: None,
            confidence_threshold: 0.40,
            export_renders: true,
            export_pages: true,
        };

        let summary = run_pipeline(&synth_pdf, &config).expect("run_pipeline should succeed");
        assert!(summary.processed_pages >= 1, "processed_pages must be >= 1");
        assert_eq!(summary.page_indices, vec![0]);
        assert_eq!(summary.total_pages, 1);

        let output_json_path = temp_dir.join("output.json");
        assert!(output_json_path.exists(), "output.json must exist");
        let json_content = fs::read_to_string(&output_json_path).expect("read output.json");
        let json_val: serde_json::Value =
            serde_json::from_str(&json_content).expect("parse output.json as valid JSON");
        assert_eq!(json_val["document"]["page_count"], 1);

        let output_md_path = temp_dir.join("output.md");
        assert!(output_md_path.exists(), "output.md must exist");
        let md_content = fs::read_to_string(&output_md_path).expect("read output.md");
        assert!(!md_content.trim().is_empty(), "output.md must not be empty");

        let page_json_path = temp_dir.join("pages/page-000.json");
        assert!(page_json_path.exists(), "pages/page-000.json must exist");

        let page_md_path = temp_dir.join("pages/page-000.md");
        assert!(page_md_path.exists(), "pages/page-000.md must exist");

        let page_render_path = temp_dir.join("renders/page-000.png");
        assert!(page_render_path.exists(), "renders/page-000.png must exist");

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn test_pipeline_engine_all_pages_and_flag_filtering() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let synth_pdf = manifest_dir.join("test_data/synthetic/synth_crop_offset.pdf");
        assert!(synth_pdf.exists(), "Synthetic PDF fixture must exist: {:?}", synth_pdf);

        let temp_dir = std::env::temp_dir().join(format!(
            "test_pipeline_filtering_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));

        let config = PipelineConfig {
            output_dir: temp_dir.clone(),
            render_dpi: 72.0,
            page_indices: None,
            model_path: None,
            confidence_threshold: 0.40,
            export_renders: false,
            export_pages: false,
        };

        let summary = run_pipeline(&synth_pdf, &config).expect("run_pipeline should succeed");
        assert_eq!(summary.total_pages, 1);
        assert_eq!(summary.processed_pages, 1);
        assert_eq!(summary.page_indices, vec![0]);

        assert!(temp_dir.join("output.json").exists());
        assert!(temp_dir.join("output.md").exists());
        assert!(!temp_dir.join("pages/page-000.json").exists());
        assert!(!temp_dir.join("pages/page-000.md").exists());
        assert!(!temp_dir.join("renders/page-000.png").exists());

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn test_pipeline_engine_invalid_pdf_returns_error() {
        let config = PipelineConfig::default();
        let res = run_pipeline(Path::new("nonexistent_file_definitely_not_found.pdf"), &config);
        assert!(res.is_err(), "Expected error for missing PDF file");
    }

    #[test]
    fn test_pipeline_engine_out_of_bounds_page_index() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let synth_pdf = manifest_dir.join("test_data/synthetic/synth_crop_offset.pdf");
        let config = PipelineConfig {
            page_indices: Some(vec![999]),
            ..Default::default()
        };
        let res = run_pipeline(&synth_pdf, &config);
        assert!(res.is_err(), "Expected error for out-of-bounds page index");
    }

    #[test]
    fn test_pipeline_engine_invalid_model_path() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let synth_pdf = manifest_dir.join("test_data/synthetic/synth_crop_offset.pdf");
        let config = PipelineConfig {
            model_path: Some(PathBuf::from("nonexistent_model_path_12345.onnx")),
            ..Default::default()
        };
        let res = run_pipeline(&synth_pdf, &config);
        assert!(res.is_err(), "Expected error for invalid model path");
    }
}
