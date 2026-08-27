from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs


def _atom(text, x0, x1, order, source_position=(1, 1, 0), *, font_size=10):
    return {
        "text": text,
        "bbox": [x0, 10, x1, 20],
        "order": order,
        "flow": order + 1,
        "source_position": list(source_position),
        "font": "SimSun",
        "font_size": font_size,
        "bold": False,
        "span_ref": f"S{order}",
        "char_boxes": [],
    }


def test_build_text_runs_merges_adjacent_chinese_fragments_on_one_native_line():
    atoms = [
        _atom("1", 10, 14, 1, (2, 3, 0)),
        _atom("年以内", 14, 38, 2, (2, 3, 1)),
    ]

    result = build_text_runs(atoms)

    assert len(result) == 1
    assert result[0]["text"] == "1年以内"
    assert result[0]["flow_start"] == 2
    assert result[0]["flow_end"] == 3
    assert result[0]["merge_kind"] == "same_line"


def test_build_text_runs_keeps_currency_and_adjacent_numeric_fields_separate():
    atoms = [
        _atom("$", 10, 16, 1, (2, 3, 0)),
        _atom("100", 17, 34, 2, (2, 3, 1)),
        _atom("200", 36, 53, 3, (2, 3, 2)),
    ]

    result = build_text_runs(atoms)

    assert [item["text"] for item in result] == ["$", "100", "200"]


def test_build_text_runs_attaches_small_superscript():
    atoms = [
        _atom("金额", 10, 24, 1, (2, 3, 0)),
        _atom("1", 24, 27, 2, (2, 3, 1), font_size=7),
    ]
    atoms[1]["bbox"] = [23, 12, 27, 19]

    result = build_text_runs(atoms)

    assert len(result) == 1
    assert result[0]["text"] == "金额1"
