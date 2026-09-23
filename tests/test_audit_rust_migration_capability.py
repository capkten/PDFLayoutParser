from __future__ import annotations

from pathlib import Path
import ast

from scripts.audit_rust_migration_capability import (
    CapabilityUnit,
    _evaluate_capability,
    _classification,
    collect_capabilities,
    collect,
    render,
)


def test_capability_audit_requires_route_tests_and_evidence():
    root = Path(__file__).resolve().parents[1]
    capabilities = {
        item.identifier: item for item in collect_capabilities([root])
    }

    assert capabilities["wired-geometry"].status == "migrated"
    assert capabilities["native-span-structure"].status == "migrated"
    assert capabilities["english-columns-and-cells"].status == "migrated"
    assert capabilities["text-alignment-grid"].status == "migrated"
    assert capabilities["financial-header-tokens"].status == "migrated"
    assert capabilities["pymupdf-page-access"].status == "python_orchestration"


def test_capability_audit_does_not_treat_rust_symbol_as_production_migration(tmp_path):
    rust_root = tmp_path / "rust"
    rust_root.mkdir()
    (rust_root / "fake.rs").write_text("pub fn fake_kernel() {}", encoding="utf-8")
    python_root = tmp_path / "src"
    python_root.mkdir()
    (python_root / "fake.py").write_text("def fake(): pass\n", encoding="utf-8")

    fake = _evaluate_capability(
        tmp_path,
        CapabilityUnit(
            identifier="fake-symbol-only",
            label="fake",
            rust_files=("rust/fake.rs",),
            rust_markers=("pub fn fake_kernel",),
            python_files=("src/fake.py",),
            route_markers=("run_python_or_rust",),
            test_files=("tests/test_fake.py",),
            evidence_globs=("output/fake/*.json",),
        ),
    )
    assert fake.status == "adapter_only"


def test_capability_audit_uses_repository_root_for_source_subdirectory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source_root = root / "src" / "hexai_pdf_parser" / "tables"

    from_root = {
        item.identifier: item for item in collect_capabilities([root])
    }
    from_source = {
        item.identifier: item for item in collect_capabilities([source_root])
    }

    assert from_source == from_root


def test_ast_collect_and_render_use_repository_root_for_source_subdirectory():
    root = Path(__file__).resolve().parents[1]
    source_root = root / "src" / "hexai_pdf_parser" / "tables"

    root_records = collect([root])
    source_records = collect([source_root])
    assert len(source_records) == len(root_records)
    assert source_records == root_records
    assert render(source_records, [source_root], collect_capabilities([source_root])) == render(
        root_records, [root], collect_capabilities([root])
    )


def test_capability_audit_reports_missing_dto_schema_separately(tmp_path):
    rust_root = tmp_path / "rust"
    rust_root.mkdir()
    (rust_root / "fake.rs").write_text("pub fn fake_kernel() {}", encoding="utf-8")
    python_root = tmp_path / "src"
    python_root.mkdir()
    (python_root / "fake.py").write_text(
        "def fake(): pass\nrun_python_or_rust(fake)\n", encoding="utf-8"
    )

    fake = _evaluate_capability(
        tmp_path,
        CapabilityUnit(
            identifier="fake-schema-missing",
            label="fake",
            rust_files=("rust/fake.rs",),
            rust_markers=("pub fn fake_kernel",),
            schema_markers=("schema_version: 1",),
            python_files=("src/fake.py",),
            route_markers=("run_python_or_rust",),
            test_files=("tests/test_fake.py",),
            evidence_globs=("output/fake/*.json",),
        ),
    )
    assert "dto_schema" in fake.missing


