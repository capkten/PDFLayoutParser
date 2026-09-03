# -*- coding: utf-8 -*-
from pathlib import Path
import pytest
import fitz

from hexai_pdf_parser.core.models import BBox, Cell
from hexai_pdf_parser.tables.wireless_structure.span_chain import (
    _split_packed_numeric_fields
)
from hexai_pdf_parser.tables.wireless_structure.text_runs import _can_join
from hexai_pdf_parser.tables.wireless_structure.columns import _compatible
from hexai_pdf_parser.tables.wireless_structure.recoverer import recover_cells_from_region


def test_can_join_rejects_standalone_placeholder_and_formatted_number():
    """独立占位符与右侧格式化正数金额严禁跨列合并。"""
    # 模拟 Page 944 小计行中 Col 4 的 '-' 与 Col 5 的 '235,243,168.96'
    previous = {
        "text": "-",
        "bbox": [286.25, 378.87, 289.13, 390.97],
        "font": "Arial Narrow",
        "font_size": 10.56,
        "source_position": [0, 0, 10],
        "flow": 10,
    }
    candidate = {
        "text": "235,243,168.96",
        "bbox": [289.13, 378.87, 358.50, 390.97],
        "font": "Arial Narrow,Bold",
        "font_size": 10.56,
        "source_position": [0, 0, 11],
        "flow": 11,
    }
    # 即使 gap == 0.0，且同 native line，也必须严禁合并
    assert not _can_join([previous], candidate, normal_gap=0.0)


def test_can_join_allows_inline_hyphen_with_text_prefix():
    """词内连字符（左侧有实质文本前缀）仍允许正常合并。"""
    prefix = {
        "text": "高质量发展专项资金",
        "bbox": [100.0, 200.0, 180.0, 212.0],
        "font": "SimSun",
        "font_size": 10.5,
        "source_position": [0, 0, 1],
        "flow": 1,
    }
    hyphen = {
        "text": "-",
        "bbox": [180.0, 200.0, 184.0, 212.0],
        "font": "SimSun",
        "font_size": 10.5,
        "source_position": [0, 0, 2],
        "flow": 2,
    }
    next_part = {
        "text": "高功率",
        "bbox": [184.0, 200.0, 220.0, 212.0],
        "font": "SimSun",
        "font_size": 10.5,
        "source_position": [0, 0, 3],
        "flow": 3,
    }
    assert _can_join([prefix], hyphen, normal_gap=0.0)
    assert _can_join([prefix, hyphen], next_part, normal_gap=0.0)


def test_split_packed_numeric_fields_separates_placeholder_and_number_span():
    """单个 Span 内封装的占位符与数值必须按内部字符间隙解离。"""
    char_boxes = [
        {"text": "-", "bbox": [286.25, 302.31, 289.13, 314.41]},
        {"text": " ", "bbox": [289.13, 302.31, 291.54, 314.41]},
        {"text": "1", "bbox": [296.21, 302.31, 301.03, 314.41]},
        {"text": "7", "bbox": [301.01, 302.31, 305.83, 314.41]},
        {"text": "7", "bbox": [305.81, 302.31, 310.63, 314.41]},
        {"text": ",", "bbox": [310.61, 302.31, 313.02, 314.41]},
        {"text": "0", "bbox": [313.00, 302.31, 317.82, 314.41]},
        {"text": "5", "bbox": [317.80, 302.31, 322.62, 314.41]},
        {"text": "8", "bbox": [322.60, 302.31, 327.42, 314.41]},
        {"text": ",", "bbox": [327.40, 302.31, 329.81, 314.41]},
        {"text": "8", "bbox": [329.79, 302.31, 334.61, 314.41]},
        {"text": "2", "bbox": [334.59, 302.31, 339.41, 314.41]},
        {"text": "3", "bbox": [339.39, 302.31, 344.21, 314.41]},
        {"text": ".", "bbox": [344.19, 302.31, 346.60, 314.41]},
        {"text": "5", "bbox": [346.59, 302.31, 351.40, 314.41]},
        {"text": "3", "bbox": [351.39, 302.31, 356.20, 314.41]},
        {"text": " ", "bbox": [356.09, 302.31, 358.50, 314.41]},
    ]
    span = {
        "text": "- 177,058,823.53",
        "bbox": [286.25, 302.31, 358.50, 314.41],
        "font": "Arial Narrow",
        "font_size": 10.56,
        "source_position": [0, 0, 5],
        "char_boxes": char_boxes,
    }
    fragments = _split_packed_numeric_fields(span)
    assert len(fragments) == 2
    assert fragments[0]["text"] == "-"
    assert fragments[1]["text"] == "177,058,823.53"
    assert fragments[0]["bbox"] == [286.25, 302.31, 289.13, 314.41]
    assert fragments[1]["bbox"] == [296.21, 302.31, 356.20, 314.41]


