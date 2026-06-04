"""Table header normalizer.

Post-processes extracted :class:`Table` objects to normalize grouped
financial headers.  Many Chinese financial reports use a two-row header
where the first row contains a group label (e.g. "本年金额") spanning
several detail columns, and the first column acts as a left anchor
(e.g. "项目") spanning both header rows.

PyMuPDF's ``find_tables`` sometimes misinterprets this layout, assigning
colspan=1 to the group label and rowspan=1 to the left anchor.  This
module detects that pattern and corrects the spans.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

import fitz

from hexai_pdf_parser.models import BBox, Cell, Table
from hexai_pdf_parser.financial_header_handler import (
    normalize_complex_financial_header,
)

_LEFT_ANCHOR_VARIANTS = {"椤圭洰", "项目"}


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _is_left_anchor(text: str) -> bool:
    return text.strip() in _LEFT_ANCHOR_VARIANTS

# Phrases that typically appear as grouped financial header labels.
_GROUP_LABEL_PATTERNS: list[str] = [
    "本年金额",
    "本期金额",
    "上年金额",
    "上期金额",
    "本年发生额",
    "本期发生额",
    "上年发生额",
    "上期发生额",
]
_GROUP_HEADER_TOP_GAP = 28.0
_LEFT_ANCHOR_TEXT = "项目"


class _GroupedHeaderBand:
    """A detected grouped-header span above a table."""

    def __init__(self, text: str, bbox: BBox) -> None:
        self.text = text
        self.bbox = bbox


@dataclass
class _WordToken:
    text: str
    bbox: BBox

    @property
    def x_center(self) -> float:
        return (self.bbox.x0 + self.bbox.x1) / 2

    @property
    def y_center(self) -> float:
        return (self.bbox.y0 + self.bbox.y1) / 2


@dataclass
class _Cluster:
    items: list[_WordToken]

    @property
    def x_center(self) -> float:
        return sum(item.x_center for item in self.items) / len(self.items)

    @property
    def y_center(self) -> float:
        return sum(item.y_center for item in self.items) / len(self.items)

    @property
    def bbox(self) -> BBox:
        x0 = min(item.bbox.x0 for item in self.items)
        y0 = min(item.bbox.y0 for item in self.items)
        x1 = max(item.bbox.x1 for item in self.items)
        y1 = max(item.bbox.y1 for item in self.items)
        return BBox(x0, y0, x1, y1)

    @property
    def text(self) -> str:
        return " ".join(item.text for item in sorted(
            self.items, key=lambda item: (item.y_center, item.x_center)
        ) if item.text.strip())


def normalize_table_headers(table: Table, page: fitz.Page) -> Table:
    """Post-process a table to normalize grouped financial headers.

    Applies generic normalisation first, then detects and promotes
    grouped financial headers when the pattern is recognised.
    *page* is reserved for future page-text-based detection.
    """
    table = _normalize_generic_table(table)
    rebuilt = _rebuild_text_aligned_table(table, page)
    if rebuilt is not None:
        table = rebuilt
    return normalize_complex_financial_header(table, page)


def _normalize_generic_table(table: Table) -> Table:
    """Apply generic header normalisation rules.

    Currently this is a pass-through that preserves existing
    rowspan/colspan values.  It exists as a hook for future
    normalisation logic that applies to all tables regardless of
    financial header structure.
    """
    return table


def _rebuild_text_aligned_table(
    table: Table, page: fitz.Page
) -> Table | None:
    """Rebuild fragmented text-aligned tables from page words.

    This is a generic reconstruction pass for tables whose current cell grid
    is too coarse or too fragmented compared with the page text.  It is only
    applied to text-aligned tables, where we can recover row and column bands
    directly from the word layout.
    """
    if table.source != "text_alignment":
        return None

    if (
        table.rows >= 5
        and table.cols >= 7
        and any(
            _is_left_anchor(cell.text)
            and cell.row_index == 0
            and cell.col_index == 0
            for cell in table.cells
        )
    ):
        return None

    words = _collect_words_in_bbox(page, table.bbox)
    if len(words) < 8:
        return None

    row_clusters = _cluster_tokens(words, axis="y", tolerance=17.0)
    if len(row_clusters) < 2:
        return None

    row_clusters = [
        cluster
        for idx, cluster in enumerate(row_clusters)
        if not _is_extraneous_section_heading(cluster, idx, len(row_clusters))
    ]
    if len(row_clusters) < 2:
        return None

    col_boundaries = _column_boundaries_from_table(table)
    if not col_boundaries:
        # Fall back to word-derived columns when the original table does not
        # expose a stable column skeleton.
        col_clusters = _cluster_tokens(words, axis="x", tolerance=60.0)
        if (
            len(col_clusters) >= 2
            and len(col_clusters) < table.cols
        ):
            sorted_centers = sorted(c.x_center for c in col_clusters)
            gaps = [
                sorted_centers[i + 1] - sorted_centers[i]
                for i in range(len(sorted_centers) - 1)
            ]
            min_gap = min(gaps)
            adaptive_tol = max(8.0, min(min_gap / 2.0, 60.0))
            if adaptive_tol < 60.0:
                col_clusters = _cluster_tokens(words, axis="x", tolerance=adaptive_tol)
        if len(col_clusters) < 2:
            return None
        col_centers = [cluster.x_center for cluster in col_clusters]
        col_boundaries = [
            (col_centers[i] + col_centers[i + 1]) / 2.0
            for i in range(len(col_centers) - 1)
        ]

    if len(row_clusters) == table.rows and len(col_boundaries) + 1 == table.cols:
        return None
    reconstructed_rows: list[list[Cell]] = []

    for row_index, row_cluster in enumerate(row_clusters):
        row_words = sorted(
            row_cluster.items,
            key=lambda item: (item.x_center, item.y_center),
        )
        cell_words: dict[int, list[_WordToken]] = defaultdict(list)

        for word in row_words:
            col_index = _column_index_from_boundaries(
                word.x_center,
                col_boundaries,
            )
            cell_words[col_index].append(word)

        row_cells: list[Cell] = []
        non_empty = 0
        for col_index in sorted(cell_words):
            texts = [token.text for token in sorted(
                cell_words[col_index], key=lambda item: (item.y_center, item.x_center)
            ) if token.text.strip()]
            if not texts:
                continue

            non_empty += 1
            text = _join_cell_text(texts)
            bbox = _union_word_bboxes(cell_words[col_index])
            row_cells.append(
                Cell(
                    text=text,
                    row_index=row_index,
                    col_index=col_index,
                    bbox=bbox,
                )
            )

        if not row_cells:
            continue

        if _looks_like_group_header_row(row_cells, row_index):
            row_cells = _promote_group_header_row(row_cells, len(col_clusters))

        reconstructed_rows.append(row_cells)

    if not reconstructed_rows:
        return None

    reconstructed_cells = [cell for row in reconstructed_rows for cell in row]
    max_row = max(cell.row_index for cell in reconstructed_cells)
    max_col = max(
        cell.col_index + max(1, cell.colspan) - 1 for cell in reconstructed_cells
    )

    return Table(
        bbox=BBox(
            min(word.bbox.x0 for word in words),
            min(word.bbox.y0 for word in words),
            max(word.bbox.x1 for word in words),
            max(word.bbox.y1 for word in words),
        ),
        rows=max_row + 1,
        cols=max_col + 1,
        cells=reconstructed_cells,
        confidence=table.confidence,
        source=table.source,
    )


def _looks_like_grouped_financial_header(table: Table, page: fitz.Page) -> bool:
    """Return *True* if *table* has a grouped financial header pattern.

    Detection criteria:
    1. A cell whose text matches a known group-label phrase (e.g. "本年金额")
       is present in the table.
    2. A cell in column 0 whose text equals "项目" acts as a left anchor.
    3. The table has at least 3 columns (group label + at least 2 detail).
    """
    if table.cols < 3 or table.rows < 2:
        return False

    has_left_anchor = any(
        _is_left_anchor(cell.text) and cell.col_index == 0
        for cell in table.cells
    )
    if not has_left_anchor:
        return False

    for cell in table.cells:
        text = cell.text.strip()
        if cell.row_index == 0:
            for pattern in _GROUP_LABEL_PATTERNS:
                if pattern in text:
                    return True

    return _find_group_header_band(page, table) is not None


def _collect_words_in_bbox(page: fitz.Page, bbox: BBox) -> list[_WordToken]:
    """Collect page words whose bbox intersects *bbox*."""
    collected: list[_WordToken] = []
    try:
        words = page.get_text("words")
    except Exception:
        return collected

    for x0, y0, x1, y1, text, *_ in words:
        if not text or not text.strip():
            continue
        if x1 < bbox.x0 or x0 > bbox.x1 or y1 < bbox.y0 or y0 > bbox.y1:
            continue
        collected.append(_WordToken(text=text.strip(), bbox=BBox(x0, y0, x1, y1)))
    return collected


def _cluster_tokens(
    tokens: list[_WordToken],
    *,
    axis: str,
    tolerance: float,
) -> list[_Cluster]:
    """Cluster tokens by either x or y center using a simple gap rule."""
    if not tokens:
        return []

    if axis == "x":
        ordered = sorted(tokens, key=lambda item: (item.x_center, item.y_center))
        coord = lambda item: item.x_center
    else:
        ordered = sorted(tokens, key=lambda item: (item.y_center, item.x_center))
        coord = lambda item: item.y_center

    clusters: list[_Cluster] = []
    current: list[_WordToken] = [ordered[0]]

    for token in ordered[1:]:
        value = coord(token)
        current_center = (
            sum(coord(item) for item in current) / len(current)
        )
        if abs(value - current_center) <= tolerance:
            current.append(token)
        else:
            clusters.append(_Cluster(items=current))
            current = [token]

    clusters.append(_Cluster(items=current))
    return clusters


def _nearest_cluster_index(value: float, centers: list[float]) -> int:
    return min(range(len(centers)), key=lambda idx: abs(centers[idx] - value))


def _column_index_from_boundaries(value: float, boundaries: list[float]) -> int:
    """Assign a value to the column interval defined by adjacent centers."""
    for idx, boundary in enumerate(boundaries):
        if value < boundary:
            return idx
    return len(boundaries)


def _column_boundaries_from_table(table: Table) -> list[float]:
    """Recover column boundaries from an already-extracted table grid."""
    by_col: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for cell in table.cells:
        if cell.colspan != 1:
            continue
        by_col[cell.col_index].append((cell.bbox.x0, cell.bbox.x1))

    ordered = []
    for col_index, spans in sorted(by_col.items()):
        if not spans:
            continue
        x0 = min(span[0] for span in spans)
        x1 = max(span[1] for span in spans)
        center = (x0 + x1) / 2.0
        ordered.append((col_index, x0, x1, center))

    if len(ordered) < 2:
        return []

    boundaries: list[float] = []
    for idx in range(len(ordered) - 1):
        _, _, left_x1, left_center = ordered[idx]
        _, right_x0, _, right_center = ordered[idx + 1]
        if left_x1 <= right_x0:
            boundaries.append((left_x1 + right_x0) / 2.0)
        else:
            boundaries.append((left_center + right_center) / 2.0)

    return boundaries


_SECTION_HEADING_RE = re.compile(r"^\s*(?:\d+[．\.]|（[一二三四五六七八九十]+）)")


def _is_extraneous_section_heading(
    cluster: _Cluster,
    cluster_index: int,
    total_clusters: int,
) -> bool:
    """Filter trailing section headings that were absorbed into the table bbox."""
    if cluster_index + 1 != total_clusters:
        return False
    text = cluster.text.strip()
    if not text:
        return False
    if any(char.isdigit() for char in text) and "．" not in text and "." not in text:
        return False
    return bool(_SECTION_HEADING_RE.match(text))


def _join_cell_text(texts: list[str]) -> str:
    """Join reconstructed fragments into a stable cell text."""
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0]
    return " ".join(texts)


def _union_word_bboxes(words: list[_WordToken]) -> BBox:
    x0 = min(word.bbox.x0 for word in words)
    y0 = min(word.bbox.y0 for word in words)
    x1 = max(word.bbox.x1 for word in words)
    y1 = max(word.bbox.y1 for word in words)
    return BBox(x0, y0, x1, y1)


def _looks_like_group_header_row(cells: list[Cell], row_index: int) -> bool:
    """Return True if a reconstructed row looks like a grouped header line."""
    if row_index != 0:
        return False
    non_empty = [cell for cell in cells if cell.text.strip()]
    if len(non_empty) != 1:
        return False
    return _matches_any(non_empty[0].text.strip(), _GROUP_LABEL_PATTERNS)


def _promote_group_header_row(cells: list[Cell], total_cols: int) -> list[Cell]:
    """Expand a single-cell group header row across the detail columns."""
    promoted: list[Cell] = []
    for cell in cells:
        if _matches_any(cell.text.strip(), _GROUP_LABEL_PATTERNS):
            promoted.append(
                Cell(
                    text=cell.text,
                    row_index=cell.row_index,
                    col_index=max(1, cell.col_index),
                    bbox=cell.bbox,
                    rowspan=1,
                    colspan=max(1, total_cols - max(1, cell.col_index)),
                )
            )
        else:
            promoted.append(cell)
    return promoted


def _promote_grouped_header(table: Table, page: fitz.Page) -> Table:
    """Promote a detected grouped financial header.

    Adjustments made:
    - The group-label cell's colspan is set to ``table.cols - 1``
      (spanning all columns except the left anchor).
    - The left-anchor cell ("项目") in column 0 has its rowspan set to 2.
    - All body cells are left unchanged.
    """
    band = _find_group_header_band(page, table)
    inline_group_label = next(
        (
            cell
            for cell in table.cells
            if cell.row_index == 0
            and _matches_any(cell.text.strip(), _GROUP_LABEL_PATTERNS)
        ),
        None,
    )

    if band is not None and inline_group_label is None:
        if any(
            _is_left_anchor(cell.text) and cell.row_index == 0 and cell.col_index == 0
            for cell in table.cells
        ):
            return _promote_grouped_header_in_place(table, band, page)
        return _promote_external_group_header(table, band)

    promoted_cells: list[Cell] = []

    for cell in table.cells:
        text = cell.text.strip()

        # Promote group label: extend colspan to cover all non-anchor columns.
        is_group_label = _matches_any(text, _GROUP_LABEL_PATTERNS)
        if is_group_label:
            promoted_cells.append(
                Cell(
                    text=cell.text,
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                    bbox=cell.bbox,
                    rowspan=cell.rowspan,
                    colspan=table.cols - 1,
                )
            )
            continue

        # Promote left anchor: extend rowspan to cover both header rows.
        if _is_left_anchor(text) and cell.col_index == 0:
            promoted_cells.append(
                Cell(
                    text=cell.text,
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                    bbox=cell.bbox,
                    rowspan=2,
                    colspan=cell.colspan,
                )
            )
            continue

        promoted_cells.append(cell)

    return Table(
        bbox=table.bbox,
        rows=table.rows,
        cols=table.cols,
        cells=promoted_cells,
        confidence=table.confidence,
        source=table.source,
    )


def _promote_grouped_header_in_place(
    table: Table, band: _GroupedHeaderBand, page: fitz.Page
) -> Table:
    """Promote a grouped header without inserting a new row.

    This keeps the left anchor on row 0 and overlays the group label into the
    same header row, which is the correct shape for text-aligned tables that
    already have a stable top row.
    """
    promoted_cells: list[Cell] = []
    moved_fragments: dict[int, Cell] = {}

    for cell in table.cells:
        text = cell.text.strip()

        if _is_left_anchor(text) and cell.row_index == 0 and cell.col_index == 0:
            promoted_cells.append(
                Cell(
                    text=cell.text,
                    row_index=cell.row_index,
                    col_index=cell.col_index,
                    bbox=cell.bbox,
                    rowspan=max(2, cell.rowspan),
                    colspan=cell.colspan,
                )
            )
            continue

        if (
            cell.row_index == 0
            and cell.col_index > 0
            and cell.rowspan > 1
            and not _matches_any(text, _GROUP_LABEL_PATTERNS)
        ):
            moved = _merge_header_fragment_with_lower_line(page, cell, table)
            if moved is not None:
                moved_fragments[cell.col_index] = moved
                continue

        promoted_cells.append(cell)

    promoted_cells.append(
        Cell(
            text=band.text,
            row_index=0,
            col_index=1,
            bbox=band.bbox,
            rowspan=1,
            colspan=max(1, table.cols - 1),
        )
    )

    promoted_cells.extend(moved_fragments.values())

    top_y = min(table.bbox.y0, band.bbox.y0)
    return Table(
        bbox=BBox(table.bbox.x0, top_y, table.bbox.x1, table.bbox.y1),
        rows=table.rows,
        cols=table.cols,
        cells=promoted_cells,
        confidence=table.confidence,
        source=table.source,
    )


def _find_group_header_band(
    page: fitz.Page, table: Table
) -> _GroupedHeaderBand | None:
    """Find a grouped-header span that sits just above the table body."""
    try:
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return None

    top = table.bbox.y0
    best: _GroupedHeaderBand | None = None

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                if not _matches_any(text, _GROUP_LABEL_PATTERNS):
                    continue

                bbox = BBox(*span["bbox"])
                center_y = (bbox.y0 + bbox.y1) / 2
                if not (top - _GROUP_HEADER_TOP_GAP <= center_y < top):
                    continue

                if best is None or (bbox.x1 - bbox.x0) > (best.bbox.x1 - best.bbox.x0):
                    best = _GroupedHeaderBand(text=text, bbox=bbox)

    return best


def _promote_external_group_header(
    table: Table, band: _GroupedHeaderBand
) -> Table:
    """Insert a grouped-header row that sits above the current table."""
    promoted_cells: list[Cell] = [
        Cell(
            text=band.text,
            row_index=0,
            col_index=1,
            bbox=band.bbox,
            rowspan=1,
            colspan=max(1, table.cols - 1),
        )
    ]

    for cell in table.cells:
        promoted_cells.append(
            Cell(
                text=cell.text,
                row_index=cell.row_index + 1,
                col_index=cell.col_index,
                bbox=cell.bbox,
                rowspan=max(1, cell.rowspan),
                colspan=max(1, cell.colspan),
            )
        )

    for idx, cell in enumerate(promoted_cells):
        if cell.row_index == 1 and cell.col_index == 0 and cell.text.strip() == _LEFT_ANCHOR_TEXT:
            promoted_cells[idx] = Cell(
                text=cell.text,
                row_index=cell.row_index,
                col_index=cell.col_index,
                bbox=cell.bbox,
                rowspan=max(2, cell.rowspan),
                colspan=cell.colspan,
            )

    top_y = min(table.bbox.y0, band.bbox.y0)
    return Table(
        bbox=BBox(table.bbox.x0, top_y, table.bbox.x1, table.bbox.y1),
        rows=table.rows + 1,
        cols=table.cols,
        cells=promoted_cells,
        confidence=table.confidence,
        source=table.source,
    )


def _merge_header_fragment_with_lower_line(
    page: fitz.Page, cell: Cell, table: Table
) -> Cell | None:
    """Merge a split header fragment with the continuation line below it."""
    try:
        words = page.get_text("words")
    except Exception:
        return None

    candidates: list[tuple[float, float, float, float, str]] = []
    for x0, y0, x1, y1, text, *_ in words:
        if not text or not text.strip():
            continue
        if x1 < cell.bbox.x0 or x0 > cell.bbox.x1:
            continue
        if y0 < cell.bbox.y1 - 1.0:
            continue
        if y0 > cell.bbox.y1 + 24.0:
            continue
        candidates.append((x0, y0, x1, y1, text.strip()))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[1], item[0]))
    merged_text = " ".join([cell.text.strip()] + [c[4] for c in candidates])
    merged_bbox = BBox(
        min([cell.bbox.x0] + [c[0] for c in candidates]),
        min([cell.bbox.y0] + [c[1] for c in candidates]),
        max([cell.bbox.x1] + [c[2] for c in candidates]),
        max([cell.bbox.y1] + [c[3] for c in candidates]),
    )
    return Cell(
        text=merged_text,
        row_index=1,
        col_index=cell.col_index,
        bbox=merged_bbox,
        rowspan=1,
        colspan=cell.colspan,
    )

