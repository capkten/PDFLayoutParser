import glob
import os
import re
import fitz
import pytest

from hexai_pdf_parser.extractors.personal_credit_report import (
    parse_personal_credit_report,
    PersonalCreditReportTableExtractor,
)


def _find_base_dir() -> str:
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "个人信用报告"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "个人信用报告"),
        r"D:\codes\PDFLayoutParser\个人信用报告",
    ]
    for c in candidates:
        if os.path.isdir(c):
            return os.path.abspath(c)
    return os.path.abspath(candidates[-1])


BASE_DIR = _find_base_dir()
ALL_PDFS = sorted(glob.glob(os.path.join(BASE_DIR, "**", "*.pdf"), recursive=True))
PDF_IDS = [os.path.relpath(p, BASE_DIR).replace("\\", "/") for p in ALL_PDFS]


def test_all_12_pdfs_found():
    """Verify that all 12 sample PDFs in 个人信用报告 are discovered."""
    assert len(ALL_PDFS) == 12, f"Expected 12 PDFs, found {len(ALL_PDFS)}: {PDF_IDS}"


@pytest.mark.parametrize("pdf_path", ALL_PDFS, ids=PDF_IDS)
def test_personal_credit_report_pipeline_runs_without_error(pdf_path):
    """Verify that parse_personal_credit_report executes cleanly on every sample PDF."""
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    doc.close()

    result = parse_personal_credit_report(pdf_path, use_ml_table_detector=False)
    assert "pages" in result
    assert len(result["pages"]) == page_count

    for page_idx, page in enumerate(result["pages"]):
        assert page["width"] > 0
        assert page["height"] > 0
        blocks = page["blocks"]

        for bidx, b in enumerate(blocks):
            assert b["type"] in ("text", "table")
            assert len(b["content"].strip()) > 0
            bbox = b["bbox"]
            assert len(bbox) == 4
            assert bbox[0] <= bbox[2], f"Invalid bbox width: {bbox} on p{page_idx+1} b{bidx}"
            assert bbox[1] <= bbox[3], f"Invalid bbox height: {bbox} on p{page_idx+1} b{bidx}"


@pytest.mark.parametrize("pdf_path", ALL_PDFS, ids=PDF_IDS)
def test_no_consecutive_number_blocks(pdf_path):
    """Verify that reading order does not produce adjacent consecutive number blocks."""
    result = parse_personal_credit_report(pdf_path, use_ml_table_detector=False)
    for page_idx, page in enumerate(result["pages"]):
        prev_num = None
        for bidx, b in enumerate(page["blocks"]):
            txt = b["content"].strip()
            is_num = bool(re.match(r"^\d+\.?$", txt))
            assert not (is_num and prev_num), (
                f"Consecutive numbers '{prev_num}' and '{txt}' at p{page_idx+1} block {bidx} in {pdf_path}"
            )
            prev_num = txt if is_num else None


@pytest.mark.parametrize("pdf_path", ALL_PDFS, ids=PDF_IDS)
def test_no_prose_detected_as_table(pdf_path):
    """Verify that prose sections (e.g. credit card paragraph details) are not extracted as tables."""
    doc = fitz.open(pdf_path)
    extractor = PersonalCreditReportTableExtractor(use_ml_table_detector=False)
    for page_idx, page in enumerate(doc):
        tables = extractor.extract(page)
        for t in tables:
            has_prose = any("从未逾期过的贷记卡" in c.text for c in t.cells)
            assert not has_prose, (
                f"Found prose table on page {page_idx+1} in {pdf_path}: {t.rows}x{t.cols}"
            )
    doc.close()
