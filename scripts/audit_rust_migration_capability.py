#!/usr/bin/env python3
"""静态枚举表格代码中的全部 AST 函数节点并生成中文迁移矩阵。"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

CLASSIFICATIONS = {"exact", "semantic", "redesign", "out_of_scope"}


@dataclass(frozen=True)
class Record:
    path: str
    symbol: str
    caller: str
    location: str
    dependency: str
    inputs: str
    outputs: str
    classification: str
    rust_target: str
    tests: str
    benchmark: str
    status: str
    retention: str


@dataclass(frozen=True)
class CapabilityUnit:
    identifier: str
    label: str
    rust_files: Tuple[str, ...] = ()
    rust_markers: Tuple[str, ...] = ()
    python_files: Tuple[str, ...] = ()
    route_markers: Tuple[str, ...] = ()
    test_files: Tuple[str, ...] = ()
    record_globs: Tuple[str, ...] = ()
    evidence_globs: Tuple[str, ...] = ()
    schema_markers: Tuple[str, ...] = ()
    fixed_status: Optional[str] = None


@dataclass(frozen=True)
class CapabilityResult:
    identifier: str
    label: str
    status: str
    missing: Tuple[str, ...]
    evidence: Tuple[str, ...]


CAPABILITY_UNITS: Tuple[CapabilityUnit, ...] = (
    CapabilityUnit(
        "wired-geometry",
        "几何线段、坐标合并与 wired grid",
        ("rust/geometry.rs", "rust/wired.rs"),
        (
            "pub fn merge_h_lines",
            "pub fn merge_v_lines",
            "pub fn find_table_regions",
            "pub fn build_cells_for_region",
            "pub fn assign_text_to_line_cells",
            "pub fn merge_oversegmented_line_columns",
            "pub fn trim_ghost_edge_rows",
        ),
        ("src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py",),
        (
            "run_python_or_rust",
            "_merge_h_lines",
            "_merge_v_lines",
            "_find_table_regions",
            "_build_cells_for_region",
            "_assign_text_to_line_cells",
            "_merge_oversegmented_line_columns",
            "_trim_ghost_edge_rows",
        ),
        ("tests/test_wired_table_extractor.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "native-span-structure",
        "native span/atom 与中文混合逻辑网格",
        ("rust/wireless_structure.rs",),
        ("pub fn recover_native_region",),
        (
            "src/hexai_pdf_parser/tables/wireless_structure/recoverer.py",
        ),
        ("run_python_or_rust", "recover_native_region"),
        (
            "tests/test_pdf_fast_wireless_structure.py",
            "tests/test_wireless_structure_recoverer.py",
        ),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "shared-wireless-recovery",
        "shared wireless candidate recovery",
        ("rust/wireless_structure.rs",),
        ("pub fn recover_wireless_tables",),
        ("src/hexai_pdf_parser/tables/wireless_table_recovery.py",),
        ("run_python_or_rust", "recover_wireless_tables"),
        ("tests/test_wireless_table_recovery.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "english-background-and-zebra",
        "英文背景分组与 zebra row 分配",
        ("rust/english_wireless.rs",),
        ("pub fn group_backgrounds", "pub fn assign_words_to_zebra_rows"),
        ("src/hexai_pdf_parser/tables/extractors/english_table_extractor.py",),
        ("run_python_or_rust", "group_backgrounds", "assign_words_to_zebra_rows"),
        ("tests/test_pdf_fast_english_wireless.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "english-columns-and-cells",
        "英文 wireless 列推断与 Cell 构建",
        ("rust/english_wireless.rs",),
        ("pub fn infer_english_columns", "pub fn build_english_cells"),
        ("src/hexai_pdf_parser/tables/extractors/english_table_extractor.py",),
        ("run_python_or_rust", "infer_english_columns", "build_english_cells"),
        ("tests/test_pdf_fast_english_wireless.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "text-alignment-grid",
        "text alignment 行、列带与 Cell 网格",
        ("rust/english_wireless.rs",),
        ("pub fn build_general_wireless_cells",),
        ("src/hexai_pdf_parser/tables/table_extractor.py",),
        ("run_python_or_rust", "build_general_wireless_cells", "_build_text_alignment_table"),
        ("tests/test_pdf_fast_text_alignment.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "legacy-text-rebuild",
        "normalizer 的 legacy text-alignment 重建",
        ("rust/english_wireless.rs",),
        ("pub fn build_legacy_text_alignment",),
        ("src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py",),
        ("run_python_or_rust", "build_legacy_text_alignment", "_rebuild_text_aligned_table"),
        ("tests/test_pdf_fast_table_normalization.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "header-topology",
        "表头拓扑与 rowspan/colspan",
        ("rust/table_normalization.rs",),
        ("pub fn infer_header_structure",),
        ("src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py",),
        ("run_python_or_rust", "infer_header_structure", "_promote_grouped_header"),
        ("tests/test_pdf_fast_table_normalization.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit(
        "financial-header-tokens",
        "金融表头 token normalization",
        ("rust/table_normalization.rs",),
        ("pub fn normalize_financial_header_tokens",),
        ("src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py",),
        ("run_python_or_rust", "normalize_financial_header_tokens", "_normalize_financial_header_tokens"),
        ("tests/test_pdf_fast_table_normalization.py",),
        ("迁移记录/*.md",),
        ("output/rust-full-migration-*",),
    ),
    CapabilityUnit("pymupdf-page-access", "PyMuPDF page/drawing/text 访问", fixed_status="python_orchestration"),
    CapabilityUnit("ml-and-rendering", "模型推理与渲染", fixed_status="out_of_scope"),
)


def _read_project_file(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _evaluate_capability(root: Path, unit: CapabilityUnit) -> CapabilityResult:
    if unit.fixed_status:
        return CapabilityResult(unit.identifier, unit.label, unit.fixed_status, (), ())

    missing: List[str] = []
    rust_text = "\n".join(_read_project_file(root, path) for path in unit.rust_files)
    python_text = "\n".join(_read_project_file(root, path) for path in unit.python_files)
    if not all(marker in rust_text for marker in unit.rust_markers):
        missing.append("rust_symbol")
    schema_markers = unit.schema_markers or (("schema_version: 1",) if unit.rust_files else ())
    if schema_markers and not all(marker in rust_text for marker in schema_markers):
        missing.append("dto_schema")
    if not all(marker in python_text for marker in unit.route_markers):
        missing.append("production_route")
    if not all((root / path).exists() for path in unit.test_files):
        missing.append("behavior_test")
    if not any(any(root.glob(pattern)) for pattern in unit.record_globs):
        missing.append("migration_record")
    evidence = tuple(
        sorted({str(path) for pattern in unit.evidence_globs for path in root.glob(pattern)})
    )
    if not evidence:
        missing.append("page_or_diff_evidence")

    if "production_route" in missing:
        status = "adapter_only"
    elif missing:
        status = "blocked"
    else:
        status = "migrated"
    return CapabilityResult(unit.identifier, unit.label, status, tuple(missing), evidence)


def _find_project_root(path: Path) -> Path:
    candidate = path.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "rust").is_dir():
            return directory
    return candidate


def collect_capabilities(roots: Sequence[Path]) -> List[CapabilityResult]:
    project_root = next(
        (root for root in (_find_project_root(item) for item in roots) if (root / "rust").is_dir()),
        _find_project_root(Path(roots[0])),
    )
    return [_evaluate_capability(project_root, unit) for unit in CAPABILITY_UNITS]


def _name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _argument_fields(args: ast.arguments) -> str:
    """Render every argument kind, including fields introduced after Python 3.7."""
    # ``posonlyargs`` was added in Python 3.8; getattr keeps the audit runnable on 3.7.
    positional_only = getattr(args, "posonlyargs", ())
    values = [item.arg for item in positional_only]
    if positional_only:
        values.append("/")
    values.extend(item.arg for item in args.args)
    if args.vararg:
        values.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        values.append("*")
    values.extend(item.arg for item in args.kwonlyargs)
    if args.kwarg:
        values.append("**" + args.kwarg.arg)
    return ", ".join(values) or "无显式参数"


def _args(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
    return _argument_fields(node.args)


def _node_text(node: ast.AST) -> str:
    return " ".join(item.id for item in ast.walk(node) if isinstance(item, ast.Name)).lower()


def _classification(node: ast.AST, path: str) -> Tuple[str, str, str]:
    names = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
    text = _node_text(node)
    path_parts = {part.lower() for part in Path(path).parts}
    if path_parts & {"scripts", "tests", "benchmark", "benchmarks"}:
        return "脚本、测试或 benchmark 边界", "out_of_scope", "非生产 owned 算法，不列为待迁移能力"
    if names & {"open", "print", "subprocess"}:
        return "文件、进程或调试输出", "out_of_scope", "I/O、CLI 或调试包装保留 Python"
    if names & {"fitz", "Page", "page", "drawing", "drawings"} or "get_text" in text:
        return "PyMuPDF Page/drawing/文字采集", "out_of_scope", "页面读取必须由 Python 转为 owned DTO"
    if names & {"Table", "Cell", "BBox", "table", "cell", "bbox"} and "normalizer" in path:
        return "公开 Table/Cell/BBox 装配", "semantic", "Python 保留公开对象装配，Rust 只消费 DTO"
    if "dict" in text or "any" in text or "mapping" in text:
        return "动态 Python 容器", "redesign", "先固定 DTO 字段，禁止动态字典直接过 FFI"
    return "owned 标量、列表或结构化值", "exact", "可按 DTO 做纯函数等价迁移"


def _target(classification: str, path: str) -> str:
    if classification == "out_of_scope":
        return "不迁移"
    stem = Path(path).stem
    mapping = {
        "wired_table_extractor": "rust/wired.rs",
        "wireless_table_recovery": "rust/native_span.rs",
        "text_runs": "rust/native_span.rs",
        "span_chain": "rust/native_span.rs",
        "columns": "rust/wireless_structure.rs",
        "grid": "rust/wireless_structure.rs",
        "logical_grid": "rust/wireless_structure.rs",
        "merged_cells": "rust/wireless_structure.rs",
        "header_topology": "rust/wireless_structure.rs",
        "hybrid_body": "rust/wireless_structure.rs",
        "english_table_extractor": "rust/english_wireless.rs",
        "table_header_normalizer": "rust/table_normalization.rs",
        "financial_header_handler": "rust/table_normalization.rs",
    }
    return mapping.get(stem, "rust/geometry.rs")


def _test(path: str) -> str:
    stem = Path(path).stem
    if stem in {"columns", "grid", "logical_grid", "merged_cells", "header_topology", "hybrid_body", "text_runs", "span_chain"}:
        return "tests/test_wireless_structure_*.py"
    return {
        "wired_table_extractor": "tests/test_wired_table_extractor.py",
        "wireless_table_recovery": "tests/test_wireless_table_recovery.py",
        "english_table_extractor": "tests/test_wireless_extractor_split.py",
        "table_header_normalizer": "tests/test_header_upward_merge.py",
        "financial_header_handler": "tests/test_financial_header_normalizer.py",
    }.get(stem, "tests/test_table_extractor.py")


def _walk(tree: ast.AST, module: str) -> Iterable[Tuple[ast.AST, str, str, str]]:
    def visit(node: ast.AST, scope: List[str], caller: str, in_class: bool = False) -> Iterable[Tuple[ast.AST, str, str, str]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from visit(child, [*scope, child.name], caller, True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*scope, child.name))
                yield child, qualified, caller or "模块入口", "method" if in_class else "function"
                yield from visit(child, [*scope, child.name], qualified, False)
            elif isinstance(child, ast.Lambda):
                qualified = ".".join((*scope, f"<lambda>@{child.lineno}:{child.col_offset}"))
                yield child, qualified, caller or "模块入口", "lambda"
                yield from visit(child, [*scope, f"<lambda>@{child.lineno}:{child.col_offset}"], qualified, False)
            else:
                yield from visit(child, scope, caller, in_class)
    yield from visit(tree, [module], "")


def _direct_scope_calls(node: ast.AST) -> Iterable[ast.Call]:
    """Yield calls in this lexical scope, excluding nested function scopes."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        children = node.body if isinstance(node.body, list) else (node.body,)
    else:
        children = ast.iter_child_nodes(node)
    for child in children:
        # Decorators, defaults, annotations and nested callable/class bodies are
        # outside the current function/method body scope.
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.ClassDef):
            continue
        if isinstance(child, ast.Call):
            yield child
        yield from _direct_scope_calls(child)


