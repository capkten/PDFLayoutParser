"""Base interface for all specialized table extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import fitz

from hexai_pdf_parser.core.models import BBox, Table


class BaseTableExtractor(ABC):
    """Abstract base class for all table extraction strategies."""

    @abstractmethod
    def extract(
        self,
        page: fitz.Page,
        table_bbox: Optional[BBox] = None,
        confidence: Optional[float] = None,
    ) -> List[Table]:
        """Extract tables from a given PDF page.

        Args:
            page: fitz.Page object.
            table_bbox: Optional bounding box constraint from ML detection or layout rules.
            confidence: Optional detection confidence score.

        Returns:
            List of detected Table objects.
        """
        pass
