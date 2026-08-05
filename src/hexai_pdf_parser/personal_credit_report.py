"""Function-based pipeline entry point for personal credit reports."""

from __future__ import annotations

import re
from typing import List, Optional

import fitz

from hexai_pdf_parser.models import BBox, Cell, Document, Table
from hexai_pdf_parser.markdown_writer import MarkdownWriter
from hexai_pdf_parser.pipeline import Pipeline
from hexai_pdf_parser.table_extractor import TableExtractor


_QUERY_SECTION = "查询记录"
_INSTITUTION_TITLE = "机构查询记录明细"
_PERSONAL_TITLE = "本人查询记录明细"
_QUERY_HEADERS = ("编号", "查询日期", "查询机构", "查询原因")


def _find_text_line_bboxes(page: fitz.Page, texts: List[str]) -> dict[str, BBox]:
    """Find exact text anchors by grouping native words into visual lines."""
    lines: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}
    for word in page.get_text("words"):
        x0, y0, x1, y1, text, block_no, line_no = word[:7]
        lines.setdefault((block_no, line_no), []).append((x0, y0, x1, y1, text))

    found: dict[str, BBox] = {}
    for words in lines.values():
        words.sort(key=lambda item: item[0])
        line_text = "".join(item[4] for item in words).replace(" ", "")
        for text in texts:
            if text == _QUERY_SECTION:
                matches = (
                    text in line_text
                    and _INSTITUTION_TITLE not in line_text
                    and _PERSONAL_TITLE not in line_text
                )
            else:
                matches = text in line_text
            if not matches:
                continue
            found[text] = BBox(
                min(item[0] for item in words),
                min(item[1] for item in words),
                max(item[2] for item in words),
                max(item[3] for item in words),
            )
    return found


def _query_regions(page: fitz.Page) -> Optional[List[BBox]]:
    """Build query-detail regions from section titles and spatial boundaries."""
    anchors = _find_text_line_bboxes(
        page,
        [_QUERY_SECTION, _INSTITUTION_TITLE, _PERSONAL_TITLE],
    )
    if _QUERY_SECTION not in anchors:
        return []
    institution = anchors.get(_INSTITUTION_TITLE)
    personal = anchors.get(_PERSONAL_TITLE)
    if institution is None or personal is None or personal.y0 <= institution.y0:
        return []

    margin_x = max(24.0, page.rect.width * 0.06)
    bottom = page.rect.y1 - max(24.0, page.rect.height * 0.06)
    return [
        BBox(margin_x, institution.y0, page.rect.x1 - margin_x, personal.y0),
        BBox(margin_x, personal.y0, page.rect.x1 - margin_x, bottom),
    ]


def _trim_query_table(table: Table) -> Table:
    """Drop section-title rows before the four-column query header."""
    header_row = None
    for row_index in range(table.rows):
        row_text = {
            cell.text.strip()
            for cell in table.cells
            if cell.row_index == row_index
        }
        if all(header in row_text for header in _QUERY_HEADERS):
            header_row = row_index
            break
    if header_row is None or header_row == 0:
        return table

    cells = []
    for cell in table.cells:
        if cell.row_index < header_row:
            continue
        cell.row_index -= header_row
        cells.append(cell)
    table.cells = cells
    table.rows -= header_row
    if cells:
        table.bbox = BBox(
            min(cell.bbox.x0 for cell in cells),
            min(cell.bbox.y0 for cell in cells),
            max(cell.bbox.x1 for cell in cells),
            max(cell.bbox.y1 for cell in cells),
        )
    return table


def _bbox_values(bbox: BBox) -> list[float]:
    """Convert an internal bbox to the public four-number representation."""
    return [float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)]


def _document_result(document: Document) -> dict:
    """Return the compact public result for the personal-report API."""
    writer = MarkdownWriter()
    pages = []
    for page in sorted(document.pages, key=lambda item: item.index):
        blocks = []
        ordered_elements = sorted(
            page.layout_elements,
            key=lambda element: (
                element.bbox.y0,
                element.bbox.x0,
                element.bbox.y1,
                element.bbox.x1,
            ),
        )
        for element in ordered_elements:
            if element.type == "text":
                content = str(element.content or "").strip()
                if not content:
                    continue
            elif element.type == "table":
                content = "\n".join(writer._render_table(element.content)).strip()
                if not content:
                    continue
            else:
                continue

            blocks.append(
                {
                    "type": element.type,
                    "content": content,
                    "bbox": _bbox_values(element.bbox),
                }
            )

        pages.append(
            {
                "page": page.index + 1,
                "width": float(page.size["width"]),
                "height": float(page.size["height"]),
                "blocks": blocks,
            }
        )

    return {
        "document": {
            "file_name": document.file_name,
            "page_count": document.page_count,
        },
        "pages": pages,
    }


