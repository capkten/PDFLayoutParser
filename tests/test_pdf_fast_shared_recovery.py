# -*- coding: utf-8 -*-
import pytest

from hexai_pdf_parser.rust_adapter import (
    table_quality,
    select_candidates,
    recover_wireless_tables,
)


def _rect(x0, y0, x1, y1):
    return {'schema_version': 1, 'x0': float(x0), 'y0': float(y0), 'x1': float(x1), 'y1': float(y1)}


def _cell(text, row, col, x0, y0, x1, y1, rowspan=1, colspan=1):
    return {
        'schema_version': 1,
        'text': text,
        'row': int(row),
        'col': int(col),
        'rect': _rect(x0, y0, x1, y1),
        'rowspan': int(rowspan),
        'colspan': int(colspan),
        'source': None,
    }


def _candidate(x0, y0, x1, y1, rows, cols, cells, confidence=0.9, source='wireless_span_recovery'):
    return {
        'schema_version': 1,
        'rect': _rect(x0, y0, x1, y1),
        'source': source,
        'confidence': float(confidence),
        'rows': int(rows),
        'cols': int(cols),
        'cells': cells,
    }


class TestTableQuality:
    def test_higher_confidence_wins(self):
        c1 = _candidate(0, 0, 100, 100, 2, 2, [_cell('A', 0, 0, 0, 0, 50, 50)], confidence=0.8)
        c2 = _candidate(0, 0, 100, 100, 2, 2, [_cell('A', 0, 0, 0, 0, 50, 50)], confidence=0.9)
        assert table_quality(c2) > table_quality(c1)

    def test_more_populated_cells_wins_on_equal_confidence(self):
        c1 = _candidate(0, 0, 100, 100, 2, 2, [_cell('A', 0, 0, 0, 0, 50, 50), _cell('', 0, 1, 50, 0, 100, 50)], confidence=0.85)
        c2 = _candidate(0, 0, 100, 100, 2, 2, [_cell('A', 0, 0, 0, 0, 50, 50), _cell('B', 0, 1, 50, 0, 100, 50)], confidence=0.85)
        assert table_quality(c2) > table_quality(c1)


class TestSelectCandidates:
    def test_select_candidates_overlapping_resolution(self):
        c1 = _candidate(0, 0, 100, 100, 2, 2, [_cell('A', 0, 0, 0, 0, 50, 50)], confidence=0.7)
        c2 = _candidate(10, 10, 100, 100, 2, 2, [_cell('A', 0, 0, 10, 10, 50, 50), _cell('B', 0, 1, 50, 10, 100, 50)], confidence=0.9)
        selected = select_candidates([c1, c2], excluded=[], allowed=[])
        assert len(selected) == 1
        assert selected[0]['confidence'] == 0.9

    def test_select_candidates_excluded_filtering(self):
        c1 = _candidate(0, 0, 100, 100, 2, 2, [_cell('A', 0, 0, 0, 0, 50, 50)], confidence=0.9)
        excluded = [_rect(10, 10, 50, 50)]
        selected = select_candidates([c1], excluded=excluded, allowed=[])
        assert len(selected) == 0


class TestRecoverWirelessTables:
    def test_recover_wireless_tables_pure_dto(self):
        page = {'schema_version': 1, 'width': 595.0, 'height': 842.0, 'rotation': 0}
        spans = [
            {
                'schema_version': 1,
                'text': '项目',
                'rect': _rect(10, 10, 40, 20),
                'font': 'SimSun',
                'size': 10.0,
                'flags': 0,
                'order': 0,
                'characters': [],
                'source_position': {'schema_version': 1, 'block': 0, 'line': 0},
                'block': 0,
                'line': 0,
            },
            {
                'schema_version': 1,
                'text': '金额',
                'rect': _rect(100, 10, 140, 20),
                'font': 'SimSun',
                'size': 10.0,
                'flags': 0,
                'order': 1,
                'characters': [],
                'source_position': {'schema_version': 1, 'block': 0, 'line': 0},
                'block': 0,
                'line': 0,
            },
            {
                'schema_version': 1,
                'text': '收入',
                'rect': _rect(10, 30, 40, 40),
                'font': 'SimSun',
                'size': 10.0,
                'flags': 0,
                'order': 2,
                'characters': [],
                'source_position': {'schema_version': 1, 'block': 0, 'line': 1},
                'block': 0,
                'line': 1,
            },
            {
                'schema_version': 1,
                'text': '500',
                'rect': _rect(100, 30, 130, 40),
                'font': 'SimSun',
                'size': 10.0,
                'flags': 0,
                'order': 3,
                'characters': [],
                'source_position': {'schema_version': 1, 'block': 0, 'line': 1},
                'block': 0,
                'line': 1,
            },
        ]
        region = {'schema_version': 1, 'rect': _rect(0, 0, 500, 500), 'source_order': 0, 'allowed': True}
        config = {
            'schema_version': 1,
            'line_tolerance': 2.0,
            'row_tolerance': 2.0,
            'column_tolerance': 2.0,
            'span_tolerance': 2.0,
            'numeric_tolerance': 2.0,
        }
        input_dto = {
            'schema_version': 1,
            'page': page,
            'spans': spans,
            'regions': [region],
            'config': config,
        }
        out = recover_wireless_tables(input_dto)
        assert 'candidates' in out
        assert len(out['candidates']) >= 1

    def test_page_spy_no_get_text_words(self):
        class PageSpy:
            def __init__(self):
                self.calls = []
            def get_text(self, kind, **kwargs):
                self.calls.append(kind)
                return []

        page = PageSpy()
        assert 'words' not in page.calls
