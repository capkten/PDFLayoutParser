use std::collections::{BTreeMap, BTreeSet};
use serde::{Deserialize, Serialize};
use crate::layout::LayoutElementDto;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct TableCellDto {
    pub text: String,
    pub row_index: usize,
    pub col_index: usize,
    #[serde(default = "default_span_one")]
    pub rowspan: usize,
    #[serde(default = "default_span_one")]
    pub colspan: usize,
    #[serde(default)]
    pub bbox: [f64; 4],
}

pub fn default_span_one() -> usize {
    1
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct FullTableDto {
    pub table_id: usize,
    pub bbox: [f64; 4],
    pub rows: usize,
    pub cols: usize,
    #[serde(default)]
    pub cells: Vec<TableCellDto>,
    #[serde(default)]
    pub confidence: Option<f64>,
    #[serde(default)]
    pub source: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Default)]
pub struct ImageElementMetaDto {
    pub image_id: usize,
    pub path: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Default)]
pub struct SealElementMetaDto {
    pub seal_id: usize,
    pub path: Option<String>,
}

/// Escapes HTML characters: `&` -> `&amp;`, `<` -> `&lt;`, `>` -> `&gt;`.
/// Single and double quotes remain unescaped (matching Python `html.escape(..., quote=False)`).
pub fn escape_html(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            _ => out.push(c),
        }
    }
    out
}

fn is_num_char(c: char) -> bool {
    c.is_ascii_digit() || c == ',' || c == '.' || c == '-'
}

/// Strips whitespace occurring strictly between numeric / formatting characters
/// `['0'..='9', ',', '.', '-']`. Equivalent to Python `re.compile(r"(?<=[\d,\.\-])\s+(?=[\d,\.\-])")`.
pub fn clean_number_text(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    while i < n {
        if chars[i].is_whitespace() {
            let mut j = i;
            while j < n && chars[j].is_whitespace() {
                j += 1;
            }
            let preceded = i > 0 && is_num_char(chars[i - 1]);
            let followed = j < n && is_num_char(chars[j]);
            if !(preceded && followed) {
                for k in i..j {
                    out.push(chars[k]);
                }
            }
            i = j;
        } else {
            out.push(chars[i]);
            i += 1;
        }
    }
    out
}

/// Renders a full table into HTML table lines.
pub fn render_html_table(table: &FullTableDto) -> Vec<String> {
    if table.cells.is_empty() {
        return Vec::new();
    }

    let mut max_row = 0;
    let mut max_col = 0;
    for cell in &table.cells {
        let r_end = cell.row_index + cell.rowspan.max(1) - 1;
        let c_end = cell.col_index + cell.colspan.max(1) - 1;
        if r_end > max_row {
            max_row = r_end;
        }
        if c_end > max_col {
            max_col = c_end;
        }
    }

    let mut cell_map: BTreeMap<(usize, usize), &TableCellDto> = BTreeMap::new();
    for cell in &table.cells {
        cell_map.entry((cell.row_index, cell.col_index)).or_insert(cell);
    }

    let mut occupied_rows: BTreeSet<usize> = BTreeSet::new();
    for cell in &table.cells {
        let r_span = cell.rowspan.max(1);
        for r in cell.row_index..(cell.row_index + r_span) {
            occupied_rows.insert(r);
        }
    }

    let mut covered: BTreeSet<(usize, usize)> = BTreeSet::new();
    let mut lines = vec!["<table>".to_string(), "  <tbody>".to_string()];

    for row_index in 0..=max_row {
        if !occupied_rows.contains(&row_index) {
            continue;
        }
        lines.push("    <tr>".to_string());
        for col_index in 0..=max_col {
            if covered.contains(&(row_index, col_index)) {
                continue;
            }

            match cell_map.get(&(row_index, col_index)) {
                None => {
                    lines.push("      <td></td>".to_string());
                }
                Some(cell) => {
                    let rowspan = cell.rowspan.max(1);
                    let colspan = cell.colspan.max(1);
                    for r in row_index..(row_index + rowspan) {
                        for c in col_index..(col_index + colspan) {
                            if r == row_index && c == col_index {
                                continue;
                            }
                            covered.insert((r, c));
                        }
                    }

                    let mut attrs = Vec::new();
                    if rowspan > 1 {
                        attrs.push(format!("rowspan=\"{}\"", rowspan));
                    }
                    if colspan > 1 {
                        attrs.push(format!("colspan=\"{}\"", colspan));
                    }

                    let clean_txt = clean_number_text(cell.text.replace('\n', " ").trim());
                    let attr_text = if attrs.is_empty() {
                        String::new()
                    } else {
                        format!(" {}", attrs.join(" "))
                    };
                    lines.push(format!("      <td{}>{}</td>", attr_text, escape_html(&clean_txt)));
                }
            }
        }
        lines.push("    </tr>".to_string());
    }

    lines.push("  </tbody>".to_string());
    lines.push("</table>".to_string());
    lines.push(String::new());

    lines
}

