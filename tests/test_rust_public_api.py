"""Migration checks for the public PDF APIs."""

import json
from pathlib import Path

import fitz

from hexai_pdf_parser import _pdf_fast
from hexai_pdf_parser.pdf_parser import PDFParser
from hexai_pdf_parser import pdfium_api
from hexai_pdf_parser.models import BBox, Block, Cell, CellStructure, Image, RenderInfo, Table, TableStructure, TextBlock, TextChar
from tests.conftest import make_pdf_with_image


FIXTURE_DIR = Path(__file__).parent / "fixtures"
BASELINE_PATH = FIXTURE_DIR / "rust_public_api" / "python_baseline.json"
FULL_PAGE = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
API_NAMES = {
    "text_region", "table_region", "table_structure", "images",
    "image_region", "render_pages", "render_region", "classify_page",
}


def test_python_wrapper_dispatches_all_path_operations(monkeypatch, tmp_path):
    requests = []

    def fake_run(request):
        requests.append(request)
        return {"data": [] if not request.get("single") else None}

    monkeypatch.setattr(pdfium_api, "_run", fake_run)
    parser = PDFParser("input.pdf", render_dpi=96, ml_model_path="model.onnx", ml_confidence=0.7)
    region = {"page_index": 2, "x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.9}
    parser.extract_text_in_region(region)
    parser.extract_table_in_region(region)
    parser.extract_table_structure(page_indices=[2], region=region)
    parser.extract_images(str(tmp_path), page_indices=[2])
    parser.extract_image_in_region(region, str(tmp_path))
    parser.render_pages(str(tmp_path), dpi=144, page_indices=[2])
    parser.render_region(region, str(tmp_path), dpi=150)
    parser.classify_page(2)
    assert [r["operation"] for r in requests] == [
        "extract_text_in_region", "extract_table_in_region", "extract_table_structure",
        "extract_images", "extract_image_in_region", "render_pages", "render_region", "classify_page",
    ]
    assert all(r["pdf_path"] == "input.pdf" for r in requests)
    assert all(r["regions"] == [region] for r in (requests[i] for i in (0, 1, 2, 4, 6)))
    assert requests[1]["single"] is True
    assert requests[2]["page_indices"] == [2]
    assert requests[2]["ml_model_path"] == "model.onnx"
    assert requests[2]["ml_confidence"] == 0.7
    assert requests[3]["page_indices"] == [2]
    assert requests[3]["output_dir"] == str(tmp_path)
    assert requests[4]["single"] is True
    assert requests[5]["dpi"] == 144
    assert requests[6]["dpi"] == 150
    assert requests[7]["page_index"] == 2


def test_python_wrapper_converts_rust_dtos(monkeypatch):
    box = {"x0": 1, "y0": 2, "x1": 3, "y1": 4}
    responses = {
        "extract_text_in_region": [{"text": "a", "bbox": box, "lines": [{"text": "a", "bbox": box, "words": []}]}],
        "extract_table_in_region": {"bbox": box, "rows": 1, "cols": 1, "cells": [{"text": "a", "row_index": 0, "col_index": 0, "bbox": box, "rowspan": 1, "colspan": 1}], "confidence": 0.9, "source": "Region", "h_lines": None, "v_lines": None},
        "extract_table_structure": [{"bbox": box, "rows": 1, "cols": 1, "cells": [{"text": "a", "row_index": 0, "col_index": 0, "cell_coord": [[1, 2], [3, 2], [3, 4], [1, 4]], "bbox": box, "text_block": {"text": "a", "bbox": box, "chars": [{"text": "a", "bbox": box, "confidence": None}]}, "tl_row": 0, "tl_col": 0, "br_row": 0, "br_col": 0}], "confidence": None, "source": "Region"}],
        "extract_images": [{"bbox": box, "page_index": 0, "resource_index": 1, "width": 10, "height": 20, "path": "image.png", "ext": "png"}],
        "render_pages": [{"path": "page-000.png", "width": 100, "height": 200, "dpi": 96}],
    }
    monkeypatch.setattr(pdfium_api, "_run", lambda r: {"data": responses[r["operation"]]})
    parser = PDFParser("input.pdf")
    region = {"page_index": 0, "x0": 0, "y0": 0, "x1": 1, "y1": 1}
    block = parser.extract_text_in_region(region).data[0]
    table = parser.extract_table_in_region(region).data
    structure = parser.extract_table_structure(region=region).data[0]
    image = parser.extract_images("out").data[0]
    render = parser.render_pages("out").data[0]
    assert isinstance(block, Block) and isinstance(block.bbox, BBox) and isinstance(block.lines[0].bbox, BBox)
    assert isinstance(table, Table) and isinstance(table.cells[0], Cell)
    assert isinstance(structure, TableStructure) and isinstance(structure.cells[0], CellStructure)
    assert isinstance(structure.cells[0].text_block, TextBlock)
    assert isinstance(structure.cells[0].text_block.chars[0], TextChar)
    assert isinstance(image, Image) and isinstance(image.bbox, BBox)
    assert isinstance(render, RenderInfo)


def test_json_bridge_calls_rust_with_native_path_or_none(monkeypatch):
    calls = []
    monkeypatch.setattr(pdfium_api, "_library_path", lambda: None)
    monkeypatch.setattr(_pdf_fast, "run_public_pdf_api", lambda payload: calls.append(json.loads(payload)) or '{"data":"vector"}', raising=False)
    assert pdfium_api._run({"operation": "classify_page", "pdf_path": "input.pdf", "page_index": 0}) == {"data": "vector"}
    assert calls == [{"operation": "classify_page", "pdf_path": "input.pdf", "page_index": 0, "pdfium_library_path": None}]


def test_all_path_wrappers_avoid_pymupdf_open(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("PyMuPDF read on Rust path")

    monkeypatch.setattr(fitz, "open", forbidden)
    for name in ("get_text", "get_pixmap", "get_drawings", "get_images"):
        monkeypatch.setattr(fitz.Page, name, forbidden)
    monkeypatch.setattr(pdfium_api, "_run", lambda request: {"data": "vector" if request["operation"] == "classify_page" else (None if request.get("single") else [])})
    parser = PDFParser("input.pdf")
    calls = [
        parser.extract_text_in_region(FULL_PAGE),
        parser.extract_table_in_region(FULL_PAGE),
        parser.extract_table_structure(region=FULL_PAGE),
        parser.extract_images(str(tmp_path)),
        parser.extract_image_in_region(FULL_PAGE, str(tmp_path)),
        parser.render_pages(str(tmp_path)),
        parser.render_region(FULL_PAGE, str(tmp_path)),
        parser.classify_page(0),
    ]
    assert all(call.code >= 0 for call in calls)


def test_python_baseline_has_replayable_cases():
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert set(baseline["cases"]) == {
        "page_000_vector.pdf", "page_437_wireless.pdf",
        "page_705_scanned.pdf", "generated_image.pdf",
    }
    for case in baseline["cases"].values():
        assert set(case["apis"]) == API_NAMES
        for api in case["apis"].values():
            assert api["result"]["code"] in (0, 1)
            assert len(api["timing_ms"]["samples"]) == 5
            assert api["timing_ms"]["median"] >= 0
        for api_name in ("render_pages", "render_region"):
            data = case["apis"][api_name]["result"]["data"]
            renders = data if isinstance(data, list) else [data]
            for render in renders:
                assert render["path"] == render["file"]["name"]
                assert render["file"]["decoded"] is True
                assert render["file"]["width"] == render["width"]
                assert render["file"]["height"] == render["height"]

    images = baseline["cases"]["generated_image.pdf"]["apis"]["images"]["result"]["data"]
    assert images
    for image in images:
        assert image["path"] == image["file"]["name"]
        assert image["ext"] == image["file"]["ext"]
        assert len(image["file"]["sha256"]) == 64
        assert image["file"]["width"] > 0
        assert image["file"]["height"] > 0


def test_rust_batch_public_api_entry_exists():
    assert callable(_pdf_fast.run_public_pdf_api)


def test_pdfparser_path_apis_do_not_open_with_pymupdf(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("target API used PyMuPDF")

    monkeypatch.setattr(fitz, "open", forbidden)
    parser = PDFParser(str(FIXTURE_DIR / "page_000_vector.pdf"))
    result = parser.extract_text_in_region(FULL_PAGE)
    assert result.code == 1
    assert result.data


def make_repeated_image_pdf(path):
    make_pdf_with_image(path)
    with fitz.open(path) as document:
        xref = document[0].get_images(full=True)[0][0]
        document[0].insert_image(fitz.Rect(300, 300, 400, 400), xref=xref)
        document.saveIncr()
        assert len(document[0].get_image_rects(xref)) == 2


def test_extract_images_tracks_each_page_placement(tmp_path):
    pdf = tmp_path / "placements.pdf"
    make_repeated_image_pdf(pdf)
    result = json.loads(_pdf_fast.run_public_pdf_api(json.dumps({
        "operation": "extract_images", "pdf_path": str(pdf),
        "output_dir": str(tmp_path / "images"), "page_indices": [0],
    })))
    images = result["data"]
    assert len(images) == 2
    assert [image["resource_index"] for image in images] == [0, 1]
    assert images[0]["bbox"] != images[1]["bbox"]
    for image in images:
        assert (image["width"], image["height"]) == (10, 10)
        assert Path(image["path"]).exists()


def test_extract_image_region_preserves_write_scope(tmp_path):
    pdf = tmp_path / "placements.pdf"
    make_repeated_image_pdf(pdf)
    request = {
        "operation": "extract_image_in_region", "pdf_path": str(pdf),
        "output_dir": str(tmp_path / "images"), "single": True,
        "regions": [{"page_index": 0, "x0": 0.1, "y0": 0.1, "x1": 0.4, "y1": 0.3}],
    }
    image = json.loads(_pdf_fast.run_public_pdf_api(json.dumps(request)))["data"]
    assert image["resource_index"] == 0
    assert len(list((tmp_path / "images").glob("page-000-img-*"))) == 2
    request["single"] = False
    request["regions"] += [FULL_PAGE, {"page_index": 0, "x0": 0, "y0": 0, "x1": 0.01, "y1": 0.01}]
    images = json.loads(_pdf_fast.run_public_pdf_api(json.dumps(request)))["data"]
    assert [image["resource_index"] for image in images] == [0, 0, 1]


def test_rust_render_page_and_region_dimensions(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("target render API used PyMuPDF")

    monkeypatch.setattr(fitz.Page, "get_pixmap", forbidden)
    monkeypatch.setattr(fitz.Page, "get_text", forbidden)
    parser = PDFParser(str(FIXTURE_DIR / "page_000_vector.pdf"), render_dpi=72)
    full = parser.render_pages(str(tmp_path / "pages"), page_indices=[0])
    crop = parser.render_region(FULL_PAGE, str(tmp_path / "regions"), dpi=72)
    assert full.code == 1, full.message
    assert crop.code == 1, crop.message
    assert (full.data[0].width, full.data[0].height) == (597, 843)
    assert (crop.data.width, crop.data.height) == (597, 843)
    assert (tmp_path / "pages" / "page-000.png").is_file()
    assert (tmp_path / "regions" / "region-000-000.png").is_file()
