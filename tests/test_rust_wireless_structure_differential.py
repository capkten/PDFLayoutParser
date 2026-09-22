"""Task 4A field-level differential contract for wireless structure migration."""

from __future__ import annotations

import hashlib
import ast
import json
from pathlib import Path
from typing import Any

from hexai_pdf_parser import rust_adapter
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.columns import (
    infer_column_bands,
    prune_paired_cjk_artifact_bands,
    prune_sparse_alignment_artifact_bands,
)
from hexai_pdf_parser.tables.wireless_structure.continuations import merge_column_continuations
from hexai_pdf_parser.tables.wireless_structure.grid import build_grid
from hexai_pdf_parser.tables.wireless_structure.header_topology import (
    annotate_columns,
    refine_leaf_bands,
    rescue_header_only_leaf_bands,
    rescue_header_only_note_bands,
    rescue_sparse_body_bands,
)
from hexai_pdf_parser.tables.wireless_structure.logical_grid import build_logical_grid, materialize_empty_cells
from hexai_pdf_parser.tables.wireless_structure.merged_cells import merge_multiline_cells, merge_same_slot_fragments
from hexai_pdf_parser.tables.wireless_structure.recoverer import _commit_header_spans_or_keep_base

FIXTURE = Path(__file__).parent / "fixtures/rust_migration/wireless/wireless_structure_differential.json"
FIELDS = ("presence", "value", "ordering", "grouping", "bbox", "rowspan/colspan", "source-continuity", "diagnostics")
CLASSIFICATIONS = {"requires_adaptation", "defect", "unsupported"}
REQUIRED_FIXTURES = {
    "paired_cjk_artifact_band", "sparse_alignment_artifact_band", "header_only_note_rescue",
    "header_only_leaf_rescue", "near_center_different_physical_rows", "left_shifted_cjk_continuation",
    "independent_leaf_same_candidate_slot", "complete_two_leaf_parent", "incomplete_two_leaf_parent",
    "rowspan_empty_coverage", "rowspan_nonempty_title_rejected", "occupancy_conflict", "out_of_bounds", "empty_slot",
}


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _atoms(case: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, source in enumerate(case["atoms"]):
        atom = dict(source)
        flow = int(atom.get("flow_start", index))
        atom.setdefault("flow_end", flow)
        atom.setdefault("source_blocks", [0])
        atom.setdefault("source_line_start", index)
        atom.setdefault("source_line_end", atom["source_line_start"])
        atom.setdefault("source_position_known", True)
        atom.setdefault("span_refs", [f"S{flow}"])
        atom.setdefault("font_size", 10.0)
        atom.setdefault("script", "cjk")
        atom.setdefault("bold", False)
        atom.setdefault("order", flow)
        result.append(atom)
    return result


def _region(case: dict[str, Any]) -> BBox:
    return BBox(*case["region"])


def _bands(case: dict[str, Any], atoms: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None]:
    bands = [dict(item) for item in case.get("bands", [])]
    if not bands:
        bands = infer_column_bands(atoms, _region(case))
    for index, band in enumerate(bands, 1):
        band.setdefault("id", index)
        band.setdefault("support", len(band.get("source_atoms", [])))
        band.setdefault("y_support", band.get("support", 0))
        band.setdefault("source_atoms", [
            atom_index for atom_index, atom in enumerate(atoms)
            if min(atom["bbox"][2], band["x1"]) > max(atom["bbox"][0], band["x0"])
        ])
    action = case.get("band_action")
    if action == "paired_cjk":
        bands = prune_paired_cjk_artifact_bands(atoms, bands)
    elif action == "sparse_alignment":
        bands = prune_sparse_alignment_artifact_bands(atoms, bands)
    bands, inferred_cutoff = refine_leaf_bands(atoms, bands)
    cutoff = case.get("header_cutoff", inferred_cutoff)
    if case.get("rescue_sparse_body"):
        bands = rescue_sparse_body_bands(atoms, bands, cutoff)
    if action == "header_note":
        bands = rescue_header_only_note_bands(atoms, bands, cutoff)
    if action == "header_leaf":
        bands = rescue_header_only_leaf_bands(atoms, bands, cutoff)
    for index, band in enumerate(bands, 1):
        band["id"] = index
    return bands, cutoff


def _python_output(case: dict[str, Any]) -> dict[str, Any]:
    atoms = _atoms(case)
    bands, cutoff = _bands(case, atoms)
    annotate_columns(atoms, bands, cutoff, _region(case))
    candidates = merge_column_continuations(atoms, bands)
    rows, columns, physical, issues = build_grid(candidates, bands)
    cells = merge_same_slot_fragments(physical, cutoff)
    cells = merge_multiline_cells(cells, cutoff)
    logical_rows, logical_columns, logical = build_logical_grid(rows, columns, cells, cutoff)
    logical = _commit_header_spans_or_keep_base(logical, cutoff)
    empty_slots = _empty_slots(_occupancy(logical, len(logical_rows), len(logical_columns)))
    logical = materialize_empty_cells(logical_rows, rows, logical_columns, logical, _region(case))
    occupancy = _occupancy(logical, len(logical_rows), len(logical_columns))
    diagnostics = [{"status": "occupancy_conflict", "message": issue} for issue in issues]
    diagnostics.extend(_bounds_diagnostics(logical, _region(case)))
    return {"rows": rows, "bands": bands, "physical_cells": physical, "logical_cells": logical,
            "empty_slots": empty_slots, "occupancy": occupancy, "diagnostics": diagnostics, "atoms": atoms}


def _rust_atoms(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, atom in enumerate(atoms):
        x0, y0, x1, y1 = atom["bbox"]
        result.append({"schema_version": 1, "text": atom["text"],
                       "rect": {"schema_version": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1},
                       "run_refs": [index], "row_hint": None, "col_hint": None,
                       "order": int(atom.get("order", index)), "flow_start": int(atom.get("flow_start", index)),
                       "flow_end": int(atom.get("flow_end", index)), "source_blocks": list(atom.get("source_blocks", [0])),
                       "source_line_start": int(atom.get("source_line_start", index)),
                       "source_line_end": int(atom.get("source_line_end", index)),
                       "source_position_known": bool(atom.get("source_position_known", True)), "column_id": None})
    return result


def _rust_bands(bands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"schema_version": 1, "x0": float(band["x0"]), "x1": float(band["x1"]),
             "source_atoms": list(band.get("source_atoms", [])), "order": index,
             "id": int(band.get("id", index + 1)), "kind": band.get("kind"),
             "support": int(band.get("support", 0)), "y_support": int(band.get("y_support", 0)),
             "parent_x0": band.get("parent_x0"), "parent_x1": band.get("parent_x1"),
             "parent_leaf_count": band.get("parent_leaf_count")} for index, band in enumerate(bands)]


def _rust_output(case: dict[str, Any], python: dict[str, Any]) -> dict[str, Any]:
    atoms = _rust_atoms(python["atoms"])
    bands = _rust_bands(python["bands"])
    rust_rows, rust_columns, physical, grid_diagnostics = rust_adapter.build_grid(atoms, bands)
    x0, y0, x1, y1 = case["region"]
    input_dto = {"schema_version": 1,
                 "region": {"schema_version": 1, "rect": {"schema_version": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1}, "source_order": 0, "allowed": True},
                 "atoms": atoms, "bands": bands,
                 "config": {"schema_version": 1, "line_tolerance": 2.0, "row_tolerance": 2.0,
                            "column_tolerance": 2.0, "span_tolerance": 2.0, "numeric_tolerance": 2.0}}
    logical = rust_adapter.recover_native_region(input_dto)
    return {"rows": rust_rows, "bands": rust_columns, "physical_cells": physical,
            "logical_cells": logical["cells"], "empty_slots": logical["grid"]["empty_slots"],
            "occupancy": logical["grid"]["grid"]["occupancy"],
            "diagnostics": [*grid_diagnostics, *logical.get("diagnostics", [])], "atoms": atoms}


def _occupancy(cells: list[dict[str, Any]], rows: int, columns: int) -> list[list[int | None]]:
    result: list[list[int | None]] = [[None] * columns for _ in range(rows)]
    for index, cell in enumerate(cells):
        for row in range(int(cell["row_start"]), int(cell["row_end"]) + 1):
            for column in range(int(cell["col_start"]), int(cell["col_end"]) + 1):
                if 1 <= row <= rows and 1 <= column <= columns:
                    result[row - 1][column - 1] = index
    return result


def _empty_slots(occupancy: list[list[int | None]]) -> list[list[int]]:
    return [[row, column] for row, values in enumerate(occupancy) for column, value in enumerate(values) if value is None]


def _bounds_diagnostics(cells: list[dict[str, Any]], region: BBox) -> list[dict[str, Any]]:
    return [{"status": "out_of_bounds", "message": cell.get("cell_id", "")} for cell in cells
            if cell.get("bbox") and (cell["bbox"][0] < region.x0 or cell["bbox"][1] < region.y0 or cell["bbox"][2] > region.x1 or cell["bbox"][3] > region.y1)]


def _rect(item: dict[str, Any]) -> list[float] | None:
    if "bbox" in item:
        return list(item["bbox"])
    rect = item.get("rect")
    return None if rect is None else [rect["x0"], rect["y0"], rect["x1"], rect["y1"]]


def _position(item: dict[str, Any], side: str) -> tuple[int, int]:
    if "row_start" in item and item["row_start"] is not None:
        row = int(item["row_start"]) - 1
    else:
        row = int(item.get("row", 0))
    if "col_start" in item and item["col_start"] is not None:
        column = int(item["col_start"]) - 1
    else:
        column = int(item.get("col", 0))
    return row, column


def _stable_number(value: Any) -> str:
    return f"{float(value):.3f}"


def _source_continuity(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return {
        "source_blocks": item.get("source_blocks"),
        "source_line_start": item.get("source_line_start"),
        "source_line_end": item.get("source_line_end"),
        "source_refs": item.get("span_refs") or item.get("source_refs") or source.get("source_refs"),
    }


def _records(items: list[Any], layer: str, side: str) -> dict[str, dict[str, Any]]:
    result = {}
    duplicate_counts: dict[str, int] = {}
    for index, item in enumerate(items):
        if layer == "bands":
            identity, value, grouping = (
                f"B:{_stable_number(item['x0'])}:{_stable_number(item['x1'])}",
                [item["x0"], item["x1"]],
                item.get("source_atoms", []),
            )
        elif layer == "rows":
            row = int(item.get("row_index", int(item.get("id", index + 1)) - 1))
            identity, value, grouping = f"R:{row}", item.get("y", [item.get("y0"), item.get("y1")]), item.get("item_indices", item.get("source_rows", []))
        elif layer == "empty_slots":
            identity, value, grouping = f"E:{item[0]}:{item[1]}", "", item
        elif layer == "occupancy":
            identity, value, grouping = f"O:{index}", item, item
        elif layer == "diagnostics":
            identity, value, grouping = ":".join(str(item.get(key, "")) for key in ("status", "path", "field", "message")), item.get("status"), None
        else:
            row, column = _position(item, side)
            identity, value, grouping = f"C:{row}:{column}:{item.get('text', '')}", str(item.get("text", "")), item.get("source_refs") or item.get("run_refs") or item.get("merged_from", [])
        span = (int(item.get("rowspan", 1)), int(item.get("colspan", 1))) if isinstance(item, dict) and layer in {"physical_cells", "logical_cells"} else None
        record = {"presence": True, "value": value, "ordering": index, "grouping": grouping,
                  "bbox": _rect(item) if isinstance(item, dict) else None, "rowspan/colspan": span,
                  "source-continuity": _source_continuity(item) if isinstance(item, dict) else None,
                  "diagnostics": item.get("diagnostics", []) if isinstance(item, dict) else []}
        ordinal = duplicate_counts.get(identity, 0)
        duplicate_counts[identity] = ordinal + 1
        result[f"{identity}#{ordinal}"] = record
    return result


def _equal(field: str, left: Any, right: Any) -> bool:
    if field == "bbox" and left is not None and right is not None:
        return len(left) == len(right) and all(abs(float(a) - float(b)) <= 0.01 for a, b in zip(left, right))
    return left == right


def _ledger(data: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = []
    for case in sorted(data["cases"], key=lambda item: item["fixture"]):
        python = _python_output(case)
        rust = _rust_output(case, python)
        for layer in ("rows", "bands", "physical_cells", "logical_cells", "empty_slots", "occupancy", "diagnostics"):
            left_items, right_items = python[layer], rust[layer]
            if layer == "occupancy":
                left_items, right_items = [v for row in left_items for v in row], [v for row in right_items for v in row]
            left = _records(left_items, layer, "python")
            right = _records(right_items, layer, "rust")
            for identity in sorted(set(left) | set(right)):
                for field in FIELDS:
                    python_value = None if identity not in left else left[identity][field]
                    rust_value = None if identity not in right else right[identity][field]
                    if identity in left and identity in right and _equal(field, python_value, rust_value):
                        continue
                    ledger.append({"fixture": case["fixture"], "layer": layer, "field": field, "identity": identity,
                                   "python_value": python_value, "rust_value": rust_value,
                                   "classification": case.get("classification", {}).get(f"{layer}.{field}", case.get("default_classification", "requires_adaptation"))})
    return sorted(ledger, key=lambda item: (item["fixture"], item["layer"], item["identity"], item["field"]))


def test_task_4a_fixture_contract_and_python_expectations():
    data = _load_fixture()
    assert {case["fixture"] for case in data["cases"]} == REQUIRED_FIXTURES
    for case in data["cases"]:
        output = _python_output(case)
        expected = case.get("python_expectations", {})
        if "band_count" in expected:
            assert len(output["bands"]) == expected["band_count"], case["fixture"]
        if "cell_texts" in expected:
            assert set(expected["cell_texts"]) <= {cell["text"] for cell in output["logical_cells"]}
        if "parent_colspan" in expected:
            parent = next(cell for cell in output["logical_cells"] if cell["text"] == expected["parent_text"])
            assert parent["colspan"] == expected["parent_colspan"]
        if "parent_rowspan" in expected:
            parent = next(cell for cell in output["logical_cells"] if cell["text"] == expected["parent_text"])
            assert parent["rowspan"] == expected["parent_rowspan"]
        if expected.get("has_occupancy_conflict"):
            assert any(item["status"] == "occupancy_conflict" for item in output["diagnostics"])
        if expected.get("has_out_of_bounds"):
            assert any(item["status"] == "out_of_bounds" for item in output["diagnostics"])
        if expected.get("empty_slot"):
            assert expected["empty_slot"] in output["empty_slots"]
        if expected.get("empty_cell"):
            row, column = expected["empty_cell"]
            empty = next(cell for cell in output["logical_cells"] if cell["row_start"] == row + 1 and cell["col_start"] == column + 1)
            assert empty["text"] == ""
            assert empty["rowspan"] == empty["colspan"] == 1
        if "source_line_span" in expected:
            cell = next(cell for cell in output["logical_cells"] if cell["text"] == expected["cell_text"])
            assert [cell["source_line_start"], cell["source_line_end"]] == expected["source_line_span"]


def test_task_4a_ledger_is_field_level_repeatable_and_classified():
    first = _ledger(_load_fixture())
    second = _ledger(_load_fixture())
    assert first == second and first
    assert all(set(item) == {"fixture", "layer", "field", "identity", "python_value", "rust_value", "classification"} for item in first)
    assert all(item["field"] in FIELDS and item["classification"] in CLASSIFICATIONS for item in first)
    assert {item["classification"] for item in first} == CLASSIFICATIONS
    assert {item["layer"] for item in first} <= {"rows", "bands", "physical_cells", "logical_cells", "empty_slots", "occupancy", "diagnostics"}
    assert {item["field"] for item in first} == set(FIELDS)
    digest = hashlib.sha256(json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == hashlib.sha256(json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_task_4a_harness_never_reads_page_or_words():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "fitz"
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "get_text"
        for node in ast.walk(tree)
    )
