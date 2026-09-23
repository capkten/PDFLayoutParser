from __future__ import annotations

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.wireless_table_recovery import WirelessRecovery
from hexai_pdf_parser.debug.rust_task5_acceptance import (
    compare_normalized,
    normalize_recovery,
    normalize_region_result,
)
from scripts.run_task5_shadow_acceptance import (
    build_page_payload,
    clear_mode_overrides,
    _summarize_mismatches,
)


def _cell(text: str, row: int, col: int, bbox: tuple[float, float, float, float]) -> Cell:
    return Cell(text=text, row_index=row, col_index=col, bbox=BBox(*bbox))


def test_normalize_recovery_preserves_cells_empty_slots_and_occupancy():
    table = Table(
        bbox=BBox(10, 20, 110, 80),
        rows=2,
        cols=2,
        source="wireless_span_recovery",
        cells=[
            _cell("项目", 0, 0, (10, 20, 60, 50)),
            _cell("", 0, 1, (60, 20, 110, 50)),
            _cell("收入", 1, 0, (10, 50, 60, 80)),
            _cell("100", 1, 1, (60, 50, 110, 80)),
        ],
    )
    recovery = WirelessRecovery(
        tables=[table],
        diagnostics={"page_index": 184, "regions": []},
    )

    normalized = normalize_recovery(recovery, page_index=184, mode="python")

    assert normalized["page_index"] == 184
    assert normalized["mode"] == "python"
    assert normalized["tables"][0]["source"] == "wireless_span_recovery"
    assert normalized["tables"][0]["cells"][1]["text"] == ""
    assert normalized["tables"][0]["occupancy"]["missing_slots"] == []
    assert normalized["tables"][0]["occupancy"]["duplicate_slots"] == []
    assert normalized["tables"][0]["occupancy"]["conflicts"] == []


def test_normalize_recovery_keeps_diagnostic_fields_without_traceback_repr():
    recovery = WirelessRecovery(
        tables=[],
        diagnostics={
            "source": "rust",
            "rust": [
                {
                    "status": "rust_fallback",
                    "path": "task5/entry",
                    "error_type": "ValueError",
                    "message": "fallback",
                    "traceback_id": "private traceback",
                    "python_value": {"str_val": "large repr"},
                }
            ],
        },
    )

    diagnostics = normalize_recovery(recovery, page_index=184, mode="rust")["diagnostics"]

    assert diagnostics["source"] == "rust"
    assert diagnostics["rust"] == [
        {
            "error_type": "ValueError",
            "message": "fallback",
            "path": "task5/entry",
            "status": "rust_fallback",
        }
    ]


def test_normalize_region_result_records_grid_and_cell_spans():
    region = BBox(0, 0, 100, 60)
    result = (
        2,
        2,
        [
            _cell("父", 0, 0, (0, 0, 50, 30)),
            _cell("叶", 0, 1, (50, 0, 100, 30)),
            _cell("值", 1, 0, (0, 30, 50, 60)),
            _cell("", 1, 1, (50, 30, 100, 60)),
        ],
    )

    normalized = normalize_region_result(result, region, page_index=188, mode="rust")

    assert normalized["rows"] == 2
    assert normalized["cols"] == 2
    assert normalized["region"] == [0.0, 0.0, 100.0, 60.0]
    assert normalized["cells"][0]["rowspan"] == 1
    assert normalized["occupancy"]["covered_slots"] == 4


def test_compare_normalized_reports_field_level_table_mismatch():
    python_value = {"tables": [{"rows": 2, "cols": 2}]}
    rust_value = {"tables": [{"rows": 3, "cols": 2}]}

    mismatches = compare_normalized(python_value, rust_value, entry="page-184")

    assert mismatches == [
        {
            "entry": "page-184",
            "layer": "tables",
            "field": "rows",
            "python_value": 2,
            "rust_value": 3,
        }
    ]


def test_compare_normalized_ignores_execution_mode_and_tiny_bbox_noise():
    python_value = {
        "mode": "python",
        "tables": [{"bbox": [1.0, 2.0, 3.0, 4.0]}],
    }
    rust_value = {
        "mode": "rust",
        "tables": [{"bbox": [1.005, 1.997, 3.0, 4.008]}],
    }

    assert compare_normalized(python_value, rust_value, entry="page-184") == []


def test_shadow_contract_keeps_python_value_and_records_mismatch():
    rust_adapter.clear_diagnostics()

    result = rust_adapter.run_python_or_rust(
        mode="shadow",
        python_fn=lambda: {"mode": "python"},
        rust_fn=lambda: {"mode": "rust"},
        path="task5/test-shadow",
    )

    assert result == {"mode": "python"}
    diagnostics = rust_adapter.get_diagnostics()
    assert diagnostics[-1]["status"] == "rust_output_mismatch"
    assert diagnostics[-1]["path"] == "task5/test-shadow"


def test_build_page_payload_records_artifacts_and_region_results():
    table = Table(
        bbox=BBox(10, 20, 110, 80),
        rows=1,
        cols=1,
        source="wireless_span_recovery",
        cells=[_cell("项目", 0, 0, (10, 20, 110, 80))],
    )
    recovery = WirelessRecovery(tables=[table], diagnostics={"source": "python"})
    region_result = normalize_region_result(
        (1, 1, table.cells), BBox(10, 20, 110, 80), page_index=184, mode="python"
    )

    payload = build_page_payload(
        recovery=recovery,
        page_index=184,
        mode="python",
        pdf_path="D:/input.pdf",
        input_sha256="abc123",
        language="mixed",
        artifacts={"json": "D:/out/page-184.json", "png": "D:/out/page-184.png"},
        region_results=[region_result],
        routing_diagnostics=[],
    )

    assert payload["page_index"] == 184
    assert payload["mode"] == "python"
    assert payload["input_sha256"] == "abc123"
    assert payload["language"] == "mixed"
    assert payload["artifacts"]["png"].endswith("page-184.png")
    assert payload["regions"][0]["rows"] == 1
    assert payload["tables"][0]["occupancy"]["conflicts"] == []


def test_clear_mode_overrides_forces_one_global_mode(monkeypatch):
    monkeypatch.setenv("PDF_RUST_MODE", "python")
    monkeypatch.setenv("PDF_RUST_MODE_WIRELESS_STRUCTURE", "rust")
    monkeypatch.setenv("PDF_RUST_MODE_WIRELESS_TABLE_RECOVERY", "shadow")

    clear_mode_overrides("rust")

    assert rust_adapter.get_rust_mode("wireless_structure") == "rust"
    assert rust_adapter.get_rust_mode("wireless_table_recovery") == "rust"


def test_mismatch_summary_separates_structure_from_routing_diagnostics():
    mismatches = [
        {"entry": "rust:page-184", "layer": "tables"},
        {"entry": "rust:page-184", "layer": "routing_diagnostics"},
    ]

    summary = _summarize_mismatches(mismatches)

    assert summary["structural_mismatch_count"] == 1
    assert summary["routing_diagnostic_count"] == 1
    assert summary["mismatch_count"] == 2
    assert len(mismatches) == 2
