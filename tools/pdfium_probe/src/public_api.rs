use crate::clustering::WordTupleDto;
use crate::{classifier, extract_page, get_platform_native_lib, normalizer};
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
        page_index: usize,
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
    let normalized = normalizer::normalize_raw_page(&raw);
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

pub fn run_public_api_json(request_json: &str) -> Result<String, String> {
    let request: PublicApiOperation = serde_json::from_str(request_json)
        .map_err(|err| format!("Invalid public API request: {}", err))?;
    let data = match request {
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
                |document| { classify_page(document, page_index) }
            )?)
        }
        _ => return Err("Public API operation is not implemented yet".to_string()),
    };
    serde_json::to_string(&serde_json::json!({ "data": data })).map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn rejects_unsupported_operation_and_invalid_json() {
        let request = serde_json::json!({
            "operation": "render_pages",
            "pdf_path": fixture("page_000_vector.pdf"),
            "output_dir": "unused",
            "dpi": 72.0
        });
        assert!(run_public_api_json(&request.to_string())
            .unwrap_err()
            .contains("not implemented"));
        assert!(run_public_api_json("{").is_err());
    }
}
