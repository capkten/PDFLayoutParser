from __future__ import annotations

from scripts.verify_personal_credit_rust_e2e import (
    configure_rust_modes,
    compare_table_payloads,
    discover_pdfs,
    render_table_overlays,
    select_pdf_paths,
    _child_environment,
)


def test_compare_table_payloads_reports_cell_field_difference():
    python_tables = [
        {
            "source": "line_projection",
            "rows": 1,
            "cols": 1,
            "confidence": 0.9,
            "bbox": [0.0, 0.0, 20.0, 20.0],
            "cells": [
                {
                    "text": "Python",
                    "row_index": 0,
                    "col_index": 0,
                    "bbox": [0.0, 0.0, 20.0, 20.0],
                    "rowspan": 1,
                    "colspan": 1,
                }
            ],
        }
    ]
    rust_tables = [
        {
            **python_tables[0],
            "cells": [{**python_tables[0]["cells"][0], "text": "Rust"}],
        }
    ]

    result = compare_table_payloads(python_tables, rust_tables)

    assert result["mismatch_count"] == 1
    assert result["mismatches"][0]["field"] == "tables[0].cells[0].text"


def test_compare_table_payloads_reports_page_assignment_difference():
    table = {
        "_page_index": 0,
        "source": "line_projection",
        "rows": 1,
        "cols": 1,
        "bbox": [0.0, 0.0, 20.0, 20.0],
        "cells": [],
    }

    result = compare_table_payloads([table], [{**table, "_page_index": 1}])

    assert result["mismatch_count"] == 1
    assert result["mismatches"][0]["field"] == "tables[0]._page_index"


def test_discover_pdfs_returns_sorted_relative_paths(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "z.pdf").write_bytes(b"z")
    (tmp_path / "nested" / "a.PDF").write_bytes(b"a")
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")

    assert discover_pdfs(tmp_path) == ["nested/a.PDF", "z.pdf"]


def test_select_pdf_paths_preserves_discovery_order():
    assert select_pdf_paths(
        ["a.pdf", "b.pdf", "c.pdf"], ["c.pdf", "a.pdf"]
    ) == ["a.pdf", "c.pdf"]


def test_configure_rust_modes_supports_path_specific_stage_overrides():
    environment = {"PDF_RUST_MODE_WIRED": "shadow", "OTHER": "keep"}

    configured = configure_rust_modes(
        environment,
        generic_mode="python",
        personal_mode="rust",
        path_modes={"wireless-structure": "shadow"},
    )

    assert configured["OTHER"] == "keep"
    assert configured["PDF_RUST_MODE"] == "python"
    assert configured["PDF_RUST_MODE_PERSONAL_CREDIT"] == "rust"
    assert configured["PDF_RUST_MODE_WIRELESS_STRUCTURE"] == "shadow"
    assert "PDF_RUST_MODE_WIRED" not in configured


def test_child_environment_preserves_generic_mode_selection(tmp_path):
    environment = _child_environment(
        {"OTHER": "keep"},
        source_root=tmp_path,
        task_mode="rust",
        generic_mode="python",
        path_modes={"wired": "rust"},
    )

    assert environment["PDF_RUST_MODE"] == "python"
    assert environment["PDF_RUST_MODE_PERSONAL_CREDIT"] == "rust"
    assert environment["PDF_RUST_MODE_WIRED"] == "rust"
    assert environment["PYTHONPATH"].endswith("src")


def test_render_table_overlays_creates_page_pngs(tmp_path):
    import fitz

    document = fitz.open()
    page = document.new_page(width=100, height=100)
    page.insert_text((20, 30), "A", fontsize=10)
    pdf_path = tmp_path / "sample.pdf"
    document.save(pdf_path)
    document.close()
    pages = [
        {
            "index": 0,
            "tables": [
                {
                    "bbox": {"x0": 10, "y0": 10, "x1": 50, "y1": 50},
                    "cells": [
                        {
                            "bbox": {"x0": 10, "y0": 10, "x1": 30, "y1": 50},
                            "rowspan": 1,
                            "colspan": 1,
                        },
                        {
                            "bbox": {"x0": 30, "y0": 10, "x1": 50, "y1": 50},
                            "rowspan": 1,
                            "colspan": 1,
                        },
                    ],
                }
            ],
        }
    ]

    hashes = render_table_overlays(pdf_path, pages, tmp_path / "overlays")

    assert list(hashes) == ["page-000.png"]
    assert (tmp_path / "overlays" / "page-000.png").is_file()
