"""Classify semantic differences between two Markdown snapshots."""

from collections import Counter
from html.parser import HTMLParser
import re
from typing import Any, Dict, List, Optional, Tuple


_WS_RE = re.compile(r"\s+")


def _clean_text(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


class _MarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[Dict[str, Any]] = []
        self._table_stack: List[Dict[str, Any]] = []
        self._row: Optional[List[Dict[str, Any]]] = None
        self._cell: Optional[Dict[str, Any]] = None
        self.body_units: List[str] = []
        self.visible_units: List[str] = []

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        tag = tag.lower()
        if tag == "table":
            table = {"rows": [], "texts": []}
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag == "tr" and self._table_stack and self._cell is None:
            self._row = []
            self._table_stack[-1]["rows"].append(self._row)
        elif tag in {"td", "th"} and self._row is not None and self._cell is None:
            values = dict(attrs)
            self._cell = {
                "text": [],
                "rowspan": self._span(values.get("rowspan")),
                "colspan": self._span(values.get("colspan")),
            }
            self._row.append(self._cell)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None:
            text = _clean_text("".join(self._cell["text"]))
            self._cell["text"] = text
            self._table_stack[-1]["texts"].append(text)
            self.visible_units.append(text)
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
            return
        if self._table_stack:
            return
        for line in data.splitlines():
            text = _clean_text(line)
            if text:
                self.body_units.append(text)
                self.visible_units.append(text)

    @staticmethod
    def _span(value: Optional[str]) -> int:
        try:
            return max(1, int(value or "1"))
        except ValueError:
            return 1


def parse_markdown(markdown: str) -> Dict[str, Any]:
    parser = _MarkdownParser()
    parser.feed(markdown)
    parser.close()
    tables = []
    for table in parser.tables:
        rows = table["rows"]
        tables.append(
            {
                "rows": len(rows),
                "cells_per_row": [len(row) for row in rows],
                "spans": [
                    [(cell["rowspan"], cell["colspan"]) for cell in row]
                    for row in rows
                ],
                "texts": list(table["texts"]),
            }
        )
    return {
        "table_count": len(tables),
        "tables": tables,
        "body_units": parser.body_units,
        "visible_units": parser.visible_units,
    }


def _table_shapes(snapshot: Dict[str, Any]) -> List[Any]:
    return [
        (table["rows"], tuple(table["cells_per_row"]), tuple(map(tuple, table["spans"])))
        for table in snapshot["tables"]
    ]


def _table_text(snapshot: Dict[str, Any]) -> List[str]:
    return [text for table in snapshot["tables"] for text in table["texts"]]


def _normal_form(markdown: str) -> str:
    parser = parse_markdown(markdown)
    body = "\n".join(parser["body_units"])
    tables = repr((_table_shapes(parser), _table_text(parser)))
    return f"{body}\n{tables}"


def detect_signals(expected: Dict[str, Any], actual: Dict[str, Any]) -> List[str]:
    signals: List[str] = []
    same_count = expected["table_count"] == actual["table_count"]
    shapes_differ = _table_shapes(expected) != _table_shapes(actual)
    table_text_differ = _table_text(expected) != _table_text(actual)
    body_differ = Counter(expected["body_units"]) != Counter(actual["body_units"])
    visible_same = Counter(expected["visible_units"]) == Counter(actual["visible_units"])
    visible_order_differ = expected["visible_units"] != actual["visible_units"]

    if not same_count:
        signals.append("table_count")
    if same_count and shapes_differ:
        signals.append("table_structure")
    if same_count and not shapes_differ and table_text_differ:
        signals.append("table_text")
    if same_count and body_differ:
        signals.append("body_text")
    if visible_same and visible_order_differ:
        signals.append("reading_order")
    return signals


def build_classification(
    expected: str, actual: str, signals: List[str]
) -> Dict[str, Any]:
    if len(signals) == 1:
        primary = signals[0]
        categories = signals
    elif signals:
        primary = "mixed"
        categories = ["mixed"]
    elif _normal_form(expected) == _normal_form(actual) and expected != actual:
        primary = "formatting"
        categories = ["formatting"]
    else:
        primary = "same"
        categories = ["same"]
    expected_snapshot = parse_markdown(expected)
    actual_snapshot = parse_markdown(actual)
    return {
        "primary_category": primary,
        "categories": categories,
        "signals": signals if signals else (["formatting"] if primary == "formatting" else []),
        "evidence": {
            "table_count": {
                "expected": expected_snapshot["table_count"],
                "actual": actual_snapshot["table_count"],
            },
            "table_shapes_differ": _table_shapes(expected_snapshot)
            != _table_shapes(actual_snapshot),
            "table_text_differ": _table_text(expected_snapshot)
            != _table_text(actual_snapshot),
            "body_text_differ": Counter(expected_snapshot["body_units"])
            != Counter(actual_snapshot["body_units"]),
        },
    }


def classify_markdown(expected: str, actual: str) -> Dict[str, Any]:
    expected_snapshot = parse_markdown(expected)
    actual_snapshot = parse_markdown(actual)
    signals = detect_signals(expected_snapshot, actual_snapshot)
    return build_classification(expected, actual, signals)


def build_review(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Reserved for the review artifact builder implemented in a later task."""
    raise NotImplementedError("build_review is not part of Task 1")
