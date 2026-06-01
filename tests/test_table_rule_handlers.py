"""Tests for registered table rule handlers."""

import pytest

from hexai_pdf_parser.models import BBox
from hexai_pdf_parser.table_rule_handlers import (
    REGION_RULE_HANDLERS,
    STRUCTURE_RULE_HANDLERS,
    get_region_handler,
    get_structure_handler,
    register_region_handler,
    register_structure_handler,
)
from hexai_pdf_parser.table_region_rules import TableRegionCandidate
from hexai_pdf_parser.table_structure_rules import TableStructureCandidate


class TestHandlerRegistry:
    def test_builtin_region_handler_exists(self):
        assert "noop_region" in REGION_RULE_HANDLERS

    def test_builtin_structure_handler_exists(self):
        assert "noop_structure" in STRUCTURE_RULE_HANDLERS

    def test_lookup_known_region_handler(self):
        handler = get_region_handler("noop_region")
        candidates = [TableRegionCandidate(bbox=BBox(0, 0, 100, 100), rows=[])]
        result = handler(candidates, [], {})
        assert result is candidates

    def test_lookup_known_structure_handler(self):
        handler = get_structure_handler("noop_structure")
        candidate = TableStructureCandidate(rows=3, cols=2, cells=[])
        result = handler(candidate, {})
        assert result is candidate

    def test_unknown_region_handler_raises(self):
        with pytest.raises(KeyError, match="unknown"):
            get_region_handler("unknown")

    def test_unknown_structure_handler_raises(self):
        with pytest.raises(KeyError, match="unknown"):
            get_structure_handler("unknown")


class TestRegisterHandlers:
    def test_register_custom_region_handler(self):
        @register_region_handler("test_custom_region")
        def custom_handler(candidates, rows, params):
            return candidates

        assert "test_custom_region" in REGION_RULE_HANDLERS
        assert get_region_handler("test_custom_region") is custom_handler

    def test_register_custom_structure_handler(self):
        @register_structure_handler("test_custom_structure")
        def custom_handler(candidate, params):
            return candidate

        assert "test_custom_structure" in STRUCTURE_RULE_HANDLERS
        assert get_structure_handler("test_custom_structure") is custom_handler


class TestCombinedParameterPlusHandler:
    def test_region_handler_receives_params(self):
        captured = {}

        @register_region_handler("test_capture_region")
        def capture_handler(candidates, rows, params):
            captured.update(params)
            return candidates

        handler = get_region_handler("test_capture_region")
        handler([], [], {"key": "value"})
        assert captured["key"] == "value"

    def test_structure_handler_receives_params(self):
        captured = {}

        @register_structure_handler("test_capture_structure")
        def capture_handler(candidate, params):
            captured.update(params)
            return candidate

        handler = get_structure_handler("test_capture_structure")
        handler(TableStructureCandidate(rows=1, cols=1, cells=[]), {"key": "value"})
        assert captured["key"] == "value"
