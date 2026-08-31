from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_table_recovery import NativeSpan

from scripts.span_table_tree_demo import (
    TreeNode,
    build_table_tree,
    build_text_nodes,
    expand_nodes,
    flatten_tree_cells,
)


def test_build_text_nodes_preserves_native_span_order():
    spans = [
        NativeSpan("left-1", BBox(10, 20, 30, 30), "f", 10, 9),
        NativeSpan("right", BBox(100, 20, 130, 30), "f", 10, 10),
        NativeSpan("left-2", BBox(10, 32, 30, 42), "f", 10, 11),
    ]
    nodes = build_text_nodes(spans)
    assert [node.text for node in nodes] == ["left-1", "right", "left-2"]
    assert [node.order_start for node in nodes] == [9, 10, 11]


def test_expand_wide_span_keeps_phrase_order_and_character_boxes():
    text = "balance    ratio    provision"
    span = NativeSpan(
        text,
        BBox(200, 20, 400, 30),
        "f",
        10,
        20,
        characters=[
            (char, BBox(200 + i * 10, 20, 210 + i * 10, 30))
            for i, char in enumerate(text)
        ],
    )
    nodes = expand_nodes(build_text_nodes([span]))
    assert [node.text for node in nodes] == ["balance", "ratio", "provision"]
    assert [node.order_start for node in nodes] == [20, 20, 20]
    assert nodes[0].bbox.x0 < nodes[1].bbox.x0 < nodes[2].bbox.x0


def test_table_tree_keeps_sparse_leaf_and_native_order_rowspan():
    def n(text, x0, y0, order):
        return TreeNode("text", text, order, order, BBox(x0, y0, x0 + 30, y0 + 10))

    nodes = [
        n("项目", 10, 10, 0),
        n("balance", 100, 20, 1), n("ratio", 150, 20, 2), n("provision", 200, 20, 3),
        n("balance", 260, 20, 4), n("ratio", 310, 20, 5), n("provision", 360, 20, 6),
        n("left-1", 10, 40, 7), n("left-2", 10, 52, 8), n("left-3", 10, 64, 9),
        n("v1", 100, 40, 10), n("v2", 100, 52, 11), n("v3", 100, 64, 12),
    ]
    root = build_table_tree(nodes, BBox(0, 0, 400, 100))
    leaves = [
        child
        for group in root.children
        if group.kind in {"leaf_column", "header_group"}
        for child in (group.children if group.kind == "header_group" else [group])
        if child.kind == "leaf_column"
    ]
    assert len(leaves) == 7
    merged = next(cell for cell in flatten_tree_cells(root) if cell.col_index == 0 and cell.row_index >= 2)
    assert merged.rowspan == 3


def test_table_tree_includes_header_cells_in_logical_grid():
    def n(text, x0, y0, order):
        return TreeNode("text", text, order, order, BBox(x0, y0, x0 + 30, y0 + 10))

    nodes = [
        n("项目", 10, 10, 0),
        n("年末数", 200, 10, 1), n("年初数", 360, 10, 2),
        n("账面余额", 100, 20, 3), n("比例", 150, 20, 4), n("坏账准备", 200, 20, 5),
        n("账面余额", 260, 20, 6), n("比例", 310, 20, 7), n("坏账准备", 360, 20, 8),
        n("项目一", 10, 40, 9), n("1", 100, 40, 10),
    ]
    root = build_table_tree(nodes, BBox(0, 0, 400, 100))
    grid = next(child for child in root.children if child.kind == "grid")
    header_rows = grid.children[:2]
    assert [cell.text for cell in header_rows[0].children] == ["年末数", "年初数"]
    assert [(cell.col_index, cell.colspan) for cell in header_rows[0].children] == [(1, 3), (4, 3)]
    assert [cell.col_index for cell in header_rows[1].children] == list(range(7))
