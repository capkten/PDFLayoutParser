"""Table extractor module.

Detects tables on a PDF page using PyMuPDF's ``find_tables()``.
"""

from typing import List

import fitz

from pdflayoutparser.models import BBox, Cell, Table


class TableExtractor:
    """Extract tables from a single PDF page.

    Example::

        extractor = TableExtractor()
        tables = extractor.extract(page)
    """

    def extract(self, page: fitz.Page) -> List[Table]:
        """Return a list of :class:`Table` objects detected on *page*."""
        try:
            tables_result = page.find_tables()
        except AttributeError:
            return []

        tables: List[Table] = []
        for table in tables_result.tables:
            bbox = BBox(*table.bbox)
            rows_data = table.extract()
            row_count = len(rows_data)
            col_count = len(rows_data[0]) if row_count > 0 else 0

            cells: List[Cell] = []
            cell_bboxes = table.cells if hasattr(table, "cells") else []
            cell_idx = 0
            for r_idx, row in enumerate(rows_data):
                for c_idx, text in enumerate(row):
                    if cell_idx < len(cell_bboxes):
                        cb = BBox(*cell_bboxes[cell_idx])
                    else:
                        cb = BBox(0.0, 0.0, 0.0, 0.0)
                    cells.append(
                        Cell(
                            text=text or "",
                            row_index=r_idx,
                            col_index=c_idx,
                            bbox=cb,
                        )
                    )
                    cell_idx += 1

            tables.append(
                Table(
                    bbox=bbox,
                    rows=row_count,
                    cols=col_count,
                    cells=cells,
                    confidence=1.0,
                    source="PyMuPDF.find_tables",
                )
            )

        return tables
