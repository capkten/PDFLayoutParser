"""Table extraction, structure parsing, and rule engine modules."""

from hexai_pdf_parser.tables.table_extractor import TableExtractor
from hexai_pdf_parser.tables.base_table_extractor import BaseTableExtractor
from hexai_pdf_parser.tables.extractors import (
    ChineseTableExtractor,
    EnglishTableExtractor,
    WiredTableExtractor,
    WirelessTableExtractor,
)
from hexai_pdf_parser.tables.normalizers import (
    normalize_table_headers,
    normalize_complex_financial_header,
)
from hexai_pdf_parser.tables.table_config import TableConfig, LayoutProfile, RegionRuleSet, StructureRuleSet
from hexai_pdf_parser.tables.table_profile_matcher import match_profiles, PageFeatures
from hexai_pdf_parser.tables.table_region_rules import TableRegionCandidate
from hexai_pdf_parser.tables.table_structure_rules import TableStructureCandidate, apply_structure_rules
from hexai_pdf_parser.tables.table_template_engine import TemplateEngine
from hexai_pdf_parser.tables.wireless_table_recovery import recover_wireless_tables

__all__ = [
    "TableExtractor",
    "BaseTableExtractor",
    "EnglishTableExtractor",
    "ChineseTableExtractor",
    "WiredTableExtractor",
    "WirelessTableExtractor",
    "normalize_table_headers",
    "normalize_complex_financial_header",
    "TableConfig",
    "LayoutProfile",
    "RegionRuleSet",
    "StructureRuleSet",
    "match_profiles",
    "PageFeatures",
    "TableRegionCandidate",
    "TableStructureCandidate",
    "apply_structure_rules",
    "TemplateEngine",
    "recover_wireless_tables",
]
