# tools/pdfium_probe/scripts/behavioral_contract.py
"""Behavioral comparator and semantic contract for Markdown and table structures."""

from collections import Counter
from html.parser import HTMLParser
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

_IMAGE_OR_SEAL_RE = re.compile(r"(!\[(?P<alt>[^\]]*)\]\((?P<target>[^\)]*)\))")
_TABLE_BLOCK_RE = re.compile(r"(<table\b[^>]*>.*?</table>)", re.DOTALL | re.IGNORECASE)

ALLOWED_CATEGORIES = (
    "page_type",
    "reading_order",
    "table_count",
    "table_structure",
    "table_text",
    "body_text",
    "resource_path",
    "unclassified",
)


def normalize_markdown(
    markdown: str, resource_roots: Optional[Mapping[str, str]] = None
) -> str:
    """Normalize markdown by converting line endings and replacing resource roots in URLs."""
    if not markdown:
        return ""

    # 1. Convert CRLF and CR to LF
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Replace resource roots ONLY in image/seal URLs
    if resource_roots:
        sorted_roots = sorted(
            resource_roots.items(), key=lambda kv: len(kv[0]), reverse=True
        )

        def _replace_image_url(match: re.Match) -> str:
            alt = match.group("alt")
            target = match.group("target")
            parts = target.strip().split(None, 1)
            if not parts:
                return match.group(0)
            url = parts[0]
            rest = f" {parts[1]}" if len(parts) > 1 else ""

            norm_url = url.replace("\\", "/")
            for root, repl in sorted_roots:
                norm_root = root.replace("\\", "/")
                if norm_url.startswith(norm_root):
                    remainder = norm_url[len(norm_root) :]
                    norm_repl = repl.replace("\\", "/")
                    url = norm_repl + remainder
                    break

            return f"![{alt}]({url}{rest})"

        text = _IMAGE_OR_SEAL_RE.sub(_replace_image_url, text)

    # 3. Unified trailing newline: non-empty text ends with exactly one newline
    stripped = text.rstrip("\n")
    if not stripped:
        return ""
    return stripped + "\n"


