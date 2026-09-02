from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs


def _span(
    text,
    x0,
    x1,
    order,
    source_position=(1, 1, 0),
    *,
    font="SimSun",
    font_size=10,
    y=10,
    bold=False,
):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 10],
        "order": order,
        "flow": order + 1,
        "source_position": list(source_position),
        "font": font,
        "font_size": font_size,
        "bold": bold,
        "span_ref": f"S{order}",
        "char_boxes": [],
    }


def test_build_text_runs_merges_wrapped_fields_with_mixed_western_and_cjk_fonts():
    """正例：第1行含西文字体（如年份2019/Arial Narrow）与第2行纯中文字体（仿宋）应成功合并为同一字段。"""
    spans = [
        _span("2019", 100, 120, 0, (1, 0, 0), font="Arial Narrow", y=10),
        _span("年省重大科技专项启动经", 120, 230, 1, (1, 0, 1), font="SimSun", y=10),
        _span("费（高速数据中心光互联芯片", 100, 230, 2, (1, 1, 0), font="SimSun", y=24),
        _span("研发及产业化）", 100, 170, 3, (1, 2, 0), font="SimSun", y=38),
        _span("11,600,289.11", 250, 310, 4, (1, 3, 0), font="Arial Narrow", y=24),
    ]

    result = build_text_runs(spans)

    assert [item["text"] for item in result] == [
        "2019年省重大科技专项启动经\n费（高速数据中心光互联芯片\n研发及产业化）",
        "11,600,289.11",
    ]
    assert result[0]["merge_kind"] == "wrapped_field"
    assert result[0]["flow_start"] == 1
    assert result[0]["flow_end"] == 4


def test_build_text_runs_merges_multi_line_wrapped_field_when_witness_at_lower_line():
    """正例：5行长文本，右侧伴随金额在第3行，整个多行段落应成功合并。"""
    spans = [
        _span("调频连续波激光雷达用核心半", 100, 230, 0, (1, 0, 0), y=10),
        _span("导体激光器芯片与器件项目资", 100, 230, 1, (1, 1, 0), y=24),
        _span("金，仕佳光子70%，河南省科学", 100, 230, 2, (1, 2, 0), y=38),
        _span("院物理研究所15%，河南师范大", 100, 230, 3, (1, 3, 0), y=52),
        _span("学15%", 100, 130, 4, (1, 4, 0), y=66),
        _span("336,000.00", 250, 310, 5, (1, 5, 0), font="Arial Narrow", y=38),
    ]

    result = build_text_runs(spans)

    assert [item["text"] for item in result] == [
        "调频连续波激光雷达用核心半\n导体激光器芯片与器件项目资\n金，仕佳光子70%，河南省科学\n院物理研究所15%，河南师范大\n学15%",
        "336,000.00",
    ]


def test_build_text_runs_keeps_distinct_bold_styles_separate():
    """反例：粗体（如分组小标题）与普通字重的文本行应保持独立，不误并。"""
    spans = [
        _span("项目小标题", 100, 180, 0, (1, 0, 0), bold=True, y=10),
        _span("正文项目明细说明", 100, 200, 1, (1, 1, 0), bold=False, y=24),
        _span("100.00", 250, 290, 2, (1, 2, 0), y=24),
    ]

    result = build_text_runs(spans)

    assert [item["text"] for item in result] == [
        "项目小标题",
        "正文项目明细说明",
        "100.00",
    ]


def test_build_text_runs_keeps_distinct_font_sizes_separate():
    """反例：字号明显不同的文本行（如标题与附注说明）应保持独立，不误并。"""
    spans = [
        _span("大字号标题", 100, 200, 0, (1, 0, 0), font_size=14, y=10),
        _span("小字号说明文字", 100, 200, 1, (1, 1, 0), font_size=9, y=26),
        _span("500.00", 250, 290, 2, (1, 2, 0), y=26),
    ]

    result = build_text_runs(spans)

    assert [item["text"] for item in result] == [
        "大字号标题",
        "小字号说明文字",
        "500.00",
    ]


def test_build_text_runs_keeps_consecutive_amount_rows_separate():
    """反例：连续两个独立的金额数值行必须保持分离。"""
    spans = [
        _span("100.00", 100, 150, 0, (1, 0, 0), font="Arial Narrow", y=10),
        _span("200.00", 100, 150, 1, (1, 1, 0), font="Arial Narrow", y=24),
        _span("右侧", 240, 280, 2, (1, 2, 0), y=17),
    ]

    result = build_text_runs(spans)

    assert [item["text"] for item in result] == ["100.00", "200.00", "右侧"]


def test_build_text_runs_keeps_colon_ended_category_headers_separate():
    """反例：以冒号结尾的分类标题（如流动负债：）与下一行具体科目（如短期借款）必须保持分离，即使右侧存在金额伴随。"""
    spans = [
        _span("流动负债：", 100, 150, 0, (1, 0, 0), y=10),
        _span("短期借款", 100, 150, 1, (1, 1, 0), y=24),
        _span("5,248,944,717.37", 250, 320, 2, (1, 2, 0), y=24),
    ]

    result = build_text_runs(spans)

    assert [item["text"] for item in result] == [
        "流动负债：",
        "短期借款",
        "5,248,944,717.37",
    ]
