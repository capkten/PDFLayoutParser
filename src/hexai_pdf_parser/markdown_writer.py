"""Markdown writer for structured Document output."""

from __future__ import annotations

from html import escape
import re

from hexai_pdf_parser.models import Document, LayoutElement, Table, Image, Seal


class MarkdownWriter:
    """Convert a parsed Document into a Markdown file."""

    def to_string(self, document: Document) -> str:
        """Convert *document* to a Markdown string without writing to disk."""
        lines: list[str] = []
        for page in document.pages:
            for element in page.layout_elements:
                lines.extend(self._render_element(element, page.index))
        return "\n".join(lines)

    def write(self, document: Document, output_path: str) -> None:
        lines: list[str] = []
        for page in document.pages:
            for element in page.layout_elements:
                lines.extend(self._render_element(element, page.index))
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def write_page(self, page, output_path: str) -> None:
        """Convert a single page into a Markdown file."""
        lines: list[str] = []
        for element in page.layout_elements:
            lines.extend(self._render_element(element, page.index))
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _render_element(self, element: LayoutElement, page_index: int) -> list[str]:
        etype = element.type
        if etype == "text":
            return [str(element.content), ""]
        if etype == "table":
            return self._render_table(element.content)
        if etype == "image":
            img: Image = element.content
            if img and img.path:
                return [f"![image]({img.path})", ""]
            return ["[图片]", ""]
        if etype == "seal":
            seal: Seal = element.content
            if seal and seal.path:
                return [f"![seal]({seal.path})", ""]
            return [f"[印章: page-{page_index}]", ""]
        if etype == "separator":
            return ["---", ""]
        return []

    def _render_table(self, table: Table) -> list[str]:
        if not table or not table.cells:
            return []

        max_row = max(
            cell.row_index + max(1, cell.rowspan) - 1
            for cell in table.cells
        )
        max_col = max(
            cell.col_index + max(1, cell.colspan) - 1
            for cell in table.cells
        )

        cell_map: dict[tuple[int, int], Table] = {}
        for cell in table.cells:
            cell_map.setdefault((cell.row_index, cell.col_index), cell)

        # Collect rows that have at least one cell or covered position.
        occupied_rows: set[int] = set()
        for cell in table.cells:
            for r in range(cell.row_index, cell.row_index + max(1, cell.rowspan)):
                occupied_rows.add(r)

        covered: set[tuple[int, int]] = set()
        lines: list[str] = ["<table>", "  <tbody>"]
        for row_index in range(max_row + 1):
            if row_index not in occupied_rows:
                continue
            lines.append("    <tr>")
            for col_index in range(max_col + 1):
                if (row_index, col_index) in covered:
                    continue

                cell = cell_map.get((row_index, col_index))
                if cell is None:
                    lines.append("      <td></td>")
                    continue

                rowspan = max(1, cell.rowspan or 1)
                colspan = max(1, cell.colspan or 1)
                for r in range(row_index, row_index + rowspan):
                    for c in range(col_index, col_index + colspan):
                        if r == row_index and c == col_index:
                            continue
                        covered.add((r, c))

                attrs: list[str] = []
                if rowspan > 1:
                    attrs.append(f'rowspan="{rowspan}"')
                if colspan > 1:
                    attrs.append(f'colspan="{colspan}"')

                text = self._clean_number_text(
                    str(cell.text or "").replace("\n", " ").strip()
                )
                attr_text = f" {' '.join(attrs)}" if attrs else ""
                lines.append(
                    f"      <td{attr_text}>{escape(text, quote=False)}</td>"
                )
            lines.append("    </tr>")
        lines.extend(["  </tbody>", "</table>", ""])
        return lines

    _NUM_SPACE_RE = re.compile(r"(?<=[\d,\.\-])\s+(?=[\d,\.\-])")

    def _clean_number_text(self, text: str) -> str:
        """Remove spurious spaces inside numbers that were split by newlines."""
        # Only apply to text that looks like it contains a numeric fragment
        if not self._NUM_SPACE_RE.search(text):
            return text
        return self._NUM_SPACE_RE.sub("", text)
