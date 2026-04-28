"""Markdown writer for structured Document output."""

from pdflayoutparser.models import Document, LayoutElement, Table, Image, Seal


class MarkdownWriter:
    """Convert a parsed Document into a Markdown file."""

    def write(self, document: Document, output_path: str) -> None:
        lines: list[str] = []
        for page in document.pages:
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
        # Group cells by row_index and sort by col_index
        row_map: dict[int, list] = {}
        for cell in table.cells:
            row_map.setdefault(cell.row_index, []).append(cell)
        rows: list[list] = []
        for ri in sorted(row_map.keys()):
            row_cells = sorted(row_map[ri], key=lambda c: c.col_index)
            rows.append(row_cells)
        if not rows:
            return []
        # Build markdown rows
        md_rows: list[str] = []
        for row_cells in rows:
            md_rows.append("| " + " | ".join(str(c.text) for c in row_cells) + " |")
        # Add separator after first row
        col_count = len(rows[0])
        separator = "| " + " | ".join(["---"] * col_count) + " |"
        md_rows.insert(1, separator)
        md_rows.append("")
        return md_rows