def test_compatible_rejects_placeholder_whitespace_overlap_with_number():
    """占位符仅末尾空白与相邻列数值轻微擦碰时，严禁判定为属于同一列。"""
    placeholder = {
        "text": "-",
        "bbox": [286.25, 193.3, 291.54, 205.4],
        "font_size": 10.56,
    }
    number = {
        "text": "235,243,168.96",
        "bbox": [289.13, 378.87, 358.50, 390.97],
        "font_size": 10.56,
    }
    assert not _compatible(placeholder, number)
    assert not _compatible(number, placeholder)


def test_page_944_table_recovery_integration():
    """集成测试：Page 944 必须成功恢复出完整的 13 列无线大表。"""
    pdf_path = Path(__file__).resolve().parents[1] / "fix" / "zh_all_table_pages.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Page 944 integration fixture is local-only and was not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    page = doc[944]

    class NoWordsPage:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def get_text(self, kind, *args, **kwargs):
            if kind == "words":
                raise AssertionError("native-span recovery must not read page words")
            return self._wrapped.get_text(kind, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    bbox = BBox(76.0, 86.8, 746.5, 413.5)

    rows, cols, cells = recover_cells_from_region(NoWordsPage(page), bbox)
    assert rows >= 8
    assert cols == 13
    slot_counts = {}
    for cell in cells:
        assert 0 <= cell.row_index < rows
        assert 0 <= cell.col_index < cols
        assert cell.row_index + cell.rowspan <= rows
        assert cell.col_index + cell.colspan <= cols
        for row in range(cell.row_index, cell.row_index + cell.rowspan):
            for col in range(cell.col_index, cell.col_index + cell.colspan):
                slot_counts[(row, col)] = slot_counts.get((row, col), 0) + 1
    expected_slots = {(row, col) for row in range(rows) for col in range(cols)}
    assert set(slot_counts) == expected_slots
    assert set(slot_counts.values()) == {1}
    empty_cells = [cell for cell in cells if cell.text == ""]
    assert empty_cells
    assert all(cell.rowspan == 1 and cell.colspan == 1 for cell in empty_cells)

    cell_map = {(c.row_index, c.col_index): c for c in cells}
    assert cell_map[(0, 0)].text == "被投资单位"
    assert cell_map[(0, 0)].rowspan == 2
    assert cell_map[(0, 1)].text == "期初余额（账\n面价值）"
    assert cell_map[(0, 1)].rowspan == 2
    assert cell_map[(0, 2)].text == "减值\n准备\n期初\n余额"
    assert cell_map[(0, 2)].rowspan == 2

    change_header = cell_map[(0, 3)]
    assert change_header.text == "本期增减变动"
    assert change_header.colspan == 8

    assert cell_map[(1, 3)].text == "追\n加/\n新\n增\n投\n资"
    assert cell_map[(1, 4)].text == "减少投资"
    assert cell_map[(1, 5)].text == "权益法下\n确认的\n投资损益"
    assert cell_map[(1, 6)].text == "其他综\n合\n收益调\n整"
    assert cell_map[(1, 7)].text == "其他\n权益\n变动"
    assert cell_map[(1, 8)].text == "宣告发放现\n金股利或利\n润"
    assert cell_map[(1, 9)].text == "计提\n减值\n准备"
    assert cell_map[(1, 10)].text == "其\n他"

    assert cell_map[(0, 11)].text == "期末余额（账\n面价值）"
    assert cell_map[(0, 11)].rowspan == 2
    assert cell_map[(0, 12)].text == "减值准\n备期末\n余额"
    assert cell_map[(0, 12)].rowspan == 2
