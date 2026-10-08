pub mod geometry;
pub mod native_span;
pub mod snapshot;
pub mod types;
pub mod wired;
pub mod wireless_structure;

pub use geometry::Line4;
pub use types::*;

fn is_color_similar(c: &[f64], bg: &[f64; 3], tol: f64) -> bool {
    if c.len() >= 3 {
        (c[0] - bg[0]).abs() <= tol
            && (c[1] - bg[1]).abs() <= tol
            && (c[2] - bg[2]).abs() <= tol
    } else if c.len() == 1 {
        (c[0] - bg[0]).abs() <= tol
            && (c[0] - bg[1]).abs() <= tol
            && (c[0] - bg[2]).abs() <= tol
    } else {
        false
    }
}

fn is_drawing_visible(drawing: &crate::drawings::WireDrawingDto, bg_color: &[f64; 3]) -> bool {
    let tol = 0.04;
    if drawing.kind == "f" {
        if let Some(ref fill) = drawing.fill {
            if is_color_similar(fill, bg_color, tol) {
                return false;
            }
        }
    } else if drawing.kind == "s" {
        if let Some(ref stroke) = drawing.stroke {
            if is_color_similar(stroke, bg_color, tol) {
                return false;
            }
        } else if let Some(ref color) = drawing.color {
            if is_color_similar(color, bg_color, tol) {
                return false;
            }
        }
    }
    true
}

/// Recovers table structure for a detected table bounding box from page normalizer data.
/// Tries wired extraction first if vector lines exist; falls back to native-span wireless recovery.
pub fn recover_table_in_region(
    norm_page: &crate::normalizer::NormalizedPageDto,
    bbox: [f64; 4],
    confidence: Option<f64>,
    _label: &str,
    table_id: usize,
) -> Option<crate::markdown::FullTableDto> {
    recover_table_in_region_with_options(
        norm_page, bbox, confidence, _label, table_id, false, true,
    )
}

