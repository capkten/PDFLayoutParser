"""中文使用说明：无线表格恢复的回归测试。

用途：覆盖 Span 文本条合并、换行处理、标题防误合并、货币列、稀疏两列字段表，
以及 PNG/HTML/JSON 诊断导出，避免后续调整改变已验证的恢复结果。

运行方式：在仓库根目录执行
``$env:PYTHONPATH='src'; & 'D:\\conda_envs\\company_tool\\python.exe' -m pytest tests\\test_wireless_table_recovery.py -q``。
"""

from pathlib import Path

import fitz

from hexai_pdf_parser.models import BBox, Cell, Table
from hexai_pdf_parser.table_extractor import TableExtractor
from hexai_pdf_parser.wireless_table_recovery import (
    NativeSpan,
    TextStrip,
    _anchor,
    _build_table,
    _completion_date_continuations,
    _drop_orphan_field_before_title,
    _prepend_short_title,
    _significant_overlap,
    _single_field_record_runs,
    _table_quality,
    _two_row_field_runs,
    collect_native_spans,
    export_wireless_debug,
    merge_text_strips,
    merge_wrapped_rows,
    recover_wireless_tables,
)


def _make_native_borderless_table(path: Path) -> None:
    """Make a native text PDF; no ruling lines or rasterized content."""

    document = fitz.open()
    page = document.new_page(width=420, height=180)
    for x, text in [(40, "Item"), (160, "Currency"), (235, "Current"), (325, "Previous")]:
        page.insert_text((x, 45), text, fontsize=10)
    for y, label, current, previous in [(72, "Alpha", "1,200", "900"), (99, "Beta", "1,350", "1,020")]:
        page.insert_text((40, y), label, fontsize=10)
        page.insert_text((160, y), "$", fontsize=10)
        page.insert_text((180, y), current, fontsize=10)
        page.insert_text((325, y), previous, fontsize=10)
    document.save(path)
    document.close()


def test_merge_text_strips_keeps_columns_separate_but_joins_tight_font_splits():
    spans = [
        NativeSpan("$", BBox(10, 10, 14, 20), "Helvetica", 10, 0),
        NativeSpan("120", BBox(15, 10, 31, 20), "Helvetica", 10, 1),
        NativeSpan("next", BBox(60, 10, 80, 20), "Helvetica", 10, 2),
    ]

    strips = merge_text_strips(spans)

    assert [strip.text for strip in strips] == ["$120", "next"]
    assert [span.order for span in strips[0].spans] == [0, 1]


def test_merge_text_strips_joins_nearby_fields_in_visual_order():
    spans = [
        NativeSpan("证件类型：", BBox(178, 10, 231, 20), "Helvetica", 10, 0),
        NativeSpan("姓名：小小", BBox(41, 10, 105, 20), "Helvetica", 10, 1),
        NativeSpan("身份证", BBox(231.5, 10, 263, 20), "Helvetica", 10, 2),
    ]

    strips = merge_text_strips(spans)

    assert [strip.text for strip in strips] == ["姓名：小小", "证件类型：身份证"]


def test_build_table_orders_nearby_same_cell_text_by_geometry():
    def strip(text, bbox, order):
        span = NativeSpan(text, bbox, "Helvetica", 10, order)
        return TextStrip(text, bbox, [span])

    row = [
        strip("证件类型：", BBox(178, 40, 231, 50), 0),
        strip("姓名：小小", BBox(41, 40, 105, 50), 1),
        strip("身份证", BBox(231, 40, 263, 50), 2),
        strip("报告时间：今天", BBox(405, 40, 480, 50), 3),
    ]
    second_row = [
        strip("编号：1", BBox(41, 60, 100, 70), 4),
        strip("状态：正常", BBox(405, 60, 480, 70), 5),
    ]

    table, _ = _build_table([row, second_row], tracks_override=[110, 405])

    assert table is not None
    first_cell = next(cell for cell in table.cells if cell.row_index == 0 and cell.col_index == 0)
    assert first_cell.text == "姓名：小小证件类型：身份证"


