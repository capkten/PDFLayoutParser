# Sprint 003：迁移有线几何和线网区域算法

## 目标与范围

将有线表格提取核心纯几何与区域拓扑算法完整迁移至 Rust (PyO3) 并释放 GIL，保持与 Python oracle 算法输出 100% 严格一致：
1. `merge_h_lines`: 横线合并与基于银行家舍入的排序。
2. `merge_v_lines`: 竖线分组合并与容差内段拼接。
3. `merge_region_line_coordinates`: 单连通区域内的近邻坐标线段合并。
4. `lines_intersect`: 横竖线正交相交判定（容差扩展包围盒）。
5. `find_table_regions`: 过滤孤立线段、构建双向连通图、BFS/DFS 提取连通表格分量并计算外包围盒。
6. `snap_coordinates`: 吸附并合并临近锚点坐标。
7. `snap_grid_coordinates`: 基于正交覆盖率计算并对齐网格坐标线。
8. `complete_partial_outer_boundaries`: 根据完整跨度层级与端点接触对齐补齐外边界短缺线段。

同时在 `WiredTableExtractor` 接入 `PDF_RUST_MODE`（支持 `python` 默认、`shadow` 对比与 `rust` 生产执行），实现平滑可控的路由解耦。

## 拥有的文件与变更清单

- `rust/geometry.rs`: 纯几何数学与线段合并算法（`round_one_decimal`, `lines_intersect`, `merge_h_lines`, `merge_v_lines`, `merge_region_line_coordinates`, `snap_coordinates`, `calculate_coverage`, `snap_grid_coordinates`）。
- `rust/wired.rs`: 有线线网连通分量划分与外边界补全算法（`find_table_regions`, `complete_partial_outer_boundaries`）。
- `rust/lib.rs`: 导出上述纯函数接口到 PyO3 模块，计算密集部分通过 `py.allow_threads` 释放 GIL。
- `src/hexai_pdf_parser/rust_adapter.py`: 封装并暴露强类型 Python 签名。
- `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py`: 在 `_merge_h_lines`、`_merge_v_lines`、`_find_table_regions`、`_merge_region_line_coordinates`、`_lines_intersect`、`_snap_coordinates`、`_snap_grid_coordinates`、`_complete_partial_outer_boundaries` 处接入 `PDF_RUST_MODE`。
- `tests/test_pdf_fast_wired.py`: 新建 12 项包含正常合并、断开间隔、相交容差、连通分量划分、外边界补全等测试。
- `tests/fixtures/rust_migration/wired/geometry.json`: 有线几何多表格基准输入数据。
- `scripts/benchmark_rust_migration.py`: 适配有线几何 fixture 的三路 / 四路分段耗时与结果采集。
- `src/hexai_pdf_parser/debug/rust_migration_benchmark.py`: 支持列表与元组类型的 bbox 规范化。
- `docs/superpowers/rust-migration/evaluations/sprint-003-benchmark.md`: 四路基准对比报告。

## 验证与测试结果

- **TDD RED 阶段**: 先编写 `tests/test_pdf_fast_wired.py`，确认 `ImportError: cannot import name 'merge_v_lines'` 预期失败。
- **TDD GREEN 阶段**:
  - `cargo fmt --check`: 格式规范检查通过。
  - `cargo test`: 6 passed, 0 failed.
  - `pytest tests/test_pdf_fast_wired.py`: 12 passed, 0 failed.
  - `pytest tests/test_wired_table_extractor.py`: 63 passed, 0 failed（在默认 Python 模式与 `$env:PDF_RUST_MODE='rust'` 模式下均 100% 通过）。
  - `pytest tests/test_rust_migration_benchmark.py`: 32 passed, 0 failed.
  - `git diff --check`: 检查通过，无额外空白或格式违规。

## 基准测试测量工件 (Benchmark Artifacts)

在 `--suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10` 下采集四路对比：
- 基线输出: `output/rust_migration_benchmark/sprint-003/baseline/wired-geometry-python.json`
- Python 输出: `output/rust_migration_benchmark/sprint-003/python/wired-geometry-python.json`
- Shadow 输出: `output/rust_migration_benchmark/sprint-003/shadow/wired-geometry-shadow.json`
- Rust 输出: `output/rust_migration_benchmark/sprint-003/rust/wired-geometry-rust.json`
- 对比报告: `docs/superpowers/rust-migration/evaluations/sprint-003-benchmark.md`
  - `equal`: True
  - `differences_count`: 0
