from hexai_pdf_parser.tables.wireless_structure.text_runs import infer_output_order_mode


def _span(text, x0, x1, y, flow, block, line=0):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 10],
        "flow": flow,
        "source_position": [block, line, 0],
        "source_position_known": True,
        "font_size": 10,
    }


def test_infer_output_order_mode_detects_columnar_left_column_stream():
    spans = [
        _span(f"左{i}", 10, 50, 10 + i * 14, i + 1, i + 1)
        for i in range(8)
    ] + [
        _span(f"右{i}", 120, 160, 10 + i * 14, 9 + i, 20 + i)
        for i in range(4)
    ]

    assert infer_output_order_mode(spans) == "columnar"


def test_infer_output_order_mode_keeps_interleaved_rows():
    spans = [
        _span("左一", 10, 50, 10, 1, 1),
        _span("右一", 120, 160, 10, 2, 1),
        _span("左二", 10, 50, 24, 3, 2),
        _span("右二", 120, 160, 24, 4, 2),
    ]

    assert infer_output_order_mode(spans) == "row_interleaved"


def test_collect_native_spans_preserves_block_line_span_position():
    from hexai_pdf_parser.tables.wireless_table_recovery import collect_native_spans

    class Page:
        def get_text(self, kind, flags):
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {"spans": [{"text": "", "chars": [{"c": "甲", "bbox": [0, 0, 5, 10]},], "bbox": [0, 0, 5, 10], "font": "SimSun", "size": 10}]},
                            {"spans": [{"text": "", "chars": [{"c": "乙", "bbox": [0, 12, 5, 22]},], "bbox": [0, 12, 5, 22], "font": "SimSun", "size": 10}]},
                        ],
                    }
                ]
            }

    spans = collect_native_spans(Page())

    assert [span.source_position for span in spans] == [(0, 0, 0), (0, 1, 0)]


def test_infer_output_order_mode_ignores_dense_right_header_rows():
    left = [
        _span(f"左{i}", 10, 50, 10 + i * 14, i + 1, i + 1)
        for i in range(8)
    ]
    right_header = [
        _span(f"表头{i}", 120 + i * 12, 128 + i * 12, 10, 9 + i, 20)
        for i in range(8)
    ]
    right_values = [
        _span(f"值{i}", 120, 160, 120 + i * 14, 17 + i, 30 + i)
        for i in range(4)
    ]

    assert infer_output_order_mode(left + right_header + right_values) == "columnar"


def test_infer_output_order_mode_does_not_classify_one_wrapped_field_as_columnar():
    spans = [
        _span(f"换行{i}", 10, 50, 10 + i * 14, i + 1, i + 1)
        for i in range(5)
    ]
    spans.append(_span("右侧见证", 120, 160, 38, 6, 10))

    assert infer_output_order_mode(spans) == "row_interleaved"


def _atom(text, x0, x1, y, flow, block, line=0):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 10],
        "flow": flow,
        "source_position": [block, line, 0],
        "source_position_known": True,
        "font": "SimSun",
        "font_size": 10,
        "bold": False,
        "span_ref": f"S{flow}",
        "char_boxes": [],
    }


def test_columnar_mode_keeps_independent_left_blocks_separate():
    from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs

    atoms = [
        _atom("左一", 10, 50, 10, 1, 1),
        _atom("左二", 10, 50, 24, 2, 2),
        _atom("左三", 10, 50, 38, 3, 3),
        _atom("右侧", 120, 160, 24, 4, 4),
    ]

    result = build_text_runs(atoms, output_mode="columnar")

    assert [item["text"] for item in result] == ["左一", "左二", "左三", "右侧"]


def test_columnar_mode_merges_only_adjacent_lines_from_one_native_block():
    from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs

    atoms = [
        _atom("第一行", 10, 50, 10, 1, 1, line=0),
        _atom("第二行", 10, 50, 24, 2, 1, line=1),
        _atom("右侧", 120, 160, 17, 3, 2),
    ]

    result = build_text_runs(atoms, output_mode="columnar")

    assert [item["text"] for item in result] == ["第一行\n第二行", "右侧"]
    assert result[0]["merge_kind"] == "same_native_block_lines"
    assert result[0]["source_blocks"] == [1]