pub fn recover_table_in_region_with_options(
    norm_page: &crate::normalizer::NormalizedPageDto,
    bbox: [f64; 4],
    confidence: Option<f64>,
    _label: &str,
    table_id: usize,
    allow_empty_line_projection: bool,
    allow_wireless_recovery: bool,
) -> Option<crate::markdown::FullTableDto> {
    let snapshot = norm_page.page_snapshot.as_ref()?;
    let tol = 2.3;

    // 1. Try wired table extraction if line drawings intersect the region
    let mut h_lines = Vec::new();
    let mut v_lines = Vec::new();

    let bg_color = [1.0, 1.0, 1.0];
    for drawing in &snapshot.drawings {
        if !is_drawing_visible(drawing, &bg_color) {
            continue;
        }
        for line in &drawing.lines {
            let r = &line.rect;
            if r.x1 >= bbox[0] - tol
                && r.x0 <= bbox[2] + tol
                && r.y1 >= bbox[1] - tol
                && r.y0 <= bbox[3] + tol
            {
                let dx = (r.x1 - r.x0).abs();
                let dy = (r.y1 - r.y0).abs();
                if dx >= 3.0 && dy <= 2.3 {
                    let cy = (r.y0 + r.y1) / 2.0;
                    h_lines.push(LineDto {
                        schema_version: 1,
                        rect: Rect4 {
                            schema_version: 1,
                            x0: r.x0.min(r.x1),
                            y0: cy,
                            x1: r.x0.max(r.x1),
                            y1: cy,
                        },
                        width: line.width,
                        color: line.color,
                        source_order: line.source_order as i64,
                    });
                } else if dy >= 3.0 && dx <= 2.3 {
                    let cx = (r.x0 + r.x1) / 2.0;
                    v_lines.push(LineDto {
                        schema_version: 1,
                        rect: Rect4 {
                            schema_version: 1,
                            x0: cx,
                            y0: r.y0.min(r.y1),
                            x1: cx,
                            y1: r.y0.max(r.y1),
                        },
                        width: line.width,
                        color: line.color,
                        source_order: line.source_order as i64,
                    });
                }
            }
        }
    }

    if h_lines.len() >= 2 && !v_lines.is_empty() {
        let mut words = Vec::new();
        for (w_idx, w) in norm_page.words.iter().enumerate() {
            let wx0 = w.x0();
            let wy0 = w.y0();
            let wx1 = w.x1();
            let wy1 = w.y1();
            let cx = (wx0 + wx1) / 2.0;
            let cy = (wy0 + wy1) / 2.0;
            if cx >= bbox[0] && cx <= bbox[2] && cy >= bbox[1] && cy <= bbox[3] {
                words.push(WordDto {
                    schema_version: 1,
                    text: w.text().to_string(),
                    rect: Rect4 {
                        schema_version: 1,
                        x0: wx0,
                        y0: wy0,
                        x1: wx1,
                        y1: wy1,
                    },
                    order: w_idx as i64,
                    block: Some(w.block_idx() as i64),
                    line: Some(w.line_idx() as i64),
                });
            }
        }

        let wired_input = WiredRegionInput {
            schema_version: 1,
            page: PageDto {
                schema_version: 1,
                width: snapshot.page.width,
                height: snapshot.page.height,
                rotation: snapshot.page.rotation,
            },
            h_lines,
            v_lines,
            words,
            tolerance: tol,
        };

        let wired_output = wired::extract_wired_region(wired_input);
        let region_cells: Vec<_> = wired_output
            .cells
            .into_iter()
            .filter(|c| {
                let cx = (c.rect.x0 + c.rect.x1) / 2.0;
                let cy = (c.rect.y0 + c.rect.y1) / 2.0;
                cx >= bbox[0] - tol
                    && cx <= bbox[2] + tol
                    && cy >= bbox[1] - tol
                    && cy <= bbox[3] + tol
            })
            .collect();

        if !region_cells.is_empty()
            && (region_cells.iter().any(|c| !c.text.trim().is_empty())
                || (allow_empty_line_projection && norm_page.page_type == "scanned"))
        {
            let num_rows = region_cells
                .iter()
                .map(|c| (c.row + c.rowspan) as usize)
                .max()
                .unwrap_or(0);
            let num_cols = region_cells
                .iter()
                .map(|c| (c.col + c.colspan) as usize)
                .max()
                .unwrap_or(0);
            if num_rows >= 1 && num_cols >= 1 {
                let table_cells: Vec<crate::markdown::TableCellDto> = region_cells
                    .into_iter()
                    .map(|c| crate::markdown::TableCellDto {
                        text: c.text,
                        row_index: c.row as usize,
                        col_index: c.col as usize,
                        rowspan: c.rowspan.max(1) as usize,
                        colspan: c.colspan.max(1) as usize,
                        bbox: [c.rect.x0, c.rect.y0, c.rect.x1, c.rect.y1],
                    })
                    .collect();

                return Some(crate::markdown::FullTableDto {
                    table_id,
                    bbox,
                    rows: num_rows,
                    cols: num_cols,
                    cells: table_cells,
                    confidence,
                    source: Some("line_projection".to_string()),
                });
            }
        }
    }

    if !allow_wireless_recovery {
        return None;
    }

    // 2. Wireless native-span table recovery
    let region_rect = Rect4 {
        schema_version: 1,
        x0: bbox[0],
        y0: bbox[1],
        x1: bbox[2],
        y1: bbox[3],
    };

    let raw_input_spans = snapshot::collect_native_spans_from_wire(
        snapshot,
        Some(&[region_rect.clone()]),
        None,
    );

    if !raw_input_spans.is_empty() {
        let span_dtos: Vec<NativeSpanDto> = raw_input_spans.iter().map(|s| s.span.clone()).collect();
        let runs = native_span::build_text_runs(span_dtos, region_rect.clone());
        let atoms = native_span::build_atoms(runs, Some(region_rect.clone()));

        let mut candidate_cells = Vec::new();

        if !atoms.is_empty() {
            let native_input = NativeRegionInput {
                schema_version: 1,
                region: RegionDto {
                    schema_version: 1,
                    rect: region_rect.clone(),
                    source_order: 0,
                    allowed: true,
                },
                atoms,
                bands: Vec::new(),
                atom_evidence: None,
                band_evidence: None,
                output_mode: "zh".to_string(),
                config: StructureConfig::default(),
            };
            let native_output = wireless_structure::recover_native_region(native_input);
            if !native_output.cells.is_empty()
                && native_output.cells.iter().any(|c| !c.text.trim().is_empty())
            {
                candidate_cells = native_output.cells;
            }
        }

        if candidate_cells.is_empty() {
            let wireless_output =
                wireless_structure::recover_cells_from_spans(raw_input_spans, &region_rect);
            if !wireless_output.cells.is_empty()
                && wireless_output.cells.iter().any(|c| !c.text.trim().is_empty())
            {
                candidate_cells = wireless_output.cells;
            }
        }

        if !candidate_cells.is_empty() {
            let num_rows = candidate_cells
                .iter()
                .map(|c| (c.row + c.rowspan) as usize)
                .max()
                .unwrap_or(0);
            let num_cols = candidate_cells
                .iter()
                .map(|c| (c.col + c.colspan) as usize)
                .max()
                .unwrap_or(0);
            if num_rows >= 1 && num_cols >= 1 {
                let table_cells: Vec<crate::markdown::TableCellDto> = candidate_cells
                    .into_iter()
                    .map(|c| crate::markdown::TableCellDto {
                        text: c.text,
                        row_index: c.row as usize,
                        col_index: c.col as usize,
                        rowspan: c.rowspan.max(1) as usize,
                        colspan: c.colspan.max(1) as usize,
                        bbox: [c.rect.x0, c.rect.y0, c.rect.x1, c.rect.y1],
                    })
                    .collect();

                return Some(crate::markdown::FullTableDto {
                    table_id,
                    bbox,
                    rows: num_rows,
                    cols: num_cols,
                    cells: table_cells,
                    confidence,
                    source: Some("wireless_span_recovery".to_string()),
                });
            }
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use pdfium_render::prelude::*;
    use std::path::{Path, PathBuf};

    fn find_pdf_fixture(manifest_dir: &Path) -> Option<PathBuf> {
        let mut cur = Some(manifest_dir);
        while let Some(dir) = cur {
            let p = dir.join("fix/zh_all_table_pages.pdf");
            if p.is_file() {
                return Some(p);
            }
            cur = dir.parent();
        }
        let fallback = PathBuf::from(r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf");
        if fallback.is_file() {
            return Some(fallback);
        }
        None
    }

    #[test]
    fn test_recover_table_p597_filters_filled_paths() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let pdf_path = find_pdf_fixture(&manifest_dir).expect("fix/zh_all_table_pages.pdf must exist");
        let (lib_path, _) = crate::get_platform_native_lib(&manifest_dir).unwrap();
        let bindings = Pdfium::bind_to_library(lib_path).unwrap();
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(&pdf_path, None).unwrap();
        let page = doc.pages().get(597).unwrap();
        let raw_page = crate::extract_page(&page, 597).unwrap();
        let norm_page = crate::normalizer::normalize_raw_page_with_meta(
            &raw_page,
            Some("zh_all_table_pages.pdf"),
            Some("test_p597"),
        );
        let recovered = recover_table_in_region(
            &norm_page,
            [85.2, 148.7, 547.6, 346.7],
            Some(0.95),
            "Table",
            0,
        )
        .expect("table should be recovered on page 597");

        println!("recovered p597: source={:?}, rows={}, cols={}, cells={}", recovered.source, recovered.rows, recovered.cols, recovered.cells.len());
        for c in &recovered.cells {
            if c.row_index > 8 {
                println!("  cell at row={}: bbox={:?} text={:?}", c.row_index, c.bbox, c.text);
            }
        }

        assert!(
            recovered.rows <= 12,
            "Expected recovered.rows <= 12, but got {}",
            recovered.rows
        );
        assert!(
            recovered.cols <= 8,
            "Expected recovered.cols <= 8, but got {}",
            recovered.cols
        );
    }

    #[test]
    fn test_recover_table_p1_extracts_filled_rect_wired_table() {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let pdf_path = find_pdf_fixture(&manifest_dir).expect("fix/zh_all_table_pages.pdf must exist");
        let (lib_path, _) = crate::get_platform_native_lib(&manifest_dir).unwrap();
        let bindings = Pdfium::bind_to_library(lib_path).unwrap();
        let pdfium = Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(&pdf_path, None).unwrap();
        let page = doc.pages().get(1).unwrap();
        let raw_page = crate::extract_page(&page, 1).unwrap();
        let norm_page = crate::normalizer::normalize_raw_page_with_meta(
            &raw_page,
            Some("zh_all_table_pages.pdf"),
            Some("test_p1"),
        );
        let recovered = recover_table_in_region(
            &norm_page,
            [63.0, 82.0, 532.0, 711.0],
            Some(0.95),
            "Table",
            0,
        )
        .expect("table on page 1 should be recovered as wired table");

        assert!(recovered.rows >= 6, "Expected recovered.rows >= 6, got {}", recovered.rows);
        assert!(recovered.cols >= 2, "Expected recovered.cols >= 2, got {}", recovered.cols);
        assert_eq!(recovered.source.as_deref(), Some("line_projection"));
    }
}
