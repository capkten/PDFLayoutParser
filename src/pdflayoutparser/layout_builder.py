"""Layout builder: aggregates text, table, and image elements into a unified layout.

This module consumes the output of layout_mapper (text LayoutElements) together
with detected tables and images, and produces a single ordered list of
LayoutElements per page.
"""

from typing import List

from pdflayoutparser.models import Image, LayoutElement, Table


class LayoutBuilder:
    """Aggregates text, table, and image elements into a single ordered list."""

    def build(
        self,
        elements: List[LayoutElement],
        tables: List[Table],
        images: List[Image],
    ) -> List[LayoutElement]:
        """Combine text elements with tables and images.

        Args:
            elements: Text LayoutElements from layout_mapper.
            tables: Detected tables on the page.
            images: Detected images on the page.

        Returns:
            A combined list of LayoutElements with sequential order values.
        """
        combined: List[LayoutElement] = list(elements)

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

        return combined
