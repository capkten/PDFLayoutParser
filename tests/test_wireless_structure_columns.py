from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.columns import (
    assign_column,
    infer_column_bands,
)


def _atom(text, x0, y0, x1=None):
    return {
        "text": text,
        "bbox": [x0, y0, x1 if x1 is not None else x0 + 10, y0 + 8],
        "font_size": 10,
    }


def test_infer_column_bands_uses_repeated_overlapping_x_tracks():
    atoms = [
        _atom("项目一", 10, 10, 35),
        _atom("项目二", 10, 30, 35),
        _atom("100", 100, 10, 120),
        _atom("200", 100, 30, 120),
    ]

    bands = infer_column_bands(atoms, BBox(0, 0, 200, 60))

    assert [(band["x0"], band["x1"]) for band in bands] == [(10, 35), (100, 120)]
    assert assign_column(_atom("150", 102, 50, 118), bands) == bands[1]["id"]


def test_wide_spanning_header_does_not_bridge_body_columns():
    atoms = [
        _atom("项目", 10, 10, 35),
        _atom("项目", 10, 30, 35),
        _atom("金额", 100, 10, 120),
        _atom("金额", 100, 30, 120),
        _atom("合计", 40, 20, 180),
    ]

    bands = infer_column_bands(atoms, BBox(0, 0, 200, 60))

    assert len(bands) == 2
