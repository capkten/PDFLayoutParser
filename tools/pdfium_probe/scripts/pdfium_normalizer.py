"""PDFium text hierarchy normalizer: chars -> spans -> lines -> blocks -> words.

Transforms PDFium raw page extraction into:
1. PyMuPDF-compatible rawdict views (blocks -> lines -> spans -> chars).
2. PDF Fast Rust wire PageSnapshotDto (text_blocks -> lines -> spans -> characters).
3. PyMuPDF-compatible words list (8-tuples).
"""

import math
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple, Union

from pdfium_classification import classify_raw_page, is_vector_page


# --- Named Clustering Constants ---
LINE_OVERLAP_RATIO_TOLERANCE: float = 0.5
LINE_Y_CENTER_FACTOR: float = 0.4
SPAN_MERGE_MAX_GAP_FACTOR: float = 0.4
BLOCK_LINE_GAP_FACTOR: float = 1.5
BLOCK_HORIZONTAL_GAP_FACTOR: float = 2.0
WORD_CHAR_GAP_FACTOR: float = 0.5


class NormalizedPage(NamedTuple):
    page_type: str
    page_snapshot: Optional[Dict[str, Any]]
    rawdict: Optional[Dict[str, Any]]
    words: List[Tuple[float, float, float, float, str, int, int, int]]
    sidecar: Dict[str, Any]
    diagnostics: Dict[str, Any]


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        (0x4E00 <= code <= 0x9FFF)
        or (0x3400 <= code <= 0x4DBF)
        or (0x20000 <= code <= 0x2A6DF)
        or (0xF900 <= code <= 0xFAFF)
        or (0x3040 <= code <= 0x309F)
        or (0x30A0 <= code <= 0x30FF)
        or (0xAC00 <= code <= 0xD7AF)
    )


def _is_punctuation(ch: str) -> bool:
    if ch.isspace() or ch.isalnum():
        return False
    if _is_cjk(ch):
        return False
    return True


def _make_rect4(x0: float, y0: float, x1: float, y1: float) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "x0": float(x0),
        "y0": float(y0),
        "x1": float(x1),
        "y1": float(y1),
    }


def _is_buffer_numeric(buf: Sequence[Mapping[str, Any]]) -> bool:
    if not buf:
        return False
    text = "".join(c["c"] for c in buf)
    if text in ("+", "-", "+.", "-.", "."):
        return True
    stripped = text.lstrip("+-")
    return bool(stripped) and any(ch.isdigit() for ch in stripped)


def _ensure_mapping_diagnostics_if_missing(raw_page: Mapping[str, Any]) -> Dict[str, Any]:
    page_dict = dict(raw_page)
    if "mapping_diagnostics" in page_dict and isinstance(page_dict["mapping_diagnostics"], Mapping):
        return page_dict

    spans = page_dict.get("spans") or []
    all_text = "".join(s.get("text", "") for s in spans if isinstance(s, Mapping))
    clean_text = all_text.strip()
    extracted_chars = 0
    replacement_count = 0
    control_count = 0
    has_geom_err = False

    for s in spans:
        if not isinstance(s, Mapping):
            continue
        chars = s.get("characters") or []
        extracted_chars += len(chars)
        for ch in s.get("text", ""):
            if ch == "\ufffd":
                replacement_count += 1
            elif ord(ch) < 32 and ch not in ("\n", "\r", "\t"):
                control_count += 1
            elif 0x7F <= ord(ch) <= 0x9F or ord(ch) == 0:
                control_count += 1
        for c_info in chars:
            if isinstance(c_info, Mapping):
                cb = c_info.get("bbox")
                if not isinstance(cb, (list, tuple)) or len(cb) != 4:
                    has_geom_err = True
                elif not all(isinstance(v, (int, float)) and math.isfinite(v) for v in cb):
                    has_geom_err = True
                elif cb[0] > cb[2] or cb[1] > cb[3]:
                    has_geom_err = True

    is_valid = bool(clean_text) and (len(all_text) == extracted_chars) and (replacement_count == 0) and (control_count == 0) and not has_geom_err

    page_dict["mapping_diagnostics"] = {
        "visible_text_scalar_count": len(all_text),
        "extracted_char_scalar_count": extracted_chars,
        "replacement_char_count": replacement_count,
        "control_char_count": control_count,
        "mapping_status": "valid" if is_valid else "unknown",
        "classification_reason": None if is_valid else "unknown_unicode_mapping",
    }
    return page_dict


