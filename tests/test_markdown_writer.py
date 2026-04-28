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
    assert "| A | B |" in content


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