def _resolve_callee(callee: str, qualified_names: set, qualified: str, module: str) -> Optional[str]:
    """Resolve only names that identify a definition in this module.

    Short names are never matched against arbitrary definitions: dynamic dispatch,
    imports, and calls outside this module remain intentionally unresolved.
    """
    if callee in qualified_names:
        return callee
    if callee.startswith(module + ".") and callee in qualified_names:
        return callee
    owner = qualified.rsplit(".", 1)[0]
    if callee.startswith(("self.", "cls.")):
        candidate = owner + "." + callee.split(".", 1)[1]
        return candidate if candidate in qualified_names else None
    if "." not in callee:
        candidates = [owner + "." + callee, module + "." + callee]
        matches = [candidate for candidate in candidates if candidate in qualified_names]
        return matches[0] if len(matches) == 1 else None
    return None


def _stable_path(path: Path) -> str:
    resolved = path.resolve()
    cwd = Path.cwd().resolve()
    try:
        return resolved.relative_to(cwd).as_posix()
    except ValueError:
        return resolved.as_posix()


def collect(roots: Sequence[Path]) -> List[Record]:
    records: List[Record] = []
    excluded_dirs = {".git", ".tmp", "target", "output", ".worktrees"}
    for root in sorted({item.resolve() for item in roots}, key=lambda item: item.as_posix()):
        paths = (
            path
            for path in root.rglob("*.py")
            if not any(part in excluded_dirs for part in path.relative_to(root).parts)
        ) if root.is_dir() else [root]
        for path in sorted(paths):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            nodes = list(_walk(tree, path.stem))
            qualified_names = {qualified for _, qualified, _, _ in nodes}
            calls: Dict[str, List[str]] = {qualified: [] for qualified in qualified_names}
            for node, qualified, _, _ in nodes:
                for call in _direct_scope_calls(node):
                    callee = _name(call.func)
                    target = _resolve_callee(callee, qualified_names, qualified, path.stem) if callee else None
                    if target and target != qualified and qualified not in calls[target]:
                        calls[target].append(qualified)
            path_text = _stable_path(path)
            for node, qualified, parent, kind in nodes:
                dependency, classification, retention = _classification(node, path_text)
                if isinstance(node, ast.Lambda):
                    inputs, outputs = _argument_fields(node.args), "表达式结果"
                else:
                    inputs = _args(node)
                    outputs = (ast.unparse(node.returns) if hasattr(ast, "unparse") else ast.dump(node.returns)) if node.returns else "未标注"
                records.append(Record(path_text, qualified, "; ".join(sorted(calls[qualified])) or parent, f"{path_text}:{node.lineno} ({kind})", dependency, inputs, outputs, classification, _target(classification, path_text), _test(path_text), "future: DTO function benchmark (feature-dev baseline)", "Python 保留" if classification == "out_of_scope" else "待迁移", retention))
    return sorted(records, key=lambda item: (item.path, item.location, item.symbol))


