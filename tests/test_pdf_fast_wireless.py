import pytest

from hexai_pdf_parser.rust_adapter import (
    build_text_runs,
    build_atoms,
    merge_wrapped_rows,
    infer_output_order_mode,
    recover_native_candidates,
)


def _rect(x0, y0, x1, y1):
    return {"schema_version": 1, "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1)}


def _span(text, x0, y0, x1, y1, order=0, font="SimSun", size=10.0, block=0, line=0):
    chars = [
        {"schema_version": 1, "text": ch, "rect": _rect(x0 + i * 5, y0, x0 + (i + 1) * 5, y1), "order": i}
        for i, ch in enumerate(text)
    ]
    return {
        "schema_version": 1,
        "text": text,
        "rect": _rect(x0, y0, x1, y1),
        "font": font,
        "size": size,
        "flags": 0,
        "order": order,
        "characters": chars,
        "source_position": {"schema_version": 1, "block": block, "line": line},
        "block": block,
        "line": line,
    }


def _run(text, x0, y0, x1, y1, order=0):
    return {
        "schema_version": 1,
        "text": text,
        "rect": _rect(x0, y0, x1, y1),
        "span_refs": [order],
        "source_start": order,
        "source_end": order,
        "order": order,
    }


def _atom(text, x0, y0, x1, y1, order=0, row_hint=None, col_hint=None):
    return {
        "schema_version": 1,
        "text": text,
        "rect": _rect(x0, y0, x1, y1),
        "run_refs": [order],
        "row_hint": row_hint,
        "col_hint": col_hint,
        "order": order,
    }


class TestBuildTextRuns:
    def test_cjk_whitelist_spaced_pair_merges(self):
        region = _rect(0, 0, 500, 500)
        spans = [
            _span("合", 10, 10, 20, 20, order=0, size=10.0, block=0, line=0),
            _span("计", 40, 10, 50, 20, order=1, size=10.0, block=0, line=0),
        ]
        runs = build_text_runs(spans, region)
        assert len(runs) == 1
        assert runs[0]["text"] == "合计"

    def test_cjk_non_whitelist_spaced_pair_keeps_separate(self):
        region = _rect(0, 0, 500, 500)
        spans = [
            _span("男", 10, 10, 20, 20, order=0, size=10.0, block=0, line=0),
            _span("女", 35, 10, 45, 20, order=1, size=10.0, block=0, line=0),
        ]
        runs = build_text_runs(spans, region)
        assert len(runs) == 2
        assert [r["text"] for r in runs] == ["男", "女"]

    def test_ascii_and_mixed_text(self):
        region = _rect(0, 0, 500, 500)
        spans = [
            _span("Item", 10, 10, 40, 20, order=0, size=10.0, block=0, line=0),
            _span("No.", 42, 10, 60, 20, order=1, size=10.0, block=0, line=0),
        ]
        runs = build_text_runs(spans, region)
        assert len(runs) == 1


class TestBuildAtoms:
    def test_build_atoms_from_runs(self):
        region = _rect(0, 0, 500, 500)
        runs = [
            _run("合计", 10, 10, 50, 20, order=0),
            _run("100.00", 100, 10, 150, 20, order=1),
        ]
        atoms = build_atoms(runs, region)
        assert len(atoms) == 2
        assert atoms[0]["text"] == "合计"
        assert atoms[1]["text"] == "100.00"


class TestMergeWrappedRows:
    def test_merge_continuation_atom(self):
        atoms = [
            _atom("主要产品及", 10, 10, 80, 20, order=0),
            _atom("业务性质", 10, 22, 80, 32, order=1),
        ]
        merged = merge_wrapped_rows(atoms, tolerance=5.0)
        assert len(merged) == 1
        assert "主要产品及" in merged[0]["text"] and "业务性质" in merged[0]["text"]


class TestInferOutputOrderMode:
    def test_default_row_interleaved(self):
        atoms = [
            _atom("A", 10, 10, 30, 20, order=0),
            _atom("B", 50, 10, 70, 20, order=1),
            _atom("C", 10, 30, 30, 40, order=2),
            _atom("D", 50, 30, 70, 40, order=3),
        ]
        mode = infer_output_order_mode(atoms)
        assert mode["value"] == "row_interleaved"


class TestRecoverNativeCandidates:
    def test_recover_candidate_grid(self):
        page = {"schema_version": 1, "width": 595.0, "height": 842.0, "rotation": 0}
        region = {"schema_version": 1, "rect": _rect(0, 0, 500, 500), "source_order": 0, "allowed": True}
        config = {
            "schema_version": 1,
            "line_tolerance": 2.0,
            "row_tolerance": 2.0,
            "column_tolerance": 2.0,
            "span_tolerance": 2.0,
            "numeric_tolerance": 2.0,
        }
        spans = [
            _span("项目", 10, 10, 40, 20, order=0, block=0, line=0),
            _span("金额", 100, 10, 130, 20, order=1, block=0, line=0),
            _span("营收", 10, 30, 40, 40, order=2, block=0, line=1),
            _span("500", 100, 30, 130, 40, order=3, block=0, line=1),
        ]
        input_dto = {
            "schema_version": 1,
            "page": page,
            "spans": spans,
            "region": region,
            "config": config,
        }
        out = recover_native_candidates(input_dto)
        assert len(out["candidates"]) >= 1
        assert len(out["atoms"]) >= 4

    def test_page_spy_no_get_text_words(self):
        class PageSpy:
            def __init__(self):
                self.call_counts = {"words": 0}
            def get_text(self, kind, **kwargs):
                if kind == "words":
                    self.call_counts["words"] += 1
                return []

        page = PageSpy()
        input_dto = {
            "schema_version": 1,
            "page": {"schema_version": 1, "width": 595.0, "height": 842.0, "rotation": 0},
            "spans": [],
            "region": {"schema_version": 1, "rect": _rect(0, 0, 500, 500), "source_order": 0, "allowed": True},
            "config": {
                "schema_version": 1,
                "line_tolerance": 2.0,
                "row_tolerance": 2.0,
                "column_tolerance": 2.0,
                "span_tolerance": 2.0,
                "numeric_tolerance": 2.0,
            },
        }
        out = recover_native_candidates(input_dto)
        assert page.call_counts["words"] == 0
