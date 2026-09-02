import hexai_pdf_parser.tables.wireless_structure.header_topology as header_topology
from hexai_pdf_parser.tables.wireless_structure.header_topology import (
    _infer_complete_child_group_span,
    annotate_columns,
    infer_header_cutoff,
    refine_leaf_bands,
    rescue_sparse_body_bands,
)


def _atom(text, x0, y0, x1, y1, flow):
    return {
        "text": text,
        "bbox": [x0, y0, x1, y1],
        "flow_start": flow,
        "flow_end": flow,
        "font_size": 10,
        "script": "cjk",
    }


def test_annotate_columns_assigns_parent_header_colspan_by_material_bbox_overlap():
    bands = [
        {"id": 1, "x0": 10, "x1": 40},
        {"id": 2, "x0": 50, "x1": 80},
        {"id": 3, "x0": 90, "x1": 120},
    ]
    atoms = [_atom("合计", 34, 10, 96, 20, 1)]

    annotate_columns(atoms, bands, header_cutoff=25)

    assert atoms[0]["column_start"] == 1
    assert atoms[0]["column_end"] == 3
    assert atoms[0]["colspan"] == 3


def test_annotate_columns_does_not_turn_a_boundary_touch_into_colspan():
    bands = [{"id": 1, "x0": 10, "x1": 50}, {"id": 2, "x0": 50, "x1": 90}]
    atoms = [_atom("金额", 42, 10, 51, 20, 1)]

    annotate_columns(atoms, bands, header_cutoff=25)

    assert atoms[0]["colspan"] == 1


def test_annotate_columns_assigns_header_to_materially_overlapping_sparse_body_band():
    bands = [
        {"id": 1, "x0": 71, "x1": 120},
        {"id": 2, "x0": 234, "x1": 366, "kind": "sparse_body"},
        {"id": 3, "x0": 395, "x1": 518},
    ]
    atoms = [_atom("中央多行表头", 227, 107, 367, 132, 1)]

    annotate_columns(atoms, bands, header_cutoff=148)

    assert atoms[0]["column_start"] == 2
    assert atoms[0]["column_end"] == 2
    assert atoms[0]["colspan"] == 1


def test_annotate_columns_does_not_force_sparse_band_on_multiple_material_overlaps():
    bands = [
        {"id": 1, "x0": 10, "x1": 30},
        {"id": 2, "x0": 40, "x1": 70, "kind": "sparse_body"},
        {"id": 3, "x0": 80, "x1": 110},
    ]
    atoms = [_atom("跨列标题", 45, 10, 95, 20, 1)]

    annotate_columns(atoms, bands, header_cutoff=25)

    assert atoms[0]["column_start"] != 2


def test_infer_header_cutoff_uses_the_earliest_large_header_body_gap():
    atoms = [
        _atom("表头一", 10, 10, 30, 18, 1),
        _atom("表头二", 50, 10, 70, 18, 2),
        _atom("叶子一", 10, 20, 30, 28, 3),
        _atom("叶子二", 50, 20, 70, 28, 4),
        _atom("项目", 10, 45, 30, 53, 5),
        _atom("100", 50, 45, 70, 53, 6),
    ]

    cutoff = infer_header_cutoff(atoms)

    assert cutoff is not None
    assert 28 < cutoff < 45


def test_infer_header_cutoff_treats_repeated_latin_rows_after_header_as_body():
    atoms = [
        _atom("表头一", 10, 10, 30, 18, 1),
        _atom("表头二", 50, 10, 70, 18, 2),
        _atom("叶子一", 10, 20, 30, 28, 3),
        _atom("叶子二", 50, 20, 70, 28, 4),
        _atom("表头尾", 10, 30, 30, 38, 5),
        _atom("FRASERS", 10, 50, 30, 58, 6),
        _atom("PROPERTY", 50, 50, 80, 58, 7),
        _atom("THAILAND", 10, 62, 35, 70, 8),
        _atom("INDUSTRIAL", 50, 62, 85, 70, 9),
        _atom("100", 50, 78, 70, 86, 10),
        _atom("200", 50, 90, 70, 98, 11),
    ]

    cutoff = infer_header_cutoff(atoms)

    assert cutoff is not None
    assert 38 < cutoff < 50