class PersonalCreditReportTableExtractor(TableExtractor):
    """Table extractor reserved for personal-credit-report region rules."""

    def _get_text_alignment_regions(
        self, page: fitz.Page
    ) -> Optional[list[BBox]]:
        """Recover native-span tables across the complete report page."""
        return None

    def _use_legacy_text_alignment_fallback(self) -> bool:
        """Avoid treating numbered explanatory paragraphs as tables."""
        return False

    @staticmethod
    def _is_numbered_prose_candidate(table: Table) -> bool:
        """Reject sparse long numbered paragraphs emitted as two-column tables."""
        cells = [cell.text.strip() for cell in table.cells if cell.text.strip()]
        return (
            table.cols <= 2
            and sum(len(text) >= 50 for text in cells) >= 2
            and sum(bool(re.match(r"^\d+[.、]", text)) for text in cells) >= 2
        )

    @staticmethod
    def _is_report_metadata_candidate(table: Table) -> bool:
        """Exclude the report identity block from structured table output."""
        text = "\n".join(cell.text for cell in table.cells)
        markers = (
            "\u62a5\u544a\u7f16\u53f7",
            "\u62a5\u544a\u65f6\u95f4",
            "\u8bc1\u4ef6\u53f7\u7801",
            "\u5176\u4ed6\u8bc1\u4ef6\u4fe1\u606f",
        )
        return sum(marker in text for marker in markers) >= 2

    @staticmethod
    def _split_repeated_record_table(table: Table) -> list[Table]:
        """Split repeated personal-report records sharing one layout."""
        record_starts = (
            "\u5904\u7f5a\u673a\u6784",
            "\u7acb\u6848\u6cd5\u9662",
            "\u6267\u884c\u6cd5\u9662",
        )
        starts = sorted(
            {
                cell.row_index
                for cell in table.cells
                if cell.col_index == 0
                and cell.text.strip().startswith(record_starts)
            }
        )
        if len(starts) < 2:
            return [table]

        ranges = list(zip([0, *starts[1:]], [*starts[1:], table.rows]))
        result = []
        for start, end in ranges:
            cells = [
                Cell(
                    text=cell.text,
                    row_index=cell.row_index - start,
                    col_index=cell.col_index,
                    bbox=cell.bbox,
                    rowspan=cell.rowspan,
                    colspan=cell.colspan,
                )
                for cell in table.cells
                if start <= cell.row_index < end
            ]
            result.append(
                Table(
                    bbox=BBox(
                        min(cell.bbox.x0 for cell in cells),
                        min(cell.bbox.y0 for cell in cells),
                        max(cell.bbox.x1 for cell in cells),
                        max(cell.bbox.y1 for cell in cells),
                    ),
                    rows=end - start,
                    cols=table.cols,
                    cells=cells,
                    confidence=table.confidence,
                    source=table.source,
                )
            )
        return result

    def _extract_via_text_alignment(
        self,
        page: fitz.Page,
        excluded_regions: Optional[List[BBox]] = None,
    ) -> List[Table]:
        tables = super()._extract_via_text_alignment(
            page,
            excluded_regions=excluded_regions,
        )
        filtered = [
            _trim_query_table(table)
            for table in tables
            if not self._is_numbered_prose_candidate(table)
            and not self._is_report_metadata_candidate(table)
        ]
        return [
            split
            for table in filtered
            for split in self._split_repeated_record_table(table)
        ]


class PersonalCreditReportPipeline(Pipeline):
    """Main pipeline with a personal-credit-report table extractor."""

    def _get_table_extractor_class(self):
        return PersonalCreditReportTableExtractor


def parse_personal_credit_report(
    pdf_path: str,
    output_dir: str | None = None,
    render_dpi: int = 200,
    page_indices: list[int] | None = None,
    debug: bool = False,
    debug_pipeline: bool = False,
) -> dict:
    """Parse a personal credit report into the compact public result format."""
    document = PersonalCreditReportPipeline(
        pdf_path=pdf_path,
        output_dir=output_dir,
        render_dpi=render_dpi,
        page_indices=page_indices,
        debug=debug,
        debug_pipeline=debug_pipeline,
    ).run()
    return _document_result(document)
