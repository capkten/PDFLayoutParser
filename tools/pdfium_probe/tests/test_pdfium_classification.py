"""Tests for PDFium raw page classification and Unicode mapping gate."""

import math
from typing import Any, Dict, List, Mapping, Optional

import pytest

from pdfium_classification import classify_raw_page, is_vector_page


def raw_page_with_text(text: str) -> Dict[str, Any]:
    characters = [
        {"c": char, "bbox": [0.0, 0.0, 1.0, 1.0], "char_index": index}
        for index, char in enumerate(text)
    ]
    return {
        "page_index": 0,
        "width": 100.0,
        "height": 100.0,
        "rotation": 0,
        "spans": [
            {
                "order": 0,
                "text": text,
                "bbox": [0.0, 0.0, 10.0, 10.0],
                "characters": characters,
            }
        ],
        "drawings": [],
        "mapping_diagnostics": {
            "visible_text_scalar_count": len(text),
            "extracted_char_scalar_count": len(characters),
            "replacement_char_count": text.count("\ufffd"),
            "control_char_count": sum(
                1
                for c in text
                if (ord(c) < 32 and c not in ("\n", "\r", "\t"))
                or (0x7F <= ord(c) <= 0x9F)
                or ord(c) == 0
            ),
            "mapping_status": "valid",
            "classification_reason": None,
        },
    }


def test_replacement_character_is_scanned() -> None:
    result = classify_raw_page(raw_page_with_text("正常\ufffd文本"))
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_unicode"
    assert result["mapping_status"] == "invalid"
    assert "evidence" in result


def test_visible_text_missing_from_characters_is_scanned() -> None:
    page = raw_page_with_text("中文")
    page["spans"][0]["characters"] = [{"c": "中", "bbox": [0.0, 0.0, 1.0, 1.0], "char_index": 0}]
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_unicode_mapping"
    assert result["mapping_status"] == "invalid"


def test_clean_page_is_vector() -> None:
    result = classify_raw_page(raw_page_with_text("Hello"))
    assert result["page_type"] == "vector"
    assert result["reason"] is None
    assert result["mapping_status"] == "valid"
    assert "evidence" in result
    assert is_vector_page(result) is True


def test_unknown_mapping_fails_closed_as_scanned() -> None:
    page = raw_page_with_text("Hello")
    page.pop("mapping_diagnostics")
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "unknown_unicode_mapping"
    assert result["mapping_status"] == "unknown"
    assert is_vector_page(result) is False


def test_empty_text_fails_closed_as_scanned() -> None:
    result = classify_raw_page(raw_page_with_text(""))
    assert result["page_type"] == "scanned"
    assert result["reason"] == "empty_text"
    assert is_vector_page(result) is False


def test_whitespace_only_text_fails_closed_as_empty_text() -> None:
    result = classify_raw_page(raw_page_with_text("   \n\t  \r\n"))
    assert result["page_type"] == "scanned"
    assert result["reason"] == "empty_text"
    assert is_vector_page(result) is False


def test_no_spans_fails_closed_as_empty_text() -> None:
    page = raw_page_with_text("A")
    page["spans"] = []
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "empty_text"
    assert is_vector_page(result) is False


def test_invalid_character_bbox_fails_closed_as_scanned() -> None:
    page = raw_page_with_text("A")
    page["spans"][0]["characters"][0]["bbox"] = [2.0, 0.0, 1.0, 1.0]
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_geometry"
    assert result["mapping_status"] == "invalid"
    assert is_vector_page(result) is False


def test_inverted_y_bbox_is_invalid_geometry() -> None:
    page = raw_page_with_text("A")
    page["spans"][0]["characters"][0]["bbox"] = [0.0, 10.0, 5.0, 2.0]
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_geometry"
    assert result["mapping_status"] == "invalid"


def test_nan_or_inf_bbox_is_invalid_geometry() -> None:
    page = raw_page_with_text("A")
    page["spans"][0]["characters"][0]["bbox"] = [float("nan"), 0.0, 5.0, 10.0]
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_geometry"

    page["spans"][0]["characters"][0]["bbox"] = [0.0, 0.0, float("inf"), 10.0]
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_geometry"


def test_missing_character_bbox_is_invalid_geometry() -> None:
    page = raw_page_with_text("A")
    del page["spans"][0]["characters"][0]["bbox"]
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_geometry"


