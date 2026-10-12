"""Tests for the table config module."""

import json
from pathlib import Path

import pytest

from hexai_pdf_parser.table_config import (
    GlobalTableSettings,
    LayoutProfile,
    MatcherConfig,
    RegionRuleSet,
    StructureRuleSet,
    TableConfig,
)


class TestTableConfigDefault:
    def test_default_returns_empty_profiles(self):
        config = TableConfig.default()
        assert config.profiles == []
        assert isinstance(config.settings, GlobalTableSettings)

    def test_default_settings_have_expected_values(self):
        settings = GlobalTableSettings()
        assert settings.line_tolerance == 2.0
        assert settings.merge_group_tol == 0.3
        assert settings.row_gap_threshold == 30.0
        assert settings.fallback_max_cols == 30
        assert settings.fallback_max_tables == 10


class TestTableConfigFromDict:
    def test_empty_dict_yields_defaults(self):
        config = TableConfig.from_dict({})
        assert config.profiles == []
        assert config.settings.line_tolerance == 2.0

    def test_settings_override(self):
        config = TableConfig.from_dict(
            {"settings": {"line_tolerance": 5.0, "row_gap_threshold": 50.0}}
        )
        assert config.settings.line_tolerance == 5.0
        assert config.settings.row_gap_threshold == 50.0

    def test_unknown_settings_ignored(self):
        config = TableConfig.from_dict(
            {"settings": {"future_field": "value"}}
        )
        assert config.settings.line_tolerance == 2.0

    def test_single_profile(self):
        config = TableConfig.from_dict(
            {
                "profiles": [
                    {
                        "name": "financial",
                        "priority": 10,
                        "matcher": {
                            "required_keywords": ["资产", "负债"],
                            "optional_keywords": ["合计"],
                        },
                        "region_rules": {
                            "stop_keywords": ["注", "说明"],
                        },
                        "structure_rules": {
                            "header_rows": 2,
                        },
                    }
                ]
            }
        )
        assert len(config.profiles) == 1
        profile = config.profiles[0]
        assert profile.name == "financial"
        assert profile.priority == 10
        assert profile.matcher.required_keywords == ["资产", "负债"]
        assert profile.region_rules.stop_keywords == ["注", "说明"]
        assert profile.structure_rules.header_rows == 2

    def test_handler_name_preserved(self):
        config = TableConfig.from_dict(
            {
                "profiles": [
                    {
                        "name": "test",
                        "region_rules": {"handler": "custom_region"},
                        "structure_rules": {"handler": "custom_structure"},
                    }
                ]
            }
        )
        profile = config.profiles[0]
        assert profile.region_rules.handler == "custom_region"
        assert profile.structure_rules.handler == "custom_structure"

    def test_missing_profile_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            TableConfig.from_dict({"profiles": [{"priority": 5}]})

    def test_empty_profile_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            TableConfig.from_dict({"profiles": [{"name": ""}]})

    def test_multiple_profiles(self):
        config = TableConfig.from_dict(
            {
                "profiles": [
                    {"name": "a", "priority": 1},
                    {"name": "b", "priority": 2},
                ]
            }
        )
        assert len(config.profiles) == 2
        assert config.profiles[0].name == "a"
        assert config.profiles[1].name == "b"


class TestTableConfigLoadJson:
    def test_load_from_file(self, tmp_path):
        data = {
            "settings": {"line_tolerance": 3.0},
            "profiles": [{"name": "loaded", "matcher": {"required_keywords": ["X"]}}],
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        config = TableConfig.load(path)
        assert config.settings.line_tolerance == 3.0
        assert config.profiles[0].name == "loaded"
        assert config.profiles[0].matcher.required_keywords == ["X"]

    def test_load_utf8_file(self, tmp_path):
        data = {
            "profiles": [
                {
                    "name": "中文配置",
                    "matcher": {"required_keywords": ["资产负债表"]},
                }
            ]
        }
        path = tmp_path / "config_cn.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        config = TableConfig.load(path)
        assert config.profiles[0].name == "中文配置"
        assert config.profiles[0].matcher.required_keywords == ["资产负债表"]

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            TableConfig.load(tmp_path / "missing.json")

    def test_load_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            TableConfig.load(path)
