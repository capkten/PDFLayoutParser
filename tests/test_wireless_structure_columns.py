from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.columns import (
    assign_column,
    infer_column_bands,
)
from hexai_pdf_parser.tables.wireless_structure import columns


def _atom(text, x0, y0, x1=None):
    return {
        "text": text,
        "bbox": [x0, y0, x1 if x1 is not None else x0 + 10, y0 + 8],
        "font_size": 10,
    }


def test_infer_column_bands_uses_repeated_overlapping_x_tracks():
    atoms = [
        _atom("项目一", 10, 10, 35),
        _atom("项目二", 10, 30, 35),
        _atom("100", 100, 10, 120),
        _atom("200", 100, 30, 120),
    ]

    bands = infer_column_bands(atoms, BBox(0, 0, 200, 60))

    assert [(band["x0"], band["x1"]) for band in bands] == [(10, 35), (100, 120)]
    assert assign_column(_atom("150", 102, 50, 118), bands) == bands[1]["id"]


def test_infer_column_bands_merges_narrow_placeholder_with_right_aligned_amounts():
    atoms = [
        _atom("100.00", 180.0, 10.0, 225.9),
        _atom("200.00", 180.0, 30.0, 225.9),
        _atom("-", 222.14, 50.0, 225.904),
        _atom("-", 222.14, 70.0, 225.904),
    ]

    bands = infer_column_bands(atoms, BBox(0.0, 0.0, 400.0, 90.0))

    assert len(bands) == 1
    assert bands[0]["x0"] == 180.0
    assert bands[0]["x1"] == 225.904


def test_wide_spanning_header_does_not_bridge_body_columns():
    atoms = [
        _atom("项目", 10, 10, 35),
        _atom("项目", 10, 30, 35),
        _atom("金额", 100, 10, 120),
        _atom("金额", 100, 30, 120),
        _atom("合计", 40, 20, 180),
    ]

    bands = infer_column_bands(atoms, BBox(0, 0, 200, 60))

    assert len(bands) == 2


def _run_atom(text, x0, y0, x1, flow, source_line):
    return {
        "text": text,
        "bbox": [x0, y0, x1, y0 + 10],
        "font_size": 10.5,
        "flow_start": flow,
        "flow_end": flow,
        "source_blocks": [0],
        "source_line_start": source_line,
        "source_line_end": source_line,
    }


def test_prune_paired_cjk_artifact_band_removes_second_character_track():
    atoms = [
        _run_atom("项", 170, 10, 180.5, 1, 1),
        _run_atom("目", 191, 10, 201.5, 2, 1),
        _run_atom("职工薪酬", 100, 30, 142, 3, 2),
        _run_atom("办公费", 100, 50, 132, 6, 3),
        _run_atom("聘请中介机构费", 100, 60, 174, 8, 4),
        _run_atom("其他", 100, 70, 121, 9, 4),
        _run_atom("合", 170, 90, 180.5, 12, 5),
        _run_atom("计", 191, 90, 201.5, 13, 5),
    ]
    for y, flow in [(10, 20), (30, 23), (50, 26), (70, 29), (90, 32)]:
        atoms.extend(
            [
                _run_atom("100", 306, y, 370, flow, int(y)),
                _run_atom("90", 401, y, 463, flow + 1, int(y)),
            ]
        )
    bands = infer_column_bands(atoms, BBox(90, 0, 470, 110))

    result = columns.prune_paired_cjk_artifact_bands(atoms, bands)

    assert len(bands) == 4
    assert [(band["x0"], band["x1"]) for band in result] == [
        (100, 180.5),
        (306, 370),
        (401, 463),
    ]
    assert [band["id"] for band in result] == [1, 2, 3]


def test_prune_paired_cjk_artifact_band_keeps_real_single_character_column():
    atoms = [
        _run_atom("甲", 100, 10, 110, 1, 1),
        _run_atom("一", 140, 10, 150, 2, 1),
        _run_atom("乙", 100, 30, 110, 3, 2),
        _run_atom("二", 140, 30, 150, 4, 2),
    ]
    bands = infer_column_bands(atoms, BBox(90, 0, 170, 50))

    result = columns.prune_paired_cjk_artifact_bands(atoms, bands)

    assert len(result) == 2


def _add_amount_tracks(atoms, y_levels):
    for index, y in enumerate(y_levels, 1):
        flow = 100 + index * 3
        atoms.extend(
            [
                _run_atom("100", 300, y, 340, flow, 100 + index),
                _run_atom("90", 400, y, 440, flow + 1, 100 + index),
            ]
        )


def test_prune_sparse_alignment_band_merges_centered_outer_labels():
    atoms = [
        _run_atom("项目", 168, 10, 189, 1, 1),
        _run_atom("正文一", 100, 30, 142, 2, 2),
        _run_atom("正文二", 100, 50, 163, 3, 3),
        _run_atom("合计", 168, 70, 189, 4, 4),
    ]
    _add_amount_tracks(atoms, [10, 30, 50, 70])
    bands = infer_column_bands(atoms, BBox(90, 0, 470, 90))

    result = columns.prune_sparse_alignment_artifact_bands(atoms, bands)

    assert len(bands) == 4
    assert [(band["x0"], band["x1"]) for band in result] == [
        (100, 163),
        (300, 340),
        (400, 440),
    ]


def test_prune_sparse_alignment_band_keeps_columns_occupied_on_same_rows():
    atoms = [
        _run_atom("甲", 100, 10, 120, 1, 1),
        _run_atom("一", 124, 10, 145, 2, 1),
        _run_atom("乙", 100, 30, 120, 3, 2),
        _run_atom("二", 124, 30, 145, 4, 2),
    ]
    _add_amount_tracks(atoms, [10, 30])
    bands = infer_column_bands(atoms, BBox(90, 0, 470, 50))

    result = columns.prune_sparse_alignment_artifact_bands(atoms, bands)

    assert len(result) == len(bands) == 4


def test_prune_sparse_alignment_band_keeps_columns_separated_by_normal_gap():
    atoms = [
        _run_atom("表头", 150, 10, 170, 1, 1),
        _run_atom("正文一", 100, 30, 120, 2, 2),
        _run_atom("正文二", 100, 50, 120, 3, 3),
        _run_atom("表尾", 150, 70, 170, 4, 4),
    ]
    _add_amount_tracks(atoms, [10, 30, 50, 70])
    bands = infer_column_bands(atoms, BBox(90, 0, 470, 90))

    result = columns.prune_sparse_alignment_artifact_bands(atoms, bands)

    assert len(result) == len(bands) == 4


def test_infer_column_bands_excludes_sparse_left_section_title():
    atoms = [
        # Column 1 items
        _atom("短期借款", 120, 10, 150),
        _atom("应付账款", 120, 30, 150),
        _atom("应付票据", 120, 50, 150),
        # Single wide item spanning across col 1 into col 2
        _atom("以公允价值计量且其变动计入当期损益的金融负债", 120, 20, 275),
        # Column 2 (note column)
        _atom("附注", 260, 10, 285),
        _atom("注释1", 260, 30, 285),
        _atom("注释2", 260, 50, 285),
        # Column 3 (amount column)
        _atom("100.00", 320, 10, 360),
        _atom("200.00", 320, 30, 360),
        _atom("300.00", 320, 50, 360),
    ]
    region = BBox(110, 0, 400, 70)

    bands = infer_column_bands(atoms, region)

    assert len(bands) == 3
    assert [(band["x0"], band["x1"]) for band in bands] == [
        (120, 150),
        (260, 285),
        (320, 360),
    ]
