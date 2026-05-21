import json
from pathlib import Path
from types import SimpleNamespace

import fitz


def _make_demo_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=320, height=220)
    page.insert_text((30, 30), "Item")
    page.insert_text((150, 30), "Current")
    page.insert_text((240, 30), "Prior")
    page.insert_text((30, 60), "Deposit")
    page.insert_text((150, 60), "10")
    page.insert_text((240, 60), "20")
    doc.save(str(path))
    doc.close()


def test_camelot_stream_demo_writes_preview_and_summary(tmp_dir, monkeypatch):
    pdf_path = Path(tmp_dir) / "demo.pdf"
    out_dir = Path(tmp_dir) / "out"
    _make_demo_pdf(pdf_path)

    fake_table = SimpleNamespace(
        shape=(2, 3),
        df=SimpleNamespace(
            to_dict=lambda orient="records": [
                {"0": "Item", "1": "Current", "2": "Prior"},
                {"0": "Deposit", "1": "10", "2": "20"},
            ]
        ),
        _bbox=(20.0, 20.0, 300.0, 90.0),
    )

    fake_camelot = SimpleNamespace(
        read_pdf=lambda *args, **kwargs: [fake_table],
    )
    monkeypatch.setitem(__import__("sys").modules, "camelot", fake_camelot)

    from pdflayoutparser.camelot_stream_demo import run_camelot_stream_demo

    result = run_camelot_stream_demo(str(pdf_path), page=1, output_dir=str(out_dir))

    preview_path = Path(result["preview_path"])
    summary_path = Path(result["summary_path"])

    assert preview_path.exists()
    assert preview_path.suffix.lower() == ".png"
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["page"] == 1
    assert summary["table_count"] == 1
    assert summary["tables"][0]["rows"] == 2
    assert summary["tables"][0]["cols"] == 3
