from __future__ import annotations

import hashlib
import importlib
import json
import math

import fitz
import pytest


def _api():
    return importlib.import_module("hexai_pdf_parser.pdf_snapshot")


def _page_and_doc():
    document = fitz.open()
    page = document.new_page(width=220, height=140)
    page.set_rotation(90)
    page.insert_text((10, 20), " A  B ")
    page.draw_line((10, 30), (100, 30), color=(1, 0, 0), width=1)
    page.draw_rect(
        fitz.Rect(20, 40, 80, 70),
        color=(0, 1, 0),
        fill=(0.5, 0.5, 0.5),
        width=2,
        fill_opacity=0.4,
        stroke_opacity=0.7,
    )
    return page, document


class RecordingPage:
    def __init__(self, page):
        self._page = page
        self.calls = []
        self.property_reads = []

    @property
    def rect(self):
        self.property_reads.append("rect")
        return self._page.rect

    @property
    def rotation(self):
        self.property_reads.append("rotation")
        return self._page.rotation

    @property
    def number(self):
        self.property_reads.append("number")
        return self._page.number

    def get_text(self, *args, **kwargs):
        self.calls.append(("get_text", args, kwargs))
        return self._page.get_text(*args, **kwargs)

    def get_drawings(self, *args, **kwargs):
        self.calls.append(("get_drawings", args, kwargs))
        return self._page.get_drawings(*args, **kwargs)


def _capture(
    recording_page,
    *,
    allowed_regions=(),
    excluded_regions=(),
    ml_render_dpi=72,
):
    api = _api()
    return api.capture_page_snapshot(
        recording_page,
        page_index=3,
        allowed_regions=allowed_regions,
        excluded_regions=excluded_regions,
        ml_render_dpi=ml_render_dpi,
    )


def test_snapshot_preserves_source_order_and_character_boxes():
    page, document = _page_and_doc()
    recording_page = RecordingPage(page)
    try:
        snapshot = _capture(recording_page)
        assert [call[0] for call in recording_page.calls].count("get_text") == 10
        assert [call[0] for call in recording_page.calls].count("get_drawings") == 2
        assert recording_page.calls[0][1:] == (("rawdict",), {})
        assert recording_page.calls[1][1:] == (("rawdict",), {"flags": fitz.TEXT_PRESERVE_WHITESPACE})
        assert recording_page.calls[2][1:] == (("dict",), {})
        assert recording_page.calls[3][1:] == (("dict",), {"flags": fitz.TEXT_PRESERVE_WHITESPACE})
        assert recording_page.property_reads.count("rect") == 1
        assert recording_page.property_reads.count("rotation") == 1
        assert recording_page.property_reads.count("number") == 1

        assert snapshot.page_index == 3
        assert snapshot.geometry["rotation"] == 90
        assert snapshot.spans[0]["raw_source_position"] == (0, 0, 0)
        assert snapshot.spans[0]["source_order"] == 0
        assert snapshot.spans[0]["text"] == " A  B "
        assert snapshot.characters[0]["raw_source_position"] == (0, 0, 0, 0)
        assert snapshot.characters[0]["c"] == " "
        assert snapshot.characters[0]["bbox"]
        assert [word["source_order"] for word in snapshot.words] == [0, 1]
        assert snapshot.words[0]["raw_source_position"] == (0, 0, 0)
    finally:
        document.close()


def test_snapshot_keeps_whitespace_and_empty_span_evidence_until_shared_filtering():
    page, document = _page_and_doc()

    class EmptySpanPage(RecordingPage):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                result["blocks"][0]["lines"][0]["spans"].append(
                    {
                        "bbox": [40.0, 8.0, 40.0, 20.0],
                        "font": "",
                        "size": 0.0,
                        "flags": 0,
                        "color": 0,
                        "chars": [],
                    }
                )
            return result

    try:
        recording_page = EmptySpanPage(page)
        snapshot = _capture(recording_page)
        empty_span = next(span for span in snapshot.spans if span["text"] == "")
        assert empty_span["raw_source_position"] == (0, 0, 1)
        assert any(character["c"].isspace() for character in snapshot.characters)

        api = _api()
        filtered = api.filter_snapshot_evidence(
            snapshot,
            allowed_regions=(fitz.Rect(0, 0, 60, 100),),
            excluded_regions=(fitz.Rect(0, 0, 5, 5),),
        )
        assert all("filtered_order" in span for span in filtered.spans)
        assert [span["filtered_order"] for span in filtered.spans] == list(
            range(len(filtered.spans))
        )
        assert all("raw_source_position" in span for span in filtered.spans)
        assert all("filtered_order" not in span for span in snapshot.spans)
    finally:
        document.close()


def test_snapshot_contains_drawings_used_by_wired_and_english_paths():
    page, document = _page_and_doc()
    try:
        snapshot = _capture(RecordingPage(page))
        assert snapshot.drawings
        drawing = snapshot.drawings[0]
        for key in (
            "source_order",
            "raw_source_position",
            "type",
            "rect",
            "items",
            "color",
            "fill",
            "stroke_opacity",
            "fill_opacity",
            "width",
            "lineCap",
            "lineJoin",
            "closePath",
            "dashes",
            "layer",
            "seqno",
            "level",
        ):
            assert key in drawing
        line_drawing = next(
            drawing
            for drawing in snapshot.drawings
            if any(item[0] == "l" for item in drawing["items"])
        )
        rect_drawing = next(
            drawing
            for drawing in snapshot.drawings
            if any(item[0] == "re" for item in drawing["items"])
        )
        assert line_drawing["source_order"] < rect_drawing["source_order"]
        assert line_drawing["color"] == (1.0, 0.0, 0.0)
        assert rect_drawing["fill"] == (0.5, 0.5, 0.5)
        assert rect_drawing["fill_opacity"] == pytest.approx(0.4)
    finally:
        document.close()


def test_snapshot_does_not_retain_fitz_page_objects():
    page, document = _page_and_doc()
    try:
        snapshot = _capture(RecordingPage(page))
        dto = _api().page_snapshot_to_dto(snapshot)
        digest = _api().page_snapshot_digest(snapshot)
        assert dto["page_index"] == 3
        assert isinstance(digest, str) and len(digest) == 64
        assert "page" not in dto
        assert "document" not in dto
    finally:
        document.close()


