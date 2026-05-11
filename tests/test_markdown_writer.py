import pytest

from pdflayoutparser.markdown_writer import MarkdownWriter
from pdflayoutparser.models import (
    BBox,
    Cell,
    Document,
    Image,
    LayoutElement,
    Page,
    Seal,
    Table,
)


def test_write_text_and_table_markdown(tmp_dir):
    table = Table(
        bbox=BBox(0, 0, 100, 50),
        rows=1,
        cols=2,
        cells=[
            Cell(text="A", row_index=0, col_index=0, bbox=BBox(0, 0, 50, 50)),
            Cell(text="B", row_index=0, col_index=1, bbox=BBox(50, 0, 100, 50)),
        ],
    )
    doc = Document(
        file_name="test.pdf",
        page_count=1,
        pages=[
            Page(
                index=0,
                size={"width": 612, "height": 792},
                rotation=0,
                layout_elements=[
                    LayoutElement(
                        type="text",
                        bbox=BBox(0, 0, 100, 20),
                        order=0,
                        content="Hello World",
                    ),
                    LayoutElement(
                        type="table",
                        bbox=BBox(0, 30, 100, 80),
                        order=1,
                        content=table,
                    ),
                ],
            )
        ],
    )
    writer = MarkdownWriter()
    output_path = f"{tmp_dir}/output.md"
    writer.write(doc, output_path)
    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Hello World" in content
    assert "<table>" in content
    assert "<td>A</td>" in content
    assert "<td>B</td>" in content


def test_write_image_and_seal_placeholders(tmp_dir):
    doc = Document(
        file_name="test.pdf",
        page_count=1,
        pages=[
            Page(
                index=0,
                size={"width": 612, "height": 792},
                rotation=0,
                layout_elements=[
                    LayoutElement(
                        type="image",
                        bbox=BBox(0, 0, 100, 100),
                        order=0,
                        content=Image(
                            bbox=BBox(0, 0, 100, 100),
                            page_index=0,
                            resource_index=0,
                            width=100,
                            height=100,
                            path="images/img.png",
                        ),
                    ),
                    LayoutElement(
                        type="seal",
                        bbox=BBox(0, 100, 50, 150),
                        order=1,
                        content=Seal(
                            bbox=BBox(0, 100, 50, 150),
                            page_index=0,
                            path="seals/seal.png",
                        ),
                    ),
                ],
            )
        ],
    )
    writer = MarkdownWriter()
    output_path = f"{tmp_dir}/output.md"
    writer.write(doc, output_path)
    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "![image](images/img.png)" in content
    assert "![seal](seals/seal.png)" in content


def test_render_sparse_table_preserves_missing_columns():
    table = Table(
        bbox=BBox(0, 0, 100, 50),
        rows=2,
        cols=3,
        cells=[
            Cell(text="A", row_index=0, col_index=0, bbox=BBox(0, 0, 10, 10)),
            Cell(text="B", row_index=0, col_index=2, bbox=BBox(20, 0, 30, 10)),
            Cell(text="C", row_index=1, col_index=0, bbox=BBox(0, 10, 10, 20)),
            Cell(text="D", row_index=1, col_index=2, bbox=BBox(20, 10, 30, 20)),
        ],
    )

    writer = MarkdownWriter()
    lines = writer._render_table(table)

    content = "\n".join(lines)

    assert content.startswith("<table>")
    assert content.count("<tr>") == 2
    assert content.count("<td>A</td>") == 1
    assert content.count("<td></td>") == 2
    assert "<td>B</td>" in content
    assert "<td>C</td>" in content
    assert "<td>D</td>" in content


def test_render_table_uses_html_and_preserves_spans():
    table = Table(
        bbox=BBox(0, 0, 100, 50),
        rows=2,
        cols=2,
        cells=[
            Cell(
                text="A",
                row_index=0,
                col_index=0,
                bbox=BBox(0, 0, 50, 25),
                rowspan=2,
                colspan=1,
            ),
            Cell(
                text="B & C",
                row_index=0,
                col_index=1,
                bbox=BBox(50, 0, 100, 25),
                rowspan=1,
                colspan=1,
            ),
            Cell(
                text="<D>",
                row_index=1,
                col_index=1,
                bbox=BBox(50, 25, 100, 50),
                rowspan=1,
                colspan=1,
            ),
        ],
    )

    writer = MarkdownWriter()
    lines = writer._render_table(table)
    content = "\n".join(lines)

    assert "<table>" in content
    assert '<td rowspan="2">A</td>' in content
    assert "B &amp; C" in content
    assert "&lt;D&gt;" in content
    assert "| A | B |" not in content
