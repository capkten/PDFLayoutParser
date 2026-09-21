use crate::types::{
    AtomDto, CharacterDto, NativeRecoveryInput, NativeRecoveryOutput, NativeSpanDto,
    OutputOrderMode, Rect4, TableCandidateDto, TextRunDto, TextRunEvidenceDto,
};

const SPACED_CJK_WORD_WHITELIST: &[(&str, &str)] = &[
    ("合", "计"),
    ("小", "计"),
    ("总", "计"),
    ("共", "计"),
    ("类", "别"),
    ("税", "种"),
    ("项", "目"),
    ("名", "称"),
    ("金", "额"),
    ("单", "位"),
    ("备", "注"),
    ("比", "例"),
    ("期", "初"),
    ("期", "末"),
    ("年", "初"),
    ("年", "末"),
    ("本", "年"),
    ("上", "年"),
    ("折", "旧"),
    ("残", "值"),
];

fn is_cjk_char(c: char) -> bool {
    ('\u{3400}'..='\u{9fff}').contains(&c)
}

fn is_single_cjk(s: &str) -> bool {
    let trimmed = s.trim();
    trimmed.chars().count() == 1 && is_cjk_char(trimmed.chars().next().unwrap())
}

fn is_whitelisted_cjk_pair(prev: &str, cand: &str) -> bool {
    let p = prev.trim();
    let c = cand.trim();
    SPACED_CJK_WORD_WHITELIST
        .iter()
        .any(|&(w1, w2)| w1 == p && w2 == c)
}

fn center_y(r: &Rect4) -> f64 {
    (r.y0 + r.y1) / 2.0
}

fn center_x(r: &Rect4) -> f64 {
    (r.x0 + r.x1) / 2.0
}

fn is_separator_span(text: &str) -> bool {
    let compact: String = text
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    if compact.is_empty() {
        return false;
    }
    compact.chars().all(|c| {
        matches!(
            c,
            '-' | '_' | '=' | '—' | '–' | '─' | '━' | '＝' | '□' | '■' | '▪' | '▫'
        )
    })
}

fn is_placeholder_text(text: &str) -> bool {
    let compact: Vec<char> = text
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();
    (1..=3).contains(&compact.len())
        && compact
            .iter()
            .all(|character| matches!(*character, '-' | '—' | '–'))
}

#[derive(Debug, Clone)]
struct PreparedSpan {
    span: NativeSpanDto,
    fragment_index: i64,
    fragment_count: i64,
    split: bool,
}

const PYTHON_DECIMAL_DIGIT_RANGES: &[(u32, u32)] = &[
    (0x30, 0x39),
    (0x660, 0x669),
    (0x6F0, 0x6F9),
    (0x7C0, 0x7C9),
    (0x966, 0x96F),
    (0x9E6, 0x9EF),
    (0xA66, 0xA6F),
    (0xAE6, 0xAEF),
    (0xB66, 0xB6F),
    (0xBE6, 0xBEF),
    (0xC66, 0xC6F),
    (0xCE6, 0xCEF),
    (0xD66, 0xD6F),
    (0xDE6, 0xDEF),
    (0xE50, 0xE59),
    (0xED0, 0xED9),
    (0xF20, 0xF29),
    (0x1040, 0x1049),
    (0x1090, 0x1099),
    (0x17E0, 0x17E9),
    (0x1810, 0x1819),
    (0x1946, 0x194F),
    (0x19D0, 0x19D9),
    (0x1A80, 0x1A89),
    (0x1A90, 0x1A99),
    (0x1B50, 0x1B59),
    (0x1BB0, 0x1BB9),
    (0x1C40, 0x1C49),
    (0x1C50, 0x1C59),
    (0xA620, 0xA629),
    (0xA8D0, 0xA8D9),
    (0xA900, 0xA909),
    (0xA9D0, 0xA9D9),
    (0xA9F0, 0xA9F9),
    (0xAA50, 0xAA59),
    (0xABF0, 0xABF9),
    (0xFF10, 0xFF19),
    (0x104A0, 0x104A9),
    (0x10D30, 0x10D39),
    (0x11066, 0x1106F),
    (0x110F0, 0x110F9),
    (0x11136, 0x1113F),
    (0x111D0, 0x111D9),
    (0x112F0, 0x112F9),
    (0x11450, 0x11459),
    (0x114D0, 0x114D9),
    (0x11650, 0x11659),
    (0x116C0, 0x116C9),
    (0x11730, 0x11739),
    (0x118E0, 0x118E9),
    (0x11950, 0x11959),
    (0x11C50, 0x11C59),
    (0x11D50, 0x11D59),
    (0x11DA0, 0x11DA9),
    (0x11F50, 0x11F59),
    (0x16A60, 0x16A69),
    (0x16AC0, 0x16AC9),
    (0x16B50, 0x16B59),
    (0x1D7CE, 0x1D7FF),
    (0x1E140, 0x1E149),
    (0x1E2F0, 0x1E2F9),
    (0x1E4F0, 0x1E4F9),
    (0x1E950, 0x1E959),
    (0x1FBF0, 0x1FBF9),
];