class _VisualSpan:
    def __init__(
        self,
        text: str,
        bbox: Sequence[float],
        font: Optional[str],
        size: Optional[float],
        flags: Optional[int],
        render_mode: int,
        is_invisible: bool,
        provenance: Dict[str, Any],
        characters: List[Dict[str, Any]],
        page_index: int,
    ) -> None:
        self.text = text
        self.bbox = [float(b) for b in bbox]
        self.font = font
        self.size = float(size) if size is not None else 10.0
        self.flags = flags
        self.render_mode = render_mode
        self.is_invisible = is_invisible
        self.provenance = dict(provenance)
        self.characters = list(characters)
        self.page_index = page_index

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def height(self) -> float:
        return max(0.1, self.y1 - self.y0)

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def can_merge_with(self, other: "_VisualSpan") -> bool:
        if self.font != other.font:
            return False
        if abs(self.size - other.size) > 0.5:
            return False
        if self.flags != other.flags:
            return False
        if self.render_mode != other.render_mode:
            return False
        char_h = min(self.height, other.height)
        gap = other.x0 - self.x1
        if gap < 0:
            return True
        return gap <= SPAN_MERGE_MAX_GAP_FACTOR * char_h

    def merge(self, other: "_VisualSpan") -> None:
        self.text = self.text + other.text
        self.bbox = [
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        ]
        # Preserve original characters intact with their individual pdfium_object_index
        self.characters.extend(other.characters)
        end_idx = other.provenance.get("char_end_index", len(other.characters))
        self.provenance["char_end_index"] = end_idx