def test_refine_leaf_bands_stops_before_a_numeric_body_row_with_later_wraps():
    bands = [
        {"id": 1, "x0": 87.74, "x1": 147.74, "support": 5, "y_support": 5},
        {"id": 2, "x0": 176.57, "x1": 218.81, "support": 5, "y_support": 5},
        {"id": 3, "x0": 240.41, "x1": 282.65, "support": 5, "y_support": 5},
        {"id": 4, "x0": 341.23, "x1": 502.42, "support": 7, "y_support": 4},
    ]
    atoms = [
        _atom("类别", 87.74, 130.55, 119.42, 140.55, 1),
        _atom("使用寿命", 176.57, 130.55, 218.81, 140.55, 2),
        _atom("摊销方法", 240.41, 130.55, 282.65, 140.55, 3),
        _atom("备注", 481.18, 130.55, 502.30, 140.55, 4),
        _atom("土地使用权", 87.74, 147.46, 147.74, 158.46, 5),
        _atom("50.00", 194.09, 147.46, 218.74, 158.46, 6),
        _atom("直线法", 246.53, 147.46, 282.53, 158.46, 7),
        _atom("土地证使用期限", 389.35, 147.46, 473.35, 158.46, 8),
        _atom("50年", 476.38, 147.46, 502.42, 158.46, 9),
        _atom("专利权", 87.74, 171.48, 123.74, 182.48, 10),
        _atom("10.00", 194.09, 171.48, 218.74, 182.48, 11),
        _atom("直线法", 246.53, 171.48, 282.53, 182.48, 12),
        _atom("有合同年限的无形资产按照合同年限摊", 298.27, 163.85, 502.27, 174.85, 13),
        _atom("销，无合同年限按照", 341.23, 179.31, 449.23, 190.31, 14),
        _atom("10年摊销", 452.26, 179.31, 502.30, 190.31, 15),
        _atom("软件", 87.74, 202.73, 111.74, 213.73, 16),
        _atom("5.00", 199.49, 202.73, 218.74, 213.73, 17),
        _atom("直线法", 246.53, 202.73, 282.53, 213.73, 18),
        _atom("有合同年限的无形资产按照合同年限摊", 298.27, 194.93, 502.27, 205.93, 19),
        _atom("销，无合同年限按照", 346.75, 210.53, 454.75, 221.53, 20),
        _atom("5年摊销", 457.78, 210.53, 502.30, 221.53, 21),
        _atom("软件著作权", 87.74, 226.73, 147.74, 237.73, 22),
        _atom("6.42", 199.49, 226.73, 218.74, 237.73, 23),
        _atom("直线法", 246.53, 226.73, 282.53, 237.73, 24),
        _atom("预计尚可使用年限摊销", 382.27, 226.73, 502.27, 237.73, 25),
    ]

    refined, cutoff = refine_leaf_bands(atoms, bands)

    assert cutoff is not None
    assert 135.55 < cutoff < 152.96
    assert [(band["x0"], band["x1"]) for band in refined] == [
        (87.74, 147.74),
        (176.57, 218.81),
        (240.41, 282.65),
        (341.23, 502.42),
    ]


def test_refine_leaf_bands_splits_a_parent_band_using_repeated_numeric_tracks():
    bands = [{"id": 1, "x0": 10, "x1": 100, "support": 8, "y_support": 4}]
    atoms = [
        _atom("上左", 20, 10, 35, 18, 1),
        _atom("上右", 60, 10, 75, 18, 2),
        _atom("中左", 20, 20, 35, 28, 3),
        _atom("中右", 60, 20, 75, 28, 4),
        _atom("下左", 20, 30, 35, 38, 5),
        _atom("下右", 60, 30, 75, 38, 6),
        _atom("100", 20, 55, 35, 63, 7),
        _atom("200", 60, 55, 75, 63, 8),
        _atom("300", 20, 75, 35, 83, 9),
        _atom("400", 60, 75, 75, 83, 10),
    ]

    refined, _ = refine_leaf_bands(atoms, bands)

    assert len(refined) == 2
    assert [(band["x0"], band["x1"]) for band in refined] == [(20, 35), (60, 75)]


def test_refine_leaf_bands_ignores_a_neighbor_header_that_only_grazes_band_edge():
    bands = [
        {"id": 1, "x0": 306.0, "x1": 350.0, "support": 4, "y_support": 4},
        {"id": 2, "x0": 348.6, "x1": 367.0, "support": 4, "y_support": 4},
    ]
    atoms = [
        _atom("本年增加", 313.0, 10, 350.0, 18, 1),
        _atom("金额", 306.7, 20, 324.7, 28, 2),
        _atom("比例", 348.6, 20, 366.6, 28, 3),
        _atom("100", 312.0, 55, 321.4, 63, 4),
        _atom("51%", 353.9, 55, 363.3, 63, 5),
        _atom("200", 312.0, 75, 321.4, 83, 6),
        _atom("52%", 353.9, 75, 363.3, 83, 7),
    ]

    refined, _ = refine_leaf_bands(atoms, bands)

    assert len(refined) == 2
    assert [(band["x0"], band["x1"]) for band in refined] == [
        (306.0, 350.0),
        (348.6, 367.0),
    ]


