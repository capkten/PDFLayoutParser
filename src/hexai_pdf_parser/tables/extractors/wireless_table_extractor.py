"""Compatibility facade for language-specific wireless table extractors."""

from __future__ import annotations

import inspect
from typing import List, Optional

import fitz

from hexai_pdf_parser.core.models import BBox, Table
from hexai_pdf_parser.tables.extractors.chinese_table_extractor import (
    ChineseTableExtractor,
)
from hexai_pdf_parser.tables.extractors.english_table_extractor import (
    EnglishTableExtractor,
    _RowData,
)
from hexai_pdf_parser.tables.wireless_structure.recoverer import (
    recover_cells_from_region,
)


class WirelessTableExtractor(EnglishTableExtractor):
    """Route wireless extraction while preserving the historical API.

    English methods remain inherited from ``EnglishTableExtractor`` so calls
    and monkeypatches made against this compatibility class keep their old
    behavior. Chinese and mixed pages are handled by a separate native-span
    strategy.
    """

    _RowData = _RowData

    def __init__(
        self,
        line_tolerance: float = 2.0,
        color_tolerance: float = 0.05,
        row_merge_tolerance: float = 2.0,
    ) -> None:
        super().__init__(
            line_tolerance=line_tolerance,
            color_tolerance=color_tolerance,
            row_merge_tolerance=row_merge_tolerance,
            method_owner=self,
        )
        self._english_extractor = EnglishTableExtractor(
            line_tolerance=line_tolerance,
            color_tolerance=color_tolerance,
            row_merge_tolerance=row_merge_tolerance,
            method_owner=self,
        )

        def recover(page: object, region: BBox):
            # Resolve the module-level name at call time for old monkeypatches.
            return recover_cells_from_region(page, region)

        self._chinese_extractor = ChineseTableExtractor(recover_cells=recover)

    def extract(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
        page_language: Optional[str] = None,
    ) -> List[Table]:
        """Extract through the strategy matching ``page_language``."""
        if page_language is None:
            from hexai_pdf_parser.extractors.language_detector import (
                detect_page_language,
            )

            page_language = detect_page_language(page)

        if page_language == "en":
            tables = self._invoke_strategy_extract(
                self._english_extractor,
                page,
                table_bbox,
                confidence,
                page_language,
            )
            self._sync_strategy_state(self._english_extractor)
            return tables

        if page_language in {"zh", "mixed"}:
            tables = self._invoke_strategy_extract(
                self._chinese_extractor,
                page,
                table_bbox,
                confidence,
                page_language,
            )
            self._sync_strategy_state(self._chinese_extractor)
            return tables

        return []

    def extract_text_alignment_candidates(
        self,
        page: fitz.Page,
        excluded_regions: Optional[List[BBox]] = None,
        allowed_regions: Optional[List[BBox]] = None,
        use_legacy_fallback: bool = True,
        page_language: Optional[str] = None,
    ) -> List[Table]:
        """Expose the language-specific text-alignment strategy."""
        if page_language is None:
            from hexai_pdf_parser.extractors.language_detector import (
                detect_page_language as detect_language,
            )

            page_language = detect_language(page)

        strategy = (
            self._chinese_extractor
            if page_language in {"zh", "mixed"}
            else self._english_extractor
        )
        tables = self._invoke_strategy_text_alignment(
            strategy,
            page,
            excluded_regions,
            allowed_regions,
            use_legacy_fallback,
        )
        self._sync_strategy_state(strategy)
        return tables

    def _sync_strategy_state(self, strategy: object) -> None:
        for name in ("_last_wireless_recovery", "_last_text_alignment_debug"):
            if hasattr(strategy, name):
                setattr(self, name, getattr(strategy, name))

    def _extract_legacy_text_alignment(
        self,
        page: fitz.Page,
        excluded_regions: Optional[List[BBox]] = None,
        allowed_regions: Optional[List[BBox]] = None,
    ) -> List[Table]:
        callback = getattr(self, "_legacy_text_alignment_callback", None)
        if callback is None:
            return []
        return callback(
            page,
            excluded_regions=excluded_regions,
            allowed_regions=allowed_regions,
        )

    @staticmethod
    def _invoke_strategy_extract(
        strategy: object,
        page: fitz.Page,
        table_bbox: Optional[BBox],
        confidence: Optional[float],
        page_language: str,
    ) -> List[Table]:
        extract = getattr(strategy, "extract")
        parameters = inspect.signature(extract).parameters
        kwargs = {"table_bbox": table_bbox, "confidence": confidence}
        if "page_language" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            kwargs["page_language"] = page_language
        return extract(page, **kwargs)

    @staticmethod
    def _invoke_strategy_text_alignment(
        strategy: object,
        page: fitz.Page,
        excluded_regions: Optional[List[BBox]],
        allowed_regions: Optional[List[BBox]],
        use_legacy_fallback: bool,
    ) -> List[Table]:
        extract = getattr(strategy, "extract_text_alignment_candidates")
        parameters = inspect.signature(extract).parameters
        kwargs = {
            "excluded_regions": excluded_regions,
            "allowed_regions": allowed_regions,
        }
        if "use_legacy_fallback" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            kwargs["use_legacy_fallback"] = use_legacy_fallback
        return extract(page, **kwargs)


__all__ = ["WirelessTableExtractor", "_RowData", "recover_cells_from_region"]
