import os
import fitz
from hexai_pdf_parser.core.models import BBox
from hexai_pdf_parser.tables.table_extractor import TableExtractor

def test_rule_branch_reuses_wireless_structure_recovery_on_personal_report():
    """Verify that use_ml_table_detector=False uses the same wireless structure recovery
    as the model branch, restoring the personal query table to 4 distinct columns.
    """
    pdf_path = os.path.join(
        "D:\\codes\\PDFLayoutParser",
        "个人信用报告",
        "个人征信报告（简版）(1).pdf",
    )
    assert os.path.exists(pdf_path), f"PDF file not found: {pdf_path}"

    doc = fitz.open(pdf_path)
    page = doc[3]  # 第4页（包含机构查询记录明细与本人查询记录明细）

    extractor = TableExtractor(use_ml_table_detector=False)
    tables = extractor.extract(page)

    # 找到包含 "本人查询记录明细" 的表格
    personal_query_tables = [
        t for t in tables
        if any("本人查询记录明细" in cell.text for cell in t.cells)
    ]
    assert len(personal_query_tables) == 1, f"Expected 1 personal query table, got {len(personal_query_tables)}"
    table = personal_query_tables[0]

    # 验证结构恢复结果：必须是 4 列，source 必须为 wireless_span_recovery
    assert table.cols == 4, f"Expected 4 columns, got {table.cols}"
    assert table.source == "wireless_span_recovery", f"Expected wireless_span_recovery, got {table.source}"

    # 验证表头中的 "查询机构" 与 "查询原因" 为独立列单元格，绝不能合并
    header_texts = [cell.text for cell in table.cells if cell.row_index == 1]
    assert "查询机构" in header_texts, f"'查询机构' missing in headers: {header_texts}"
    assert "查询原因" in header_texts, f"'查询原因' missing in headers: {header_texts}"
    assert not any("查询机构查询原因" in text for text in header_texts), "Headers improperly merged"

    # 验证数据行中的第 3 列与第 4 列
    row2_cells = {cell.col_index: cell.text for cell in table.cells if cell.row_index == 2}
    assert 2 in row2_cells and 3 in row2_cells
    assert "本人" in row2_cells[2]
    assert "互联网个人信用信息服务平台" in row2_cells[3]


def test_rule_branch_calls_wireless_extractor_extract_for_candidate_regions(monkeypatch):
    """Verify that _extract_rule_tables delegates candidate regions to _wireless_extractor.extract."""
    from types import SimpleNamespace
    from hexai_pdf_parser.core.models import Cell, Table

    extractor = TableExtractor(use_ml_table_detector=False)
    page = SimpleNamespace(
        rect=fitz.Rect(0, 0, 500, 500),
        get_text=lambda *args, **kwargs: [],
        get_drawings=lambda *args, **kwargs: [],
    )

    box1 = BBox(10, 10, 100, 100)
    box2 = BBox(10, 150, 100, 250)
    candidate1 = Table(bbox=box1, rows=2, cols=2, cells=[], confidence=0.88, source="wireless_span_recovery")
    candidate2 = Table(bbox=box2, rows=2, cols=2, cells=[], confidence=0.75, source="wireless_text_strip")

    calls = []
    def fake_extract(p, table_bbox=None, confidence=None, page_language=None):
        calls.append((table_bbox, confidence, page_language))
        return [Table(bbox=table_bbox, rows=2, cols=2, cells=[Cell("recovered", 0, 0, table_bbox)], source="wireless_span_recovery")]

    monkeypatch.setattr(extractor._wireless_extractor, "extract", fake_extract)

    results = extractor._extract_rule_tables(page, candidates=[candidate1, candidate2], page_language="zh")
    assert len(results) == 2
    assert len(calls) == 2
    assert calls[0] == (box1, 0.88, "zh")
    assert calls[1] == (box2, 0.75, "zh")


def test_rule_branch_preserves_unmatched_wired_tables(monkeypatch):
    """Verify that pure wired tables not overlapping any candidate regions are preserved."""
    from types import SimpleNamespace
    from hexai_pdf_parser.core.models import Cell, Table

    extractor = TableExtractor(use_ml_table_detector=False)
    page = SimpleNamespace(
        rect=fitz.Rect(0, 0, 500, 500),
        get_text=lambda *args, **kwargs: [],
        get_drawings=lambda *args, **kwargs: [],
    )

    wired_box = BBox(0, 0, 200, 200)
    wired_table = Table(bbox=wired_box, rows=2, cols=2, cells=[Cell("wired", 0, 0, wired_box)], source="line_projection")

    # No wireless candidate
    results = extractor._extract_rule_tables(page, candidates=[wired_table], page_language="en")
    assert len(results) == 1
    assert results[0].source == "line_projection"

