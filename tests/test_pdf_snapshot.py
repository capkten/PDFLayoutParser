from __future__ import annotations

import hashlib
import importlib
import json

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


def _capture(recording_page, *, allowed_regions=(), excluded_regions=()):
    api = _api()
    return api.capture_page_snapshot(
        recording_page,
        page_index=3,
        allowed_regions=allowed_regions,
        excluded_regions=excluded_regions,
    )


def test_snapshot_preserves_source_order_and_character_boxes():
    page, document = _page_and_doc()
    recording_page = RecordingPage(page)
    try:
        snapshot = _capture(recording_page)
        assert [call[0] for call in recording_page.calls] == [
            "get_text",
            "get_text",
            "get_drawings",
        ]
        assert recording_page.calls[0][1:] == (
            ("rawdict",),
            {"flags": fitz.TEXT_PRESERVE_WHITESPACE},
        )
        assert recording_page.calls[1][1:] == (("words",), {})
        assert recording_page.calls[2][1:] == ((), {"extended": True})
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
            snapshot.extraction_options["rawdict"]["kwargs"]["flags"] = 0
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
        assert options["rawdict"]["mode"] == "rawdict"
        assert options["rawdict"]["flags"] == fitz.TEXT_PRESERVE_WHITESPACE
        assert options["rawdict"]["clip"] is None
        assert options["words"] == {
            "method": "get_text",
            "mode": "words",
            "args": ("words",),
            "kwargs": {},
            "clip": None,
        }
        assert options["drawings"]["extended"] is True
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
