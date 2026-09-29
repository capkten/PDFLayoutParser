import sys
from pathlib import Path

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from typing import Any, Dict, List, Optional
import pytest

from fixtures_normalizer import make_raw_page, make_span
from hexai_pdf_parser import rust_adapter
from pdfium_normalizer import normalize_drawings, normalize_raw_page


def test_line_drawing_uses_rust_adapter_item_shape() -> None:
    raw = make_raw_page(
        [],
        drawings=[
            {
                "drawing_index": 0,
                "path_type": "stroked",
                "rect": [0, 0, 100, 1],
                "width": 1.0,
                "items": [{"cmd": "l", "points": [[0, 0], [100, 0]]}],
            }
        ],
    )
    drawings = normalize_drawings(raw)
    assert len(drawings) == 1
    assert drawings[0]["type"] == "s"
    assert drawings[0]["items"] == [["l", [0.0, 0.0], [100.0, 0.0]]]
    assert drawings[0]["lines"][0]["rect"] == {"x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 0.0}


def test_rect_drawing_uses_re_item_shape() -> None:
    raw = make_raw_page(
        [],
        drawings=[
            {
                "drawing_index": 0,
                "path_type": "filled",
                "rect": [10, 20, 50, 60],
                "width": 1.0,
                "items": [{"cmd": "re", "rect": [10, 20, 50, 60]}],
            }
        ],
    )
    drawings = normalize_drawings(raw)
    assert len(drawings) == 1
    assert drawings[0]["type"] == "f"
    assert drawings[0]["items"] == [["re", [10.0, 20.0, 50.0, 60.0]]]
    assert drawings[0]["lines"][0]["rect"] == {"x0": 10.0, "y0": 20.0, "x1": 50.0, "y1": 60.0}


def test_path_type_mappings() -> None:
    raw = make_raw_page(
        [],
        drawings=[
            {
                "drawing_index": 0,
                "path_type": "stroked",
                "rect": [0, 0, 10, 10],
                "items": [{"cmd": "l", "points": [[0, 0], [10, 0]]}],
            },
            {
                "drawing_index": 1,
                "path_type": "filled",
                "rect": [0, 0, 10, 10],
                "items": [{"cmd": "l", "points": [[0, 0], [10, 0]]}],
            },
            {
                "drawing_index": 2,
                "path_type": "stroked_filled",
                "rect": [0, 0, 10, 10],
                "items": [{"cmd": "l", "points": [[0, 0], [10, 0]]}],
            },
            {
                "drawing_index": 3,
                "path_type": "unknown",
                "rect": [0, 0, 10, 10],
                "items": [{"cmd": "l", "points": [[0, 0], [10, 0]]}],
            },
        ],
    )
    drawings = normalize_drawings(raw)
    assert drawings[0]["type"] == "s"
    assert drawings[1]["type"] == "f"
    assert drawings[2]["type"] == "fs"
    assert drawings[3]["type"] == "unknown"


def test_curve_cmd_goes_to_diagnostics_not_lines() -> None:
    raw = make_raw_page(
        [],
        drawings=[
            {
                "drawing_index": 0,
                "path_type": "stroked",
                "rect": [0, 0, 20, 20],
                "items": [
                    {"cmd": "c", "points": [[0, 0], [10, 20], [20, 0]]},
                ],
            }
        ],
    )
    drawings = normalize_drawings(raw)
    assert len(drawings) == 1
    assert drawings[0]["lines"] == []
    # Curve item is in items for diagnostics / PyMuPDF compat
    assert len(drawings[0]["items"]) == 1
    assert drawings[0]["items"][0][0] == "c"


def test_source_order_and_raw_source_position() -> None:
    raw = make_raw_page(
        [],
        drawings=[
            {
                "drawing_index": 5,
                "path_type": "stroked",
                "rect": [0, 0, 100, 1],
                "items": [{"cmd": "l", "points": [[0, 0], [100, 0]]}],
            }
        ],
    )
    drawings = normalize_drawings(raw)
    assert drawings[0]["source_order"] == 5
    assert drawings[0]["raw_source_position"] == [5]


def test_page_snapshot_digest_with_normalized_drawings() -> None:
    raw = make_raw_page(
        [make_span("Heading", 10, 10, 60, 20, order=0)],
        drawings=[
            {
                "drawing_index": 0,
                "path_type": "stroked",
                "rect": [10, 25, 100, 26],
                "width": 1.0,
                "items": [{"cmd": "l", "points": [[10, 25], [100, 25]]}],
            }
        ],
    )
    norm = normalize_raw_page(raw)
    assert norm.page_snapshot is not None
    assert len(norm.page_snapshot["drawings"]) == 1

    digest = rust_adapter.page_snapshot_digest(norm.page_snapshot)
    assert isinstance(digest, str)
    assert len(digest) == 64
