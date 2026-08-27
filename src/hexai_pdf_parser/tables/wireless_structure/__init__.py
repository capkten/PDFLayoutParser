"""Isolated wireless-table structure recovery building blocks."""

from .span_chain import region_spans
from .recoverer import recover_cells_from_region

__all__ = ["region_spans", "recover_cells_from_region"]