def test_annotate_columns_pairs_a_complete_parent_tier_with_two_leaf_groups():
    bands = [
        {"id": 1, "x0": 102.5, "x1": 210.5},
        {"id": 2, "x0": 217.7, "x1": 266.4},
        {"id": 3, "x0": 268.9, "x1": 286.9},
        {"id": 4, "x0": 306.7, "x1": 349.9},
        {"id": 5, "x0": 348.6, "x1": 366.6},
        {"id": 6, "x0": 388.1, "x1": 414.6},
        {"id": 7, "x0": 414.6, "x1": 441.1},
        {"id": 8, "x0": 447.8, "x1": 498.6},
        {"id": 9, "x0": 502.7, "x1": 520.7},
    ]
    parents = [
        _atom("年初数", 239.4, 10, 266.4, 18, 1),
        _atom("本年增加", 313.9, 10, 349.9, 18, 2),
        _atom("本年减少", 392.1, 10, 428.1, 18, 3),
        _atom("年末数", 471.6, 10, 498.6, 18, 4),
    ]
    leaves = [
        _atom("金额", 230.3, 30, 248.3, 38, 6),
        _atom("比例", 268.9, 30, 286.9, 38, 7),
        _atom("金额", 306.7, 30, 324.7, 38, 8),
        _atom("比例", 348.6, 30, 366.6, 38, 9),
        _atom("金额", 388.1, 30, 406.1, 38, 10),
        _atom("比例", 423.1, 30, 441.1, 38, 11),
        _atom("金额", 460.4, 30, 478.4, 38, 12),
        _atom("比例", 502.7, 30, 520.7, 38, 13),
    ]

    annotate_columns(
        [*parents, _atom("企业名称", 138.5, 20, 174.5, 28, 5), *leaves],
        bands,
        header_cutoff=40,
    )

    assert [
        (atom["column_start"], atom["column_end"], atom["colspan"])
        for atom in parents
    ] == [(2, 3, 2), (4, 5, 2), (6, 7, 2), (8, 9, 2)]


def test_annotate_columns_pairs_short_parents_over_unequal_leaf_widths():
    bands = [
        {"id": 1, "x0": 92.5, "x1": 218.5},
        {"id": 2, "x0": 218.5, "x1": 308.2},
        {"id": 3, "x0": 314.6, "x1": 356.6},
        {"id": 4, "x0": 371.7, "x1": 451.1},
        {"id": 5, "x0": 453.6, "x1": 495.6},
    ]
    parents = [
        _atom("年末数", 276.7, 10, 308.2, 18, 1),
        _atom("年初数", 416.3, 10, 447.8, 18, 2),
    ]
    leaves = [
        _atom("金额", 259.9, 30, 280.9, 38, 4),
        _atom("坏账准备", 314.6, 30, 356.6, 38, 5),
        _atom("金额", 392.7, 30, 413.7, 38, 6),
        _atom("坏账准备", 453.6, 30, 495.6, 38, 7),
    ]

    annotate_columns(
        [*parents, _atom("项目", 148.0, 20, 169.0, 28, 3), *leaves],
        bands,
        header_cutoff=40,
    )

    assert [
        (atom["column_start"], atom["column_end"], atom["colspan"])
        for atom in parents
    ] == [(2, 3, 2), (4, 5, 2)]


def test_annotate_columns_pairs_parent_when_one_leaf_header_wraps_vertically():
    bands = [
        {"id": 1, "x0": 72.4, "x1": 167.1},
        {"id": 2, "x0": 199.2, "x1": 277.7},
        {"id": 3, "x0": 284.7, "x1": 321.6},
        {"id": 4, "x0": 339.8, "x1": 385.3},
        {"id": 5, "x0": 431.9, "x1": 451.1},
        {"id": 6, "x0": 462.6, "x1": 520.1},
    ]
    parents = [
        _atom("账面余额", 235.5, 319, 277.7, 328, 1),
        _atom("坏账准备", 367.0, 319, 409.3, 328, 2),
    ]
    leaves = [
        _atom("金额", 233.2, 340, 254.3, 351, 3),
        _atom("比例(%)", 284.7, 340, 321.6, 351, 4),
        _atom("金额", 361.8, 340, 382.9, 351, 5),
        _atom("预期信用损", 396.0, 333, 448.8, 344, 6),
        _atom("失率(%)", 414.2, 347, 451.1, 358, 7),
        _atom("账面", 496.5, 325, 517.7, 336, 8),
        _atom("价值", 496.5, 339, 517.7, 350, 9),
    ]

    annotate_columns([*parents, *leaves], bands, header_cutoff=360)

    assert [
        (atom["column_start"], atom["column_end"], atom["colspan"])
        for atom in parents
    ] == [(2, 3, 2), (4, 5, 2)]


