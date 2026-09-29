from typing import Any, Dict, List, Mapping, Optional, Sequence

from behavioral_contract import (
    build_layout_signature,
    compare_behavior,
    normalize_markdown,
    parse_markdown_semantics,
)


def test_normalize_markdown_preserves_internal_spaces():
    result = normalize_markdown("A  B\r\n![image](C:/a/p.png)\r\n", {"C:/a": "<ROOT>"})
    assert result == "A  B\n![image](<ROOT>/p.png)\n"


def test_table_text_difference_is_not_hidden_by_whitespace_cleanup():
    result = compare_behavior(
        {"page_type": "vector", "markdown": "<table><tr><td>A  B</td></tr></table>"},
        {"page_type": "vector", "markdown": "<table><tr><td>A B</td></tr></table>"},
    )
    assert result["passed"] is False
    assert "table_text" in result["categories"]


def test_scanned_empty_markdown_matches():
    result = compare_behavior(
        {"page_type": "scanned", "markdown": ""},
        {"page_type": "scanned", "markdown": ""},
    )
    assert result["passed"] is True


def test_vector_scanned_mismatch_fails():
    result = compare_behavior(
        {"page_type": "vector", "markdown": "正文"},
        {"page_type": "scanned", "markdown": ""},
    )
    assert result["passed"] is False
    assert "page_type" in result["categories"]


def test_reading_order_difference_fails_even_when_text_set_matches():
    result = compare_behavior(
        {"page_type": "vector", "markdown": "A\nB", "reading_order": ["A", "B"], "tables": []},
        {"page_type": "vector", "markdown": "B\nA", "reading_order": ["B", "A"], "tables": []},
    )
    assert result["passed"] is False
    assert "reading_order" in result["categories"]


def test_span_difference_and_occupancy_gap_are_reported():
    result = compare_behavior(
        {
            "page_type": "vector",
            "markdown": "<table><tr><td>A</td><td>B</td></tr></table>",
            "tables": [
                {
                    "rows": 1,
                    "cols": 2,
                    "cells": [
                        {"row": 0, "col": 0, "text": "A"},
                        {"row": 0, "col": 1, "text": "B"},
                    ],
                }
            ],
        },
        {
            "page_type": "vector",
            "markdown": "<table><tr><td>A</td></tr></table>",
            "tables": [
                {
                    "rows": 1,
                    "cols": 2,
                    "cells": [
                        {"row": 0, "col": 0, "text": "A"},
                    ],
                }
            ],
        },
    )
    assert result["passed"] is False
    assert "table_structure" in result["categories"] or "unclassified" in result["categories"]


def test_normalize_markdown_does_not_replace_body_or_table_text():
    markdown = "Mention C:/a/path here.\r\n<table><tr><td>C:/a/path</td></tr></table>\r\n![image](C:/a/path/img.png)\r\n"
    normalized = normalize_markdown(markdown, {"C:/a/path": "<ROOT>"})
    assert "Mention C:/a/path here." in normalized
    assert "<td>C:/a/path</td>" in normalized
    assert "![image](<ROOT>/img.png)" in normalized


def test_normalize_markdown_handles_windows_backslashes_in_resource_roots():
    markdown = "![seal](C:/resources/stamps/seal1.png)\n"
    normalized = normalize_markdown(markdown, {"C:\\resources\\stamps": "<STAMPS>"})
    assert normalized == "![seal](<STAMPS>/seal1.png)\n"


def test_parse_markdown_semantics_extracts_table_and_reading_order():
    markdown = (
        "# Heading\n\n"
        "Paragraph text.\n\n"
        "<table>\n"
        "  <tr><td rowspan=\"2\">TopLeft</td><td>TopRight</td></tr>\n"
        "  <tr><td>BottomRight</td></tr>\n"
        "</table>\n\n"
        "Footer text.\n"
    )
    semantics = parse_markdown_semantics(markdown)
    assert len(semantics["tables"]) == 1
    table = semantics["tables"][0]
    assert table["rows"] == 2
    assert table["cols"] == 2
    assert len(table["cells"]) == 3
    # Check cell coordinates
    cells_by_text = {c["text"]: c for c in table["cells"]}
    assert cells_by_text["TopLeft"]["row"] == 0
    assert cells_by_text["TopLeft"]["col"] == 0
    assert cells_by_text["TopLeft"]["rowspan"] == 2
    assert cells_by_text["TopRight"]["row"] == 0
    assert cells_by_text["TopRight"]["col"] == 1
    assert cells_by_text["BottomRight"]["row"] == 1
    assert cells_by_text["BottomRight"]["col"] == 1
    # Check reading order
    ro = semantics["reading_order"]
    assert any(elem.get("type") == "table" for elem in ro)


