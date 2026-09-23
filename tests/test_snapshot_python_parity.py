from __future__ import annotations

import fitz
import pytest

from hexai_pdf_parser.models import BBox
from hexai_pdf_parser.pdf_snapshot import capture_page_snapshot
from hexai_pdf_parser.tables.wireless_table_recovery import (
    NativeSpan,
    collect_native_spans,
    collect_native_spans_from_snapshot,
    _recover_wireless_tables_python,
    _recover_wireless_tables_from_snapshot_python,
    recover_wireless_tables,
)
from hexai_pdf_parser.tables.wireless_structure.recoverer import (
    _recover_cells_from_region_python,
    _recover_cells_from_snapshot_python,
)


class StrictSpyPage:
    """Wrapper around fitz.Page that can freeze and forbid further reads."""

    def __init__(self, page: fitz.Page):
        self._page = page
        self.locked = False
        self.calls: list[str] = []

    @property
    def rect(self):
        if self.locked:
            raise RuntimeError("Unexpected page.rect read after snapshot capture!")
        return self._page.rect

    @property
    def rotation(self):
        if self.locked:
            raise RuntimeError("Unexpected page.rotation read after snapshot capture!")
        return self._page.rotation

    @property
    def number(self):
        if self.locked:
            raise RuntimeError("Unexpected page.number read after snapshot capture!")
        return self._page.number

    def get_text(self, *args, **kwargs):
        if self.locked:
            raise RuntimeError(
                f"Unexpected page.get_text({args}, {kwargs}) read after snapshot capture!"
            )
        self.calls.append("get_text")
        return self._page.get_text(*args, **kwargs)

    def get_drawings(self, *args, **kwargs):
        if self.locked:
            raise RuntimeError(
                f"Unexpected page.get_drawings({args}, {kwargs}) read after snapshot capture!"
            )
        self.calls.append("get_drawings")
        return self._page.get_drawings(*args, **kwargs)


def _create_sample_doc():
    doc = fitz.open()
    page = doc.new_page(width=500, height=600)
    # Header & table content
    page.insert_text((50, 50), "2023年度财务数据表")
    page.insert_text((50, 100), "项目")
    page.insert_text((150, 100), "金额")
    page.insert_text((250, 100), "比例")
    page.insert_text((50, 130), "营业收入")
    page.insert_text((150, 130), "10,000.00")
    page.insert_text((250, 130), "100.0%")
    page.insert_text((50, 160), "营业成本")
    page.insert_text((150, 160), "6,000.00")
    page.insert_text((250, 160), "60.0%")
    # Footer
    page.insert_text((200, 550), "第 1 页 / 共 5 页")
    return doc, page


def test_collect_native_spans_from_snapshot_parity():
    doc, page = _create_sample_doc()
    try:
        allowed = [BBox(0, 0, 500, 400)]
        excluded = [BBox(0, 0, 500, 70)]

        # Direct page collection
        legacy_spans = collect_native_spans(
            page, allowed_regions=allowed, excluded_regions=excluded
        )

        # Snapshot collection
        snapshot = capture_page_snapshot(
            page,
            page_index=page.number,
            allowed_regions=allowed,
            excluded_regions=excluded,
        )
        snapshot_spans = collect_native_spans_from_snapshot(
            snapshot, allowed_regions=allowed, excluded_regions=excluded
        )

        assert len(snapshot_spans) == len(legacy_spans)
        for s_span, l_span in zip(snapshot_spans, legacy_spans):
            assert s_span.text == l_span.text
            assert s_span.order == l_span.order
            assert s_span.bbox.x0 == pytest.approx(l_span.bbox.x0, abs=1e-4)
            assert s_span.bbox.y0 == pytest.approx(l_span.bbox.y0, abs=1e-4)
            assert s_span.bbox.x1 == pytest.approx(l_span.bbox.x1, abs=1e-4)
            assert s_span.bbox.y1 == pytest.approx(l_span.bbox.y1, abs=1e-4)
            assert s_span.source_position == l_span.source_position
            assert len(s_span.characters) == len(l_span.characters)
            for (sc, sb), (lc, lb) in zip(s_span.characters, l_span.characters):
                assert sc == lc
                assert sb.x0 == pytest.approx(lb.x0, abs=1e-4)
                assert sb.y0 == pytest.approx(lb.y0, abs=1e-4)
                assert sb.x1 == pytest.approx(lb.x1, abs=1e-4)
                assert sb.y1 == pytest.approx(lb.y1, abs=1e-4)
    finally:
        doc.close()


def test_strict_spy_page_zero_read_during_recovery():
    doc, page = _create_sample_doc()
    try:
        spy_page = StrictSpyPage(page)
        # Capture snapshot
        snapshot = capture_page_snapshot(spy_page, page_index=page.number)
        # Now lock spy_page! Any further calls to page must fail
        spy_page.locked = True

        # Recovery from snapshot
        recovery = _recover_wireless_tables_from_snapshot_python(snapshot)
        assert len(recovery.tables) >= 1
    finally:
        doc.close()


def test_recover_cells_from_snapshot_python_parity():
    doc, page = _create_sample_doc()
    try:
        region_bbox = BBox(40, 80, 400, 200)
        rows1, cols1, cells1 = _recover_cells_from_region_python(page, region_bbox)

        snapshot = capture_page_snapshot(
            page, page_index=page.number, allowed_regions=[region_bbox]
        )
        rows2, cols2, cells2 = _recover_cells_from_snapshot_python(snapshot, region_bbox)

        assert rows1 == rows2
        assert cols1 == cols2
        assert len(cells1) == len(cells2)
        for c1, c2 in zip(cells1, cells2):
            assert c1.text == c2.text
            assert c1.row_index == c2.row_index
            assert c1.col_index == c2.col_index
            assert c1.rowspan == c2.rowspan
            assert c1.colspan == c2.colspan
    finally:
        doc.close()