def test_annotate_columns_allows_parent_center_offset_for_unequal_leaf_widths():
    bands = [
        {"id": 2, "x0": 197.8, "x1": 277.5},
        {"id": 3, "x0": 284.7, "x1": 321.6},
        {"id": 4, "x0": 343.4, "x1": 388.9},
        {"id": 5, "x0": 437.1, "x1": 456.3},
    ]
    parents = [
        _atom("父一", 235.2, 517, 277.5, 527, 1),
        _atom("父二", 369.7, 517, 411.9, 527, 2),
    ]
    leaves = [
        _atom("叶一", 231.8, 539, 252.9, 549, 3),
        _atom("叶二", 284.7, 539, 321.6, 549, 4),
        _atom("叶三", 365.4, 539, 386.5, 549, 5),
        _atom("叶四上", 401.2, 532, 454.0, 543, 6),
        _atom("叶四下", 419.5, 547, 456.3, 557, 7),
    ]

    annotate_columns([*parents, *leaves], bands, header_cutoff=560)

    assert [
        (atom["column_start"], atom["column_end"], atom["colspan"])
        for atom in parents
    ] == [(2, 3, 2), (4, 5, 2)]


def test_annotate_columns_infers_top_parent_from_mixed_child_spans():
    bands = [
        {"id": 1, "x0": 72.4, "x1": 167.1},
        {"id": 2, "x0": 199.2, "x1": 277.7},
        {"id": 3, "x0": 284.7, "x1": 321.6},
        {"id": 4, "x0": 339.8, "x1": 385.3},
        {"id": 5, "x0": 431.9, "x1": 451.1},
        {"id": 6, "x0": 462.6, "x1": 520.1},
    ]
    atoms = [
        _atom("期末余额", 334.8, 301.1, 377.0, 311.6, 1),
        _atom("类别", 72.4, 323.3, 98.8, 333.8, 2),
        _atom("账面余额", 235.5, 318.1, 277.7, 328.7, 3),
        _atom("坏账准备", 367.0, 318.1, 409.3, 328.7, 4),
        _atom("账面", 496.5, 324.9, 517.7, 336.0, 5),
        _atom("金额", 233.2, 340.2, 254.3, 350.7, 6),
        _atom("比例(%)", 284.7, 339.4, 321.6, 351.5, 7),
        _atom("金额", 361.8, 340.2, 382.9, 350.7, 8),
        _atom("预期信用损", 396.0, 333.5, 448.8, 344.0, 9),
        _atom("失率(%)", 414.2, 347.0, 451.1, 358.3, 10),
        _atom("价值", 496.5, 339.0, 517.7, 350.0, 11),
    ]

    annotate_columns(atoms, bands, header_cutoff=360)

    assert (atoms[0]["column_start"], atoms[0]["column_end"], atoms[0]["colspan"]) == (2, 6, 5)
    assert (atoms[4]["column_start"], atoms[4]["column_end"], atoms[4]["colspan"]) == (6, 6, 1)
    assert (atoms[8]["column_start"], atoms[8]["column_end"], atoms[8]["colspan"]) == (5, 5, 1)


def test_annotate_columns_infers_parent_over_complete_physical_leaf_run():
    bands = [
        {"id": 1, "x0": 0, "x1": 30},
        {"id": 2, "x0": 40, "x1": 55, "kind": "header_only_note"},
        {"id": 3, "x0": 60, "x1": 90},
        {"id": 4, "x0": 95, "x1": 125, "kind": "sparse_body"},
        {"id": 5, "x0": 130, "x1": 160, "kind": "sparse_body"},
        {"id": 6, "x0": 165, "x1": 195, "kind": "sparse_body"},
        {"id": 7, "x0": 200, "x1": 230},
        {"id": 8, "x0": 235, "x1": 265, "kind": "sparse_body"},
        {"id": 9, "x0": 270, "x1": 300},
        {"id": 10, "x0": 305, "x1": 335},
        {"id": 11, "x0": 340, "x1": 370},
    ]
    parent = _atom("年度", 205, 10, 225, 18, 1)
    leaves = [
        _atom(f"叶{column}", band["x0"] + 5, 30, band["x1"] - 5, 38, column)
        for column, band in enumerate(bands[2:], 3)
    ]

    annotate_columns([parent, *leaves], bands, header_cutoff=40)

    assert (parent["column_start"], parent["column_end"], parent["colspan"]) == (3, 11, 9)
    assert parent["bbox"] == [205, 10, 225, 18]


