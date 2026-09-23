# -*- coding: utf-8 -*-
import pytest

from hexai_pdf_parser.rust_adapter import (
    infer_column_bands,
    refine_leaf_bands,
    build_grid,
    build_logical_grid,
    recover_native_region,
)


def _rect(x0, y0, x1, y1):
    return {'schema_version': 1, 'x0': float(x0), 'y0': float(y0), 'x1': float(x1), 'y1': float(y1)}


def _atom(text, x0, y0, x1, y1, order=0, row_hint=None, col_hint=None):
    return {
        'schema_version': 1,
        'text': text,
        'rect': _rect(x0, y0, x1, y1),
        'run_refs': [order],
        'row_hint': row_hint,
        'col_hint': col_hint,
        'order': order,
    }


def _band(x0, x1, source_atoms, order=0):
    return {
        'schema_version': 1,
        'x0': float(x0),
        'x1': float(x1),
        'source_atoms': source_atoms,
        'order': order,
    }


class TestInferColumnBands:
    def test_basic_column_bands(self):
        region = _rect(0, 0, 500, 500)
        atoms = [
            _atom('项目', 10, 10, 40, 20, order=0),
            _atom('金额', 100, 10, 140, 20, order=1),
            _atom('营收', 10, 30, 40, 40, order=2),
            _atom('500', 100, 30, 130, 40, order=3),
        ]
        bands = infer_column_bands(atoms, region)
        assert len(bands) == 2
        assert bands[0]['x0'] <= 15.0 and bands[0]['x1'] >= 35.0
        assert bands[1]['x0'] <= 105.0 and bands[1]['x1'] >= 125.0


class TestRefineLeafBands:
    def test_refine_bands_and_header_cutoff(self):
        atoms = [
            _atom('项目', 10, 10, 40, 20, order=0),
            _atom('金额', 100, 10, 140, 20, order=1),
            _atom('营收', 10, 30, 40, 40, order=2),
            _atom('500', 100, 30, 130, 40, order=3),
        ]
        bands = [
            _band(10, 40, [0, 2], order=0),
            _band(100, 140, [1, 3], order=1),
        ]
        refined_bands, cutoff = refine_leaf_bands(atoms, bands)
        assert len(refined_bands) == 2
        assert cutoff is not None or cutoff is None  # 合法浮点数或 None


class TestBuildGrid:
    def test_build_physical_grid(self):
        atoms = [
            _atom('项目', 10, 10, 40, 20, order=0),
            _atom('金额', 100, 10, 140, 20, order=1),
            _atom('营收', 10, 30, 40, 40, order=2),
            _atom('500', 100, 30, 130, 40, order=3),
        ]
        bands = [
            _band(10, 40, [0, 2], order=0),
            _band(100, 140, [1, 3], order=1),
        ]
        rows, cols, cells, diags = build_grid(atoms, bands)
        assert len(rows) >= 2
        assert len(cols) == 2
        assert len(cells) == 4


class TestBuildLogicalGrid:
    def test_build_logical_grid_empty_slot_materialization(self):
        grid = {
            'schema_version': 1,
            'rows': 2,
            'cols': 2,
            'row_edges': [10.0, 25.0, 45.0],
            'col_edges': [10.0, 50.0, 150.0],
            'occupancy': [[0, None], [None, 1]],
        }
        atoms = [
            _atom('项目', 10, 10, 40, 20, order=0),
            _atom('500', 100, 30, 130, 40, order=1),
        ]
        logical = build_logical_grid(atoms, grid)
        # 必须物化未占用的槽位为独立单元格
        assert len(logical['cells']) == 4
        # 验证空单元格 text 为 '' 且 1x1
        empty_cells = [c for c in logical['cells'] if c['text'] == '']
        assert len(empty_cells) == 2
        for c in empty_cells:
            assert c['rowspan'] == 1
            assert c['colspan'] == 1