def test_snapshot_is_recursively_immutable():
    page, document = _page_and_doc()
    try:
        snapshot = _capture(RecordingPage(page))
        with pytest.raises(TypeError):
            snapshot.geometry["rotation"] = 0
        with pytest.raises(TypeError):
            snapshot.spans[0]["text"] = "changed"
        with pytest.raises(TypeError):
            snapshot.text_blocks[0]["lines"][0]["spans"][0]["chars"][0]["c"] = "x"
        with pytest.raises(TypeError):
            snapshot.drawings[0]["items"][0][1][0] = 0
        with pytest.raises(TypeError):
            snapshot.extraction_options["rawdict"]["variants"]["preserve_whitespace"]["kwargs"]["flags"] = 0
        assert _api().page_snapshot_digest(snapshot) == _api().page_snapshot_digest(
            snapshot
        )
    finally:
        document.close()


def test_snapshot_records_exact_extraction_options():
    page, document = _page_and_doc()
    try:
        snapshot = _capture(RecordingPage(page))
        options = snapshot.extraction_options
        assert options["rawdict"]["selected"]["kwargs"]["flags"] == fitz.TEXT_PRESERVE_WHITESPACE
        assert options["rawdict"]["variants"]["default"]["args"] == ("rawdict",)
        assert options["words"]["selected"]["args"] == ("words",)
        assert options["words"]["variants"]["preserve_whitespace"]["kwargs"]["flags"] == fitz.TEXT_PRESERVE_WHITESPACE
        assert options["drawings"]["variants"]["extended"]["kwargs"]["extended"] is True
        assert snapshot.schema_version == 1
        assert snapshot.version == 1
        assert snapshot.summary["span_count"] == len(snapshot.spans)
    finally:
        document.close()