fn is_python_decimal_digit(character: char) -> bool {
    let codepoint = character as u32;
    PYTHON_DECIMAL_DIGIT_RANGES
        .iter()
        .any(|&(start, end)| (start..=end).contains(&codepoint))
}

fn is_python_numeric_text(text: &str) -> bool {
    let chars: Vec<char> = text.trim().chars().collect();
    if chars.is_empty() {
        return false;
    }

    let mut start = 0;
    let mut end = chars.len();
    if chars.first() == Some(&'(') {
        start += 1;
    }
    if chars.last() == Some(&')') {
        end -= 1;
    }
    if start >= end {
        return false;
    }

    let body = &chars[start..end];
    let mut index = 0;
    if body
        .get(index)
        .is_some_and(|character| matches!(*character, '+' | '-' | '–' | '—' | '−'))
    {
        index += 1;
    }
    if index >= body.len() || !is_python_decimal_digit(body[index]) {
        return false;
    }
    index += 1;
    while index < body.len() && (is_python_decimal_digit(body[index]) || body[index] == ',') {
        index += 1;
    }
    if index < body.len() && body[index] == '.' {
        index += 1;
        let decimal_start = index;
        while index < body.len() && is_python_decimal_digit(body[index]) {
            index += 1;
        }
        if decimal_start == index {
            return false;
        }
    }
    if index < body.len() && body[index] == '%' {
        index += 1;
    }
    index == body.len()
}

fn is_packed_numeric_char(character: char) -> bool {
    character.is_whitespace()
        || is_python_decimal_digit(character)
        || matches!(character, ',' | '.' | '(' | ')' | '%' | '+' | '-' | '–' | '—' | '−')
}

fn prepared_unsplit(span: NativeSpanDto) -> PreparedSpan {
    PreparedSpan {
        span,
        fragment_index: 0,
        fragment_count: 1,
        split: false,
    }
}

fn normalize_span_text(mut span: NativeSpanDto) -> NativeSpanDto {
    span.text = span.text.replace('\n', " ").trim().to_string();
    span
}

fn split_packed_numeric_span(span: NativeSpanDto) -> Vec<PreparedSpan> {
    let text = span.text.trim();
    if text.is_empty() || !text.chars().all(is_packed_numeric_char) {
        return vec![prepared_unsplit(span)];
    }

    let mut first = 0;
    let mut last = span.characters.len();
    while first < last
        && span.characters[first]
            .text
            .chars()
            .all(char::is_whitespace)
    {
        first += 1;
    }
    while last > first
        && span.characters[last - 1]
            .text
            .chars()
            .all(char::is_whitespace)
    {
        last -= 1;
    }
    let character_boxes = &span.characters[first..last];
    if character_boxes
        .iter()
        .any(|character| character.text.chars().count() != 1)
        || character_boxes
            .iter()
            .map(|character| character.text.as_str())
            .collect::<String>()
            != text
    {
        return vec![prepared_unsplit(span)];
    }

    let characters: Vec<char> = text.chars().collect();
    let gap_limit = 1.5_f64.max(span.size.unwrap_or(0.0) * 0.18);
    let mut split_points = vec![0usize];
    let mut index = 0usize;
    while index < characters.len() {
        if !characters[index].is_whitespace() {
            index += 1;
            continue;
        }
        let whitespace_start = index;
        while index < characters.len() && characters[index].is_whitespace() {
            index += 1;
        }
        let whitespace_end = index;
        if whitespace_start == 0 || whitespace_end == characters.len() {
            continue;
        }
        let total_gap = span.characters[first + whitespace_end].rect.x0
            - span.characters[first + whitespace_start - 1].rect.x1;
        let max_gap = (whitespace_start..=whitespace_end)
            .map(|right| {
                span.characters[first + right].rect.x0
                    - span.characters[first + right - 1].rect.x1
            })
            .fold(f64::NEG_INFINITY, f64::max);
        if total_gap >= gap_limit || max_gap >= gap_limit {
            split_points.push(whitespace_end);
        }
    }
    if split_points.len() == 1 {
        return vec![prepared_unsplit(span)];
    }
    split_points.push(characters.len());

    let fragment_count = (split_points.len() - 1) as i64;
    let mut fragments = Vec::with_capacity(fragment_count as usize);
    for (fragment_index, bounds) in split_points.windows(2).enumerate() {
        let start = bounds[0];
        let end = bounds[1];
        let fragment_text: String = characters[start..end].iter().collect();
        let fragment_text = fragment_text.trim().to_string();
        let glyphs: Vec<CharacterDto> = character_boxes[start..end]
            .iter()
            .filter(|character| !character.text.chars().all(char::is_whitespace))
            .cloned()
            .collect();
        if fragment_text.is_empty() || glyphs.is_empty() {
            return vec![prepared_unsplit(span)];
        }
        let rect = Rect4 {
            schema_version: 1,
            x0: glyphs
                .iter()
                .map(|character| character.rect.x0)
                .fold(f64::INFINITY, f64::min),
            y0: glyphs
                .iter()
                .map(|character| character.rect.y0)
                .fold(f64::INFINITY, f64::min),
            x1: glyphs
                .iter()
                .map(|character| character.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max),
            y1: glyphs
                .iter()
                .map(|character| character.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max),
        };
        let mut fragment = span.clone();
        fragment.text = fragment_text;
        fragment.rect = rect;
        fragment.characters = glyphs;
        fragments.push(PreparedSpan {
            span: fragment,
            fragment_index: fragment_index as i64,
            fragment_count,
            split: true,
        });
    }
    fragments
}

