from hexai_pdf_parser.tables.wireless_structure.header_topology import (
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
