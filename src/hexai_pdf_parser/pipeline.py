"""Pipeline: orchestrates the full PDF processing flow.

This module ties together all individual modules (loader, text_extractor,
layout_mapper, image_extractor, table_extractor, layout_builder,
json_writer, markdown_writer, render_engine) into a single end-to-end
processing pipeline.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
from time import perf_counter
from typing import List, Optional

import fitz

from hexai_pdf_parser.image_extractor import ImageExtractor
from hexai_pdf_parser.json_writer import JSONWriter
from hexai_pdf_parser.layout_builder import LayoutBuilder
from hexai_pdf_parser.layout_mapper import LayoutMapper
from hexai_pdf_parser.loader import Loader
from hexai_pdf_parser.markdown_writer import MarkdownWriter
from hexai_pdf_parser.models import BBox, Document, LayoutElement, Seal
from hexai_pdf_parser.render_engine import RenderEngine
from hexai_pdf_parser.table_extractor import TableExtractor
from hexai_pdf_parser.table_config import TableConfig
from hexai_pdf_parser.text_alignment_debug import render_text_alignment_debug_page
from hexai_pdf_parser.text_extractor import TextExtractor


# Persistent process pool for multi-processing execution backend
_PROCESS_POOL = None
_PROCESS_POOL_WORKERS = None


def _run_page_pipeline(
    pdf_doc: fitz.Document,
    page: "Page",
    pdf_path: str,
    images_dir: str,
    pages_dir: str,
    text_alignment_debug_dir: str,
    render_dpi: int,
    seal_coords,
    use_ml: bool,
    ml_model_path,
    ml_confidence: float,
    debug: bool,
    table_config,
    output_dir,
):
    """Run all pipeline stages for a single page.

    Mutates *page* in-place and returns a dict of stage elapsed times.
    The caller owns the *pdf_doc* lifecycle (open/close).
    """
    from hexai_pdf_parser.text_extractor import TextExtractor
    from hexai_pdf_parser.layout_mapper import LayoutMapper
    from hexai_pdf_parser.table_extractor import TableExtractor
    from hexai_pdf_parser.image_extractor import ImageExtractor
    from hexai_pdf_parser.layout_builder import LayoutBuilder
    from hexai_pdf_parser.render_engine import RenderEngine
    from hexai_pdf_parser.json_writer import JSONWriter
    from hexai_pdf_parser.markdown_writer import MarkdownWriter
    from hexai_pdf_parser.models import BBox, LayoutElement, Seal
    from hexai_pdf_parser.text_alignment_debug import render_text_alignment_debug_page

    stage_totals: dict[str, float] = {}

    def time_stage(stage: str, func):
        start = perf_counter()
        result = func()
        elapsed = perf_counter() - start
        stage_totals[stage] = stage_totals.get(stage, 0.0) + elapsed
        return result

    page_handle = pdf_doc[page.index]

    # a. Text extraction
    page.blocks = time_stage(
        "text_extract",
        lambda: TextExtractor().extract_blocks(page_handle),
    )

    # b. Layout mapping (text -> LayoutElements)
    text_elements = time_stage(
        "layout_map",
        lambda: LayoutMapper().map_blocks(page.blocks),
    )

    # c. Table extraction
    table_extractor = TableExtractor(
        use_ml=use_ml,
        ml_model_path=ml_model_path,
        ml_confidence=ml_confidence,
        table_config=table_config,
    )
    page.tables = time_stage(
        "table_extract",
        lambda: table_extractor.extract(page_handle),
    )

    if debug and output_dir is not None:
        debug_payload = table_extractor._last_text_alignment_debug
        has_text_alignment = any(
            table.source == "text_alignment" for table in page.tables
        )
        if debug_payload and has_text_alignment:
            debug_path = os.path.join(
                text_alignment_debug_dir,
                f"page-{page.index:03d}.png",
            )
            time_stage(
                "write_text_alignment_debug",
                lambda: render_text_alignment_debug_page(
                    page=page_handle,
                    debug_payload=debug_payload,
                    output_path=debug_path,
                    dpi=render_dpi,
                ),
            )

    # d. Image extraction
    if output_dir is not None:
        page.images = time_stage(
            "image_extract",
            lambda: ImageExtractor(images_dir).extract(
                pdf_path, page.index
            ),
        )
    else:
        page.images = []

    # e. Seals
    seals: list[Seal] = []
    for coord in (seal_coords or []):
        if coord.get("page_index") != page.index:
            continue
        seals.append(
            Seal(
                bbox=BBox(
                    coord["x0"],
                    coord["y0"],
                    coord["x1"],
                    coord["y1"],
                ),
                page_index=page.index,
            )
        )
    page.seals = seals

    # f. Layout building
    layout_elements = time_stage(
        "layout_build",
        lambda: LayoutBuilder().build(
            text_elements, page.tables, page.images
        ),
    )

    # g. Append seal layout elements
    for seal in seals:
        layout_elements.append(
            LayoutElement(
                type="seal",
                bbox=seal.bbox,
                order=len(layout_elements),
                content=seal,
            )
        )

    layout_elements = LayoutBuilder.sort_layout_elements(layout_elements)

    # h. Set layout_elements on the page
    page.layout_elements = layout_elements

    # i. Render
    if output_dir is not None:
        page.render = time_stage(
            "render",
            lambda: RenderEngine(
                output_dir, render_dpi
            ).render(pdf_path, page.index),
        )

    # j. Per-page output
    if output_dir is not None:
        page_json_path = os.path.join(
            pages_dir, f"page-{page.index:03d}.json"
        )
        page_md_path = os.path.join(
            pages_dir, f"page-{page.index:03d}.md"
        )
        time_stage(
            "write_page_json",
            lambda: JSONWriter().write_page(page, page_json_path),
        )
        time_stage(
            "write_page_md",
            lambda: MarkdownWriter().write_page(page, page_md_path),
        )

    return stage_totals


def _process_page_process_worker(
    pdf_path: str,
    page_index: int,
    images_dir: str,
    pages_dir: str,
    text_alignment_debug_dir: str,
    render_dpi: int,
    seal_coords,
    use_ml: bool,
    ml_model_path,
    ml_confidence: float,
    debug: bool,
    table_config,
    page_size: dict,
    page_rotation: int,
) -> tuple[int, "Page", dict[str, float], float]:
    """Worker function for process-based parallelism.

    Opens its own fitz document, delegates to ``_run_page_pipeline``,
    and returns results that can be serialized across process boundaries.
    """
    import os
    from time import perf_counter
    import fitz
    from hexai_pdf_parser.models import Page

    page_start = perf_counter()

    page = Page(
        index=page_index,
        size=page_size,
        rotation=page_rotation,
    )

    output_dir = os.path.dirname(images_dir) if images_dir else None

    pdf_doc = fitz.open(pdf_path)
    try:
        stage_totals = _run_page_pipeline(
            pdf_doc=pdf_doc,
            page=page,
            pdf_path=pdf_path,
            images_dir=images_dir,
            pages_dir=pages_dir,
            text_alignment_debug_dir=text_alignment_debug_dir,
            render_dpi=render_dpi,
            seal_coords=seal_coords,
            use_ml=use_ml,
            ml_model_path=ml_model_path,
            ml_confidence=ml_confidence,
            debug=debug,
            table_config=table_config,
            output_dir=output_dir,
        )
    finally:
        pdf_doc.close()

    total_page_time = perf_counter() - page_start
    return page_index, page, stage_totals, total_page_time


class Pipeline:
    """Orchestrate the full PDF processing flow.

    Example::

        pipeline = Pipeline("doc.pdf", output_dir="/tmp/out", render_dpi=200)
        document = pipeline.run()
    """

    def __init__(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
        render_dpi: int = 200,
        seal_coords: Optional[List[dict]] = None,
        page_indices: Optional[List[int]] = None,
        use_ml: bool = False,
        ml_model_path: Optional[str] = None,
        ml_confidence: float = 0.25,
        debug: bool = False,
        table_config: Optional[TableConfig] = None,
        num_workers: Optional[int] = None,
        backend: str = "thread",
    ):
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.render_dpi = render_dpi
        self.seal_coords = seal_coords or []
        self.page_indices = page_indices
        self.use_ml = use_ml
        self._ml_model_path = ml_model_path
        self._ml_confidence = ml_confidence
        self.debug = debug
        self._table_config = table_config
        self.num_workers = num_workers
        self.backend = backend
        self._lock = threading.Lock()
        self._fitz_lock = threading.Lock()
        self._stage_totals: dict[str, float] = {}
        self._page_totals: list[dict[str, float]] = []

    def _time_stage(self, stage: str, func):
        """Measure and accumulate elapsed time for a callable stage."""
        start = perf_counter()
        result = func()
        elapsed = perf_counter() - start
        with self._lock:
            self._stage_totals[stage] = self._stage_totals.get(stage, 0.0) + elapsed
        return result, elapsed

    def _record_page_total(self, page_index: int, elapsed: float) -> None:
        with self._lock:
            self._page_totals.append(
                {"page_index": page_index, "total_seconds": elapsed}
            )

    def _percentile(self, values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return values[0]
        ordered = sorted(values)
        position = (len(ordered) - 1) * percentile
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    def _build_timing_report(
        self,
        page_count: int,
        total_seconds: float,
    ) -> dict:
        page_totals = [item["total_seconds"] for item in self._page_totals]
        return {
            "page_count": page_count,
            "total_seconds": total_seconds,
            "avg_seconds_per_page": (
                total_seconds / page_count if page_count else 0.0
            ),
            "stage_totals": dict(sorted(self._stage_totals.items())),
            "page_totals": self._page_totals,
            "page_total_summary": {
                "min_seconds": min(page_totals) if page_totals else 0.0,
                "median_seconds": (
                    statistics.median(page_totals) if page_totals else 0.0
                ),
                "p95_seconds": self._percentile(page_totals, 0.95),
                "max_seconds": max(page_totals) if page_totals else 0.0,
            },
        }

    def _format_timing_report(self, report: dict) -> str:
        lines = [
            "[Timing] pipeline summary",
            (
                "[Timing] total="
                f"{report['total_seconds']:.3f}s "
                f"pages={report['page_count']} "
                f"avg={report['avg_seconds_per_page']:.3f}s/page"
            ),
        ]
        summary = report["page_total_summary"]
        lines.append(
            "[Timing] page totals "
            f"min={summary['min_seconds']:.3f}s "
            f"median={summary['median_seconds']:.3f}s "
            f"p95={summary['p95_seconds']:.3f}s "
            f"max={summary['max_seconds']:.3f}s"
        )
        lines.append("[Timing] stage totals:")
        for stage, elapsed in report["stage_totals"].items():
            pct = (elapsed / report["total_seconds"] * 100.0) if report["total_seconds"] else 0.0
            lines.append(
                f"[Timing]   {stage}: {elapsed:.3f}s ({pct:.1f}%)"
            )
        return "\n".join(lines)

    def _write_timing_report(self, output_dir: str, report: dict) -> None:
        path = os.path.join(output_dir, "timings.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def _process_single_page(
        self,
        page_index: int,
        document: Document,
        images_dir: str,
        pages_dir: str,
        text_alignment_debug_dir: str,
        pdf_doc: fitz.Document,
    ) -> None:
        page = document.pages[page_index]
        page_start = perf_counter()

        with self._fitz_lock:
            stage_totals = _run_page_pipeline(
                pdf_doc=pdf_doc,
                page=page,
                pdf_path=self.pdf_path,
                images_dir=images_dir,
                pages_dir=pages_dir,
                text_alignment_debug_dir=text_alignment_debug_dir,
                render_dpi=self.render_dpi,
                seal_coords=self.seal_coords,
                use_ml=self.use_ml,
                ml_model_path=self._ml_model_path,
                ml_confidence=self._ml_confidence,
                debug=self.debug,
                table_config=self._table_config,
                output_dir=self.output_dir,
            )

        for stage, elapsed in stage_totals.items():
            with self._lock:
                self._stage_totals[stage] = self._stage_totals.get(stage, 0.0) + elapsed
        self._record_page_total(page.index, perf_counter() - page_start)

    def run(self) -> Document:
        """Run the full processing pipeline and return the Document."""
        self._stage_totals = {}
        self._page_totals = []
        overall_start = perf_counter()

        # 1. Load PDF
        document, _ = self._time_stage(
            "load",
            lambda: Loader(self.pdf_path).load(),
        )

        # Prepare output directories
        images_dir = ""
        pages_dir = ""
        text_alignment_debug_dir = ""
        if self.output_dir is not None:
            images_dir = os.path.join(self.output_dir, "images")
            pages_dir = os.path.join(self.output_dir, "pages")
            text_alignment_debug_dir = os.path.join(
                self.output_dir,
                "debug",
                "text-alignment",
            )
            os.makedirs(self.output_dir, exist_ok=True)
            os.makedirs(images_dir, exist_ok=True)
            os.makedirs(pages_dir, exist_ok=True)
            if self.debug:
                os.makedirs(text_alignment_debug_dir, exist_ok=True)

        # 2. Per-page processing
        pages_to_process = []
        for page in document.pages:
            if self.page_indices is not None and page.index not in self.page_indices:
                continue
            pages_to_process.append(page.index)

        num_workers = self.num_workers
        if num_workers is None:
            if len(pages_to_process) > 1:
                num_workers = min(4, os.cpu_count() or 1)
            else:
                num_workers = 1

        is_parallel = len(pages_to_process) > 1 and num_workers > 1 and self.backend != "sequential"

        if is_parallel:
            if self.backend == "process":
                global _PROCESS_POOL, _PROCESS_POOL_WORKERS
                if _PROCESS_POOL is None or _PROCESS_POOL_WORKERS != num_workers:
                    if _PROCESS_POOL is not None:
                        _PROCESS_POOL.shutdown()
                    from concurrent.futures import ProcessPoolExecutor
                    _PROCESS_POOL = ProcessPoolExecutor(max_workers=num_workers)
                    _PROCESS_POOL_WORKERS = num_workers

                futures = []
                for page_index in pages_to_process:
                    page = document.pages[page_index]
                    futures.append(
                        _PROCESS_POOL.submit(
                            _process_page_process_worker,
                            self.pdf_path,
                            page_index,
                            images_dir,
                            pages_dir,
                            text_alignment_debug_dir,
                            self.render_dpi,
                            self.seal_coords,
                            self.use_ml,
                            self._ml_model_path,
                            self._ml_confidence,
                            self.debug,
                            self._table_config,
                            page.size,
                            page.rotation,
                        )
                    )
                for future in futures:
                    page_index, populated_page, stage_timings, total_page_time = future.result()
                    document.pages[page_index] = populated_page
                    for stage, elapsed in stage_timings.items():
                        self._stage_totals[stage] = self._stage_totals.get(stage, 0.0) + elapsed
                    self._record_page_total(page_index, total_page_time)
            else:
                from concurrent.futures import ThreadPoolExecutor
                def process_page_job(page_index: int):
                    thread_doc = fitz.open(self.pdf_path)
                    try:
                        self._process_single_page(
                            page_index,
                            document,
                            images_dir,
                            pages_dir,
                            text_alignment_debug_dir,
                            thread_doc,
                        )
                    finally:
                        thread_doc.close()

                with ThreadPoolExecutor(max_workers=num_workers) as executor:
                    list(executor.map(process_page_job, pages_to_process))
        else:
            pdf_doc = fitz.open(self.pdf_path)
            try:
                for page_index in pages_to_process:
                    self._process_single_page(
                        page_index,
                        document,
                        images_dir,
                        pages_dir,
                        text_alignment_debug_dir,
                        pdf_doc,
                    )
            finally:
                pdf_doc.close()

        # 3. Output writers
        if self.output_dir is not None:
            self._time_stage(
                "write_output_json",
                lambda: JSONWriter().write(
                    document, os.path.join(self.output_dir, "output.json")
                ),
            )
            self._time_stage(
                "write_output_md",
                lambda: MarkdownWriter().write(
                    document, os.path.join(self.output_dir, "output.md")
                ),
            )

        total_elapsed = perf_counter() - overall_start
        report = self._build_timing_report(document.page_count, total_elapsed)
        if self.output_dir is not None:
            self._write_timing_report(self.output_dir, report)
        print(self._format_timing_report(report))

        return document
