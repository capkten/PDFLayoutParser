"""Pipeline: orchestrates the full PDF processing flow.

This module ties together all individual modules (loader, text_extractor,
layout_mapper, image_extractor, table_extractor, layout_builder,
json_writer, markdown_writer, render_engine) into a single end-to-end
processing pipeline.
"""

import json
import os
import statistics
from time import perf_counter
from typing import List, Optional

import fitz

from pdflayoutparser.image_extractor import ImageExtractor
from pdflayoutparser.json_writer import JSONWriter
from pdflayoutparser.layout_builder import LayoutBuilder
from pdflayoutparser.layout_mapper import LayoutMapper
from pdflayoutparser.loader import Loader
from pdflayoutparser.markdown_writer import MarkdownWriter
from pdflayoutparser.models import BBox, Document, LayoutElement, Seal
from pdflayoutparser.render_engine import RenderEngine
from pdflayoutparser.table_extractor import TableExtractor
from pdflayoutparser.text_extractor import TextExtractor


class Pipeline:
    """Orchestrate the full PDF processing flow.

    Example::

        pipeline = Pipeline("doc.pdf", output_dir="/tmp/out", render_dpi=200)
        document = pipeline.run()
    """

    def __init__(
        self,
        pdf_path: str,
        output_dir: str,
        render_dpi: int = 200,
        seal_coords: Optional[List[dict]] = None,
    ):
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.render_dpi = render_dpi
        self.seal_coords = seal_coords or []
        self._stage_totals: dict[str, float] = {}
        self._page_totals: list[dict[str, float]] = []

    def _time_stage(self, stage: str, func):
        """Measure and accumulate elapsed time for a callable stage."""
        start = perf_counter()
        result = func()
        elapsed = perf_counter() - start
        self._stage_totals[stage] = self._stage_totals.get(stage, 0.0) + elapsed
        return result, elapsed

    def _record_page_total(self, page_index: int, elapsed: float) -> None:
        self._page_totals.append(
            {"page_index": page_index, "total_seconds": elapsed}
        )

    def _match_seals(self, page_index: int) -> list[Seal]:
        """Build seal objects for a page index."""
        seals: list[Seal] = []
        for coord in self.seal_coords:
            if coord.get("page_index") != page_index:
                continue
            seals.append(
                Seal(
                    bbox=BBox(
                        coord["x0"],
                        coord["y0"],
                        coord["x1"],
                        coord["y1"],
                    ),
                    page_index=page_index,
                )
            )
        return seals

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
        images_dir = os.path.join(self.output_dir, "images")
        pages_dir = os.path.join(self.output_dir, "pages")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(pages_dir, exist_ok=True)

        # 2. Per-page processing
        pdf_doc = fitz.open(self.pdf_path)
        try:
            for page in document.pages:
                page_start = perf_counter()
                page_handle = pdf_doc[page.index]

                # a. Text extraction
                page.blocks, _ = self._time_stage(
                    "text_extract",
                    lambda: TextExtractor().extract_blocks(page_handle),
                )

                # b. Layout mapping (text -> LayoutElements)
                text_elements, _ = self._time_stage(
                    "layout_map",
                    lambda: LayoutMapper().map_blocks(page.blocks),
                )

                # c. Table extraction
                page.tables, _ = self._time_stage(
                    "table_extract",
                    lambda: TableExtractor().extract(page_handle),
                )

                # d. Image extraction
                page.images, _ = self._time_stage(
                    "image_extract",
                    lambda: ImageExtractor(images_dir).extract(
                        self.pdf_path, page.index
                    ),
                )

                # e. Seals
                seals, _ = self._time_stage(
                    "seal_match",
                    lambda: self._match_seals(page.index),
                )
                page.seals = seals

                # f. Layout building
                layout_elements, _ = self._time_stage(
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

                layout_elements = LayoutBuilder.sort_layout_elements(
                    layout_elements
                )

                # h. Set layout_elements on the page
                page.layout_elements = layout_elements

                # i. Render
                page.render, _ = self._time_stage(
                    "render",
                    lambda: RenderEngine(
                        self.output_dir, self.render_dpi
                    ).render(self.pdf_path, page.index),
                )

                # j. Per-page output
                page_json_path = os.path.join(
                    pages_dir, f"page-{page.index:03d}.json"
                )
                page_md_path = os.path.join(
                    pages_dir, f"page-{page.index:03d}.md"
                )
                self._time_stage(
                    "write_page_json",
                    lambda: JSONWriter().write_page(page, page_json_path),
                )
                self._time_stage(
                    "write_page_md",
                    lambda: MarkdownWriter().write_page(page, page_md_path),
                )
                self._record_page_total(page.index, perf_counter() - page_start)
        finally:
            pdf_doc.close()

        # 3. Output writers
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
        self._write_timing_report(self.output_dir, report)
        print(self._format_timing_report(report))

        return document
