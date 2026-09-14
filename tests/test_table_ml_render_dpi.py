"Tests for ml_render_dpi configuration and propagation."

from unittest.mock import MagicMock, patch
import fitz
import pytest

from hexai_pdf_parser.tables.table_config import GlobalTableSettings, TableConfig
from hexai_pdf_parser.tables.table_extractor import TableExtractor
from hexai_pdf_parser.core.pipeline import Pipeline
from hexai_pdf_parser.extractors.personal_credit_report import (
    PersonalCreditReportPipeline,
    parse_personal_credit_report,
)


def test_table_config_global_settings_has_ml_render_dpi():
    settings = GlobalTableSettings()
    assert settings.ml_render_dpi == 72

    custom = GlobalTableSettings(ml_render_dpi=150)
    assert custom.ml_render_dpi == 150


def test_table_config_from_dict_supports_ml_render_dpi():
    cfg = TableConfig.from_dict({"settings": {"ml_render_dpi": 200}})
    assert cfg.settings.ml_render_dpi == 200


def test_table_extractor_default_and_custom_ml_render_dpi():
    extractor = TableExtractor()
    assert extractor.ml_render_dpi == 72

    custom_extractor = TableExtractor(ml_render_dpi=120)
    assert custom_extractor.ml_render_dpi == 120

    cfg = TableConfig(settings=GlobalTableSettings(ml_render_dpi=180))
    cfg_extractor = TableExtractor(table_config=cfg)
    assert cfg_extractor.ml_render_dpi == 180


def test_table_extractor_passes_ml_render_dpi_to_ml_table_detector():
    extractor = TableExtractor(ml_render_dpi=144)
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)

    with patch("hexai_pdf_parser.ml.ml_table_detector.MLTableDetector") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.detect_with_scores.return_value = []
        mock_cls.return_value = mock_instance

        extractor._extract_model_tables(page, wired_tables=[])
        mock_cls.assert_called_once()
        _, kwargs = mock_cls.call_args
        assert kwargs.get("render_dpi") == 144


def test_pipeline_propagates_ml_render_dpi():
    pipeline = Pipeline("dummy.pdf", ml_render_dpi=160)
    assert pipeline.ml_render_dpi == 160
    extractor = pipeline._create_table_extractor()
    assert extractor.ml_render_dpi == 160


def test_personal_credit_report_pipeline_propagates_ml_render_dpi():
    pipeline = PersonalCreditReportPipeline("dummy.pdf", ml_render_dpi=96)
    assert pipeline.ml_render_dpi == 96
    extractor = pipeline._create_table_extractor()
    assert extractor.ml_render_dpi == 96


def test_parse_personal_credit_report_passes_ml_render_dpi():
    with patch("hexai_pdf_parser.extractors.personal_credit_report.PersonalCreditReportPipeline") as mock_pipeline_cls:
        mock_instance = MagicMock()
        mock_instance.run.return_value = MagicMock(file_name="dummy.pdf", page_count=0, pages=[])
        mock_pipeline_cls.return_value = mock_instance

        parse_personal_credit_report("dummy.pdf", ml_render_dpi=110)
        mock_pipeline_cls.assert_called_once()
        _, kwargs = mock_pipeline_cls.call_args
        assert kwargs.get("ml_render_dpi") == 110