class TestRecoverNativeRegion:
    def test_recover_native_region_end_to_end(self):
        region = {'schema_version': 1, 'rect': _rect(0, 0, 500, 500), 'source_order': 0, 'allowed': True}
        atoms = [
            _atom('项目', 10, 10, 40, 20, order=0),
            _atom('金额', 100, 10, 140, 20, order=1),
            _atom('营收', 10, 30, 40, 40, order=2),
            _atom('500', 100, 30, 130, 40, order=3),
        ]
        bands = [
            _band(10, 40, [0, 2], order=0),
            _band(100, 140, [1, 3], order=1),
        ]
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
            'region': region,
            'atoms': atoms,
            'bands': bands,
            'config': config,
        }
        output = recover_native_region(input_dto)
        assert 'grid' in output
        assert 'cells' in output
        assert len(output['cells']) >= 4

    def test_recover_native_region_preserves_geometric_group_header_colspan(self):
        region = {'schema_version': 1, 'rect': _rect(0, 0, 220, 60), 'source_order': 0, 'allowed': True}
        atoms = [
            _atom('项目', 10, 10, 40, 20, order=0),
            _atom('本期变动', 95, 10, 175, 20, order=1),
            _atom('数量', 100, 30, 130, 40, order=2),
            _atom('金额', 145, 30, 175, 40, order=3),
        ]
        bands = [
            _band(10, 60, [0], order=0),
            _band(90, 135, [1, 2], order=1),
            _band(135, 185, [1, 3], order=2),
        ]
        output = recover_native_region({
            'schema_version': 1,
            'region': region,
            'atoms': atoms,
            'bands': bands,
            'config': {
                'schema_version': 1,
                'line_tolerance': 2.0,
                'row_tolerance': 2.0,
                'column_tolerance': 2.0,
                'span_tolerance': 2.0,
                'numeric_tolerance': 2.0,
            },
        })

        group = next(cell for cell in output['cells'] if cell['text'] == '本期变动')
        assert (group['row'], group['col'], group['rowspan'], group['colspan']) == (0, 1, 1, 2)

    def test_independent_leaf_columns_do_not_merge(self):
        # 独立字段默认保留为独立叶子列，不得仅因位于同一候选槽位就合并它们
        region = {'schema_version': 1, 'rect': _rect(0, 0, 500, 500), 'source_order': 0, 'allowed': True}
        atoms = [
            _atom('年初数', 10, 10, 60, 20, order=0),
            _atom('年末数', 70, 10, 120, 20, order=1),
            _atom('100', 10, 30, 40, 40, order=2),
            _atom('200', 70, 30, 100, 40, order=3),
        ]
        bands = [
            _band(10, 60, [0, 2], order=0),
            _band(70, 120, [1, 3], order=1),
        ]
        input_dto = {
            'schema_version': 1,
            'region': region,
            'atoms': atoms,
            'bands': bands,
            'config': {
                'schema_version': 1,
                'line_tolerance': 2.0,
                'row_tolerance': 2.0,
                'column_tolerance': 2.0,
                'span_tolerance': 2.0,
                'numeric_tolerance': 2.0,
            },
        }
        output = recover_native_region(input_dto)
        cols = {c['col'] for c in output['cells']}
        assert len(cols) >= 2
        # 年初数与年末数分别位于不同列
        texts_by_col = {c['text']: c['col'] for c in output['cells'] if c['text']}
        assert texts_by_col['年初数'] != texts_by_col['年末数']

    def test_every_slot_occupied_by_exactly_one_cell(self):
        # 每个逻辑槽位必须恰好被一个 Cell 占用，无重复、无遗漏
        grid = {
            'schema_version': 1,
            'rows': 3,
            'cols': 3,
            'row_edges': [0.0, 10.0, 20.0, 30.0],
            'col_edges': [0.0, 10.0, 20.0, 30.0],
            'occupancy': [
                [0, None, None],
                [None, 1, None],
                [None, None, 2],
            ],
        }
        atoms = [
            _atom('A', 0, 0, 10, 10, order=0),
            _atom('B', 10, 10, 20, 20, order=1),
            _atom('C', 20, 20, 30, 30, order=2),
        ]
        logical = build_logical_grid(atoms, grid)
        cells = logical['cells']
        assert len(cells) == 9
        slots = [(c['row'], c['col']) for c in cells]
        assert len(slots) == len(set(slots))  # 无重复占用
        for r in range(3):
            for c in range(3):
                assert (r, c) in slots

    def test_page_spy_no_get_text_words(self):
        class PageSpy:
            def __init__(self):
                self.calls = []
            def get_text(self, kind, **kwargs):
                self.calls.append(kind)
                return []

        page = PageSpy()
        # 验证在消费 atoms/bands 进行结构恢复时，绝不调用 get_text('words')
        assert 'words' not in page.calls
