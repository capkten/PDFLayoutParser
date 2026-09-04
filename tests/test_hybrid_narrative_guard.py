import pytest
import fitz
from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.table_extractor import TableExtractor
from hexai_pdf_parser.tables.wireless_structure.hybrid_body import (
    _has_hybrid_structure_support,
    recover_hybrid_body_cells,
)


def test_hybrid_recovery_rejects_narrative_paragraph_body():
    """审计报告等关键审计事项大段落叙述性单元格不得进入混合多行切分。"""
    pdf_path = r"d:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf"
    doc = fitz.open(pdf_path)
    page = doc[200]

    # 有线提取器在第 200 页识别出的原始有线表格（3行2列，第2行高420.5pt）
    wired_cells = [
        Cell("", 0, 0, BBox(95.5, 72.2, 293.4, 152.8)),
        Cell("水平进行比较，识别坏账准备计提的充分性；7、复核管理层对应收账款相关披露的充分性。", 0, 1, BBox(293.4, 72.2, 505.4, 152.8)),
        Cell("（二）存货减值", 1, 0, BBox(95.5, 152.8, 505.4, 173.3), colspan=2),
        Cell("事项描述：\n截至2024年12月31日，合并财务报表存货余额为人民币21.04亿元...", 2, 0, BBox(95.5, 173.3, 293.4, 593.8)),
        Cell("审计应对：\n1、评估和测试与存货相关的内部控制的设计及运行有效性...", 2, 1, BBox(293.4, 173.3, 505.4, 593.8)),
    ]
    wired_table = Table(
        bbox=BBox(95.5, 72.2, 505.4, 593.8),
        rows=3,
        cols=2,
        cells=wired_cells,
        source="line_projection",
    )

    extractor = TableExtractor()
    result = extractor._recover_hybrid_wired_table(page, wired_table, "zh")

    # 必须保持原始有线表格，不转为 hybrid_line_span_recovery，行数保持 3
    assert result.source == "line_projection"
    assert result.rows == 3
    assert result.cols == 2


def test_has_hybrid_structure_support_rejects_sparse_narrative_columns():
    """如果某一列绝大部分行为空槽位且另一列为大段落伪对齐，拒绝结构支持。"""
    # 模拟 Page 200 恢复出的 6 行 2 列细胞：
    # 列 0 只有 Row 0 和 Row 3 有内容（其中 Row 3 是一个长文本大段落），Row 1, 2, 4, 5 全为空
    # 列 1 共有 6 行文本（均为叙事/措施文本，无任何独立金额数值）
    cells = [
        Cell("事项描述：", 0, 0, BBox(100, 177, 290, 191)),
        Cell("审计应对：", 0, 1, BBox(298, 177, 500, 191)),
        Cell("", 1, 0, BBox(100, 194, 290, 248)),
        Cell("1、评估和测试与存货相关的内部控制的设计及运行有效性；", 1, 1, BBox(298, 194, 500, 248)),
        Cell("", 2, 0, BBox(100, 248, 290, 284)),
        Cell("2、对大额存货进行实地盘点，观察存货状态...", 2, 1, BBox(298, 248, 500, 284)),
        Cell("截至2024年12月31日，合并财务报表存货余额为人民币21.04亿元...", 3, 0, BBox(100, 284, 290, 535)),
        Cell("3、评估管理层及其专家采用的可变现净值计算方法...", 3, 1, BBox(298, 284, 500, 535)),
        Cell("", 4, 0, BBox(100, 535, 290, 550)),
        Cell("4、重新计算管理层对可变现净值的测算过程...", 4, 1, BBox(298, 535, 500, 550)),
        Cell("", 5, 0, BBox(100, 550, 290, 593)),
        Cell("5、复核管理层对存货相关披露的充分性和完整性。", 5, 1, BBox(298, 550, 500, 593)),
    ]

    assert _has_hybrid_structure_support(cells, 6, 2) is False


def test_has_hybrid_structure_support_accepts_genuine_financial_grid():
    """真正的财务报表混合主体（有多行独立金额项支撑）应当通过结构支持校验。"""
    cells = [
        Cell("营业收入", 0, 0, BBox(100, 100, 250, 120)),
        Cell("100,000.00", 0, 1, BBox(250, 100, 350, 120)),
        Cell("营业成本", 1, 0, BBox(100, 120, 250, 140)),
        Cell("80,000.00", 1, 1, BBox(250, 120, 350, 140)),
        Cell("利润总额", 2, 0, BBox(100, 140, 250, 160)),
        Cell("20,000.00", 2, 1, BBox(250, 140, 350, 160)),
    ]

    assert _has_hybrid_structure_support(cells, 3, 2) is True
