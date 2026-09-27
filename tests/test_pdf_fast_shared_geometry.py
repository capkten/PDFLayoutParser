import pytest

from hexai_pdf_parser.rust_adapter import (
    rect_overlap,
    filter_regions,
    cluster_rows,
    cluster_columns,
    stable_output_order,
)


def _rect(x0, y0, x1, y1):
    return {'schema_version': 1, 'x0': float(x0), 'y0': float(y0), 'x1': float(x1), 'y1': float(y1)}


def _ordered_rect(id_, x0, y0, x1, y1, order=0):
    return {
        'schema_version': 1,
        'id': int(id_),
        'rect': _rect(x0, y0, x1, y1),
        'order': int(order),
    }


def _table_candidate(x0, y0, x1, y1, source='test', confidence=0.95, rows=2, cols=2):
    return {
        'schema_version': 1,
        'rect': _rect(x0, y0, x1, y1),
        'source': source,
        'confidence': confidence,
        'rows': rows,
        'cols': cols,
        'cells': [],
    }


class TestRectOverlap:
    def test_positive_area_overlap(self):
        a = _rect(10, 10, 50, 50)
        b = _rect(30, 30, 70, 70)
        assert rect_overlap(a, b, strict=True) is True
        assert rect_overlap(a, b, strict=False) is True

    def test_edge_touching_strict_false(self):
        a = _rect(10, 10, 50, 50)
        b = _rect(50, 10, 90, 50)
        assert rect_overlap(a, b, strict=True) is False
        assert rect_overlap(a, b, strict=False) is True

    def test_corner_touching_strict_false(self):
        a = _rect(10, 10, 50, 50)
        b = _rect(50, 50, 90, 90)
        assert rect_overlap(a, b, strict=True) is False
        assert rect_overlap(a, b, strict=False) is True

    def test_disjoint_rectangles(self):
        a = _rect(10, 10, 50, 50)
        b = _rect(60, 60, 90, 90)
        assert rect_overlap(a, b, strict=True) is False
        assert rect_overlap(a, b, strict=False) is False

    def test_contained_rectangle(self):
        outer = _rect(0, 0, 100, 100)
        inner = _rect(20, 20, 40, 40)
        assert rect_overlap(outer, inner, strict=True) is True
        assert rect_overlap(outer, inner, strict=False) is True


class TestFilterRegions:
    def test_empty_inputs(self):
        assert filter_regions([], [], []) == []

    def test_no_filter_rules_keeps_all(self):
        regions = [_rect(10, 10, 50, 50), _rect(60, 60, 100, 100)]
        res = filter_regions(regions, excluded=[], allowed=[])
        assert len(res) == 2

    def test_excluded_filter(self):
        regions = [_rect(10, 10, 50, 50), _rect(60, 60, 100, 100)]
        excluded = [_rect(0, 0, 30, 30)]
        res = filter_regions(regions, excluded=excluded, allowed=[])
        assert len(res) == 1
        assert res[0]['x0'] == 60.0

    def test_allowed_filter(self):
        regions = [_rect(10, 10, 50, 50), _rect(60, 60, 100, 100)]
        allowed = [_rect(5, 5, 55, 55)]
        res = filter_regions(regions, excluded=[], allowed=allowed)
        assert len(res) == 1
        assert res[0]['x0'] == 10.0

    def test_both_excluded_and_allowed(self):
        regions = [
            _rect(10, 10, 50, 50),
            _rect(60, 10, 100, 50),
            _rect(10, 60, 50, 100),
        ]
        allowed = [_rect(0, 0, 120, 60)]
        excluded = [_rect(5, 5, 25, 25)]
        res = filter_regions(regions, excluded=excluded, allowed=allowed)
        assert len(res) == 1
        assert res[0]['x0'] == 60.0


class TestRowClustering:
    def test_empty_rows(self):
        assert cluster_rows([], tolerance=3.0) == []

    def test_single_row_multiple_items(self):
        items = [
            _ordered_rect(2, 60, 10, 90, 20, order=2),
            _ordered_rect(1, 10, 11, 40, 21, order=1),
        ]
        clusters = cluster_rows(items, tolerance=5.0)
        assert len(clusters) == 1
        c = clusters[0]
        assert c['row_index'] == 0
        assert c['item_indices'] == [1, 2]
        assert c['y0'] == 10.0
        assert c['y1'] == 21.0

    def test_multiple_rows_clustering(self):
        items = [
            _ordered_rect(1, 10, 10, 40, 20),
            _ordered_rect(2, 50, 10, 80, 20),
            _ordered_rect(3, 10, 40, 40, 50),
            _ordered_rect(4, 50, 40, 80, 50),
        ]
        clusters = cluster_rows(items, tolerance=5.0)
        assert len(clusters) == 2
        assert clusters[0]['row_index'] == 0
        assert clusters[0]['item_indices'] == [1, 2]
        assert clusters[1]['row_index'] == 1
        assert clusters[1]['item_indices'] == [3, 4]


class TestColumnClustering:
    def test_empty_columns(self):
        assert cluster_columns([], tolerance=3.0) == []

    def test_multiple_columns_clustering(self):
        items = [
            _ordered_rect(3, 50, 40, 80, 50),
            _ordered_rect(1, 10, 10, 40, 20),
            _ordered_rect(4, 50, 10, 80, 20),
            _ordered_rect(2, 10, 40, 40, 50),
        ]
        clusters = cluster_columns(items, tolerance=5.0)
        assert len(clusters) == 2
        assert clusters[0]['col_index'] == 0
        assert clusters[0]['item_indices'] == [1, 2]
        assert clusters[1]['col_index'] == 1
        assert clusters[1]['item_indices'] == [4, 3]


class TestStableOutputOrder:
    def test_empty_tables(self):
        assert stable_output_order([]) == []

    def test_ordering_by_geometry_and_source(self):
        tables = [
            _table_candidate(10, 100, 200, 200, source='t2'),
            _table_candidate(10, 50, 200, 80, source='t1'),
            _table_candidate(5, 50, 100, 80, source='t0'),
            _table_candidate(10, 100, 200, 200, source='t3'),
        ]
        ordered = stable_output_order(tables)
        sources = [t['source'] for t in ordered]
        assert sources == ['t0', 't1', 't2', 't3']