def test_annotate_columns_rejects_parent_when_physical_leaf_run_has_a_gap():
    bands = [
        {"id": 1, "x0": 0, "x1": 30},
        {"id": 2, "x0": 40, "x1": 70},
        {"id": 3, "x0": 80, "x1": 110},
        {"id": 4, "x0": 120, "x1": 150},
    ]
    parent = _atom("年度", 82, 10, 102, 18, 1)
    leaves = [
        _atom("叶一", 85, 30, 105, 38, 2),
        _atom("叶三", 125, 30, 145, 38, 3),
    ]

    annotate_columns([parent, *leaves], bands, header_cutoff=40)

    assert parent["colspan"] == 1


def test_annotate_columns_rejects_top_parent_when_child_coverage_is_incomplete():
    bands = [
        {"id": 1, "x0": 72.4, "x1": 167.1},
        {"id": 2, "x0": 199.2, "x1": 277.7},
        {"id": 3, "x0": 284.7, "x1": 321.6},
        {"id": 4, "x0": 339.8, "x1": 385.3},
        {"id": 5, "x0": 431.9, "x1": 451.1},
        {"id": 6, "x0": 462.6, "x1": 520.1},
    ]
    atoms = [
        _atom("期末余额", 334.8, 301.1, 377.0, 311.6, 1),
        _atom("类别", 72.4, 323.3, 98.8, 333.8, 2),
        _atom("账面余额", 235.5, 318.1, 277.7, 328.7, 3),
        _atom("坏账准备", 367.0, 318.1, 409.3, 328.7, 4),
        _atom("金额", 233.2, 340.2, 254.3, 350.7, 5),
        _atom("比例(%)", 284.7, 339.4, 321.6, 351.5, 6),
        _atom("金额", 361.8, 340.2, 382.9, 350.7, 7),
        _atom("预期信用损", 396.0, 333.5, 448.8, 344.0, 8),
        _atom("失率(%)", 414.2, 347.0, 451.1, 358.3, 9),
    ]

    annotate_columns(atoms, bands, header_cutoff=360)

    assert atoms[0]["colspan"] == 1


def test_annotate_columns_rejects_top_parent_when_target_slot_has_peer_text():
    bands = [
        {"id": 1, "x0": 0, "x1": 20},
        {"id": 2, "x0": 20, "x1": 40},
        {"id": 3, "x0": 40, "x1": 60},
        {"id": 4, "x0": 60, "x1": 80},
        {"id": 5, "x0": 80, "x1": 100},
    ]
    atoms = [
        _atom("顶层", 45, 0, 55, 10, 1),
        _atom("同层标题", 45, 0, 55, 10, 2),
        _atom("组一", 20, 20, 40, 30, 3),
        _atom("组二", 60, 20, 80, 30, 4),
        _atom("叶一", 5, 40, 15, 50, 5),
        _atom("叶二", 25, 40, 35, 50, 6),
        _atom("叶三", 45, 40, 55, 50, 7),
        _atom("叶四", 65, 40, 75, 50, 8),
        _atom("终端", 85, 20, 95, 30, 9),
    ]

    annotate_columns(atoms, bands, header_cutoff=55)

    assert atoms[0]["colspan"] == 1


def test_complete_child_group_rejects_peer_that_overlaps_target_band():
    bands = [
        {"id": 1, "x0": 0, "x1": 20},
        {"id": 2, "x0": 20, "x1": 40},
        {"id": 3, "x0": 40, "x1": 60},
        {"id": 4, "x0": 60, "x1": 80},
        {"id": 5, "x0": 80, "x1": 100},
        {"id": 6, "x0": 100, "x1": 120},
    ]
    parent = _atom("顶层", 65, 0, 75, 10, 1)
    peer = _atom("边界文字", 0, 0, 30, 10, 2)
    child_one = _atom("组一", 25, 20, 35, 30, 3)
    child_two = _atom("组二", 65, 20, 75, 30, 4)
    terminal = _atom("终端", 105, 20, 115, 30, 5)

    inferred = _infer_complete_child_group_span(
        parent,
        [parent, peer, child_one, child_two, terminal],
        bands,
        header_cutoff=35,
        inferred_spans={id(child_one): [2, 3], id(child_two): [4, 5]},
    )

    assert inferred == []