def test_overlap_selection_ignores_adjacent_tables_but_prefers_complete_candidate():
    partial = Table(
        BBox(50, 510, 538, 582), 4, 2,
        [Cell("value", 0, 0, BBox(50, 510, 200, 530))],
        confidence=0.80,
    )
    complete = Table(
        BBox(42, 461, 542, 646), 11, 2,
        [Cell("value", 0, 0, BBox(42, 461, 200, 480))] * 19,
        confidence=0.95,
    )
    adjacent = BBox(42, 637, 528, 782)

    assert _significant_overlap(partial.bbox, complete.bbox)
    assert not _significant_overlap(complete.bbox, adjacent)
    assert _table_quality(complete) > _table_quality(partial)


def test_two_row_field_run_accepts_a_shifting_right_column():
    rows = [
        [
            TextStrip("Authority: A", BBox(60, 40, 180, 50), []),
            TextStrip("Date: 2023", BBox(420, 40, 520, 50), []),
        ],
        [
            TextStrip("Amount: 500", BBox(60, 60, 150, 70), []),
            TextStrip("Identifier: C1", BBox(294, 60, 410, 70), []),
        ],
    ]

    assert _two_row_field_runs(rows) == [rows]


def test_orphan_field_before_new_title_is_removed_and_title_spans_columns():
    def strip(text, bbox, order):
        span = NativeSpan(text, bbox, "Helvetica", 10, order)
        return TextStrip(text, bbox, [span])

    rows = [
        [strip("Amount: 500", BBox(60, 40, 150, 50), 0)],
        [strip("New record", BBox(42, 60, 120, 70), 1)],
        [
            strip("Court: A", BBox(60, 80, 140, 90), 2),
            strip("Case: 1", BBox(294, 80, 360, 90), 3),
        ],
    ]

    cleaned = _drop_orphan_field_before_title(rows)
    table, _ = _build_table(cleaned, tracks_override=[60, 294])

    assert [row[0].text for row in cleaned] == ["New record", "Court: A"]
    assert table is not None
    title = next(cell for cell in table.cells if cell.row_index == 0)
    assert (title.col_index, title.colspan) == (0, 2)


def test_completion_date_before_a_new_two_column_record_is_removed():
    def strip(text, bbox, order):
        span = NativeSpan(text, bbox, "Helvetica", 10, order)
        return TextStrip(text, bbox, [span])

    rows = [
        [strip("结案日期：2024 年01 月", BBox(60, 40, 180, 50), 0)],
        [
            strip("Court: A", BBox(60, 60, 140, 70), 1),
            strip("Case: 1", BBox(294, 60, 360, 70), 2),
        ],
        [
            strip("Reason: --", BBox(60, 80, 140, 90), 3),
            strip("Result: done", BBox(294, 80, 380, 90), 4),
        ],
    ]

    assert _drop_orphan_field_before_title(rows) == rows[1:]


def test_completion_date_continuation_is_a_separate_one_row_table():
    def strip(text, bbox, order):
        span = NativeSpan(text, bbox, "Helvetica", 10, order)
        return TextStrip(text, bbox, [span])

    rows = [
        [strip("结案日期：2024 年01 月", BBox(60, 40, 180, 50), 0)],
        [
            strip("Court: A", BBox(60, 60, 140, 70), 1),
            strip("Case: 1", BBox(294, 60, 360, 70), 2),
        ],
    ]

    tables = _completion_date_continuations(rows)
    assert len(tables) == 1
    assert (tables[0].rows, tables[0].cols) == (1, 2)
    assert tables[0].cells[0].text.startswith("结案日期")


def test_collect_native_spans_excludes_footer_page_number(tmp_path):
    pdf_path = tmp_path / "footer.pdf"
    document = fitz.open()
    page = document.new_page(width=300, height=400)
    page.insert_text((40, 80), "Body")
    page.insert_text((120, 380), "第3页/共5页")
    document.save(pdf_path)
    document.close()

    with fitz.open(pdf_path) as document:
        texts = [span.text for span in collect_native_spans(document[0])]

    assert "Body" in texts
    assert "第3页/共5页" not in texts