class _VisualLine:
    def __init__(self, initial_span: _VisualSpan) -> None:
        self.spans: List[_VisualSpan] = [initial_span]
        self.y0: float = initial_span.y0
        self.y1: float = initial_span.y1
        self.cy: float = initial_span.cy
        self.height: float = initial_span.height

    def matches_span(self, span: _VisualSpan) -> bool:
        v_overlap = max(0.0, min(self.y1, span.y1) - max(self.y0, span.y0))
        min_h = min(self.height, span.height)
        overlap_ratio = v_overlap / min_h
        center_dist = abs(self.cy - span.cy)

        if overlap_ratio >= LINE_OVERLAP_RATIO_TOLERANCE:
            return True
        if center_dist <= LINE_Y_CENTER_FACTOR * min_h:
            return True
        return False

    def add_span(self, span: _VisualSpan) -> None:
        self.spans.append(span)
        self.y0 = min(self.y0, span.y0)
        self.y1 = max(self.y1, span.y1)
        self.cy = (self.y0 + self.y1) / 2.0
        self.height = max(0.1, self.y1 - self.y0)

    @property
    def x0(self) -> float:
        return min(s.x0 for s in self.spans)

    @property
    def x1(self) -> float:
        return max(s.x1 for s in self.spans)

    @property
    def bbox(self) -> List[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    def normalize_spans(self) -> None:
        # Sort spans strictly by horizontal x0
        self.spans.sort(key=lambda s: s.x0)
        # Merge compatible adjacent spans
        merged: List[_VisualSpan] = []
        for s in self.spans:
            if not merged:
                merged.append(s)
            else:
                last = merged[-1]
                if last.can_merge_with(s):
                    last.merge(s)
                else:
                    merged.append(s)
        self.spans = merged


class _VisualBlock:
    def __init__(self, initial_line: _VisualLine) -> None:
        self.lines: List[_VisualLine] = [initial_line]

    @property
    def x0(self) -> float:
        return min(l.x0 for l in self.lines)

    @property
    def y0(self) -> float:
        return min(l.y0 for l in self.lines)

    @property
    def x1(self) -> float:
        return max(l.x1 for l in self.lines)

    @property
    def y1(self) -> float:
        return max(l.y1 for l in self.lines)

    @property
    def bbox(self) -> List[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    def matches_line(self, line: _VisualLine) -> bool:
        last_line = self.lines[-1]
        line_gap = line.y0 - last_line.y1
        ref_h = min(last_line.height, line.height)

        # Allow vertical gap within tolerance
        if line_gap > BLOCK_LINE_GAP_FACTOR * ref_h:
            return False
        if line_gap < -0.5 * ref_h:
            return False

        # Horizontal projection: must overlap or be close, not across column gutter
        h_overlap = min(self.x1, line.x1) - max(self.x0, line.x0)
        if h_overlap < 0:
            h_gutter = max(self.x0, line.x0) - min(self.x1, line.x1)
            if h_gutter > BLOCK_HORIZONTAL_GAP_FACTOR * ref_h:
                return False
        return True

    def add_line(self, line: _VisualLine) -> None:
        self.lines.append(line)


def _derive_words(
    blocks: List[_VisualBlock], page_index: int
) -> Tuple[
    List[Tuple[float, float, float, float, str, int, int, int]],
    List[Dict[str, Any]],
]:
    word_tuples: List[Tuple[float, float, float, float, str, int, int, int]] = []
    wire_words: List[Dict[str, Any]] = []
    global_word_order = 0

    for block_idx, block in enumerate(blocks):
        for line_idx, line in enumerate(block.lines):
            line_chars: List[Dict[str, Any]] = []
            for span in line.spans:
                for ch in span.characters:
                    line_chars.append(
                        {
                            "c": ch["c"],
                            "bbox": ch["bbox"],
                            "char_index": ch["char_index"],
                            "obj_idx": ch["pdfium_object_index"],
                            "page_index": ch["page_index"],
                            "font": span.font,
                            "size": span.size,
                        }
                    )

            if not line_chars:
                continue

            # Sort characters by horizontal x0
            line_chars.sort(key=lambda c: c["bbox"][0])

            current_buf: List[Dict[str, Any]] = []
            line_word_idx = 0

            def flush_buf() -> None:
                nonlocal current_buf, global_word_order, line_word_idx
                if not current_buf:
                    return
                w_text = "".join(c["c"] for c in current_buf)
                if w_text in ("+", "-", "+.", "-.", "."):
                    current_buf = []
                    return
                w_x0 = min(c["bbox"][0] for c in current_buf)
                w_y0 = min(c["bbox"][1] for c in current_buf)
                w_x1 = max(c["bbox"][2] for c in current_buf)
                w_y1 = max(c["bbox"][3] for c in current_buf)
                first_c = current_buf[0]
                last_c = current_buf[-1]
                raw_pos = [
                    int(first_c["page_index"]),
                    int(first_c["obj_idx"]),
                    int(first_c["char_index"]),
                    int(last_c["char_index"]),
                ]

                word_tuples.append(
                    (
                        float(w_x0),
                        float(w_y0),
                        float(w_x1),
                        float(w_y1),
                        w_text,
                        int(block_idx),
                        int(line_idx),
                        int(line_word_idx),
                    )
                )

                wire_words.append(
                    {
                        "schema_version": 1,
                        "text": w_text,
                        "rect": _make_rect4(w_x0, w_y0, w_x1, w_y1),
                        "order": int(global_word_order),
                        "block": int(block_idx),
                        "line": int(line_idx),
                        "raw_source_position": raw_pos,
                    }
                )

                global_word_order += 1
                line_word_idx += 1
                current_buf = []

            i = 0
            while i < len(line_chars):
                ch_item = line_chars[i]
                c_str = ch_item["c"]

                if c_str.isspace():
                    flush_buf()
                    i += 1
                    continue

                if current_buf:
                    prev_c = current_buf[-1]
                    char_h = min(
                        prev_c["bbox"][3] - prev_c["bbox"][1],
                        ch_item["bbox"][3] - ch_item["bbox"][1],
                    )
                    char_gap = ch_item["bbox"][0] - prev_c["bbox"][2]
                    if char_gap > WORD_CHAR_GAP_FACTOR * char_h:
                        flush_buf()

                # If current_buf is still non-empty, test whether c_str continues it
                if current_buf:
                    prev_c = current_buf[-1]
                    prev_char = prev_c["c"]

                    if _is_buffer_numeric(current_buf):
                        if c_str.isdigit():
                            current_buf.append(ch_item)
                            i += 1
                            continue
                        elif c_str in ".,":
                            next_is_digit = (
                                i + 1 < len(line_chars) and line_chars[i + 1]["c"].isdigit()
                            )
                            if prev_char.isdigit() and next_is_digit:
                                if c_str == "." and any(c["c"] == "." for c in current_buf):
                                    flush_buf()
                                else:
                                    current_buf.append(ch_item)
                                    i += 1
                                    continue
                            else:
                                flush_buf()
                        elif c_str == "%" and prev_char.isdigit():
                            current_buf.append(ch_item)
                            flush_buf()
                            i += 1
                            continue
                        else:
                            flush_buf()

                    elif _is_cjk(prev_char):
                        if _is_cjk(c_str):
                            current_buf.append(ch_item)
                            i += 1
                            continue
                        else:
                            flush_buf()

                    else:
                        # Latin / Alphanumeric word
                        if (c_str.isalnum() and not _is_cjk(c_str)) or (
                            c_str == "'"
                            and i + 1 < len(line_chars)
                            and line_chars[i + 1]["c"].isalpha()
                        ):
                            current_buf.append(ch_item)
                            i += 1
                            continue
                        else:
                            flush_buf()

                # current_buf is empty (either initially or just flushed). Start new token if applicable:
                if c_str.isdigit():
                    current_buf.append(ch_item)
                    i += 1
                elif c_str in "+-":
                    next_is_digit = (
                        i + 1 < len(line_chars)
                        and (
                            line_chars[i + 1]["c"].isdigit()
                            or (
                                line_chars[i + 1]["c"] == "."
                                and i + 2 < len(line_chars)
                                and line_chars[i + 2]["c"].isdigit()
                            )
                        )
                    )
                    if next_is_digit:
                        current_buf.append(ch_item)
                        i += 1
                    else:
                        # standalone operator / delimiter
                        i += 1
                elif _is_cjk(c_str):
                    current_buf.append(ch_item)
                    i += 1
                elif c_str.isalnum() and not _is_cjk(c_str):
                    current_buf.append(ch_item)
                    i += 1
                else:
                    # delimiter punctuation
                    i += 1

            flush_buf()

    return word_tuples, wire_words


def normalize_raw_page(raw_page: Mapping[str, Any]) -> NormalizedPage:
    """Normalize a PDFium raw page extraction into NormalizedPage contract."""
    checked_page = _ensure_mapping_diagnostics_if_missing(raw_page)
    classification = classify_raw_page(checked_page)

    if not is_vector_page(classification):
        return NormalizedPage(
            page_type="scanned",
            page_snapshot=None,
            rawdict=None,
            words=[],
            sidecar={"classification": classification},
            diagnostics=dict(classification),
        )

    page_index = int(checked_page.get("page_index", 0))
    width = float(checked_page.get("width", 0.0))
    height = float(checked_page.get("height", 0.0))
    rotation = int(checked_page.get("rotation", 0))

    raw_spans = checked_page.get("spans") or []

    # Step 1: Construct visual span objects with rich character metadata
    visual_spans: List[_VisualSpan] = []
    for s_idx, r_span in enumerate(raw_spans):
        if not isinstance(r_span, Mapping):
            continue
        text = str(r_span.get("text", ""))
        bbox = list(r_span.get("bbox") or [0.0, 0.0, 0.0, 0.0])
        font = r_span.get("font")
        size = r_span.get("size")
        flags = r_span.get("flags")
        render_mode = int(r_span.get("render_mode", 0))
        is_invisible = bool(r_span.get("is_invisible", False))
        prov = dict(r_span.get("provenance") or {})
        p_obj_idx = prov.get("pdfium_object_index", r_span.get("order", s_idx))
        raw_chars = r_span.get("characters") or []

        char_records: List[Dict[str, Any]] = []
        for c_idx, ch in enumerate(raw_chars):
            c_text = ch.get("c", "") if isinstance(ch, Mapping) else ""
            c_bbox = list(ch.get("bbox", bbox)) if isinstance(ch, Mapping) else list(bbox)
            c_char_idx = ch.get("char_index", c_idx) if isinstance(ch, Mapping) else c_idx
            char_records.append(
                {
                    "c": c_text,
                    "bbox": [float(b) for b in c_bbox],
                    "char_index": int(c_char_idx),
                    "pdfium_object_index": int(p_obj_idx),
                    "page_index": int(page_index),
                }
            )

        visual_spans.append(
            _VisualSpan(
                text=text,
                bbox=bbox,
                font=font,
                size=size,
                flags=flags,
                render_mode=render_mode,
                is_invisible=is_invisible,
                provenance=prov,
                characters=char_records,
                page_index=page_index,
            )
        )

    # Step 2: Cluster visual spans into lines
    # Initial sort by vertical center
    visual_spans.sort(key=lambda s: (s.cy, s.x0))
    lines: List[_VisualLine] = []
    for s in visual_spans:
        matched_line: Optional[_VisualLine] = None
        for l in lines:
            if l.matches_span(s):
                matched_line = l
                break
        if matched_line is not None:
            matched_line.add_span(s)
        else:
            lines.append(_VisualLine(s))

    # Sort lines by y0 top-to-bottom and normalize spans in each line
    lines.sort(key=lambda l: (l.y0, l.x0))
    for l in lines:
        l.normalize_spans()

    # Step 3: Cluster lines into blocks
    blocks: List[_VisualBlock] = []
    for l in lines:
        if not blocks:
            blocks.append(_VisualBlock(l))
        else:
            last_block = blocks[-1]
            if last_block.matches_line(l):
                last_block.add_line(l)
            else:
                blocks.append(_VisualBlock(l))

    # Step 4: Derive words
    words_tuples, wire_words = _derive_words(blocks, page_index)

    # Step 5: Build wire DTO structures and rawdict
    wire_blocks: List[Dict[str, Any]] = []
    rawdict_blocks: List[Dict[str, Any]] = []
    flat_wire_spans: List[Dict[str, Any]] = []

    global_span_order = 0
    global_char_order = 0

    for block_idx, block in enumerate(blocks):
        wire_lines: List[Dict[str, Any]] = []
        rawdict_lines: List[Dict[str, Any]] = []

        for line_idx, line in enumerate(block.lines):
            wire_line_spans: List[Dict[str, Any]] = []
            rawdict_line_spans: List[Dict[str, Any]] = []

            for span in line.spans:
                wire_chars: List[Dict[str, Any]] = []
                rawdict_chars: List[Dict[str, Any]] = []

                for ch in span.characters:
                    c_text = ch["c"]
                    c_bbox = ch["bbox"]
                    c_obj_idx = ch["pdfium_object_index"]
                    c_char_idx = ch["char_index"]
                    c_page_idx = ch["page_index"]

                    char_raw_pos = [
                        int(c_page_idx),
                        int(c_obj_idx),
                        int(c_char_idx),
                        int(c_char_idx),
                    ]

                    wire_chars.append(
                        {
                            "schema_version": 1,
                            "text": c_text,
                            "rect": _make_rect4(c_bbox[0], c_bbox[1], c_bbox[2], c_bbox[3]),
                            "order": int(global_char_order),
                            "raw_source_position": char_raw_pos,
                        }
                    )
                    rawdict_chars.append(
                        {
                            "c": c_text,
                            "bbox": (
                                float(c_bbox[0]),
                                float(c_bbox[1]),
                                float(c_bbox[2]),
                                float(c_bbox[3]),
                            ),
                        }
                    )
                    global_char_order += 1

                first_char = span.characters[0] if span.characters else None
                last_char = span.characters[-1] if span.characters else None
                if first_char and last_char:
                    span_raw_pos = [
                        int(first_char["page_index"]),
                        int(first_char["pdfium_object_index"]),
                        int(first_char["char_index"]),
                        int(last_char["char_index"]),
                    ]
                else:
                    span_raw_pos = [
                        int(page_index),
                        int(span.provenance.get("pdfium_object_index", 0)),
                        0,
                        0,
                    ]

                span_dict = {
                    "schema_version": 1,
                    "text": span.text,
                    "rect": _make_rect4(span.x0, span.y0, span.x1, span.y1),
                    "font": span.font,
                    "size": span.size,
                    "flags": span.flags,
                    "order": int(global_span_order),
                    "characters": wire_chars,
                    "source_position": {
                        "schema_version": 1,
                        "block": int(block_idx),
                        "line": int(line_idx),
                    },
                    "raw_source_position": span_raw_pos,
                    "block": int(block_idx),
                    "line": int(line_idx),
                }

                wire_line_spans.append(span_dict)
                flat_wire_spans.append(span_dict)

                rawdict_line_spans.append(
                    {
                        "bbox": (
                            float(span.x0),
                            float(span.y0),
                            float(span.x1),
                            float(span.y1),
                        ),
                        "text": span.text,
                        "font": span.font or "",
                        "size": span.size,
                        "flags": span.flags or 0,
                        "chars": rawdict_chars,
                    }
                )

                global_span_order += 1

            wire_lines.append(
                {
                    "schema_version": 1,
                    "rect": _make_rect4(line.x0, line.y0, line.x1, line.y1),
                    "spans": wire_line_spans,
                    "order": int(line_idx),
                    "source_position": [int(block_idx), int(line_idx)],
                    "source_order": int(line_idx),
                }
            )

            rawdict_lines.append(
                {
                    "bbox": (
                        float(line.x0),
                        float(line.y0),
                        float(line.x1),
                        float(line.y1),
                    ),
                    "spans": rawdict_line_spans,
                }
            )

        wire_blocks.append(
            {
                "schema_version": 1,
                "type": 0,
                "rect": _make_rect4(block.x0, block.y0, block.x1, block.y1),
                "lines": wire_lines,
                "order": int(block_idx),
                "source_position": [int(block_idx)],
                "source_order": int(block_idx),
            }
        )

        rawdict_blocks.append(
            {
                "type": 0,
                "bbox": (
                    float(block.x0),
                    float(block.y0),
                    float(block.x1),
                    float(block.y1),
                ),
                "lines": rawdict_lines,
            }
        )

    page_snapshot: Dict[str, Any] = {
        "schema_version": 1,
        "page_index": int(page_index),
        "page": {
            "schema_version": 1,
            "width": width,
            "height": height,
            "rotation": rotation,
        },
        "text_blocks": wire_blocks,
        "spans": flat_wire_spans,
        "words": wire_words,
        "drawings": [],
        "allowed_regions": [],
        "excluded_regions": [],
        "extraction_options": {
            "schema_version": 1,
            "options": {},
        },
    }

    rawdict: Dict[str, Any] = {
        "width": width,
        "height": height,
        "blocks": rawdict_blocks,
    }

    sidecar = {
        "classification": classification,
        "raw_provenance": {
            "source_file": checked_page.get("source_file"),
            "generator": checked_page.get("generator"),
            "spans_count": len(raw_spans),
        },
    }

    return NormalizedPage(
        page_type="vector",
        page_snapshot=page_snapshot,
        rawdict=rawdict,
        words=words_tuples,
        sidecar=sidecar,
        diagnostics=dict(classification),
    )


def normalize_raw_snapshot(raw_snapshot: Mapping[str, Any]) -> List[NormalizedPage]:
    """Normalize a multi-page raw snapshot or a single raw page mapping."""
    if "pages" in raw_snapshot and isinstance(raw_snapshot["pages"], Sequence):
        return [normalize_raw_page(page) for page in raw_snapshot["pages"]]
    return [normalize_raw_page(raw_snapshot)]