def test_annotate_columns_does_not_force_pair_an_incomplete_leaf_tier():
    bands = [
        {"id": 1, "x0": 10, "x1": 40},
        {"id": 2, "x0": 50, "x1": 80},
        {"id": 3, "x0": 90, "x1": 120},
        {"id": 4, "x0": 130, "x1": 160},
    ]
    parents = [
        _atom("父一", 52, 10, 78, 18, 1),
        _atom("父二", 132, 10, 158, 18, 2),
    ]
    leaves = [
        _atom("叶一", 52, 30, 78, 38, 3),
        _atom("叶二", 92, 30, 118, 38, 4),
        _atom("叶三", 132, 30, 158, 38, 5),
    ]

    annotate_columns([*parents, *leaves], bands, header_cutoff=40)

    assert [atom["colspan"] for atom in parents] == [1, 1]


def test_rescue_sparse_body_bands_keeps_a_clear_inner_track():
    bands = [
        {"id": 1, "x0": 10, "x1": 30, "support": 4, "y_support": 2},
        {"id": 2, "x0": 90, "x1": 110, "support": 4, "y_support": 2},
    ]
    atoms = [
        _atom("100", 10, 40, 30, 48, 1),
        _atom("200", 90, 40, 110, 48, 2),
        _atom("附加", 48, 40, 58, 48, 3),
    ]

    refined = rescue_sparse_body_bands(atoms, bands, header_cutoff=30)

    assert len(refined) == 3
    assert any(band.get("kind") == "sparse_body" for band in refined)


def test_rescue_header_only_note_band_keeps_a_note_gap_as_a_physical_column():
    bands = [
        {"id": 1, "x0": 10, "x1": 40, "support": 5, "y_support": 5},
        {"id": 2, "x0": 70, "x1": 100, "support": 5, "y_support": 5},
        {"id": 3, "x0": 130, "x1": 160, "support": 5, "y_support": 5},
    ]
    atoms = [
        _atom("项目", 16, 10, 34, 18, 1),
        _atom("附注五", 45, 10, 60, 18, 2),
        _atom("金额", 76, 30, 94, 38, 3),
    ]

    rescue = getattr(header_topology, "rescue_header_only_note_bands", None)
    assert rescue is not None
    rescued = rescue(atoms, bands, header_cutoff=25)

    assert [(band["x0"], band["x1"], band.get("kind")) for band in rescued] == [
        (10, 40, None),
        (45, 60, "header_only_note"),
        (70, 100, None),
        (130, 160, None),
    ]


def test_rescue_header_only_leaf_band_keeps_a_trailing_empty_body_column():
    bands = [
        {"id": 1, "x0": 10, "x1": 30, "support": 6, "y_support": 6},
        {"id": 2, "x0": 70, "x1": 90, "support": 6, "y_support": 6},
        {"id": 3, "x0": 130, "x1": 150, "support": 6, "y_support": 6},
        {"id": 4, "x0": 190, "x1": 210, "support": 6, "y_support": 6},
    ]
    atoms = [
        _atom("类别", 10, 10, 30, 20, 1),
        _atom("寿命", 70, 10, 90, 20, 2),
        _atom("依据", 130, 10, 150, 20, 3),
        _atom("方法", 190, 10, 210, 20, 4),
        _atom("空列表头", 250, 10, 290, 20, 5),
    ]

    rescue = getattr(header_topology, "rescue_header_only_leaf_bands", None)
    assert rescue is not None
    rescued = rescue(atoms, bands, header_cutoff=25)

    assert [(band["x0"], band["x1"], band.get("kind")) for band in rescued] == [
        (10, 30, None),
        (70, 90, None),
        (130, 150, None),
        (190, 210, None),
        (250, 290, "header_only_leaf"),
    ]


def test_rescue_header_only_leaf_band_keeps_an_inner_empty_body_column():
    bands = [
        {"id": 1, "x0": 10, "x1": 30, "support": 4, "y_support": 4},
        {"id": 2, "x0": 90, "x1": 110, "support": 4, "y_support": 4},
    ]
    atoms = [
        _atom("左列", 10, 10, 30, 20, 1),
        _atom("空列表头", 45, 10, 70, 20, 2),
        _atom("右列", 90, 10, 110, 20, 3),
    ]

    rescued = header_topology.rescue_header_only_leaf_bands(
        atoms, bands, header_cutoff=25
    )

    assert [band.get("kind") for band in rescued] == [
        None,
        "header_only_leaf",
        None,
    ]


def test_rescue_header_only_leaf_band_rejects_a_parent_header_level():
    bands = [
        {"id": 1, "x0": 10, "x1": 30, "support": 4, "y_support": 4},
        {"id": 2, "x0": 70, "x1": 90, "support": 4, "y_support": 4},
        {"id": 3, "x0": 130, "x1": 150, "support": 4, "y_support": 4},
    ]
    atoms = [
        _atom("父标题", 180, 5, 220, 15, 1),
        _atom("叶子一", 10, 25, 30, 35, 2),
        _atom("叶子二", 70, 25, 90, 35, 3),
        _atom("叶子三", 130, 25, 150, 35, 4),
    ]

    rescued = header_topology.rescue_header_only_leaf_bands(
        atoms, bands, header_cutoff=40
    )

    assert len(rescued) == len(bands)