class _TableHTMLParser(HTMLParser):
    """HTML table parser preserving raw cell text and spans."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[Dict[str, Any]] = []
        self._current_table: Optional[Dict[str, Any]] = None
        self._current_row: Optional[List[Dict[str, Any]]] = None
        self._current_cell: Optional[Dict[str, Any]] = None
        self._cell_text_buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        if tag_lower == "table":
            self._current_table = {"raw_rows": []}
        elif tag_lower == "tr":
            if self._current_table is not None:
                self._current_row = []
        elif tag_lower in ("td", "th"):
            if self._current_row is not None:
                attr_dict = {k.lower(): (v or "") for k, v in attrs}
                try:
                    rowspan = int(attr_dict.get("rowspan", 1))
                except ValueError:
                    rowspan = 1
                try:
                    colspan = int(attr_dict.get("colspan", 1))
                except ValueError:
                    colspan = 1
                if rowspan < 1:
                    rowspan = 1
                if colspan < 1:
                    colspan = 1
                self._current_cell = {
                    "rowspan": rowspan,
                    "colspan": colspan,
                }
                self._cell_text_buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._cell_text_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("td", "th"):
            if self._current_cell is not None and self._current_row is not None:
                self._current_cell["text"] = "".join(self._cell_text_buffer)
                self._current_row.append(self._current_cell)
                self._current_cell = None
                self._cell_text_buffer = []
        elif tag_lower == "tr":
            if self._current_table is not None and self._current_row is not None:
                self._current_table["raw_rows"].append(self._current_row)
                self._current_row = None
        elif tag_lower == "table":
            if self._current_table is not None:
                self.tables.append(self._current_table)
                self._current_table = None


def _compute_table_grid(
    raw_rows: List[List[Dict[str, Any]]],
    declared_rows: Optional[int] = None,
    declared_cols: Optional[int] = None,
) -> Tuple[
    int,
    int,
    List[Dict[str, Any]],
    Dict[Tuple[int, int], int],
    List[Dict[str, Any]],
]:
    """Compute grid coordinates, literal cells, and occupancy from raw table rows."""
    cells: List[Dict[str, Any]] = []
    occupancy: Dict[Tuple[int, int], int] = {}
    unclassified: List[Dict[str, Any]] = []

    for r_idx, row in enumerate(raw_rows):
        c_idx = 0
        for cell_data in row:
            while (r_idx, c_idx) in occupancy:
                c_idx += 1
            rs = cell_data.get("rowspan", 1)
            cs = cell_data.get("colspan", 1)
            txt = cell_data.get("text", "")
            cell_idx = len(cells)
            cell = {
                "row": r_idx,
                "col": c_idx,
                "rowspan": rs,
                "colspan": cs,
                "text": txt,
            }
            cells.append(cell)

            for dr in range(rs):
                for dc in range(cs):
                    slot = (r_idx + dr, c_idx + dc)
                    if slot in occupancy:
                        unclassified.append(
                            {
                                "type": "duplicate_occupancy",
                                "slot": slot,
                                "existing_cell_index": occupancy[slot],
                                "conflicting_cell_index": cell_idx,
                            }
                        )
                    occupancy[slot] = cell_idx
            c_idx += cs

    calc_rows = (
        max(c["row"] + c["rowspan"] for c in cells) if cells else len(raw_rows)
    )
    calc_cols = max(c["col"] + c["colspan"] for c in cells) if cells else 0
    total_rows = declared_rows if declared_rows is not None else calc_rows
    total_cols = declared_cols if declared_cols is not None else calc_cols

    for idx, c in enumerate(cells):
        for dr in range(c["rowspan"]):
            for dc in range(c["colspan"]):
                r = c["row"] + dr
                col = c["col"] + dc
                if r >= total_rows or col >= total_cols or r < 0 or col < 0:
                    unclassified.append(
                        {
                            "type": "out_of_bounds",
                            "cell_index": idx,
                            "slot": (r, col),
                            "bounds": (total_rows, total_cols),
                        }
                    )

    for r in range(total_rows):
        for col in range(total_cols):
            if (r, col) not in occupancy:
                unclassified.append(
                    {
                        "type": "occupancy_gap",
                        "slot": (r, col),
                    }
                )

    return total_rows, total_cols, cells, occupancy, unclassified


def _process_explicit_table(
    table_dict: Mapping[str, Any]
) -> Tuple[
    int,
    int,
    List[Dict[str, Any]],
    Dict[Tuple[int, int], int],
    List[Dict[str, Any]],
]:
    """Compute occupancy and check anomalies for an explicitly declared table mapping."""
    unclassified: List[Dict[str, Any]] = []
    declared_rows = table_dict.get("rows")
    declared_cols = table_dict.get("cols")
    raw_cells = table_dict.get("cells", [])

    cells: List[Dict[str, Any]] = []
    occupancy: Dict[Tuple[int, int], int] = {}

    for idx, c in enumerate(raw_cells):
        r = c.get("row", c.get("row_index", 0))
        col = c.get("col", c.get("col_index", 0))
        rs = c.get("rowspan", 1)
        cs = c.get("colspan", 1)
        txt = c.get("text", "")
        cell_obj = {
            "row": r,
            "col": col,
            "rowspan": rs,
            "colspan": cs,
            "text": txt,
        }
        cells.append(cell_obj)

        for dr in range(rs):
            for dc in range(cs):
                slot = (r + dr, col + dc)
                if slot in occupancy:
                    unclassified.append(
                        {
                            "type": "duplicate_occupancy",
                            "slot": slot,
                            "existing_cell_index": occupancy[slot],
                            "conflicting_cell_index": idx,
                        }
                    )
                occupancy[slot] = idx

    calc_rows = (
        max(c["row"] + c["rowspan"] for c in cells)
        if cells
        else (declared_rows or 0)
    )
    calc_cols = (
        max(c["col"] + c["colspan"] for c in cells)
        if cells
        else (declared_cols or 0)
    )
    total_rows = declared_rows if declared_rows is not None else calc_rows
    total_cols = declared_cols if declared_cols is not None else calc_cols

    for idx, c in enumerate(cells):
        for dr in range(c["rowspan"]):
            for dc in range(c["colspan"]):
                r = c["row"] + dr
                col = c["col"] + dc
                if r >= total_rows or col >= total_cols or r < 0 or col < 0:
                    unclassified.append(
                        {
                            "type": "out_of_bounds",
                            "cell_index": idx,
                            "slot": (r, col),
                            "bounds": (total_rows, total_cols),
                        }
                    )

    for r in range(total_rows):
        for col in range(total_cols):
            if (r, col) not in occupancy:
                unclassified.append(
                    {
                        "type": "occupancy_gap",
                        "slot": (r, col),
                    }
                )

    return total_rows, total_cols, cells, occupancy, unclassified


def parse_markdown_semantics(markdown: str) -> Dict[str, Any]:
    """Parse Markdown to extract tables, reading order, body text, and anomalies."""
    tables: List[Dict[str, Any]] = []
    reading_order: List[Dict[str, Any]] = []
    body_texts: List[str] = []
    resources: List[str] = []
    unclassified: List[Dict[str, Any]] = []

    last_pos = 0
    elem_idx = 0

    for match in _TABLE_BLOCK_RE.finditer(markdown):
        # Process text preceding the table
        text_before = markdown[last_pos : match.start()]
        if text_before:
            paragraphs = re.split(r"\n\s*\n", text_before)
            for p in paragraphs:
                p_str = p.strip()
                if not p_str:
                    continue
                if p_str == "---":
                    reading_order.append({"type": "separator", "order": elem_idx})
                    elem_idx += 1
                elif _IMAGE_OR_SEAL_RE.match(p_str):
                    m = _IMAGE_OR_SEAL_RE.match(p_str)
                    alt = m.group("alt")
                    target = m.group("target")
                    parts = target.strip().split(None, 1)
                    url = parts[0] if parts else ""
                    kind = "seal" if "seal" in alt.lower() else "image"
                    reading_order.append(
                        {"type": kind, "order": elem_idx, "path": url}
                    )
                    resources.append(url)
                    elem_idx += 1
                else:
                    reading_order.append(
                        {"type": "text", "order": elem_idx, "text": p_str}
                    )
                    body_texts.append(p_str)
                    elem_idx += 1

        # Process the HTML table
        table_html = match.group(1)
        parser = _TableHTMLParser()
        parser.feed(table_html)
        for tbl in parser.tables:
            r, c, cells, occ, unc = _compute_table_grid(tbl["raw_rows"])
            sorted_cells = sorted(cells, key=lambda cl: (cl["row"], cl["col"]))
            table_dict = {
                "rows": r,
                "cols": c,
                "cells": sorted_cells,
                "occupancy": {f"{slot[0]},{slot[1]}": v for slot, v in occ.items()},
            }
            tables.append(table_dict)
            unclassified.extend(unc)
            reading_order.append(
                {
                    "type": "table",
                    "order": elem_idx,
                    "table": {
                        "rows": r,
                        "cols": c,
                        "cells": sorted_cells,
                    },
                }
            )
            elem_idx += 1

        last_pos = match.end()

    # Process remaining text after the last table
    text_remaining = markdown[last_pos:]
    if text_remaining:
        paragraphs = re.split(r"\n\s*\n", text_remaining)
        for p in paragraphs:
            p_str = p.strip()
            if not p_str:
                continue
            if p_str == "---":
                reading_order.append({"type": "separator", "order": elem_idx})
                elem_idx += 1
            elif _IMAGE_OR_SEAL_RE.match(p_str):
                m = _IMAGE_OR_SEAL_RE.match(p_str)
                alt = m.group("alt")
                target = m.group("target")
                parts = target.strip().split(None, 1)
                url = parts[0] if parts else ""
                kind = "seal" if "seal" in alt.lower() else "image"
                reading_order.append(
                    {"type": kind, "order": elem_idx, "path": url}
                )
                resources.append(url)
                elem_idx += 1
            else:
                reading_order.append(
                    {"type": "text", "order": elem_idx, "text": p_str}
                )
                body_texts.append(p_str)
                elem_idx += 1

    return {
        "tables": tables,
        "reading_order": reading_order,
        "body_text": body_texts,
        "resources": resources,
        "unclassified": unclassified,
    }


def build_layout_signature(
    elements: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Build signature list of layout elements stripped of bboxes and raw coordinates."""
    signatures: List[Dict[str, Any]] = []
    for idx, elem in enumerate(elements):
        if isinstance(elem, Mapping):
            etype = elem.get("type", "unknown")
            order = elem.get("order", idx)
        else:
            etype = getattr(elem, "type", "unknown")
            order = getattr(elem, "order", idx)

        sig: Dict[str, Any] = {"type": etype, "order": order}

        if etype == "text":
            text = (
                elem.get("text", elem.get("content", ""))
                if isinstance(elem, Mapping)
                else getattr(elem, "content", getattr(elem, "text", ""))
            )
            sig["text"] = str(text)
        elif etype == "table":
            tbl_data = (
                elem.get("table", elem.get("content", elem))
                if isinstance(elem, Mapping)
                else getattr(elem, "content", elem)
            )
            if isinstance(tbl_data, Mapping):
                rows = tbl_data.get("rows", 0)
                cols = tbl_data.get("cols", 0)
                cells_raw = tbl_data.get("cells", [])
            else:
                rows = getattr(tbl_data, "rows", 0)
                cols = getattr(tbl_data, "cols", 0)
                cells_raw = getattr(tbl_data, "cells", [])

            clean_cells = []
            for c in cells_raw:
                if isinstance(c, Mapping):
                    r = c.get("row", c.get("row_index", 0))
                    col = c.get("col", c.get("col_index", 0))
                    rs = c.get("rowspan", 1)
                    cs = c.get("colspan", 1)
                    txt = c.get("text", "")
                else:
                    r = getattr(c, "row_index", getattr(c, "row", 0))
                    col = getattr(c, "col_index", getattr(c, "col", 0))
                    rs = getattr(c, "rowspan", 1)
                    cs = getattr(c, "colspan", 1)
                    txt = getattr(c, "text", "")
                clean_cells.append(
                    {
                        "row": r,
                        "col": col,
                        "rowspan": rs,
                        "colspan": cs,
                        "text": txt,
                    }
                )
            clean_cells.sort(key=lambda cell: (cell["row"], cell["col"]))
            sig["table"] = {
                "rows": rows,
                "cols": cols,
                "cells": clean_cells,
            }
        elif etype in ("image", "seal"):
            path = (
                elem.get("path")
                if isinstance(elem, Mapping)
                else getattr(elem, "path", None)
            )
            if path is None:
                content = (
                    elem.get("content")
                    if isinstance(elem, Mapping)
                    else getattr(elem, "content", None)
                )
                if content is not None:
                    path = (
                        content.get("path")
                        if isinstance(content, Mapping)
                        else getattr(content, "path", None)
                    )
            if path is not None:
                sig["path"] = path
        elif etype == "separator":
            pass

        signatures.append(sig)
    return signatures


