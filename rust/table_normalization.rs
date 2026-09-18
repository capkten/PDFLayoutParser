use crate::types::{
    CellDto, HeaderGridInput, HeaderGridOutput, HeaderTokenInput, HeaderTokenOutput,
};

pub fn infer_header_structure(input: HeaderGridInput) -> HeaderGridOutput {
    let mut grid = input.grid.clone();
    let mut cells = grid.cells.clone();
    let mut diagnostics = Vec::new();

    if cells.is_empty() || grid.grid.rows == 0 || grid.grid.cols == 0 {
        return HeaderGridOutput {
            schema_version: 1,
            grid,
            cells,
            diagnostics,
        };
    }

    let total_rows = grid.grid.rows.max(0) as usize;
    let total_cols = grid.grid.cols.max(0) as usize;
    let top_indices: Vec<usize> = cells
        .iter()
        .enumerate()
        .filter(|(_, cell)| cell.row == 0 && !cell.text.trim().is_empty())
        .map(|(index, _)| index)
        .collect();
    let lower_indices: Vec<usize> = cells
        .iter()
        .enumerate()
        .filter(|(_, cell)| cell.row == 1 && !cell.text.trim().is_empty())
        .map(|(index, _)| index)
        .collect();

    if total_rows >= 2 && !top_indices.is_empty() && !lower_indices.is_empty() {
        let mut group_ranges: Vec<(usize, usize, usize)> = Vec::new();

        for (position, top_index) in top_indices.iter().enumerate() {
            let top = &cells[*top_index];
            let start = top.col.max(0) as usize;
            let next_start = top_indices
                .get(position + 1)
                .map(|next| cells[*next].col.max(0) as usize)
                .unwrap_or(total_cols)
                .min(total_cols);
            if start >= next_start || start >= total_cols {
                continue;
            }

            let mut valid = true;
            let mut child_count = 0usize;
            for column in start..next_start {
                let matching: Vec<&CellDto> = lower_indices
                    .iter()
                    .map(|index| &cells[*index])
                    .filter(|child| {
                        let child_start = child.col.max(0) as usize;
                        let child_end = child_start.saturating_add(child.colspan.max(1) as usize);
                        child_start <= column && column < child_end
                    })
                    .collect();
                if matching.len() != 1 {
                    valid = false;
                    break;
                }
                child_count += 1;
            }

            if valid && child_count >= 2 {
                group_ranges.push((*top_index, start, next_start));
            }
        }

        for (top_index, start, end) in &group_ranges {
            let cell = &mut cells[*top_index];
            let required = (*end - *start) as i64;
            if cell.colspan < required {
                cell.colspan = required;
            }
        }

        if let Some((_, group_start, _)) = group_ranges.first() {
            if *group_start > 0 {
                if let Some(stub) = cells
                    .iter_mut()
                    .find(|cell| cell.row == 0 && cell.col == 0 && !cell.text.trim().is_empty())
                {
                    stub.rowspan = stub.rowspan.max(2);
                }
            }
        }

        // A first-row cell may be a vertical stub.  Extend it only when all
        // covered slots in the second row are empty.
        let lower_spans: Vec<(usize, usize)> = lower_indices
            .iter()
            .map(|index| {
                let child = &cells[*index];
                let start = child.col.max(0) as usize;
                (start, start.saturating_add(child.colspan.max(1) as usize))
            })
            .collect();
        for cell in cells.iter_mut().filter(|cell| cell.row == 0) {
            let start = cell.col.max(0) as usize;
            let end = start.saturating_add(cell.colspan.max(1) as usize);
            let lower_has_text = lower_spans
                .iter()
                .any(|(child_start, child_end)| *child_start < end && *child_end > start);
            if !lower_has_text && cell.rowspan == 1 {
                cell.rowspan = 2;
            }
        }

        // Some extracted grids put the stub in row one while row zero starts
        // with an empty slot.  The topology still identifies that stub without
        // relying on its business label.
        let row_zero_col_zero_has_text = cells
            .iter()
            .any(|cell| cell.row == 0 && cell.col == 0 && !cell.text.trim().is_empty());
        if !row_zero_col_zero_has_text {
            if let Some(stub) = cells
                .iter_mut()
                .find(|cell| cell.row == 1 && cell.col == 0 && !cell.text.trim().is_empty())
            {
                if stub.rowspan == 1 {
                    stub.rowspan = 2;
                }
            }
        }

        if !group_ranges.is_empty() {
            cells.retain(|cell| {
                if cell.row != 0 || !cell.text.trim().is_empty() {
                    return true;
                }
                !group_ranges.iter().any(|(_, start, end)| {
                    let column = cell.col.max(0) as usize;
                    column >= *start && column < *end
                })
            });
        }
    }

    let mut occupancy = vec![vec![None; total_cols]; total_rows];
    for (index, cell) in cells.iter().enumerate() {
        let row_start = cell.row.max(0) as usize;
        let col_start = cell.col.max(0) as usize;
        for row in row_start..row_start.saturating_add(cell.rowspan.max(1) as usize) {
            for col in col_start..col_start.saturating_add(cell.colspan.max(1) as usize) {
                if row >= total_rows || col >= total_cols {
                    continue;
                }
                if occupancy[row][col].is_some() {
                    diagnostics.push(crate::types::DiagnosticDto {
                        schema_version: 1,
                        status: "occupancy_conflict".to_string(),
                        path: "table_normalization.infer_header_structure".to_string(),
                        error_type: Some("OccupancyConflict".to_string()),
                        message: Some(format!("multiple cells claim slot ({row}, {col})")),
                        traceback_id: None,
                        field: Some("occupancy".to_string()),
                        python_value: None,
                        rust_value: None,
                        classification: Some("defect".to_string()),
                    });
                } else {
                    occupancy[row][col] = Some(index as i64);
                }
            }
        }
    }
    grid.grid.occupancy = occupancy;
    grid.cells = cells.clone();

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
                CellDto {
                    schema_version: 1,
                    text: "左叶".to_string(),
                    row: 1,
                    col: 1,
                    rect: dummy_rect.clone(),
                    rowspan: 1,
                    colspan: 1,
                    source: None,
                },
                CellDto {
                    schema_version: 1,
                    text: "中叶".to_string(),
                    row: 1,
                    col: 2,
                    rect: dummy_rect.clone(),
                    rowspan: 1,
                    colspan: 1,
                    source: None,
                },
                CellDto {
                    schema_version: 1,
                    text: "右叶".to_string(),
                    row: 1,
                    col: 3,
                    rect: dummy_rect,
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

    #[test]
    fn test_infer_header_structure_uses_geometry_for_unknown_labels() {
        let rect = |x0, y0, x1, y1| Rect4 {
            schema_version: 1,
            x0,
            y0,
            x1,
            y1,
        };
        let cells = vec![
            CellDto {
                schema_version: 1,
                text: "Stub".to_string(),
                row: 0,
                col: 0,
                rect: rect(0.0, 0.0, 50.0, 20.0),
                rowspan: 1,
                colspan: 1,
                source: None,
            },
            CellDto {
                schema_version: 1,
                text: "Group-X".to_string(),
                row: 0,
                col: 1,
                rect: rect(50.0, 0.0, 150.0, 20.0),
                rowspan: 1,
                colspan: 1,
                source: None,
            },
            CellDto {
                schema_version: 1,
                text: "Left".to_string(),
                row: 1,
                col: 1,
                rect: rect(50.0, 20.0, 100.0, 40.0),
                rowspan: 1,
                colspan: 1,
                source: None,
            },
            CellDto {
                schema_version: 1,
                text: "Right".to_string(),
                row: 1,
                col: 2,
                rect: rect(100.0, 20.0, 150.0, 40.0),
                rowspan: 1,
                colspan: 1,
                source: None,
            },
        ];
        let input = HeaderGridInput {
            schema_version: 1,
            grid: LogicalGridDto {
                schema_version: 1,
                grid: GridDto {
                    schema_version: 1,
                    rows: 2,
                    cols: 3,
                    row_edges: vec![0.0, 20.0, 40.0],
                    col_edges: vec![0.0, 50.0, 100.0, 150.0],
                    occupancy: vec![vec![None; 3]; 2],
                },
                cells,
                empty_slots: Vec::new(),
            },
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = infer_header_structure(input);
        let group = output
            .cells
            .iter()
            .find(|cell| cell.text == "Group-X")
            .expect("geometric group header");
        let stub = output
            .cells
            .iter()
            .find(|cell| cell.text == "Stub")
            .expect("geometric stub header");
        assert_eq!(group.colspan, 2);
        assert_eq!(stub.rowspan, 2);
    }

    #[test]
    fn test_infer_header_structure_rejects_incomplete_geometric_group() {
        let rect = |x0, y0, x1, y1| Rect4 {
            schema_version: 1,
            x0,
            y0,
            x1,
            y1,
        };
        let input = HeaderGridInput {
            schema_version: 1,
            grid: LogicalGridDto {
                schema_version: 1,
                grid: GridDto {
                    schema_version: 1,
                    rows: 2,
                    cols: 3,
                    row_edges: vec![0.0, 20.0, 40.0],
                    col_edges: vec![0.0, 50.0, 100.0, 150.0],
                    occupancy: vec![vec![None; 3]; 2],
                },
                cells: vec![
                    CellDto {
                        schema_version: 1,
                        text: "Unknown group".to_string(),
                        row: 0,
                        col: 1,
                        rect: rect(50.0, 0.0, 150.0, 20.0),
                        rowspan: 1,
                        colspan: 1,
                        source: None,
                    },
                    CellDto {
                        schema_version: 1,
                        text: "Only child".to_string(),
                        row: 1,
                        col: 1,
                        rect: rect(50.0, 20.0, 100.0, 40.0),
                        rowspan: 1,
                        colspan: 1,
                        source: None,
                    },
                ],
                empty_slots: Vec::new(),
            },
            config: StructureConfig {
                schema_version: 1,
                line_tolerance: 2.0,
                row_tolerance: 2.0,
                column_tolerance: 2.0,
                span_tolerance: 2.0,
                numeric_tolerance: 2.0,
            },
        };

        let output = infer_header_structure(input);
        let group = output
            .cells
            .iter()
            .find(|cell| cell.text == "Unknown group")
            .expect("incomplete group header");
        assert_eq!(group.colspan, 1);
    }
}
