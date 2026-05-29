"""Tests for the parameter-based table region rule engine."""

import pytest

from hexai_pdf_parser.models import BBox
from hexai_pdf_parser.table_config import RegionRuleSet
from hexai_pdf_parser.table_region_rules import (
    TableRegionCandidate,
    apply_region_rules,
    _find_anchor_regions,
    _expand_downward,
    _merge_nearby_candidates,
)


def _row(y0: float, y1: float, text: str = "", x0: float = 10.0, x1: float = 200.0):
    return {
        "tokens": [{"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1}],
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
    }


class TestFindAnchorRegions:
    def test_anchor_generates_region(self):
        rows = [_row(10, 20, "资产负债表"), _row(25, 35, "数据行")]
        candidates = _find_anchor_regions(rows, ["资产负债表"], min_row_window=2)
        assert len(candidates) == 1
        assert candidates[0].diagnostics["anchor"] == "资产负债表"

    def test_no_anchor_match_returns_empty(self):
        rows = [_row(10, 20, "利润表")]
        candidates = _find_anchor_regions(rows, ["资产负债表"], min_row_window=2)
        assert candidates == []

    def test_multiple_anchors_multiple_candidates(self):
        rows = [
            _row(10, 20, "资产"),
            _row(30, 40, "数据"),
            _row(50, 60, "资产"),
        ]
        candidates = _find_anchor_regions(rows, ["资产"], min_row_window=1)
        assert len(candidates) == 2


class TestExpandDownward:
    def test_expands_until_stop_keyword(self):
        all_rows = [
            _row(10, 20, "资产"),
            _row(25, 35, "数据A"),
            _row(40, 50, "数据B"),
            _row(55, 65, "注：这是注释"),
            _row(70, 80, "应排除"),
        ]
        candidate = TableRegionCandidate(
            bbox=BBox(10, 10, 200, 20),
            rows=[all_rows[0]],
        )
        result = _expand_downward(candidate, all_rows, ["注"])
        assert len(result.rows) == 3  # 资产, 数据A, 数据B
        assert "expanded" in result.diagnostics

    def test_no_stop_keywords_expands_all(self):
        all_rows = [
            _row(10, 20, "资产"),
            _row(25, 35, "数据A"),
        ]
        candidate = TableRegionCandidate(
            bbox=BBox(10, 10, 200, 20),
            rows=[all_rows[0]],
        )
        result = _expand_downward(candidate, all_rows, [])
        assert len(result.rows) == 2


class TestMergeNearbyCandidates:
    def test_merges_close_regions(self):
        c1 = TableRegionCandidate(bbox=BBox(10, 10, 200, 30), rows=[_row(10, 30)])
        c2 = TableRegionCandidate(bbox=BBox(10, 35, 200, 50), rows=[_row(35, 50)])
        merged = _merge_nearby_candidates([c1, c2], merge_distance=20.0)
        assert len(merged) == 1

    def test_keeps_separate_distant_regions(self):
        c1 = TableRegionCandidate(bbox=BBox(10, 10, 200, 30), rows=[_row(10, 30)])
        c2 = TableRegionCandidate(bbox=BBox(10, 100, 200, 120), rows=[_row(100, 120)])
        merged = _merge_nearby_candidates([c1, c2], merge_distance=20.0)
        assert len(merged) == 2


class TestApplyRegionRules:
    def test_disabled_rules_return_empty(self):
        rules = RegionRuleSet(enabled=False)
        result = apply_region_rules(rules, [_row(10, 20, "数据")])
        assert result == []

    def test_disabled_rules_return_existing(self):
        rules = RegionRuleSet(enabled=False)
        existing = [TableRegionCandidate(bbox=BBox(0, 0, 100, 100), rows=[])]
        result = apply_region_rules(rules, [], existing_regions=existing)
        assert result == existing

    def test_anchor_based_region_generation(self):
        rules = RegionRuleSet(
            expand_anchors=["资产负债表"],
            stop_keywords=["注"],
            min_row_window=2,
        )
        all_rows = [
            _row(10, 20, "资产负债表"),
            _row(25, 35, "数据A"),
            _row(40, 50, "数据B"),
            _row(55, 65, "注：注释"),
            _row(70, 80, "不应出现"),
        ]
        result = apply_region_rules(rules, all_rows)
        assert len(result) == 1
        assert len(result[0].rows) == 3

    def test_no_anchors_returns_existing(self):
        rules = RegionRuleSet(expand_anchors=[])
        existing = [TableRegionCandidate(bbox=BBox(0, 0, 100, 100), rows=[])]
        result = apply_region_rules(rules, [], existing_regions=existing)
        assert result == existing

    def test_no_anchors_no_existing_returns_empty(self):
        rules = RegionRuleSet(expand_anchors=[])
        result = apply_region_rules(rules, [_row(10, 20, "数据")])
        assert result == []