def test_snapshot_digest_is_stable_for_same_page():
    page, document = _page_and_doc()
    try:
        first = _capture(RecordingPage(page))
        second = _capture(RecordingPage(page))
        api = _api()
        first_dto = api.page_snapshot_to_dto(first)
        second_dto = api.page_snapshot_to_dto(second)
        assert api.page_snapshot_digest(first) == api.page_snapshot_digest(second)
        assert first_dto == second_dto

        encoded = json.dumps(
            {key: value for key, value in first_dto.items() if key != "digest"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        assert hashlib.sha256(encoded).hexdigest() == api.page_snapshot_digest(first)
        assert '": ' not in encoded.decode("utf-8")
        assert ", " not in encoded.decode("utf-8")
    finally:
        document.close()


def test_real_capture_digest_has_fixed_canonical_golden_value():
    page, document = _page_and_doc()
    try:
        snapshot = _capture(RecordingPage(page))
        dto = _api().page_snapshot_to_dto(snapshot)
        canonical = json.dumps(
            {key: value for key, value in dto.items() if key != "digest"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        assert hashlib.sha256(canonical).hexdigest() == (
            "a5ef950ed76e3533b7a1797cacb859f840fc8db047456030887142af0fdfdfe7"
        )
        assert dto["digest"] == snapshot.digest
    finally:
        document.close()


class _PixmapSpy:
    width = 12
    height = 8
    n = 3
    alpha = False
    samples = b"rgb"


class _ParentSpy:
    def __init__(self):
        self.calls = []

    def xref_object(self, xref):
        self.calls.append(xref)
        return f"<< /Font {xref} 0 R >>"


class _FullPageSpy:
    rect = fitz.Rect(0, 0, 220, 140)
    rotation = 0
    number = 2

    def __init__(self):
        self.parent = _ParentSpy()
        self.calls = []

    def get_text(self, *args, **kwargs):
        self.calls.append(("get_text", args, kwargs))
        mode = args[0]
        block = {
            "type": 0,
            "bbox": [10.0, 10.0, 40.0, 22.0],
            "lines": [{
                "bbox": [10.0, 10.0, 40.0, 22.0],
                "spans": [{
                    "bbox": [10.0, 10.0, 40.0, 22.0],
                    "text": "hello",
                    "chars": [{"c": "h", "bbox": [10.0, 10.0, 15.0, 22.0]}],
                }],
            }],
        }
        if mode in {"rawdict", "dict"}:
            return {"width": 220.0, "height": 140.0, "blocks": [block]}
        if mode == "text":
            return "hello"
        if mode == "blocks":
            return [(10.0, 10.0, 40.0, 22.0, "hello", 0, 0)]
        if mode == "words":
            return [(10.0, 10.0, 40.0, 22.0, "hello", 0, 0, 0)]
        raise AssertionError(mode)

    def get_drawings(self, *args, **kwargs):
        self.calls.append(("get_drawings", args, kwargs))
        return []

    def get_fonts(self, *args, **kwargs):
        self.calls.append(("get_fonts", args, kwargs))
        return [(7, "Arial", "TrueType", "F1", "WinAnsi")]

    def get_images(self, *args, **kwargs):
        self.calls.append(("get_images", args, kwargs))
        return [(11, 0, 100, 100, 8, "DeviceRGB", "", "Im0", "")]

    def get_image_info(self, *args, **kwargs):
        self.calls.append(("get_image_info", args, kwargs))
        return [{"xref": 11, "bbox": fitz.Rect(1, 2, 3, 4), "width": 100, "height": 100}]

    def get_image_rects(self, *args, **kwargs):
        self.calls.append(("get_image_rects", args, kwargs))
        return [fitz.Rect(1, 2, 3, 4)]

    def get_pixmap(self, *args, **kwargs):
        self.calls.append(("get_pixmap", args, kwargs))
        return _PixmapSpy()

    def get_bboxlog(self, *args, **kwargs):
        self.calls.append(("get_bboxlog", args, kwargs))
        return [("fill", fitz.Rect(1, 2, 3, 4))]

    def find_tables(self, *args, **kwargs):
        self.calls.append(("find_tables", args, kwargs))
        return {"tables": [{"bbox": fitz.Rect(1, 2, 3, 4), "cells": []}]}


def test_snapshot_captures_full_page_read_boundary_as_plain_results():
    page = _FullPageSpy()
    snapshot = _capture(page, allowed_regions=(fitz.Rect(0, 0, 60, 60),))
    dto = _api().page_snapshot_to_dto(snapshot)

    assert snapshot.resources["fonts"]["status"] == "ok"
    assert snapshot.resources["fonts"]["result"][0][0] == 7
    assert snapshot.resources["images"]["result"][0][0] == 11
    assert snapshot.resources["image_info"]["result"][0]["bbox"] == (1.0, 2.0, 3.0, 4.0)
    assert snapshot.resources["image_rects"]["11"]["result"] == ((1.0, 2.0, 3.0, 4.0),)
    assert snapshot.resources["font_xref_objects"]["7"]["result"] == "<< /Font 7 0 R >>"
    assert snapshot.raster["result"]["width"] == 12
    assert snapshot.bboxlog["result"][0][1] == (1.0, 2.0, 3.0, 4.0)
    assert snapshot.table_fallback["result"]["tables"][0]["bbox"] == (1.0, 2.0, 3.0, 4.0)
    assert dto["page_reads"]["pixmap"]["kwargs"]["alpha"] is False
    assert any(
        call[0] == "get_text" and call[1] == ("words",) and "clip" in call[2]
        for call in page.calls
    )

    def assert_plain(value):
        assert not isinstance(value, (fitz.Page, fitz.Document))
        if isinstance(value, dict):
            for item in value.values():
                assert_plain(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                assert_plain(item)

    assert_plain(dto)


def test_snapshot_records_unavailable_and_error_page_apis():
    class ErrorPage(_FullPageSpy):
        def get_fonts(self, *args, **kwargs):
            raise RuntimeError("font probe failed")

        def __getattribute__(self, name):
            if name == "get_images":
                raise AttributeError(name)
            return super().__getattribute__(name)

    snapshot = _capture(ErrorPage())
    assert snapshot.resources["fonts"]["status"] == "error"
    assert snapshot.resources["fonts"]["error"]["type"] == "RuntimeError"
    assert snapshot.resources["images"]["status"] == "unavailable"
    assert snapshot.page_reads["parent"]["status"] == "ok"


def test_snapshot_filtering_filters_blocks_and_preserves_global_order():
    class TwoBlockPage(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                second = {
                    "type": 0,
                    "bbox": [100.0, 10.0, 130.0, 22.0],
                    "lines": [{
                        "bbox": [100.0, 10.0, 130.0, 22.0],
                        "spans": [{
                            "bbox": [100.0, 10.0, 130.0, 22.0],
                            "text": "world",
                            "chars": [{"c": "w", "bbox": [100.0, 10.0, 105.0, 22.0]}],
                        }],
                    }],
                }
                result["blocks"].append(second)
            return result

    snapshot = _capture(TwoBlockPage())
    assert [span["source_order"] for span in snapshot.spans] == [0, 1]
    assert [block["lines"][0]["source_order"] for block in snapshot.text_blocks] == [0, 1]
    filtered = _api().filter_snapshot_evidence(
        snapshot,
        allowed_regions=(fitz.Rect(0, 0, 60, 100),),
    )
    assert [block["raw_source_position"] for block in filtered.text_blocks] == [(0,)]
    assert [block["filtered_order"] for block in filtered.text_blocks] == [0]
    assert [span["raw_source_position"] for span in filtered.spans] == [(0, 0, 0)]
    assert [span["filtered_order"] for span in filtered.spans] == [0]


def test_direct_snapshot_construction_freezes_nested_values_and_rejects_nonfinite():
    api = _api()
    snapshot = api.PageSnapshot(
        schema_version=1,
        version=1,
        page_index=0,
        geometry={"rect": [0.0, 0.0, 10.0, 10.0]},
        text_blocks=({"lines": [{"spans": [{"text": ""}]}]},),
        spans=({"text": ""},),
        characters=(),
        words=(),
        drawings=(),
        allowed_regions=(),
        excluded_regions=(),
        extraction_options={"words": {"kwargs": {"clip": None}}},
        summary={"empty": ""},
        resources={"nested": [{"value": ""}]},
        raster={},
        bboxlog={},
        table_fallback={},
        page_reads={},
    )
    with pytest.raises(TypeError):
        snapshot.resources["nested"][0]["value"] = "changed"
    with pytest.raises(TypeError):
        snapshot.text_blocks[0]["lines"][0]["spans"][0]["text"] = "x"
    assert _api().page_snapshot_to_dto(snapshot)["summary"]["empty"] == ""

    with pytest.raises(ValueError):
        api.PageSnapshot(
            1, 1, 0, {"bad": math.nan}, (), (), (), (), (), (), {}, {}, {}
        )


def test_snapshot_digest_keeps_empty_values_in_canonical_golden_fixture():
    snapshot = _api().PageSnapshot(
        1,
        1,
        0,
        {"rect": (0.0, 0.0, 10.0, 10.0)},
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        {"text": ""},
        {"empty": [], "value": ""},
    )
    assert _api().page_snapshot_to_dto(snapshot)["extraction_options"]["text"] == ""
    assert _api().page_snapshot_to_dto(snapshot)["summary"]["empty"] == []
    assert _api().page_snapshot_digest(snapshot) == (
        "b37a29c03d77ed8880960afca865c429e2adbdf1fd384d5866b61b67665f6c32"
    )


def test_snapshot_records_pixmap_pixels_and_all_registered_parameter_variants():
    page = _FullPageSpy()
    snapshot = _capture(page, allowed_regions=(fitz.Rect(0, 0, 60, 60),))

    text_calls = [call for call in page.calls if call[0] == "get_text"]
    assert ("rawdict",) in [call[1] for call in text_calls]
    assert ("dict",) in [call[1] for call in text_calls]
    assert ("text",) in [call[1] for call in text_calls]
    assert ("blocks",) in [call[1] for call in text_calls]
    assert any(call[1] == ("words",) and not call[2] for call in text_calls)
    assert any(
        call[1] == ("words",) and call[2].get("flags") == fitz.TEXT_PRESERVE_WHITESPACE
        for call in text_calls
    )
    assert any(
        call[1] == ("words",)
        and isinstance(call[2].get("clip"), fitz.Rect)
        and call[2].get("flags") == fitz.TEXT_PRESERVE_WHITESPACE
        for call in text_calls
    )
    drawing_calls = [call for call in page.calls if call[0] == "get_drawings"]
    assert any(not call[2] for call in drawing_calls)
    assert any(call[2] == {"extended": True} for call in drawing_calls)

    pixmap_calls = [call for call in page.calls if call[0] == "get_pixmap"]
    assert len(pixmap_calls) == 2
    assert pixmap_calls[0][2]["alpha"] is False
    assert pixmap_calls[0][2]["matrix"] == fitz.Matrix(0.1, 0.1)
    assert "colorspace" in pixmap_calls[0][2]
    pixels = snapshot.raster["result"]["samples"]
    assert pixels["byte_length"] == 3
    assert pixels["sha256"] == hashlib.sha256(b"rgb").hexdigest()
    assert pixels["hex"] == b"rgb".hex()


def test_snapshot_records_find_tables_extract_rows_and_fake_fallback_evidence():
    class FakeTable:
        bbox = fitz.Rect(1, 2, 30, 40)
        cells = ((1.0, 2.0, 30.0, 20.0),)
        header = {"names": ["A"]}

        def extract(self):
            return [["A"], ["value"]]

    class TablePage(_FullPageSpy):
        def find_tables(self, *args, **kwargs):
            self.calls.append(("find_tables", args, kwargs))
            return type("FakeFinder", (), {"tables": [FakeTable()]})()

    snapshot = _capture(TablePage())
    fallback = snapshot.table_fallback
    assert fallback["status"] == "ok"
    assert fallback["tables"][0]["bbox"] == (1.0, 2.0, 30.0, 40.0)
    assert fallback["tables"][0]["extract"]["args"] == ()
    assert fallback["tables"][0]["extract"]["kwargs"] == {}
    assert fallback["tables"][0]["extract"]["status"] == "ok"
    assert fallback["tables"][0]["extract"]["result"] == (("A",), ("value",))


def test_filter_snapshot_evidence_preserves_hierarchy_and_filters_footer_and_blank_spans():
    class FooterPage(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                result["blocks"][0]["lines"].extend(
                    [
                        {
                            "bbox": [10.0, 125.0, 80.0, 137.0],
                            "spans": [
                                {
                                    "bbox": [10.0, 125.0, 80.0, 137.0],
                                    "chars": [
                                        {"c": "第3页/共5页", "bbox": [10.0, 125.0, 80.0, 137.0]}
                                    ],
                                }
                            ],
                        },
                        {
                            "bbox": [90.0, 80.0, 95.0, 90.0],
                            "spans": [
                                {
                                    "bbox": [90.0, 80.0, 95.0, 90.0],
                                    "chars": [{"c": " ", "bbox": [90.0, 80.0, 95.0, 90.0]}],
                                }
                            ],
                        },
                    ]
                )
            return result

    snapshot = _capture(FooterPage())
    filtered = _api().filter_snapshot_evidence(snapshot)
    assert len(filtered.lines) == 1
    assert all("第3页" not in line.get("text", "") for line in filtered.lines)
    assert all(span["text"].strip() for span in filtered.spans)
    assert [block["filtered_order"] for block in filtered.text_blocks] == list(
        range(len(filtered.text_blocks))
    )
    assert [line["filtered_order"] for line in filtered.lines] == list(
        range(len(filtered.lines))
    )
    assert [span["filtered_order"] for span in filtered.spans] == list(
        range(len(filtered.spans))
    )
    assert any("第3页" in span["text"] for span in snapshot.spans)


def test_parent_dto_is_minimal_and_digest_is_stable_across_equivalent_documents():
    first = _capture(_FullPageSpy())
    second = _capture(_FullPageSpy())
    api = _api()
    first_dto = api.page_snapshot_to_dto(first)
    second_dto = api.page_snapshot_to_dto(second)
    assert first_dto["page_reads"]["parent"]["result"] == {
        "available": True,
        "type": "_ParentSpy",
    }
    assert "attributes" not in first_dto["page_reads"]["parent"]["result"]
    assert api.page_snapshot_digest(first) == api.page_snapshot_digest(second)


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_snapshot_records_nonfinite_result_normalization_errors_without_crashing(bad_value):
    class NonFinitePage(_FullPageSpy):
        def get_bboxlog(self, *args, **kwargs):
            self.calls.append(("get_bboxlog", args, kwargs))
            return [("fill", (bad_value, 1.0, 2.0, 3.0))]

    snapshot = _capture(NonFinitePage())
    record = snapshot.bboxlog
    assert record["status"] == "error"
    assert record["error"]["phase"] == "normalize"
    assert record["result"] is None


def test_snapshot_serialization_and_filtering_never_reenter_strict_spy_page():
    class StrictPage(_FullPageSpy):
        locked = False

        def __getattribute__(self, name):
            if name in {
                "rect", "width", "height", "size", "rotation", "number",
                "parent", "get_text", "get_drawings", "get_fonts", "get_images",
                "get_image_info", "get_image_rects", "get_pixmap", "get_bboxlog",
                "find_tables",
            } and object.__getattribute__(self, "locked"):
                raise AssertionError(f"page reread after capture: {name}")
            return super().__getattribute__(name)

    page = StrictPage()
    snapshot = _capture(page)
    page.locked = True
    api = _api()
    dto = api.page_snapshot_to_dto(snapshot)
    api.page_snapshot_digest(snapshot)
    api.filter_snapshot_evidence(snapshot)

    def assert_owned(value):
        assert not isinstance(value, (fitz.Page, fitz.Document))
        if isinstance(value, dict):
            for item in value.values():
                assert_owned(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                assert_owned(item)

    assert_owned(dto)


def test_snapshot_captures_replayable_production_and_ml_pixmap_variants():
    class Pixmap:
        def __init__(self, width, height, stride, samples, colorspace, alpha):
            self.width = width
            self.height = height
            self.stride = stride
            self.samples = samples
            self.colorspace = colorspace
            self.n = colorspace.n + int(alpha)
            self.alpha = alpha

    class PixmapPage(_FullPageSpy):
        def get_pixmap(self, *args, **kwargs):
            self.calls.append(("get_pixmap", args, kwargs))
            matrix = kwargs["matrix"]
            if matrix == fitz.Matrix(0.1, 0.1):
                assert kwargs == {
                    "matrix": fitz.Matrix(0.1, 0.1),
                    "colorspace": fitz.csRGB,
                    "alpha": False,
                }
                return Pixmap(12, 8, 36, b"rgb", fitz.csRGB, False)
            assert matrix == fitz.Matrix(1, 1)
            assert kwargs == {"matrix": fitz.Matrix(1, 1), "alpha": False}
            return Pixmap(220, 140, 660, b"ml-rgb", fitz.csRGB, False)

    page = PixmapPage()
    snapshot = _capture(page)
    variants = snapshot.raster["variants"]

    assert [call[2] for call in page.calls if call[0] == "get_pixmap"] == [
        {"matrix": fitz.Matrix(0.1, 0.1), "colorspace": fitz.csRGB, "alpha": False},
        {"matrix": fitz.Matrix(1, 1), "alpha": False},
    ]
    assert variants["production"]["kwargs"]["matrix"] == (0.1, 0.0, 0.0, 0.1, 0.0, 0.0)
    assert variants["production"]["kwargs"]["colorspace"]["identity"] == "csRGB"
    assert variants["production"]["result"]["stride"] == 36
    assert variants["production"]["result"]["samples"]["hex"] == b"rgb".hex()
    assert variants["ml"]["kwargs"]["matrix"] == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    assert "colorspace" not in variants["ml"]["kwargs"]
    assert variants["ml"]["result"]["colorspace"]["identity"] == "csRGB"
    assert variants["ml"]["result"]["samples"]["hex"] == b"ml-rgb".hex()
    assert variants["ml"]["result"]["stride"] == 660
    assert _api().snapshot_pixmap(snapshot, variant="ml")["result"]["width"] == 220
    with pytest.raises(TypeError):
        variants["production"]["result"]["samples"]["hex"] = "changed"


def test_snapshot_uses_configurable_ml_render_dpi_and_exact_rgb_call():
    class PixmapPage(_FullPageSpy):
        def get_pixmap(self, *args, **kwargs):
            self.calls.append(("get_pixmap", args, kwargs))
            if kwargs.get("colorspace") is fitz.csRGB:
                return _PixmapSpy()
            assert kwargs == {"matrix": fitz.Matrix(2, 2), "alpha": False}
            return type(
                "MLPixmap",
                (),
                {
                    "width": 440,
                    "height": 280,
                    "stride": 1320,
                    "n": 3,
                    "alpha": False,
                    "colorspace": fitz.csRGB,
                    "samples": b"custom-ml-rgb",
                },
            )()

    snapshot = _capture(PixmapPage(), ml_render_dpi=144)
    ml = snapshot.raster["variants"]["ml"]
    assert ml["kwargs"] == {"matrix": (2.0, 0.0, 0.0, 2.0, 0.0, 0.0), "alpha": False}
    assert ml["result"]["width"] == 440
    assert ml["result"]["height"] == 280
    assert ml["result"]["stride"] == 1320
    assert ml["result"]["n"] == 3
    assert ml["result"]["alpha"] is False
    assert ml["result"]["colorspace"]["identity"] == "csRGB"
    assert ml["result"]["samples"]["hex"] == b"custom-ml-rgb".hex()


def test_plain_serializes_real_pixmap_before_point_detection_with_full_pixels():
    pixmap = fitz.Pixmap(fitz.csRGB, (0, 0, 2, 1))
    plain = _api()._plain(pixmap)
    assert plain["type"] == "pixmap"
    assert plain["width"] == 2
    assert plain["height"] == 1
    assert plain["stride"] == 6
    assert plain["n"] == 3
    assert plain["alpha"] is False
    assert plain["colorspace"]["identity"] == "csRGB"
    assert plain["samples"]["byte_length"] == len(pixmap.samples)
    assert plain["samples"]["hex"] == bytes(pixmap.samples).hex()


def test_snapshot_words_for_clip_reconstructs_partial_words_from_captured_chars():
    class CharWordPage(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                chars = [
                    {"c": char, "bbox": [10.0 + index * 5, 10.0, 15.0 + index * 5, 22.0]}
                    for index, char in enumerate("hello")
                ]
                result["blocks"][0]["lines"][0]["spans"][0]["chars"] = chars
                result["blocks"][0]["lines"][0]["spans"][0]["text"] = "hello"
            if args and args[0] == "words":
                return [(10.0, 10.0, 35.0, 22.0, "hello", 0, 0, 0)]
            return result

        def __getattribute__(self, name):
            if name == "get_text" and object.__getattribute__(self, "locked"):
                raise AssertionError("clip query reread page after capture")
            return super().__getattribute__(name)

        locked = False

    page = CharWordPage()
    snapshot = _capture(page)
    page.locked = True
    words = _api().snapshot_words_for_clip(snapshot, fitz.Rect(10, 10, 20, 22))
    assert len(words) == 1
    assert words[0]["text"] == "he"
    assert words[0]["bbox"] == (10.0, 10.0, 20.0, 22.0)
    assert words[0]["block_index"] == 0
    assert words[0]["line_index"] == 0
    assert words[0]["word_index"] == 0
    assert words[0]["raw_source_position"] == (0, 0, 0)
    assert words[0]["source_order"] == 0


def test_filter_snapshot_evidence_applies_regions_to_empty_and_image_blocks():
    class LineLessBlocksPage(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                result["blocks"].extend(
                    [
                        {"type": 0, "bbox": [70.0, 10.0, 80.0, 20.0]},
                        {"type": 1, "bbox": [80.0, 10.0, 90.0, 20.0]},
                        {"type": 1, "bbox": [40.0, 40.0, 50.0, 50.0]},
                    ]
                )
            return result

    snapshot = _capture(LineLessBlocksPage())
    filtered = _api().filter_snapshot_evidence(
        snapshot,
        allowed_regions=(fitz.Rect(0, 0, 60, 60),),
        excluded_regions=(fitz.Rect(15, 35, 35, 55),),
    )
    assert [block["type"] for block in filtered.text_blocks] == [0, 1]
    assert [block["bbox"] for block in filtered.text_blocks if "bbox" in block] == [
        (10.0, 10.0, 40.0, 22.0),
        (40.0, 40.0, 50.0, 50.0),
    ]


def test_snapshot_strict_spy_captures_exact_parent_xref_call_and_never_reenters_it():
    class StrictParent(_ParentSpy):
        locked = False

        def xref_object(self, *args, **kwargs):
            if self.locked:
                raise AssertionError("parent.xref_object reread after capture")
            assert args == (7,)
            assert kwargs == {}
            self.calls.append((args, kwargs))
            return "<< /Font 7 0 R >>"

    class StrictPage(_FullPageSpy):
        def __init__(self):
            super().__init__()
            self.parent = StrictParent()

    page = StrictPage()
    snapshot = _capture(page)
    page.parent.locked = True
    api = _api()
    api.page_snapshot_to_dto(snapshot)
    api.page_snapshot_digest(snapshot)
    api.filter_snapshot_evidence(snapshot)
    assert page.parent.calls == [((7,), {})]


def test_snapshot_materializes_table_header_proxy_attributes_without_callables():
    class Header:
        bbox = fitz.Rect(1, 2, 30, 10)
        cells = ((1.0, 2.0, 15.0, 10.0), (15.0, 2.0, 30.0, 10.0))
        names = ("left", "right")
        external = True

        def get_names(self):
            return self.names

    class Table:
        bbox = fitz.Rect(1, 2, 30, 40)
        cells = ((1.0, 2.0, 30.0, 20.0),)
        header = Header()

        def extract(self):
            return [["value"]]

    class TablePage(_FullPageSpy):
        def find_tables(self, *args, **kwargs):
            self.calls.append(("find_tables", args, kwargs))
            return type("Finder", (), {"tables": (Table(),)})()

    snapshot = _capture(TablePage())
    table = snapshot.table_fallback["tables"][0]
    assert table["header"]["bbox"] == (1.0, 2.0, 30.0, 10.0)
    assert table["header"]["cells"] == ((1.0, 2.0, 15.0, 10.0), (15.0, 2.0, 30.0, 10.0))
    assert table["header"]["names"] == ("left", "right")
    assert table["header"]["external"] is True
    assert "get_names" not in table["header"]


def test_snapshot_words_for_clip_is_pure_and_uses_captured_words():
    class CompleteCharacterPage(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                result["blocks"][0]["lines"][0]["spans"][0]["chars"] = [
                    {
                        "c": char,
                        "origin": (10.0 + index * 6.0, 20.0),
                        "bbox": [10.0 + index * 6.0, 10.0, 16.0 + index * 6.0, 22.0],
                    }
                    for index, char in enumerate("hello")
                ]
            return result

    page = CompleteCharacterPage()
    snapshot = _capture(page)
    page.locked = True
    words = _api().snapshot_words_for_clip(snapshot, fitz.Rect(0, 0, 50, 50))
    assert len(words) == 1
    assert words[0]["text"] == "hello"
    assert all("page" not in word and "document" not in word for word in words)
    with pytest.raises(TypeError):
        words[0]["text"] = "changed"


def test_snapshot_words_for_clip_does_not_fallback_when_characters_are_incomplete():
    snapshot = _capture(_FullPageSpy())
    assert _api().snapshot_words_for_clip(snapshot, fitz.Rect(0, 0, 50, 50)) == ()


@pytest.mark.parametrize(
    "clip_values",
    (
        (9, 0, 24, 40),
        (20, 10, 25, 40),
        (23, 0, 24, 40),
        (10, 0, 11, 40),
        (12, 0, 13, 40),
        (16, 0, 17, 40),
        (22, 0, 25, 40),
        (70, 10, 80, 40),
    ),
)
@pytest.mark.parametrize("font_size", (6, 12, 24))
def test_snapshot_words_for_clip_matches_real_pymupdf_for_multiple_boundaries(
    clip_values,
    font_size,
):
    document = fitz.open()
    real_page = document.new_page(width=120, height=80)
    real_page.insert_text((10, 30), "hello world", fontsize=font_size)

    class StrictRealPage:
        _blocked = {
            "get_text", "get_drawings", "get_fonts", "get_images",
            "get_image_info", "get_image_rects", "get_pixmap",
            "get_bboxlog", "find_tables", "rect", "rotation", "number",
        }

        def __init__(self, page):
            self._page = page
            self.locked = False

        def __getattr__(self, name):
            if self.locked and name in self._blocked:
                raise AssertionError(f"page reread after capture: {name}")
            return getattr(self._page, name)

    page = StrictRealPage(real_page)
    try:
        snapshot = _capture(page)
        page.locked = True
        clip = fitz.Rect(*clip_values)
        expected = real_page.get_text("words", clip=clip)
        actual = _api().snapshot_words_for_clip(snapshot, clip)
        assert [tuple(word[:4]) + (word[4],) + tuple(word[5:]) for word in expected] == [
            (word["bbox"] + (word["text"], word["block_index"], word["line_index"], word["word_index"]))
            for word in actual
        ]
    finally:
        document.close()


def test_snapshot_words_for_clip_splits_noncontiguous_selected_characters():
    document = fitz.open()
    real_page = document.new_page(width=120, height=80)
    real_page.insert_text((10, 30), "hello world", fontsize=12)
    try:
        snapshot = _capture(real_page)
        clip = fitz.Rect(0, 16, 75, 23)
        expected = real_page.get_text("words", clip=clip)
        actual = _api().snapshot_words_for_clip(snapshot, clip)
        assert [tuple(word[:4]) + (word[4],) + tuple(word[5:]) for word in expected] == [
            (word["bbox"] + (word["text"], word["block_index"], word["line_index"], word["word_index"]))
            for word in actual
        ]
    finally:
        document.close()


def test_snapshot_words_for_clip_reindexes_selected_blocks_and_lines():
    document = fitz.open()
    real_page = document.new_page(width=120, height=100)
    real_page.insert_text((10, 30), "hello world", fontsize=12)
    real_page.insert_text((10, 60), "alpha beta", fontsize=12)

    class StrictRealPage:
        _blocked = {
            "get_text", "get_drawings", "get_fonts", "get_images",
            "get_image_info", "get_image_rects", "get_pixmap",
            "get_bboxlog", "find_tables", "rect", "rotation", "number",
        }

        def __init__(self, page):
            self._page = page
            self.locked = False

        def __getattr__(self, name):
            if self.locked and name in self._blocked:
                raise AssertionError(f"page reread after capture: {name}")
            return getattr(self._page, name)

    page = StrictRealPage(real_page)
    try:
        snapshot = _capture(page)
        page.locked = True
        clip = fitz.Rect(0, 40, 120, 80)
        expected = real_page.get_text("words", clip=clip)
        actual = _api().snapshot_words_for_clip(snapshot, clip)
        assert [tuple(word[:4]) + (word[4],) + tuple(word[5:]) for word in expected] == [
            (word["bbox"] + (word["text"], word["block_index"], word["line_index"], word["word_index"]))
            for word in actual
        ]
    finally:
        document.close()


def test_snapshot_words_for_clip_reindexes_selected_lines_within_one_block():
    document = fitz.open()
    real_page = document.new_page(width=120, height=100)
    real_page.insert_textbox(
        fitz.Rect(10, 10, 110, 90),
        "hello\nalpha\nomega",
        fontsize=12,
    )
    snapshot = _capture(real_page)
    try:
        clip = fitz.Rect(0, 40, 120, 80)
        expected = real_page.get_text("words", clip=clip)
        actual = _api().snapshot_words_for_clip(snapshot, clip)
        assert [tuple(word[:4]) + (word[4],) + tuple(word[5:]) for word in expected] == [
            (word["bbox"] + (word["text"], word["block_index"], word["line_index"], word["word_index"]))
            for word in actual
        ]
    finally:
        document.close()


def test_snapshot_words_for_clip_preserves_skipped_line_indices_and_reindexes_blocks():
    class MultiLinePage(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if not args or args[0] != "rawdict":
                if args and args[0] == "words":
                    return [
                        (10.0, 0.0, 12.0, 5.0, "x", 0, 0, 0),
                        (35.0, 10.0, 36.0, 15.0, "a", 0, 1, 0),
                        (10.0, 20.0, 12.0, 25.0, "y", 0, 2, 0),
                        (35.0, 30.0, 36.0, 35.0, "b", 0, 3, 0),
                        (35.0, 10.0, 36.0, 15.0, "c", 1, 2, 0),
                    ]
                return result
            result["blocks"] = [
                {
                    "type": 0,
                    "bbox": [10.0, 0.0, 36.0, 35.0],
                    "lines": [
                        {
                            "bbox": [10.0, 0.0, 12.0, 5.0],
                            "spans": [{
                                "bbox": [10.0, 0.0, 12.0, 5.0],
                                "chars": [{"c": "x", "bbox": [10.0, 0.0, 12.0, 5.0]}],
                            }],
                        },
                        {
                            "bbox": [35.0, 10.0, 36.0, 15.0],
                            "spans": [{
                                "bbox": [35.0, 10.0, 36.0, 15.0],
                                "chars": [{"c": "a", "bbox": [35.0, 10.0, 36.0, 15.0]}],
                            }],
                        },
                        {
                            "bbox": [10.0, 20.0, 12.0, 25.0],
                            "spans": [{
                                "bbox": [10.0, 20.0, 12.0, 25.0],
                                "chars": [{"c": "y", "bbox": [10.0, 20.0, 12.0, 25.0]}],
                            }],
                        },
                        {
                            "bbox": [35.0, 30.0, 36.0, 35.0],
                            "spans": [{
                                "bbox": [35.0, 30.0, 36.0, 35.0],
                                "chars": [{"c": "b", "bbox": [35.0, 30.0, 36.0, 35.0]}],
                            }],
                        },
                    ],
                },
                {
                    "type": 0,
                    "bbox": [35.0, 10.0, 36.0, 15.0],
                    "lines": [
                        {"bbox": [35.0, 10.0, 36.0, 15.0], "spans": []},
                        {"bbox": [35.0, 10.0, 36.0, 15.0], "spans": []},
                        {
                            "bbox": [35.0, 10.0, 36.0, 15.0],
                            "spans": [{
                                "bbox": [35.0, 10.0, 36.0, 15.0],
                                "chars": [{"c": "c", "bbox": [35.0, 10.0, 36.0, 15.0]}],
                            }],
                        },
                    ],
                },
            ]
            return result

    snapshot = _capture(MultiLinePage())
    actual = _api().snapshot_words_for_clip(snapshot, fitz.Rect(35, 0, 36, 40))
    assert [
        word["bbox"] + (word["text"], word["block_index"], word["line_index"], word["word_index"])
        for word in actual
    ] == [
        (35.0, 10.0, 36.0, 15.0, "a", 0, 1, 0),
        (35.0, 30.0, 36.0, 35.0, "b", 0, 3, 0),
        (35.0, 10.0, 36.0, 15.0, "c", 1, 0, 0),
    ]


@pytest.mark.parametrize(
    ("text_rotation", "clip_values"),
    (
        (0, (49, 65, 74, 82)),
        (90, (35, 55, 55, 81)),
        (180, (26, 74, 51, 90)),
        (270, (46, 77, 63, 94)),
    ),
)
def test_snapshot_words_for_clip_matches_rotated_glyph_geometry(
    text_rotation,
    clip_values,
):
    document = fitz.open()
    real_page = document.new_page(width=120, height=120)
    real_page.insert_text((50, 78), "hello world", fontsize=11, rotate=text_rotation)

    class StrictRealPage:
        _blocked = {
            "get_text", "get_drawings", "get_fonts", "get_images",
            "get_image_info", "get_image_rects", "get_pixmap",
            "get_bboxlog", "find_tables", "rect", "rotation", "number",
        }

        def __init__(self, page):
            self._page = page
            self.locked = False

        def __getattr__(self, name):
            if self.locked and name in self._blocked:
                raise AssertionError(f"page reread after capture: {name}")
            return getattr(self._page, name)

    page = StrictRealPage(real_page)
    try:
        snapshot = _capture(page)
        page.locked = True
        clip = fitz.Rect(*clip_values)
        expected = real_page.get_text("words", clip=clip)
        actual = _api().snapshot_words_for_clip(snapshot, clip)
        assert [tuple(word[:4]) + (word[4],) + tuple(word[5:]) for word in expected] == [
            (word["bbox"] + (word["text"], word["block_index"], word["line_index"], word["word_index"]))
            for word in actual
        ]
    finally:
        document.close()


@pytest.mark.parametrize(
    ("text", "clip_values"),
    (
        ("aaaaa\nbbbbb\nccccc\nddddd", (35, 0, 36, 40)),
        ("aaaaa\nbbbbb\nccccc\nddddd", (35, 20, 36, 50)),
        ("zero\naaaaaa\ntwo\nthree", (35, 0, 36, 40)),
    ),
)
def test_snapshot_words_for_clip_matches_real_multiline_block_indexing(
    text,
    clip_values,
):
    document = fitz.open()
    real_page = document.new_page(width=120, height=100)
    real_page.insert_textbox(
        fitz.Rect(10, 4, 110, 90),
        text,
        fontsize=12,
        lineheight=1.0,
    )

    class StrictRealPage:
        _blocked = {
            "get_text", "get_drawings", "get_fonts", "get_images",
            "get_image_info", "get_image_rects", "get_pixmap",
            "get_bboxlog", "find_tables", "rect", "rotation", "number",
        }

        def __init__(self, page):
            self._page = page
            self.locked = False

        def __getattr__(self, name):
            if self.locked and name in self._blocked:
                raise AssertionError(f"page reread after capture: {name}")
            return getattr(self._page, name)

    page = StrictRealPage(real_page)
    try:
        snapshot = _capture(page)
        clip = fitz.Rect(*clip_values)
        expected = real_page.get_text("words", clip=clip)
        page.locked = True
        actual = _api().snapshot_words_for_clip(snapshot, clip)
        assert [
            tuple(word[:4]) + (word[4],) + tuple(word[5:8])
            for word in expected
        ] == [
            word["bbox"]
            + (word["text"], word["block_index"], word["line_index"], word["word_index"])
            for word in actual
        ]
    finally:
        document.close()


@pytest.mark.parametrize(
    ("text_rotation", "clip_values"),
    (
        (0, (49, 65, 74, 82)),
        (90, (35, 55, 55, 81)),
        (180, (26, 74, 51, 90)),
        (270, (46, 77, 63, 94)),
    ),
)
def test_snapshot_words_for_clip_matches_real_rotated_page_without_reread(
    text_rotation,
    clip_values,
):
    document = fitz.open()
    real_page = document.new_page(width=120, height=120)
    real_page.insert_text((50, 78), "hello world", fontsize=11, rotate=text_rotation)

    class StrictRealPage:
        _blocked = {
            "get_text", "get_drawings", "get_fonts", "get_images",
            "get_image_info", "get_image_rects", "get_pixmap",
            "get_bboxlog", "find_tables", "rect", "rotation", "number",
        }

        def __init__(self, page):
            self._page = page
            self.locked = False

        def __getattr__(self, name):
            if self.locked and name in self._blocked:
                raise AssertionError(f"page reread after capture: {name}")
            return getattr(self._page, name)

    page = StrictRealPage(real_page)
    try:
        snapshot = _capture(page)
        clip = fitz.Rect(*clip_values)
        expected = real_page.get_text("words", clip=clip)
        page.locked = True
        actual = _api().snapshot_words_for_clip(snapshot, clip)
        assert [
            tuple(word[:4]) + (word[4],) + tuple(word[5:8])
            for word in expected
        ] == [
            word["bbox"]
            + (word["text"], word["block_index"], word["line_index"], word["word_index"])
            for word in actual
        ]
    finally:
        document.close()


def test_filter_snapshot_evidence_removes_footer_words_with_their_footer_line():
    class FooterWordsPage(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                result["blocks"][0]["lines"].append(
                    {
                        "bbox": [10.0, 125.0, 80.0, 137.0],
                        "spans": [
                            {
                                "bbox": [10.0, 125.0, 80.0, 137.0],
                                "chars": [
                                    {"c": "第3页/共5页", "bbox": [10.0, 125.0, 80.0, 137.0]}
                                ],
                            }
                        ],
                    }
                )
            if args and args[0] == "words":
                return [
                    (10.0, 10.0, 40.0, 22.0, "hello", 0, 0, 0),
                    (10.0, 125.0, 80.0, 137.0, "第3页/共5页", 0, 1, 0),
                ]
            return result

    snapshot = _capture(FooterWordsPage())
    filtered = _api().filter_snapshot_evidence(snapshot)
    assert [word["text"] for word in snapshot.words] == ["hello", "第3页/共5页"]
    assert [word["text"] for word in filtered.words] == ["hello"]
    assert [word["filtered_order"] for word in filtered.words] == [0]


def test_filter_snapshot_evidence_keeps_block_when_only_child_span_is_in_region():
    class ParentOutsideChildInside(_FullPageSpy):
        def get_text(self, *args, **kwargs):
            result = super().get_text(*args, **kwargs)
            if args and args[0] == "rawdict":
                result["blocks"][0]["bbox"] = [100.0, 100.0, 130.0, 130.0]
                result["blocks"][0]["lines"][0]["bbox"] = [100.0, 100.0, 130.0, 130.0]
                result["blocks"][0]["lines"][0]["spans"][0]["bbox"] = [
                    10.0, 10.0, 40.0, 22.0
                ]
            return result

    snapshot = _capture(ParentOutsideChildInside())
    filtered = _api().filter_snapshot_evidence(
        snapshot,
        allowed_regions=(fitz.Rect(0, 0, 60, 60),),
    )
    assert len(filtered.text_blocks) == 1
    assert len(filtered.lines) == 1
    assert len(filtered.spans) == 1


def test_snapshot_page_api_call_contract_is_exact_and_owned():
    page = _FullPageSpy()
    snapshot = _capture(page)
    calls = [call for call in page.calls if call[0] in {
        "get_fonts", "get_images", "get_image_info", "get_image_rects",
        "get_pixmap", "get_bboxlog", "find_tables",
    }]

    assert [call for call in calls if call[0] == "get_fonts"] == [
        ("get_fonts", (), {"full": True})
    ]
    assert [call[2] for call in calls if call[0] == "get_images"] == [{}, {"full": True}]
    assert [call for call in calls if call[0] == "get_image_info"] == [
        ("get_image_info", (), {"xrefs": True})
    ]
    assert [call for call in calls if call[0] == "get_image_rects"] == [
        ("get_image_rects", (11,), {})
    ]
    assert [call[2] for call in calls if call[0] == "get_pixmap"] == [
        {"matrix": fitz.Matrix(0.1, 0.1), "colorspace": fitz.csRGB, "alpha": False},
        {"matrix": fitz.Matrix(1, 1), "alpha": False},
    ]
    assert [call for call in calls if call[0] == "get_bboxlog"] == [
        ("get_bboxlog", (), {})
    ]
    assert [call for call in calls if call[0] == "find_tables"] == [
        ("find_tables", (), {})
    ]
    assert page.parent.calls == [7]
    dto = _api().page_snapshot_to_dto(snapshot)
    assert "colorspace" not in dto["page_reads"]["pixmap.ml"]["kwargs"]
    assert dto["page_reads"]["find_tables"]["status"] == "ok"