def test_build_layout_signature_excludes_bbox():
    elements = [
        {
            "type": "text",
            "order": 0,
            "content": "Sample text",
            "bbox": [10.0, 20.0, 100.0, 40.0],
        },
        {
            "type": "table",
            "order": 1,
            "bbox": [10.0, 50.0, 300.0, 200.0],
            "table": {
                "rows": 1,
                "cols": 1,
                "cells": [
                    {
                        "row": 0,
                        "col": 0,
                        "rowspan": 1,
                        "colspan": 1,
                        "text": "Cell 0",
                        "bbox": [10.0, 50.0, 50.0, 80.0],
                    }
                ],
            },
        },
    ]
    sigs = build_layout_signature(elements)
    assert len(sigs) == 2
    assert sigs[0] == {"type": "text", "order": 0, "text": "Sample text"}
    assert "bbox" not in sigs[0]
    assert sigs[1]["type"] == "table"
    assert sigs[1]["order"] == 1
    assert "bbox" not in sigs[1]
    assert "bbox" not in sigs[1]["table"]["cells"][0]
    assert sigs[1]["table"]["cells"][0] == {
        "row": 0,
        "col": 0,
        "rowspan": 1,
        "colspan": 1,
        "text": "Cell 0",
    }


def test_compare_behavior_table_count_mismatch():
    result = compare_behavior(
        {
            "page_type": "vector",
            "markdown": "<table><tr><td>A</td></tr></table>\n<table><tr><td>B</td></tr></table>",
        },
        {
            "page_type": "vector",
            "markdown": "<table><tr><td>A</td></tr></table>",
        },
    )
    assert result["passed"] is False
    assert "table_count" in result["categories"]
    assert result["table_structure_equal"] is False


def test_compare_behavior_table_structure_rowspan_mismatch():
    result = compare_behavior(
        {
            "page_type": "vector",
            "markdown": "<table><tr><td rowspan=\"2\">A</td><td>B</td></tr><tr><td>C</td></tr></table>",
        },
        {
            "page_type": "vector",
            "markdown": "<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>",
        },
    )
    assert result["passed"] is False
    assert "table_structure" in result["categories"]
    assert result["table_structure_equal"] is False


def test_compare_behavior_body_text_mismatch():
    result = compare_behavior(
        {"page_type": "vector", "markdown": "Paragraph One\n\nParagraph Two\n"},
        {"page_type": "vector", "markdown": "Paragraph One\n\nParagraph Three\n"},
    )
    assert result["passed"] is False
    assert "body_text" in result["categories"]


def test_compare_behavior_resource_path_mismatch():
    result = compare_behavior(
        {"page_type": "vector", "markdown": "![image](path/to/img1.png)\n"},
        {"page_type": "vector", "markdown": "![image](path/to/img2.png)\n"},
    )
    assert result["passed"] is False
    assert "resource_path" in result["categories"]


def test_compare_behavior_scanned_with_nonempty_markdown_fails():
    result = compare_behavior(
        {"page_type": "scanned", "markdown": "Should be empty for scanned"},
        {"page_type": "scanned", "markdown": "Should be empty for scanned"},
    )
    assert result["passed"] is False
    assert "body_text" in result["categories"] or "unclassified" in result["categories"]


def test_compare_behavior_occupancy_overlap_goes_to_unclassified():
    result = compare_behavior(
        {
            "page_type": "vector",
            "markdown": "",
            "tables": [
                {
                    "rows": 1,
                    "cols": 2,
                    "cells": [
                        {"row": 0, "col": 0, "text": "A"},
                        {"row": 0, "col": 1, "text": "B"},
                    ],
                }
            ],
        },
        {
            "page_type": "vector",
            "markdown": "",
            "tables": [
                {
                    "rows": 1,
                    "cols": 2,
                    "cells": [
                        {"row": 0, "col": 0, "text": "A"},
                        {"row": 0, "col": 0, "text": "Overlap!"},
                    ],
                }
            ],
        },
    )
    assert result["passed"] is False
    assert "unclassified" in result["categories"]
    assert any(item.get("type") == "duplicate_occupancy" for item in result["unclassified"])


def test_compare_behavior_identical_vector_pages_pass():
    table_data = [
        {
            "rows": 2,
            "cols": 2,
            "cells": [
                {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "A"},
                {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "B"},
                {"row": 1, "col": 0, "rowspan": 1, "colspan": 1, "text": "C"},
                {"row": 1, "col": 1, "rowspan": 1, "colspan": 1, "text": "D"},
            ],
        }
    ]
    reading_order = [
        {"type": "text", "order": 0, "text": "Header"},
        {"type": "table", "order": 1, "table": table_data[0]},
    ]
    markdown = "Header\n\n<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>\n"
    result = compare_behavior(
        {
            "page_type": "vector",
            "markdown": markdown,
            "reading_order": reading_order,
            "tables": table_data,
        },
        {
            "page_type": "vector",
            "markdown": markdown,
            "reading_order": reading_order,
            "tables": table_data,
        },
    )
    assert result["passed"] is True
    assert result["markdown_equal"] is True
    assert result["page_type_equal"] is True
    assert result["reading_order_equal"] is True
    assert result["table_structure_equal"] is True
    assert result["categories"] == []
    assert result["unclassified"] == []
