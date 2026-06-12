"""Template-driven table builder for complex header layouts.

Loads JSON template definitions from a directory and provides a generic
:class:`TemplateEngine` that can classify, validate, and build tables
from text-alignment regions using zone-based column mapping.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .models import BBox, Cell, Table

if TYPE_CHECKING:
    import fitz

    from .table_extractor import TableExtractor


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ZoneKeywordRule:
    """Validation rule for a single zone."""
    mode: str = "any"  # "any", "contains", "exact"
    keywords: List[str] = field(default_factory=list)
    exact: Optional[str] = None


@dataclass
class ValidationConfig:
    min_header_rows: int = 3
    zone_keywords: Dict[int, ZoneKeywordRule] = field(default_factory=dict)
    group_zone: Optional[Tuple[int, int]] = None
    group_keywords: List[str] = field(default_factory=list)


@dataclass
class MatchConfig:
    min_rows: int = 4
    header_scan_rows: int = 3
    required_keyword: str = ""
    required_keywords: List[str] = field(default_factory=list)
    min_keyword_hits: int = 5


@dataclass
class HeaderCellDef:
    col: int
    text: str
    rowspan: int = 1
    colspan: int = 1


@dataclass
class HeaderRowDef:
    row: int
    cells: List[HeaderCellDef] = field(default_factory=list)


@dataclass
class BodyConfig:
    label_col: int = 0
    skip_first_token: bool = True
    column0_remap_to: Optional[int] = None
    mode: str = "zone"  # "zone" or "guide"
    header_row_count: Optional[int] = None  # override auto-detection


@dataclass
class TableTemplateConfig:
    """Parsed representation of a single table template JSON."""
    name: str = ""
    description: str = ""
    confidence: float = 0.8
    match: MatchConfig = field(default_factory=MatchConfig)
    zones: List[Tuple[float, float]] = field(default_factory=list)
    header_rows: List[HeaderRowDef] = field(default_factory=list)
    body: BodyConfig = field(default_factory=BodyConfig)
    validation: Optional[ValidationConfig] = None

    @staticmethod
    def load(path: Path) -> TableTemplateConfig:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return TableTemplateConfig.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TableTemplateConfig:
        match_data = data.get("match", {})
        match = MatchConfig(
            min_rows=match_data.get("min_rows", 4),
            header_scan_rows=match_data.get("header_scan_rows", 3),
            required_keyword=match_data.get("required_keyword", ""),
            required_keywords=match_data.get("required_keywords", []),
            min_keyword_hits=match_data.get("min_keyword_hits", 5),
        )

        zones = [tuple(z) for z in data.get("zones", [])]

        header_rows = []
        for hr_data in data.get("header_rows", []):
            cells = [
                HeaderCellDef(
                    col=c["col"],
                    text=c["text"],
                    rowspan=c.get("rowspan", 1),
                    colspan=c.get("colspan", 1),
                )
                for c in hr_data.get("cells", [])
            ]
            header_rows.append(HeaderRowDef(row=hr_data["row"], cells=cells))

        body_data = data.get("body", {})
        body = BodyConfig(
            label_col=body_data.get("label_col", 0),
            skip_first_token=body_data.get("skip_first_token", True),
            column0_remap_to=body_data.get("column0_remap_to"),
            mode=body_data.get("mode", "zone"),
            header_row_count=body_data.get("header_row_count"),
        )

        validation = None
        if "validation" in data:
            val_data = data["validation"]
            zone_kw = {}
            for zone_idx_str, rule_raw in val_data.get("zone_keywords", {}).items():
                zone_idx = int(zone_idx_str)
                if isinstance(rule_raw, list):
                    zone_kw[zone_idx] = ZoneKeywordRule(mode="any", keywords=rule_raw)
                elif isinstance(rule_raw, dict):
                    if "exact" in rule_raw:
                        zone_kw[zone_idx] = ZoneKeywordRule(mode="exact", exact=rule_raw["exact"])
                    elif "contains" in rule_raw:
                        zone_kw[zone_idx] = ZoneKeywordRule(mode="contains", keywords=rule_raw["contains"])

            gz = val_data.get("group_zone")
            validation = ValidationConfig(
                min_header_rows=val_data.get("min_header_rows", 3),
                zone_keywords=zone_kw,
                group_zone=tuple(gz) if gz else None,
                group_keywords=val_data.get("group_keywords", []),
            )

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            confidence=data.get("confidence", 0.8),
            match=match,
            zones=zones,
            header_rows=header_rows,
            body=body,
            validation=validation,
        )


def load_templates(directory: Path) -> List[TableTemplateConfig]:
    """Load all template JSON files from *directory*."""
    templates = []
    if not directory.is_dir():
        return templates
    for path in sorted(directory.glob("*.json")):
        templates.append(TableTemplateConfig.load(path))
    return templates


# ---------------------------------------------------------------------------
# Template engine
# ---------------------------------------------------------------------------

class TemplateEngine:
    """Generic zone-based table builder driven by :class:`TableTemplateConfig`."""

    def __init__(self, extractor: "TableExtractor") -> None:
        self._extractor = extractor

    def classify(
        self,
        region_rows: List[dict],
        templates: List[TableTemplateConfig],
    ) -> Optional[TableTemplateConfig]:
        """Return the first template whose keyword match criteria are met."""
        for template in templates:
            if self._matches_keywords(region_rows, template.match):
                return template
        return None

    def build_table(
        self,
        page: "fitz.Page",
        region_rows: List[dict],
        template: TableTemplateConfig,
    ) -> Optional[Table]:
        """Build a Table from *region_rows* using *template*, or None on validation failure."""
        if len(template.zones) < 2:
            return None

        table_bbox = self._extractor._rows_bbox(region_rows)
        width = max(table_bbox.x1 - table_bbox.x0, 1.0)
        zones = template.zones

        header_rows, header_words = self._collect_header_rows(
            page, table_bbox, region_rows
        )

        if template.validation and not self._validate_zones(
            header_words, table_bbox, zones, template.validation
        ):
            return None

        cells: List[Cell] = self._build_header_cells(
            header_rows, table_bbox, width, zones, template.header_rows
        )

        header_row_count = template.body.header_row_count
        if header_row_count is None:
            header_row_count = max((h.row for h in template.header_rows), default=-1) + 1
        if template.body.mode == "guide":
            body_rows = region_rows[header_row_count:]
            guides = self._extractor._infer_column_guides(body_rows, table_bbox)
            guides = self._extractor._compact_column_guides(body_rows, guides)
            if len(guides) >= 2:
                _, _, body_cells = self._extractor._build_text_alignment_table(
                    body_rows, guides, table_bbox
                )
                for c in body_cells:
                    c.row_index += header_row_count
                    c.rowspan = 1
                    c.colspan = 1
                body_cells = self._consolidate_body_rows(
                    body_cells, body_rows, header_row_count
                )
                cells.extend(body_cells)
        else:
            cells.extend(
                self._build_body_cells(
                    region_rows, table_bbox, width, zones, template.header_rows, template.body
                )
            )

        if not cells:
            return None

        return Table(
            bbox=table_bbox,
            rows=max((c.row_index for c in cells), default=0) + 1,
            cols=len(zones),
            cells=cells,
            confidence=template.confidence,
            source=f"text_alignment:{template.name}_template",
        )

    # ------------------------------------------------------------------
    # Keyword matching
    # ------------------------------------------------------------------

    @staticmethod
    def _matches_keywords(
        region_rows: List[dict], match: MatchConfig
    ) -> bool:
        if len(region_rows) < match.min_rows:
            return False

        scan_rows = region_rows[: match.header_scan_rows]
        header_text = "".join(
            token["text"]
            for row in scan_rows
            for token in row.get("tokens", [])
            if token.get("text")
        )

        if match.required_keyword and match.required_keyword not in header_text:
            return False

        if match.required_keywords:
            hits = sum(1 for kw in match.required_keywords if kw in header_text)
            if hits < match.min_keyword_hits:
                return False

        return True

    # ------------------------------------------------------------------
    # Header row collection (clip above table, extract text rows)
    # ------------------------------------------------------------------

    def _collect_header_rows(
        self,
        page: "fitz.Page",
        table_bbox: BBox,
        region_rows: List[dict],
    ) -> Tuple[List[dict], List[tuple]]:
        """Collect text rows and raw words from the header band above the table."""
        import fitz

        header_bottom = max(row["y1"] for row in region_rows[:3])
        clip = fitz.Rect(
            table_bbox.x0 - 10.0,
            max(0.0, region_rows[0]["y0"] - 40.0),
            table_bbox.x1 + 10.0,
            header_bottom + 2.0,
        )
        words = page.get_text("words", clip=clip)
        rows = self._extractor._collect_text_rows(words)
        header_rows = [row for row in rows if row["y1"] <= header_bottom + 2.0]
        header_words = [
            w for w in words if w[3] <= header_bottom + 2.0
        ]
        return header_rows, header_words

    # ------------------------------------------------------------------
    # Zone validation
    # ------------------------------------------------------------------

    def _validate_zones(
        self,
        header_words: List[tuple],
        table_bbox: BBox,
        zones: List[Tuple[float, float]],
        validation: ValidationConfig,
    ) -> bool:
        if len(header_words) < 2:
            return False

        width = max(table_bbox.x1 - table_bbox.x0, 1.0)
        zone_texts: Dict[int, List[str]] = defaultdict(list)
        group_texts: List[str] = []

        for w in header_words:
            # words tuple: (x0, y0, x1, y1, text, block, line, word)
            text = w[4].strip()
            if not text:
                continue
            x_center = (w[0] + w[2]) / 2.0
            normalized_x = (x_center - table_bbox.x0) / width
            zone_index = self._zone_index(normalized_x, zones)
            zone_texts[zone_index].append(text)
            if validation.group_zone:
                lo, hi = validation.group_zone
                if lo <= zone_index <= hi:
                    group_texts.append(text)

        zone_joined = {
            idx: "".join(texts).replace(" ", "")
            for idx, texts in zone_texts.items()
        }
        group_joined = "".join(group_texts).replace(" ", "")

        for zone_idx, rule in validation.zone_keywords.items():
            zone_text = zone_joined.get(zone_idx, "")
            if rule.mode == "any":
                if not any(kw in zone_text for kw in rule.keywords):
                    return False
            elif rule.mode == "contains":
                if not all(kw in zone_text for kw in rule.keywords):
                    return False
            elif rule.mode == "exact":
                if zone_text != rule.exact:
                    return False

        if validation.group_keywords:
            if not all(kw in group_joined for kw in validation.group_keywords):
                return False

        return True

    # ------------------------------------------------------------------
    # Header cell building
    # ------------------------------------------------------------------

    def _build_header_cells(
        self,
        header_rows: List[dict],
        table_bbox: BBox,
        width: float,
        zones: List[Tuple[float, float]],
        header_defs: List[HeaderRowDef],
    ) -> List[Cell]:
        if not header_rows:
            return []

        header_top = min(row["y0"] for row in header_rows)
        header_bottom = max(row["y1"] for row in header_rows)

        # Find the top-most row to determine split between upper/lower header
        top_group_row = min(
            header_rows,
            key=lambda row: min(token["y0"] for token in row.get("tokens", [])),
        )
        lower_header_top = min(
            row["y0"] for row in header_rows if row is not top_group_row
        ) if len(header_rows) > 1 else header_top

        cells: List[Cell] = []
        for hdr_def in header_defs:
            row_idx = hdr_def.row
            is_top_row = (row_idx == 0)
            for cell_def in hdr_def.cells:
                col = cell_def.col
                if col >= len(zones):
                    continue
                left_norm, right_norm = zones[col]
                left = table_bbox.x0 + width * left_norm
                right = table_bbox.x0 + width * right_norm

                # Handle colspan: extend right edge to end of spanned zones
                if cell_def.colspan > 1:
                    end_col = min(col + cell_def.colspan, len(zones)) - 1
                    right = table_bbox.x0 + width * zones[end_col][1]

                y0 = header_top if is_top_row else lower_header_top
                cells.append(
                    Cell(
                        text=cell_def.text,
                        row_index=row_idx,
                        col_index=col,
                        bbox=BBox(left, y0, right, header_bottom),
                        rowspan=cell_def.rowspan,
                        colspan=cell_def.colspan,
                    )
                )

        return cells

    # ------------------------------------------------------------------
    # Body cell building
    # ------------------------------------------------------------------

    def _build_body_cells(
        self,
        region_rows: List[dict],
        table_bbox: BBox,
        width: float,
        zones: List[Tuple[float, float]],
        header_defs: List[HeaderRowDef],
        body: BodyConfig,
    ) -> List[Cell]:
        header_row_count = max((h.row for h in header_defs), default=-1) + 1
        body_rows = region_rows[header_row_count:]
        cells: List[Cell] = []

        for row_offset, row in enumerate(body_rows, start=header_row_count):
            tokens = row.get("tokens", [])
            if not tokens:
                continue

            sorted_tokens = sorted(tokens, key=lambda t: t["x0"])

            # Label cell
            if body.skip_first_token and sorted_tokens:
                label_token = sorted_tokens[0]
                label_text = label_token["text"].strip()
                if label_text:
                    cells.append(
                        Cell(
                            text=label_text,
                            row_index=row_offset,
                            col_index=body.label_col,
                            bbox=BBox(
                                label_token["x0"],
                                label_token["y0"],
                                label_token["x1"],
                                label_token["y1"],
                            ),
                        )
                    )

            # Value tokens → zone mapping
            value_tokens = (
                sorted_tokens[1:]
                if body.skip_first_token
                else sorted_tokens
            )

            zone_tokens: Dict[int, List[dict]] = defaultdict(list)
            for token in value_tokens:
                if not token.get("text", "").strip():
                    continue
                x_center = (token["x0"] + token["x1"]) / 2.0
                normalized_x = (x_center - table_bbox.x0) / width
                col_index = self._zone_index(normalized_x, zones)

                # Remap col 0 if configured
                if col_index == 0 and body.column0_remap_to is not None:
                    col_index = body.column0_remap_to

                zone_tokens[col_index].append(token)

            for col_index, tokens_in_zone in sorted(zone_tokens.items()):
                text = " ".join(
                    t["text"].strip() for t in tokens_in_zone if t["text"].strip()
                )
                if not text:
                    continue
                cells.append(
                    Cell(
                        text=text,
                        row_index=row_offset,
                        col_index=col_index,
                        bbox=BBox(
                            min(t["x0"] for t in tokens_in_zone),
                            min(t["y0"] for t in tokens_in_zone),
                            max(t["x1"] for t in tokens_in_zone),
                            max(t["y1"] for t in tokens_in_zone),
                        ),
                    )
                )

        return cells

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Body row consolidation
    # ------------------------------------------------------------------

    @staticmethod
    def _consolidate_body_rows(
        cells: List[Cell],
        body_rows: List[dict] | None = None,
        row_offset: int = 0,
    ) -> List[Cell]:
        """Consolidate wrapped body rows using column structure.

        Three-pass approach:

        Pass 1 — Split multi-line label-only rows: when a label-only
        row contains tokens at different y-positions, split the first
        y-group into the previous data row's col 0 and keep the rest
        as a new label cell.

        Pass 2 — Assign pending labels: data rows missing col 0 get
        the most recent label-only row's text as their label.

        Pass 3 — Merge trailing labels: when a row has col 0 but the
        previous row does not, merge this row's col 0 into the
        previous row's col 0.
        """
        if not cells:
            return cells

        row_cols: dict[int, set[int]] = defaultdict(set)
        row_cells: dict[int, dict[int, Cell]] = defaultdict(dict)
        for c in cells:
            row_cols[c.row_index].add(c.col_index)
            row_cells[c.row_index][c.col_index] = c

        sorted_rows = sorted(row_cols.keys())
        if not sorted_rows:
            return cells

        def _y_split(row_idx: int) -> tuple[str, str | None]:
            """Split col 0 text by y-position groups."""
            if body_rows is None:
                return row_cells[row_idx][0].text, None
            local_idx = row_idx - row_offset
            if local_idx < 0 or local_idx >= len(body_rows):
                return row_cells[row_idx][0].text, None
            tokens = [
                t for t in body_rows[local_idx].get("tokens", [])
                if t["text"].strip()
            ]
            if len(tokens) < 2:
                return row_cells[row_idx][0].text, None
            sorted_t = sorted(tokens, key=lambda t: t["y0"])
            groups: list[list[dict]] = [[sorted_t[0]]]
            for token in sorted_t[1:]:
                if token["y0"] - groups[-1][-1]["y0"] > 8.0:
                    groups.append([])
                groups[-1].append(token)
            if len(groups) < 2:
                return row_cells[row_idx][0].text, None
            first = " ".join(t["text"].strip() for t in groups[0] if t["text"].strip())
            rest = " ".join(
                t["text"].strip()
                for g in groups[1:]
                for t in g
                if t["text"].strip()
            )
            return first, rest or None

        rows_to_delete: set[int] = set()

        # Pass 1: Split multi-line label-only rows.
        for row_idx in sorted_rows:
            if row_idx in rows_to_delete:
                continue
            cols = row_cols[row_idx]
            if not (0 in cols and not any(c > 0 for c in cols)):
                continue
            first, rest = _y_split(row_idx)
            if rest is None:
                continue
            # Merge first group into previous row's col 0.
            for prev_idx in reversed(sorted_rows):
                if prev_idx >= row_idx:
                    continue
                if prev_idx in rows_to_delete:
                    continue
                if any(c > 0 for c in row_cols[prev_idx]):
                    prev_label = row_cells[prev_idx].get(0)
                    if prev_label is not None:
                        prev_label.text = (prev_label.text + " " + first).strip()
                    break
            # Replace this row's col 0 with the rest.
            row_cells[row_idx][0].text = rest

        # Pass 2: Assign pending labels to data rows missing col 0.
        pending_label: str | None = None
        pending_row: int | None = None
        pass2_cells: set[tuple[int, int]] = set()  # cells created by Pass 2
        for row_idx in sorted_rows:
            if row_idx in rows_to_delete:
                continue
            cols = row_cols[row_idx]
            has_col0 = 0 in cols
            has_other = any(c > 0 for c in cols)

            if has_col0 and not has_other:
                pending_label = row_cells[row_idx][0].text
                pending_row = row_idx

            elif has_other and not has_col0:
                if pending_label is not None:
                    new_label = Cell(
                        text=pending_label,
                        row_index=row_idx,
                        col_index=0,
                        bbox=row_cells[pending_row][0].bbox if pending_row else BBox(0, 0, 0, 0),
                    )
                    row_cells[row_idx][0] = new_label
                    row_cols[row_idx].add(0)
                    rows_to_delete.add(pending_row)
                    pass2_cells.add((row_idx, 0))
                    pending_label = None
                    pending_row = None

            elif has_col0 and has_other:
                if pending_label is not None:
                    label_cell = row_cells[row_idx][0]
                    label_cell.text = (pending_label + " " + label_cell.text).strip()
                    rows_to_delete.add(pending_row)
                    pending_label = None
                    pending_row = None

        merged_away: set[tuple[int, int]] = set()

        # Pass 3: Merge trailing labels into the previous data row.
        # When a row has col 0 and the previous row has data (other
        # columns), the col 0 text is a label continuation and should
        # be merged into the previous row's col 0.  Skip cells
        # created by Pass 2 (they are real labels, not continuations).
        for row_idx in sorted_rows:
            if row_idx in rows_to_delete:
                continue
            if (row_idx, 0) in pass2_cells:
                continue  # Created by Pass 2; keep as-is.
            cols = row_cols[row_idx]
            if 0 not in cols:
                continue
            has_other = any(c > 0 for c in cols)
            # Find previous row.
            prev_idx = None
            for pi in reversed(sorted_rows):
                if pi < row_idx and pi not in rows_to_delete:
                    prev_idx = pi
                    break
            if prev_idx is None:
                continue
            prev_cols = row_cols[prev_idx]
            prev_has_other = any(c > 0 for c in prev_cols)
            if not prev_has_other:
                continue  # Previous row is label-only; skip.
            # Previous row has data — merge this row's col 0 into it.
            label_text = row_cells[row_idx][0].text
            if 0 in prev_cols:
                prev_label = row_cells[prev_idx][0]
                prev_label.text = (prev_label.text + " " + label_text).strip()
            else:
                new_label = Cell(
                    text=label_text,
                    row_index=prev_idx,
                    col_index=0,
                    bbox=row_cells[row_idx][0].bbox,
                )
                row_cells[prev_idx][0] = new_label
                row_cols[prev_idx].add(0)
            # Remove col 0 from this row.
            del row_cells[row_idx][0]
            row_cols[row_idx].discard(0)
            merged_away.add((row_idx, 0))

        result: List[Cell] = []
        for c in cells:
            if c.row_index not in rows_to_delete and (c.row_index, c.col_index) not in merged_away:
                result.append(c)
        for row_idx, col_map in row_cells.items():
            if row_idx in rows_to_delete:
                continue
            if 0 in col_map:
                cell = col_map[0]
                if cell not in result:
                    result.append(cell)

        # Filter out empty rows (rows with no non-empty text).
        occupied_rows = {c.row_index for c in result if c.text.strip()}
        result = [c for c in result if c.row_index in occupied_rows]

        result.sort(key=lambda c: (c.row_index, c.col_index))
        return result

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _zone_index(normalized_x: float, zones: List[Tuple[float, float]]) -> int:
        for idx, (left, right) in enumerate(zones):
            if left <= normalized_x < right:
                return idx
        return len(zones) - 1
