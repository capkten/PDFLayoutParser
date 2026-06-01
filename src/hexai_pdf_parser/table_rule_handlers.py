"""Registered table rule handlers for complex layout processing.

Provides two registries — ``REGION_RULE_HANDLERS`` and
``STRUCTURE_RULE_HANDLERS`` — that map handler names to callable functions.
Handlers are looked up by name from a profile's ``handler`` field and applied
after parameter-based rules.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from hexai_pdf_parser.models import Table
from hexai_pdf_parser.table_region_rules import TableRegionCandidate
from hexai_pdf_parser.table_structure_rules import TableStructureCandidate

# Type aliases for handler signatures
RegionHandler = Callable[
    [List[TableRegionCandidate], List[Dict[str, Any]], Dict[str, Any]],
    List[TableRegionCandidate],
]
StructureHandler = Callable[
    [TableStructureCandidate, Dict[str, Any]],
    TableStructureCandidate,
]

REGION_RULE_HANDLERS: Dict[str, RegionHandler] = {}
STRUCTURE_RULE_HANDLERS: Dict[str, StructureHandler] = {}


def register_region_handler(name: str) -> Callable:
    """Decorator to register a region rule handler by name."""
    def decorator(func: RegionHandler) -> RegionHandler:
        REGION_RULE_HANDLERS[name] = func
        return func
    return decorator


def register_structure_handler(name: str) -> Callable:
    """Decorator to register a structure rule handler by name."""
    def decorator(func: StructureHandler) -> StructureHandler:
        STRUCTURE_RULE_HANDLERS[name] = func
        return func
    return decorator


def get_region_handler(name: str) -> RegionHandler:
    """Look up a region handler by name, raising KeyError if not found."""
    if name not in REGION_RULE_HANDLERS:
        raise KeyError(
            f"Unknown region rule handler: {name!r}. "
            f"Available: {list(REGION_RULE_HANDLERS.keys())}"
        )
    return REGION_RULE_HANDLERS[name]


def get_structure_handler(name: str) -> StructureHandler:
    """Look up a structure handler by name, raising KeyError if not found."""
    if name not in STRUCTURE_RULE_HANDLERS:
        raise KeyError(
            f"Unknown structure rule handler: {name!r}. "
            f"Available: {list(STRUCTURE_RULE_HANDLERS.keys())}"
        )
    return STRUCTURE_RULE_HANDLERS[name]


@register_region_handler("noop_region")
def _noop_region_handler(
    candidates: List[TableRegionCandidate],
    rows: List[Dict[str, Any]],
    params: Dict[str, Any],
) -> List[TableRegionCandidate]:
    """Built-in no-op region handler for testing."""
    return candidates


@register_structure_handler("noop_structure")
def _noop_structure_handler(
    candidate: TableStructureCandidate,
    params: Dict[str, Any],
) -> TableStructureCandidate:
    """Built-in no-op structure handler for testing."""
    return candidate
