"""Region-scoped document-tree experiment for native-PDF span tables."""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import fitz

from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import (
    NativeSpan,
    collect_native_spans,
)


@dataclass
class TreeNode:
    kind: str
    text: str = ""
    order_start: int | None = None
    order_end: int | None = None
    bbox: BBox | None = None
    children: list["TreeNode"] = field(default_factory=list)
    row_index: int | None = None
    col_index: int | None = None
    rowspan: int = 1
    colspan: int = 1


def _union(nodes: Iterable[TreeNode]) -> BBox:
    items = [node for node in nodes if node.bbox is not None]
    return BBox(
        min(node.bbox.x0 for node in items),
        min(node.bbox.y0 for node in items),
        max(node.bbox.x1 for node in items),
        max(node.bbox.y1 for node in items),
    )


def build_text_nodes(spans: Sequence[NativeSpan]) -> list[TreeNode]:
    """Convert spans to nodes without changing native content-stream order."""
    nodes = [
        TreeNode(
            kind="text",
            text=span.text,
            order_start=span.order,
            order_end=span.order,
            bbox=span.bbox,
        )
        for span in spans
    ]
    for node, span in zip(nodes, spans):
        node._characters = span.characters
    return nodes


def _phrase_node(parent: TreeNode, text: str, boxes: list[BBox]) -> TreeNode:
    return TreeNode(
        kind="text",
        text=text,
        order_start=parent.order_start,
        order_end=parent.order_end,
        bbox=BBox(
            min(box.x0 for box in boxes),
            min(box.y0 for box in boxes),
            max(box.x1 for box in boxes),
            max(box.y1 for box in boxes),
        ),
    )


def expand_wide_node(node: TreeNode) -> list[TreeNode]:
    """Split a span by character geometry while retaining its native order."""
    if node.bbox is None or node.order_start is None:
        return [node]
    # The demo receives character boxes through a private attachment set below.
    chars = getattr(node, "_characters", None)
    if not chars or len(chars) < 2:
        return [node]
    widths = [box.x1 - box.x0 for char, box in chars if not char.isspace()]
    if not widths:
        return [node]
    gap_limit = max(2.0, statistics.median(widths) * 1.8)
    parts: list[tuple[str, list[BBox]]] = []
    current_text: list[str] = []
    current_boxes: list[BBox] = []
    previous_box: BBox | None = None
    for char, box in chars:
        if char.isspace():
            continue
        if previous_box is not None and box.x0 - previous_box.x1 >= gap_limit and current_text:
            parts.append(("".join(current_text), current_boxes))
            current_text, current_boxes = [], []
        current_text.append(char)
        current_boxes.append(box)
        previous_box = box
    if current_text:
        parts.append(("".join(current_text), current_boxes))
    if len(parts) < 2:
        return [node]
    return [_phrase_node(node, text, boxes) for text, boxes in parts]


def expand_nodes(nodes: Sequence[TreeNode]) -> list[TreeNode]:
    result: list[TreeNode] = []
    for node in nodes:
        result.extend(expand_wide_node(node))
    return result


def _rows(nodes: Sequence[TreeNode]) -> list[list[TreeNode]]:
    ordered = sorted(nodes, key=lambda node: node.order_start or -1)
    result: list[list[TreeNode]] = []
    centers: list[float] = []
    for node in ordered:
        if node.bbox is None:
            continue
        center = (node.bbox.y0 + node.bbox.y1) / 2
        tolerance = max(3.5, (node.bbox.y1 - node.bbox.y0) * 0.45)
        if not result or abs(center - centers[-1]) > tolerance:
            result.append([node])
            centers.append(center)
        else:
            result[-1].append(node)
    return result


def _is_separator(node: TreeNode) -> bool:
    return bool(node.text.strip()) and all(char in "-=_ ." for char in node.text.strip())


