use lopdf::{Document, Object};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug)]
pub struct Type3GlyphMap {
    pub characters: HashMap<u32, char>,
    pub font_bbox: [f64; 4],
    pub font_matrix: [f64; 6],
}

pub struct Type3GlyphMapLookup {
    pdf_path: PathBuf,
    document: Option<Document>,
    load_attempted: bool,
    page_mappings: HashMap<usize, Option<Type3GlyphMap>>,
}

impl Type3GlyphMapLookup {
    pub fn new(pdf_path: &Path) -> Self {
        Self {
            pdf_path: pdf_path.to_path_buf(),
            document: None,
            load_attempted: false,
            page_mappings: HashMap::new(),
        }
    }

    pub fn for_page(&mut self, page_index: usize) -> Option<Type3GlyphMap> {
        if !self.page_mappings.contains_key(&page_index) {
            if !self.load_attempted {
                self.document = Document::load(&self.pdf_path).ok();
                self.load_attempted = true;
            }
            let mapping = self
                .document
                .as_ref()
                .and_then(|document| numeric_type3_glyph_map(document, page_index));
            self.page_mappings.insert(page_index, mapping);
        }
        self.page_mappings.get(&page_index).cloned().flatten()
    }
}

fn numeric_type3_glyph_map(document: &Document, page_index: usize) -> Option<Type3GlyphMap> {
    let page_number = u32::try_from(page_index.checked_add(1)?).ok()?;
    let page_id = *document.get_pages().get(&page_number)?;
    let fonts = document.get_page_fonts(page_id).ok()?;
    if fonts.len() != 1 {
        return None;
    }

    let font = fonts.values().next()?;
    if font.has(b"ToUnicode")
        || font.get(b"Subtype").and_then(Object::as_name).ok() != Some(&b"Type3"[..])
    {
        return None;
    }

    let encoding = font
        .get_deref(b"Encoding", document)
        .ok()?
        .as_dict()
        .ok()?;
    let font_bbox = numeric_array::<4>(font.get(b"FontBBox").ok()?)?;
    let font_matrix = numeric_array::<6>(font.get(b"FontMatrix").ok()?)?;
    let differences = encoding
        .get_deref(b"Differences", document)
        .ok()?
        .as_array()
        .ok()?;

    Some(Type3GlyphMap {
        characters: numeric_difference_map(differences)?,
        font_bbox,
        font_matrix,
    })
}

fn numeric_array<const N: usize>(object: &Object) -> Option<[f64; N]> {
    let values = object.as_array().ok()?;
    if values.len() != N {
        return None;
    }
    let mut output = [0.0; N];
    for (index, value) in values.iter().enumerate() {
        output[index] = match value {
            Object::Integer(value) => *value as f64,
            Object::Real(value) => *value as f64,
            _ => return None,
        };
    }
    Some(output)
}

fn numeric_difference_map(differences: &[Object]) -> Option<HashMap<u32, char>> {
    let mut next_code = None;
    let mut mapping = HashMap::new();

    for item in differences {
        match item {
            Object::Integer(code) if (0..=255).contains(code) => next_code = Some(*code as u32),
            Object::Integer(_) => return None,
            Object::Name(name) => {
                let code = next_code?;
                if code > 255 {
                    return None;
                }
                next_code = code.checked_add(1);

                if !name.is_empty() && name.iter().all(u8::is_ascii_digit) {
                    let glyph_value = std::str::from_utf8(name).ok()?.parse::<u32>().ok()?;
                    let character = char::from_u32(glyph_value)?;
                    if mapping.insert(code, character).is_some() {
                        return None;
                    }
                }
            }
            _ => return None,
        }
    }

    (!mapping.is_empty()).then_some(mapping)
}

#[cfg(test)]
mod tests {
    use super::Type3GlyphMapLookup;
    use std::path::Path;

    #[test]
    fn maps_numeric_type3_glyph_names_to_unicode_for_page_705() {
        let pdf_path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/page_705_scanned.pdf");
        let mapping = Type3GlyphMapLookup::new(&pdf_path).for_page(0).unwrap();

        assert_eq!(mapping.characters.get(&32), Some(&'!'));
        assert_eq!(mapping.characters.get(&33), Some(&'"'));
        assert_eq!(mapping.characters.get(&53), Some(&'6'));
        assert_eq!(mapping.font_bbox, [-10.0, -10.0, 10.0, 10.0]);
        assert_eq!(mapping.font_matrix, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]);
    }

    #[test]
    fn does_not_apply_type3_glyph_mapping_to_other_pages() {
        let pdf_path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/page_000_vector.pdf");

        assert!(Type3GlyphMapLookup::new(&pdf_path).for_page(0).is_none());
    }
}
