"""Tests for the CLI module."""

import os
import subprocess
import sys

from tests.conftest import make_text_pdf


def test_cli_runs_pipeline(tmp_dir):
    pdf_path = os.path.join(tmp_dir, "cli_test.pdf")
    make_text_pdf(pdf_path, text="CLI Test")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hexai_pdf_parser.cli",
            pdf_path,
            "--output",
            tmp_dir,
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert os.path.exists(os.path.join(tmp_dir, "output.json"))
    assert os.path.exists(os.path.join(tmp_dir, "output.md"))