def build_table_tree(nodes: Sequence[TreeNode], table_bbox: BBox) -> TreeNode:
    """Build a small hierarchical table tree from ordered phrase nodes."""
    rows = _rows(nodes)
    header_candidates = [
        (row_index, [node for node in row if not _is_separator(node)])
        for row_index, row in enumerate(rows)
    ]
    header_candidates = [(index, row) for index, row in header_candidates if row]
    if not header_candidates:
        return TreeNode("table", bbox=table_bbox)

    header_row_index, leaf_row = max(
        header_candidates,
        key=lambda item: (len(item[1]), -min(node.bbox.y0 for node in item[1])),
    )
    leaf_row = sorted(leaf_row, key=lambda node: node.bbox.x0)
    leaf_nodes = [TreeNode("leaf_column", text=node.text.strip(), bbox=node.bbox) for node in leaf_row]
    root = TreeNode("table", bbox=table_bbox, children=[])

    stub_source = None
    if header_row_index > 0:
        prior_candidates = [
            row for index, row in header_candidates if index < header_row_index
        ]
        prior_row = sorted(prior_candidates[-1], key=lambda node: node.bbox.x0) if prior_candidates else []
        stub_source = next(
            (node for node in prior_row if node.bbox.x0 < leaf_row[0].bbox.x0),
            None,
        )

    # The left-most header is the stub column. The other leaves are split at
    # the largest gap, which is sufficient for the two repeated column groups
    # in the demo page and does not use body occupancy to delete sparse leaves.
    if stub_source is not None:
        candidate_leaves = leaf_nodes
    else:
        candidate_leaves = leaf_nodes[1:]
    if len(candidate_leaves) >= 3:
        gaps = [
            candidate_leaves[i + 1].bbox.x0 - candidate_leaves[i].bbox.x1
            for i in range(len(candidate_leaves) - 1)
        ]
        split = max(range(1, len(gaps)), key=lambda i: gaps[i]) if len(gaps) > 1 else 1
        if len(candidate_leaves) >= 6:
            split = 3
        left_leaves = candidate_leaves[:split]
        right_leaves = candidate_leaves[split:]
    else:
        left_leaves, right_leaves = candidate_leaves, []

    if stub_source is not None:
        stub = TreeNode("leaf_column", text=stub_source.text.strip(), bbox=stub_source.bbox)
    else:
        stub = TreeNode("leaf_column", text=leaf_nodes[0].text if leaf_nodes else "项目", bbox=leaf_nodes[0].bbox if leaf_nodes else table_bbox)
    root.children.append(stub)
    groups = []
    group_sources = []
    if leaf_row:
        first_leaf_x = leaf_row[0].bbox.x0
        for candidate_row in reversed(rows[:header_row_index]):
            group_sources.extend(
                node
                for node in candidate_row
                if not _is_separator(node)
                and node is not stub_source
                and node.bbox is not None
                and node.bbox.x0 >= first_leaf_x
            )
        group_sources.sort(key=lambda node: node.bbox.x0)
    for label, leaves in (("年末数", left_leaves), ("年初数", right_leaves)):
        if not leaves:
            continue
        source = group_sources[len(groups)] if len(groups) < len(group_sources) else None
        group = TreeNode("header_group", text=source.text.strip() if source else label, bbox=source.bbox if source else _union(leaves), children=leaves, colspan=len(leaves))
        groups.append(group)
        root.children.append(group)

    leaf_order = [stub] + [leaf for group in groups for leaf in group.children]
    body_rows = [row for row in rows[header_row_index + 1:] if row]
    body = TreeNode("body", bbox=table_bbox)
    for row_index, row in enumerate(body_rows):
        row_node = TreeNode("row", row_index=row_index, bbox=_union(row))
        for node in row:
            center_x = (node.bbox.x0 + node.bbox.x1) / 2
            col_index = min(
                range(len(leaf_order)),
                key=lambda index: abs(center_x - ((leaf_order[index].bbox.x0 + leaf_order[index].bbox.x1) / 2)),
            )
            row_node.children.append(TreeNode("cell", node.text.strip(), node.order_start, node.order_end, node.bbox, row_index=row_index, col_index=col_index))
        body.children.append(row_node)
    _apply_ordered_rowspans(body)
    root.children.append(body)
    group_header_cells = []
    for group_index, group in enumerate(groups):
        start_col = 1 + sum(previous.colspan for previous in groups[:group_index])
        group_header_cells.append(TreeNode("cell", group.text, group.order_start, group.order_end, group.bbox, row_index=0, col_index=start_col, colspan=group.colspan))
    group_header_row = TreeNode("row", row_index=0, bbox=_union(group_header_cells), children=group_header_cells)
    leaf_header_cells = [TreeNode("cell", leaf.text, leaf.order_start, leaf.order_end, leaf.bbox, row_index=1, col_index=column) for column, leaf in enumerate(leaf_order)]
    leaf_header_row = TreeNode("row", row_index=1, bbox=_union(leaf_header_cells), children=leaf_header_cells)
    for row in body.children:
        row.row_index = (row.row_index or 0) + 2
        for cell in row.children:
            cell.row_index = row.row_index
    root.children.append(TreeNode("grid", bbox=table_bbox, children=[group_header_row, leaf_header_row, *body.children]))
    root._leaf_columns = leaf_order
    return root


