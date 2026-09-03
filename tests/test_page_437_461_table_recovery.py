# -*- coding: utf-8 -*-
import pytest
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.wireless_structure.text_runs import build_text_runs
from hexai_pdf_parser.tables.wireless_structure.header_topology import (
    _split_by_lowest_header_children,
    _coalesce_right_aligned_sibling_leaves,
    _infer_complete_physical_leaf_span,
    refine_leaf_bands,
)


def _span(
    text,
    x0,
    x1,
    order,
    source_position=(1, 1, 0),
    *,
    font="SimSun",
    font_size=12,
    y=10,
    bold=False,
):
    return {
        "text": text,
        "bbox": [x0, y, x1, y + 12],
        "order": order,
        "flow": order + 1,
        "source_position": list(source_position),
        "font": font,
        "font_size": font_size,
        "bold": bold,
        "span_ref": f"S{order}",
        "char_boxes": [],
    }


def test_build_text_runs_merges_cjk_embedded_numbers_with_following_cjk():
    """正例：'未来'(中文) + '12'(数字) + '个月'(中文) 在同一 native_line 内应完整合并为 '未来12个月'。"""
    spans = [
        _span("未来", 294.8, 318.9, 0, (6, 0, 0), font="SimSun", y=153.8, bold=False),
        _span("12", 322.0, 332.9, 1, (6, 0, 1), font="Arial Narrow", y=152.8, bold=True),
        _span("个月", 332.9, 360.0, 2, (6, 0, 2), font="SimSun", y=153.8, bold=False),
    ]

    result = build_text_runs(spans)

    assert len(result) == 1
    assert result[0]["text"] == "未来12个月"


def test_build_text_runs_keeps_chinese_label_and_standalone_numeric_column_separate():
    """反例：'应收账款'(中文) 与右侧无后置中文的独立金额列 '100,000.00'(数字) 必须保持分离。"""
    spans = [
        _span("应收账款", 100.0, 160.0, 0, (1, 0, 0), font="SimSun", y=10.0),
        _span("100,000.00", 200.0, 280.0, 1, (1, 0, 1), font="Arial", y=10.0),
    ]

    result = build_text_runs(spans)

    assert [r["text"] for r in result] == ["应收账款", "100,000.00"]


def test_build_text_runs_merges_multiline_cjk_with_embedded_bold_western_number():
    """正例：'未来 12 个月'(含粗体西文数字) 与下一行 '内的预期信\\n用损失率(%)' 应跨行合并为同一 Atom。"""
    spans = [
        _span("未来", 294.8, 318.9, 0, (6, 0, 0), font="SimSun", y=153.8, bold=False),
        _span("12", 322.0, 332.9, 1, (6, 0, 1), font="Arial Narrow", y=152.8, bold=True),
        _span("个月", 332.9, 360.0, 2, (6, 0, 2), font="SimSun", y=153.8, bold=False),
        _span("内的预期信", 299.7, 359.9, 3, (7, 0, 0), font="SimSun", y=169.2, bold=False),
        _span("用损失率", 296.5, 344.7, 4, (7, 1, 0), font="SimSun", y=184.8, bold=False),
        _span("(%)", 344.8, 362.7, 5, (7, 1, 1), font="SimSun", y=183.9, bold=False),
        # 右侧见证者
        _span("坏账准备", 382.0, 430.2, 6, (8, 0, 0), font="SimSun", y=169.2, bold=False),
        _span("账面价值", 452.4, 500.6, 7, (8, 1, 0), font="SimSun", y=169.2, bold=False),
    ]

    result = build_text_runs(spans)

    assert result[0]["text"] == "未来12个月\n内的预期信\n用损失率(%)"
    assert result[0]["flow_start"] == 1
    assert result[0]["flow_end"] == 6


