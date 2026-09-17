use crate::types::{HeaderGridInput, HeaderGridOutput, HeaderTokenInput, HeaderTokenOutput};

pub fn infer_header_structure(input: HeaderGridInput) -> HeaderGridOutput {
    let mut grid = input.grid.clone();
    let mut cells = grid.cells.clone();
    let diagnostics = Vec::new();

    if cells.is_empty() || grid.grid.rows == 0 || grid.grid.cols == 0 {
        return HeaderGridOutput {
            schema_version: 1,
            grid,
            cells,
            diagnostics,
        };
    }

    // 1. Identify left anchor in col 0 (e.g. "项目", "椤圭洰")
    let has_left_anchor = cells.iter().any(|c| {
        (c.text.trim() == "项目"
            || c.text.trim() == "椤圭洰"
            || c.text.trim() == "\u{9879}\u{76ee}")
            && c.col == 0
            && c.row == 0
    });

    // Group labels: "本年金额", "本期金额", "上年金额", "上期金额", "本年发生额", "本期发生额", "上年发生额", "上期发生额"
    let group_labels = [
        "本年金额",
        "本期金额",
        "上年金额",
        "上期金额",
        "本年发生额",
        "本期发生额",
        "上年发生额",
        "上期发生额",
        "\u{672c}\u{5e74}\u{91d1}\u{989d}",
        "\u{672c}\u{671f}\u{91d1}\u{989d}",
        "\u{4e0a}\u{5e74}\u{91d1}\u{989d}",
        "\u{4e0a}\u{671f}\u{91d1}\u{989d}",
        "\u{672c}\u{5e74}\u{53d1}\u{751f}\u{989d}",
        "\u{672c}\u{671f}\u{53d1}\u{751f}\u{989d}",
        "\u{4e0a}\u{5e74}\u{53d1}\u{751f}\u{989d}",
        "\u{4e0a}\u{671f}\u{53d1}\u{751f}\u{989d}",
    ];

    let total_cols = grid.grid.cols;
    let mut modified = false;

    if has_left_anchor && total_cols >= 3 && grid.grid.rows >= 2 {
        for c in cells.iter_mut() {
            let txt = c.text.trim();
            if (txt == "项目" || txt == "椤圭洰" || txt == "\u{9879}\u{76ee}")
                && c.col == 0
                && c.row == 0
            {
                if c.rowspan < 2 {
                    c.rowspan = 2;
                    modified = true;
                }
            } else if c.row == 0 && group_labels.iter().any(|&g| txt.contains(g)) {
                let needed_colspan = (total_cols - 1).max(1);
                if c.colspan < needed_colspan {
                    c.colspan = needed_colspan;
                    modified = true;
                }
            }
        }
    }

    if modified {
        grid.cells = cells.clone();
    }

    HeaderGridOutput {
        schema_version: 1,
        grid,
        cells,
        diagnostics,
    }
}

pub fn merge_header_spans(input: HeaderGridInput) -> HeaderGridOutput {
    let grid = input.grid.clone();
    let mut cells = grid.cells.clone();
    let diagnostics = Vec::new();

    if cells.is_empty() {
        return HeaderGridOutput {
            schema_version: 1,
            grid,
            cells,
            diagnostics,
        };
    }

    cells.sort_by(|a, b| match a.row.cmp(&b.row) {
        std::cmp::Ordering::Equal => a.col.cmp(&b.col),
        other => other,
    });

    HeaderGridOutput {
        schema_version: 1,
        grid,
        cells,
        diagnostics,
    }
}

pub fn normalize_financial_header_tokens(input: HeaderTokenInput) -> HeaderTokenOutput {
    let mut cells = input.cells.clone();
    let diagnostics = Vec::new();

    for c in cells.iter_mut() {
        let text = c.text.trim();
        if text.is_empty() {
            continue;
        }

        if c.row <= 1 {
            let words: Vec<&str> = text.split_whitespace().collect();
            if words.len() > 1 {
                let last = words.last().unwrap();
                let is_num = last
                    .chars()
                    .all(|ch| ch.is_ascii_digit() || ch == ',' || ch == '.' || ch == '-');
                if is_num {
                    let cleaned = words[..words.len() - 1].join(" ");
                    if !cleaned.is_empty() {
                        c.text = cleaned;
                    }
                }
            }
        }
    }

    HeaderTokenOutput {
        schema_version: 1,
        cells,
        diagnostics,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{CellDto, GridDto, LogicalGridDto, Rect4, StructureConfig};

    fn make_test_grid() -> LogicalGridDto {
        let dummy_rect = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 100.0,
            y1: 20.0,
        };
        LogicalGridDto {
            schema_version: 1,
            grid: GridDto {
                schema_version: 1,
                rows: 2,
                cols: 4,
                row_edges: vec![0.0, 10.0, 20.0],
                col_edges: vec![0.0, 25.0, 50.0, 75.0, 100.0],
                occupancy: vec![
                    vec![Some(0), Some(1), None, None],
                    vec![None, Some(2), Some(3), Some(4)],
                ],
            },
            cells: vec![
                CellDto {
                    schema_version: 1,
                    text: "项目".to_string(),
                    row: 0,
                    col: 0,
                    rect: dummy_rect.clone(),
                    rowspan: 1,
                    colspan: 1,
                    source: None,
                },
                CellDto {
                    schema_version: 1,
                    text: "本年金额".to_string(),
                    row: 0,
                    col: 1,
                    rect: dummy_rect.clone(),
                    rowspan: 1,
                    colspan: 1,
                    source: None,
                },
            ],
            empty_slots: Vec::new(),
        }
    }

    #[test]
    fn test_infer_header_structure_promotes_anchor_and_group() {
        let grid = make_test_grid();
        let input = HeaderGridInput {
            schema_version: 1,
            grid,
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };
        let out = infer_header_structure(input);
        assert_eq!(out.cells[0].text, "项目");
        assert_eq!(out.cells[0].rowspan, 2);
        assert_eq!(out.cells[1].text, "本年金额");
        assert_eq!(out.cells[1].colspan, 3);
    }

    #[test]
    fn test_normalize_financial_header_tokens_cleans_numbers() {
        let dummy_rect = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 100.0,
            y1: 20.0,
        };
        let input = HeaderTokenInput {
            schema_version: 1,
            cells: vec![CellDto {
                schema_version: 1,
                text: "期末余额 1,234.50".to_string(),
                row: 0,
                col: 1,
                rect: dummy_rect,
                rowspan: 1,
                colspan: 1,
                source: None,
            }],
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };
        let out = normalize_financial_header_tokens(input);
        assert_eq!(out.cells[0].text, "期末余额");
    }
}
