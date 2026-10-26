"""给定区域内被跨列分节行断开的有线网格。"""

from types import SimpleNamespace

import fitz
import pytest

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.extractors.wired_table_extractor import WiredTableExtractor
from hexai_pdf_parser.tables.table_extractor import TableExtractor


def _sectioned_page(*, closed=False, gap_text=True, second_column=150.0, header_inset=0):
    doc = fitz.open()
    page = doc.new_page(width=420, height=320)
    for y in (50, 70, 90, 110, 130, 150, 170):
        page.draw_line((50, y), (350, y))
    for top, bottom, columns in (
        (50, 70, (150, 250)),
        (90, 130, (150, 250)),
        (150, 170, (second_column, 250)),
    ):
        for x in columns:
            inset = header_inset if top == 50 else 0
            page.draw_line((x, top + inset), (x, bottom - inset))
        if closed:
            for x in (50, 350):
                page.draw_line((x, top), (x, bottom))
    for x, text in ((60, "项目"), (160, "本期"), (260, "上期")):
        page.insert_text((x, 64), text, fontsize=9, fontname="china-s")
    for y, text in ((104, "甲"), (124, "乙"), (164, "丙")):
        page.insert_text((60, y), text, fontsize=9, fontname="china-s")
        page.insert_text((160, y), "10", fontsize=9)
        if y != 124:
            page.insert_text((260, y), "20", fontsize=9)
    if gap_text:
        for y, text in ((84, "分节甲"), (144, "分节乙")):
            page.insert_text((60, y), text, fontsize=9, fontname="china-s")
    return doc, page, BBox(48, 48, 352, 172)


def _assert_occupancy(table):
    slots = []
    for cell in table.cells:
        slots.extend(
            (r, c)
            for r in range(cell.row_index, cell.row_index + cell.rowspan)
            for c in range(cell.col_index, cell.col_index + cell.colspan)
        )
    assert len(slots) == len(set(slots)) == table.rows * table.cols


def test_region_preserves_header_sections_and_empty_slots():
    doc, page, bbox = _sectioned_page()
    try:
        table = TableExtractor(use_ml_table_detector=False).extract_table_in_region(
            page, bbox, page_language="zh"
        )
        assert table is not None
        assert (table.source, table.rows, table.cols) == ("line_projection", 6, 3)
        assert len(table.cells) == 14
        assert [(c.row_index, c.col_index) for c in table.cells if not c.text] == [(3, 2)]
        assert [(c.row_index, c.colspan, c.text) for c in table.cells if c.colspan > 1] == [
            (1, 3, "分节甲"), (4, 3, "分节乙")
        ]
        assert [c.text for c in table.cells if c.row_index == 0] == ["项目", "本期", "上期"]
        _assert_occupancy(table)
    finally:
        doc.close()


def test_region_accepts_short_header_line_endpoints_without_splitting_sections():
    doc, page, bbox = _sectioned_page(header_inset=1.5)
    try:
        table = TableExtractor(use_ml_table_detector=False).extract_table_in_region(page, bbox)
        assert table is not None
        assert [c.text for c in table.cells if c.row_index == 0] == ["项目", "本期", "上期"]
        assert len(table.cells) == 14
        _assert_occupancy(table)
    finally:
        doc.close()


@pytest.mark.parametrize("kwargs", [
    {"closed": True},
    {"gap_text": False},
    {"second_column": 180},
])
def test_bounded_wired_extraction_keeps_independent_components(kwargs):
    doc, page, bbox = _sectioned_page(**kwargs)
    try:
        tables = WiredTableExtractor().extract(page, table_bbox=bbox)
        assert len(tables) == 3
        assert sorted((t.rows, t.cols) for t in tables) == [(1, 3), (1, 3), (2, 3)]
    finally:
        doc.close()


def test_full_page_line_discovery_still_returns_physical_components():
    doc, page, _ = _sectioned_page()
    try:
        assert len(WiredTableExtractor().extract(page)) == 3
    finally:
        doc.close()


def test_bounded_wired_extraction_rejects_multiple_fields_in_the_gap():
    doc, page, bbox = _sectioned_page()
    try:
        page.insert_text((260, 144), "独立表头", fontsize=9, fontname="china-s")
        assert len(WiredTableExtractor().extract(page, table_bbox=bbox)) == 3
    finally:
        doc.close()


def test_region_does_not_fill_a_truly_missing_header_separator():
    doc, page, bbox = _sectioned_page(header_inset=4)
    try:
        for x in (50, 350):
            page.draw_line((x, 50), (x, 170))
        table = TableExtractor(use_ml_table_detector=False).extract_table_in_region(page, bbox)
        assert table is not None
        header = [c for c in table.cells if c.row_index == 0]
        assert len(header) == 1 and header[0].colspan == 3
        _assert_occupancy(table)
    finally:
        doc.close()


def test_main_pipeline_uses_detected_region_to_recover_sectioned_wired_table():
    doc, page, bbox = _sectioned_page()
    try:
        extractor = TableExtractor()
        extractor._ml_detector = SimpleNamespace(detect_with_scores=lambda page: [(bbox, 0.97)])
        tables = extractor.extract(page)
        assert len(tables) == 1
        assert (tables[0].source, tables[0].rows, tables[0].cols) == ("line_projection", 6, 3)
        assert [(c.row_index, c.colspan) for c in tables[0].cells if c.colspan > 1] == [(1, 3), (4, 3)]
        _assert_occupancy(tables[0])
    finally:
        doc.close()


def test_main_pipeline_keeps_independent_closed_frames_inside_one_detection():
    doc, page, bbox = _sectioned_page(closed=True)
    try:
        extractor = TableExtractor()
        extractor._ml_detector = SimpleNamespace(detect_with_scores=lambda page: [(bbox, 0.97)])
        tables = extractor.extract(page)
        assert len(tables) == 3
        assert all(t.source == "line_projection" for t in tables)
        assert sorted((t.rows, t.cols) for t in tables) == [(1, 3), (1, 3), (2, 3)]
    finally:
        doc.close()
