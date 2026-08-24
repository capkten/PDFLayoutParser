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


def _query_rows(page: fitz.Page) -> list[list[tuple[float, float, float, float, str]]]:
    """Group native page words into visual rows for query-record recovery."""
    rows: list[list[tuple[float, float, float, float, str]]] = []
    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[:5]
        if not text.strip():
            continue
        center_y = (y0 + y1) / 2.0
        row = next(
            (candidate for candidate in rows if abs((candidate[0][1] + candidate[0][3]) / 2.0 - center_y) <= 2.0),
            None,
        )
        item = (x0, y0, x1, y1, text)
        if row is None:
            rows.append([item])
        else:
            row.append(item)
    return [sorted(row, key=lambda item: item[0]) for row in sorted(rows, key=lambda row: row[0][1])]


def _is_query_record_row(row: list[tuple[float, float, float, float, str]]) -> bool:
    """Return True for a row with the four query-record column anchors."""
    texts = [item[4] for item in row]
    has_number = any(item[0] < 110 and re.fullmatch(r"\d+", item[4]) for item in row)
    has_date = any(item[0] >= 120 and item[0] < 240 and "年" in text for item, text in zip(row, texts))
    has_reason = any(item[0] >= 350 for item in row)
    return has_number and has_date and has_reason


def _make_query_table(
    page: fitz.Page,
    *,
    header_index: int | None = None,
    end_index: int | None = None,
) -> Table | None:
    """Recover one four-column institution-query table directly from page words."""
    rows = _query_rows(page)
    if header_index is None:
        for index, row in enumerate(rows):
            row_text = "".join(item[4] for item in row)
            if all(header in row_text for header in _QUERY_HEADERS):
                header_index = index
                break

    if header_index is None:
        record_indices = [index for index, row in enumerate(rows) if _is_query_record_row(row)]
        if len(record_indices) < 2:
            return None
        start_index = record_indices[0]
        end_index = record_indices[-1] + 1
        header_cells: list[Cell] = []
    else:
        start_index = header_index + 1
        end_index = len(rows) if end_index is None else end_index
        header_cells = [
            Cell(
                text=header,
                row_index=0,
                col_index=index,
                bbox=BBox(
                    item[0], item[1], item[2], item[3]
                ),
            )
            for index, header in enumerate(_QUERY_HEADERS)
            for item in rows[header_index]
            if header == item[4]
        ]

    boundaries = [120.0, 243.0, 410.0]
    recovered_rows: list[list[tuple[float, float, float, float, str]]] = []
    for row in rows[start_index:end_index]:
        row_text = "".join(item[4] for item in row)
        if "页" in row_text and "第" in row_text:
            break
        if _is_query_record_row(row):
            recovered_rows.append(row)
            continue
        if recovered_rows and any(243.0 <= (item[0] + item[2]) / 2.0 < 410.0 for item in row):
            recovered_rows.append(row)

    if not recovered_rows or not any(_is_query_record_row(row) for row in recovered_rows):
        return None

    cells = list(header_cells)
    row_number = 1 if header_index is not None else 0
    for row in recovered_rows:
        by_col: dict[int, list[tuple[float, float, float, float, str]]] = {index: [] for index in range(4)}
        for item in row:
            center_x = (item[0] + item[2]) / 2.0
            col_index = 0 if center_x < boundaries[0] else 1 if center_x < boundaries[1] else 2 if center_x < boundaries[2] else 3
            by_col[col_index].append(item)

        if not by_col[0]:
            if row_number <= 1:
                continue
            continuation = "".join(item[4] for item in by_col[2])
            if continuation:
                previous = next(cell for cell in cells if cell.row_index == row_number - 1 and cell.col_index == 2)
                previous.text += continuation
                previous.bbox = BBox(previous.bbox.x0, previous.bbox.y0, max(previous.bbox.x1, max(item[2] for item in by_col[2])), max(previous.bbox.y1, max(item[3] for item in by_col[2])))
            continue

        row_y0 = min(item[1] for item in row)
        row_y1 = max(item[3] for item in row)
        for col_index in range(4):
            parts = by_col[col_index]
            if parts:
                bbox = BBox(
                    min(item[0] for item in parts),
                    min(item[1] for item in parts),
                    max(item[2] for item in parts),
                    max(item[3] for item in parts),
                )
                text = "".join(item[4] for item in parts)
            else:
                x0 = 0.0 if col_index == 0 else boundaries[col_index - 1]
                x1 = boundaries[col_index] if col_index < 3 else page.rect.width
                bbox = BBox(x0, row_y0, x1, row_y1)
                text = ""
            cells.append(Cell(text, row_number, col_index, bbox))
        row_number += 1

    if row_number <= (1 if header_index is not None else 0):
        return None
    all_cells = [cell for cell in cells if cell.text or cell.row_index == 0]
    return Table(
        bbox=BBox(
            min(cell.bbox.x0 for cell in all_cells),
            min(cell.bbox.y0 for cell in all_cells),
            max(cell.bbox.x1 for cell in all_cells),
            max(cell.bbox.y1 for cell in all_cells),
        ),
        rows=row_number,
        cols=4,
        cells=all_cells,
        confidence=0.95,
        source="personal_query_recovery",
    )


def _make_query_tables(page: fitz.Page) -> list[Table]:
    """Recover separate institution and personal query tables on one page."""
    rows = _query_rows(page)
    header_indices = []
    section_indices = []
    for index, row in enumerate(rows):
        row_text = "".join(item[4] for item in row)
        if all(header in row_text for header in _QUERY_HEADERS):
            header_indices.append(index)
        if _INSTITUTION_TITLE in row_text or _PERSONAL_TITLE in row_text:
            section_indices.append(index)

    if not header_indices:
        table = _make_query_table(page)
        return [table] if table is not None else []

    tables = []
    for header_index in header_indices:
        next_boundaries = [
            index
            for index in [*header_indices, *section_indices, len(rows)]
            if index > header_index
        ]
        table = _make_query_table(
            page,
            header_index=header_index,
            end_index=min(next_boundaries),
        )
        if table is not None:
            tables.append(table)
    return tables


def _table_overlaps(left: Table, right: Table) -> bool:
    return not (
        left.bbox.x1 < right.bbox.x0
        or right.bbox.x1 < left.bbox.x0
        or left.bbox.y1 < right.bbox.y0
        or right.bbox.y1 < left.bbox.y0
    )


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
        query_tables = _make_query_tables(page)
        if query_tables:
            tables = [
                table
                for table in tables
                if not any(_table_overlaps(table, query) for query in query_tables)
            ]
            tables.extend(query_tables)
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