fn run_font_size(run: &TextRunDto) -> f64 {
    run.evidence
        .as_ref()
        .and_then(|evidence| evidence.sizes.first().copied().flatten())
        .unwrap_or(10.0)
}

fn run_is_bold(run: &TextRunDto) -> bool {
    run.evidence
        .as_ref()
        .and_then(|evidence| evidence.fonts.first())
        .and_then(|font| font.as_deref())
        .map(|font| font.to_ascii_lowercase().contains("bold"))
        .unwrap_or(false)
}

fn run_source_bounds(run: &TextRunDto) -> Option<(Vec<i64>, i64, i64)> {
    let evidence = run.evidence.as_ref()?;
    if evidence.source_positions.is_empty() {
        return None;
    }
    let mut blocks = Vec::new();
    let mut line_start = i64::MAX;
    let mut line_end = i64::MIN;
    for position in &evidence.source_positions {
        if !blocks.contains(&position.block) {
            blocks.push(position.block);
        }
        line_start = line_start.min(position.line);
        line_end = line_end.max(position.line);
    }
    blocks.sort_unstable();
    Some((blocks, line_start, line_end))
}

fn horizontal_overlap(left: &Rect4, right: &Rect4) -> f64 {
    (left.x1.min(right.x1) - left.x0.max(right.x0)).max(0.0)
}

fn right_witnesses<'a>(
    chain: &[TextRunDto],
    candidate: &TextRunDto,
    runs: &'a [TextRunDto],
    require_flow_after: bool,
    minimum_horizontal_gap: f64,
    vertical_margin: f64,
) -> Vec<&'a TextRunDto> {
    let y0 = chain
        .first()
        .map(|run| run.rect.y0.min(candidate.rect.y0))
        .unwrap_or(candidate.rect.y0)
        - vertical_margin;
    let y1 = chain
        .last()
        .map(|run| run.rect.y1.max(candidate.rect.y1))
        .unwrap_or(candidate.rect.y1)
        + run_font_size(candidate).max(10.0) * 4.0;
    let x1 = chain
        .iter()
        .map(|run| run.rect.x1)
        .chain(std::iter::once(candidate.rect.x1))
        .fold(f64::NEG_INFINITY, f64::max);
    runs.iter()
        .filter(|run| {
            let in_chain = chain.iter().any(|item| item.order == run.order);
            let after_candidate = run.source_start > candidate.source_end;
            !in_chain
                && run.order != candidate.order
                && (!require_flow_after || after_candidate)
                && run.rect.x0 >= x1 + minimum_horizontal_gap
                && y1.min(run.rect.y1) > y0.max(run.rect.y0)
        })
        .collect()
}

