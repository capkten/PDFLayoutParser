from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "test_single.py"


def test_single_script_uses_current_parser_api_for_page_zero():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "page_index: int = 0" in source
    assert "page_indices=[page_index]" in source
    assert "ml_model_path=ml_model_path" in source
    assert "use_ml" not in source
    assert "CURRENT_DIR / \"src\"" in source
