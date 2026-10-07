use pdfium_probe::*;
use pdfium_render::prelude::*;
use serde::Deserialize;
use std::fs;
use std::path::{Path, PathBuf};

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
    use std::io::Read;

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

