import importlib
import sys
import types
from unittest.mock import patch

import pytest


def test_text_runs_literal_import_fallback_when_typing_lacks_literal():
    """Simulate Python 3.7 environment where typing has no Literal attribute."""
    import hexai_pdf_parser.tables.wireless_structure.text_runs as text_runs_mod

    # Create a mock typing module that does NOT have Literal (mimics Python 3.7)
    real_typing = sys.modules["typing"]
    mock_typing = types.ModuleType("typing")
    for attr in dir(real_typing):
        if attr != "Literal":
            setattr(mock_typing, attr, getattr(real_typing, attr))

    # Also verify that reloading text_runs succeeds under simulated Python 3.7 typing
    with patch.dict(sys.modules, {"typing": mock_typing}):
        reloaded = importlib.reload(text_runs_mod)
        assert hasattr(reloaded, "build_text_runs")
        assert hasattr(reloaded, "script_kind")
        assert reloaded.script_kind("中文") == "cjk"
        assert reloaded.script_kind("123") == "numeric"


def test_setup_py_declares_typing_extensions_for_python_37():
    """Verify setup.py declares typing_extensions requirement for python < 3.8."""
    from pathlib import Path

    setup_file = Path(__file__).resolve().parents[1] / "setup.py"
    content = setup_file.read_text(encoding="utf-8")
    assert "typing_extensions" in content
    assert "python_version<'3.8'" in content
