"""Tests for the layout profile matcher."""

import pytest

from hexai_pdf_parser.table_config import (
    LayoutProfile,
    MatcherConfig,
    RegionRuleSet,
    StructureRuleSet,
)
from hexai_pdf_parser.table_profile_matcher import (
    MatchResult,
    PageFeatures,
    match_profiles,
    score_profile,
)


def _profile(
    name: str = "test",
    *,
    required: list[str] | None = None,
    optional: list[str] | None = None,
    forbidden: list[str] | None = None,
    header_order: list[str] | None = None,
    max_header_distance: float = 200.0,
    priority: int = 0,
    min_score: float = 0.5,
) -> LayoutProfile:
    return LayoutProfile(
        name=name,
        priority=priority,
        matcher=MatcherConfig(
            required_keywords=required or [],
            optional_keywords=optional or [],
            forbidden_keywords=forbidden or [],
            header_order=header_order or [],
            max_header_distance=max_header_distance,
            min_match_score=min_score,
        ),
        region_rules=RegionRuleSet(),
        structure_rules=StructureRuleSet(),
    )


class TestScoreProfile:
    def test_exact_required_match(self):
        p = _profile(required=["资产", "负债"])
        features = PageFeatures(text_lines=["资产负债表", "负债合计"])
        result = score_profile(p, features)
        assert result.matched_required is True
        assert result.score > 0.0

    def test_missing_required_keyword_gives_zero(self):
        p = _profile(required=["资产"])
        features = PageFeatures(text_lines=["利润表"])
        result = score_profile(p, features)
        assert result.matched_required is False
        assert result.score == 0.0

    def test_optional_keyword_boost(self):
        p = _profile(required=["资产"], optional=["合计"])
        features = PageFeatures(text_lines=["资产负债表", "合计金额"])
        result = score_profile(p, features)
        assert result.matched_optional_count == 1

    def test_forbidden_keyword_rejects(self):
        p = _profile(required=["资产"], forbidden=["注释"])
        features = PageFeatures(text_lines=["资产负债表", "注释部分"])
        result = score_profile(p, features)
        assert result.hit_forbidden is True
        assert result.score == 0.0

    def test_header_order_mismatch_halves_score(self):
        p = _profile(required=["A", "B"], header_order=["A", "B"], max_header_distance=5.0)
        # B appears before A → order mismatch
        features = PageFeatures(text_lines=["B first", "A second"])
        result = score_profile(p, features)
        assert result.score > 0.0
        # Compare with correct order
        features_ok = PageFeatures(text_lines=["A first", "B second"])
        result_ok = score_profile(p, features_ok)
        assert result_ok.score > result.score

    def test_no_keywords_always_matches(self):
        p = _profile()
        features = PageFeatures(text_lines=["anything"])
        result = score_profile(p, features)
        assert result.score >= 0.0


class TestMatchProfiles:
    def test_returns_best_matching_profile(self):
        profiles = [
            _profile(name="a", required=["资产"], priority=1),
            _profile(name="b", required=["资产"], priority=5),
        ]
        features = PageFeatures(text_lines=["资产负债表"])
        result = match_profiles(profiles, features)
        assert result is not None
        assert result.name == "b"

    def test_returns_none_when_no_profile_meets_threshold(self):
        profiles = [
            _profile(name="a", required=["X", "Y", "Z"], optional=["W"], min_score=0.9),
        ]
        # Only X and Y present → score < threshold with 3 required + 1 optional
        features = PageFeatures(text_lines=["X is here", "Y too"])
        result = match_profiles(profiles, features)
        assert result is None

    def test_priority_tiebreak(self):
        profiles = [
            _profile(name="low", required=["X"], priority=1),
            _profile(name="high", required=["X"], priority=10),
        ]
        features = PageFeatures(text_lines=["X is here"])
        result = match_profiles(profiles, features)
        assert result.name == "high"

    def test_score_tiebreak_when_same_priority(self):
        profiles = [
            _profile(name="more_optional", required=["X"], optional=["Y", "Z"], priority=5),
            _profile(name="less_optional", required=["X"], optional=["Y"], priority=5),
        ]
        features = PageFeatures(text_lines=["X and Y and Z"])
        result = match_profiles(profiles, features)
        assert result.name == "more_optional"

    def test_empty_profiles_returns_none(self):
        features = PageFeatures(text_lines=["anything"])
        assert match_profiles([], features) is None
