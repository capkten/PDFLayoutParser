"""PyMuPDF-compatible read-only page adapter for NormalizedPage."""

from typing import Any, Dict, List, Optional, Tuple

from pdfium_normalizer import NormalizedPage


class PageRect(Tuple[float, float, float, float]):
    """A 4-tuple rectangle (x0, y0, x1, y1) with fitz.Rect compatibility properties."""

    def __new__(cls, x0: float, y0: float, x1: float, y1: float) -> "PageRect":
        return super(PageRect, cls).__new__(
            cls, (float(x0), float(y0), float(x1), float(y1))
        )

    @property
    def x0(self) -> float:
        return self[0]

    @property
    def y0(self) -> float:
        return self[1]

    @property
    def x1(self) -> float:
        return self[2]

    @property
    def y1(self) -> float:
        return self[3]

    @property
    def width(self) -> float:
        return self[2] - self[0]

    @property
    def height(self) -> float:
        return self[3] - self[1]

    def __repr__(self) -> str:
        return f"PageRect({self[0]}, {self[1]}, {self[2]}, {self[3]})"


class PdfiumPageAdapter:
    """Read-only PyMuPDF Page adapter projecting a NormalizedPage.

    Provides a fitz.Page-compatible projection for downstream consumers
    (e.g., TextExtractor, LayoutMapper) without modifying or re-clustering
    the underlying normalized data.
    """

    def __init__(self, normalized_page: NormalizedPage) -> None:
        self._normalized_page = normalized_page

    @property
    def normalized_page(self) -> NormalizedPage:
        """Return the underlying NormalizedPage."""
        return self._normalized_page

    @property
    def number(self) -> int:
        """Return page index (0-based) from page_snapshot or sidecar/diagnostics."""
        snapshot = self._normalized_page.page_snapshot
        if snapshot is not None:
            if "page_index" in snapshot and snapshot["page_index"] is not None:
                return int(snapshot["page_index"])
            if "page_number" in snapshot and snapshot["page_number"] is not None:
                return int(snapshot["page_number"])
            if "number" in snapshot and snapshot["number"] is not None:
                return int(snapshot["number"])
            page_meta = snapshot.get("page")
            if isinstance(page_meta, dict):
                for key in ("page_index", "page_number", "number"):
                    if key in page_meta and page_meta[key] is not None:
                        return int(page_meta[key])

        for container in (self._normalized_page.sidecar, self._normalized_page.diagnostics):
            if not isinstance(container, dict):
                continue
            for key in ("page_index", "page_number", "number"):
                if key in container and container[key] is not None:
                    return int(container[key])
            raw_prov = container.get("raw_provenance")
            if isinstance(raw_prov, dict):
                for key in ("page_index", "page_number", "number"):
                    if key in raw_prov and raw_prov[key] is not None:
                        return int(raw_prov[key])
            evidence = container.get("evidence")
            if isinstance(evidence, dict):
                for key in ("page_index", "page_number", "number"):
                    if key in evidence and evidence[key] is not None:
                        return int(evidence[key])

        return 0

    @property
    def rect(self) -> Tuple[float, float, float, float]:
        """Return page rectangle as a fitz.Rect-compatible tuple (0.0, 0.0, width, height)."""
        width = 0.0
        height = 0.0

        snapshot = self._normalized_page.page_snapshot
        if snapshot is not None:
            page_meta = snapshot.get("page")
            if isinstance(page_meta, dict):
                width = float(page_meta.get("width", 0.0))
                height = float(page_meta.get("height", 0.0))
            if width == 0.0 and height == 0.0:
                width = float(snapshot.get("width", 0.0))
                height = float(snapshot.get("height", 0.0))

        if width == 0.0 and height == 0.0 and self._normalized_page.rawdict is not None:
            width = float(self._normalized_page.rawdict.get("width", 0.0))
            height = float(self._normalized_page.rawdict.get("height", 0.0))

        if width == 0.0 and height == 0.0:
            for container in (self._normalized_page.sidecar, self._normalized_page.diagnostics):
                if not isinstance(container, dict):
                    continue
                if "width" in container and "height" in container:
                    width = float(container["width"])
                    height = float(container["height"])
                    break
                page_meta = container.get("page")
                if isinstance(page_meta, dict) and "width" in page_meta and "height" in page_meta:
                    width = float(page_meta["width"])
                    height = float(page_meta["height"])
                    break
                raw_prov = container.get("raw_provenance")
                if isinstance(raw_prov, dict) and "width" in raw_prov and "height" in raw_prov:
                    width = float(raw_prov["width"])
                    height = float(raw_prov["height"])
                    break

        return PageRect(0.0, 0.0, width, height)

    def get_text(self, kind: str, flags: Optional[int] = None, **kwargs: Any) -> Any:
        """Extract text view according to PyMuPDF get_text convention.

        Supported modes:
        - "rawdict": PyMuPDF rawdict format containing blocks -> lines -> spans -> chars.
        - "dict": PyMuPDF dict format, compatible with rawdict (preserving character lists
          to prevent downstream synthesis fallbacks).
        - "words": List of 8-tuples (x0, y0, x1, y1, word, block_no, line_no, word_no).

        Any other mode raises ValueError.
        """
        if kind == "rawdict":
            return (
                self._normalized_page.rawdict
                if self._normalized_page.rawdict is not None
                else {"blocks": []}
            )
        elif kind == "dict":
            return (
                self._normalized_page.rawdict
                if self._normalized_page.rawdict is not None
                else {"blocks": []}
            )
        elif kind == "words":
            return (
                list(self._normalized_page.words)
                if self._normalized_page.words is not None
                else []
            )
        else:
            raise ValueError(f"unsupported text mode: {kind}")

    def get_drawings(self) -> List[Dict[str, Any]]:
        """Return drawings list from page snapshot or sidecar/diagnostics, or empty list."""
        snapshot = self._normalized_page.page_snapshot
        if snapshot is not None:
            drawings = snapshot.get("drawings")
            if drawings:
                return list(drawings)

        sidecar = self._normalized_page.sidecar
        if isinstance(sidecar, dict):
            drawings = sidecar.get("drawings")
            if drawings:
                return list(drawings)

        diagnostics = self._normalized_page.diagnostics
        if isinstance(diagnostics, dict):
            drawings = diagnostics.get("drawings")
            if drawings:
                return list(drawings)

        return []

    def snapshot_dto(self) -> Optional[Dict[str, Any]]:
        """Return the wire PageSnapshotDto dictionary or None."""
        return self._normalized_page.page_snapshot
