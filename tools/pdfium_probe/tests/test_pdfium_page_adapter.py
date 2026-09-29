import os
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
from pdfium_normalizer import NormalizedPage, normalize_raw_page
from pdfium_page_adapter import PageRect, PdfiumPageAdapter


def test_adapter_exposes_three_text_views():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("Hello world", 0, 10, 70, 20)]))
    )
    assert adapter.get_text("rawdict")["blocks"]
    assert adapter.get_text("dict")["blocks"]
    assert [item[4] for item in adapter.get_text("words")] == ["Hello", "world"]


def test_scanned_adapter_has_no_text():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("坏\ufffd字", 0, 10, 30, 20)]))
    )
    assert adapter.get_text("rawdict") == {"blocks": []}
    assert adapter.get_text("dict") == {"blocks": []}
    assert adapter.get_text("words") == []


def test_unknown_mode_fails_loudly():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("A", 0, 10, 10, 20)]))
    )
    with pytest.raises(ValueError, match="unsupported text mode"):
        adapter.get_text("html")


def test_adapter_number_and_rect():
    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    raw["page_index"] = 3
    raw["width"] = 250.0
    raw["height"] = 350.0
    adapter = PdfiumPageAdapter(normalize_raw_page(raw))

    assert adapter.number == 3
    assert isinstance(adapter.rect, tuple)
    assert adapter.rect == (0.0, 0.0, 250.0, 350.0)
    assert adapter.rect.x0 == 0.0
    assert adapter.rect.y0 == 0.0
    assert adapter.rect.x1 == 250.0
    assert adapter.rect.y1 == 350.0
    assert adapter.rect.width == 250.0
    assert adapter.rect.height == 350.0

    x0, y0, x1, y1 = adapter.rect
    assert (x0, y0, x1, y1) == (0.0, 0.0, 250.0, 350.0)

    try:
        import fitz
        f_rect = fitz.Rect(adapter.rect)
        assert f_rect.width == 250.0
        assert f_rect.height == 350.0
    except ImportError:
        pass


def test_adapter_drawings_and_snapshot_dto():
    drawing_item = {"drawing_index": 0, "rect": [10.0, 10.0, 50.0, 50.0]}
    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    norm_page = normalize_raw_page(raw)
    assert norm_page.page_snapshot is not None
    norm_page.page_snapshot["drawings"] = [drawing_item]

    adapter = PdfiumPageAdapter(norm_page)
    assert adapter.get_drawings(raw=True) == [drawing_item]
    assert len(adapter.get_drawings()) == 1
    assert adapter.get_drawings()[0]["type"] == "f"
    assert adapter.snapshot_dto() is norm_page.page_snapshot

    # Test drawings fallback from sidecar
    norm_page_sidecar = NormalizedPage(
        page_type="vector",
        page_snapshot={"page_index": 1, "page": {"width": 100, "height": 100}, "drawings": []},
        rawdict={"blocks": []},
        words=[],
        sidecar={"drawings": [drawing_item]},
        diagnostics={},
    )
    adapter_sidecar = PdfiumPageAdapter(norm_page_sidecar)
    assert adapter_sidecar.get_drawings(raw=True) == [drawing_item]
    assert len(adapter_sidecar.get_drawings()) == 1

    # Test scanned page drawings default
    scanned_norm = normalize_raw_page(make_raw_page([make_span("坏\ufffd字", 0, 10, 30, 20)]))
    scanned_adapter = PdfiumPageAdapter(scanned_norm)
    assert scanned_adapter.get_drawings() == []
    assert scanned_adapter.snapshot_dto() is None


def test_dict_view_preserves_characters_for_text_extractor():
    from hexai_pdf_parser.extractors.text_extractor import TextExtractor

    raw = make_raw_page([make_span("Hello world", 0, 10, 70, 20)])
    adapter = PdfiumPageAdapter(normalize_raw_page(raw))

    extractor = TextExtractor()
    blocks = extractor.extract_blocks(adapter)
    assert len(blocks) == 1
    assert len(blocks[0].lines) == 1
    assert blocks[0].lines[0].text == "Hello world"
    # Ensure characters were preserved in words rather than synthesized with equal spacing
    first_word = blocks[0].lines[0].words[0]
    assert len(first_word.chars) == len("Hello world")
    assert "".join(c.text for c in first_word.chars) == "Hello world"


