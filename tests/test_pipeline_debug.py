from pathlib import Path

import fitz

from hexai_pdf_parser.pipeline import Pipeline


def test_debug_pipeline_writes_all_stage_artifacts(tmp_dir):
    pdf_path = Path(tmp_dir) / "debug_pipeline.pdf"
    output_dir = Path(tmp_dir) / "out"
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_text((40, 60), "A")
    doc.save(str(pdf_path))
    doc.close()

    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
        debug_pipeline=True,
        backend="sequential",
    ).run()

    debug_dir = output_dir / "debug" / "pipeline" / "page-000"
    expected = [
        "00-original.png",
        "01-drawings.png",
        "02-lines.png",
        "03-regions.png",
        "04-cells.png",
        "05-text-alignment.png",
        "06-final-tables.png",
        "debug.json",
    ]
    assert all((debug_dir / name).exists() for name in expected)
    assert all((debug_dir / name).stat().st_size > 0 for name in expected)
