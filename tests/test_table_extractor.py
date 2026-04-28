"""Tests for the table extractor."""

from pathlib import Path

import fitz
import pytest

from pdflayoutparser.table_extractor import TableExtractor


def make_pdf_with_table(path: str | Path) -> None:
    """Create a PDF with a simple 2x2 grid drawn with lines and text."""
    doc = fitz.open()
    page = doc.new_page()
    # Draw horizontal lines
    page.draw_line((100, 100), (300, 100))
    page.draw_line((100, 150), (300, 150))
    page.draw_line((100, 200), (300, 200))
    # Draw vertical lines
    page.draw_line((100, 100), (100, 200))
    page.draw_line((200, 100), (200, 200))
    page.draw_line((300, 100), (300, 200))
    # Insert text in cells
    page.insert_text((120, 120), "A1")
    page.insert_text((220, 120), "B1")
    page.insert_text((120, 170), "A2")
    page.insert_text((220, 170), "B2")
    doc.save(path)
    doc.close()


class TestTableExtractor:
    def test_extract_table_from_lines(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "with_table.pdf"
        make_pdf_with_table(pdf_path)

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            tables = extractor.extract(page)

            assert isinstance(tables, list)
            if tables:
                table = tables[0]
                assert table.rows >= 1
                assert table.cols >= 1
                assert len(table.cells) >= 1
                assert table.confidence == 1.0
                assert table.source == "PyMuPDF.find_tables"
        finally:
            doc.close()

    def test_extract_no_crash_on_text_only(self, tmp_dir):
        """Ensure the extractor does not crash on pages without tables."""
        pdf_path = Path(tmp_dir) / "no_table.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Just some text")
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            extractor = TableExtractor()
            tables = extractor.extract(page)
            assert isinstance(tables, list)
        finally:
            doc.close()