def test_ast_audit_classifies_scripts_pages_and_pure_dto_functions():
    script = ast.parse("def build(): return 1").body[0]
    page = ast.parse("def read(page): return page.get_text('words')").body[0]
    dto = ast.parse("def make_dto(x): return {'schema_version': 1, 'x': x}").body[0]
    plain_page_value = ast.parse("def add_one(page): return page + 1").body[0]
    plain_fitz_value = ast.parse("def add_one(fitz): return fitz + 1").body[0]
    plain_page_type_name = ast.parse("def add_one(Page): return Page + 1").body[0]
    plain_drawings_value = ast.parse("def count(drawings): return len(drawings)").body[0]
    fitz_type = ast.parse("def read(page: fitz.Page): return page.get_text('words')").body[0]
    fitz_constructor = ast.parse("def make_rect(): return fitz.Rect(0, 0, 1, 1)").body[0]
    normalizer_assembly = ast.parse(
        "def assemble(table, cell, bbox): return Table(table, cell, bbox)"
    ).body[0]
    normalizer_helper = ast.parse(
        "def compare(table, cell, bbox): return table == cell or bbox is None"
    ).body[0]

    assert _classification(script, "scripts/audit.py")[1] == "out_of_scope"
    assert _classification(page, "src/parser.py")[1] == "out_of_scope"
    assert _classification(dto, "src/owned_dto.py")[1] == "exact"
    assert _classification(plain_page_value, "src/parser.py")[1] == "exact"
    assert _classification(plain_fitz_value, "src/parser.py")[1] == "exact"
    assert _classification(plain_page_type_name, "src/parser.py")[1] == "exact"
    assert _classification(plain_drawings_value, "src/parser.py")[1] == "exact"
    assert _classification(fitz_type, "src/parser.py")[1] == "out_of_scope"
    assert _classification(fitz_constructor, "src/parser.py")[1] == "out_of_scope"
    assert _classification(normalizer_assembly, "src/tables/normalizer.py")[1] == "out_of_scope"
    assert _classification(normalizer_helper, "src/tables/normalizer.py")[1] == "exact"


def test_ast_audit_ignores_bare_page_and_drawing_parameter_names():
    node = ast.parse(
        "def keep(fitz, Page, drawing, drawings): return fitz, Page, drawing, drawings"
    ).body[0]
    assert _classification(node, "src/parser.py")[1] == "exact"


def test_ast_audit_classifies_qualified_page_api_and_types_as_out_of_scope():
    for source in (
        "def read(page): return page.get_text('words')",
        "def typed(page: fitz.Page): return page",
        "def rect(page): return fitz.Rect(0, 0, 1, 1)",
    ):
        node = ast.parse(source).body[0]
        assert _classification(node, "src/parser.py")[1] == "out_of_scope"


def test_ast_audit_requires_normalizer_table_names_to_be_called():
    variable_only = ast.parse(
        "def keep(table, cell, bbox): return table, cell, bbox"
    ).body[0]
    assert _classification(variable_only, "src/tables/normalizer.py")[1] == "exact"


def test_capability_evidence_requires_files_and_returns_repository_relative_paths(tmp_path):
    (tmp_path / "output" / "empty").mkdir(parents=True)
    unit = CapabilityUnit(
        identifier="evidence-contract",
        label="evidence",
        rust_files=("rust/fake.rs",),
        rust_markers=("pub fn fake",),
        python_files=("src/fake.py",),
        route_markers=("route",),
        test_files=("tests/test_fake.py",),
        evidence_globs=("output/**/*",),
    )
    (tmp_path / "rust").mkdir()
    (tmp_path / "rust" / "fake.rs").write_text("pub fn fake() {}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "fake.py").write_text("route()", encoding="utf-8")
    result_without_file = _evaluate_capability(tmp_path, unit)
    assert result_without_file.evidence == ()
    assert "page_or_diff_evidence" in result_without_file.missing

    evidence_file = tmp_path / "output" / "empty" / "diff.json"
    evidence_file.write_text("{}", encoding="utf-8")
    result_with_file = _evaluate_capability(tmp_path, unit)
    assert result_with_file.evidence == ("output/empty/diff.json",)