def test_rescue_header_only_leaf_band_rejects_a_nearby_field_fragment():
    bands = [
        {"id": 1, "x0": 10, "x1": 30, "support": 4, "y_support": 4},
        {"id": 2, "x0": 70, "x1": 90, "support": 4, "y_support": 4},
        {"id": 3, "x0": 130, "x1": 150, "support": 4, "y_support": 4},
    ]
    atoms = [
        _atom("类别", 10, 10, 30, 20, 1),
        _atom("依据", 70, 10, 90, 20, 2),
        _atom("摊销方", 130, 10, 150, 20, 3),
        _atom("法", 153, 10, 163, 20, 4),
    ]

    rescued = header_topology.rescue_header_only_leaf_bands(
        atoms, bands, header_cutoff=25
    )

    assert len(rescued) == len(bands)


def test_rescue_header_only_note_band_rejects_parenthetical_annotation_text():
    bands = [
        {"id": 1, "x0": 10, "x1": 40, "support": 5, "y_support": 5},
        {"id": 2, "x0": 70, "x1": 100, "support": 5, "y_support": 5},
    ]
    atoms = [
        _atom("项目", 16, 10, 34, 18, 1),
        _atom("（除特别注明外）", 45, 10, 65, 18, 2),
        _atom("金额", 76, 30, 94, 38, 3),
    ]

    rescued = header_topology.rescue_header_only_note_bands(
        atoms, bands, header_cutoff=25
    )

    assert len(rescued) == len(bands)


def test_rescue_header_only_note_band_rejects_ordinary_english_note_phrase():
    bands = [
        {"id": 1, "x0": 10, "x1": 40, "support": 5, "y_support": 5},
        {"id": 2, "x0": 70, "x1": 100, "support": 5, "y_support": 5},
    ]
    atoms = [
        _atom("项目", 16, 10, 34, 18, 1),
        _atom("Note payable", 45, 10, 65, 18, 2),
        _atom("金额", 76, 30, 94, 38, 3),
    ]

    rescued = header_topology.rescue_header_only_note_bands(
        atoms, bands, header_cutoff=25
    )

    assert len(rescued) == len(bands)


def test_rescue_header_only_note_band_rejects_long_english_note_reference():
    bands = [
        {"id": 1, "x0": 10, "x1": 40, "support": 5, "y_support": 5},
        {"id": 2, "x0": 70, "x1": 100, "support": 5, "y_support": 5},
    ]
    for text in ("Note (abc)", "(Note (abc))"):
        atoms = [
            _atom("项目", 16, 10, 34, 18, 1),
            _atom(text, 45, 10, 65, 18, 2),
            _atom("金额", 76, 30, 94, 38, 3),
        ]

        rescued = header_topology.rescue_header_only_note_bands(
            atoms, bands, header_cutoff=25
        )

        assert len(rescued) == len(bands)


def test_rescue_header_only_note_band_rejects_long_numeric_note_reference():
    bands = [
        {"id": 1, "x0": 10, "x1": 40, "support": 5, "y_support": 5},
        {"id": 2, "x0": 70, "x1": 100, "support": 5, "y_support": 5},
    ]
    for text in ("45(abc)", "45(foo)"):
        atoms = [
            _atom("项目", 16, 10, 34, 18, 1),
            _atom(text, 45, 10, 65, 18, 2),
            _atom("金额", 76, 30, 94, 38, 3),
        ]

        rescued = header_topology.rescue_header_only_note_bands(
            atoms, bands, header_cutoff=25
        )

        assert len(rescued) == len(bands)


def test_rescue_header_only_note_band_accepts_english_note_references():
    bands = [
        {"id": 1, "x0": 10, "x1": 40, "support": 5, "y_support": 5},
        {"id": 2, "x0": 70, "x1": 100, "support": 5, "y_support": 5},
    ]
    for text in ("Note i", "(note i)"):
        atoms = [
            _atom("项目", 16, 10, 34, 18, 1),
            _atom(text, 45, 10, 65, 18, 2),
            _atom("金额", 76, 30, 94, 38, 3),
        ]

        rescued = header_topology.rescue_header_only_note_bands(
            atoms, bands, header_cutoff=25
        )

        assert len(rescued) == len(bands) + 1