def test_get_text_flags_and_kwargs_support():
    adapter = PdfiumPageAdapter(
        normalize_raw_page(make_raw_page([make_span("Hello", 0, 10, 50, 20)]))
    )
    rawdict_result = adapter.get_text("rawdict", flags=1)
    assert rawdict_result["blocks"]
    dict_result = adapter.get_text("dict", flags=1)
    assert dict_result["blocks"]
    words_result = adapter.get_text("words", flags=0)
    assert len(words_result) == 1


def test_adapter_get_pixmap():
    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    raw["width"] = 100.0
    raw["height"] = 200.0
    adapter = PdfiumPageAdapter(normalize_raw_page(raw))

    # Test blank fallback pixmap when no file attached
    pix = adapter.get_pixmap(dpi=72)
    assert pix.width == 100
    assert pix.height == 200
    assert pix.n == 3
    assert len(pix.samples) == 100 * 200 * 3
    assert hasattr(pix, "stride")
    assert pix.stride == 100 * 3
    assert pix.tobytes() == pix.samples

    # Test matrix scaling
    try:
        import fitz
        mat = fitz.Matrix(2.0, 2.0)
        pix2 = adapter.get_pixmap(matrix=mat)
        assert pix2.width == 200
        assert pix2.height == 400
    except ImportError:
        pass


def test_adapter_adapted_drawings():
    drawing_raw = {
        "drawing_index": 0,
        "path_type": "filled",
        "rect": {"x0": 10.0, "y0": 20.0, "x1": 50.0, "y1": 60.0},
        "width": 1.0,
        "color": None,
        "fill": None,
        "items": [
            {"cmd": "l", "points": [[10.0, 20.0], [50.0, 20.0]]},
            {"cmd": "l", "points": [[50.0, 20.0], [50.0, 60.0]]},
        ],
    }
    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    norm_page = normalize_raw_page(raw)
    norm_page.page_snapshot["drawings"] = [drawing_raw]
    adapter = PdfiumPageAdapter(norm_page)

    # raw=True returns original snapshot items
    assert adapter.get_drawings(raw=True) == [drawing_raw]

    # default returns PyMuPDF-compatible dictionaries
    drawings = adapter.get_drawings()
    assert len(drawings) == 1
    d = drawings[0]
    assert d["type"] == "f"
    assert d["fill"] == (0.0, 0.0, 0.0)
    assert hasattr(d["rect"], "x0")
    assert d["rect"].x0 == 10.0
    assert len(d["items"]) == 2
    assert d["items"][0][0] == "l"
    p1 = d["items"][0][1]
    assert hasattr(p1, "x")
    assert p1.x == 10.0


def test_adapter_extracts_wired_tables_on_real_credit_report():
    import json
    from hexai_pdf_parser.tables.table_extractor import TableExtractor

    snapshot_path = _TEST_DIR.parent / "test_data/real_pdfium_output/credit_p1_detail_pdfium.json"
    if not snapshot_path.is_file():
        pytest.skip("credit_p1_detail_pdfium.json not present")

    raw_snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
    raw_page = raw_snap["pages"][0]
    norm_page = normalize_raw_page(raw_page)
    adapter = PdfiumPageAdapter(norm_page)

    extractor = TableExtractor()
    tables = extractor.extract(adapter)
    # credit_p1 has 6 tables
    assert len(tables) == 6
    assert all(t.rows > 1 and t.cols > 1 for t in tables)


