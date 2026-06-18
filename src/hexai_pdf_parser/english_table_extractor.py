"""English table extractor for financial reports.

Extracts tables from English financial reports (e.g., SEC 10-Q, 10-K)
using color-alternating row backgrounds as strong row signals.

Key features:
- Detects light blue / white alternating row backgrounds
- Handles $ symbol pairing with amounts
- Detects columns based on x-position overlap
- Identifies header rows above colored data area
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import fitz

from hexai_pdf_parser.models import BBox, Cell, Table


# Color constants for row backgrounds
LIGHT_BLUE = (0.8, 0.933, 1.0)
WHITE = (1.0, 1.0, 1.0)


@dataclass
class _RowData:
    """Internal representation of a table row."""
    words: List[Tuple[float, float, float, float, str]]  # (x0, y0, x1, y1, text)
    y0: float
    y1: float
    color: Optional[str]  # 'blue', 'white', or None for header rows
    is_header: bool = False


class EnglishTableExtractor:
    """Extract tables from English financial reports."""

    def __init__(
        self,
        color_tolerance: float = 0.05,
        row_merge_tolerance: float = 2.0,
    ):
        self.color_tolerance = color_tolerance
        self.row_merge_tolerance = row_merge_tolerance

    def extract(self, page: fitz.Page) -> List[Table]:
        """Extract tables from a page.

        Returns a list of Table objects found on the page.
        """
        # 1. Detect color-alternating row backgrounds
        row_backgrounds = self._detect_row_backgrounds(page)
        if not row_backgrounds:
            return []

        # 2. Detect header rows
        header_rows = self._detect_header_rows(page, row_backgrounds)

        # 3. Build data rows from backgrounds
        data_rows = self._build_rows_from_backgrounds(page, row_backgrounds)

        # 4. Handle $ symbols
        data_rows = self._handle_dollar_signs(data_rows)

        # 5. Detect columns
        all_rows = header_rows + data_rows
        if not all_rows:
            return []

        columns = self._detect_columns(all_rows)

        # 6. Build table
        table = self._build_table(header_rows, data_rows, columns, page)

        return [table] if table else []

    def _detect_row_backgrounds(
        self, page: fitz.Page
    ) -> List[Tuple[float, float, str]]:
        """Detect color-alternating row backgrounds.

        Returns:
            Sorted list of (y0, y1, color_name) tuples.
            Each unique y range represents one row.
        """
        try:
            drawings = page.get_drawings()
        except Exception:
            return []

        row_rects: List[Tuple[float, float, str]] = []

        for d in drawings:
            fill = d.get("fill")
            rect = d.get("rect")
            if fill is None or rect is None:
                continue

            # Normalize fill color
            if isinstance(fill, (tuple, list)):
                key = tuple(round(c, 3) for c in fill)
            else:
                key = round(fill, 3)

            # Check for light blue or white
            if self._is_color_match(key, LIGHT_BLUE):
                row_rects.append((rect.y0, rect.y1, "blue"))
            elif self._is_color_match(key, WHITE):
                row_rects.append((rect.y0, rect.y1, "white"))

        if not row_rects:
            return []

        # Sort by y0
        row_rects.sort(key=lambda x: x[0])

        # Deduplicate by y range (same y0 and y1 = same row)
        unique_rows: List[Tuple[float, float, str]] = []
        seen_y_ranges: set = set()

        for y0, y1, color in row_rects:
            # Round to avoid floating point issues
            y_key = (round(y0, 1), round(y1, 1))
            if y_key not in seen_y_ranges:
                seen_y_ranges.add(y_key)
                unique_rows.append((y0, y1, color))

        return unique_rows

    def _is_color_match(self, color1: Tuple, color2: Tuple) -> bool:
        """Check if two colors match within tolerance."""
        if len(color1) != len(color2):
            return False
        return all(abs(c1 - c2) <= self.color_tolerance for c1, c2 in zip(color1, color2))

    def _detect_header_rows(
        self, page: fitz.Page, row_backgrounds: List[Tuple[float, float, str]]
    ) -> List[_RowData]:
        """Detect header rows above the colored data area.

        Uses font style (bold) to identify title rows vs column headers.
        Only column headers should be included in the table.
        """
        if not row_backgrounds:
            return []

        first_data_y = row_backgrounds[0][0]

        try:
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        except Exception:
            return []

        # Collect rows with font info
        rows_by_y: Dict[float, List[Dict]] = defaultdict(list)
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    
                    bbox = span.get("bbox", [0, 0, 0, 0])
                    y_center = (bbox[1] + bbox[3]) / 2.0
                    
                    # Only consider rows above the first colored row
                    if y_center >= first_data_y:
                        continue
                    
                    font = span.get("font", "")
                    is_bold = "Bold" in font
                    
                    rows_by_y[round(bbox[1], 0)].append({
                        "text": text,
                        "bbox": bbox,
                        "is_bold": is_bold,
                        "y_center": y_center,
                    })

        if not rows_by_y:
            return []

        # Group into rows
        header_rows: List[_RowData] = []
        for y_pos in sorted(rows_by_y.keys()):
            items = rows_by_y[y_pos]
            
            # Sort by x position
            items.sort(key=lambda x: x["bbox"][0])
            
            # Build words list in PyMuPDF format
            words = []
            for item in items:
                bbox = item["bbox"]
                words.append((bbox[0], bbox[1], bbox[2], bbox[3], item["text"]))
            
            if words:
                y0 = min(w[1] for w in words)
                y1 = max(w[3] for w in words)
                
                header_rows.append(_RowData(
                    words=words,
                    y0=y0,
                    y1=y1,
                    color=None,
                    is_header=True,
                ))

        # Filter: only include rows that are close to the data area
        # and contain column-like content
        column_header_rows = []
        for row in header_rows:
            # Check if this row is close to the data area (within 30pt)
            if first_data_y - row.y1 > 30:
                continue
            
            # Check if this row contains column-like content
            text = " ".join(w[4] for w in row.words)
            if self._is_column_header_text(text):
                column_header_rows.append(row)
            # Also include rows with multiple numeric-looking columns
            elif self._has_multiple_numeric_columns(row.words):
                column_header_rows.append(row)

        return column_header_rows

    def _is_column_header_text(self, text: str) -> bool:
        """Check if text looks like a column header (dates, periods, etc.)."""
        import re
        
        text_lower = text.lower()
        
        # Date patterns
        if re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)', text_lower):
            return True
        if re.search(r'\d{4}', text):  # Year like 2025, 2024
            return True
        
        # Financial column headers
        column_keywords = [
            "as of", "for the", "three months", "year ended",
            "quarter", "period", "2025", "2024", "2023",
        ]
        for keyword in column_keywords:
            if keyword in text_lower:
                return True
        
        return False

    def _has_multiple_numeric_columns(self, words: List[Tuple]) -> bool:
        """Check if a row has multiple numeric-looking columns."""
        numeric_count = 0
        for w in words:
            text = w[4].strip()
            if self._is_numeric(text) or text in ["$", "—", "-"]:
                numeric_count += 1
        return numeric_count >= 2

    def _group_words_into_rows(
        self, words: List[Tuple[float, float, float, float, str]]
    ) -> List[Dict[str, Any]]:
        """Group words into rows based on y position."""
        if not words:
            return []

        # Sort by y center, then x
        words_with_center = []
        for w in words:
            y_center = (w[1] + w[3]) / 2.0
            words_with_center.append((y_center, w))

        words_with_center.sort(key=lambda x: (x[0], x[1][0]))

        rows: List[Dict[str, Any]] = []
        current_row: Dict[str, Any] = {
            "words": [],
            "y0": float("inf"),
            "y1": float("-inf"),
        }
        current_y_center: Optional[float] = None

        row_tolerance = 5.0

        for y_center, word in words_with_center:
            if current_y_center is None:
                # First word
                current_row["words"].append(word)
                current_row["y0"] = min(current_row["y0"], word[1])
                current_row["y1"] = max(current_row["y1"], word[3])
                current_y_center = y_center
            elif abs(y_center - current_y_center) <= row_tolerance:
                # Same row
                current_row["words"].append(word)
                current_row["y0"] = min(current_row["y0"], word[1])
                current_row["y1"] = max(current_row["y1"], word[3])
                # Update running average
                n = len(current_row["words"])
                current_y_center = (current_y_center * (n - 1) + y_center) / n
            else:
                # New row
                if current_row["words"]:
                    current_row["words"].sort(key=lambda w: w[0])
                    rows.append(current_row)
                current_row = {
                    "words": [word],
                    "y0": word[1],
                    "y1": word[3],
                }
                current_y_center = y_center

        if current_row["words"]:
            current_row["words"].sort(key=lambda w: w[0])
            rows.append(current_row)

        return rows

    def _build_rows_from_backgrounds(
        self, page: fitz.Page, row_backgrounds: List[Tuple[float, float, str]]
    ) -> List[_RowData]:
        """Build data rows based on background colors.

        Uses text y-center to assign words to rows, which handles
        cases where text spans across background rectangle boundaries.
        """
        try:
            words = page.get_text("words")
        except Exception:
            return []

        # Calculate row boundaries from backgrounds
        # Each background defines a row center
        row_centers = [(y0 + y1) / 2.0 for y0, y1, _ in row_backgrounds]
        row_height = row_backgrounds[0][1] - row_backgrounds[0][0] if row_backgrounds else 10.0
        half_height = row_height / 2.0

        rows: List[_RowData] = []

        for i, (y0, y1, color) in enumerate(row_backgrounds):
            row_center = (y0 + y1) / 2.0

            # Collect words whose y-center is within this row's range
            row_words = []
            for w in words:
                w_center = (w[1] + w[3]) / 2.0
                # Check if word center is within row range (with tolerance)
                if y0 - 2.0 <= w_center <= y1 + 2.0:
                    row_words.append(w)

            if row_words:
                # Sort by x position
                row_words.sort(key=lambda w: w[0])
                rows.append(_RowData(
                    words=row_words,
                    y0=y0,
                    y1=y1,
                    color=color,
                    is_header=False,
                ))

        return rows

    def _handle_dollar_signs(self, rows: List[_RowData]) -> List[_RowData]:
        """Handle $ symbols, ensuring they pair with amounts.

        Rules:
        1. If $ is followed by a numeric token, merge them
        2. If $ is followed by a non-numeric token, move $ to nearest numeric column
        """
        for row in rows:
            words = row.words
            i = 0
            while i < len(words):
                text = words[i][4].strip()
                if text == "$":
                    if i + 1 < len(words):
                        next_text = words[i + 1][4].strip()
                        if self._is_numeric(next_text):
                            # Merge $ and amount
                            merged = self._merge_dollar_amount(words[i], words[i + 1])
                            words[i] = merged
                            words.pop(i + 1)
                            continue
                        else:
                            # Move $ to nearest numeric column
                            self._move_dollar_to_numeric_column(row, i)
                    i += 1
                else:
                    i += 1
        return rows

    def _merge_dollar_amount(
        self,
        dollar_word: Tuple,
        amount_word: Tuple,
    ) -> Tuple:
        """Merge $ symbol with the following amount.

        Preserves the original tuple format from PyMuPDF.
        """
        x0 = dollar_word[0]
        y0 = min(dollar_word[1], amount_word[1])
        x1 = amount_word[2]
        y1 = max(dollar_word[3], amount_word[3])
        text = "$" + amount_word[4].strip()

        # Preserve additional fields if present (block_no, line_no, word_no)
        if len(dollar_word) > 5:
            return (x0, y0, x1, y1, text) + dollar_word[5:]
        return (x0, y0, x1, y1, text)

    def _move_dollar_to_numeric_column(self, row: _RowData, dollar_idx: int):
        """Move a standalone $ to the nearest numeric column.

        This handles the case where $ is not immediately followed by an amount.
        """
        words = row.words
        dollar_word = words[dollar_idx]
        dollar_x = dollar_word[0]

        # Find the nearest numeric word to the right
        best_idx = None
        best_dist = float("inf")

        for i, w in enumerate(words):
            if i == dollar_idx:
                continue
            text = w[4].strip()
            if self._is_numeric(text) and w[0] > dollar_x:
                dist = w[0] - dollar_x
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i

        if best_idx is not None:
            # Save target position before pop shifts indices
            target_x = words[best_idx][0]
            dollar = words.pop(dollar_idx)
            # Adjust the $ x position to be just before the numeric word
            adjusted_dollar = (
                target_x - 5.0,
                dollar[1],
                dollar[2],
                dollar[3],
                dollar[4],
            )
            # After pop, best_idx shifted left if it was after dollar_idx
            insert_idx = best_idx if best_idx < dollar_idx else best_idx - 1
            words.insert(insert_idx, adjusted_dollar)

    def _detect_columns(
        self, rows: List[_RowData]
    ) -> List[Tuple[float, float]]:
        """Detect column boundaries using clustering approach.

        Similar to Chinese table extractor:
        1. Numeric tokens use right edge (x1) as anchor with high weight
        2. Text tokens use left edge (x0) as anchor with low weight
        3. Cluster anchors to find column boundaries

        Returns:
            List of (x_start, x_end) tuples defining column boundaries.
        """
        # Collect anchors from all rows
        # For numeric tokens: use x1 (right edge) for right-alignment
        # For text tokens: use x0 (left edge) for left-alignment
        numeric_anchors: List[float] = []
        text_anchors: List[float] = []

        for row in rows:
            for w in row.words:
                text = w[4].strip()
                x0 = w[0]
                x1 = w[2]

                if self._is_numeric(text):
                    # Numeric: use right edge for right-alignment
                    numeric_anchors.append(x1)
                elif text not in ["$", "—", "-", "(", ")"]:
                    # Text (not special chars): use left edge
                    text_anchors.append(x0)

        # Cluster numeric anchors first (these define data columns)
        numeric_clusters = self._cluster_positions(numeric_anchors, tolerance=15.0)

        # Filter: only keep clusters with enough support (at least 30% of rows)
        min_support = max(2, len(rows) * 0.3)
        strong_numeric_clusters = [
            c for c in numeric_clusters
            if c["count"] >= min_support
        ]

        if len(strong_numeric_clusters) >= 2:
            # Found multiple numeric columns - use these as column boundaries
            # Sort by position
            strong_numeric_clusters.sort(key=lambda c: c["x"])

            # Build columns
            columns = []

            # Label column: from leftmost text to first numeric cluster
            if text_anchors:
                label_x = min(text_anchors)
                first_numeric_x = strong_numeric_clusters[0]["x"]
                # Use midpoint between label area and first numeric column
                label_end = (label_x + first_numeric_x) / 2.0
                columns.append((label_x, label_end))

            # Data columns: each numeric cluster defines a column
            for i, cluster in enumerate(strong_numeric_clusters):
                x_start = columns[-1][1] if columns else cluster["x"] - 10
                if i + 1 < len(strong_numeric_clusters):
                    # Use midpoint between this and next cluster
                    x_end = (cluster["x"] + strong_numeric_clusters[i + 1]["x"]) / 2.0
                else:
                    x_end = max(w[2] for row in rows for w in row.words) + 10
                columns.append((x_start, x_end))

            return columns

        # Fallback: use simple gap detection
        all_x = [w[0] for row in rows for w in row.words] + [w[2] for row in rows for w in row.words]
        if not all_x:
            return []

        # Find large gaps (> 20.0pt)
        all_x_sorted = sorted(set(all_x))
        gaps = []
        for i in range(1, len(all_x_sorted)):
            gap = all_x_sorted[i] - all_x_sorted[i-1]
            if gap > 20.0:
                gaps.append((all_x_sorted[i-1], all_x_sorted[i]))

        if not gaps:
            return [(min(all_x), max(all_x))]

        # Build columns from gaps
        columns = []
        x_start = min(all_x)
        for x_left, x_right in gaps:
            x_end = (x_left + x_right) / 2.0
            columns.append((x_start, x_end))
            x_start = x_end
        columns.append((x_start, max(all_x)))

        return columns

    def _cluster_positions(
        self, positions: List[float], tolerance: float = 15.0
    ) -> List[dict]:
        """Cluster positions with given tolerance."""
        if not positions:
            return []

        clusters: List[dict] = []

        for pos in sorted(positions):
            target = None
            for cluster in clusters:
                if abs(pos - cluster["x"]) <= tolerance:
                    target = cluster
                    break

            if target is None:
                clusters.append({
                    "x": pos,
                    "count": 1,
                })
            else:
                # Update cluster center
                target["x"] = (target["x"] * target["count"] + pos) / (target["count"] + 1)
                target["count"] += 1

        return clusters

    def _build_table(
        self,
        header_rows: List[_RowData],
        data_rows: List[_RowData],
        columns: List[Tuple[float, float]],
        page: fitz.Page,
    ) -> Optional[Table]:
        """Build a Table object from rows and columns."""
        all_rows = header_rows + data_rows

        if not all_rows or not columns:
            return None

        cells: List[Cell] = []

        for row_idx, row in enumerate(all_rows):
            # Assign each word to a column
            # Normalize words to (x0, y0, x1, y1, text) format
            normalized_words = [
                (w[0], w[1], w[2], w[3], w[4]) for w in row.words
            ]
            row_cells = self._assign_words_to_columns(normalized_words, columns, row_idx)
            cells.extend(row_cells)

        if not cells:
            return None

        # Calculate bounding box
        x0 = min(c.bbox.x0 for c in cells)
        y0 = min(c.bbox.y0 for c in cells)
        x1 = max(c.bbox.x1 for c in cells)
        y1 = max(c.bbox.y1 for c in cells)

        row_count = len(all_rows)
        col_count = len(columns)

        return Table(
            bbox=BBox(x0, y0, x1, y1),
            rows=row_count,
            cols=col_count,
            cells=cells,
            confidence=0.85,
            source="english_color_based",
        )

    def _assign_words_to_columns(
        self,
        words: List[Tuple[float, float, float, float, str]],
        columns: List[Tuple[float, float]],
        row_idx: int,
    ) -> List[Cell]:
        """Assign words to columns based on x position.

        Args:
            words: List of (x0, y0, x1, y1, text) tuples
            columns: List of (x_start, x_end) column boundaries
            row_idx: Row index for the cells
        """
        # Group words by column
        column_words: Dict[int, List[Tuple]] = defaultdict(list)

        for word in words:
            x0, y0, x1, y1, text = word
            x_center = (x0 + x1) / 2.0

            # Find which column this word belongs to
            col_idx = self._find_column(x_center, columns)
            column_words[col_idx].append(word)

        # Create cells
        cells: List[Cell] = []
        for col_idx, words_in_col in column_words.items():
            if not words_in_col:
                continue

            # Sort words by x position
            words_in_col.sort(key=lambda w: w[0])

            # Combine text
            text = " ".join(w[4].strip() for w in words_in_col if w[4].strip())
            if not text:
                continue

            # Calculate bounding box
            x0 = min(w[0] for w in words_in_col)
            y0 = min(w[1] for w in words_in_col)
            x1 = max(w[2] for w in words_in_col)
            y1 = max(w[3] for w in words_in_col)

            cells.append(Cell(
                text=text,
                row_index=row_idx,
                col_index=col_idx,
                bbox=BBox(x0, y0, x1, y1),
            ))

        return cells

    def _find_column(self, x: float, columns: List[Tuple[float, float]]) -> int:
        """Find which column an x position belongs to."""
        for i, (x_start, x_end) in enumerate(columns):
            if x <= x_end:
                return i
        return len(columns) - 1

    def _is_numeric(self, text: str) -> bool:
        """Check if text represents a numeric value."""
        import re

        stripped = text.strip()
        if not stripped:
            return False

        # Remove common prefixes/suffixes
        normalized = stripped
        if normalized.startswith("$"):
            normalized = normalized[1:]
        if normalized.startswith("(") and normalized.endswith(")"):
            normalized = normalized[1:-1]
        if normalized.endswith("%"):
            normalized = normalized[:-1]

        # Remove commas and spaces
        normalized = normalized.replace(",", "").replace(" ", "")

        # Check if it's a number
        try:
            float(normalized)
            return True
        except ValueError:
            return False
