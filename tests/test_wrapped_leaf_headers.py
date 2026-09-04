import pytest
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure import logical_grid
from hexai_pdf_parser.tables.wireless_structure.logical_grid import build_logical_grid
from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs


def _logical_cell(cell_id, text, row, col_start, col_end=None, *, y=10):
    col_end = col_start if col_end is None else col_end
    return {
        "cell_id": cell_id,
        "text": text,
        "bbox": [col_start * 20, y, (col_end + 1) * 20, y + 8],
        "row_start": row,
        "row_end": row,
        "col_start": col_start,
        "col_end": col_end,
        "rowspan": 1,
        "colspan": col_end - col_start + 1,
    }


def test_build_logical_grid_collapses_multiple_wrapped_leaf_headers():
    """多列同时折行时，首物理行纯由多个单列叶表头占据，应整体折叠至兄弟叶表头所在逻辑行。"""
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 30},
        {"id": 4, "y": 50},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 7)
    ]
    cells = [
        # H4: 列 4，跨物理行 1~2，多行叶表头
        {
            **_logical_cell("H4", "注册资本\n(万元)", 1, 4, y=10),
            "row_end": 2,
            "rowspan": 2,
            "merge_kind": "multiline_cell",
            "bbox": [80, 10, 100, 28],
        },
        # H6: 列 6，跨物理行 1~3，多行叶表头
        {
            **_logical_cell("H6", "母公司对本公司\n表决权比例\n(%)", 1, 6, y=10),
            "row_end": 3,
            "rowspan": 3,
            "merge_kind": "multiline_cell",
            "bbox": [120, 10, 140, 38],
        },
        # 其余兄弟单行叶表头位于物理行 2
        _logical_cell("H1", "母公司名称", 2, 1, y=20),
        _logical_cell("H2", "注册地", 2, 2, y=20),
        _logical_cell("H3", "业务性质", 2, 3, y=20),
        _logical_cell("H5", "持股比例", 2, 5, y=20),
        # 正文行位于物理行 4
        *[_logical_cell(f"B{column}", f"正文{column}", 4, column, y=50) for column in range(1, 7)],
    ]

    rows, _, logical_cells = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=40,
    )

    # 物理行 1, 2, 3 应该折叠进同一逻辑表头行 [1, 2, 3]
    assert [row["source_rows"] for row in rows] == [[1, 2, 3], [4]]
    header = [cell for cell in logical_cells if cell["cell_id"].startswith("H")]
    assert all(
        (cell["row_start"], cell["row_end"], cell["rowspan"]) == (1, 1, 1)
        for cell in header
    )

    # 物化空单元格后，表头行（行 1）不应出现任何多余的空单元格
    materialized = logical_grid.materialize_empty_cells(
        rows,
        physical_rows,
        columns,
        logical_cells,
        BBox(0, 0, 140, 60),
    )
    assert not any(
        cell.get("merge_kind") == "empty_slot" and cell["row_start"] == 1
        for cell in materialized
    )
    assert len(materialized) == 12  # 2 行 x 6 列


def test_build_logical_grid_rejects_collapse_when_parent_header_starts_on_row():
    """反例：首物理行包含真正跨列父表头（colspan >= 2）时，绝对不能折叠，必须保持多级表头。"""
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 40},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 5)
    ]
    cells = [
        # P1: 列 1~2 的父表头，colspan=2
        {
            **_logical_cell("P1", "期末余额", 1, 1, 2, y=10),
            "row_end": 1,
            "rowspan": 1,
            "colspan": 2,
        },
        # H3: 列 3 的折行叶表头，跨 1~2
        {
            **_logical_cell("H3", "坏账准备\n金额", 1, 3, y=10),
            "row_end": 2,
            "rowspan": 2,
            "merge_kind": "multiline_cell",
        },
        _logical_cell("H1", "账面余额", 2, 1, y=20),
        _logical_cell("H2", "比例(%)", 2, 2, y=20),
        _logical_cell("H4", "账面价值", 2, 4, y=20),
        *[_logical_cell(f"B{column}", f"正文{column}", 3, column, y=40) for column in range(1, 5)],
    ]

    rows, _, _ = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=30,
    )

    # 包含真实父表头时，物理行 1 不能被压缩
    assert [row["source_rows"] for row in rows] == [[1], [2], [3]]


def test_build_logical_grid_rejects_collapse_when_single_line_cell_starts_on_row():
    """反例：首物理行存在普通单行独立表头时，表明该物理行是独立结构行，拒绝折叠。"""
    physical_rows = [
        {"id": 1, "y": 10},
        {"id": 2, "y": 20},
        {"id": 3, "y": 40},
    ]
    columns = [
        {"id": column, "x0": column * 20, "x1": column * 20 + 10}
        for column in range(1, 4)
    ]
    cells = [
        # H1 是普通的单行单列表头（row_start==row_end==1）
        _logical_cell("H1", "第一列", 1, 1, y=10),
        # H2 是多行叶表头
        {
            **_logical_cell("H2", "第二列\n详情", 1, 2, y=10),
            "row_end": 2,
            "rowspan": 2,
            "merge_kind": "multiline_cell",
        },
        _logical_cell("H3", "第三列", 2, 3, y=20),
        *[_logical_cell(f"B{column}", f"正文{column}", 3, column, y=40) for column in range(1, 4)],
    ]

    rows, _, _ = build_logical_grid(
        physical_rows,
        columns,
        cells,
        header_cutoff=30,
    )

    assert [row["source_rows"] for row in rows] == [[1], [2], [3]]


def test_build_text_runs_cjk_dominant_bold_not_polluted_by_opening_bracket():
    """西文开括号即使带粗体属性，主体为未加粗中文的 text run 其 bold 属性应为 False。"""
    spans = [
        {
            "span_ref": 1,
            "order": 1,
            "flow": 1,
            "source_position": [1, 0, 0],
            "source_position_known": True,
            "bbox": [10.0, 10.0, 13.0, 20.0],
            "text": "(",
            "font": "Arial Narrow,Bold",
            "font_size": 10.0,
            "bold": True,
            "char_boxes": [{"text": "(", "bbox": [10.0, 10.0, 13.0, 20.0]}],
        },
        {
            "span_ref": 2,
            "order": 2,
            "flow": 2,
            "source_position": [1, 0, 1],
            "source_position_known": True,
            "bbox": [13.0, 10.0, 33.0, 20.0],
            "text": "万元",
            "font": "SimSun",
            "font_size": 10.0,
            "bold": False,
            "char_boxes": [
                {"text": "万", "bbox": [13.0, 10.0, 23.0, 20.0]},
                {"text": "元", "bbox": [23.0, 10.0, 33.0, 20.0]},
            ],
        },
        {
            "span_ref": 3,
            "order": 3,
            "flow": 3,
            "source_position": [1, 0, 2],
            "source_position_known": True,
            "bbox": [33.0, 10.0, 36.0, 20.0],
            "text": ")",
            "font": "Arial Narrow,Bold",
            "font_size": 10.0,
            "bold": True,
            "char_boxes": [{"text": ")", "bbox": [33.0, 10.0, 36.0, 20.0]}],
        },
    ]

    runs = build_text_runs(spans)
    assert len(runs) == 1
    assert runs[0]["text"] == "(万元)"
    # 主体为中文未加粗，不应被括号误判为 bold
    assert runs[0]["bold"] is False
