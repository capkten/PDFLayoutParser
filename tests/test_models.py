"""Tests for shared data models."""

import pytest

from hexai_pdf_parser.models import (
    BBox,
    Block,
    Cell,
    Char,
    Document,
    Image,
    LayoutElement,
    Line,
    Page,
    RenderInfo,
    Seal,
    Span,
    Table,
    Word,
)


class TestBBox:
    def test_creation(self):
        bbox = BBox(x0=10.0, y0=20.0, x1=100.0, y1=200.0)
        assert bbox.x0 == 10.0
        assert bbox.y0 == 20.0
        assert bbox.x1 == 100.0
        assert bbox.y1 == 200.0


class TestDocument:
    def test_structure(self):
        page = Page(index=0, size={"width": 612.0, "height": 792.0}, rotation=0)
        doc = Document(file_name="test.pdf", page_count=1, pages=[page])
        assert doc.file_name == "test.pdf"
        assert doc.page_count == 1
        assert len(doc.pages) == 1
        assert doc.pages[0].index == 0

    def test_default_pages(self):
        doc = Document(file_name="empty.pdf", page_count=0)
        assert doc.pages == []


class TestPage:
    def test_structure(self):
        page = Page(
            index=1,
            size={"width": 612.0, "height": 792.0},
            rotation=90,
        )
        assert page.index == 1
        assert page.size["width"] == 612.0
        assert page.size["height"] == 792.0
        assert page.rotation == 90
        assert page.blocks == []
        assert page.tables == []
        assert page.images == []
        assert page.seals == []
        assert isinstance(page.render, RenderInfo)
        assert page.layout_elements == []


class TestLayoutElementTypes:
    def test_text_element(self):
        bbox = BBox(0, 0, 100, 20)
        span = Span(text="Hello", bbox=bbox, font="Arial", size=12.0)
        elem = LayoutElement(type="text", bbox=bbox, order=0, spans=[span])
        assert elem.type == "text"
        assert len(elem.spans) == 1
        assert elem.spans[0].text == "Hello"

    def test_table_element(self):
        bbox = BBox(0, 0, 200, 100)
        cell = Cell(text="A1", row_index=0, col_index=0, bbox=bbox)
        table = Table(bbox=bbox, rows=1, cols=1, cells=[cell])
        elem = LayoutElement(type="table", bbox=bbox, order=1, content=table)
        assert elem.type == "table"
        assert elem.content == table

    def test_seal_element(self):
        bbox = BBox(400, 700, 500, 792)
        seal = Seal(bbox=bbox, page_index=0, path="/tmp/seal.png")
        elem = LayoutElement(type="seal", bbox=bbox, order=2, content=seal)
        assert elem.type == "seal"
        assert elem.content.path == "/tmp/seal.png"

    def test_image_element(self):
        bbox = BBox(100, 100, 300, 300)
        img = Image(
            bbox=bbox,
            page_index=0,
            resource_index=0,
            width=200,
            height=200,
            path="/tmp/img.png",
            ext="png",
        )
        elem = LayoutElement(type="image", bbox=bbox, order=3, content=img)
        assert elem.type == "image"
        assert elem.content.ext == "png"

    def test_separator_element(self):
        bbox = BBox(0, 100, 612, 102)
        elem = LayoutElement(type="separator", bbox=bbox, order=4)
        assert elem.type == "separator"
        assert elem.content is None


class TestChar:
    def test_optional_fields(self):
        bbox = BBox(10, 10, 20, 20)
        char = Char(text="H", bbox=bbox)
        assert char.font is None
        assert char.size is None
        assert char.color is None
        assert char.flags is None

    def test_with_all_fields(self):
        bbox = BBox(10, 10, 20, 20)
        char = Char(text="H", bbox=bbox, font="Arial", size=12.0, color="#000000", flags=0)
        assert char.font == "Arial"
        assert char.size == 12.0


class TestWord:
    def test_default_chars(self):
        bbox = BBox(0, 0, 50, 20)
        word = Word(text="Hello", bbox=bbox)
        assert word.chars == []

    def test_with_chars(self):
        bbox = BBox(0, 0, 50, 20)
        char = Char(text="H", bbox=bbox)
        word = Word(text="Hello", bbox=bbox, chars=[char])
        assert len(word.chars) == 1


class TestLine:
    def test_default_words(self):
        bbox = BBox(0, 0, 200, 20)
        line = Line(text="Hello world", bbox=bbox)
        assert line.words == []


class TestBlock:
    def test_default_lines(self):
        bbox = BBox(0, 0, 200, 100)
        block = Block(text="Paragraph", bbox=bbox)
        assert block.lines == []


class TestTable:
    def test_defaults(self):
        bbox = BBox(0, 0, 200, 100)
        table = Table(bbox=bbox, rows=2, cols=2)
        assert table.cells == []
        assert table.confidence is None
        assert table.source is None


class TestCell:
    def test_default_span(self):
        bbox = BBox(0, 0, 50, 20)
        cell = Cell(text="A", row_index=0, col_index=0, bbox=bbox)
        assert cell.rowspan == 1
        assert cell.colspan == 1


class TestImage:
    def test_optional_fields(self):
        bbox = BBox(0, 0, 100, 100)
        img = Image(bbox=bbox, page_index=0, resource_index=0, width=100, height=100)
        assert img.path is None
        assert img.ext is None


class TestSeal:
    def test_optional_path(self):
        bbox = BBox(0, 0, 50, 50)
        seal = Seal(bbox=bbox, page_index=0)
        assert seal.path is None


class TestRenderInfo:
    def test_defaults(self):
        info = RenderInfo()
        assert info.path is None
        assert info.width is None
        assert info.height is None
        assert info.dpi is None
