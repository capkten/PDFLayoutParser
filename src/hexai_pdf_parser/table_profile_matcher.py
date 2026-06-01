"""Layout profile matcher: score pages against named profiles.

Given a page's normalized text lines, keyword positions, and optional header
candidates, this module ranks configured :class:`LayoutProfile` objects and
returns the best match (if any exceeds its ``min_match_score``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from hexai_pdf_parser.table_config import LayoutProfile


@dataclass
class PageFeatures:
    """Extracted features from a single PDF page used for profile matching."""

    text_lines: List[str]
    keyword_positions: Dict[str, List[float]] = field(default_factory=dict)
    header_candidates: List[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """Result of matching a single profile against a page."""

    profile_name: str
    score: float
    matched_required: bool
    matched_optional_count: int
    hit_forbidden: bool


def _find_keyword_lines(keyword: str, text_lines: List[str]) -> List[int]:
    """Return indices of lines containing *keyword*."""
    return [i for i, line in enumerate(text_lines) if keyword in line]


def _check_header_order(
    header_order: List[str],
    text_lines: List[str],
    max_distance: float,
) -> bool:
    """Return True if the header keywords appear in order within *max_distance* lines."""
    if len(header_order) < 2:
        return True

    positions: List[int] = []
    for keyword in header_order:
        indices = _find_keyword_lines(keyword, text_lines)
        if not indices:
            return False
        if positions and indices[0] < positions[-1]:
            return False
        positions.append(indices[0])

    span = positions[-1] - positions[0]
    return span <= max_distance


def score_profile(
    profile: LayoutProfile,
    features: PageFeatures,
) -> MatchResult:
    """Score a single profile against extracted page features."""
    matcher = profile.matcher
    text_lines = features.text_lines

    # Required keywords — all must be present
    required_hits = []
    for kw in matcher.required_keywords:
        indices = _find_keyword_lines(kw, text_lines)
        if not indices:
            return MatchResult(
                profile_name=profile.name,
                score=0.0,
                matched_required=False,
                matched_optional_count=0,
                hit_forbidden=False,
            )
        required_hits.append(len(indices))

    # Forbidden keywords — any present disqualifies
    for kw in matcher.forbidden_keywords:
        if _find_keyword_lines(kw, text_lines):
            return MatchResult(
                profile_name=profile.name,
                score=0.0,
                matched_required=True,
                matched_optional_count=0,
                hit_forbidden=True,
            )

    # Optional keywords — boost score
    optional_count = 0
    for kw in matcher.optional_keywords:
        if _find_keyword_lines(kw, text_lines):
            optional_count += 1

    # Base score from required keywords
    score = float(len(matcher.required_keywords))

    # Boost from optional keywords
    if matcher.optional_keywords:
        score += optional_count * 0.5

    # Order check
    order_ok = _check_header_order(
        matcher.header_order, text_lines, matcher.max_header_distance
    )
    if not order_ok:
        score *= 0.5

    # Normalize
    max_possible = len(matcher.required_keywords) + len(matcher.optional_keywords) * 0.5
    if max_possible > 0:
        score /= max_possible

    return MatchResult(
        profile_name=profile.name,
        score=score,
        matched_required=True,
        matched_optional_count=optional_count,
        hit_forbidden=False,
    )


def match_profiles(
    profiles: List[LayoutProfile],
    features: PageFeatures,
) -> Optional[LayoutProfile]:
    """Return the best-matching profile, or None if no profile meets its threshold."""
    candidates: List[Tuple[LayoutProfile, MatchResult]] = []

    for profile in profiles:
        result = score_profile(profile, features)
        if result.score >= profile.matcher.min_match_score:
            candidates.append((profile, result))

    if not candidates:
        return None

    # Sort by (priority desc, score desc)
    candidates.sort(key=lambda item: (-item[0].priority, -item[1].score))
    return candidates[0][0]
