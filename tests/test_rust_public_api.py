"""Migration checks for the public PDF APIs."""

import json
from pathlib import Path

import fitz

from hexai_pdf_parser import _pdf_fast
from hexai_pdf_parser.pdf_parser import PDFParser


FIXTURE_DIR = Path(__file__).parent / "fixtures"
BASELINE_PATH = FIXTURE_DIR / "rust_public_api" / "python_baseline.json"
FULL_PAGE = {"page_index": 0, "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
API_NAMES = {
    "text_region", "table_region", "table_structure", "images",
    "image_region", "render_pages", "render_region", "classify_page",
}


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
