"""Table extractors package."""

from hexai_pdf_parser.tables.extractors.wired_table_extractor import WiredTableExtractor
from hexai_pdf_parser.tables.extractors.wireless_table_extractor import WirelessTableExtractor

__all__ = [
    "WiredTableExtractor",
    "WirelessTableExtractor",
]
