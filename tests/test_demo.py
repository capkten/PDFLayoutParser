from pathlib import Path


def test_demo_passes_output_dir_to_parser_and_writes_json(tmp_path, monkeypatch):
    import demo

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"placeholder")
    output_dir = tmp_path / "visualized"
    captured = {}

    def fake_parse_personal_credit_report(**kwargs):
        captured.update(kwargs)
        return {"document": {"file_name": "sample.pdf"}, "pages": []}

    monkeypatch.setattr(demo, "parse_personal_credit_report", fake_parse_personal_credit_report)
    monkeypatch.setattr(
        demo.sys,
        "argv",
        [
            "demo.py",
            str(pdf_path),
            "--output-dir",
            str(output_dir),
            "--wired-line-tolerance",
            "1.75",
        ],
    )

    demo.main()

    assert captured["output_dir"] == str(output_dir)
    assert captured["use_ml_table_detector"] is False
    assert captured["wired_line_tolerance"] == 1.75
    assert (output_dir / "sample.json").exists()


def test_demo_defaults_wired_line_tolerance_to_2_2(tmp_path, monkeypatch):
    import demo

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"placeholder")
    output_dir = tmp_path / "visualized"
    captured = {}

    def fake_parse_personal_credit_report(**kwargs):
        captured.update(kwargs)
        return {"document": {"file_name": "sample.pdf"}, "pages": []}

    monkeypatch.setattr(
        demo, "parse_personal_credit_report", fake_parse_personal_credit_report
    )
    monkeypatch.setattr(
        demo.sys,
        "argv",
        ["demo.py", str(pdf_path), "--output-dir", str(output_dir)],
    )

    demo.main()

    assert captured["wired_line_tolerance"] == 2.2
