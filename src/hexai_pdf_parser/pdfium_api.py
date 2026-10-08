"""JSON bridge and DTO conversion for the standalone Rust PDF APIs."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Optional

from hexai_pdf_parser import _pdf_fast
from hexai_pdf_parser.core.models import (
    BBox, Block, Cell, CellStructure, Image, Line, RenderInfo, Table,
    TableStructure, TextBlock, TextChar, Word,
)


def _native_library_path() -> Optional[str]:
    system = platform.system()
    machine = platform.machine().lower()
    target = {
        ("Windows", "amd64"): ("win-x64", "pdfium.dll"),
        ("Windows", "x86_64"): ("win-x64", "pdfium.dll"),
        ("Linux", "x86_64"): ("linux-x64", "libpdfium.so"),
        ("Darwin", "x86_64"): ("mac-x64", "libpdfium.dylib"),
        ("Darwin", "arm64"): ("mac-arm64", "libpdfium.dylib"),
        ("Darwin", "aarch64"): ("mac-arm64", "libpdfium.dylib"),
    }.get((system, machine))
    if target is None:
        return None
    path = Path(__file__).parent / "native" / target[0] / target[1]
    return str(path) if path.is_file() else None


def _run(request: dict):
    request = {**request, "pdfium_library_path": _native_library_path()}
    return json.loads(_pdf_fast.run_public_pdf_api(json.dumps(request)))


def classify_bytes(data: bytes, page_index: int) -> str:
    return _pdf_fast.classify_page_from_bytes(data, page_index, _native_library_path())


def bbox(value: dict) -> BBox:
    return BBox(**value)


def block(value: dict) -> Block:
    return Block(
        text=value["text"], bbox=bbox(value["bbox"]),
        lines=[Line(
            text=line["text"], bbox=bbox(line["bbox"]),
            words=[Word(text=word["text"], bbox=bbox(word["bbox"]))
                   for word in line.get("words", [])],
        ) for line in value.get("lines", [])],
    )


def table(value: dict) -> Table:
    return Table(
        bbox=bbox(value["bbox"]), rows=value["rows"], cols=value["cols"],
        cells=[Cell(
            text=cell["text"], row_index=cell["row_index"],
            col_index=cell["col_index"], bbox=bbox(cell["bbox"]),
            rowspan=cell["rowspan"], colspan=cell["colspan"],
        ) for cell in value["cells"]],
        confidence=value.get("confidence"), source=value.get("source"),
        h_lines=[tuple(line) for line in value["h_lines"]] if value.get("h_lines") is not None else None,
        v_lines=[tuple(line) for line in value["v_lines"]] if value.get("v_lines") is not None else None,
    )


def table_structure(value: dict) -> TableStructure:
    def text_block(item):
        if item is None:
            return None
        return TextBlock(
            text=item["text"], bbox=bbox(item["bbox"]),
            chars=[TextChar(text=char["text"], bbox=bbox(char["bbox"]),
                            confidence=char.get("confidence")) for char in item["chars"]],
        )

    return TableStructure(
        bbox=bbox(value["bbox"]), rows=value["rows"], cols=value["cols"],
        cells=[CellStructure(
            text=cell["text"], row_index=cell["row_index"],
            col_index=cell["col_index"],
            cell_coord=[tuple(point) for point in cell["cell_coord"]],
            bbox=bbox(cell["bbox"]), text_block=text_block(cell.get("text_block")),
            tl_row=cell["tl_row"], tl_col=cell["tl_col"],
            br_row=cell["br_row"], br_col=cell["br_col"],
        ) for cell in value["cells"]],
        confidence=value.get("confidence"), source=value.get("source"),
    )


def image(value: dict) -> Image:
    return Image(
        bbox=bbox(value["bbox"]), page_index=value["page_index"],
        resource_index=value["resource_index"], width=value["width"],
        height=value["height"], path=value.get("path"), ext=value.get("ext"),
    )


def render(value: dict) -> RenderInfo:
    return RenderInfo(**value)
