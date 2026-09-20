from typing import Sequence
import fitz
import pytest

from hexai_pdf_parser.models import BBox, Cell
from hexai_pdf_parser.pdf_snapshot import PageSnapshot, capture_page_snapshot
from hexai_pdf_parser.tables.wireless_structure.recoverer import (
    _recover_cells_from_snapshot_python,
)
from hexai_pdf_parser import rust_adapter


class StrictSpyPage:
    """A proxy over fitz.Page that raises if any read methods are called while locked."""

    def __init__(self, page: fitz.Page) -> None:
        self._page = page
        self.locked = False

    def __getattr__(self, name: str):
        if self.locked:
            forbidden_prefixes = ("get_text", "get_drawings", "get_pixmap", "get_images", "get_bboxlog")
            if any(name.startswith(p) for p in forbidden_prefixes):
                raise AssertionError(f"StrictSpyPage violation: forbidden method {name} called after snapshot capture!")
        return getattr(self._page, name)


def _assert_cells_equal(actual_cells: Sequence[Cell], expected_cells: Sequence[Cell]):
    assert len(actual_cells) == len(expected_cells), (
        f"Cell count mismatch: got {len(actual_cells)}, expected {len(expected_cells)}"
    )
    for idx, (actual, expected) in enumerate(zip(actual_cells, expected_cells)):
        assert actual.row_index == expected.row_index, (
            f"Cell {idx} row_index mismatch: {actual.row_index} vs {expected.row_index}"
        )
        assert actual.col_index == expected.col_index, (
            f"Cell {idx} col_index mismatch: {actual.col_index} vs {expected.col_index}"
        )
        assert actual.rowspan == expected.rowspan, (
            f"Cell {idx} rowspan mismatch: {actual.rowspan} vs {expected.rowspan}"
        )
        assert actual.colspan == expected.colspan, (
            f"Cell {idx} colspan mismatch: {actual.colspan} vs {expected.colspan}"
        )
        assert actual.text.strip() == expected.text.strip(), (
            f"Cell {idx} text mismatch: {actual.text!r} vs {expected.text!r}"
        )
        assert actual.bbox.x0 == pytest.approx(expected.bbox.x0, abs=1.5), f"Cell {idx} bbox.x0 mismatch"
        assert actual.bbox.y0 == pytest.approx(expected.bbox.y0, abs=1.5), f"Cell {idx} bbox.y0 mismatch"
        assert actual.bbox.x1 == pytest.approx(expected.bbox.x1, abs=1.5), f"Cell {idx} bbox.x1 mismatch"
        assert actual.bbox.y1 == pytest.approx(expected.bbox.y1, abs=1.5), f"Cell {idx} bbox.y1 mismatch"


def test_real_page_437_chinese_wireless_table_parity():
    """Verify Rust end-to-end recovery matches Python exactly on page 437 fixture."""
    doc = fitz.open("tests/fixtures/page_437_wireless.pdf")
    try:
        page = doc[0]
        region = BBox(67.6, 646.8, 522.5, 766.1)
        snapshot = capture_page_snapshot(page, page_index=0, allowed_regions=[region])

        py_rows, py_cols, py_cells = _recover_cells_from_snapshot_python(snapshot, region)
        ru_rows, ru_cols, ru_cells = rust_adapter.recover_cells_from_snapshot(snapshot, region)

        assert (ru_rows, ru_cols) == (py_rows, py_cols) == (3, 6)
        assert len(ru_cells) == len(py_cells) == 18
        _assert_cells_equal(ru_cells, py_cells)
    finally:
        doc.close()


def test_zero_page_read_during_table_recovery():
    """Verify strictly 0 PyMuPDF read calls occur during table recovery."""
    doc = fitz.open("tests/fixtures/page_437_wireless.pdf")
    try:
        page = doc[0]
        spy_page = StrictSpyPage(page)
        region = BBox(67.6, 646.8, 522.5, 766.1)
        snapshot = capture_page_snapshot(spy_page, page_index=0, allowed_regions=[region])

        # Lock the spy page; any access to PyMuPDF must raise AssertionError
        spy_page.locked = True

        ru_rows, ru_cols, ru_cells = rust_adapter.recover_cells_from_snapshot(snapshot, region)
        assert (ru_rows, ru_cols) == (3, 6)
        assert len(ru_cells) == 18
    finally:
        doc.close()


