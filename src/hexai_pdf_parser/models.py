"""Shared data models for PDFLayoutParser.

All dataclasses in this module are the foundation for the loader, text_extractor,
layout_mapper, and other downstream modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ApiResult:
    """Unified API response wrapper.

    ``code`` is ``1`` for success with content, ``0`` for success with no
    content, and ``-1`` for exceptions.
    """

    code: int
    message: str
    data: Any | None = None


@dataclass
class BBox:
    """Axis-aligned bounding box."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Char:
    """A single character extracted from a PDF."""

    text: str
    bbox: BBox
    font: Optional[str] = None
    size: Optional[float] = None
    color: Optional[str] = None
    flags: Optional[int] = None


@dataclass
class Word:
    """A word composed of one or more characters."""

    text: str
    bbox: BBox
    chars: List[Char] = field(default_factory=list)


@dataclass
class Line:
    """A line of text composed of one or more words."""

    text: str
    bbox: BBox
    words: List[Word] = field(default_factory=list)


@dataclass
class Block:
    """A text block composed of one or more lines."""

    text: str
    bbox: BBox
    lines: List[Line] = field(default_factory=list)


@dataclass
class Span:
    """A styled text span (font + size) within a layout element."""

    text: str
    bbox: BBox
    font: Optional[str] = None
    size: Optional[float] = None


@dataclass
class Cell:
    """A single cell inside a table."""

    text: str
    row_index: int
    col_index: int
    bbox: BBox
    rowspan: int = 1
    colspan: int = 1


@dataclass
class Table:
    """A detected table with cells and metadata."""

    bbox: BBox
    rows: int
    cols: int
    cells: List[Cell] = field(default_factory=list)
    confidence: Optional[float] = None
    source: Optional[str] = None


@dataclass
class Image:
    """An image extracted from a PDF page."""

    bbox: BBox
    page_index: int
    resource_index: int
    width: int
    height: int
    path: Optional[str] = None
    ext: Optional[str] = None


@dataclass
class Seal:
    """A detected seal / stamp on a PDF page."""

    bbox: BBox
    page_index: int
    path: Optional[str] = None


@dataclass
class RenderInfo:
    """Rendering metadata for a page (e.g. rasterised PNG)."""

    path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    dpi: Optional[int] = None


@dataclass
class LayoutElement:
    """A generic layout element produced by the layout mapper.

    The ``type`` field discriminates the element kind (text, table, seal,
    image, separator, etc.).  Depending on the type, one or more of the
    list fields may be populated.
    """

    type: str
    bbox: BBox
    order: int
    content: Any = None
    spans: List[Span] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)
    words: List[Word] = field(default_factory=list)
    chars: List[Char] = field(default_factory=list)


@dataclass
class Page:
    """A single page inside a PDF document."""

    index: int
    size: Dict[str, float]
    rotation: int
    blocks: List[Block] = field(default_factory=list)
    tables: List[Table] = field(default_factory=list)
    images: List[Image] = field(default_factory=list)
    seals: List[Seal] = field(default_factory=list)
    render: RenderInfo = field(default_factory=RenderInfo)
    layout_elements: List[LayoutElement] = field(default_factory=list)


@dataclass
class Document:
    """Top-level document container."""

    file_name: str
    page_count: int
    pages: List[Page] = field(default_factory=list)