def render(
    records: Sequence[Record],
    roots: Sequence[Path],
    capabilities: Sequence[CapabilityResult] = (),
) -> str:
    lines = [
        "# Rust 迁移能力矩阵（AST 审计）", "",
        "> 本文件由 `scripts/audit_rust_migration_capability.py` 生成。顶部能力单元是生产接入判定，下面 AST 表是静态盘点，不是性能报告。",
        "> 分类仅允许 `exact`、`semantic`、`redesign`、`out_of_scope`；未测量性能统一标记未来 benchmark。",
        f"> 输入根目录：{'、'.join(_stable_path(item) for item in roots)}；登记 {len(records)} 个 AST 函数/方法/嵌套函数/lambda 节点。", "",
        "## 能力单元生产接入判定", "",
        "| 能力单元 | 状态 | 缺失项 | 页面/差分证据 |",
        "|---|---|---|---|",
    ]
    for item in capabilities:
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{item.identifier}` {item.label}",
                    item.status,
                    ", ".join(item.missing) or "—",
                    ", ".join(item.evidence) or "—",
                )
            )
            + " |"
        )
    lines += [
        "",
        "| 符号 | 调用者 | 位置/类型 | 依赖边界 | 输入字段 | 输出字段 | 分类 | Rust 目标 | 测试 | benchmark suite | 状态 | Python 保留理由 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in records:
        lines.append("| " + " | ".join((f"`{item.symbol}`", item.caller, item.location, item.dependency, item.inputs, item.outputs, item.classification, f"`{item.rust_target}`", f"`{item.tests}`", item.benchmark, item.status, item.retention)) + " |")
    lines += ["", "## 审计规则", "", "- `out_of_scope`：页面/绘图/文字采集、公开对象装配、I/O 和调试边界，明确保留 Python。", "- `semantic`：在 Python 已采集快照上可重现，但需适配公开对象并通过输出 equality。", "- `redesign`：当前依赖动态字段，先落实固定 DTO；`exact` 也不表示已经实现或已经测得加速。", "- 调用者只遍历当前函数/方法的直接 lexical body scope；遇到 nested function/lambda 即停止，因此不会把嵌套调用归入外层。仅解析本模块内可确定的完整限定名（含 `self.`/`cls.` 的当前类方法）；动态调用、导入调用和无法唯一解析的短名不作断言。"]
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    roots = [Path(item) for item in args.root]
    missing = [str(item) for item in roots if not item.exists()]
    if missing:
        parser.error("根目录不存在: " + ", ".join(missing))
    records = collect(roots)
    if not records or any(item.classification not in CLASSIFICATIONS for item in records):
        raise RuntimeError("审计结果为空或包含未注册分类")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    capabilities = collect_capabilities(roots)
    output.write_text(render(records, roots, capabilities), encoding="utf-8")
    counts: Dict[str, int] = {}
    for item in capabilities:
        counts[item.status] = counts.get(item.status, 0) + 1
    print(
        f"已写入 {output}；登记 {len(records)} 个 AST 节点；"
        f"能力单元状态：{counts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