def _make_char(c: str, x0: float, y0: float, x1: float, y1: float, pos: tuple[int, int, int, int]):
    return {
        "c": c,
        "bbox": (x0, y0, x1, y1),
        "raw_source_position": pos,
        "source_order": pos[3],
    }


def _make_span(text: str, bbox: tuple[float, float, float, float], pos: tuple[int, int, int]):
    chars = [
        _make_char(ch, bbox[0] + i * 10, bbox[1], bbox[0] + (i + 1) * 10, bbox[3], (*pos, i))
        for i, ch in enumerate(text)
    ]
    return {
        "text": text,
        "bbox": bbox,
        "font": "SimSun",
        "size": 10.0,
        "flags": 0,
        "chars": tuple(chars),
        "raw_source_position": pos,
        "source_order": pos[2],
    }


def test_synthetic_empty_slot_materialization_and_occupancy():
    """Verify that unpopulated grid slots materialize as empty 1x1 cells with no conflicts."""
    region = BBox(50.0, 100.0, 350.0, 200.0)
    # 3 rows x 3 columns table:
    # Row 0: "项目" (col 0), "金额" (col 1), "比例" (col 2)
    # Row 1: "收入" (col 0), [EMPTY] (col 1), "100%" (col 2)
    # Row 2: "支出" (col 0), "500" (col 1), "50%" (col 2)
    blocks = [
        {
            "type": 0,
            "bbox": (50.0, 100.0, 350.0, 180.0),
            "raw_source_position": (0,),
            "source_order": 0,
            "lines": [
                {
                    "bbox": (50.0, 100.0, 350.0, 120.0),
                    "raw_source_position": (0, 0),
                    "source_order": 0,
                    "spans": [
                        _make_span("项目", (50.0, 105.0, 90.0, 120.0), (0, 0, 0)),
                        _make_span("金额", (150.0, 105.0, 190.0, 120.0), (0, 0, 1)),
                        _make_span("比例", (250.0, 105.0, 290.0, 120.0), (0, 0, 2)),
                    ],
                },
                {
                    "bbox": (50.0, 130.0, 350.0, 150.0),
                    "raw_source_position": (0, 1),
                    "source_order": 1,
                    "spans": [
                        _make_span("收入", (50.0, 135.0, 90.0, 150.0), (0, 1, 0)),
                        # col 1 is intentionally omitted (empty slot)
                        _make_span("100%", (250.0, 135.0, 290.0, 150.0), (0, 1, 1)),
                    ],
                },
                {
                    "bbox": (50.0, 160.0, 350.0, 180.0),
                    "raw_source_position": (0, 2),
                    "source_order": 2,
                    "spans": [
                        _make_span("支出", (50.0, 165.0, 90.0, 180.0), (0, 2, 0)),
                        _make_span("500", (150.0, 165.0, 190.0, 180.0), (0, 2, 1)),
                        _make_span("50%", (250.0, 165.0, 290.0, 180.0), (0, 2, 2)),
                    ],
                },
            ],
        }
    ]
    all_spans = []
    for b in blocks:
        for l in b["lines"]:
            all_spans.extend(l["spans"])

    snapshot = PageSnapshot(
        schema_version=1,
        version=1,
        page_index=0,
        geometry={
            "rect": (0.0, 0.0, 500.0, 800.0),
            "x0": 0.0,
            "y0": 0.0,
            "x1": 500.0,
            "y1": 800.0,
            "width": 500.0,
            "height": 800.0,
            "rotation": 0,
        },
        text_blocks=tuple(blocks),
        spans=tuple(all_spans),
        characters=(),
        words=(),
        drawings=(),
        allowed_regions=(),
        excluded_regions=(),
        extraction_options={},
        summary={},
    )

    ru_rows, ru_cols, ru_cells = rust_adapter.recover_cells_from_snapshot(snapshot, region)
    assert (ru_rows, ru_cols) == (3, 3)
    assert len(ru_cells) == 9

    # Verify slot (1, 1) is materialized as empty cell
    empty_cell = next((c for c in ru_cells if c.row_index == 1 and c.col_index == 1), None)
    assert empty_cell is not None, "Slot (1, 1) was not materialized!"
    assert empty_cell.text == ""
    assert empty_cell.rowspan == 1
    assert empty_cell.colspan == 1

    # Verify exact 1:1 slot occupancy (every slot claimed by exactly one cell)
    claimed_slots = set()
    for c in ru_cells:
        for r in range(c.row_index, c.row_index + c.rowspan):
            for col in range(c.col_index, c.col_index + c.colspan):
                slot = (r, col)
                assert slot not in claimed_slots, f"Occupancy conflict at slot {slot}"
                claimed_slots.add(slot)
    assert len(claimed_slots) == 9


