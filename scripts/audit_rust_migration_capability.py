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


def _name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _args(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> str:
    values = [item.arg for item in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
    if node.args.vararg:
        values.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        values.append("**" + node.args.kwarg.arg)
    return ", ".join(values) or "无显式参数"


def _node_text(node: ast.AST) -> str:
    return " ".join(item.id for item in ast.walk(node) if isinstance(item, ast.Name)).lower()


def _classification(node: ast.AST, path: str) -> Tuple[str, str, str]:
    names = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
    text = _node_text(node)
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
    def visit(node: ast.AST, scope: List[str], caller: str) -> Iterable[Tuple[ast.AST, str, str, str]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*scope, child.name))
                yield child, qualified, caller or "模块入口", "method" if scope else "function"
                yield from visit(child, [*scope, child.name], qualified)
            elif isinstance(child, ast.Lambda):
                qualified = ".".join((*scope, f"<lambda>@{child.lineno}:{child.col_offset}"))
                yield child, qualified, caller or "模块入口", "lambda"
                yield from visit(child, [*scope, qualified], qualified)
            else:
                yield from visit(child, scope, caller)
    yield from visit(tree, [module], "")


def collect(roots: Sequence[Path]) -> List[Record]:
    records: List[Record] = []
    for root in sorted({item.resolve() for item in roots}, key=lambda item: item.as_posix()):
        for path in sorted(root.rglob("*.py")) if root.is_dir() else [root]:
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            nodes = list(_walk(tree, path.stem))
            qualified_names = {qualified for _, qualified, _, _ in nodes}
            calls: Dict[str, List[str]] = {qualified: [] for qualified in qualified_names}
            for node, qualified, _, _ in nodes:
                for call in ast.walk(node):
                    if isinstance(call, ast.Call):
                        callee = _name(call.func)
                        if callee:
                            short = callee.rsplit(".", 1)[-1]
                            for target in qualified_names:
                                if target.rsplit(".", 1)[-1] == short and target != qualified and qualified not in calls[target]:
                                    calls[target].append(qualified)
            path_text = path.as_posix()
            for node, qualified, parent, kind in nodes:
                dependency, classification, retention = _classification(node, path_text)
                if isinstance(node, ast.Lambda):
                    inputs, outputs = ", ".join(item.arg for item in node.args.args) or "无显式参数", "表达式结果"
                else:
                    inputs = _args(node)
                    outputs = (ast.unparse(node.returns) if hasattr(ast, "unparse") else ast.dump(node.returns)) if node.returns else "未标注"
                records.append(Record(path_text, qualified, "; ".join(sorted(calls[qualified])) or parent, f"{path_text}:{node.lineno} ({kind})", dependency, inputs, outputs, classification, _target(classification, path_text), _test(path_text), "future: DTO function benchmark (feature-dev baseline)", "Python 保留" if classification == "out_of_scope" else "待迁移", retention))
    return sorted(records, key=lambda item: (item.path, item.location, item.symbol))


def render(records: Sequence[Record], roots: Sequence[Path]) -> str:
    lines = [
        "# Rust 迁移能力矩阵（AST 审计）", "",
        "> 本文件由 `scripts/audit_rust_migration_capability.py` 生成，是静态能力盘点，不是性能报告。",
        "> 分类仅允许 `exact`、`semantic`、`redesign`、`out_of_scope`；未测量性能统一标记未来 benchmark。",
        f"> 输入根目录：{'、'.join(item.as_posix() for item in roots)}；登记 {len(records)} 个 AST 函数/方法/嵌套函数/lambda 节点。", "",
        "| 符号 | 调用者 | 位置/类型 | 依赖边界 | 输入字段 | 输出字段 | 分类 | Rust 目标 | 测试 | benchmark suite | 状态 | Python 保留理由 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in records:
        lines.append("| " + " | ".join((f"`{item.symbol}`", item.caller, item.location, item.dependency, item.inputs, item.outputs, item.classification, f"`{item.rust_target}`", f"`{item.tests}`", item.benchmark, item.status, item.retention)) + " |")
    lines += ["", "## 审计规则", "", "- `out_of_scope`：页面/绘图/文字采集、公开对象装配、I/O 和调试边界，明确保留 Python。", "- `semantic`：在 Python 已采集快照上可重现，但需适配公开对象并通过输出 equality。", "- `redesign`：当前依赖动态字段，先落实固定 DTO；`exact` 也不表示已经实现或已经测得加速。"]
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
    output.write_text(render(records, roots), encoding="utf-8")
    print(f"已写入 {output}；登记 {len(records)} 个 AST 节点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
