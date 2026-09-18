from __future__ import annotations

from pathlib import Path
import ast

from scripts.audit_rust_migration_capability import (
    CapabilityUnit,
    _evaluate_capability,
    _classification,
    collect_capabilities,
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

    assert _classification(script, "scripts/audit.py")[1] == "out_of_scope"
    assert _classification(page, "src/parser.py")[1] == "out_of_scope"
    assert _classification(dto, "src/owned_dto.py")[1] == "exact"