fn is_strong_native_vertical_pair(previous: &TextRunDto, candidate: &TextRunDto) -> bool {
    let previous_text = previous.text.trim();
    let candidate_text = candidate.text.trim();
    if !is_single_cjk(previous_text) || !is_single_cjk(candidate_text) {
        return false;
    }
    let Some((previous_blocks, previous_start, previous_end)) = run_source_bounds(previous) else {
        return false;
    };
    let Some((candidate_blocks, candidate_start, candidate_end)) = run_source_bounds(candidate) else {
        return false;
    };
    if previous_blocks.len() != 1
        || previous_blocks != candidate_blocks
        || previous_start != previous_end
        || candidate_start != candidate_end
        || candidate_start != previous_end + 1
    {
        return false;
    }

    let minimum_font_size = run_font_size(previous).min(run_font_size(candidate));
    if minimum_font_size <= 0.0
        || run_is_bold(previous) != run_is_bold(candidate)
        || (run_font_size(previous) - run_font_size(candidate)).abs()
            > 0.5_f64.max(minimum_font_size * 0.1)
    {
        return false;
    }

    let tolerance = 1.0_f64.max(minimum_font_size * 0.12);
    (previous.rect.x0 - candidate.rect.x0).abs() <= tolerance
        && (previous.rect.x1 - candidate.rect.x1).abs() <= tolerance
        && candidate.rect.y0 >= previous.rect.y1
        && candidate.rect.y0 - previous.rect.y1 <= 6.0_f64.max(minimum_font_size)
        && candidate.rect.y0 > previous.rect.y0
}

fn is_multiline_witness(run: &TextRunDto) -> bool {
    let font_size = run_font_size(run);
    font_size > 0.0
        && run.rect.y1 - run.rect.y0 >= (font_size * 1.5).max(font_size + 3.0)
}