def test_merge_text_strips_splits_raw_span_with_character_level_field_positions():
    text = "左：1      右：2"
    characters = [(char, BBox(10 + index * 6, 10, 15 + index * 6, 20)) for index, char in enumerate(text)]
    span = NativeSpan(text, BBox(10, 10, 94, 20), "Helvetica", 10, 0, characters=characters)

    strips = merge_text_strips([span])

    assert [strip.text for strip in strips] == ["左：1", "右：2"]
    assert [round(strip.bbox.x0) for strip in strips] == [10, 64]


def test_merge_wrapped_rows_keeps_a_sparse_same_column_continuation():
    first = NativeSpan("Description", BBox(20, 20, 70, 30), "Helvetica", 10, 0)
    amount = NativeSpan("100", BBox(180, 20, 200, 30), "Helvetica", 10, 1)
    continuation = NativeSpan("continued", BBox(20, 33, 62, 43), "Helvetica", 10, 2)
    rows = [
        [TextStrip(first.text, first.bbox, [first]), TextStrip(amount.text, amount.bbox, [amount])],
        [TextStrip(continuation.text, continuation.bbox, [continuation])],
    ]

    merged = merge_wrapped_rows(rows)

    assert len(merged) == 1
    assert [strip.text for strip in merged[0]] == ["Description", "continued", "100"]


def test_merge_wrapped_rows_does_not_absorb_a_centered_section_title():
    label = NativeSpan("Item", BBox(20, 20, 45, 30), "Helvetica", 10, 0)
    value = NativeSpan("Amount", BBox(170, 20, 205, 30), "Helvetica", 10, 1)
    title = NativeSpan("Section", BBox(92, 33, 133, 43), "Helvetica", 10, 2)
    rows = [
        [TextStrip(label.text, label.bbox, [label]), TextStrip(value.text, value.bbox, [value])],
        [TextStrip(title.text, title.bbox, [title])],
    ]

    merged = merge_wrapped_rows(rows)

    assert len(merged) == 2
    assert [strip.text for strip in merged[1]] == ["Section"]


def test_merge_wrapped_rows_does_not_absorb_a_sparse_field_row():
    label = NativeSpan("Item", BBox(20, 20, 45, 30), "Helvetica", 10, 0)
    value = NativeSpan("Status", BBox(170, 20, 205, 30), "Helvetica", 10, 1)
    field = NativeSpan("Amount: 700", BBox(20, 33, 85, 43), "Helvetica", 10, 2)
    rows = [
        [TextStrip(label.text, label.bbox, [label]), TextStrip(value.text, value.bbox, [value])],
        [TextStrip(field.text, field.bbox, [field])],
    ]

    assert len(merge_wrapped_rows(rows)) == 2


def test_sparse_single_field_record_uses_detail_row_as_two_column_tracks():
    title = NativeSpan("欠税记录", BBox(20, 20, 65, 30), "Helvetica", 10, 0)
    full = NativeSpan("主管机关：甲  统计日期：乙", BBox(20, 38, 390, 48), "Helvetica", 10, 1)
    left = NativeSpan("欠税总额：500", BBox(20, 55, 100, 65), "Helvetica", 10, 2)
    right = NativeSpan("识别号：CN1", BBox(220, 55, 300, 65), "Helvetica", 10, 3)
    rows = [
        [TextStrip(title.text, title.bbox, [title])],
        [TextStrip(full.text, full.bbox, [full])],
        [TextStrip(left.text, left.bbox, [left]), TextStrip(right.text, right.bbox, [right])],
    ]

    run = _single_field_record_runs(rows)[0]
    expanded = _prepend_short_title(run, rows)
    table, evidence = _build_table(
        expanded,
        tracks_override=sorted(_anchor(strip) for strip in expanded[-1]),
    )

    assert table is not None
    assert table.rows == 3
    assert table.cols == 2
    assert evidence["column_tracks"] == [20, 220]
    assert any(cell.text.startswith("主管机关") and cell.colspan == 2 for cell in table.cells)


