"""Layout builder: aggregates text, table, and image elements into a unified layout.

This module consumes the output of layout_mapper (text LayoutElements) together
with detected tables and images, and produces a single ordered list of
LayoutElements per page.
"""

from typing import List

from hexai_pdf_parser.models import Image, LayoutElement, Table


TEXT_TABLE_IOU_THRESHOLD = 0.5


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
        # Filter out text elements substantially covered by any table.
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
        """Check if *bbox* is a table duplicate or substantially covered.

        Text wholly inside a table is already represented by table cells, so
        it must be filtered even though its IoU with the whole table is small.
        Blocks that cross a table boundary use the stricter IoU threshold.
        """
        bbox_area = max(0.0, bbox.x1 - bbox.x0) * max(0.0, bbox.y1 - bbox.y0)
        if bbox_area == 0:
            return False

        for t in tables:
            tb = t.bbox
            intersection_width = max(0.0, min(bbox.x1, tb.x1) - max(bbox.x0, tb.x0))
            intersection_height = max(0.0, min(bbox.y1, tb.y1) - max(bbox.y0, tb.y0))
            intersection_area = intersection_width * intersection_height
            table_area = max(0.0, tb.x1 - tb.x0) * max(0.0, tb.y1 - tb.y0)
            union_area = bbox_area + table_area - intersection_area

            if (
                bbox.x0 >= tb.x0
                and bbox.y0 >= tb.y0
                and bbox.x1 <= tb.x1
                and bbox.y1 <= tb.y1
            ):
                return True

            if union_area > 0 and intersection_area / union_area > TEXT_TABLE_IOU_THRESHOLD:
                return True
        return False
