"""Materialize text runs as candidate cells without premature row merging."""

from __future__ import annotations

from typing import Any, Sequence


def merge_column_continuations(
    atoms: Sequence[dict[str, Any]], bands: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert column-assigned text runs to ordered candidate cells.

    Same-column and native-flow adjacency remain evidence for the later
    multiline-cell stage; they are deliberately not merged here.
    """
    del bands  # Column assignment has already happened at this stage.
    cells = []
    for atom in atoms:
        column_id = atom.get("column_id")
        if column_id is None:
            continue
        cell = dict(atom, cell_id="")
        cell.setdefault("column_start", column_id)
        cell.setdefault("column_end", column_id)
        cells.append(cell)
    cells.sort(key=lambda item: (item["flow_start"], item["flow_end"]))
    for order, cell in enumerate(cells, 1):
        label = cell.get("candidate_label", f"T{order}")
        cell["candidate_order"] = cell.get("candidate_order", order)
        cell["candidate_label"] = label
        cell["cell_id"] = label
    return cells