def test_control_character_is_scanned() -> None:
    page = raw_page_with_text("Hello\x00World")
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_unicode"
    assert result["mapping_status"] == "invalid"

    page2 = raw_page_with_text("Hello\x07World")
    result2 = classify_raw_page(page2)
    assert result2["page_type"] == "scanned"
    assert result2["reason"] == "invalid_unicode"


def test_legal_whitespace_controls_allowed() -> None:
    result = classify_raw_page(raw_page_with_text("Hello\tWorld\nLine2\r\nLine3"))
    assert result["page_type"] == "vector"
    assert result["mapping_status"] == "valid"
    assert is_vector_page(result) is True


def test_char_text_content_mismatch_even_if_lengths_match() -> None:
    page = raw_page_with_text("AB")
    page["spans"][0]["characters"][1]["c"] = "C"
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "invalid_unicode_mapping"
    assert result["mapping_status"] == "invalid"


def test_explicit_unknown_mapping_status_fails_closed() -> None:
    page = raw_page_with_text("Hello")
    page["mapping_diagnostics"]["mapping_status"] = "unknown"
    result = classify_raw_page(page)
    assert result["page_type"] == "scanned"
    assert result["reason"] == "unknown_unicode_mapping"
    assert result["mapping_status"] == "unknown"


def test_precedence_order_enforced() -> None:
    # 1. empty text vs invalid unicode: empty text comes first
    page_empty_with_fffd = raw_page_with_text("")
    page_empty_with_fffd["mapping_diagnostics"]["replacement_char_count"] = 1
    result1 = classify_raw_page(page_empty_with_fffd)
    assert result1["reason"] == "empty_text"

    # 2. invalid unicode vs invalid mapping: invalid unicode comes first
    page_unicode_and_mismatch = raw_page_with_text("A\ufffdB")
    page_unicode_and_mismatch["spans"][0]["characters"] = [{"c": "A", "bbox": [0, 0, 1, 1], "char_index": 0}]
    result2 = classify_raw_page(page_unicode_and_mismatch)
    assert result2["reason"] == "invalid_unicode"

    # 3. invalid mapping vs invalid geometry: invalid mapping comes first
    page_mismatch_and_geom = raw_page_with_text("AB")
    page_mismatch_and_geom["spans"][0]["characters"] = [
        {"c": "A", "bbox": [5.0, 0.0, 1.0, 1.0], "char_index": 0}  # inverted bbox
    ]
    result3 = classify_raw_page(page_mismatch_and_geom)
    assert result3["reason"] == "invalid_unicode_mapping"

    # 4. invalid geometry vs unknown mapping: invalid geometry comes first
    page_geom_no_diag = raw_page_with_text("A")
    page_geom_no_diag["spans"][0]["characters"][0]["bbox"] = [5.0, 0.0, 1.0, 1.0]
    page_geom_no_diag.pop("mapping_diagnostics")
    result4 = classify_raw_page(page_geom_no_diag)
    assert result4["reason"] == "invalid_geometry"


def test_is_vector_page_matrix() -> None:
    assert is_vector_page({"page_type": "vector", "mapping_status": "valid"}) is True
    assert is_vector_page({"page_type": "vector", "mapping_status": "invalid"}) is False
    assert is_vector_page({"page_type": "vector", "mapping_status": "unknown"}) is False
    assert is_vector_page({"page_type": "scanned", "mapping_status": "valid"}) is False
    assert is_vector_page({"page_type": "scanned", "mapping_status": "invalid"}) is False
    assert is_vector_page({"page_type": "scanned", "mapping_status": "unknown"}) is False
    assert is_vector_page({}) is False


def test_old_raw_file_without_diagnostics_fails_closed() -> None:
    import json
    from pathlib import Path

    old_file = Path("tools/pdfium_probe/test_data/pdfium_output/synth_crop_offset_pdfium.json")
    if old_file.exists():
        with open(old_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for page in data.get("pages", []):
            if "mapping_diagnostics" not in page:
                result = classify_raw_page(page)
                assert result["page_type"] == "scanned"
                assert result["reason"] == "unknown_unicode_mapping"
                assert result["mapping_status"] == "unknown"
                assert is_vector_page(result) is False

