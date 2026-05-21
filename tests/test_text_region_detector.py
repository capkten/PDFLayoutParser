from pdflayoutparser.text_region_detector import (
    CandidateRegion,
    HorizontalSeparator,
    detect_candidate_regions,
    score_row_structure,
)
from pdflayoutparser.text_visual_debug import TextFragment, VisualRow


def _row(*items):
    fragments = [
        TextFragment(text=text, bbox=(x0, y0, x1, y1))
        for text, x0, y0, x1, y1 in items
    ]
    return VisualRow(
        fragments=fragments,
        bbox=CandidateRegion.bbox_union([fragment.bbox for fragment in fragments]),
    )


def test_score_row_structure_flags_sparse_multi_field_row():
    row = _row(
        ("项目", 20, 30, 70, 42),
        ("123", 180, 30, 220, 42),
        ("456", 300, 30, 340, 42),
    )
    score = score_row_structure(row)
    assert score["fragment_count"] == 3
    assert score["looks_sparse"] is True


def test_detect_candidate_regions_groups_repeated_table_like_rows():
    rows = [
        _row(("项目A", 20, 30, 80, 42), ("10", 180, 30, 205, 42), ("20", 300, 30, 325, 42)),
        _row(("项目B", 20, 50, 80, 62), ("11", 180, 50, 205, 62), ("21", 300, 50, 325, 62)),
        _row(("项目C", 20, 70, 80, 82), ("12", 180, 70, 205, 82), ("22", 300, 70, 325, 82)),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert len(regions[0].rows) == 3


def test_detect_candidate_regions_rejects_dense_prose_rows():
    rows = [
        _row(("这是一段说明文字", 20, 30, 200, 42)),
        _row(("继续说明前述事项", 20, 48, 200, 60)),
        _row(("不会形成表格区域", 20, 66, 200, 78)),
    ]
    assert detect_candidate_regions(rows) == []


def test_detect_candidate_regions_requires_repeated_alignment_pattern():
    rows = [
        _row(("事项说明", 20, 30, 140, 42), ("2021", 260, 30, 300, 42)),
        _row(("更多说明文字", 20, 48, 180, 60), ("2022", 300, 48, 340, 60)),
        _row(("继续段落文本", 20, 66, 170, 78), ("15", 210, 66, 230, 78)),
    ]
    assert detect_candidate_regions(rows) == []


def test_detect_candidate_regions_prefers_rows_with_stable_numeric_columns():
    rows = [
        _row(("项目A", 20, 30, 80, 42), ("10", 180, 30, 205, 42), ("20", 300, 30, 325, 42)),
        _row(("项目B", 20, 50, 80, 62), ("11", 180, 50, 205, 62), ("21", 300, 50, 325, 62)),
        _row(("项目C", 20, 70, 80, 82), ("12", 180, 70, 205, 82), ("22", 300, 70, 325, 82)),
    ]
    region = detect_candidate_regions(rows)[0]
    assert region.features["repeated_alignment_count"] >= 2
    assert region.features["numeric_column_count"] >= 1


def test_detect_candidate_regions_keeps_only_contiguous_table_run():
    rows = [
        _row(("正文说明", 20, 20, 120, 32)),
        _row(("继续正文", 20, 38, 120, 50)),
        _row(("项目A", 20, 80, 80, 92), ("10", 180, 80, 205, 92), ("20", 300, 80, 325, 92)),
        _row(("项目B", 20, 98, 80, 110), ("11", 180, 98, 205, 110), ("21", 300, 98, 325, 110)),
        _row(("项目C", 20, 116, 80, 128), ("12", 180, 116, 205, 128), ("22", 300, 116, 325, 128)),
        _row(("结尾说明", 20, 170, 120, 182)),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert len(regions[0].rows) == 3
    assert regions[0].bbox.y0 >= 80
    assert regions[0].bbox.y1 <= 128


def test_detect_candidate_regions_keeps_wide_numeric_table_rows():
    rows = [
        _row(("列A", 20, 30, 60, 42), ("列B", 180, 30, 220, 42), ("列C", 300, 30, 340, 42)),
        _row(
            ("说明字段较长", 20, 48, 165, 60),
            ("20,136,924.05", 180, 48, 285, 60),
            ("3,537,565,613.15", 300, 48, 430, 60),
            ("3,517,428,689.10", 450, 48, 580, 60),
        ),
        _row(
            ("另一说明字段较长", 20, 66, 175, 78),
            ("20,136,924.05", 180, 66, 285, 78),
            ("14,558,725,540.92", 300, 66, 435, 78),
            ("14,538,588,616.87", 450, 66, 585, 78),
        ),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert len(regions[0].rows) == 3


def test_detect_candidate_regions_accepts_header_plus_single_data_row():
    rows = [
        _row(("公司名称", 20, 30, 90, 42), ("股权取得时点", 180, 30, 260, 42), ("股权取得成本", 320, 30, 400, 42)),
        _row(("取得比例", 120, 48, 170, 60), ("被购买方收入", 260, 48, 340, 60), ("购买方净利润", 400, 48, 480, 60)),
        _row(("北京市域铁路融合发", 20, 66, 110, 78)),
        _row(("2022年12月31日", 180, 84, 270, 96), ("其他", 320, 84, 350, 96), ("10.00%", 400, 84, 450, 96), ("0.00", 500, 84, 530, 96), ("0.00", 560, 84, 590, 96)),
        _row(("展集团有限公司", 20, 102, 110, 114)),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert len(regions[0].rows) >= 3
    assert regions[0].bbox.y1 >= 114


def test_detect_candidate_regions_keeps_trailing_bridge_row_in_bbox():
    rows = [
        _row(("表头A", 20, 30, 70, 42), ("表头B", 180, 30, 230, 42)),
        _row(("主体行", 20, 48, 120, 60), ("10", 180, 48, 210, 60), ("20", 280, 48, 310, 60)),
        _row(("续行说明", 20, 66, 110, 78)),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert regions[0].bbox.y1 >= 78


def test_detect_candidate_regions_keeps_two_bridge_rows_between_data_rows():
    rows = [
        _row(("表头A", 20, 30, 70, 42), ("表头B", 180, 30, 230, 42), ("表头C", 320, 30, 370, 42)),
        _row(("左列上半", 20, 48, 90, 60)),
        _row(("主体一", 100, 48, 180, 60), ("10", 260, 48, 290, 60), ("20", 360, 48, 390, 60)),
        _row(("左列下半", 20, 66, 90, 78)),
        _row(("第二项上半", 20, 84, 90, 96)),
        _row(("主体二", 100, 84, 180, 96), ("11", 260, 84, 290, 96), ("21", 360, 84, 390, 96)),
        _row(("第二项下半", 20, 102, 90, 114)),
    ]
    regions = detect_candidate_regions(rows)
    assert len(regions) == 1
    assert regions[0].bbox.y1 >= 114
    assert len(regions[0].rows) >= 6


def test_detect_candidate_regions_merges_header_and_body_across_separator():
    rows = [
        _row(("所属单位", 20, 30, 80, 42), ("会计差错更正的内容", 150, 30, 280, 42), ("受影响项目", 320, 30, 420, 42)),
        _row(("积影响数", 460, 48, 520, 60), ("未分配利润", 560, 48, 640, 60), ("净利润影响额", 700, 48, 790, 60)),
        _row(("北京市地铁运", 20, 84, 90, 96)),
        _row(("主体一", 100, 102, 180, 114), ("20,136,924.05", 460, 102, 560, 114), ("3,537,565,613.15", 580, 102, 710, 114), ("3,517,428,689.10", 720, 102, 840, 114)),
        _row(("营有限公司", 20, 120, 90, 132)),
        _row(("本公司", 20, 138, 70, 150)),
        _row(("主体二", 100, 156, 180, 168), ("20,136,924.05", 460, 156, 560, 168), ("14,558,725,540.92", 580, 156, 715, 168), ("14,538,588,616.87", 720, 156, 855, 168)),
        _row(("合并报表", 20, 174, 80, 186)),
    ]
    separators = [HorizontalSeparator(x0=20, x1=840, y=72)]
    regions = detect_candidate_regions(rows, horizontal_separators=separators)
    assert len(regions) == 1
    assert regions[0].bbox.y0 <= 30
    assert regions[0].bbox.y1 >= 186


def test_detect_candidate_regions_expands_upward_for_nearby_header_like_row():
    rows = [
        _row(("上方补充列A", 460, 12, 520, 24), ("上方补充列B", 560, 12, 650, 24), ("上方补充列C", 700, 12, 790, 24)),
        _row(("所属单位", 20, 30, 80, 42), ("会计差错更正的内容", 150, 30, 280, 42), ("受影响项目", 320, 30, 420, 42)),
        _row(("积影响数", 460, 48, 520, 60), ("未分配利润", 560, 48, 640, 60), ("净利润影响额", 700, 48, 790, 60)),
        _row(("北京市地铁运", 20, 84, 90, 96)),
        _row(("主体一", 100, 102, 180, 114), ("20,136,924.05", 460, 102, 560, 114), ("3,537,565,613.15", 580, 102, 710, 114), ("3,517,428,689.10", 720, 102, 840, 114)),
    ]
    separators = [HorizontalSeparator(x0=20, x1=840, y=72)]
    regions = detect_candidate_regions(rows, horizontal_separators=separators)
    assert len(regions) == 1
    assert regions[0].bbox.y0 <= 12


def test_detect_candidate_regions_expands_upward_for_dense_multi_fragment_header():
    rows = [
        _row(("上方补充A", 460, 12, 520, 24), ("上方很长的补充B", 540, 12, 730, 24), ("上方补充C", 740, 12, 800, 24)),
        _row(("所属单位", 20, 30, 80, 42), ("会计差错更正的内容", 150, 30, 280, 42), ("受影响项目", 320, 30, 420, 42)),
        _row(("积影响数", 460, 48, 520, 60), ("未分配利润", 560, 48, 640, 60), ("净利润影响额", 700, 48, 790, 60)),
        _row(("主体一", 100, 84, 180, 96), ("20,136,924.05", 460, 84, 560, 96), ("3,537,565,613.15", 580, 84, 710, 96), ("3,517,428,689.10", 720, 84, 840, 96)),
    ]
    separators = [HorizontalSeparator(x0=20, x1=840, y=72)]
    regions = detect_candidate_regions(rows, horizontal_separators=separators)
    assert len(regions) == 1
    assert regions[0].bbox.y0 <= 12