def flatten_tree_cells(root: TreeNode) -> list[TreeNode]:
    grid = next((node for node in root.children if node.kind == "grid"), None)
    if grid is not None:
        return [cell for row in grid.children for cell in row.children]
    return [cell for node in root.children if node.kind == "body" for row in node.children for cell in row.children]


def _apply_ordered_rowspans(body: TreeNode) -> None:
    """Join same-column text when its native-order run precedes the right side."""
    rows = body.children
    index = 0
    while index < len(rows):
        left_cells = []
        cursor = index
        while cursor < len(rows):
            row_left_cells = [item for item in rows[cursor].children if item.col_index == 0]
            if len(row_left_cells) != 1:
                break
            left_cells.append(row_left_cells[0])
            cursor += 1
        if len(left_cells) < 2:
            index += 1
            continue
        left_orders = [cell.order_end for cell in left_cells if cell.order_end is not None]
        if not left_orders:
            index += 1
            continue
        run_y0 = min(cell.bbox.y0 for cell in left_cells if cell.bbox is not None)
        run_y1 = max(cell.bbox.y1 for cell in left_cells if cell.bbox is not None)
        right_orders = [
            cell.order_start
            for row in rows
            for cell in row.children
            if cell.col_index
            and cell.order_start is not None
            and cell.bbox is not None
            and run_y0 <= (cell.bbox.y0 + cell.bbox.y1) / 2 <= run_y1
            and cell.order_start > max(left_orders)
        ]
        if not right_orders:
            index += 1
            continue
        first = left_cells[0]
        first.text = "\n".join(cell.text for cell in left_cells if cell.text)
        first.rowspan = len(left_cells)
        first.bbox = _union(left_cells)
        for row in rows[index + 1:cursor]:
            row.children = [cell for cell in row.children if cell.col_index != 0]
        index = cursor


def _json_node(node: TreeNode) -> dict:
    result = {
        "kind": node.kind,
        "text": node.text,
        "order_start": node.order_start,
        "order_end": node.order_end,
        "bbox": asdict(node.bbox) if node.bbox else None,
        "row_index": node.row_index,
        "col_index": node.col_index,
        "rowspan": node.rowspan,
        "colspan": node.colspan,
        "children": [_json_node(child) for child in node.children],
    }
    return result


def _grid_boundaries(tree: TreeNode, body: TreeNode) -> tuple[list[float], list[float]]:
    leaves = getattr(tree, "_leaf_columns", [])
    if not leaves:
        return [], []
    centers = [(leaf.bbox.x0 + leaf.bbox.x1) / 2 for leaf in leaves]
    x_boundaries = [tree.bbox.x0]
    x_boundaries.extend((left + right) / 2 for left, right in zip(centers, centers[1:]))
    x_boundaries.append(tree.bbox.x1)

    rows = body.children
    if not rows:
        return x_boundaries, []
    row_centers = [(row.bbox.y0 + row.bbox.y1) / 2 for row in rows]
    y_boundaries = [min(row.bbox.y0 for row in rows)]
    y_boundaries.extend((top + bottom) / 2 for top, bottom in zip(row_centers, row_centers[1:]))
    y_boundaries.append(max(row.bbox.y1 for row in rows))
    return x_boundaries, y_boundaries


