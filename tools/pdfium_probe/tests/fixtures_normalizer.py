"""Test fixtures and helpers for PDFium normalizer tests."""

from typing import Any, Dict, Iterable, List, Optional


def make_span(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    order: int = 0,
    font: str = "TestFont",
    size: float = 10.0,
    flags: Optional[int] = None,
) -> Dict[str, Any]:
    chars = [
        {
            "c": char,
            "bbox": [float(x0), float(y0), float(x1), float(y1)],
            "char_index": index,
        }
        for index, char in enumerate(text)
    ]
    return {
        "order": order,
        "text": text,
        "bbox": [float(x0), float(y0), float(x1), float(y1)],
        "font": font,
        "size": size,
        "flags": flags,
        "render_mode": 0,
        "is_invisible": False,
        "provenance": {
            "pdfium_object_index": order,
            "char_start_index": 0,
            "char_end_index": len(text),
        },
        "characters": chars,
    }


def make_raw_page(spans: Iterable[Dict[str, Any]], drawings: Iterable[Any] = ()) -> Dict[str, Any]:
    span_list = list(spans)
    visible_text = "".join(item["text"] for item in span_list)
    return {
        "schema_version": "pdfium_raw_page_v1.0",
        "page_index": 0,
        "width": 100.0,
        "height": 100.0,
        "rotation": 0,
        "crop_box": [0.0, 0.0, 100.0, 100.0],
        "media_box": [0.0, 0.0, 100.0, 100.0],
        "has_invisible_text": False,
        "spans": span_list,
        "drawings": list(drawings),
        "mapping_diagnostics": {
            "visible_text_scalar_count": len(visible_text),
            "extracted_char_scalar_count": sum(len(item.get("characters", [])) for item in span_list),
            "replacement_char_count": visible_text.count("\ufffd"),
            "control_char_count": 0,
            "mapping_status": "valid",
            "classification_reason": None,
        },
    }