/// Renders page layout elements into a single Markdown reading flow string.
pub fn render_page_markdown(
    elements: &[LayoutElementDto],
    tables: &[FullTableDto],
    images: &[ImageElementMetaDto],
    seals: &[SealElementMetaDto],
    page_index: usize,
) -> String {
    let mut lines: Vec<String> = Vec::new();

    for element in elements {
        match element.element_type.as_str() {
            "text" => {
                let content = element.text.as_deref().unwrap_or("");
                lines.push(content.to_string());
                lines.push(String::new());
            }
            "table" => {
                let table = element
                    .table_index
                    .and_then(|idx| tables.iter().find(|t| t.table_id == idx).or_else(|| tables.get(idx)))
                    .or_else(|| if tables.len() == 1 { tables.first() } else { None });
                if let Some(t) = table {
                    lines.extend(render_html_table(t));
                }
            }
            "image" => {
                let img = element
                    .image_index
                    .and_then(|idx| images.iter().find(|im| im.image_id == idx).or_else(|| images.get(idx)))
                    .or_else(|| if images.len() == 1 { images.first() } else { None });
                if let Some(img) = img {
                    if let Some(path) = &img.path {
                        lines.push(format!("![image]({})", path));
                    } else {
                        lines.push("[图片]".to_string());
                    }
                } else {
                    lines.push("[图片]".to_string());
                }
                lines.push(String::new());
            }
            "seal" => {
                let seal = element
                    .image_index
                    .and_then(|idx| seals.iter().find(|s| s.seal_id == idx).or_else(|| seals.get(idx)))
                    .or_else(|| if seals.len() == 1 { seals.first() } else { None });
                if let Some(seal) = seal {
                    if let Some(path) = &seal.path {
                        lines.push(format!("![seal]({})", path));
                    } else {
                        lines.push(format!("[印章: page-{}]", page_index));
                    }
                } else {
                    lines.push(format!("[印章: page-{}]", page_index));
                }
                lines.push(String::new());
            }
            "separator" => {
                lines.push("---".to_string());
                lines.push(String::new());
            }
            _ => {}
        }
    }

    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::layout::LayoutElementDto;

    #[test]
    fn test_markdown_escape_html() {
        let input = "<div>Tom & 'Jerry' \"cartoon\"</div>";
        let escaped = escape_html(input);
        assert_eq!(escaped, "&lt;div&gt;Tom &amp; 'Jerry' \"cartoon\"&lt;/div&gt;");
    }

    #[test]
    fn test_markdown_clean_number_text() {
        assert_eq!(clean_number_text("123 456"), "123456");
        assert_eq!(clean_number_text("- 10. 5"), "-10.5");
        assert_eq!(clean_number_text("normal text"), "normal text");
        assert_eq!(clean_number_text("12. 34"), "12.34");
        assert_eq!(clean_number_text(" 123   456 "), " 123456 ");
        assert_eq!(clean_number_text("123 -bar"), "123-bar");
    }

    #[test]
    fn test_markdown_render_sparse_table() {
        let table = FullTableDto {
            table_id: 0,
            bbox: [0.0, 0.0, 100.0, 50.0],
            rows: 2,
            cols: 3,
            cells: vec![
                TableCellDto {
                    text: "A".to_string(),
                    row_index: 0,
                    col_index: 0,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [0.0, 0.0, 10.0, 10.0],
                },
                TableCellDto {
                    text: "B".to_string(),
                    row_index: 0,
                    col_index: 2,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [20.0, 0.0, 30.0, 10.0],
                },
                TableCellDto {
                    text: "C".to_string(),
                    row_index: 1,
                    col_index: 0,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [0.0, 10.0, 10.0, 20.0],
                },
                TableCellDto {
                    text: "D".to_string(),
                    row_index: 1,
                    col_index: 2,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [20.0, 10.0, 30.0, 20.0],
                },
            ],
            confidence: Some(1.0),
            source: Some("test".to_string()),
        };

        let lines = render_html_table(&table);
        let content = lines.join("\n");
        assert!(content.starts_with("<table>"));
        assert_eq!(content.matches("<tr>").count(), 2);
        assert_eq!(content.matches("<td>A</td>").count(), 1);
        assert_eq!(content.matches("<td></td>").count(), 2);
        assert!(content.contains("<td>B</td>"));
        assert!(content.contains("<td>C</td>"));
        assert!(content.contains("<td>D</td>"));
    }

    #[test]
    fn test_markdown_render_table_spans() {
        let table = FullTableDto {
            table_id: 0,
            bbox: [0.0, 0.0, 200.0, 100.0],
            rows: 2,
            cols: 3,
            cells: vec![
                TableCellDto {
                    text: "Item & Details".to_string(),
                    row_index: 0,
                    col_index: 0,
                    rowspan: 2,
                    colspan: 1,
                    bbox: [0.0, 0.0, 20.0, 40.0],
                },
                TableCellDto {
                    text: "<Amount>".to_string(),
                    row_index: 0,
                    col_index: 1,
                    rowspan: 1,
                    colspan: 2,
                    bbox: [20.0, 0.0, 180.0, 20.0],
                },
                TableCellDto {
                    text: "100 000".to_string(),
                    row_index: 1,
                    col_index: 1,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [20.0, 20.0, 100.0, 40.0],
                },
                TableCellDto {
                    text: "200 000".to_string(),
                    row_index: 1,
                    col_index: 2,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [100.0, 20.0, 180.0, 40.0],
                },
            ],
            confidence: None,
            source: None,
        };

        let lines = render_html_table(&table);
        let content = lines.join("\n");
        assert!(content.contains("<td rowspan=\"2\">Item &amp; Details</td>"));
        assert!(content.contains("<td colspan=\"2\">&lt;Amount&gt;</td>"));
        assert!(content.contains("<td>100000</td>"));
        assert!(content.contains("<td>200000</td>"));
    }

    #[test]
    fn test_markdown_render_page_markdown() {
        let elements = vec![
            LayoutElementDto {
                element_type: "text".to_string(),
                bbox: [0.0, 0.0, 100.0, 20.0],
                order: 0,
                text: Some("Page Title".to_string()),
                table_index: None,
                image_index: None,
                lines: vec![],
            },
            LayoutElementDto {
                element_type: "table".to_string(),
                bbox: [0.0, 25.0, 100.0, 75.0],
                order: 1,
                text: None,
                table_index: Some(0),
                image_index: None,
                lines: vec![],
            },
            LayoutElementDto {
                element_type: "image".to_string(),
                bbox: [0.0, 80.0, 50.0, 120.0],
                order: 2,
                text: None,
                table_index: None,
                image_index: Some(0),
                lines: vec![],
            },
            LayoutElementDto {
                element_type: "seal".to_string(),
                bbox: [50.0, 80.0, 100.0, 120.0],
                order: 3,
                text: None,
                table_index: None,
                image_index: Some(0),
                lines: vec![],
            },
            LayoutElementDto {
                element_type: "separator".to_string(),
                bbox: [0.0, 125.0, 100.0, 130.0],
                order: 4,
                text: None,
                table_index: None,
                image_index: None,
                lines: vec![],
            },
        ];

        let tables = vec![FullTableDto {
            table_id: 0,
            bbox: [0.0, 25.0, 100.0, 75.0],
            rows: 1,
            cols: 2,
            cells: vec![
                TableCellDto {
                    text: "Col 1".to_string(),
                    row_index: 0,
                    col_index: 0,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [0.0, 25.0, 50.0, 75.0],
                },
                TableCellDto {
                    text: "Col 2".to_string(),
                    row_index: 0,
                    col_index: 1,
                    rowspan: 1,
                    colspan: 1,
                    bbox: [50.0, 25.0, 100.0, 75.0],
                },
            ],
            confidence: None,
            source: None,
        }];

        let images = vec![ImageElementMetaDto {
            image_id: 0,
            path: Some("images/fig1.png".to_string()),
        }];

        let seals = vec![SealElementMetaDto {
            seal_id: 0,
            path: Some("seals/stamp1.png".to_string()),
        }];

        let md = render_page_markdown(&elements, &tables, &images, &seals, 0);

        assert!(md.contains("Page Title"));
        assert!(md.contains("<table>"));
        assert!(md.contains("<td>Col 1</td>"));
        assert!(md.contains("<td>Col 2</td>"));
        assert!(md.contains("![image](images/fig1.png)"));
        assert!(md.contains("![seal](seals/stamp1.png)"));
        assert!(md.contains("---"));
    }

    #[test]
    fn test_markdown_render_page_markdown_fallbacks() {
        let elements = vec![
            LayoutElementDto {
                element_type: "image".to_string(),
                bbox: [0.0, 0.0, 50.0, 50.0],
                order: 0,
                text: None,
                table_index: None,
                image_index: None,
                lines: vec![],
            },
            LayoutElementDto {
                element_type: "seal".to_string(),
                bbox: [50.0, 0.0, 100.0, 50.0],
                order: 1,
                text: None,
                table_index: None,
                image_index: None,
                lines: vec![],
            },
        ];

        let md = render_page_markdown(&elements, &[], &[], &[], 3);
        assert!(md.contains("[图片]"));
        assert!(md.contains("[印章: page-3]"));
    }
}