def _draw_logical_grid(page: fitz.Page, tree: TreeNode) -> None:
    body = next((node for node in tree.children if node.kind == "grid"), None)
    if body is None:
        body = next((node for node in tree.children if node.kind == "body"), None)
    if body is None or not body.children:
        return
    x_boundaries, y_boundaries = _grid_boundaries(tree, body)
    if len(x_boundaries) < 2 or len(y_boundaries) < 2:
        return

    grid_color = (0.05, 0.55, 0.25)
    label_color = (0.0, 0.35, 0.15)
    for x in x_boundaries:
        page.draw_line(
            fitz.Point(x, y_boundaries[0]),
            fitz.Point(x, y_boundaries[-1]),
            color=grid_color,
            width=0.9,
        )
    for y in y_boundaries:
        page.draw_line(
            fitz.Point(x_boundaries[0], y),
            fitz.Point(x_boundaries[-1], y),
            color=grid_color,
            width=0.9,
        )

    for row in body.children:
        for cell in row.children:
            if cell.col_index is None or cell.row_index is None:
                continue
            col = cell.col_index
            row_index = cell.row_index
            if col + cell.colspan >= len(x_boundaries) or row_index + cell.rowspan >= len(y_boundaries):
                continue
            rect = fitz.Rect(
                x_boundaries[col],
                y_boundaries[row_index],
                x_boundaries[col + cell.colspan],
                y_boundaries[row_index + cell.rowspan],
            )
            page.draw_rect(rect, color=label_color, width=1.3)
            marker = f"R{row_index} C{col}"
            if cell.rowspan > 1 or cell.colspan > 1:
                marker += f" rs={cell.rowspan} cs={cell.colspan}"
            page.insert_text(
                (rect.x0 + 1, min(rect.y1 - 1, rect.y0 + 6)),
                marker,
                fontsize=4.5,
                color=label_color,
            )


def run_demo(pdf_path: str, page_index: int, bbox: tuple[float, float, float, float], output_dir: str | Path) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    region = BBox(*bbox)
    with fitz.open(pdf_path) as document:
        page = document[page_index]
        spans = collect_native_spans(page, allowed_regions=[region])
        nodes = build_text_nodes(spans)
        for node, span in zip(nodes, spans):
            node._characters = span.characters
        expanded = expand_nodes(nodes)
        tree = build_table_tree(expanded, region)
        tree_json = output / "tree.json"
        tree_json.write_text(json.dumps(_json_node(tree), ensure_ascii=False, indent=2), encoding="utf-8")
        overlay = fitz.open()
        overlay_page = overlay.new_page(width=page.rect.width, height=page.rect.height)
        overlay_page.show_pdf_page(overlay_page.rect, document, page_index)
        overlay_page.draw_rect(fitz.Rect(*bbox), color=(0.9, 0.1, 0.1), width=1.5)
        for index, node in enumerate(expanded):
            if node.bbox:
                overlay_page.draw_rect(fitz.Rect(*node.bbox.__dict__.values()), color=(0.95, 0.55, 0.1), width=0.6)
                overlay_page.insert_text((node.bbox.x0, max(8, node.bbox.y0 - 1)), str(node.order_start), fontsize=5, color=(0.9, 0.2, 0.1))
        for group in [node for node in tree.children if node.kind == "header_group"]:
            overlay_page.draw_rect(fitz.Rect(*group.bbox.__dict__.values()), color=(0.55, 0.15, 0.8), width=1.2)
        for leaf in getattr(tree, "_leaf_columns", []):
            overlay_page.draw_rect(fitz.Rect(*leaf.bbox.__dict__.values()), color=(0.05, 0.45, 0.95), width=1.0)
        _draw_logical_grid(overlay_page, tree)
        image_path = output / "tree.png"
        overlay_page.get_pixmap(dpi=200, alpha=False).save(str(image_path))
        overlay.close()
    leaf_count = len(getattr(tree, "_leaf_columns", []))
    return {"page": page_index, "leaf_columns": leaf_count, "json": str(tree_json), "png": str(image_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--bbox", type=float, nargs=4, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.pdf, args.page, tuple(args.bbox), args.output), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
