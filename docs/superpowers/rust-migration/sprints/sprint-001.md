# Sprint 001：abi3 扩展骨架与首个有线函数

## 状态

计划待执行。行为基线已由用户确认；本 sprint 不修改有线生产路由。

## 范围与所有权

- 新增根目录 `Cargo.toml`、`rust/lib.rs` 和 Rust 函数测试。
- 修改 `pyproject.toml`、`build.sh`，新增 `src/hexai_pdf_parser/rust_adapter.py` 与 `tests/test_pdf_fast_binding.py`。
- 迁移单元：`WiredTableExtractor._merge_h_lines(lines)`；调用者仍由 Python 执行原方法。
- 不改 `wired_table_extractor.py` 生产逻辑，不切换任何表格路径。

## 接口合同

- Rust纯函数：接收 `Vec<(f64, f64, f64, f64)>` 水平线段和 `merge_group_tol: f64`，返回相同元组形状的有序线段列表。
- PyO3 暴露一个批量 `merge_h_lines(lines, merge_group_tol)`；Python adapter 只负责转换类型。
- 兼容当前 Python 规则：先按 `(round(y, 1), x0)` 排序；按组首线的 y 与容差归组；组内 y 求算术平均；x 线段按起点排序，间隙 `<=3.0` 合并，较大间隙另起一段；返回顺序保持当前分组/线段顺序。
- ABI feature 必须令生成 wheel 声明 Python 3.7 abi3；若当前 toolchain 无法构建该目标，本 sprint 停在依赖决策，不修改 `requires-python`。

## 测试先行向量

Rust 与 pytest 都覆盖以下完全相同的输入输出：

```text
输入：[(0, 10, 10, 10), (10.5, 10.2, 20, 10.2)]，merge_group_tol=0.3
输出：[(0, 10.1, 20, 10.1)]

输入：[(0, 10, 10, 10), (14, 10, 20, 10)]，merge_group_tol=0.3
输出：[(0, 10, 10, 10), (14, 10, 20, 10)]

输入：[]，merge_group_tol=0.3
输出：[]
```

## 验证命令

```powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_binding.py tests/test_wired_table_extractor.py
maturin build --release
maturin sdist
git diff --check
```

验收还须检查 wheel 文件名不再是 `py3-none-any`，metadata 仍声明 `Requires-Python: >=3.7`，且 PyO3 使用的 abi3 下限为 `cp37`。只有此检查通过，才将 Sprint 001 标为完成。
还须检查 sdist 包含 `Cargo.toml`、`rust/` 源码和 Python `src/` 包，使源码分发能够重建同一扩展。

## 后续阶段输入

Sprint 001 通过后，Generator 才开始把其他有线纯几何函数纳入 Rust；独立 Evaluator 复跑本 sprint 命令并验证 wheel tag 与基线向量。任何不精确数值差异均返回 bounded repair，不改变输入或容差合同。
