use crate::clustering::WordTupleDto;
use crate::{
    classifier, detector, extract_page, get_platform_native_lib, markdown, normalizer, table_engine,
};
use pdfium_render::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RegionInput {
    pub page_index: usize,
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case")]
pub enum PublicApiOperation {
    ExtractTextInRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        regions: Vec<RegionInput>,
    },
    ExtractTableInRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        regions: Vec<RegionInput>,
        single: bool,
    },
    ExtractTableStructure {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        page_indices: Option<Vec<usize>>,
        regions: Option<Vec<RegionInput>>,
        ml_model_path: Option<String>,
        ml_confidence: f32,
    },
    ExtractImages {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        page_indices: Option<Vec<usize>>,
    },
    ExtractImageInRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        regions: Vec<RegionInput>,
        single: bool,
    },
    RenderPages {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        dpi: f32,
        page_indices: Option<Vec<usize>>,
    },
    RenderRegion {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        output_dir: String,
        regions: Vec<RegionInput>,
        dpi: f32,
        single: bool,
    },
    ClassifyPage {
        pdf_path: String,
        pdfium_library_path: Option<String>,
        page_index: i64,
    },
}

#[derive(Serialize)]
struct BBoxDto {
    x0: f64,
    y0: f64,
    x1: f64,
    y1: f64,
}

impl BBoxDto {
    fn from_array(rect: [f64; 4]) -> Self {
        Self {
            x0: rect[0],
            y0: rect[1],
            x1: rect[2],
            y1: rect[3],
        }
    }

    fn from_word(word: &WordTupleDto) -> Self {
        Self {
            x0: word.0,
            y0: word.1,
            x1: word.2,
            y1: word.3,
        }
    }

    fn include(&mut self, other: &Self) {
        self.x0 = self.x0.min(other.x0);
        self.y0 = self.y0.min(other.y0);
        self.x1 = self.x1.max(other.x1);
        self.y1 = self.y1.max(other.y1);
    }
}

#[derive(Serialize)]
struct WordDto {
    text: String,
    bbox: BBoxDto,
    chars: Vec<serde_json::Value>,
}

#[derive(Serialize)]
struct LineDto {
    text: String,
    bbox: BBoxDto,
    words: Vec<WordDto>,
}

#[derive(Serialize)]
struct BlockDto {
    text: String,
    bbox: BBoxDto,
    lines: Vec<LineDto>,
}

#[derive(Serialize)]
struct TableCellDto {
    text: String,
    row_index: usize,
    col_index: usize,
    bbox: BBoxDto,
    rowspan: usize,
    colspan: usize,
}

#[derive(Serialize)]
struct TableDto {
    bbox: BBoxDto,
    rows: usize,
    cols: usize,
    cells: Vec<TableCellDto>,
    confidence: Option<f64>,
    source: Option<String>,
    h_lines: Option<Vec<[f64; 4]>>,
    v_lines: Option<Vec<[f64; 4]>>,
}

#[derive(Serialize)]
struct TextCharDto {
    text: String,
    bbox: BBoxDto,
    confidence: Option<f64>,
}

#[derive(Serialize)]
struct TextBlockStructureDto {
    text: String,
    bbox: BBoxDto,
    chars: Vec<TextCharDto>,
}

#[derive(Serialize)]
struct CellStructureDto {
    text: String,
    row_index: usize,
    col_index: usize,
    cell_coord: [[f64; 2]; 4],
    bbox: BBoxDto,
    text_block: TextBlockStructureDto,
    tl_row: usize,
    tl_col: usize,
    br_row: usize,
    br_col: usize,
}

#[derive(Serialize)]
struct TableStructureDto {
    bbox: BBoxDto,
    rows: usize,
    cols: usize,
    cells: Vec<CellStructureDto>,
    confidence: Option<f64>,
    source: Option<String>,
}

fn bind_pdfium(pdfium_library_path: Option<&str>) -> Result<Pdfium, String> {
    let mut attempts = Vec::new();
    if let Some(path) = pdfium_library_path {
        match Pdfium::bind_to_library(path) {
            Ok(bindings) => return Ok(Pdfium::new(bindings)),
            Err(err) => attempts.push(format!("{}: {}", path, err)),
        }
    }
    match get_platform_native_lib(Path::new(env!("CARGO_MANIFEST_DIR"))) {
        Ok((path, _)) => match Pdfium::bind_to_library(&path) {
            Ok(bindings) => return Ok(Pdfium::new(bindings)),
            Err(err) => attempts.push(format!("{}: {}", path.display(), err)),
        },
        Err(err) => attempts.push(err),
    }
    match Pdfium::bind_to_system_library() {
        Ok(bindings) => Ok(Pdfium::new(bindings)),
        Err(err) => {
            attempts.push(format!("system PDFium: {}", err));
            Err(format!(
                "Could not bind PDFium; tried {}",
                attempts.join("; ")
            ))
        }
    }
}