def test_no_pypdfium2_dependency_in_page_adapter(tmp_path: Path):
    adapter_path = Path("tools/pdfium_probe/scripts/pdfium_page_adapter.py")
    if not adapter_path.is_file():
        adapter_path = _SCRIPTS_DIR / "pdfium_page_adapter.py"
    adapter_src = adapter_path.read_text(encoding="utf-8")
    assert "pypdfium2" not in adapter_src, "Found pypdfium2 reference in pdfium_page_adapter.py!"

    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    adapter = PdfiumPageAdapter(normalize_raw_page(raw))
    pix = adapter.get_pixmap(dpi=72)
    assert pix is not None
    assert pix.n == 3

    blank_png = tmp_path / "test_blank.png"
    pix.save(blank_png)
    assert blank_png.is_file()
    assert blank_png.stat().st_size > 0

    pdf_file = _TEST_DIR.parent / "test_data/synthetic/synth_crop_offset.pdf"
    if pdf_file.is_file():
        adapter_pdf = PdfiumPageAdapter(normalize_raw_page(raw), pdf_path=pdf_file)
        pix_pdf = adapter_pdf.get_pixmap(dpi=72)
        assert pix_pdf is not None
        assert pix_pdf.width > 0
        assert pix_pdf.height > 0
        assert pix_pdf.n == 3
        assert len(pix_pdf.samples) == pix_pdf.width * pix_pdf.height * 3

        pdf_png = tmp_path / "test_pdf.png"
        pix_pdf.save(pdf_png)
        assert pdf_png.is_file()
        assert pdf_png.stat().st_size > 0


def test_dynamic_subprocess_render_and_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import subprocess
    import pdfium_page_adapter
    from pdfium_page_adapter import PdfiumPixmap, _find_pdfium_probe_bin

    pdf_file = _TEST_DIR.parent / "test_data/synthetic/synth_crop_offset.pdf"
    if not pdf_file.is_file():
        pytest.skip(f"Test pdf {pdf_file} not found")

    probe_bin = _find_pdfium_probe_bin()
    if probe_bin is None or not probe_bin.is_file():
        pytest.skip("pdfium_probe binary not compiled/found")

    raw = make_raw_page([make_span("Hello", 0, 10, 50, 20)])
    adapter = PdfiumPageAdapter(normalize_raw_page(raw), pdf_path=pdf_file)

    # 1. Force dynamic subprocess rendering by mocking _find_prerendered_png to return None
    monkeypatch.setattr(pdfium_page_adapter, "_find_prerendered_png", lambda *args, **kwargs: None)

    real_run = subprocess.run
    captured_commands = []

    def tracking_run(cmd, *args, **kwargs):
        captured_commands.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(pdfium_page_adapter.subprocess, "run", tracking_run)

    pix = adapter.get_pixmap(dpi=72)
    assert len(captured_commands) == 1
    cmd = captured_commands[0]
    assert cmd[1] == "render"
    assert cmd[2] == str(pdf_file)
    assert cmd[3] == "0"
    assert cmd[4] == "72"

    assert isinstance(pix, PdfiumPixmap)
    assert pix.width > 0
    assert pix.height > 0
    assert pix.n == 3
    assert len(pix.samples) == pix.width * pix.height * 3

    # 2. Test timeout handling
    def timing_out_run(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    monkeypatch.setattr(pdfium_page_adapter.subprocess, "run", timing_out_run)

    # get_pixmap should catch TimeoutExpired and gracefully fall back without raising
    pix_timeout = adapter.get_pixmap(dpi=72)
    assert isinstance(pix_timeout, PdfiumPixmap)
    assert pix_timeout.width > 0
    assert pix_timeout.height > 0


def test_find_pdfium_probe_bin_with_cargo_target_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from pdfium_page_adapter import _find_pdfium_probe_bin

    fake_target = tmp_path / "custom_cargo_target"
    fake_release = fake_target / "release"
    fake_release.mkdir(parents=True)
    fake_bin = fake_release / ("pdfium_probe.exe" if os.name == "nt" else "pdfium_probe")
    fake_bin.write_bytes(b"mock_bin")

    monkeypatch.setenv("CARGO_TARGET_DIR", str(fake_target))
    found = _find_pdfium_probe_bin()
    assert found == fake_bin
