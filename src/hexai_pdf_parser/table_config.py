"""Table configuration: global settings, layout profiles, and JSON loading.

Provides :class:`TableConfig` as the single entry point for configuring the
table extraction pipeline.  A config can be loaded from a UTF-8 JSON file or
constructed programmatically via :meth:`TableConfig.default`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class MatcherConfig:
    """Controls how a layout profile is matched against a page."""

    required_keywords: List[str] = field(default_factory=list)
    optional_keywords: List[str] = field(default_factory=list)
    forbidden_keywords: List[str] = field(default_factory=list)
    header_order: List[str] = field(default_factory=list)
    max_header_distance: float = 200.0
    min_match_score: float = 0.5


@dataclass
class RegionRuleSet:
    """Parameter-based rules for region detection correction."""

    expand_anchors: List[str] = field(default_factory=list)
    stop_keywords: List[str] = field(default_factory=list)
    min_row_window: int = 2
    merge_distance: float = 20.0
    handler: Optional[str] = None
    enabled: bool = True


@dataclass
class StructureRuleSet:
    """Parameter-based rules for table structure correction."""

    header_rows: int = 1
    main_columns: List[int] = field(default_factory=list)
    trim_trailing_summary: bool = False
    numeric_column_bias: bool = False
    narrow_header_split: bool = False
    handler: Optional[str] = None
    enabled: bool = True


@dataclass
class LayoutProfile:
    """A named profile that bundles matcher and rule sets."""

    name: str
    priority: int = 0
    matcher: MatcherConfig = field(default_factory=MatcherConfig)
    region_rules: RegionRuleSet = field(default_factory=RegionRuleSet)
    structure_rules: StructureRuleSet = field(default_factory=StructureRuleSet)


@dataclass
class GlobalTableSettings:
    """Global table extraction thresholds and flags."""

    line_tolerance: float = 2.0
    merge_group_tol: float = 0.3
    row_gap_threshold: float = 30.0
    fallback_max_cols: int = 30
    fallback_max_tables: int = 10
    separator_min_width: float = 200.0
    separator_max_height: float = 1.5


@dataclass
class TableConfig:
    """Root configuration object for the table layout rule system."""

    settings: GlobalTableSettings = field(default_factory=GlobalTableSettings)
    profiles: List[LayoutProfile] = field(default_factory=list)

    @staticmethod
    def default() -> TableConfig:
        """Return a config with sensible defaults and no profiles."""
        return TableConfig()

    @staticmethod
    def load(path: str | Path) -> TableConfig:
        """Load a :class:`TableConfig` from a UTF-8 JSON file.

        Unknown top-level keys are ignored so that config files can carry
        forward-compatible fields.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TableConfig.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TableConfig:
        """Construct a :class:`TableConfig` from a parsed JSON dict."""
        settings = GlobalTableSettings(
            **{
                k: v
                for k, v in data.get("settings", {}).items()
                if k in GlobalTableSettings.__dataclass_fields__
            }
        )

        profiles: List[LayoutProfile] = []
        for raw_profile in data.get("profiles", []):
            profiles.append(_parse_profile(raw_profile))

        return cls(settings=settings, profiles=profiles)


def _parse_profile(raw: Dict[str, Any]) -> LayoutProfile:
    """Parse a single profile dict, raising on missing required fields."""
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("Each profile must have a non-empty string 'name'")

    matcher_data = raw.get("matcher", {})
    region_data = raw.get("region_rules", {})
    structure_data = raw.get("structure_rules", {})

    matcher = MatcherConfig(
        **{
            k: v
            for k, v in matcher_data.items()
            if k in MatcherConfig.__dataclass_fields__
        }
    )
    region_rules = RegionRuleSet(
        **{
            k: v
            for k, v in region_data.items()
            if k in RegionRuleSet.__dataclass_fields__
        }
    )
    structure_rules = StructureRuleSet(
        **{
            k: v
            for k, v in structure_data.items()
            if k in StructureRuleSet.__dataclass_fields__
        }
    )

    return LayoutProfile(
        name=name,
        priority=raw.get("priority", 0),
        matcher=matcher,
        region_rules=region_rules,
        structure_rules=structure_rules,
    )
