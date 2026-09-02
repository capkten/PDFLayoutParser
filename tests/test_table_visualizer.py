from hexai_pdf_parser.core.models import BBox, Cell, Table
from hexai_pdf_parser.debug.table_visualizer import _compute_cell_grid_rects
import hexai_pdf_parser.debug.table_visualizer as table_visualizer


def test_complete_wireless_recovery_table_still_uses_inferred_grid_rects():
    table = Table(
        bbox=BBox(0, 0, 100, 40),
        rows=2,
        cols=2,
        source="wireless_span_recovery",
        cells=[
            Cell("项目", 0, 0, BBox(10, 5, 20, 10)),
            Cell("", 0, 1, BBox(50, 0, 100, 20)),
            Cell("甲", 1, 0, BBox(10, 25, 20, 30)),
            Cell("10", 1, 1, BBox(60, 25, 70, 30)),
        ],
    )

    rects = _compute_cell_grid_rects(table)

    first = rects[0][1]
    assert (first.x0, first.y0) == (0, 0)
    assert first.x1 > table.cells[0].bbox.x1


def test_visualization_normalizes_fresh_rotated_page(monkeypatch, tmp_path):
    calls = []

    class FakePixmap:
        def save(self, path):
            calls.append(("save", path))

    class FakePage:
        def get_text(self, mode):
            return []

        def new_shape(self):
            class Shape:
                def draw_rect(self, *_args):
                    pass

                def finish(self, **_kwargs):
                    pass

                def commit(self):
                    pass

            return Shape()

        def get_pixmap(self, **_kwargs):
            return FakePixmap()

    class FakeDoc:
        def __getitem__(self, _index):
            return FakePage()

        def close(self):
            pass

    monkeypatch.setattr(table_visualizer.fitz, "open", lambda _source: FakeDoc())
    monkeypatch.setattr(
        table_visualizer,
        "normalize_page_rotation",
        lambda page: calls.append(("normalize", page)),
    )

    output = tmp_path / "page.png"
    table_visualizer.render_table_visualization("rotated.pdf", [], str(output))

    assert calls and calls[0][0] == "normalize"


def test_visualization_passes_page_type_to_visual_annotation(monkeypatch, tmp_path):
    calls = []

    class FakePixmap:
        def save(self, path):
            pass

    class FakePage:
        def get_text(self, mode):
            return []

        def new_shape(self):
            class Shape:
                def draw_rect(self, *_args):
                    pass

                def finish(self, **_kwargs):
                    pass

                def commit(self):
                    pass

            return Shape()

        def get_pixmap(self, **_kwargs):
            return FakePixmap()

    class FakeDoc:
        def __getitem__(self, _index):
            return FakePage()

        def close(self):
            pass

    monkeypatch.setattr(table_visualizer.fitz, "open", lambda _source: FakeDoc())
    monkeypatch.setattr(table_visualizer, "normalize_page_rotation", lambda _page: None)
    monkeypatch.setattr(
        table_visualizer,
        "draw_page_type_label",
        lambda _page, page_type: calls.append(page_type),
        raising=False,
    )

    table_visualizer.render_table_visualization(
        "scanned.pdf",
        [],
        str(tmp_path / "page.png"),
        page_type="scanned",
    )

    assert calls == ["scanned"]


def test_cell_text_box_is_clipped_to_cell_grid_for_broken_font_bbox():
    finishes = []

    class Shape:
        def __init__(self):
            self.rect = None

        def draw_rect(self, rect):
            self.rect = rect

        def finish(self, **kwargs):
            finishes.append((self.rect, kwargs))

        def insert_text(self, *_args, **_kwargs):
            pass

        def commit(self):
            pass

    class Page:
        rect = table_visualizer.fitz.Rect(0, 0, 200, 200)

        def get_text(self, _mode):
            return [(10.0, -100.0, 20.0, 100.0, "A", 0, 0, 0)]

        def new_shape(self):
            return Shape()

    table = Table(
        bbox=BBox(0, 0, 100, 20),
        rows=1,
        cols=1,
        source="line_projection",
        cells=[Cell("A", 0, 0, BBox(0, 0, 100, 20))],
    )

    table_visualizer.draw_tables_on_page(Page(), [table])

    green_rects = [
        rect
        for rect, kwargs in finishes
        if kwargs.get("color") == table_visualizer.LAYOUT_TEXT_COLOR
    ]
    assert len(green_rects) == 1
    assert tuple(green_rects[0]) == (10.0, 0.0, 20.0, 20.0)


def test_cell_text_box_drawn_for_glued_adjacent_words_via_chars():
    finishes = []

    class Shape:
        def __init__(self):
            self.rect = None

        def draw_rect(self, rect):
            self.rect = rect

        def finish(self, **kwargs):
            finishes.append((self.rect, kwargs))

        def insert_text(self, *_args, **_kwargs):
            pass

        def commit(self):
            pass

    class Page:
        rect = table_visualizer.fitz.Rect(0, 0, 500, 500)

        def get_text(self, mode):
            if mode == "words":
                # Glued word whose midpoint x=247.31 falls into col 1 (231.5..290.6), bypassing col 0 (204.0..231.5)
                return [(204.29, 116.61, 290.33, 125.61, "100.0014,403,362.65", 0, 0, 0)]
            if mode == "rawdict":
                return {
                    "blocks": [
                        {
                            "lines": [
                                {
                                    "spans": [
                                        {
                                            "chars": [
                                                {"c": "1", "bbox": (204.29, 116.61, 208.79, 125.61)},
                                                {"c": "0", "bbox": (208.84, 116.61, 213.34, 125.61)},
                                                {"c": "0", "bbox": (213.40, 116.61, 217.90, 125.61)},
                                                {"c": ".", "bbox": (217.83, 116.61, 222.33, 125.61)},
                                                {"c": "0", "bbox": (222.39, 116.61, 226.89, 125.61)},
                                                {"c": "0", "bbox": (226.83, 116.61, 231.33, 125.61)},
                                                {"c": "1", "bbox": (231.77, 116.61, 236.27, 125.61)},
                                                {"c": "4", "bbox": (236.32, 116.61, 240.82, 125.61)},
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            return []

        def new_shape(self):
            return Shape()

    table = Table(
        bbox=BBox(204.0, 108.7, 290.6, 133.2),
        rows=1,
        cols=2,
        source="line_projection",
        cells=[
            Cell("100.00", 0, 0, BBox(204.0, 108.7, 231.5, 133.2)),
            Cell("14", 0, 1, BBox(231.5, 108.7, 290.6, 133.2)),
        ],
    )

    table_visualizer.draw_tables_on_page(Page(), [table])

    green_rects = [
        rect
        for rect, kwargs in finishes
        if kwargs.get("color") == table_visualizer.LAYOUT_TEXT_COLOR
    ]
    # Both cells must have their text bounding boxes rendered
    assert len(green_rects) == 2
    # Col 0 text bbox should correspond to 100.00 (x0=204.29, x1=231.33)
    assert round(green_rects[0].x0, 2) == 204.29
    assert round(green_rects[0].x1, 2) == 231.33
    # Col 1 text bbox should correspond to 14 (x0=231.77, x1=240.82)
    assert round(green_rects[1].x0, 2) == 231.77
    assert round(green_rects[1].x1, 2) == 240.82

