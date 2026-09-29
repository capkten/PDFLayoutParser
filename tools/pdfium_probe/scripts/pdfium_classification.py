"""PDFium raw page classification and Unicode mapping gate.

Precedence order:
1. 无可见文本 -> empty_text
2. 替换或控制字符 -> invalid_unicode
3. 文本和字符序列不一致 -> invalid_unicode_mapping
4. 非有限、倒置或缺失字符 bbox -> invalid_geometry
5. 缺少 mapping_diagnostics 或状态为 unknown -> unknown_unicode_mapping
6. 其余 -> vector/valid
"""

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _is_illegal_control_char(c: str) -> bool:
    """Return whether character is an illegal control character (C0/C1 excluding whitespace)."""
    code = ord(c)
    if code < 32:
        return c not in ("\n", "\r", "\t")
    if 0x7F <= code <= 0x9F:
        return True
    return code == 0


def _is_valid_bbox(bbox: Any) -> bool:
    """Check if bbox is a 4-element finite sequence with x0 <= x1 and y0 <= y1."""
    if not isinstance(bbox, (list, tuple)):
        return False
    if len(bbox) != 4:
        return False
    for val in bbox:
        if not isinstance(val, (int, float)):
            return False
        if not math.isfinite(val):
            return False
    x0, y0, x1, y1 = bbox
    if x0 > x1 or y0 > y1:
        return False
    return True


