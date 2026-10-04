use crate::{ProvenanceSidecar, SpanInfo};
use serde::{Deserialize, Serialize};

// --- Named Clustering Constants ---
pub const LINE_OVERLAP_RATIO_TOLERANCE: f64 = 0.5;
pub const LINE_Y_CENTER_FACTOR: f64 = 0.4;
pub const SPAN_MERGE_MAX_GAP_FACTOR: f64 = 0.4;
pub const BLOCK_LINE_GAP_FACTOR: f64 = 1.5;
pub const BLOCK_HORIZONTAL_GAP_FACTOR: f64 = 2.0;
pub const WORD_CHAR_GAP_FACTOR: f64 = 0.5;
pub const LINE_MAX_HORIZONTAL_GAP: f64 = 25.0;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct Rect4Dto {
    pub schema_version: i64,
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

pub fn make_rect4(x0: f64, y0: f64, x1: f64, y1: f64) -> Rect4Dto {
    Rect4Dto {
        schema_version: 1,
        x0,
        y0,
        x1,
        y1,
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WordTupleDto(
    pub f64,
    pub f64,
    pub f64,
    pub f64,
    pub String,
    pub usize,
    pub usize,
    pub usize,
);

impl WordTupleDto {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        x0: f64,
        y0: f64,
        x1: f64,
        y1: f64,
        text: String,
        block_idx: usize,
        line_idx: usize,
        word_idx: usize,
    ) -> Self {
        Self(x0, y0, x1, y1, text, block_idx, line_idx, word_idx)
    }

    pub fn x0(&self) -> f64 {
        self.0
    }
    pub fn y0(&self) -> f64 {
        self.1
    }
    pub fn x1(&self) -> f64 {
        self.2
    }
    pub fn y1(&self) -> f64 {
        self.3
    }
    pub fn text(&self) -> &str {
        &self.4
    }
    pub fn block_idx(&self) -> usize {
        self.5
    }
    pub fn line_idx(&self) -> usize {
        self.6
    }
    pub fn word_idx(&self) -> usize {
        self.7
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct WireWordDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4Dto,
    pub order: usize,
    pub block: usize,
    pub line: usize,
    pub raw_source_position: Vec<i64>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct VisualChar {
    pub c: String,
    pub bbox: [f64; 4],
    pub char_index: usize,
    pub pdfium_object_index: usize,
    pub page_index: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct VisualSpan {
    pub text: String,
    pub bbox: [f64; 4],
    pub font: Option<String>,
    pub size: f64,
    pub flags: Option<i64>,
    pub render_mode: i32,
    pub is_invisible: bool,
    pub provenance: ProvenanceSidecar,
    pub characters: Vec<VisualChar>,
    pub page_index: usize,
}

impl VisualSpan {
    pub fn x0(&self) -> f64 {
        self.bbox[0]
    }
    pub fn y0(&self) -> f64 {
        self.bbox[1]
    }
    pub fn x1(&self) -> f64 {
        self.bbox[2]
    }
    pub fn y1(&self) -> f64 {
        self.bbox[3]
    }
    pub fn height(&self) -> f64 {
        (self.y1() - self.y0()).max(0.1)
    }
    pub fn cy(&self) -> f64 {
        (self.y0() + self.y1()) / 2.0
    }

    pub fn can_merge_with(&self, other: &VisualSpan) -> bool {
        if self.font != other.font {
            return false;
        }
        if (self.size - other.size).abs() > 0.5 {
            return false;
        }
        if self.flags != other.flags {
            return false;
        }
        if self.render_mode != other.render_mode {
            return false;
        }
        let char_h = self.height().min(other.height());
        let gap = other.x0() - self.x1();
        if gap < -0.2 * char_h {
            return false;
        }
        gap <= SPAN_MERGE_MAX_GAP_FACTOR * char_h
    }

    pub fn merge(&mut self, other: VisualSpan) {
        self.text.push_str(&other.text);
        self.bbox[0] = self.bbox[0].min(other.bbox[0]);
        self.bbox[1] = self.bbox[1].min(other.bbox[1]);
        self.bbox[2] = self.bbox[2].max(other.bbox[2]);
        self.bbox[3] = self.bbox[3].max(other.bbox[3]);
        self.characters.extend(other.characters);
        self.provenance.char_end_index = other.provenance.char_end_index;
        self.provenance.character_count = self.characters.len();
        self.provenance.char_indices.extend(other.provenance.char_indices);
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct VisualLine {
    pub spans: Vec<VisualSpan>,
    pub y0: f64,
    pub y1: f64,
    pub cy: f64,
    pub height: f64,
}

impl VisualLine {
    pub fn new(initial_span: VisualSpan) -> Self {
        let y0 = initial_span.y0();
        let y1 = initial_span.y1();
        let cy = initial_span.cy();
        let height = initial_span.height();
        Self {
            spans: vec![initial_span],
            y0,
            y1,
            cy,
            height,
        }
    }

    pub fn matches_span(&self, span: &VisualSpan) -> bool {
        // Spans on the same line cannot overlap significantly horizontally
        for existing in &self.spans {
            let h_overlap = (existing.x1().min(span.x1()) - existing.x0().max(span.x0())).max(0.0);
            let min_w = ((existing.x1() - existing.x0()).max(0.1)).min((span.x1() - span.x0()).max(0.1));
            if h_overlap > 0.3 * min_w {
                return false;
            }
        }

        // Horizontal gap between span and line must not exceed maximum gap
        // (prohibits merging across columns or between distant header/footer elements)
        let min_h_dist = self
            .spans
            .iter()
            .map(|existing| {
                if span.x0() > existing.x1() {
                    span.x0() - existing.x1()
                } else if existing.x0() > span.x1() {
                    existing.x0() - span.x1()
                } else {
                    0.0
                }
            })
            .fold(f64::INFINITY, f64::min);
        if min_h_dist > LINE_MAX_HORIZONTAL_GAP {
            return false;
        }

        let v_overlap = (self.y1.min(span.y1()) - self.y0.max(span.y0())).max(0.0);
        let min_h = self.height.min(span.height());
        let overlap_ratio = v_overlap / min_h;
        let center_dist = (self.cy - span.cy()).abs();

        if overlap_ratio >= LINE_OVERLAP_RATIO_TOLERANCE {
            return true;
        }
        if center_dist <= LINE_Y_CENTER_FACTOR * min_h {
            return true;
        }
        false
    }

    pub fn add_span(&mut self, span: VisualSpan) {
        self.y0 = self.y0.min(span.y0());
        self.y1 = self.y1.max(span.y1());
        self.cy = (self.y0 + self.y1) / 2.0;
        self.height = (self.y1 - self.y0).max(0.1);
        self.spans.push(span);
    }

    pub fn x0(&self) -> f64 {
        self.spans
            .iter()
            .map(|s| s.x0())
            .fold(f64::INFINITY, f64::min)
    }

    pub fn x1(&self) -> f64 {
        self.spans
            .iter()
            .map(|s| s.x1())
            .fold(f64::NEG_INFINITY, f64::max)
    }

    pub fn bbox(&self) -> [f64; 4] {
        [self.x0(), self.y0, self.x1(), self.y1]
    }

    pub fn normalize_spans(&mut self) {
        self.spans.sort_by(|a, b| {
            a.x0()
                .partial_cmp(&b.x0())
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut merged: Vec<VisualSpan> = Vec::new();
        for span in self.spans.drain(..) {
            if let Some(last) = merged.last_mut() {
                if last.can_merge_with(&span) {
                    last.merge(span);
                    continue;
                }
            }
            merged.push(span);
        }
        self.spans = merged;
    }
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct VisualBlock {
    pub lines: Vec<VisualLine>,
    pub bbox: [f64; 4],
}

impl VisualBlock {
    pub fn new(initial_line: VisualLine) -> Self {
        let bbox = initial_line.bbox();
        Self {
            lines: vec![initial_line],
            bbox,
        }
    }

    pub fn x0(&self) -> f64 {
        self.bbox[0]
    }
    pub fn y0(&self) -> f64 {
        self.bbox[1]
    }
    pub fn x1(&self) -> f64 {
        self.bbox[2]
    }
    pub fn y1(&self) -> f64 {
        self.bbox[3]
    }

    pub fn matches_line(&self, line: &VisualLine) -> bool {
        let last_line = match self.lines.last() {
            Some(l) => l,
            None => return false,
        };
        let line_gap = line.y0 - last_line.y1;
        let ref_h = last_line.height.min(line.height);

        // Allow vertical gap within tolerance
        if line_gap > BLOCK_LINE_GAP_FACTOR * ref_h {
            return false;
        }
        if line_gap < -0.5 * ref_h {
            return false;
        }

        // Horizontal projection: must overlap or be close, not across column gutter
        let h_overlap = self.x1().min(line.x1()) - self.x0().max(line.x0());
        if h_overlap < 0.0 {
            let h_gutter = self.x0().max(line.x0()) - self.x1().min(line.x1());
            if h_gutter > BLOCK_HORIZONTAL_GAP_FACTOR * ref_h {
                return false;
            }
        }
        true
    }

    pub fn add_line(&mut self, line: VisualLine) {
        self.bbox[0] = self.bbox[0].min(line.x0());
        self.bbox[1] = self.bbox[1].min(line.y0);
        self.bbox[2] = self.bbox[2].max(line.x1());
        self.bbox[3] = self.bbox[3].max(line.y1);
        self.lines.push(line);
    }
}

pub fn is_cjk(ch: char) -> bool {
    let code = ch as u32;
    (0x4E00..=0x9FFF).contains(&code)
        || (0x3400..=0x4DBF).contains(&code)
        || (0x20000..=0x2A6DF).contains(&code)
        || (0xF900..=0xFAFF).contains(&code)
        || (0x3040..=0x309F).contains(&code)
        || (0x30A0..=0x30FF).contains(&code)
        || (0xAC00..=0xD7AF).contains(&code)
}

pub fn is_cjk_str(s: &str) -> bool {
    !s.is_empty() && s.chars().all(is_cjk)
}

pub fn is_punctuation(ch: char) -> bool {
    if ch.is_whitespace() || ch.is_alphanumeric() {
        return false;
    }
    if is_cjk(ch) {
        return false;
    }
    true
}


pub fn cluster_spans_into_blocks(
    spans: &[SpanInfo],
    page_index: usize,
) -> Vec<VisualBlock> {
    // 1. SpanInfo -> VisualSpan
    let mut visual_spans: Vec<VisualSpan> = spans
        .iter()
        .map(|s| {
            let p_obj_idx = s.provenance.pdfium_object_index;
            let characters = s
                .characters
                .iter()
                .map(|ch| VisualChar {
                    c: ch.c.clone(),
                    bbox: ch.bbox,
                    char_index: ch.char_index,
                    pdfium_object_index: p_obj_idx,
                    page_index,
                })
                .collect();
            VisualSpan {
                text: s.text.clone(),
                bbox: s.bbox,
                font: s.font.clone(),
                size: s.size.unwrap_or(10.0),
                flags: s.flags,
                render_mode: s.render_mode,
                is_invisible: s.is_invisible,
                provenance: s.provenance.clone(),
                characters,
                page_index,
            }
        })
        .collect();

    // 2. Sort by (cy, x0)
    visual_spans.sort_by(|a, b| {
        a.cy()
            .partial_cmp(&b.cy())
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.x0().partial_cmp(&b.x0()).unwrap_or(std::cmp::Ordering::Equal))
    });

    // 3. Cluster lines
    let mut lines: Vec<VisualLine> = Vec::new();
    for s in visual_spans {
        let mut matched_idx = None;
        for (idx, l) in lines.iter().enumerate() {
            if l.matches_span(&s) {
                matched_idx = Some(idx);
                break;
            }
        }
        if let Some(idx) = matched_idx {
            lines[idx].add_span(s);
        } else {
            lines.push(VisualLine::new(s));
        }
    }

    // 4. Sort lines by (y0, x0) and normalize spans
    lines.sort_by(|a, b| {
        a.y0
            .partial_cmp(&b.y0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.x0().partial_cmp(&b.x0()).unwrap_or(std::cmp::Ordering::Equal))
    });
    for l in &mut lines {
        l.normalize_spans();
    }

    // 5. Cluster blocks
    let mut blocks: Vec<VisualBlock> = Vec::new();
    for l in lines {
        if blocks.is_empty() {
            blocks.push(VisualBlock::new(l));
        } else {
            let last_idx = blocks.len() - 1;
            if blocks[last_idx].matches_line(&l) {
                blocks[last_idx].add_line(l);
            } else {
                blocks.push(VisualBlock::new(l));
            }
        }
    }

    blocks
}

pub fn derive_words(
    blocks: &[VisualBlock],
    _page_index: usize,
) -> (Vec<WordTupleDto>, Vec<WireWordDto>) {
    let mut word_tuples = Vec::new();
    let mut wire_words = Vec::new();
    let mut global_word_order = 0;

    for (block_idx, block) in blocks.iter().enumerate() {
        for (line_idx, line) in block.lines.iter().enumerate() {
            let mut line_chars: Vec<&VisualChar> = Vec::new();
            for span in &line.spans {
                for ch in &span.characters {
                    line_chars.push(ch);
                }
            }

            if line_chars.is_empty() {
                continue;
            }

            line_chars.sort_by(|a, b| {
                a.bbox[0]
                    .partial_cmp(&b.bbox[0])
                    .unwrap_or(std::cmp::Ordering::Equal)
            });

            let mut current_buf: Vec<&VisualChar> = Vec::new();
            let mut line_word_idx = 0;

            let mut flush_buf = |buf: &mut Vec<&VisualChar>| {
                if buf.is_empty() {
                    return;
                }
                let mut w_text = String::new();
                for c in buf.iter() {
                    w_text.push_str(&c.c);
                }
                let mut w_x0 = f64::INFINITY;
                let mut w_y0 = f64::INFINITY;
                let mut w_x1 = f64::NEG_INFINITY;
                let mut w_y1 = f64::NEG_INFINITY;
                for c in buf.iter() {
                    w_x0 = w_x0.min(c.bbox[0]);
                    w_y0 = w_y0.min(c.bbox[1]);
                    w_x1 = w_x1.max(c.bbox[2]);
                    w_y1 = w_y1.max(c.bbox[3]);
                }
                let first_c = buf.first().unwrap();
                let last_c = buf.last().unwrap();
                let raw_pos = vec![
                    first_c.page_index as i64,
                    first_c.pdfium_object_index as i64,
                    first_c.char_index as i64,
                    last_c.char_index as i64,
                ];

                word_tuples.push(WordTupleDto(
                    w_x0,
                    w_y0,
                    w_x1,
                    w_y1,
                    w_text.clone(),
                    block_idx,
                    line_idx,
                    line_word_idx,
                ));

                wire_words.push(WireWordDto {
                    schema_version: 1,
                    text: w_text,
                    rect: make_rect4(w_x0, w_y0, w_x1, w_y1),
                    order: global_word_order,
                    block: block_idx,
                    line: line_idx,
                    raw_source_position: raw_pos,
                });

                global_word_order += 1;
                line_word_idx += 1;
                buf.clear();
            };

            let mut i = 0;
            while i < line_chars.len() {
                let ch_item = line_chars[i];
                let c_str = ch_item.c.as_str();

                if !c_str.is_empty() && c_str.chars().all(|c| c.is_whitespace()) {
                    flush_buf(&mut current_buf);
                    i += 1;
                    continue;
                }

                if let Some(prev_c) = current_buf.last() {
                    let char_h = (prev_c.bbox[3] - prev_c.bbox[1])
                        .min(ch_item.bbox[3] - ch_item.bbox[1]);
                    let char_gap = ch_item.bbox[0] - prev_c.bbox[2];
                    if char_gap > 0.22 * char_h || char_gap >= 2.5 {
                        flush_buf(&mut current_buf);
                    }
                }

                current_buf.push(ch_item);
                i += 1;
            }

            flush_buf(&mut current_buf);
        }
    }

    (word_tuples, wire_words)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CharInfo;

    fn make_test_span(
        text: &str,
        bbox: [f64; 4],
        font: Option<&str>,
        size: f64,
        obj_idx: usize,
    ) -> SpanInfo {
        let char_count = text.chars().count();
        let w = (bbox[2] - bbox[0]) / (char_count.max(1) as f64);
        let characters = text
            .chars()
            .enumerate()
            .map(|(idx, ch)| CharInfo {
                c: ch.to_string(),
                bbox: [bbox[0] + idx as f64 * w, bbox[1], bbox[0] + (idx + 1) as f64 * w, bbox[3]],
                char_index: idx,
            })
            .collect();
        SpanInfo {
            order: obj_idx as i64,
            text: text.to_string(),
            bbox,
            font: font.map(|s| s.to_string()),
            size: Some(size),
            flags: None,
            render_mode: 0,
            is_invisible: false,
            provenance: ProvenanceSidecar {
                page_index: 0,
                pdfium_object_index: obj_idx,
                character_count: char_count,
                char_start_index: 0,
                char_end_index: char_count,
                char_indices: (0..char_count).collect(),
                is_derived: false,
                derived_block: None,
                derived_line: None,
            },
            characters,
        }
    }

    #[test]
    fn test_clustering_single_span() {
        let span = make_test_span("SingleText", [10.0, 20.0, 80.0, 32.0], Some("Arial"), 12.0, 5);
        let blocks = cluster_spans_into_blocks(&[span], 0);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].lines.len(), 1);
        assert_eq!(blocks[0].lines[0].spans.len(), 1);
        let vspan = &blocks[0].lines[0].spans[0];
        assert_eq!(vspan.text, "SingleText");
        assert_eq!(vspan.characters.len(), 10);
        assert_eq!(vspan.characters[0].pdfium_object_index, 5);
    }

    #[test]
    fn test_clustering_span_merge_with_provenance() {
        let span1 = make_test_span("Hello", [10.0, 20.0, 50.0, 30.0], Some("Arial"), 10.0, 1);
        let span2 = make_test_span("World", [52.0, 20.0, 90.0, 30.0], Some("Arial"), 10.0, 2);
        let blocks = cluster_spans_into_blocks(&[span1, span2], 0);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].lines.len(), 1);
        assert_eq!(blocks[0].lines[0].spans.len(), 1);
        let merged = &blocks[0].lines[0].spans[0];
        assert_eq!(merged.text, "HelloWorld");
        assert_eq!(merged.bbox, [10.0, 20.0, 90.0, 30.0]);
        assert_eq!(merged.characters.len(), 10);
        assert_eq!(merged.characters[0].pdfium_object_index, 1);
        assert_eq!(merged.characters[5].pdfium_object_index, 2);
    }

    #[test]
    fn test_clustering_span_incompatible_no_merge() {
        // Different font
        let span1 = make_test_span("Hello", [10.0, 20.0, 50.0, 30.0], Some("Arial"), 10.0, 1);
        let span2 = make_test_span("World", [52.0, 20.0, 90.0, 30.0], Some("Times"), 10.0, 2);
        let blocks = cluster_spans_into_blocks(&[span1, span2], 0);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].lines.len(), 1);
        assert_eq!(blocks[0].lines[0].spans.len(), 2);
    }

    #[test]
    fn test_clustering_span_large_horizontal_gap_not_merged() {
        // Two spans on the same horizontal baseline but with horizontal gap > 25.0pt
        let span1 = make_test_span("Version 1.8", [50.0, 20.0, 110.0, 30.0], Some("Arial"), 10.0, 1);
        let span2 = make_test_span("Page 3", [500.0, 20.0, 540.0, 30.0], Some("Arial"), 10.0, 2);
        let blocks = cluster_spans_into_blocks(&[span1, span2], 0);
        // Should be separate lines and separate blocks
        assert_eq!(blocks.len(), 2);
        assert_eq!(blocks[0].lines.len(), 1);
        assert_eq!(blocks[1].lines.len(), 1);
        assert_eq!(blocks[0].lines[0].spans[0].text, "Version 1.8");
        assert_eq!(blocks[1].lines[0].spans[0].text, "Page 3");
    }

    #[test]
    fn test_clustering_different_baselines() {
        let span1 = make_test_span("Line1", [10.0, 10.0, 50.0, 20.0], Some("Arial"), 10.0, 1);
        let span2 = make_test_span("Line2", [10.0, 30.0, 50.0, 40.0], Some("Arial"), 10.0, 2);
        let blocks = cluster_spans_into_blocks(&[span1, span2], 0);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].lines.len(), 2);
    }

    #[test]
    fn test_clustering_derive_words_english() {
        let span = make_test_span("Hello world! It don't stop.", [10.0, 10.0, 250.0, 20.0], Some("Arial"), 10.0, 1);
        let blocks = cluster_spans_into_blocks(&[span], 0);
        let (tuples, wire) = derive_words(&blocks, 0);
        let words: Vec<&str> = tuples.iter().map(|t| t.text()).collect();
        assert_eq!(words, vec!["Hello", "world!", "It", "don't", "stop."]);
        assert_eq!(wire.len(), 5);
        assert_eq!(wire[0].text, "Hello");
        assert_eq!(wire[1].text, "world!");
        assert_eq!(wire[2].text, "It");
        assert_eq!(wire[3].text, "don't");
        assert_eq!(wire[4].text, "stop.");
    }

    #[test]
    fn test_clustering_derive_words_numeric() {
        let texts = ["-12.34", "1,000", "1,000.50", "-50%"];
        let mut spans = Vec::new();
        let mut x = 10.0;
        for (i, t) in texts.iter().enumerate() {
            spans.push(make_test_span(t, [x, 10.0, x + 50.0, 20.0], Some("Arial"), 10.0, i));
            x += 65.0; // large gap forces word break
        }
        let blocks = cluster_spans_into_blocks(&spans, 0);
        let (tuples, wire) = derive_words(&blocks, 0);
        let words: Vec<&str> = tuples.iter().map(|t| t.text()).collect();
        assert_eq!(words, vec!["-12.34", "1,000", "1,000.50", "-50%"]);
        assert_eq!(wire.len(), 4);
    }

    #[test]
    fn test_clustering_derive_words_cjk() {
        let span = make_test_span("中文测试", [10.0, 10.0, 90.0, 20.0], Some("SimSun"), 10.0, 1);
        let blocks = cluster_spans_into_blocks(&[span], 0);
        let (tuples, wire) = derive_words(&blocks, 0);
        assert_eq!(tuples.len(), 1);
        assert_eq!(tuples[0].text(), "中文测试");
        assert_eq!(wire.len(), 1);
        assert_eq!(wire[0].text, "中文测试");
    }

    #[test]
    fn test_clustering_derive_words_preserves_punctuation_and_symbols() {
        // English punctuation, hyphen, dash, parens
        let span1 = make_test_span(
            "e-Submission System – FAQs",
            [10.0, 10.0, 250.0, 20.0],
            Some("Arial"),
            10.0,
            1,
        );
        let blocks1 = cluster_spans_into_blocks(&[span1], 0);
        let (tuples1, _) = derive_words(&blocks1, 0);
        let words1: Vec<&str> = tuples1.iter().map(|t| t.text()).collect();
        assert_eq!(words1, vec!["e-Submission", "System", "–", "FAQs"]);

        let span2 = make_test_span(
            "Access to e-Submission System (ESS)",
            [10.0, 30.0, 300.0, 40.0],
            Some("Arial"),
            10.0,
            2,
        );
        let blocks2 = cluster_spans_into_blocks(&[span2], 0);
        let (tuples2, _) = derive_words(&blocks2, 0);
        let words2: Vec<&str> = tuples2.iter().map(|t| t.text()).collect();
        assert_eq!(words2, vec!["Access", "to", "e-Submission", "System", "(ESS)"]);

        // Chinese punctuation: parentheses, dunhao, book quotes, dash, comma
        let span3 = make_test_span(
            "（4）现金和现金等价物",
            [10.0, 50.0, 200.0, 60.0],
            Some("SimSun"),
            10.0,
            3,
        );
        let blocks3 = cluster_spans_into_blocks(&[span3], 0);
        let (tuples3, _) = derive_words(&blocks3, 0);
        let words3: Vec<&str> = tuples3.iter().map(|t| t.text()).collect();
        assert_eq!(words3, vec!["（4）现金和现金等价物"]);

        let span4 = make_test_span(
            "五、关联方关系及其交易",
            [10.0, 70.0, 200.0, 80.0],
            Some("SimSun"),
            10.0,
            4,
        );
        let blocks4 = cluster_spans_into_blocks(&[span4], 0);
        let (tuples4, _) = derive_words(&blocks4, 0);
        let words4: Vec<&str> = tuples4.iter().map(|t| t.text()).collect();
        assert_eq!(words4, vec!["五、关联方关系及其交易"]);
    }


    #[test]
    fn test_clustering_word_tuple_and_wire_dto_contract() {
        let span = make_test_span("Test", [10.0, 10.0, 50.0, 20.0], Some("Arial"), 10.0, 3);
        let blocks = cluster_spans_into_blocks(&[span], 0);
        let (tuples, wire) = derive_words(&blocks, 0);
        assert_eq!(tuples.len(), 1);
        assert_eq!(wire.len(), 1);
        let w = &wire[0];
        assert_eq!(w.schema_version, 1);
        assert_eq!(w.order, 0);
        assert_eq!(w.block, 0);
        assert_eq!(w.line, 0);
        assert_eq!(w.raw_source_position, vec![0, 3, 0, 3]);
        assert_eq!(w.rect.schema_version, 1);
        assert_eq!(w.rect.x0, 10.0);
        assert_eq!(w.rect.y0, 10.0);

        // Test serde serialization
        let json = serde_json::to_string(&w).unwrap();
        assert!(json.contains("\"schema_version\":1"));
        assert!(json.contains("\"text\":\"Test\""));
        assert!(json.contains("\"raw_source_position\":[0,3,0,3]"));

        let tuple_json = serde_json::to_string(&tuples[0]).unwrap();
        // Tuple struct serializes to array: [10.0, 10.0, 50.0, 20.0, "Test", 0, 0, 0]
        assert!(tuple_json.starts_with('['));
        assert!(tuple_json.contains("\"Test\""));
    }

    fn find_pdf_fixture(manifest_dir: &std::path::Path) -> Option<std::path::PathBuf> {
        let mut cur = Some(manifest_dir);
        while let Some(dir) = cur {
            let p = dir.join("fix/zh_all_table_pages.pdf");
            if p.is_file() {
                return Some(p);
            }
            cur = dir.parent();
        }
        let fallback = std::path::PathBuf::from(r"D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf");
        if fallback.is_file() {
            return Some(fallback);
        }
        None
    }

    #[test]
    fn test_preserve_trailing_span_space_and_footer_separation() {
        let manifest_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let pdf_path = find_pdf_fixture(&manifest_dir).expect("fix/zh_all_table_pages.pdf must exist");
        let (lib_path, _) = crate::get_platform_native_lib(&manifest_dir).unwrap();
        let bindings = pdfium_render::prelude::Pdfium::bind_to_library(lib_path).unwrap();
        let pdfium = pdfium_render::prelude::Pdfium::new(bindings);
        let doc = pdfium.load_pdf_from_file(&pdf_path, None).unwrap();
        let page = doc.pages().get(0).unwrap();
        let raw_page = crate::extract_page(&page, 0).unwrap();
        let norm_page = crate::normalizer::normalize_raw_page_with_meta(
            &raw_page,
            Some("zh_all_table_pages.pdf"),
            Some("test_p0"),
        );

        // 2. Check footer left 'Version 1.8' and right 'Page 3' are in separate words/blocks
        let snapshot = norm_page
            .page_snapshot
            .as_ref()
            .expect("page_snapshot should exist");
        for (b_i, block) in snapshot.text_blocks.iter().enumerate() {
            let block_text = block
                .lines
                .iter()
                .flat_map(|l| l.spans.iter().map(|s| s.text.as_str()))
                .collect::<Vec<_>>()
                .join(" ");
            assert!(
                !(block_text.contains("Version 1.8") && block_text.contains("Page")),
                "Footer 'Version 1.8' and 'Page' should be in separate blocks, but found block {}: '{}'",
                b_i,
                block_text
            );
            for line in &block.lines {
                let line_text: String = line
                    .spans
                    .iter()
                    .map(|s| s.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ");
                assert!(
                    !(line_text.contains("Version 1.8") && line_text.contains("Page")),
                    "Footer 'Version 1.8' and 'Page' should not be merged in the same line: {}",
                    line_text
                );
            }
        }

        for w in &norm_page.words {
            let t = w.text();
            assert!(
                !(t.contains("Version 1.8") && t.contains("Page 3")),
                "Footer 'Version 1.8' and 'Page 3' should not be merged in the same word: {}",
                t
            );
        }

        // 1. Check no word contains "ESS(https://"
        let ess_merged = norm_page
            .words
            .iter()
            .any(|w| w.text().contains("ESS(https://"));
        assert!(
            !ess_merged,
            "Found word containing 'ESS(https://', expected trailing space to separate them into distinct words"
        );
    }
}

