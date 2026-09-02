"""Chinese and mixed-language native-span wireless table extraction."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.tables.wireless_table_recovery import recover_wireless_tables
from hexai_pdf_parser.tables.wireless_structure.recoverer import (
    recover_cells_from_region,
)


class ChineseTableExtractor:
    """Recover ``zh``/``mixed`` wireless tables from native PDF spans only."""

    def __init__(
        self,
        recover_cells: Optional[Callable[[object, BBox], Tuple[int, int, List[Cell]]]] = None,
    ) -> None:
        self._recover_cells = recover_cells or recover_cells_from_region

    def extract(
        self,
        page: object,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
        page_language: Optional[str] = None,
    ) -> List[Table]:
        """Extract one trusted Chinese or mixed-language region."""
        if page_language is None:
            page_language = "zh"
        if page_language not in {"zh", "mixed"} or table_bbox is None:
            return []

        row_count, col_count, cells = self._recover_cells(page, table_bbox)
        if row_count < 1 or col_count < 1 or not cells:
            return []

        conf_score = round(confidence, 4) if confidence is not None else 0.85
        return [
            Table(
                bbox=table_bbox,
                rows=row_count,
                cols=col_count,
                cells=cells,
                confidence=conf_score,
                source="wireless_span_recovery",
            )
        ]

    def extract_text_alignment_candidates(
        self,
        page: object,
        excluded_regions: Optional[List[BBox]] = None,
        allowed_regions: Optional[List[BBox]] = None,
        use_legacy_fallback: bool = False,
    ) -> List[Table]:
        """Return page-level native-span candidates without a words fallback."""
        del use_legacy_fallback
        if allowed_regions == []:
            self._last_wireless_recovery = {"regions": [], "disabled": True}
            return []
        try:
            recovery = recover_wireless_tables(
                page,
                excluded_regions=excluded_regions,
                allowed_regions=allowed_regions,
            )
        except (AttributeError, TypeError, ValueError):
            self._last_wireless_recovery = {"regions": []}
            return []

        self._last_wireless_recovery = recovery.diagnostics
        if not excluded_regions:
            return list(recovery.tables)

        return [
            table
            for table in recovery.tables
            if not any(
                min(table.bbox.x1, region.x1) > max(table.bbox.x0, region.x0)
                and min(table.bbox.y1, region.y1) > max(table.bbox.y0, region.y0)
                for region in excluded_regions
            )
        ]


__all__ = ["ChineseTableExtractor"]