def test_coalesce_right_aligned_sibling_leaves_keeps_leaves_with_dash_placeholders():
    """正例：'直接'列含数字 100.00，'间接'列全为占位符 '--'，不能将间接列误判为伪列合并。"""
    bands = [
        {
            "id": 5,
            "x0": 418.3,
            "x1": 453.5,
            "kind": "header_leaf",
            "parent_x0": 418.3,
            "parent_x1": 485.9,
            "parent_leaf_count": 2,
        },
        {
            "id": 6,
            "x0": 453.5,
            "x1": 485.9,
            "kind": "header_leaf",
            "parent_x0": 418.3,
            "parent_x1": 485.9,
            "parent_leaf_count": 2,
        },
    ]
    atoms = [
        # 正文数字与破折号
        {"text": "100.00", "bbox": [418.3, 233.5, 447.0, 245.6]},
        {"text": "--", "bbox": [477.7, 233.5, 485.9, 245.6]},
        {"text": "100.00", "bbox": [418.3, 260.8, 447.0, 272.9]},
        {"text": "--", "bbox": [477.7, 260.8, 485.9, 272.9]},
    ]

    result = _coalesce_right_aligned_sibling_leaves(atoms, bands, cutoff=150.0)

    # 应该保持 2 个独立叶子列，不能被合并为 1 个
    assert len(result) == 2
    assert result[0]["x1"] <= 455.0
    assert result[1]["x0"] >= 450.0


def test_split_by_lowest_header_children_with_clustered_y_levels():
    """正例：当子表头 '直接' 与 '间接' 的 y 坐标与聚类均值有微小偏差（0.56pt）时，仍能正确拆分。"""
    band = {"id": 5, "x0": 386.5, "x1": 462.2, "support": 5, "y_support": 3}
    header = [
        {"text": "持股比例(%)", "bbox": [386.5, 502.1, 444.5, 514.2]},
        {"text": "对合营企业", "bbox": [480.5, 501.2, 533.3, 511.8]},
        {"text": "或联营企业", "bbox": [480.5, 514.9, 533.3, 525.5]},
        {"text": "投资的会计", "bbox": [480.5, 528.5, 533.3, 539.0]},
        {"text": "处理方法", "bbox": [491.0, 542.2, 533.3, 552.7]},
        {"text": "直接", "bbox": [387.8, 530.2, 408.9, 540.7]},
        {"text": "间接", "bbox": [438.7, 530.2, 459.8, 540.7]},
    ]

    children = _split_by_lowest_header_children(header, band)

    assert len(children) == 2
    assert children[0]["kind"] == "header_leaf"
    assert children[1]["kind"] == "header_leaf"


def test_infer_complete_physical_leaf_span_rejects_narrow_atom():
    """反例：物理宽度仅 66pt 的单列小标题，即使几何中心接近全表中心，也不能被误判为跨 5 列（414pt）大表头。"""
    bands = [
        {"id": 1, "x0": 89.3, "x1": 197.3},
        {"id": 2, "x0": 224.1, "x1": 284.3},
        {"id": 3, "x0": 294.8, "x1": 362.7},
        {"id": 4, "x0": 381.1, "x1": 433.0},
        {"id": 5, "x0": 443.1, "x1": 503.4},
    ]
    atom = {
        "text": "内的预期信用损失率(%)",
        "bbox": [296.5, 169.2, 362.7, 197.7],
    }
    atoms = [
        atom,
        {"text": "按单项计提坏账准备", "bbox": [89.3, 201.6, 197.3, 213.6]},
        {"text": "--", "bbox": [275.0, 200.5, 284.3, 214.2]},
        {"text": "--", "bbox": [353.4, 200.5, 362.7, 214.2]},
        {"text": "--", "bbox": [423.7, 200.5, 433.0, 214.2]},
        {"text": "--", "bbox": [494.0, 200.5, 503.4, 214.2]},
    ]

    span = _infer_complete_physical_leaf_span(atom, atoms, bands, header_cutoff=215.0)

    # 物理宽度过窄（66.2 / 414.1 = 16%），必须拒绝推断为 [1, 2, 3, 4, 5]
    assert span == []
