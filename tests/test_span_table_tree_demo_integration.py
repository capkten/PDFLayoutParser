import json
from pathlib import Path

import pytest

from scripts.span_table_tree_demo import run_demo


PDF_PATH = Path("fix/zh_all_table_pages.pdf")


@pytest.mark.skipif(not PDF_PATH.exists(), reason="demo PDF is not checked in")
def test_page_184_region_builds_seven_leaf_columns_and_json_png(tmp_path):
    result = run_demo(
        str(PDF_PATH),
        page_index=184,
        bbox=(90, 515, 498, 685),
        output_dir=tmp_path,
    )

    tree = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
    assert result["leaf_columns"] == 7
    assert Path(result["png"]).is_file()
    assert [child["kind"] for child in tree["children"][:3]] == [
        "leaf_column",
        "header_group",
        "header_group",
    ]
    grid = next(child for child in tree["children"] if child["kind"] == "grid")
    assert len(grid["children"]) >= 2
    assert [(cell["col_index"], cell["colspan"]) for cell in grid["children"][0]["children"]] == [(1, 3), (4, 3)]
    assert [cell["col_index"] for cell in grid["children"][1]["children"]] == list(range(7))
    body = next(child for child in tree["children"] if child["kind"] == "body")
    assert all(
        cell["rowspan"] == 1
        for row in body["children"]
        for cell in row["children"]
    )