def _normalize_ro_item(item: Any) -> Any:
    """Normalize reading order item for comparison."""
    if isinstance(item, str):
        return {"type": "text", "text": item}
    if isinstance(item, Mapping):
        itype = item.get("type", "text")
        if itype == "text":
            return {"type": "text", "text": item.get("text", item.get("content", ""))}
        elif itype == "table":
            tbl = item.get("table", item.get("content"))
            if tbl and isinstance(tbl, Mapping):
                cells = tbl.get("cells", [])
                clean_cells = [
                    {
                        "row": c.get("row", c.get("row_index", 0)),
                        "col": c.get("col", c.get("col_index", 0)),
                        "rowspan": c.get("rowspan", 1),
                        "colspan": c.get("colspan", 1),
                        "text": c.get("text", ""),
                    }
                    for c in cells
                ]
                clean_cells.sort(key=lambda x: (x["row"], x["col"]))
                return {
                    "type": "table",
                    "table": {
                        "rows": tbl.get("rows", 0),
                        "cols": tbl.get("cols", 0),
                        "cells": clean_cells,
                    },
                }
            return {"type": "table"}
        elif itype in ("image", "seal"):
            return {"type": itype, "path": item.get("path")}
        elif itype == "separator":
            return {"type": "separator"}
        return {k: v for k, v in item.items() if k not in ("order", "bbox")}
    return str(item)