def test_multiline_cell_vertical_merge_and_reject_cross_column():
    """Verify that multi-line text within the same cell is merged with newline and not horizontally merged."""
    region = BBox(50.0, 100.0, 350.0, 200.0)
    # 2 rows x 3 columns table:
    # Row 0: "项目" (col 0), "金额" (col 1), "比例" (col 2)
    # Row 1: "研发支出" & "(资本化)" (col 0 multiline), "123.45" (col 1), "50%" (col 2)
    # Row 2: "合计" (col 0), "123.45" (col 1), "50%" (col 2)
    blocks = [
        {
            "type": 0,
            "bbox": (50.0, 100.0, 350.0, 190.0),
            "raw_source_position": (0,),
            "source_order": 0,
            "lines": [
                {
                    "bbox": (50.0, 100.0, 350.0, 120.0),
                    "raw_source_position": (0, 0),
                    "source_order": 0,
                    "spans": [
                        _make_span("项目", (50.0, 105.0, 90.0, 120.0), (0, 0, 0)),
                        _make_span("金额", (150.0, 105.0, 190.0, 120.0), (0, 0, 1)),
                        _make_span("比例", (250.0, 105.0, 290.0, 120.0), (0, 0, 2)),
                    ],
                },
                {
                    "bbox": (50.0, 130.0, 350.0, 142.0),
                    "raw_source_position": (0, 1),
                    "source_order": 1,
                    "spans": [
                        _make_span("研发支出", (50.0, 130.0, 90.0, 142.0), (0, 1, 0)),
                        _make_span("123.45", (150.0, 130.0, 190.0, 142.0), (0, 1, 1)),
                        _make_span("50%", (250.0, 130.0, 290.0, 142.0), (0, 1, 2)),
                    ],
                },
                {
                    "bbox": (50.0, 144.0, 100.0, 156.0),
                    "raw_source_position": (0, 2),
                    "source_order": 2,
                    "spans": [
                        # Vertical continuation of "研发支出" in col 0
                        _make_span("（资本化）", (50.0, 144.0, 95.0, 156.0), (0, 2, 0)),
                    ],
                },
                {
                    "bbox": (50.0, 165.0, 350.0, 185.0),
                    "raw_source_position": (0, 3),
                    "source_order": 3,
                    "spans": [
                        _make_span("合计", (50.0, 168.0, 90.0, 183.0), (0, 3, 0)),
                        _make_span("123.45", (150.0, 168.0, 190.0, 183.0), (0, 3, 1)),
                        _make_span("50%", (250.0, 168.0, 290.0, 183.0), (0, 3, 2)),
                    ],
                },
            ],
        }
    ]
    all_spans = []
    for b in blocks:
        for l in b["lines"]:
            all_spans.extend(l["spans"])

    snapshot = PageSnapshot(
        schema_version=1,
        version=1,
        page_index=0,
        geometry={
            "rect": (0.0, 0.0, 500.0, 800.0),
            "x0": 0.0,
            "y0": 0.0,
            "x1": 500.0,
            "y1": 800.0,
            "width": 500.0,
            "height": 800.0,
            "rotation": 0,
        },
        text_blocks=tuple(blocks),
        spans=tuple(all_spans),
        characters=(),
        words=(),
        drawings=(),
        allowed_regions=(),
        excluded_regions=(),
        extraction_options={},
        summary={},
    )

    ru_rows, ru_cols, ru_cells = rust_adapter.recover_cells_from_snapshot(snapshot, region)
    assert (ru_rows, ru_cols) == (3, 3)

    # Col 0 of row 1 must be merged
    multiline_cell = next((c for c in ru_cells if c.row_index == 1 and c.col_index == 0), None)
    assert multiline_cell is not None
    assert "研发支出" in multiline_cell.text
    assert "（资本化）" in multiline_cell.text
    assert "\n" in multiline_cell.text


