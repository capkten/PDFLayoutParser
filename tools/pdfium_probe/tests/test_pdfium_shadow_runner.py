import copy
from pathlib import Path
import sys

_TEST_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TEST_DIR.parent / "scripts"
_SRC_DIR = _TEST_DIR.parents[2] / "src"

for path_str in (str(_TEST_DIR), str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from typing import Any, Dict, List, Optional
import pytest

from fixtures_normalizer import make_raw_page, make_span
from pdfium_normalizer import normalize_drawings, normalize_raw_page
from pdfium_page_adapter import PageRect, PdfiumPageAdapter
from pdfium_shadow_runner import run_shadow_page


class _MockPyMuPDFPage:
    def __init__(self, raw_page: Dict[str, Any], images: Optional[List[Any]] = None) -> None:
        self._raw_page = raw_page
        self._images = images or []
        self.width = float(raw_page.get("width", 100.0))
        self.height = float(raw_page.get("height", 100.0))
        self.size = (self.width, self.height)
        self.rotation = int(raw_page.get("rotation", 0))
        self.rect = PageRect(0.0, 0.0, self.width, self.height)
        self.number = int(raw_page.get("page_index", 0))

    def get_text(self, kind: str, flags: Optional[int] = None, clip: Optional[Any] = None) -> Any:
        adapter = PdfiumPageAdapter(normalize_raw_page(self._raw_page))
        return adapter.get_text(kind, flags=flags)

    def get_drawings(self, extended: bool = False) -> List[Dict[str, Any]]:
        return normalize_drawings(self._raw_page)

    def get_images(self, full: bool = False) -> List[Any]:
        return list(self._images)

    def get_image_info(self, xrefs: bool = False) -> List[Any]:
        return []

    def get_fonts(self, full: bool = False) -> List[Any]:
        return []


def test_scanned_shadow_skips_tables_and_text(tmp_path: Path) -> None:
    raw = make_raw_page([make_span("坏\ufffd字", 0, 10, 30, 20)])
    result = run_shadow_page(
        pdfium_raw_page=raw,
        pymupdf_page=None,
        page_index=0,
        table_regions=[{"x0": 0.0, "y0": 0.0, "x1": 30.0, "y1": 20.0}],
        output_dir=tmp_path,
    )
    assert result["pdfium_page_type"] == "scanned"
    assert result["tables"]["pdfium"] == []
    assert result["pdfium_markdown"] == ""
    assert result["status"] == "compared"


def test_page_classification_disagreement_is_unsupported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pdfium_shadow_runner

    monkeypatch.setattr(pdfium_shadow_runner, "classify_page_type", lambda page: "vector")
    result = pdfium_shadow_runner.run_shadow_page(
        pdfium_raw_page=make_raw_page([make_span("坏\ufffd字", 0, 10, 30, 20)]),
        pymupdf_page=object(),
        page_index=0,
        output_dir=tmp_path,
    )
    assert result["status"] == "unsupported"
    assert "page_classification" in result["diff"]["categories"]
    assert result["pdfium_markdown"] == ""


def test_vector_shadow_runner_outputs_files(tmp_path: Path) -> None:
    raw = make_raw_page([make_span("Hello PDFium", 10, 10, 80, 25, order=0)])
    py_page = _MockPyMuPDFPage(raw)

    result = run_shadow_page(
        pdfium_raw_page=raw,
        pymupdf_page=py_page,
        page_index=0,
        table_regions=[],
        output_dir=tmp_path,
    )
    assert result["status"] == "compared"
    assert result["pdfium_page_type"] == "vector"
    assert result["pymupdf_page_type"] == "vector"
    assert "Hello PDFium" in result["pdfium_markdown"]
    assert "Hello PDFium" in result["pymupdf_markdown"]

    for fname in (
        "pdfium.md",
        "pymupdf.md",
        "layout_signature.json",
        "table_signature.json",
        "diff.json",
        "diagnostics.json",
        "errors.json",
    ):
        file_path = tmp_path / fname
        assert file_path.exists(), f"Expected output file {fname} not found"
        assert file_path.stat().st_size > 0 or fname in ("pdfium.md", "pymupdf.md")


def test_wireless_table_region_in_shadow_runner(tmp_path: Path) -> None:
    # 2x2 grid of spans inside table region [10, 10, 90, 50]
    spans = [
        make_span("Cell11", 15, 15, 45, 25, order=0),
        make_span("Cell12", 55, 15, 85, 25, order=1),
        make_span("Cell21", 15, 35, 45, 45, order=2),
        make_span("Cell22", 55, 35, 85, 45, order=3),
    ]
    raw = make_raw_page(spans)
    py_page = _MockPyMuPDFPage(raw)

    result = run_shadow_page(
        pdfium_raw_page=raw,
        pymupdf_page=py_page,
        page_index=0,
        table_regions=[{"kind": "wireless", "x0": 10.0, "y0": 10.0, "x1": 90.0, "y1": 50.0}],
        output_dir=tmp_path,
    )
    assert result["status"] == "compared"
    pdfium_tables = result["tables"]["pdfium"]
    assert len(pdfium_tables) == 1
    assert pdfium_tables[0].rows >= 2
    assert pdfium_tables[0].cols >= 2


def test_wired_table_region_in_shadow_runner(tmp_path: Path) -> None:
    # Simple wired table: h_lines at y=10, 30, 50; v_lines at x=10, 50, 90
    drawings = [
        {
            "drawing_index": 0,
            "path_type": "stroked",
            "rect": [10, 10, 90, 10],
            "width": 1.0,
            "items": [{"cmd": "l", "points": [[10, 10], [90, 10]]}],
        },
        {
            "drawing_index": 1,
            "path_type": "stroked",
            "rect": [10, 30, 90, 30],
            "width": 1.0,
            "items": [{"cmd": "l", "points": [[10, 30], [90, 30]]}],
        },
        {
            "drawing_index": 2,
            "path_type": "stroked",
            "rect": [10, 50, 90, 50],
            "width": 1.0,
            "items": [{"cmd": "l", "points": [[10, 50], [90, 50]]}],
        },
        {
            "drawing_index": 3,
            "path_type": "stroked",
            "rect": [10, 10, 10, 50],
            "width": 1.0,
            "items": [{"cmd": "l", "points": [[10, 10], [10, 50]]}],
        },
        {
            "drawing_index": 4,
            "path_type": "stroked",
            "rect": [50, 10, 50, 50],
            "width": 1.0,
            "items": [{"cmd": "l", "points": [[50, 10], [50, 50]]}],
        },
        {
            "drawing_index": 5,
            "path_type": "stroked",
            "rect": [90, 10, 90, 50],
            "width": 1.0,
            "items": [{"cmd": "l", "points": [[90, 10], [90, 50]]}],
        },
    ]
    spans = [
        make_span("A", 15, 15, 30, 25, order=0),
        make_span("B", 55, 15, 70, 25, order=1),
        make_span("C", 15, 35, 30, 45, order=2),
        make_span("D", 55, 35, 70, 45, order=3),
    ]
    raw = make_raw_page(spans, drawings=drawings)
    py_page = _MockPyMuPDFPage(raw)

    result = run_shadow_page(
        pdfium_raw_page=raw,
        pymupdf_page=py_page,
        page_index=0,
        table_regions=[{"kind": "wired", "x0": 10.0, "y0": 10.0, "x1": 90.0, "y1": 50.0}],
        output_dir=tmp_path,
    )
    assert result["status"] == "compared"
    pdfium_tables = result["tables"]["pdfium"]
    assert len(pdfium_tables) == 1
    assert pdfium_tables[0].rows == 2
    assert pdfium_tables[0].cols == 2


def test_unsupported_unknown_path_type_wired_drawing(tmp_path: Path) -> None:
    drawings = [
        {
            "drawing_index": 0,
            "path_type": "unknown",
            "rect": [10, 10, 90, 10],
            "width": 1.0,
            "items": [{"cmd": "l", "points": [[10, 10], [90, 10]]}],
        },
    ]
    raw = make_raw_page([make_span("Table Title", 10, 5, 80, 15)], drawings=drawings)
    py_page = _MockPyMuPDFPage(raw)

    result = run_shadow_page(
        pdfium_raw_page=raw,
        pymupdf_page=py_page,
        page_index=0,
        table_regions=[{"kind": "wired", "x0": 10.0, "y0": 10.0, "x1": 90.0, "y1": 50.0}],
        output_dir=tmp_path,
    )
    assert result["status"] == "unsupported"


def test_unmodeled_image_element_in_shadow_runner(tmp_path: Path) -> None:
    raw = make_raw_page([make_span("Text with image", 10, 10, 80, 20)])
    py_page = _MockPyMuPDFPage(raw, images=[(1, 0, 100, 100, 8, "DeviceRGB", "", "Im1", "DCTDecode")])

    result = run_shadow_page(
        pdfium_raw_page=raw,
        pymupdf_page=py_page,
        page_index=0,
        output_dir=tmp_path,
    )
    assert result["status"] == "unsupported"
    assert "unsupported_element_kind" in result["diff"]["categories"]


def test_page_rect_tuple_argument_and_copy() -> None:
    # 4 floats
    r1 = PageRect(0.0, 10.0, 100.0, 200.0)
    assert r1.x0 == 0.0
    assert r1.y0 == 10.0
    assert r1.x1 == 100.0
    assert r1.y1 == 200.0
    assert r1.width == 100.0
    assert r1.height == 190.0

    # single tuple argument
    r2 = PageRect((0.0, 10.0, 100.0, 200.0))
    assert r2 == r1
    assert r2.width == 100.0

    # copy and deepcopy
    c1 = copy.copy(r1)
    assert c1 == r1
    assert isinstance(c1, PageRect)
    assert c1.x0 == 0.0

    c2 = copy.deepcopy(r1)
    assert c2 == r1
    assert isinstance(c2, PageRect)
    assert c2.y1 == 200.0


def test_run_shadow_page_with_auto_detect_tables(tmp_path: Path) -> None:
    raw = make_raw_page([make_span("Hello PDFium", 10, 10, 80, 25, order=0)])
    py_page = _MockPyMuPDFPage(raw)

    result = run_shadow_page(
        pdfium_raw_page=raw,
        pymupdf_page=py_page,
        page_index=0,
        output_dir=tmp_path,
        auto_detect_tables=True,
    )
    assert result["status"] == "compared"
    assert result["pdfium_page_type"] == "vector"
    assert "Hello PDFium" in result["pdfium_markdown"]
