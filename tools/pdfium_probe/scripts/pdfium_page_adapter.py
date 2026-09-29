import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from PIL import Image

from pdfium_normalizer import NormalizedPage


class PdfiumPixmap:
    """PyMuPDF-compatible Pixmap projection wrapping rasterized RGB image bytes."""

    def __init__(self, samples: bytes, width: int, height: int, n: int = 3) -> None:
        self.samples = samples
        self.width = int(width)
        self.height = int(height)
        self.n = int(n)
        self.stride = self.width * self.n

    def tobytes(self) -> bytes:
        return self.samples

    def save(self, filename: Union[str, Path]) -> None:
        """Save pixmap to an image file (e.g. PNG)."""
        img = Image.frombytes("RGB", (self.width, self.height), self.samples)
        img.save(str(filename))



class PageRect(Tuple[float, float, float, float]):
    """A 4-tuple rectangle (x0, y0, x1, y1) with fitz.Rect compatibility properties."""

    def __new__(cls, *args: Any) -> "PageRect":
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            vals = args[0]
            if len(vals) != 4:
                raise TypeError(f"PageRect expects 4 values, got {len(vals)}")
            x0, y0, x1, y1 = vals
        elif len(args) == 4:
            x0, y0, x1, y1 = args
        else:
            raise TypeError(f"PageRect expects 4 coordinates or a 4-tuple, got {args}")
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


def _pixmap_from_png_path(png_path: Path) -> PdfiumPixmap:
    """Load a PNG image file into a PdfiumPixmap."""
    with Image.open(png_path) as img:
        rgb_img = img.convert("RGB")
        samples = rgb_img.tobytes()
        w, h = rgb_img.width, rgb_img.height
    return PdfiumPixmap(samples, w, h, n=3)


def _find_pdfium_probe_bin() -> Optional[Path]:
    """Locate compiled pdfium_probe binary (debug or release)."""
    probe_root = Path(__file__).resolve().parents[1]
    fallback_repo = probe_root.parents[1] if len(probe_root.parents) > 1 else probe_root.parent.parent
    repo_root = Path(os.environ.get("REPO_ROOT", str(fallback_repo)))
    bin_names = (
        ["pdfium_probe.exe", "pdfium_probe"]
        if os.name == "nt"
        else ["pdfium_probe", "pdfium_probe.exe"]
    )

    candidate_dirs: List[Path] = []
    cargo_target_dir = os.environ.get("CARGO_TARGET_DIR")
    if cargo_target_dir:
        c_target = Path(cargo_target_dir)
        candidate_dirs.extend([
            c_target / "release",
            c_target / "debug",
        ])

    candidate_dirs.extend([
        probe_root / "target" / "release",
        probe_root / "target" / "debug",
        fallback_repo / "tools" / "pdfium_probe" / "target" / "release",
        fallback_repo / "tools" / "pdfium_probe" / "target" / "debug",
        repo_root / "tools" / "pdfium_probe" / "target" / "release",
        repo_root / "tools" / "pdfium_probe" / "target" / "debug",
    ])

    for cdir in candidate_dirs:
        for bname in bin_names:
            cand = cdir / bname
            if cand.is_file():
                return cand

    for bname in bin_names:
        which_path = shutil.which(bname)
        if which_path:
            p = Path(which_path)
            if p.is_file():
                return p

    return None


def _find_prerendered_png(pdf_path: Path, page_num: int, dpi: int) -> Optional[Path]:
    """Look for pre-rendered PNG from Rust probe output directories."""
    filename = f"{pdf_path.stem}_page_{page_num}_dpi{dpi}.png"
    probe_root = Path(__file__).resolve().parents[1]
    fallback_repo = probe_root.parents[1] if len(probe_root.parents) > 1 else probe_root.parent.parent
    repo_root = Path(os.environ.get("REPO_ROOT", str(fallback_repo)))

    candidate_dirs: List[Path] = []
    if "PDFIUM_OUTPUT_ROOT" in os.environ:
        out_root = Path(os.environ["PDFIUM_OUTPUT_ROOT"])
        candidate_dirs.extend([
            out_root / "pdfium_output",
            out_root / "real_pdfium_output",
            out_root,
        ])

    candidate_dirs.extend([
        probe_root / "test_data" / "pdfium_output",
        probe_root / "test_data" / "real_pdfium_output",
        probe_root / "test_data",
        pdf_path.parent / "pdfium_output",
        pdf_path.parent / "real_pdfium_output",
        pdf_path.parent,
        fallback_repo / "test_data" / "pdfium_output",
        fallback_repo / "test_data" / "real_pdfium_output",
        repo_root / "test_data" / "pdfium_output",
        repo_root / "test_data" / "real_pdfium_output",
    ])

    for cdir in candidate_dirs:
        cand = cdir / filename
        if cand.is_file():
            return cand
    return None