def test_rescue_sparse_body_bands_uses_line_height_for_wrapped_inner_field():
    bands = [
        {"id": 1, "x0": 71, "x1": 120, "support": 2, "y_support": 2},
        {"id": 2, "x0": 395, "x1": 518, "support": 3, "y_support": 3},
    ]
    atoms = [
        _atom("左列", 72, 157, 120, 169, 1),
        _atom("中央多行\n字段内容\n末行", 234, 142, 366, 185, 2),
        _atom("右列多行字段", 395, 157, 518, 170, 3),
    ]

    refined = rescue_sparse_body_bands(atoms, bands, header_cutoff=148)

    assert len(refined) == 3
    assert [(band["x0"], band["x1"]) for band in refined] == [
        (71, 120),
        (234, 366),
        (395, 518),
    ]


def test_rescue_sparse_body_bands_does_not_split_nearby_wrapped_phrase():
    bands = [
        {"id": 1, "x0": 10, "x1": 30, "support": 2, "y_support": 2},
        {"id": 2, "x0": 90, "x1": 110, "support": 2, "y_support": 2},
    ]
    atoms = [
        _atom("左", 10, 40, 30, 50, 1),
        _atom("同一短语\n续行", 34, 28, 66, 62, 2),
        _atom("右", 70, 40, 90, 50, 3),
    ]

    refined = rescue_sparse_body_bands(atoms, bands, header_cutoff=20)

    assert len(refined) == 2


def test_rescue_sparse_body_bands_accepts_none_font_size_with_line_bbox_fallback():
    bands = [
        {"id": 1, "x0": 71, "x1": 120, "support": 2, "y_support": 2},
        {"id": 2, "x0": 395, "x1": 518, "support": 3, "y_support": 3},
    ]
    atoms = [
        _atom("左列", 72, 157, 120, 169, 1),
        _atom("中央多行\n字段内容", 234, 142, 366, 185, 2),
        _atom("右列", 395, 157, 518, 170, 3),
    ]
    atoms[1]["font_size"] = None

    refined = rescue_sparse_body_bands(atoms, bands, header_cutoff=148)

    assert len(refined) == 3


def test_refine_leaf_bands_rejects_split_when_body_atom_crosses_split_line():
    bands = [{"id": 1, "x0": 470.0, "x1": 512.2, "support": 4, "y_support": 3}]
    atoms = [
        _atom("页", 470.0, 10, 484.1, 20, 1),
        _atom("次", 498.1, 10, 512.2, 20, 2),
        _atom("1-6", 480.6, 30, 501.5, 40, 3),
        _atom("11-12", 473.5, 50, 508.6, 60, 4),
    ]

    refined, cutoff = refine_leaf_bands(atoms, bands)

    assert cutoff is not None
    assert len(refined) == 1
    assert refined[0]["x0"] == 470.0
    assert refined[0]["x1"] == 512.2


def test_refine_leaf_bands_accepts_split_when_body_atoms_are_independent_columns():
    bands = [{"id": 1, "x0": 10.0, "x1": 90.0, "support": 7, "y_support": 4}]
    atoms = [
        _atom("股权比例", 25.0, 10, 75.0, 20, 1),
        _atom("直接", 15.0, 30, 35.0, 40, 2),
        _atom("间接", 65.0, 30, 85.0, 40, 3),
        _atom("60", 15.0, 60, 35.0, 70, 4),
        _atom("40", 65.0, 60, 85.0, 70, 5),
        _atom("70", 15.0, 80, 35.0, 90, 6),
        _atom("30", 65.0, 80, 85.0, 90, 7),
    ]

    refined, cutoff = refine_leaf_bands(atoms, bands)

    assert cutoff is not None
    assert len(refined) == 2
    assert refined[0]["x0"] == 10.0
    assert refined[0]["x1"] == 50.0
    assert refined[1]["x0"] == 50.0
    assert refined[1]["x1"] == 90.0





def test_rescue_sparse_body_bands_ignores_header_region_atoms():
    bands = [
        {"id": 1, "x0": 140.0, "x1": 280.0, "support": 3, "y_support": 3},
        {"id": 2, "x0": 470.0, "x1": 512.0, "support": 3, "y_support": 3},
    ]
    atoms = [
        _atom("目", 250.0, 10, 264.0, 20, 1),
        _atom("录", 300.0, 10, 314.0, 20, 2),
        _atom("页次", 470.0, 10, 512.0, 20, 3),
        _atom("审计报告", 140.0, 30, 200.0, 40, 4),
        _atom("1-6", 480.0, 30, 500.0, 40, 5),
    ]

    refined = rescue_sparse_body_bands(atoms, bands, header_cutoff=25)

    assert len(refined) == 2