def classify_raw_page(raw_page: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify a PDFium raw page before normalization and table recovery.

    Returns a dict with keys:
    - page_type: 'vector' or 'scanned'
    - reason: failure reason string or None
    - mapping_status: 'valid', 'invalid', or 'unknown'
    - evidence: dict of metrics and evidence for the classification
    """
    spans = raw_page.get("spans") or []
    mapping_diag = raw_page.get("mapping_diagnostics")

    # 1. 无可见文本 -> empty_text
    all_text = "".join(span.get("text", "") for span in spans if isinstance(span, Mapping))
    clean_text = all_text.strip()
    diag_visible_scalars = (
        mapping_diag.get("visible_text_scalar_count", 0)
        if isinstance(mapping_diag, Mapping)
        else 0
    )

    if not spans or (not clean_text and diag_visible_scalars == 0) or not clean_text:
        diag_status = (
            mapping_diag.get("mapping_status", "valid")
            if isinstance(mapping_diag, Mapping)
            else "unknown"
        )
        return {
            "page_type": "scanned",
            "reason": "empty_text",
            "mapping_status": diag_status if diag_status == "valid" else "unknown",
            "evidence": {
                "visible_text_scalar_count": diag_visible_scalars,
                "text_length": len(all_text),
                "clean_text_length": len(clean_text),
                "span_count": len(spans),
            },
        }

    # 2. 替换或控制字符 -> invalid_unicode
    replacement_count = 0
    control_count = 0

    if isinstance(mapping_diag, Mapping):
        replacement_count = mapping_diag.get("replacement_char_count", 0)
        control_count = mapping_diag.get("control_char_count", 0)
        if mapping_diag.get("classification_reason") == "invalid_unicode":
            replacement_count = max(replacement_count, 1)

    # Inspect span texts and characters directly
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        text = span.get("text", "")
        for ch in text:
            if ch == "\ufffd":
                replacement_count += 1
            elif _is_illegal_control_char(ch):
                control_count += 1

        for c_info in span.get("characters", []):
            if isinstance(c_info, Mapping):
                c_str = c_info.get("c", "")
                for ch in c_str:
                    if ch == "\ufffd":
                        replacement_count += 1
                    elif _is_illegal_control_char(ch):
                        control_count += 1

    if replacement_count > 0 or control_count > 0:
        return {
            "page_type": "scanned",
            "reason": "invalid_unicode",
            "mapping_status": "invalid",
            "evidence": {
                "replacement_char_count": replacement_count,
                "control_char_count": control_count,
            },
        }

    # 3. 文本和字符序列不一致 -> invalid_unicode_mapping
    has_mapping_mismatch = False
    mismatch_evidence: Dict[str, Any] = {}

    if isinstance(mapping_diag, Mapping):
        v_count = mapping_diag.get("visible_text_scalar_count")
        e_count = mapping_diag.get("extracted_char_scalar_count")
        s_count = mapping_diag.get("synthetic_space_count", 0)
        if v_count is not None and e_count is not None and v_count != (e_count + s_count):
            has_mapping_mismatch = True
            mismatch_evidence["visible_text_scalar_count"] = v_count
            mismatch_evidence["extracted_char_scalar_count"] = e_count
            mismatch_evidence["synthetic_space_count"] = s_count
        if mapping_diag.get("classification_reason") == "invalid_unicode_mapping":
            has_mapping_mismatch = True

    for span in spans:
        if not isinstance(span, Mapping):
            continue
        text = span.get("text", "")
        chars = span.get("characters", [])
        char_text = "".join(
            c_info.get("c", "") for c_info in chars if isinstance(c_info, Mapping)
        )
        if char_text == text or char_text == text.rstrip(" "):
            continue
        has_mapping_mismatch = True
        mismatch_evidence["span_order"] = span.get("order")
        mismatch_evidence["expected_text"] = text
        mismatch_evidence["extracted_char_text"] = char_text
        mismatch_evidence["text_length"] = len(text)
        mismatch_evidence["char_count"] = len(chars)
        break

    if has_mapping_mismatch:
        return {
            "page_type": "scanned",
            "reason": "invalid_unicode_mapping",
            "mapping_status": "invalid",
            "evidence": mismatch_evidence,
        }

    # 4. 非有限、倒置或缺失字符 bbox -> invalid_geometry
    has_geom_error = False
    geom_evidence: Dict[str, Any] = {}

    if isinstance(mapping_diag, Mapping):
        if mapping_diag.get("classification_reason") == "invalid_geometry":
            has_geom_error = True

    for span in spans:
        if not isinstance(span, Mapping):
            continue
        span_bbox = span.get("bbox")
        if span_bbox is not None and not _is_valid_bbox(span_bbox):
            has_geom_error = True
            geom_evidence["invalid_span_bbox"] = span_bbox
            geom_evidence["span_order"] = span.get("order")
            break

        chars = span.get("characters", [])
        for ch_idx, ch in enumerate(chars):
            if not isinstance(ch, Mapping):
                has_geom_error = True
                geom_evidence["non_mapping_character"] = ch_idx
                break
            if "bbox" not in ch:
                has_geom_error = True
                geom_evidence["missing_bbox_character"] = ch_idx
                break
            c_bbox = ch.get("bbox")
            if not _is_valid_bbox(c_bbox):
                has_geom_error = True
                geom_evidence["invalid_character_bbox"] = c_bbox
                geom_evidence["char_index"] = ch.get("char_index", ch_idx)
                break
        if has_geom_error:
            break

    if has_geom_error:
        return {
            "page_type": "scanned",
            "reason": "invalid_geometry",
            "mapping_status": "invalid",
            "evidence": geom_evidence,
        }

    # 5. 缺少 mapping_diagnostics 或状态为 unknown -> unknown_unicode_mapping
    if (
        mapping_diag is None
        or not isinstance(mapping_diag, Mapping)
        or mapping_diag.get("mapping_status") == "unknown"
        or mapping_diag.get("mapping_status") not in ("valid", "invalid", "empty")
    ):
        return {
            "page_type": "scanned",
            "reason": "unknown_unicode_mapping",
            "mapping_status": "unknown",
            "evidence": {
                "has_mapping_diagnostics": mapping_diag is not None,
                "mapping_diagnostics": mapping_diag,
            },
        }

    # Extra gate: if mapping diagnostics explicitly marked invalid
    if mapping_diag.get("mapping_status") == "invalid":
        return {
            "page_type": "scanned",
            "reason": mapping_diag.get("classification_reason") or "invalid_unicode_mapping",
            "mapping_status": "invalid",
            "evidence": {"diagnostics": mapping_diag},
        }

    # 6. 其余 -> vector/valid
    return {
        "page_type": "vector",
        "reason": None,
        "mapping_status": "valid",
        "evidence": {
            "visible_text_scalar_count": mapping_diag.get("visible_text_scalar_count", len(all_text)),
            "extracted_char_scalar_count": mapping_diag.get("extracted_char_scalar_count", len(all_text)),
            "span_count": len(spans),
        },
    }


def is_vector_page(classification: Mapping[str, Any]) -> bool:
    """Return True only if page_type == 'vector' and mapping_status == 'valid'."""
    return (
        classification.get("page_type") == "vector"
        and classification.get("mapping_status") == "valid"
    )