def test_table_build_splits_wide_field_span_but_only_merges_centered_header():
    wide = NativeSpan("机构：甲          文号：乙", BBox(20, 20, 300, 30), "Helvetica", 10, 0)
    left = NativeSpan("金额：500", BBox(20, 38, 80, 48), "Helvetica", 10, 1)
    right = NativeSpan("结果：无", BBox(200, 38, 260, 48), "Helvetica", 10, 2)
    rows = [
        [TextStrip(wide.text, wide.bbox, [wide])],
        [TextStrip(left.text, left.bbox, [left]), TextStrip(right.text, right.bbox, [right])],
    ]

    table, _ = _build_table(rows, tracks_override=[20, 200])

    assert table is not None
    first_row = [cell for cell in table.cells if cell.row_index == 0]
    assert [(cell.col_index, cell.text, cell.colspan) for cell in first_row] == [
        (0, "机构：甲", 1),
        (1, "文号：乙", 1),
    ]

    title = NativeSpan("查询明细", BBox(110, 60, 190, 70), "Helvetica", 10, 3)
    cells = [NativeSpan(str(index), BBox(20 + 90 * index, 78, 35 + 90 * index, 88), "Helvetica", 10, 4 + index) for index in range(4)]
    header_table, _ = _build_table(
        [[TextStrip(title.text, title.bbox, [title])], [TextStrip(cell.text, cell.bbox, [cell]) for cell in cells]],
        tracks_override=[20, 110, 200, 290],
    )

    assert header_table is not None
    assert [(cell.col_index, cell.colspan) for cell in header_table.cells if cell.row_index == 0] == [(0, 4)]


def test_native_span_recovery_keeps_span_metadata_and_currency_column(tmp_path):
    pdf_path = tmp_path / "native-borderless.pdf"
    _make_native_borderless_table(pdf_path)

    with fitz.open(pdf_path) as document:
        page = document[0]
        spans = collect_native_spans(page)
        recovery = recover_wireless_tables(page)

    assert spans == sorted(spans, key=lambda span: span.order)
    assert all(span.font and span.size and span.bbox.x1 > span.bbox.x0 for span in spans)
    assert len(recovery.tables) == 1
    table = recovery.tables[0]
    assert table.source == "wireless_span_recovery"
    assert table.rows >= 3
    assert table.cols >= 4
    row_one = [cell.text for cell in table.cells if cell.row_index == 1]
    assert "$" in row_one
    assert "1,200" in row_one
    assert recovery.diagnostics["native_spans"][0]["order"] == 0
    assert recovery.diagnostics["regions"][0]["column_tracks"]


def test_table_extractor_uses_wireless_recovery_before_legacy_word_alignment(tmp_path):
    pdf_path = tmp_path / "native-borderless.pdf"
    _make_native_borderless_table(pdf_path)

    with fitz.open(pdf_path) as document:
        tables = TableExtractor()._extract_via_text_alignment(document[0])

    assert len(tables) == 1
    assert tables[0].source == "wireless_span_recovery"


def test_wireless_recovery_excludes_text_inside_wired_regions(tmp_path):
    pdf_path = tmp_path / "native-borderless.pdf"
    _make_native_borderless_table(pdf_path)

    with fitz.open(pdf_path) as document:
        tables = TableExtractor()._extract_via_text_alignment(
            document[0],
            excluded_regions=[BBox(0, 0, 420, 180)],
        )

    assert tables == []


def test_export_wireless_debug_writes_html_json_and_overlay(tmp_path):
    pdf_path = tmp_path / "native-borderless.pdf"
    _make_native_borderless_table(pdf_path)

    with fitz.open(pdf_path) as document:
        recovery = recover_wireless_tables(document[0])
        paths = export_wireless_debug(document[0], recovery, str(tmp_path / "debug"), dpi=100)

    assert Path(paths["json"]).exists()
    assert Path(paths["html"]).exists()
    assert Path(paths["image"]).exists()
    assert "Alpha" in Path(paths["html"]).read_text(encoding="utf-8")