fn with_document<T>(
    pdf_path: &str,
    pdfium_library_path: Option<&str>,
    f: impl FnOnce(&PdfDocument<'_>) -> Result<T, String>,
) -> Result<T, String> {
    let pdfium = bind_pdfium(pdfium_library_path)?;
    let document = pdfium
        .load_pdf_from_file(pdf_path, None)
        .map_err(|err| format!("Could not load PDF {}: {}", pdf_path, err))?;
    f(&document)
}

fn get_page<'a>(document: &'a PdfDocument<'_>, page_index: usize) -> Result<PdfPage<'a>, String> {
    let count = document.pages().len() as usize;
    if page_index >= count {
        return Err(format!(
            "page_index {} out of range (total pages: {})",
            page_index, count
        ));
    }
    document
        .pages()
        .get(page_index as u16)
        .map_err(|err| err.to_string())
}

fn classify_page(document: &PdfDocument<'_>, page_index: usize) -> Result<String, String> {
    let page = get_page(document, page_index)?;
    let raw = extract_page(&page, page_index).map_err(|err| err.to_string())?;
    Ok(classifier::classify_raw_page(&raw).page_type)
}

pub fn classify_page_from_pdf_bytes(
    bytes: &[u8],
    page_index: usize,
    pdfium_library_path: Option<&str>,
) -> Result<String, String> {
    let pdfium = bind_pdfium(pdfium_library_path)?;
    let document = pdfium
        .load_pdf_from_byte_slice(bytes, None)
        .map_err(|err| format!("Could not load PDF bytes: {}", err))?;
    classify_page(&document, page_index)
}

fn intersects(word: &WordTupleDto, region: [f64; 4]) -> bool {
    !(word.2 < region[0] || word.0 > region[2] || word.3 < region[1] || word.1 > region[3])
}

fn extract_region(
    document: &PdfDocument<'_>,
    region: &RegionInput,
) -> Result<Option<BlockDto>, String> {
    let page = get_page(document, region.page_index)?;
    let raw = extract_page(&page, region.page_index).map_err(|err| err.to_string())?;
    let rect = [
        region.x0 * raw.width,
        region.y0 * raw.height,
        region.x1 * raw.width,
        region.y1 * raw.height,
    ];
    let normalized = normalizer::normalize_raw_page_for_public_api(&raw);
    let mut groups: BTreeMap<(usize, usize), Vec<&WordTupleDto>> = BTreeMap::new();
    for word in &normalized.words {
        if intersects(word, rect) {
            groups.entry((word.5, word.6)).or_default().push(word);
        }
    }
    let mut lines = Vec::new();
    for (_, mut words) in groups {
        words.sort_by(|left, right| left.0.total_cmp(&right.0));
        let mut bbox = BBoxDto::from_word(words[0]);
        for word in words.iter().skip(1) {
            bbox.include(&BBoxDto::from_word(word));
        }
        let text = words
            .iter()
            .map(|word| word.4.as_str())
            .collect::<Vec<_>>()
            .join(" ");
        let words = words
            .into_iter()
            .map(|word| WordDto {
                text: word.4.clone(),
                bbox: BBoxDto::from_word(word),
                chars: Vec::new(),
            })
            .collect();
        lines.push(LineDto { text, bbox, words });
    }
    if lines.is_empty() {
        return Ok(None);
    }
    let mut bbox = BBoxDto {
        x0: lines[0].bbox.x0,
        y0: lines[0].bbox.y0,
        x1: lines[0].bbox.x1,
        y1: lines[0].bbox.y1,
    };
    for line in lines.iter().skip(1) {
        bbox.include(&line.bbox);
    }
    let text = lines
        .iter()
        .map(|line| line.text.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    Ok(Some(BlockDto { text, bbox, lines }))
}

fn normalized_page(
    document: &PdfDocument<'_>,
    page_index: usize,
) -> Result<normalizer::NormalizedPageDto, String> {
    let page = get_page(document, page_index)?;
    let raw = extract_page(&page, page_index).map_err(|err| err.to_string())?;
    Ok(normalizer::normalize_raw_page_for_public_api(&raw))
}

fn region_bbox(region: &RegionInput, norm: &normalizer::NormalizedPageDto) -> Option<[f64; 4]> {
    let page = &norm.page_snapshot.as_ref()?.page;
    Some([
        region.x0 * page.width,
        region.y0 * page.height,
        region.x1 * page.width,
        region.y1 * page.height,
    ])
}

fn bbox_intersects(left: [f64; 4], right: [f64; 4]) -> bool {
    left[0] < right[2] && left[2] > right[0] && left[1] < right[3] && left[3] > right[1]
}

fn valid_table(table: &markdown::FullTableDto, allow_empty_line_projection: bool) -> bool {
    let baseline_empty_line_projection = allow_empty_line_projection
        && !table.cells.is_empty()
        && table.source.as_deref() == Some("line_projection")
        && table.cells.iter().all(|cell| cell.text.trim().is_empty());
    if table.rows == 0
        || table.cols == 0
        || (table.rows == 1 && table.cols == 1)
        || (!table.cells.iter().any(|c| !c.text.trim().is_empty())
            && !baseline_empty_line_projection)
    {
        return false;
    }
    let mut occupied = vec![false; table.rows * table.cols];
    for cell in &table.cells {
        if cell.rowspan == 0
            || cell.colspan == 0
            || cell.row_index + cell.rowspan > table.rows
            || cell.col_index + cell.colspan > table.cols
        {
            return false;
        }
        for row in cell.row_index..cell.row_index + cell.rowspan {
            for col in cell.col_index..cell.col_index + cell.colspan {
                let slot = &mut occupied[row * table.cols + col];
                if *slot {
                    return false;
                }
                *slot = true;
            }
        }
    }
    baseline_empty_line_projection || occupied.into_iter().all(|slot| slot)
}

fn recover_table(
    norm: &normalizer::NormalizedPageDto,
    bbox: [f64; 4],
    confidence: Option<f64>,
    label: &str,
    table_id: usize,
    allow_empty_line_projection: bool,
    allow_wireless_recovery: bool,
) -> Option<markdown::FullTableDto> {
    table_engine::recover_table_in_region_with_options(
        norm,
        bbox,
        confidence,
        label,
        table_id,
        allow_empty_line_projection && norm.page_type == "scanned",
        allow_wireless_recovery,
    )
        .filter(|table| {
            valid_table(
                table,
                allow_empty_line_projection && norm.page_type == "scanned",
            )
        })
        .map(|mut table| {
            if let Some(first) = table.cells.first() {
                let mut tight = first.bbox;
                for cell in table.cells.iter().skip(1) {
                    tight[0] = tight[0].min(cell.bbox[0]);
                    tight[1] = tight[1].min(cell.bbox[1]);
                    tight[2] = tight[2].max(cell.bbox[2]);
                    tight[3] = tight[3].max(cell.bbox[3]);
                }
                table.bbox = tight;
            }
            table
        })
}

fn table_lines(
    norm: &normalizer::NormalizedPageDto,
    bbox: [f64; 4],
) -> (Option<Vec<[f64; 4]>>, Option<Vec<[f64; 4]>>) {
    let mut horizontal = Vec::new();
    let mut vertical = Vec::new();
    if let Some(snapshot) = &norm.page_snapshot {
        let is_white = |color: &[f64]| match color {
            [gray] => (gray - 1.0).abs() <= 0.04,
            [red, green, blue, ..] => [red, green, blue]
                .into_iter()
                .all(|component| (component - 1.0).abs() <= 0.04),
            _ => false,
        };
        for drawing in &snapshot.drawings {
            let invisible = match drawing.kind.as_str() {
                "f" => drawing.fill.as_deref().is_some_and(is_white),
                "s" => drawing
                    .stroke
                    .as_deref()
                    .or(drawing.color.as_deref())
                    .is_some_and(is_white),
                _ => false,
            };
            if invisible {
                continue;
            }
            for line in &drawing.lines {
                let rect = &line.rect;
                let dx = (rect.x1 - rect.x0).abs();
                let dy = (rect.y1 - rect.y0).abs();
                if dx >= 3.0 && dy <= 2.3 {
                    let y = (rect.y0 + rect.y1) / 2.0;
                    let x0 = rect.x0.max(bbox[0]);
                    let x1 = rect.x1.min(bbox[2]);
                    if y >= bbox[1] && y <= bbox[3] && x1 > x0 {
                        horizontal.push([x0, y, x1, y]);
                    }
                } else if dy >= 3.0 && dx <= 2.3 {
                    let x = (rect.x0 + rect.x1) / 2.0;
                    let y0 = rect.y0.max(bbox[1]);
                    let y1 = rect.y1.min(bbox[3]);
                    if x >= bbox[0] && x <= bbox[2] && y1 > y0 {
                        vertical.push([x, y0, x, y1]);
                    }
                }
            }
        }
    }
    (
        (!horizontal.is_empty()).then_some(horizontal),
        (!vertical.is_empty()).then_some(vertical),
    )
}

fn ordinary_table(table: markdown::FullTableDto, norm: &normalizer::NormalizedPageDto) -> TableDto {
    let (h_lines, v_lines) = table_lines(norm, table.bbox);
    TableDto {
        bbox: BBoxDto::from_array(table.bbox),
        rows: table.rows,
        cols: table.cols,
        cells: table
            .cells
            .into_iter()
            .map(|cell| TableCellDto {
                text: cell.text,
                row_index: cell.row_index,
                col_index: cell.col_index,
                bbox: BBoxDto::from_array(cell.bbox),
                rowspan: cell.rowspan,
                colspan: cell.colspan,
            })
            .collect(),
        confidence: table.confidence,
        source: table.source,
        h_lines,
        v_lines,
    }
}

fn cell_text_block(norm: &normalizer::NormalizedPageDto, bbox: [f64; 4]) -> TextBlockStructureDto {
    let mut selected = Vec::new();
    if let Some(snapshot) = &norm.page_snapshot {
        for span in &snapshot.spans {
            for ch in &span.characters {
                let rect = &ch.rect;
                let x = (rect.x0 + rect.x1) / 2.0;
                let y = (rect.y0 + rect.y1) / 2.0;
                if x >= bbox[0] && x <= bbox[2] && y >= bbox[1] && y <= bbox[3] {
                    selected.push((
                        ch.raw_source_position.clone(),
                        TextCharDto {
                            text: ch.text.clone(),
                            bbox: BBoxDto {
                                x0: rect.x0,
                                y0: rect.y0,
                                x1: rect.x1,
                                y1: rect.y1,
                            },
                            confidence: None,
                        },
                    ));
                }
            }
        }
    }
    selected.sort_by(|left, right| left.0.cmp(&right.0));
    let chars: Vec<_> = selected.into_iter().map(|(_, ch)| ch).collect();
    let mut bbox_out = BBoxDto {
        x0: 0.0,
        y0: 0.0,
        x1: 0.0,
        y1: 0.0,
    };
    if let Some(first) = chars.first() {
        bbox_out = BBoxDto {
            x0: first.bbox.x0,
            y0: first.bbox.y0,
            x1: first.bbox.x1,
            y1: first.bbox.y1,
        };
        for ch in chars.iter().skip(1) {
            bbox_out.include(&ch.bbox);
        }
    }
    let text = chars.iter().map(|ch| ch.text.as_str()).collect();
    TextBlockStructureDto {
        text,
        bbox: bbox_out,
        chars,
    }
}

fn structure_table(
    table: markdown::FullTableDto,
    norm: &normalizer::NormalizedPageDto,
) -> TableStructureDto {
    TableStructureDto {
        bbox: BBoxDto::from_array(table.bbox),
        rows: table.rows,
        cols: table.cols,
        cells: table
            .cells
            .into_iter()
            .map(|cell| {
                let [x0, y0, x1, y1] = cell.bbox;
                CellStructureDto {
                    text: cell.text,
                    row_index: cell.row_index,
                    col_index: cell.col_index,
                    cell_coord: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                    bbox: BBoxDto::from_array(cell.bbox),
                    text_block: cell_text_block(norm, cell.bbox),
                    tl_row: cell.row_index,
                    tl_col: cell.col_index,
                    br_row: cell.row_index + cell.rowspan - 1,
                    br_col: cell.col_index + cell.colspan - 1,
                }
            })
            .collect(),
        confidence: table.confidence,
        source: table.source,
    }
}

fn detect_page_tables(
    document: &PdfDocument<'_>,
    page_index: usize,
    norm: &normalizer::NormalizedPageDto,
    detector: Option<&mut detector::YoloTableDetector>,
) -> Result<Vec<markdown::FullTableDto>, String> {
    let Some(snapshot) = &norm.page_snapshot else {
        return Ok(Vec::new());
    };
    let mut tables = Vec::new();
    if let Some(detector) = detector {
        let page = get_page(document, page_index)?;
        let words: Vec<[f32; 4]> = norm
            .words
            .iter()
            .map(|word| [word.0 as f32, word.1 as f32, word.2 as f32, word.3 as f32])
            .collect();
        let detections = detector::detect_tables_on_pdf_page_with_detector(&page, &words, detector)
            .map_err(|err| format!("Could not detect tables on page {}: {}", page_index, err))?;
        for detection in detections {
            if let Some(table) = recover_table(
                norm,
                [
                    detection.x0 as f64,
                    detection.y0 as f64,
                    detection.x1 as f64,
                    detection.y1 as f64,
                ],
                Some(detection.score as f64),
                &detection.label,
                tables.len(),
                false,
                true,
            ) {
                tables.push(table);
            }
        }
    }
    let (h_lines, v_lines) =
        table_lines(norm, [0.0, 0.0, snapshot.page.width, snapshot.page.height]);
    let h_lines = h_lines
        .unwrap_or_default()
        .into_iter()
        .map(|line| (line[0], line[1], line[2], line[3]))
        .collect();
    let v_lines = v_lines
        .unwrap_or_default()
        .into_iter()
        .map(|line| (line[0], line[1], line[2], line[3]))
        .collect();
    for (region, _, _) in table_engine::wired::find_table_regions(h_lines, v_lines, 2.3) {
        let bbox = [region.x0, region.y0, region.x1, region.y1];
        if tables.iter().any(|table| bbox_intersects(table.bbox, bbox)) {
            continue;
        }
        if let Some(table) = recover_table(
            norm,
            bbox,
            None,
            "Rust wired candidate",
            tables.len(),
            false,
            true,
        ) {
            tables.push(table);
        }
    }
    Ok(tables)
}

fn table_detector(
    ml_model_path: Option<&str>,
    ml_confidence: f32,
) -> Result<Option<detector::YoloTableDetector>, String> {
    let model = ml_model_path
        .map(std::path::PathBuf::from)
        .or_else(detector::resolve_default_model_path)
        .or_else(|| {
            let path = Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../src/hexai_pdf_parser/ml/table_detector_model/best.onnx");
            path.is_file().then_some(path)
        });
    let Some(model) = model else {
        return Ok(None);
    };
    let config = detector::TableDetectorConfig {
        confidence_threshold: ml_confidence,
        ..Default::default()
    };
    detector::YoloTableDetector::new(&model, config)
        .map(Some)
        .map_err(|err| {
            format!(
                "Could not initialize table detector {}: {}",
                model.display(),
                err
            )
        })
}

#[derive(Serialize)]
struct RenderInfoDto {
    path: String,
    width: u32,
    height: u32,
    dpi: f32,
}

fn render_public_page(page: &PdfPage<'_>, dpi: f32) -> Result<image::DynamicImage, String> {
    if !dpi.is_finite() || dpi <= 0.0 {
        return Err("render dpi must be positive and finite".to_string());
    }
    let width = (page.width().value * dpi / 72.0).ceil().max(1.0) as u32;
    let height = (page.height().value * dpi / 72.0).ceil().max(1.0) as u32;
    let image = crate::render_page_to_image(page, dpi).map_err(|err| err.to_string())?;
    // The shared pipeline rounds pixel dimensions; public APIs retain MuPDF's outward rounding.
    if image.width() == width && image.height() == height {
        Ok(image)
    } else {
        Ok(image.resize_exact(width, height, image::imageops::FilterType::Triangle))
    }
}

fn draw_page_type_badge(
    pdfium: &Pdfium,
    image: &mut image::DynamicImage,
    page_width: f32,
    page_height: f32,
    page_type: &str,
) -> Result<(), String> {
    let label = format!("page_type: {}", page_type);
    let badge_width = (label.len() as f32 * 4.8 + 10.0)
        .max(96.0)
        .min((page_width - 12.0).max(0.0));
    if badge_width <= 0.0 || page_height < 26.0 {
        return Ok(());
    }
    // A separate transparent PDFium page keeps the original PDF and region renders untouched.
    let mut overlay_document = pdfium.create_new_pdf().map_err(|err| err.to_string())?;
    let font = overlay_document.fonts_mut().helvetica();
    let mut overlay_page = overlay_document
        .pages_mut()
        .create_page_at_end(PdfPagePaperSize::new_custom(
            PdfPoints::new(page_width),
            PdfPoints::new(page_height),
        ))
        .map_err(|err| err.to_string())?;
    let fill = PdfColor::new(20, 20, 20, 255);
    let badge = PdfPagePathObject::new_rect(
        &overlay_document,
        PdfRect::new(
            PdfPoints::new(page_height - 20.0),
            PdfPoints::new(6.0),
            PdfPoints::new(page_height - 6.0),
            PdfPoints::new(6.0 + badge_width),
        ),
        Some(fill),
        Some(PdfPoints::new(1.0)),
        Some(fill),
    )
    .map_err(|err| err.to_string())?;
    overlay_page
        .objects_mut()
        .add_path_object(badge)
        .map_err(|err| err.to_string())?;
    let mut text = PdfPageTextObject::new(&overlay_document, label, font, PdfPoints::new(8.0))
        .map_err(|err| err.to_string())?;
    text.set_fill_color(PdfColor::WHITE)
        .map_err(|err| err.to_string())?;
    text.translate(PdfPoints::new(11.0), PdfPoints::new(page_height - 16.0))
        .map_err(|err| err.to_string())?;
    overlay_page
        .objects_mut()
        .add_text_object(text)
        .map_err(|err| err.to_string())?;
    let config = PdfRenderConfig::new()
        .set_target_width(image.width() as i32)
        .set_target_height(image.height() as i32)
        .set_clear_color(PdfColor::new(0, 0, 0, 0));
    let overlay = overlay_page
        .render_with_config(&config)
        .map_err(|err| err.to_string())?
        .as_image();
    image::imageops::overlay(image, &overlay, 0, 0);
    Ok(())
}

fn write_render(
    image: &image::DynamicImage,
    path: &Path,
    dpi: f32,
) -> Result<RenderInfoDto, String> {
    crate::save_image_to_png(image, path)
        .map_err(|err| format!("Could not write render {}: {}", path.display(), err))?;
    Ok(RenderInfoDto {
        path: path.to_string_lossy().into_owned(),
        width: image.width(),
        height: image.height(),
        dpi,
    })
}

pub fn run_public_api_json(request_json: &str) -> Result<String, String> {
    let request: PublicApiOperation = serde_json::from_str(request_json)
        .map_err(|err| format!("Invalid public API request: {}", err))?;
    let data = match request {
        PublicApiOperation::RenderPages {
            pdf_path,
            pdfium_library_path,
            output_dir,
            dpi,
            page_indices,
        } => {
            let pdfium = bind_pdfium(pdfium_library_path.as_deref())?;
            let document = pdfium
                .load_pdf_from_file(&pdf_path, None)
                .map_err(|err| format!("Could not load PDF {}: {}", pdf_path, err))?;
            std::fs::create_dir_all(&output_dir).map_err(|err| err.to_string())?;
            let mut renders = Vec::new();
            // Existing render_pages scans pages in document order and ignores duplicates/invalid indices.
            for page_index in 0..document.pages().len() as usize {
                if page_indices
                    .as_ref()
                    .is_some_and(|indices| !indices.contains(&page_index))
                {
                    continue;
                }
                let page_type = classify_page(&document, page_index)?;
                let mut page = get_page(&document, page_index)?;
                // Full-page rendering matches RenderEngine's in-memory rotation normalization.
                page.set_rotation(PdfPageRenderRotation::None);
                let mut image = render_public_page(&page, dpi)?;
                draw_page_type_badge(
                    &pdfium,
                    &mut image,
                    page.width().value,
                    page.height().value,
                    &page_type,
                )?;
                let path = Path::new(&output_dir).join(format!("page-{:03}.png", page_index));
                renders.push(write_render(&image, &path, dpi)?);
            }
            serde_json::to_value(renders).map_err(|err| err.to_string())?
        }
        PublicApiOperation::RenderRegion {
            pdf_path,
            pdfium_library_path,
            output_dir,
            regions,
            dpi,
            single,
        } => with_document(&pdf_path, pdfium_library_path.as_deref(), |document| {
            std::fs::create_dir_all(&output_dir).map_err(|err| err.to_string())?;
            let mut renders = Vec::new();
            for (region_index, region) in regions.iter().enumerate() {
                let page = get_page(document, region.page_index)?;
                let image = render_public_page(&page, dpi)?;
                let scale = dpi as f64 / 72.0;
                let x0 = (region.x0 * page.width().value as f64 * scale)
                    .floor()
                    .max(0.0) as u32;
                let y0 = (region.y0 * page.height().value as f64 * scale)
                    .floor()
                    .max(0.0) as u32;
                let x1 = (region.x1 * page.width().value as f64 * scale)
                    .ceil()
                    .max(0.0) as u32;
                let y1 = (region.y1 * page.height().value as f64 * scale)
                    .ceil()
                    .max(0.0) as u32;
                let x1 = x1.min(image.width());
                let y1 = y1.min(image.height());
                if x0 >= x1 || y0 >= y1 {
                    return Err("Cannot render an empty region".to_string());
                }
                let crop = image.crop_imm(x0, y0, x1 - x0, y1 - y0);
                let path = Path::new(&output_dir).join(format!(
                    "region-{:03}-{:03}.png",
                    region.page_index, region_index,
                ));
                let render = write_render(&crop, &path, dpi)?;
                if single {
                    return serde_json::to_value(render).map_err(|err| err.to_string());
                }
                renders.push(render);
            }
            serde_json::to_value(renders).map_err(|err| err.to_string())
        })?,
        PublicApiOperation::ExtractImages {
            pdf_path,
            pdfium_library_path,
            output_dir,
            page_indices,
        } => with_document(&pdf_path, pdfium_library_path.as_deref(), |document| {
            let mut images = Vec::new();
            for page_index in 0..document.pages().len() as usize {
                if page_indices
                    .as_ref()
                    .is_some_and(|indices| !indices.contains(&page_index))
                {
                    continue;
                }
                let page = get_page(document, page_index)?;
                images.extend(crate::image_extraction::extract_page_images(
                    &page,
                    page_index,
                    Path::new(&output_dir),
                )?);
            }
            serde_json::to_value(images).map_err(|err| err.to_string())
        })?,
        PublicApiOperation::ExtractImageInRegion {
            pdf_path,
            pdfium_library_path,
            output_dir,
            regions,
            single,
        } => with_document(&pdf_path, pdfium_library_path.as_deref(), |document| {
            let mut pages = BTreeMap::new();
            for region in &regions {
                if !pages.contains_key(&region.page_index) {
                    let page = get_page(document, region.page_index)?;
                    let images = crate::image_extraction::extract_page_images(
                        &page,
                        region.page_index,
                        Path::new(&output_dir),
                    )?;
                    pages.insert(
                        region.page_index,
                        (
                            page.width().value as f64,
                            page.height().value as f64,
                            images,
                        ),
                    );
                }
            }
            let mut output = Vec::new();
            for region in &regions {
                let (width, height, images) = &pages[&region.page_index];
                let bbox = [
                    region.x0 * width,
                    region.y0 * height,
                    region.x1 * width,
                    region.y1 * height,
                ];
                let selected = images
                    .iter()
                    .filter(|image| crate::image_extraction::intersects(image, bbox));
                if single {
                    return serde_json::to_value(selected.into_iter().next())
                        .map_err(|err| err.to_string());
                }
                output.extend(selected.cloned());
            }
            if single {
                Ok(serde_json::Value::Null)
            } else {
                serde_json::to_value(output).map_err(|err| err.to_string())
            }
        })?,
        PublicApiOperation::ExtractTextInRegion {
            pdf_path,
            pdfium_library_path,
            regions,
        } => with_document(&pdf_path, pdfium_library_path.as_deref(), |document| {
            let mut blocks = Vec::new();
            for region in &regions {
                if let Some(block) = extract_region(document, region)? {
                    blocks.push(block);
                }
            }
            serde_json::to_value(blocks).map_err(|err| err.to_string())
        })?,
        PublicApiOperation::ClassifyPage {
            pdf_path,
            pdfium_library_path,
            page_index,
        } => {
            serde_json::json!(with_document(
                &pdf_path,
                pdfium_library_path.as_deref(),
                |document| {
                    let index = usize::try_from(page_index).map_err(|_| {
                        format!(
                            "page_index {} out of range (total pages: {})",
                            page_index,
                            document.pages().len()
                        )
                    })?;
                    classify_page(document, index)
                }
            )?)
        }
        PublicApiOperation::ExtractTableInRegion {
            pdf_path,
            pdfium_library_path,
            regions,
            single,
        } => with_document(&pdf_path, pdfium_library_path.as_deref(), |document| {
            let mut pages = BTreeMap::new();
            let mut tables = Vec::new();
            for region in &regions {
                if !pages.contains_key(&region.page_index) {
                    pages.insert(
                        region.page_index,
                        normalized_page(document, region.page_index)?,
                    );
                }
                let norm = &pages[&region.page_index];
                let table = region_bbox(region, norm)
                    .and_then(|bbox| {
                        recover_table(
                            norm,
                            bbox,
                            None,
                            "Region",
                            tables.len(),
                            true,
                            !(region.x0 <= 0.001
                                && region.y0 <= 0.001
                                && region.x1 >= 0.999
                                && region.y1 >= 0.999),
                        )
                    })
                    .map(|table| ordinary_table(table, norm));
                if single {
                    return serde_json::to_value(table).map_err(|err| err.to_string());
                }
                if let Some(table) = table {
                    tables.push(table);
                }
            }
            if single {
                Ok(serde_json::Value::Null)
            } else {
                serde_json::to_value(tables).map_err(|err| err.to_string())
            }
        })?,
        PublicApiOperation::ExtractTableStructure {
            pdf_path,
            pdfium_library_path,
            page_indices,
            regions,
            ml_model_path,
            ml_confidence,
        } => with_document(&pdf_path, pdfium_library_path.as_deref(), |document| {
            let mut detector = table_detector(ml_model_path.as_deref(), ml_confidence)?;
            let mut output = Vec::new();
            if let Some(regions) = regions {
                let mut pages: BTreeMap<
                    usize,
                    (normalizer::NormalizedPageDto, Vec<markdown::FullTableDto>),
                > = BTreeMap::new();
                for region in &regions {
                    if !pages.contains_key(&region.page_index) {
                        let norm = normalized_page(document, region.page_index)?;
                        let tables = detect_page_tables(
                            document,
                            region.page_index,
                            &norm,
                            detector.as_mut(),
                        )?;
                        pages.insert(region.page_index, (norm, tables));
                    }
                    let (norm, tables) = &pages[&region.page_index];
                    let Some(bbox) = region_bbox(region, norm) else {
                        continue;
                    };
                    let overlapping: Vec<_> = tables
                        .iter()
                        .filter(|table| bbox_intersects(table.bbox, bbox))
                        .collect();
                    if overlapping.is_empty() {
                        if let Some(table) = recover_table(
                            norm,
                            bbox,
                            None,
                            "Region",
                            output.len(),
                            false,
                            true,
                        ) {
                            output.push(structure_table(table, norm));
                        }
                    } else {
                        output.extend(
                            overlapping
                                .into_iter()
                                .map(|table| structure_table(table.clone(), norm)),
                        );
                    }
                }
            } else {
                let indices =
                    page_indices.unwrap_or_else(|| (0..document.pages().len() as usize).collect());
                for page_index in indices {
                    let norm = normalized_page(document, page_index)?;
                    let tables =
                        detect_page_tables(document, page_index, &norm, detector.as_mut())?;
                    output.extend(
                        tables
                            .into_iter()
                            .map(|table| structure_table(table, &norm)),
                    );
                }
            }
            serde_json::to_value(output).map_err(|err| err.to_string())
        })?,
    };
    serde_json::to_string(&serde_json::json!({ "data": data })).map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn image_fixture(name: &str, form: bool, rotated: bool) -> std::path::PathBuf {
        image_fixture_with_form_content(name, form, rotated, "q 50 0 0 50 10 20 cm /Im Do Q")
    }

    fn image_fixture_with_form_content(
        name: &str,
        form: bool,
        rotated: bool,
        form_content: &str,
    ) -> std::path::PathBuf {
        let directory =
            std::env::temp_dir().join(format!("pdfium-images-{}-{}", std::process::id(), name));
        std::fs::create_dir_all(&directory).unwrap();
        let content = if form {
            "q 2 0 0 2 20 20 cm /Fm Do Q"
        } else {
            "q 100 0 0 100 100 200 cm /Im Do Q q 100 0 0 100 300 0 cm /Im Do Q"
        };
        let page_extra = if rotated {
            "/CropBox [50 50 400 400] /Rotate 90"
        } else {
            ""
        };
        let objects = vec![
            "<< /Type /Catalog /Pages 2 0 R >>".as_bytes().to_vec(),
            "<< /Type /Pages /Kids [3 0 R 7 0 R] /Count 2 >>".as_bytes().to_vec(),
            format!("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 400] {} /Resources << /XObject << /Im 5 0 R /Fm 6 0 R >> >> /Contents 4 0 R >>", page_extra).into_bytes(),
            format!("<< /Length {} >>\nstream\n{}\nendstream", content.len(), content).into_bytes(),
            [b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\nstream\n".as_slice(), &[255, 0, 0], b"\nendstream"].concat(),
            format!("<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] /Matrix [1 0 0 1 5 7] /Resources << /XObject << /Im 5 0 R >> >> /Length {} >>\nstream\n{}\nendstream", form_content.len(), form_content).into_bytes(),
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 400] /Resources << /XObject << /Im 5 0 R >> >> /Contents 4 0 R >>".as_bytes().to_vec(),
        ];
        let mut bytes = b"%PDF-1.4\n".to_vec();
        let mut offsets = vec![0];
        for (index, object) in objects.iter().enumerate() {
            offsets.push(bytes.len());
            bytes.extend_from_slice(format!("{} 0 obj\n", index + 1).as_bytes());
            bytes.extend_from_slice(object);
            bytes.extend_from_slice(b"\nendobj\n");
        }
        let start = bytes.len();
        bytes.extend_from_slice(
            format!("xref\n0 {}\n0000000000 65535 f \n", offsets.len()).as_bytes(),
        );
        for offset in offsets.iter().skip(1) {
            bytes.extend_from_slice(format!("{:010} 00000 n \n", offset).as_bytes());
        }
        bytes.extend_from_slice(
            format!(
                "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF",
                offsets.len(),
                start
            )
            .as_bytes(),
        );
        let path = directory.join("images.pdf");
        std::fs::write(&path, bytes).unwrap();
        path
    }

    fn image_request(path: &Path, operation: &str, output: &Path) -> serde_json::Value {
        serde_json::json!({"operation": operation, "pdf_path": path, "output_dir": output, "page_indices": [0]})
    }

    #[test]
    fn images_track_each_placement() {
        let path = image_fixture("placements", false, false);
        let output = path.parent().unwrap().join("export");
        let request = image_request(&path, "extract_images", &output);
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        let images = result["data"].as_array().unwrap();
        assert_eq!(images.len(), 2);
        for (index, image) in images.iter().enumerate() {
            assert_eq!(image["resource_index"], index);
            assert_eq!(image["width"], 1);
            assert_eq!(image["height"], 1);
            let image_path = image["path"].as_str().unwrap();
            assert!(Path::new(image_path).exists());
            assert_eq!(
                image::open(image_path).unwrap().to_rgb8().get_pixel(0, 0).0,
                [255, 0, 0]
            );
        }
        assert_eq!(
            images[0]["bbox"],
            serde_json::json!({"x0":100.0,"y0":100.0,"x1":200.0,"y1":200.0})
        );
        assert_eq!(
            images[1]["bbox"],
            serde_json::json!({"x0":300.0,"y0":300.0,"x1":400.0,"y1":400.0})
        );
    }

    #[test]
    fn images_page_selection_deduplicates_in_document_order() {
        let path = image_fixture("selection", false, false);
        let output = path.parent().unwrap().join("export");
        let mut request = image_request(&path, "extract_images", &output);
        for (indices, expected) in [
            (serde_json::json!([0, 0]), vec![0, 0]),
            (serde_json::json!([1, 0]), vec![0, 0, 1, 1]),
            (serde_json::json!([999, 0]), vec![0, 0]),
            (serde_json::json!([999]), vec![]),
        ] {
            request["page_indices"] = indices;
            let result: serde_json::Value =
                serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
            let pages: Vec<_> = result["data"]
                .as_array()
                .unwrap()
                .iter()
                .map(|image| image["page_index"].as_u64().unwrap())
                .collect();
            assert_eq!(pages, expected);
        }
    }

    #[test]
    fn images_skip_children_fully_clipped_by_form_bbox() {
        let path = image_fixture_with_form_content(
            "form-clipping",
            true,
            false,
            "q 20 0 0 20 10 20 cm /Im Do Q q 20 0 0 20 120 20 cm /Im Do Q",
        );
        let output = path.parent().unwrap().join("export");
        let request = image_request(&path, "extract_images", &output);
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        let images = result["data"].as_array().unwrap();
        assert_eq!(images.len(), 1);
        assert_eq!(
            images[0]["bbox"],
            serde_json::json!({"x0":50.0,"y0":286.0,"x1":90.0,"y1":326.0})
        );
        assert_eq!(std::fs::read_dir(&output).unwrap().count(), 1);
    }

    #[test]
    fn images_region_writes_all_target_page_placements() {
        let path = image_fixture("regions", false, false);
        let output = path.parent().unwrap().join("export");
        let mut request = image_request(&path, "extract_image_in_region", &output);
        request["single"] = serde_json::json!(true);
        // Touching the first image's edge still counts as an intersection.
        request["regions"] =
            serde_json::json!([{ "page_index":0,"x0":0.5,"y0":0.25,"x1":0.6,"y1":0.5 }]);
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(result["data"]["resource_index"], 0);
        assert_eq!(std::fs::read_dir(&output).unwrap().count(), 2);
        request["single"] = serde_json::json!(false);
        request["regions"] = serde_json::json!([
            { "page_index":0,"x0":0.25,"y0":0.25,"x1":0.5,"y1":0.5 },
            { "page_index":0,"x0":0.0,"y0":0.0,"x1":1.0,"y1":1.0 }
        ]);
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(result["data"].as_array().unwrap().len(), 3);
        request["single"] = serde_json::json!(true);
        request["regions"] =
            serde_json::json!([{ "page_index":0,"x0":0.0,"y0":0.0,"x1":0.01,"y1":0.01 }]);
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert!(result["data"].is_null());
    }

    #[test]
    fn images_apply_form_parent_matrix_and_crop_rotation() {
        for (name, form, rotated, bbox) in [
            (
                "form",
                true,
                false,
                serde_json::json!({"x0":50.0,"y0":226.0,"x1":150.0,"y1":326.0}),
            ),
            (
                "rotation",
                false,
                true,
                serde_json::json!({"x0":150.0,"y0":50.0,"x1":250.0,"y1":150.0}),
            ),
        ] {
            let path = image_fixture(name, form, rotated);
            let request = image_request(
                &path,
                "extract_images",
                &path.parent().unwrap().join("export"),
            );
            let result: serde_json::Value =
                serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
            assert_eq!(result["data"][0]["bbox"], bbox);
        }
    }

    #[test]
    fn images_propagate_file_errors() {
        let path = image_fixture("write-error", false, false);
        let request = image_request(&path, "extract_images", &path);
        assert!(run_public_api_json(&request.to_string()).is_err());
    }

    #[test]
    fn images_region_deduplicates_pages_and_keeps_page_scope() {
        let path = image_fixture("page-scope", false, false);
        let output = path.parent().unwrap().join("export");
        let mut request = image_request(&path, "extract_image_in_region", &output);
        request["single"] = serde_json::json!(false);
        request["regions"] = serde_json::json!([
            { "page_index":1,"x0":0.0,"y0":0.0,"x1":0.01,"y1":0.01 },
            { "page_index":1,"x0":0.0,"y0":0.0,"x1":1.0,"y1":1.0 }
        ]);
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(result["data"].as_array().unwrap().len(), 2);
        assert_eq!(std::fs::read_dir(&output).unwrap().count(), 2);
        assert!(output.join("page-001-img-000.png").exists());
        assert!(!output.join("page-000-img-000.png").exists());
        request["regions"][0]["page_index"] = serde_json::json!(999);
        assert!(run_public_api_json(&request.to_string())
            .unwrap_err()
            .contains("out of range"));
    }

    #[test]
    fn accepts_single_axis_tables_when_every_slot_has_one_cell() {
        for (rows, cols) in [(1, 2), (2, 1)] {
            let cells = (0..rows)
                .flat_map(|row| {
                    (0..cols).map(move |col| markdown::TableCellDto {
                        text: format!("{}:{}", row, col),
                        row_index: row,
                        col_index: col,
                        rowspan: 1,
                        colspan: 1,
                        bbox: [col as f64, row as f64, (col + 1) as f64, (row + 1) as f64],
                    })
                })
                .collect();
            let table = markdown::FullTableDto {
                table_id: 0,
                bbox: [0.0, 0.0, cols as f64, rows as f64],
                rows,
                cols,
                cells,
                confidence: None,
                source: None,
            };
            assert!(valid_table(&table, false), "{}x{} table was rejected", rows, cols);
        }
    }

    #[test]
    fn rejects_an_isolated_text_slot_as_a_table() {
        let table = markdown::FullTableDto {
            table_id: 0,
            bbox: [0.0, 0.0, 1.0, 1.0],
            rows: 1,
            cols: 1,
            cells: vec![markdown::TableCellDto {
                text: "isolated text".to_string(),
                row_index: 0,
                col_index: 0,
                rowspan: 1,
                colspan: 1,
                bbox: [0.0, 0.0, 1.0, 1.0],
            }],
            confidence: None,
            source: None,
        };
        assert!(!valid_table(&table, false));
    }

    fn filled_rule_page(fill: Vec<f64>) -> normalizer::NormalizedPageDto {
        let rect = |x0, y0, x1, y1| crate::clustering::make_rect4(x0, y0, x1, y1);
        let lines = [
            rect(10.0, 10.0, 50.0, 10.0),
            rect(10.0, 50.0, 50.0, 50.0),
            rect(10.0, 10.0, 10.0, 50.0),
            rect(50.0, 10.0, 50.0, 50.0),
        ]
        .into_iter()
        .enumerate()
        .map(|(source_order, rect)| crate::drawings::WireDrawingLine {
            schema_version: 1,
            rect,
            width: None,
            color: None,
            source_order,
        })
        .collect();
        normalizer::NormalizedPageDto {
            page_type: "vector".to_string(),
            page_snapshot: Some(normalizer::PageSnapshotWireDto {
                schema_version: 1,
                page_index: 0,
                page: normalizer::PageInfoDto {
                    schema_version: 1,
                    width: 100.0,
                    height: 100.0,
                    rotation: 0,
                },
                text_blocks: Vec::new(),
                spans: Vec::new(),
                words: Vec::new(),
                drawings: vec![crate::drawings::WireDrawingDto {
                    schema_version: 1,
                    kind: "f".to_string(),
                    path_type: "filled".to_string(),
                    lines,
                    rect: rect(10.0, 10.0, 50.0, 50.0),
                    fill: Some(fill),
                    stroke: None,
                    clip: None,
                    source_order: 0,
                    raw_source_position: Vec::new(),
                    color: None,
                    width: None,
                    items: Vec::new(),
                }],
                allowed_regions: Vec::new(),
                excluded_regions: Vec::new(),
                extraction_options: normalizer::ExtractionOptionsWireDto {
                    schema_version: 1,
                    options: serde_json::Map::new(),
                },
            }),
            rawdict: None,
            words: Vec::new(),
            sidecar: serde_json::Value::Null,
            diagnostics: serde_json::Value::Null,
        }
    }

    #[test]
    fn visible_filled_rectangle_contributes_rules_but_white_background_does_not() {
        let (horizontal, vertical) = table_lines(
            &filled_rule_page(vec![0.0, 0.0, 0.0]),
            [0.0, 0.0, 100.0, 100.0],
        );
        assert_eq!(horizontal.unwrap().len(), 2);
        assert_eq!(vertical.unwrap().len(), 2);
        let (horizontal, vertical) = table_lines(
            &filled_rule_page(vec![1.0, 1.0, 1.0]),
            [0.0, 0.0, 100.0, 100.0],
        );
        assert!(horizontal.is_none());
        assert!(vertical.is_none());
    }

    fn fixture(name: &str) -> String {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures")
            .join(name)
            .to_string_lossy()
            .into_owned()
    }

    #[test]
    fn classifies_vector_fixture_through_public_api() {
        let request = serde_json::json!({
            "operation": "classify_page",
            "pdf_path": fixture("page_000_vector.pdf"),
            "page_index": 0
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(value["data"], "vector");
    }

    #[test]
    fn classifies_pdf_bytes_like_pdf_path() {
        let path = fixture("page_000_vector.pdf");
        let bytes = std::fs::read(&path).unwrap();
        let from_bytes = classify_page_from_pdf_bytes(&bytes, 0, None).unwrap();
        let request = serde_json::json!({
            "operation": "classify_page",
            "pdf_path": path,
            "page_index": 0
        });
        let from_path: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(from_bytes, from_path["data"]);
    }

    #[test]
    fn falls_back_after_explicit_library_path_fails() {
        let request = serde_json::json!({
            "operation": "classify_page",
            "pdf_path": fixture("page_000_vector.pdf"),
            "pdfium_library_path": "nonexistent-pdfium-library",
            "page_index": 0
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(value["data"], "vector");
    }

    #[test]
    fn extracts_only_words_intersecting_region() {
        let request = serde_json::json!({
            "operation": "extract_text_in_region",
            "pdf_path": fixture("page_000_vector.pdf"),
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}]
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        let blocks = value["data"].as_array().unwrap();
        assert!(!blocks.is_empty());
        assert!(blocks[0]["bbox"]["x1"].as_f64().unwrap() > 0.0);
        assert!(!blocks[0]["lines"].as_array().unwrap().is_empty());
    }

    #[test]
    fn empty_region_returns_empty_data() {
        let request = serde_json::json!({
            "operation": "extract_text_in_region",
            "pdf_path": fixture("page_000_vector.pdf"),
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.001, "y1": 0.001}]
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(value["data"], serde_json::json!([]));
    }

    #[test]
    fn recovers_wireless_table_from_designated_region() {
        let request = serde_json::json!({
            "operation": "extract_table_in_region",
            "pdf_path": fixture("page_437_wireless.pdf"),
            "single": true,
            "regions": [{"page_index": 0, "x0": 0.14, "y0": 0.17, "x1": 0.86, "y1": 0.35}]
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        let table = &value["data"];
        assert!(!table["cells"].as_array().unwrap().is_empty());
        assert_eq!(table["source"], "wireless_span_recovery");
        assert!(table["h_lines"].is_null());
        assert!(table["v_lines"].is_null());
    }

    #[test]
    fn full_page_wireless_region_rejects_false_positive_but_designated_table_region_recovers() {
        let pdf_path = fixture("page_437_wireless.pdf");
        let full_page = serde_json::json!({
            "operation": "extract_table_in_region",
            "pdf_path": pdf_path,
            "single": true,
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}]
        });
        let full_page_value: serde_json::Value = serde_json::from_str(
            &run_public_api_json(&full_page.to_string()).unwrap(),
        ).unwrap();
        assert!(full_page_value["data"].is_null());

        let designated_region = serde_json::json!({
            "operation": "extract_table_in_region",
            "pdf_path": fixture("page_437_wireless.pdf"),
            "single": true,
            "regions": [{"page_index": 0, "x0": 0.14, "y0": 0.17, "x1": 0.86, "y1": 0.35}]
        });
        let designated_value: serde_json::Value = serde_json::from_str(
            &run_public_api_json(&designated_region.to_string()).unwrap(),
        ).unwrap();
        assert_eq!(designated_value["data"]["source"], "wireless_span_recovery");
        assert!(designated_value["data"]["rows"].as_u64().unwrap() > 1);
    }

    #[test]
    fn scanned_region_apis_match_the_saved_text_and_empty_table_baseline() {
        let baseline: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/rust_public_api/python_baseline.json"
        )).unwrap();
        let saved_apis = &baseline["cases"]["page_705_scanned.pdf"]["apis"];
        let pdf_path = fixture("page_705_scanned.pdf");
        let text_request = serde_json::json!({
            "operation": "extract_text_in_region",
            "pdf_path": pdf_path,
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}]
        });
        let text_value: serde_json::Value = serde_json::from_str(
            &run_public_api_json(&text_request.to_string()).unwrap(),
        ).unwrap();
        assert_eq!(text_value["data"], saved_apis["text_region"]["result"]["data"]);

        let table_request = serde_json::json!({
            "operation": "extract_table_in_region",
            "pdf_path": fixture("page_705_scanned.pdf"),
            "single": true,
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}]
        });
        let table_value: serde_json::Value = serde_json::from_str(
            &run_public_api_json(&table_request.to_string()).unwrap(),
        ).unwrap();
        let saved_table = &saved_apis["table_region"]["result"]["data"];
        assert_eq!(table_value["data"]["bbox"], saved_table["bbox"]);
        assert_eq!(table_value["data"]["rows"], 4);
        assert_eq!(table_value["data"]["cols"], 2);
        assert_eq!(table_value["data"]["source"], "line_projection");
        assert_eq!(table_value["data"]["cells"], saved_table["cells"]);
        assert!(table_value["data"]["cells"]
            .as_array()
            .unwrap()
            .iter()
            .all(|cell| cell["text"] == ""));
    }

    #[test]
    fn returns_null_for_region_without_table() {
        let request = serde_json::json!({
            "operation": "extract_table_in_region",
            "pdf_path": fixture("page_000_vector.pdf"),
            "single": true,
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.2, "y1": 0.2}]
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert!(value["data"].is_null());
    }

    #[test]
    fn multiple_regions_omit_empty_tables() {
        let request = serde_json::json!({
            "operation": "extract_table_in_region",
            "pdf_path": fixture("page_437_wireless.pdf"),
            "single": false,
            "regions": [
                {"page_index": 0, "x0": 0.14, "y0": 0.17, "x1": 0.86, "y1": 0.35},
                {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 0.01, "y1": 0.01}
            ]
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(value["data"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn full_page_structure_has_recovered_cells() {
        let request = serde_json::json!({
            "operation": "extract_table_structure",
            "pdf_path": fixture("page_437_wireless.pdf"),
            "page_indices": [0],
            "ml_confidence": 0.4
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert!(value["data"]
            .as_array()
            .unwrap()
            .iter()
            .any(|table| { !table["cells"].as_array().unwrap().is_empty() }));
    }

    #[test]
    fn structure_cells_have_native_character_geometry_and_no_slot_conflicts() {
        let request = serde_json::json!({
            "operation": "extract_table_structure",
            "pdf_path": fixture("page_437_wireless.pdf"),
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}],
            "ml_confidence": 0.4
        });
        let value: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        let tables = value["data"].as_array().unwrap();
        assert!(!tables.is_empty());
        for table in tables {
            let rows = table["rows"].as_u64().unwrap() as usize;
            let cols = table["cols"].as_u64().unwrap() as usize;
            let mut occupancy = vec![vec![false; cols]; rows];
            for cell in table["cells"].as_array().unwrap() {
                let row = cell["row_index"].as_u64().unwrap() as usize;
                let col = cell["col_index"].as_u64().unwrap() as usize;
                let bottom = cell["br_row"].as_u64().unwrap() as usize;
                let right = cell["br_col"].as_u64().unwrap() as usize;
                assert_eq!(cell["tl_row"], row);
                assert_eq!(cell["tl_col"], col);
                let corners = cell["cell_coord"].as_array().unwrap();
                assert_eq!(corners.len(), 4);
                assert_eq!(
                    corners[0],
                    serde_json::json!([cell["bbox"]["x0"], cell["bbox"]["y0"]])
                );
                assert_eq!(
                    corners[2],
                    serde_json::json!([cell["bbox"]["x1"], cell["bbox"]["y1"]])
                );
                assert!(bottom < rows && right < cols);
                for line in occupancy.iter_mut().take(bottom + 1).skip(row) {
                    for occupied in line.iter_mut().take(right + 1).skip(col) {
                        assert!(!*occupied, "table cells overlap");
                        *occupied = true;
                    }
                }
                if !cell["text"].as_str().unwrap().is_empty() {
                    let chars = cell["text_block"]["chars"].as_array().unwrap();
                    assert!(!chars.is_empty());
                    assert!(chars.iter().all(|ch| ch["bbox"]["x1"].is_number()));
                }
            }
            assert!(occupancy.iter().flatten().all(|occupied| *occupied));
        }
    }

    #[test]
    fn rejects_out_of_range_page() {
        let request = serde_json::json!({
            "operation": "classify_page",
            "pdf_path": fixture("page_000_vector.pdf"),
            "page_index": 999
        });
        assert!(run_public_api_json(&request.to_string()).is_err());
        assert!(classify_page_from_pdf_bytes(
            &std::fs::read(fixture("page_000_vector.pdf")).unwrap(),
            999,
            None
        )
        .is_err());
    }

    #[test]
    fn renders_pages_and_regions_with_badge_and_compatible_dimensions() {
        let output = std::env::temp_dir().join(format!("pdfium-render-api-{}", std::process::id()));
        let request = serde_json::json!({
            "operation": "render_pages", "pdf_path": fixture("page_000_vector.pdf"),
            "output_dir": output.join("pages"), "dpi": 72.0, "page_indices": [0, 0, 999]
        });
        let full: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(full["data"].as_array().unwrap().len(), 1);
        let page = &full["data"][0];
        assert_eq!(page["width"], 597);
        assert_eq!(page["height"], 843);
        assert_eq!(page["dpi"], 72.0);
        let full_image = image::open(page["path"].as_str().unwrap())
            .unwrap()
            .to_rgb8();
        assert!(output.join("pages/page-000.png").is_file());
        assert!(full_image
            .get_pixel(8, 8)
            .0
            .iter()
            .all(|channel| *channel < 30));
        assert!(
            (11..85).any(|x| (9..17).any(|y| full_image.get_pixel(x, y).0[0] > 200)),
            "badge must have white text"
        );
        let request = serde_json::json!({
            "operation": "render_region", "pdf_path": fixture("page_000_vector.pdf"),
            "output_dir": output.join("regions"), "dpi": 72.0, "single": true,
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}]
        });
        let crop: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(crop["data"]["width"], 597);
        assert_eq!(crop["data"]["height"], 843);
        let crop_image = image::open(crop["data"]["path"].as_str().unwrap())
            .unwrap()
            .to_rgb8();
        assert!(crop_image
            .get_pixel(8, 8)
            .0
            .iter()
            .all(|channel| *channel > 240));
        assert!(output.join("regions/region-000-000.png").is_file());
    }

    #[test]
    fn renders_region_list_in_order_with_fractional_pixel_boundaries() {
        let output =
            std::env::temp_dir().join(format!("pdfium-render-regions-{}", std::process::id()));
        let request = serde_json::json!({
            "operation": "render_region", "pdf_path": fixture("page_000_vector.pdf"),
            "output_dir": output, "dpi": 144.0, "single": false,
            "regions": [
                {"page_index": 0, "x0": 0.25, "y0": 0.25, "x1": 0.5, "y1": 0.5},
                {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
            ]
        });
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        let crops = result["data"].as_array().unwrap();
        assert_eq!(crops.len(), 2);
        assert_eq!(crops[0]["width"], 299);
        assert_eq!(crops[0]["height"], 422);
        assert_eq!(crops[1]["width"], 1193);
        assert_eq!(crops[1]["height"], 1685);
        assert!(output.join("region-000-000.png").is_file());
        assert!(output.join("region-000-001.png").is_file());
    }

    #[test]
    fn render_reports_file_errors_and_empty_selection() {
        let blocked =
            std::env::temp_dir().join(format!("pdfium-render-blocked-{}", std::process::id()));
        std::fs::write(&blocked, b"file").unwrap();
        let mut request = serde_json::json!({
            "operation": "render_pages", "pdf_path": fixture("page_000_vector.pdf"),
            "output_dir": blocked, "dpi": 72.0, "page_indices": []
        });
        assert!(run_public_api_json(&request.to_string()).is_err());
        request["output_dir"] = serde_json::json!(blocked.with_extension("empty"));
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(result["data"], serde_json::json!([]));
    }

    #[test]
    fn render_pages_preserves_document_order_and_scanned_baseline_dimensions() {
        let path = image_fixture("render-order", false, false);
        let output = path.parent().unwrap().join("renders");
        let request = serde_json::json!({
            "operation": "render_pages", "pdf_path": path,
            "output_dir": output, "dpi": 72.0, "page_indices": [1, 0, 1]
        });
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        let pages = result["data"].as_array().unwrap();
        assert_eq!(pages.len(), 2);
        assert!(pages[0]["path"].as_str().unwrap().ends_with("page-000.png"));
        assert!(pages[1]["path"].as_str().unwrap().ends_with("page-001.png"));
        for (name, width, height) in [
            ("page_437_wireless.pdf", 595, 843),
            ("page_705_scanned.pdf", 596, 842),
        ] {
            let request = serde_json::json!({
                "operation": "render_pages", "pdf_path": fixture(name),
                "output_dir": output.join(name), "dpi": 72.0
            });
            let result: serde_json::Value =
                serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
            assert_eq!(result["data"][0]["width"], width);
            assert_eq!(result["data"][0]["height"], height);
            let image = image::open(result["data"][0]["path"].as_str().unwrap())
                .unwrap()
                .to_rgb8();
            assert!(image.get_pixel(8, 8).0.iter().all(|channel| *channel < 30));
        }
    }

    #[test]
    fn render_region_preserves_rotated_cropbox_and_reports_invalid_page_and_file_errors() {
        let path = image_fixture("render-rotation", false, true);
        let output = path.parent().unwrap().join("renders");
        let mut request = serde_json::json!({
            "operation": "render_region", "pdf_path": path,
            "output_dir": output, "dpi": 72.0, "single": true,
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}]
        });
        let result: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(result["data"]["width"], 350);
        assert_eq!(result["data"]["height"], 350);
        request["regions"][0]["page_index"] = serde_json::json!(999);
        assert!(run_public_api_json(&request.to_string())
            .unwrap_err()
            .contains("out of range"));
        request["regions"][0]["page_index"] = serde_json::json!(0);
        let blocked = output.join("blocked");
        std::fs::create_dir_all(blocked.join("region-000-000.png")).unwrap();
        request["output_dir"] = serde_json::json!(blocked);
        assert!(run_public_api_json(&request.to_string())
            .unwrap_err()
            .contains("Could not write render"));
    }

    #[test]
    fn render_pages_normalizes_nonsquare_rotation_without_changing_region_viewport_or_source() {
        let output =
            std::env::temp_dir().join(format!("pdfium-render-nonsquare-{}", std::process::id()));
        std::fs::create_dir_all(&output).unwrap();
        let path = output.join("rotated.pdf");
        let pdfium = bind_pdfium(None).unwrap();
        let mut document = pdfium.create_new_pdf().unwrap();
        let mut page = document
            .pages_mut()
            .create_page_at_end(PdfPagePaperSize::new_custom(
                PdfPoints::new(400.0),
                PdfPoints::new(200.0),
            ))
            .unwrap();
        page.set_rotation(PdfPageRenderRotation::Degrees90);
        drop(page);
        document.save_to_file(&path).unwrap();
        drop(document);
        drop(pdfium);
        let original_bytes = std::fs::read(&path).unwrap();
        let request = serde_json::json!({
            "operation": "render_pages", "pdf_path": path,
            "output_dir": output.join("pages"), "dpi": 72.0,
        });
        let full: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(full["data"][0]["width"], 400);
        assert_eq!(full["data"][0]["height"], 200);
        let request = serde_json::json!({
            "operation": "render_region", "pdf_path": path,
            "output_dir": output.join("regions"), "dpi": 72.0, "single": true,
            "regions": [{"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}]
        });
        let region: serde_json::Value =
            serde_json::from_str(&run_public_api_json(&request.to_string()).unwrap()).unwrap();
        assert_eq!(region["data"]["width"], 200);
        assert_eq!(region["data"]["height"], 400);
        assert_eq!(std::fs::read(&path).unwrap(), original_bytes);
    }

    #[test]
    fn rejects_invalid_json() {
        assert!(run_public_api_json("{").is_err());
    }
}
