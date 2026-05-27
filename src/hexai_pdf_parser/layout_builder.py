"""Layout builder: aggregates text, table, and image elements into a unified layout.

This module consumes the output of layout_mapper (text LayoutElements) together
with detected tables and images, and produces a single ordered list of
LayoutElements per page.
"""

from typing import List

from hexai_pdf_parser.models import Image, LayoutElement, Table


class LayoutBuilder:
    """Aggregates text, table, and image elements into a single ordered list."""

    def build(
        self,
        elements: List[LayoutElement],
        tables: List[Table],
        images: List[Image],
    ) -> List[LayoutElement]:
        """Combine text elements with tables and images.

        Text elements that fall inside a table's bounding box are removed
        to avoid duplicate output (the table already contains the text).

        Args:
            elements: Text LayoutElements from layout_mapper.
            tables: Detected tables on the page.
            images: Detected images on the page.

        Returns:
            A combined list of LayoutElements with sequential order values.
        """
        # Filter out text elements that are fully inside any table
        filtered = [
            e for e in elements
            if not self._inside_any_table(e.bbox, tables)
        ]

        combined: List[LayoutElement] = list(filtered)

        for table in tables:
            combined.append(
                LayoutElement(
                    type="table",
                    bbox=table.bbox,
                    order=len(combined),
                    content=table,
                )
            )

        for image in images:
            combined.append(
                LayoutElement(
                    type="image",
                    bbox=image.bbox,
                    order=len(combined),
                    content=image,
                )
            )

        return self.sort_layout_elements(combined)

    @staticmethod
    def sort_layout_elements(
        elements: List[LayoutElement],
    ) -> List[LayoutElement]:
        """Sort layout elements in page reading order and renumber them."""
        sorted_elements = sorted(
            elements,
            key=lambda e: (
                e.bbox.y0,
                e.bbox.x0,
                e.bbox.y1,
                e.bbox.x1,
            ),
        )
        for order, element in enumerate(sorted_elements):
            element.order = order
        return sorted_elements

    def _inside_any_table(self, bbox, tables: List[Table]) -> bool:
        """Check if *bbox* overlaps any table's bbox."""
        for t in tables:
            tb = t.bbox
            if (
                bbox.x0 < tb.x1
                and bbox.x1 > tb.x0
                and bbox.y0 < tb.y1
                and bbox.y1 > tb.y0
            ):
                return True
        return False