fn has_multiline_right_witness(
    chain: &[TextRunDto],
    candidate: &TextRunDto,
    runs: &[TextRunDto],
) -> bool {
    let font_size = run_font_size(chain.last().unwrap_or(candidate)).min(run_font_size(candidate));
    if font_size <= 0.0 {
        return false;
    }
    let witnesses = right_witnesses(
        chain,
        candidate,
        runs,
        false,
        6.0_f64.max(font_size * 0.6),
        2.0_f64.max(font_size * 0.8),
    );
    for seed in &witnesses {
        let seed_width = seed.rect.x1 - seed.rect.x0;
        let mut group: Vec<&TextRunDto> = witnesses
            .iter()
            .copied()
            .filter(|item| {
                horizontal_overlap(&seed.rect, &item.rect)
                    >= 2.0_f64.max(seed_width.min(item.rect.x1 - item.rect.x0) * 0.45)
            })
            .collect();
        group.sort_by(|left, right| {
            left.rect
                .y0
                .partial_cmp(&right.rect.y0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        if group.len() == 1 && !is_multiline_witness(group[0]) {
            continue;
        }
        if group.windows(2).any(|pair| {
            pair[1].rect.y0 - pair[0].rect.y1 > 4.0_f64.max(font_size * 0.5)
        }) {
            continue;
        }
        let group_y0 = group.iter().map(|item| item.rect.y0).fold(f64::INFINITY, f64::min);
        let group_y1 = group.iter().map(|item| item.rect.y1).fold(f64::NEG_INFINITY, f64::max);
        if group_y0 <= chain.last().unwrap().rect.y0 - 2.0_f64.max(font_size * 0.5)
            && candidate.rect.y1 >= group_y1 - font_size
        {
            return true;
        }
    }
    false
}

fn is_wrapped_chain_pair(
    chain: &[TextRunDto],
    candidate: &TextRunDto,
    runs: &[TextRunDto],
) -> bool {
    let left = chain.last().unwrap();
    if left.text.trim_end().ends_with([':', '：'])
        || candidate.source_start != left.source_end + 1
    {
        return false;
    }
    let base_bold = run_is_bold(chain.first().unwrap());
    if run_is_bold(left) != run_is_bold(candidate) && base_bold != run_is_bold(candidate) {
        return false;
    }
    if (run_font_size(left) - run_font_size(candidate)).abs() > 1.0
        || is_python_numeric_text(left.text.trim())
        || is_python_numeric_text(candidate.text.trim())
        || is_placeholder_text(left.text.trim())
        || is_placeholder_text(candidate.text.trim())
    {
        return false;
    }

    let left_center = center_y(&left.rect);
    let candidate_center = center_y(&candidate.rect);
    if candidate_center <= left_center || candidate.rect.y0 < left.rect.y1 {
        return false;
    }
    let minimum_width = (left.rect.x1 - left.rect.x0).min(candidate.rect.x1 - candidate.rect.x0);
    if horizontal_overlap(&left.rect, &candidate.rect) < minimum_width * 0.45
        || candidate.rect.y0 - left.rect.y1
            > 6.0_f64.max(run_font_size(left).min(run_font_size(candidate)))
    {
        return false;
    }

    if !right_witnesses(chain, candidate, runs, true, 8.0, 2.0).is_empty() {
        return true;
    }
    is_strong_native_vertical_pair(left, candidate)
        && has_multiline_right_witness(chain, candidate, runs)
}

fn merge_run_chain(chain: &[TextRunDto]) -> TextRunDto {
    let first = chain.first().expect("wrapped chain must not be empty");
    let mut source_positions = Vec::new();
    let mut fonts = Vec::new();
    let mut sizes = Vec::new();
    let mut flags = Vec::new();
    let mut fragment_indices = Vec::new();
    let mut fragment_counts = Vec::new();
    let mut has_fragment_evidence = true;
    for run in chain {
        if let Some(evidence) = &run.evidence {
            source_positions.extend(evidence.source_positions.clone());
            fonts.extend(evidence.fonts.clone());
            sizes.extend(evidence.sizes.clone());
            flags.extend(evidence.flags.clone());
            match (
                &evidence.source_fragment_indices,
                &evidence.source_fragment_counts,
            ) {
                (Some(indices), Some(counts)) => {
                    fragment_indices.extend(indices.clone());
                    fragment_counts.extend(counts.clone());
                }
                _ => has_fragment_evidence = false,
            }
        } else {
            has_fragment_evidence = false;
        }
    }
    let evidence = if source_positions.is_empty() {
        None
    } else {
        Some(TextRunEvidenceDto {
            schema_version: first
                .evidence
                .as_ref()
                .map(|evidence| evidence.schema_version)
                .unwrap_or(1),
            source_positions,
            fonts,
            sizes,
            flags,
            source_fragment_indices: has_fragment_evidence.then_some(fragment_indices),
            source_fragment_counts: has_fragment_evidence.then_some(fragment_counts),
        })
    };
    TextRunDto {
        schema_version: first.schema_version,
        text: chain
            .iter()
            .map(|run| run.text.as_str())
            .collect::<Vec<_>>()
            .join("\n"),
        rect: Rect4 {
            schema_version: first.rect.schema_version,
            x0: chain.iter().map(|run| run.rect.x0).fold(f64::INFINITY, f64::min),
            y0: chain.iter().map(|run| run.rect.y0).fold(f64::INFINITY, f64::min),
            x1: chain.iter().map(|run| run.rect.x1).fold(f64::NEG_INFINITY, f64::max),
            y1: chain.iter().map(|run| run.rect.y1).fold(f64::NEG_INFINITY, f64::max),
        },
        span_refs: chain
            .iter()
            .flat_map(|run| run.span_refs.iter().copied())
            .collect(),
        source_start: chain.iter().map(|run| run.source_start).min().unwrap_or(0),
        source_end: chain.iter().map(|run| run.source_end).max().unwrap_or(0),
        order: first.order,
        evidence,
    }
}

fn merge_wrapped_field_runs(mut runs: Vec<TextRunDto>) -> Vec<TextRunDto> {
    if runs.len() < 2 {
        return runs;
    }
    runs.sort_by(|left, right| {
        left.source_start
            .cmp(&right.source_start)
            .then(left.source_end.cmp(&right.source_end))
            .then(left.order.cmp(&right.order))
    });
    let mut result = Vec::new();
    let mut index = 0;
    while index < runs.len() {
        let mut chain = vec![runs[index].clone()];
        let mut cursor = index + 1;
        while cursor < runs.len() && is_wrapped_chain_pair(&chain, &runs[cursor], &runs) {
            chain.push(runs[cursor].clone());
            cursor += 1;
        }
        if chain.len() == 1 {
            result.push(runs[index].clone());
            index += 1;
        } else {
            result.push(merge_run_chain(&chain));
            index = cursor;
        }
    }
    result.sort_by(|left, right| {
        left.source_start
            .cmp(&right.source_start)
            .then(left.source_end.cmp(&right.source_end))
            .then(left.order.cmp(&right.order))
    });
    result
}

pub fn build_text_runs(spans: Vec<NativeSpanDto>, region: Rect4) -> Vec<TextRunDto> {
    if spans.is_empty() {
        return Vec::new();
    }

    // 1. 过滤中心点在 region 范围内的非空 span，并排除长度大于 3 的纯线分隔符
    let mut valid_spans: Vec<PreparedSpan> = spans
        .into_iter()
        .map(normalize_span_text)
        .filter(|s| {
            let t = s.text.trim();
            if t.is_empty() {
                return false;
            }
            let cx = center_x(&s.rect);
            let cy = center_y(&s.rect);
            if cx < region.x0 || cx > region.x1 || cy < region.y0 || cy > region.y1 {
                return false;
            }
            let is_sep = is_separator_span(t);
            if is_sep && t.chars().count() > 3 {
                return false;
            }
            true
        })
        .flat_map(split_packed_numeric_span)
        .filter(|s| {
            let text = s.span.text.trim();
            !(is_separator_span(text) && text.chars().count() > 3)
        })
        .collect();

    if valid_spans.is_empty() {
        return Vec::new();
    }

    // 2. 按视觉行分组（y-center 容差聚类）
    valid_spans.sort_by(
        |a, b| match center_y(&a.span.rect).partial_cmp(&center_y(&b.span.rect)) {
            Some(std::cmp::Ordering::Equal) => match a.span.rect.x0.partial_cmp(&b.span.rect.x0) {
                Some(std::cmp::Ordering::Equal) => a.span.order.cmp(&b.span.order),
                Some(ord) => ord,
                None => std::cmp::Ordering::Equal,
            },
            Some(ord) => ord,
            None => std::cmp::Ordering::Equal,
        },
    );

    let mut rows: Vec<Vec<PreparedSpan>> = Vec::new();
    let mut row_centers: Vec<f64> = Vec::new();

    for span in valid_spans {
        let cy = center_y(&span.span.rect);
        let size = span.span.size.unwrap_or(10.0);
        let tol = 2.4_f64.max(size * 0.38);

        let mut matched = false;
        for (r_idx, center) in row_centers.iter().enumerate().rev() {
            if (cy - center).abs() <= tol {
                rows[r_idx].push(span.clone());
                let count = rows[r_idx].len() as f64;
                let sum_cy: f64 = rows[r_idx]
                    .iter()
                    .map(|s| center_y(&s.span.rect))
                    .sum();
                row_centers[r_idx] = sum_cy / count;
                matched = true;
                break;
            }
        }
        if !matched {
            rows.push(vec![span]);
            row_centers.push(cy);
        }
    }

    // 3. 行内成词（基于 can_join 与白名单逻辑）
    let mut runs: Vec<TextRunDto> = Vec::new();
    let mut run_order = 0;

    for mut row in rows {
        row.sort_by(|a, b| {
            a.span
                .rect
                .x0
                .partial_cmp(&b.span.rect.x0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut groups: Vec<Vec<PreparedSpan>> = Vec::new();
        for span in row {
            if groups.is_empty() {
                groups.push(vec![span]);
                continue;
            }

            let can_join = {
                let previous = groups.last().unwrap().last().unwrap();
                let prev = &previous.span;
                let candidate = &span.span;
                let gap = candidate.rect.x0 - prev.rect.x1;
                let prev_size = prev.size.unwrap_or(10.0);
                let cand_size = candidate.size.unwrap_or(10.0);
                let min_size = prev_size.min(cand_size);
                let same_line =
                    prev.block == candidate.block
                        && prev.line == candidate.line
                        && candidate.order >= prev.order;
                let same_source_fragments = previous.split
                    && span.split
                    && prev.order == candidate.order
                    && previous.fragment_count == span.fragment_count;
                let previous_is_placeholder = is_placeholder_text(&prev.text);
                let candidate_is_placeholder = is_placeholder_text(&candidate.text);
                let previous_is_numeric = is_python_numeric_text(&prev.text);
                let candidate_is_numeric = is_python_numeric_text(&candidate.text);
                let has_substantive_text = groups.iter().flatten().any(|item| {
                    let text = item.span.text.trim();
                    !text.is_empty() && !is_placeholder_text(text) && !is_python_numeric_text(text)
                });
                let inline_punctuation = same_line
                    && gap <= 1.0
                    && (!previous_is_placeholder || has_substantive_text)
                    && (prev.text.trim().chars().count() == 1
                        || candidate.text.trim().chars().count() == 1);
                let placeholder_veto = (previous_is_placeholder && candidate_is_numeric)
                    || (previous_is_numeric && candidate_is_placeholder)
                    || (previous_is_placeholder && candidate_is_placeholder)
                    || (gap > 0.0
                        && !inline_punctuation
                        && (previous_is_placeholder || candidate_is_placeholder));
                let superscript = cand_size < prev_size * 0.82
                    && prev.rect.x1 - prev_size * 0.9 <= candidate.rect.x0
                    && candidate.rect.x0 <= prev.rect.x1 + prev_size * 0.45;
                let numeric_gap_veto = gap > 0.8 && previous_is_numeric && candidate_is_numeric;

                if same_source_fragments {
                    false
                } else if prev.text == "$" || candidate.text == "$" {
                    false
                } else if (center_y(&prev.rect) - center_y(&candidate.rect)).abs()
                    > 2.4_f64.max(min_size * 0.38)
                {
                    false
                } else if placeholder_veto {
                    false
                } else if superscript && numeric_gap_veto {
                    false
                } else if superscript {
                    true
                } else if is_whitelisted_cjk_pair(&prev.text, &candidate.text) {
                    same_line && (-0.8..=min_size * 2.5).contains(&gap)
                } else if is_single_cjk(&prev.text) && is_single_cjk(&candidate.text) {
                    same_line && (-0.8..=min_size * 1.25).contains(&gap)
                } else if same_line && (-0.8..=min_size * 0.8).contains(&gap) {
                    true
                } else {
                    false
                }
            };

            if can_join {
                groups.last_mut().unwrap().push(span);
            } else {
                groups.push(vec![span]);
            }
        }

        for group in groups {
            let joined_text = group
                .iter()
                .map(|s| s.span.text.as_str())
                .collect::<Vec<_>>()
                .join("");
            let x0 = group
                .iter()
                .map(|s| s.span.rect.x0)
                .fold(f64::INFINITY, f64::min);
            let y0 = group
                .iter()
                .map(|s| s.span.rect.y0)
                .fold(f64::INFINITY, f64::min);
            let x1 = group
                .iter()
                .map(|s| s.span.rect.x1)
                .fold(f64::NEG_INFINITY, f64::max);
            let y1 = group
                .iter()
                .map(|s| s.span.rect.y1)
                .fold(f64::NEG_INFINITY, f64::max);
            let span_refs = group.iter().map(|s| s.span.order).collect();
            let source_start = group.iter().map(|s| s.span.order).min().unwrap_or(0);
            let source_end = group.iter().map(|s| s.span.order).max().unwrap_or(0);
            let has_fragments = group.iter().any(|s| s.split);
            let evidence = TextRunEvidenceDto {
                schema_version: 1,
                source_positions: group
                    .iter()
                    .map(|s| s.span.source_position.clone())
                    .collect(),
                fonts: group.iter().map(|s| s.span.font.clone()).collect(),
                sizes: group.iter().map(|s| s.span.size).collect(),
                flags: group.iter().map(|s| s.span.flags).collect(),
                source_fragment_indices: has_fragments
                    .then(|| group.iter().map(|s| s.fragment_index).collect()),
                source_fragment_counts: has_fragments
                    .then(|| group.iter().map(|s| s.fragment_count).collect()),
            };

            runs.push(TextRunDto {
                schema_version: 1,
                text: joined_text,
                rect: Rect4 {
                    schema_version: 1,
                    x0,
                    y0,
                    x1,
                    y1,
                },
                span_refs,
                source_start,
                source_end,
                order: run_order,
                evidence: Some(evidence),
            });
            run_order += 1;
        }
    }

    merge_wrapped_field_runs(runs)
}

pub fn build_atoms(runs: Vec<TextRunDto>, _region: Option<Rect4>) -> Vec<AtomDto> {
    runs.into_iter()
        .map(|run| AtomDto {
            schema_version: 1,
            text: run.text,
            rect: run.rect,
            run_refs: vec![run.order],
            row_hint: None,
            col_hint: None,
            order: run.order,
        })
        .collect()
}

pub fn merge_wrapped_rows(atoms: Vec<AtomDto>, tolerance: f64) -> Vec<AtomDto> {
    if atoms.len() < 2 {
        return atoms;
    }

    let mut result: Vec<AtomDto> = Vec::new();
    for atom in atoms {
        if let Some(prev) = result.last_mut() {
            let vertical_gap = atom.rect.y0 - prev.rect.y1;
            let overlap_x = prev.rect.x1.min(atom.rect.x1) - prev.rect.x0.max(atom.rect.x0);
            let prev_w = prev.rect.x1 - prev.rect.x0;

            if vertical_gap >= 0.0
                && vertical_gap <= tolerance
                && overlap_x > 0.0
                && overlap_x >= prev_w * 0.4
            {
                prev.text.push_str(&atom.text);
                prev.rect.y1 = prev.rect.y1.max(atom.rect.y1);
                prev.rect.x0 = prev.rect.x0.min(atom.rect.x0);
                prev.rect.x1 = prev.rect.x1.max(atom.rect.x1);
                prev.run_refs.extend(atom.run_refs);
                continue;
            }
        }
        result.push(atom);
    }
    result
}

pub fn infer_output_order_mode(atoms: Vec<AtomDto>) -> OutputOrderMode {
    if atoms.len() < 4 {
        return OutputOrderMode {
            schema_version: 1,
            value: "row_interleaved".to_string(),
        };
    }

    let mut row_interleaved_votes = 0;
    let mut columnar_votes = 0;

    for window in atoms.windows(2) {
        let a = &window[0];
        let b = &window[1];
        let dy = (center_y(&b.rect) - center_y(&a.rect)).abs();
        let dx = (center_x(&b.rect) - center_x(&a.rect)).abs();
        if dx > dy * 1.5 {
            row_interleaved_votes += 1;
        } else if dy > dx * 1.5 {
            columnar_votes += 1;
        }
    }

    let value = if columnar_votes > row_interleaved_votes * 2 {
        "columnar".to_string()
    } else {
        "row_interleaved".to_string()
    };

    OutputOrderMode {
        schema_version: 1,
        value,
    }
}

pub fn recover_native_candidates(input: NativeRecoveryInput) -> NativeRecoveryOutput {
    let runs = build_text_runs(input.spans, input.region.rect.clone());
    let atoms = build_atoms(runs, Some(input.region.rect.clone()));

    if atoms.len() < 4 {
        return NativeRecoveryOutput {
            schema_version: 1,
            candidates: Vec::new(),
            atoms,
            diagnostics: Vec::new(),
        };
    }

    // 简单行/列分布检测
    let mut y_coords: Vec<f64> = atoms.iter().map(|a| center_y(&a.rect)).collect();
    y_coords.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mut rows = 1;
    for w in y_coords.windows(2) {
        if w[1] - w[0] > input.config.row_tolerance {
            rows += 1;
        }
    }

    let mut x_coords: Vec<f64> = atoms.iter().map(|a| center_x(&a.rect)).collect();
    x_coords.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let mut cols = 1;
    for w in x_coords.windows(2) {
        if w[1] - w[0] > input.config.column_tolerance * 5.0 {
            cols += 1;
        }
    }

    let mut candidates = Vec::new();
    if rows >= 2 && cols >= 2 {
        let x0 = atoms
            .iter()
            .map(|a| a.rect.x0)
            .fold(f64::INFINITY, f64::min);
        let y0 = atoms
            .iter()
            .map(|a| a.rect.y0)
            .fold(f64::INFINITY, f64::min);
        let x1 = atoms
            .iter()
            .map(|a| a.rect.x1)
            .fold(f64::NEG_INFINITY, f64::max);
        let y1 = atoms
            .iter()
            .map(|a| a.rect.y1)
            .fold(f64::NEG_INFINITY, f64::max);

        candidates.push(TableCandidateDto {
            schema_version: 1,
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            source: "wireless_native_recovery".to_string(),
            confidence: Some(0.9),
            rows: rows as i64,
            cols: cols as i64,
            cells: Vec::new(),
        });
    }

    NativeRecoveryOutput {
        schema_version: 1,
        candidates,
        atoms,
        diagnostics: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{CharacterDto, Rect4, SourcePositionDto};

    fn make_span(text: &str, x0: f64, y0: f64, x1: f64, y1: f64, order: i64) -> NativeSpanDto {
        NativeSpanDto {
            schema_version: 1,
            text: text.to_string(),
            rect: Rect4 {
                schema_version: 1,
                x0,
                y0,
                x1,
                y1,
            },
            font: Some("SimSun".to_string()),
            size: Some(10.0),
            flags: Some(0),
            order,
            characters: vec![CharacterDto {
                schema_version: 1,
                text: text.to_string(),
                rect: Rect4 {
                    schema_version: 1,
                    x0,
                    y0,
                    x1,
                    y1,
                },
                order,
            }],
            source_position: SourcePositionDto {
                schema_version: 1,
                block: 0,
                line: 0,
            },
            block: 0,
            line: 0,
        }
    }

    #[test]
    fn test_whitelist_cjk_merge() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 500.0,
        };
        let spans = vec![
            make_span("合", 10.0, 10.0, 20.0, 20.0, 0),
            make_span("计", 40.0, 10.0, 50.0, 20.0, 1),
        ];
        let runs = build_text_runs(spans, region);
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].text, "合计");
    }

    #[test]
    fn test_non_whitelist_cjk_separated() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 500.0,
        };
        let spans = vec![
            make_span("男", 10.0, 10.0, 20.0, 20.0, 0),
            make_span("女", 35.0, 10.0, 45.0, 20.0, 1),
        ];
        let runs = build_text_runs(spans, region);
        assert_eq!(runs.len(), 2);
        assert_eq!(runs[0].text, "男");
        assert_eq!(runs[1].text, "女");
    }

    #[test]
    fn test_filters_spaced_text_separator_rows() {
        let region = Rect4 {
            schema_version: 1,
            x0: 0.0,
            y0: 0.0,
            x1: 500.0,
            y1: 500.0,
        };
        let spans = vec![
            make_span(
                "=================  ================",
                10.0,
                10.0,
                180.0,
                20.0,
                0,
            ),
            make_span("项目", 10.0, 30.0, 40.0, 40.0, 1),
            make_span("500", 100.0, 30.0, 130.0, 40.0, 2),
        ];
        let runs = build_text_runs(spans, region);
        assert_eq!(runs.len(), 2);
        assert_eq!(runs[0].text, "项目");
        assert_eq!(runs[1].text, "500");
    }
}