class PdfiumPageAdapter:
    """Read-only PyMuPDF Page adapter projecting a NormalizedPage.

    Provides a fitz.Page-compatible projection for downstream consumers
    (e.g., TextExtractor, LayoutMapper, MLTableDetector, WiredTableExtractor)
    without modifying or re-clustering the underlying normalized data.
    """

    def __init__(
        self,
        normalized_page: Union[NormalizedPage, Mapping[str, Any]],
        pdf_path: Optional[Union[str, Any]] = None,
    ) -> None:
        if isinstance(normalized_page, Mapping):
            from pdfium_normalizer import normalize_raw_page
            self._normalized_page = normalize_raw_page(normalized_page)
        else:
            self._normalized_page = normalized_page
        self._pdf_path = Path(pdf_path) if pdf_path is not None else None

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
        elif kind == "text":
            if self._normalized_page.words:
                return " ".join(w[4] for w in self._normalized_page.words)
            return ""
        else:
            raise ValueError(f"unsupported text mode: {kind}")

    def _resolve_pdf_path(self) -> Optional[Path]:
        probe_root = Path(__file__).resolve().parents[1]
        fallback_repo = probe_root.parents[1] if len(probe_root.parents) > 1 else probe_root.parent.parent
        repo_root = Path(os.environ.get("REPO_ROOT", str(fallback_repo)))

        if self._pdf_path is not None:
            if self._pdf_path.is_file():
                return self._pdf_path
            for base in (probe_root, fallback_repo, repo_root):
                target = base / self._pdf_path
                if target.is_file():
                    return target

        candidates: List[str] = []
        snapshot = self._normalized_page.page_snapshot
        if snapshot is not None:
            if snapshot.get("source_file"):
                candidates.append(str(snapshot["source_file"]))
        for container in (self._normalized_page.sidecar, self._normalized_page.diagnostics):
            if isinstance(container, dict) and container.get("source_file"):
                candidates.append(str(container["source_file"]))

        for cand in candidates:
            cand_p = Path(cand)
            if cand_p.is_file():
                return cand_p
            for base in (
                probe_root,
                probe_root / "test_data",
                probe_root / "test_data" / "synthetic",
                probe_root / "test_data" / "real",
                fallback_repo,
                repo_root,
            ):
                target = base / cand_p.name
                if target.is_file():
                    return target
        return None

    def get_pixmap(
        self,
        matrix: Optional[Any] = None,
        dpi: Optional[int] = None,
        alpha: bool = False,
        colorspace: Optional[Any] = None,
        clip: Optional[Any] = None,
        **kwargs: Any,
    ) -> PdfiumPixmap:
        """Render page to a PyMuPDF-compatible PdfiumPixmap.

        Consumes pre-rendered PNGs from Rust probe or calls pdfium_probe CLI
        via pure Rust rendering.
        Falls back to PyMuPDF or blank canvas for synthetic tests.
        """
        scale = 1.0
        if matrix is not None:
            scale = float(getattr(matrix, "a", 1.0))
            effective_dpi = max(1, int(round(scale * 72.0)))
        elif dpi is not None:
            effective_dpi = max(1, int(round(float(dpi))))
            scale = effective_dpi / 72.0
        else:
            effective_dpi = 72

        pdf_path = self._resolve_pdf_path()
        if pdf_path is not None:
            # 1. Look for pre-rendered PNG from probe output
            prerendered = _find_prerendered_png(pdf_path, self.number, effective_dpi)
            if prerendered is not None:
                try:
                    return _pixmap_from_png_path(prerendered)
                except Exception:
                    pass

            # 2. Invoke Rust pdfium_probe binary to render page
            probe_bin = _find_pdfium_probe_bin()
            if probe_bin is not None:
                try:
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        temp_png = Path(tmp_dir) / f"{pdf_path.stem}_p{self.number}_dpi{effective_dpi}.png"
                        cmd = [
                            str(probe_bin),
                            "render",
                            str(pdf_path),
                            str(self.number),
                            str(effective_dpi),
                            str(temp_png),
                        ]
                        proc = subprocess.run(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False,
                            timeout=30,
                        )
                        if proc.returncode == 0 and temp_png.is_file():
                            return _pixmap_from_png_path(temp_png)
                except Exception:
                    pass

            # 3. Fallback to PyMuPDF if installed
            try:
                import fitz
                doc = fitz.open(str(pdf_path))
                page_idx = min(self.number, len(doc) - 1)
                page = doc[page_idx]
                mat = fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=mat, alpha=alpha)
                return PdfiumPixmap(pix.samples, pix.width, pix.height, n=getattr(pix, "n", 3))
            except Exception:
                pass

        # Fallback when no PDF file exists on disk (e.g. synthetic test):
        w = max(1, int(round(self.rect.width * scale)))
        h = max(1, int(round(self.rect.height * scale)))
        blank_samples = b"\xff\xff\xff" * (w * h)
        return PdfiumPixmap(blank_samples, w, h, n=3)

    def get_drawings(
        self,
        extended: bool = True,
        raw: bool = False,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Return drawings list.

        If raw=True, returns the unnormalized probe raw snapshot dictionaries.
        Otherwise, returns PyMuPDF-compatible drawing dictionaries (type, rect, color, fill, items).
        """
        snapshot = self._normalized_page.page_snapshot
        raw_drawings: List[Dict[str, Any]] = []
        if snapshot is not None:
            d = snapshot.get("drawings")
            if d:
                raw_drawings = list(d)

        if not raw_drawings:
            for container in (self._normalized_page.sidecar, self._normalized_page.diagnostics):
                if isinstance(container, dict):
                    d = container.get("drawings")
                    if d:
                        raw_drawings = list(d)
                        break

        if raw or not raw_drawings:
            return raw_drawings

        try:
            import fitz
            has_fitz = True
        except ImportError:
            has_fitz = False

        adapted: List[Dict[str, Any]] = []
        for d in raw_drawings:
            # If the drawing is already PyMuPDF-adapted, return as is
            if "type" in d and ("items" in d or "rect" in d) and "path_type" not in d:
                adapted.append(d)
                continue

            ptype = str(d.get("path_type", "filled"))
            if ptype == "stroked_filled":
                t = "fs"
            elif ptype == "stroked":
                t = "s"
            else:
                t = "f"

            fill = d.get("fill")
            color = d.get("color")
            if t in ("f", "fs") and fill is None:
                fill = (0.0, 0.0, 0.0)
            if t in ("s", "fs") and color is None:
                color = (0.0, 0.0, 0.0)

            r = d.get("rect")
            if isinstance(r, dict):
                rx0 = float(r.get("x0", 0.0))
                ry0 = float(r.get("y0", 0.0))
                rx1 = float(r.get("x1", 0.0))
                ry1 = float(r.get("y1", 0.0))
            elif isinstance(r, (list, tuple)) and len(r) >= 4:
                rx0, ry0, rx1, ry1 = float(r[0]), float(r[1]), float(r[2]), float(r[3])
            else:
                rx0, ry0, rx1, ry1 = 0.0, 0.0, 0.0, 0.0

            rect = fitz.Rect(rx0, ry0, rx1, ry1) if has_fitz else PageRect(rx0, ry0, rx1, ry1)

            items: List[Any] = []
            for it in d.get("items", []):
                if isinstance(it, dict):
                    cmd = it.get("cmd")
                    pts = it.get("points", [])
                elif isinstance(it, (list, tuple)) and len(it) >= 2:
                    cmd = it[0]
                    pts = it[1:]
                else:
                    continue

                if cmd == "l" and len(pts) >= 2:
                    p1 = pts[0]
                    p2 = pts[1]
                    pt1 = fitz.Point(float(p1[0]), float(p1[1])) if has_fitz else (float(p1[0]), float(p1[1]))
                    pt2 = fitz.Point(float(p2[0]), float(p2[1])) if has_fitz else (float(p2[0]), float(p2[1]))
                    items.append(("l", pt1, pt2))
                elif cmd == "re":
                    if len(pts) >= 4 and isinstance(pts[0], (int, float)):
                        re_r = fitz.Rect(pts[0], pts[1], pts[2], pts[3]) if has_fitz else PageRect(pts[0], pts[1], pts[2], pts[3])
                        items.append(("re", re_r))
                    elif len(pts) >= 2 and isinstance(pts[0], (list, tuple)):
                        re_r = fitz.Rect(pts[0][0], pts[0][1], pts[1][0], pts[1][1]) if has_fitz else PageRect(pts[0][0], pts[0][1], pts[1][0], pts[1][1])
                        items.append(("re", re_r))
                elif cmd == "c" and len(pts) >= 4:
                    pts_pts = [
                        fitz.Point(float(p[0]), float(p[1])) if has_fitz else (float(p[0]), float(p[1]))
                        for p in pts[:4]
                    ]
                    items.append(("c", *pts_pts))

            adapted.append({
                "type": t,
                "rect": rect,
                "color": color,
                "fill": fill,
                "width": float(d.get("width", 1.0)),
                "items": items,
            })

        return adapted

    def snapshot_dto(self) -> Optional[Dict[str, Any]]:
        """Return the wire PageSnapshotDto dictionary or None."""
        return self._normalized_page.page_snapshot