def _compare_reading_orders(ro1: Sequence[Any], ro2: Sequence[Any]) -> bool:
    """Compare two reading order sequences strictly element-by-element."""
    if len(ro1) != len(ro2):
        return False
    for item1, item2 in zip(ro1, ro2):
        if _normalize_ro_item(item1) != _normalize_ro_item(item2):
            return False
    return True


def _extract_image_urls(markdown: str) -> List[str]:
    """Extract image and seal URLs from markdown."""
    urls = []
    for m in _IMAGE_OR_SEAL_RE.finditer(markdown):
        target = m.group("target").strip()
        parts = target.split(None, 1)
        if parts:
            urls.append(parts[0].replace("\\", "/"))
    return urls


def compare_behavior(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    resource_roots: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Compare behavior between expected and actual extraction outputs."""
    raw_categories: Set[str] = set()
    unclassified: List[Dict[str, Any]] = []
    diagnostics: Dict[str, Any] = {}

    roots = resource_roots or expected.get("resource_roots") or actual.get("resource_roots")

    exp_pt = expected.get("page_type")
    act_pt = actual.get("page_type")
    page_type_equal = (exp_pt == act_pt)
    if not page_type_equal:
        raw_categories.add("page_type")
        diagnostics["page_type"] = {"expected": exp_pt, "actual": act_pt}

    exp_raw_md = expected.get("markdown", "")
    act_raw_md = actual.get("markdown", "")
    exp_md = normalize_markdown(exp_raw_md, roots)
    act_md = normalize_markdown(act_raw_md, roots)
    markdown_equal = (exp_md == act_md)

    # Scanned pages rule: only pass when both markdowns are empty
    if exp_pt == "scanned" and act_pt == "scanned":
        if exp_md != "" or act_md != "":
            raw_categories.add("body_text")
            diagnostics["scanned_markdown_nonempty"] = {
                "expected": exp_md,
                "actual": act_md,
            }

    # Extract tables
    exp_sem: Optional[Dict[str, Any]] = None
    act_sem: Optional[Dict[str, Any]] = None

    if "tables" in expected:
        exp_tables = []
        for t in expected["tables"]:
            r, c, cells, occ, unc = _process_explicit_table(t)
            exp_tables.append({"rows": r, "cols": c, "cells": cells, "occupancy": occ})
            unclassified.extend(unc)
    else:
        exp_sem = parse_markdown_semantics(exp_md)
        exp_tables = exp_sem["tables"]
        unclassified.extend(exp_sem["unclassified"])

    if "tables" in actual:
        act_tables = []
        for t in actual["tables"]:
            r, c, cells, occ, unc = _process_explicit_table(t)
            act_tables.append({"rows": r, "cols": c, "cells": cells, "occupancy": occ})
            unclassified.extend(unc)
    else:
        act_sem = parse_markdown_semantics(act_md)
        act_tables = act_sem["tables"]
        unclassified.extend(act_sem["unclassified"])

    # Extract reading order
    if "reading_order" in expected:
        exp_ro = expected["reading_order"]
    else:
        if exp_sem is None:
            exp_sem = parse_markdown_semantics(exp_md)
        exp_ro = exp_sem["reading_order"]

    if "reading_order" in actual:
        act_ro = actual["reading_order"]
    else:
        if act_sem is None:
            act_sem = parse_markdown_semantics(act_md)
        act_ro = act_sem["reading_order"]

    # Table comparison
    table_structure_equal = True
    if len(exp_tables) != len(act_tables):
        table_structure_equal = False
        raw_categories.add("table_count")
        diagnostics["table_count"] = {
            "expected": len(exp_tables),
            "actual": len(act_tables),
        }
    else:
        for i, (t_exp, t_act) in enumerate(zip(exp_tables, act_tables)):
            struct_diff = False
            text_diff = False
            if t_exp["rows"] != t_act["rows"] or t_exp["cols"] != t_act["cols"]:
                struct_diff = True

            c_exp_map = {(c["row"], c["col"]): c for c in t_exp["cells"]}
            c_act_map = {(c["row"], c["col"]): c for c in t_act["cells"]}

            if set(c_exp_map.keys()) != set(c_act_map.keys()):
                struct_diff = True

            for pos in set(c_exp_map.keys()) & set(c_act_map.keys()):
                ce = c_exp_map[pos]
                ca = c_act_map[pos]
                if (
                    ce.get("rowspan", 1) != ca.get("rowspan", 1)
                    or ce.get("colspan", 1) != ca.get("colspan", 1)
                ):
                    struct_diff = True
                if ce.get("text", "") != ca.get("text", ""):
                    text_diff = True

            if struct_diff:
                table_structure_equal = False
                raw_categories.add("table_structure")
            if text_diff:
                raw_categories.add("table_text")

    # Reading order comparison
    reading_order_equal = _compare_reading_orders(exp_ro, act_ro)
    if not reading_order_equal:
        raw_categories.add("reading_order")
        diagnostics["reading_order"] = {
            "expected": exp_ro,
            "actual": act_ro,
        }

    # Extract body texts
    if exp_sem is None:
        exp_sem = parse_markdown_semantics(exp_md)
    if act_sem is None:
        act_sem = parse_markdown_semantics(act_md)

    exp_body = exp_sem["body_text"]
    act_body = act_sem["body_text"]

    if Counter(exp_body) != Counter(act_body):
        raw_categories.add("body_text")
        diagnostics["body_text"] = {"expected": exp_body, "actual": act_body}
    elif exp_body != act_body:
        raw_categories.add("reading_order")

    # Check resource paths
    exp_urls = _extract_image_urls(exp_md)
    act_urls = _extract_image_urls(act_md)
    if exp_urls != act_urls:
        raw_categories.add("resource_path")
        diagnostics["resource_path"] = {"expected": exp_urls, "actual": act_urls}

    # Record unclassified anomalies
    if unclassified:
        raw_categories.add("unclassified")
        diagnostics["unclassified"] = unclassified

    if not markdown_equal and not raw_categories:
        raw_categories.add("unclassified")

    # Format sorted categories
    categories = [cat for cat in ALLOWED_CATEGORIES if cat in raw_categories]

    passed = (
        len(categories) == 0
        and markdown_equal
        and page_type_equal
        and reading_order_equal
        and table_structure_equal
        and len(unclassified) == 0
    )

    return {
        "passed": passed,
        "markdown_equal": markdown_equal,
        "page_type_equal": page_type_equal,
        "reading_order_equal": reading_order_equal,
        "table_structure_equal": table_structure_equal,
        "categories": categories,
        "unclassified": unclassified,
        "diagnostics": diagnostics,
    }
