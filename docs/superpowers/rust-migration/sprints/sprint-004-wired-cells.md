# Sprint 004：迁移有线 Cell、文字归属和区域装配

## 目标与范围

将有线表格提取核心纯几何线网 Cell 拓扑生成、幽灵行修剪、超切列合并、文字归属与区域装配算法完整迁移至 Rust (PyO3) 并释放 GIL，保持与 Python oracle 算法输出 100% 严格一致：
1. `build_cells_for_region`: 连通区域外边框补齐、泛洪连通分量遍历、互不重叠安全矩形划分与 occupancy 槽位占用检查。
2. `trim_ghost_edge_rows`: 修剪超薄缝隙行及无真实物理线支撑的边缘行，同步收缩跨行 Cell。
3. `merge_oversegmented_line_columns`: 合并超薄或全覆盖空列并重新计算 `colspan`。
4. `assign_text_to_line_cells`: 支持字符级边界切分、中心点跨格归属与基于银行家舍入的行列排序。
5. `extract_wired_region`: 装配完整的有线表格提取流程（连通分量划分 -> 网格切分 -> 字符归属 -> 空列合并 -> 幽灵行修剪）。

在 `WiredTableExtractor` 中完成 words 单次读取与缓存改造，杜绝全流程回读 `page.get_text("words")`，并接入 `PDF_RUST_MODE`（支持 `python` 生产默认、`shadow` 双路对比与 `rust` 执行）。

## 拥有的文件与变更清单

- `rust/wired.rs`: 有线 Cell 划分、幽灵行修剪、超切列合并与文字归属算法内核实现。
- `rust/types.rs`: 新增 `WiredRegionInput` 与 `WiredRegionOutput` DTO 结构，注册 `roundtrip_dto` 支持。
- `rust/lib.rs`: 导出上述纯函数接口与 `extract_wired_region`，密集计算使用 `py.allow_threads` 释放 GIL。
- `src/hexai_pdf_parser/rust_adapter.py`: 暴露强类型 Python 签名。
- `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py`:
  - 入口处实现 `words` 与 `raw_chars` 的页面级单次获取与缓存，彻底避免回读。
  - 在 `_build_cells_for_region`、`_trim_ghost_edge_rows`、`_merge_oversegmented_line_columns` 与 `_assign_text_to_line_cells` 接入 `PDF_RUST_MODE`。
- `tests/test_pdf_fast_wired.py`: 新增 8 项覆盖 Cell 拓扑、幽灵行修剪、超切列合并、文本归属及 `PageSpy` words 单次调用的自动化测试。
- `tests/fixtures/rust_migration/wired/cells.json`: 有线表格单元格与文字归属基准测试输入。
- `scripts/benchmark_rust_migration.py`: 增加 `wired-cells` fixture 算法包围计时（`t_alg`）与四路分段采集支持。
- `scripts/export_rust_migration_e2e.py`: 真实 PDF 页面端到端对比导出器。
- `changes.md`: 记录 Sprint 004 变更详情。
- `docs/superpowers/rust-migration/evaluations/sprint-004-pages.md`: 真实页面 P196/P415 比对报告。
- `docs/superpowers/rust-migration/evaluations/sprint-004-benchmark.md`: 四路基准测试比对报告。

## 验证与测试结果

- **TDD RED 阶段**: 先编写 `tests/test_pdf_fast_wired.py`，确认 `ImportError: cannot import name 'build_cells_for_region'` 产生预期失败。
- **TDD GREEN 阶段**:
  - `cargo fmt --check`: 检查通过。
  - `cargo test`: 6 passed, 0 failed.
  - `pytest tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_wireless_extractor_split.py`:
    - `PDF_RUST_MODE=python`: 90 passed, 0 failed.
    - `PDF_RUST_MODE=rust`: 90 passed, 0 failed.
    - `PDF_RUST_MODE=shadow`: 90 passed, 0 failed.
  - `PageSpy` 验证: 页面提取过程中对 `get_text("words")` 与 `get_text("rawdict")` 的调用次数均为 1 次，Rust 只接收解析后的 DTO。
  - `git diff --check`: 检查通过，exit 0。

## 端到端真实页面验证 (Page-level Manifest Comparison)

使用真实 PDF `fix/zh_all_table_pages.pdf` 对页面索引 196 与 415 进行全量渲染与提取比对：
- Python 模式输出: `output/pdf_rust_migration_wired_python_20260916/`
- Rust 模式输出: `output/pdf_rust_migration_wired_rust_20260916/`
- 比对报告: `docs/superpowers/rust-migration/evaluations/sprint-004-pages.md`
  - `equal`: True
  - `differences_count`: 0
  - P196（印刷页 197）表格边界、36x9 网格及 72 个 Cell 文本 100% 一致。
  - P415 柱状图过滤保持生效，下方表格 100% 一致。

## 基准测试测量工件 (Benchmark Artifacts)

在 `--suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10` 下采集四路对比：
- 基线输出: `output/rust_migration_benchmark/sprint-004/baseline/wired-cells-python.json`
- Python 输出: `output/rust_migration_benchmark/sprint-004/python/wired-cells-python.json`
- Shadow 输出: `output/rust_migration_benchmark/sprint-004/shadow/wired-cells-shadow.json`
- Rust 输出: `output/rust_migration_benchmark/sprint-004/rust/wired-cells-rust.json`
- 对比报告: `docs/superpowers/rust-migration/evaluations/sprint-004-benchmark.md`
  - `equal`: True
  - `differences_count`: 0
  - **Algorithm P95 Speedup**: **7.30x**
  - **Total P95 Speedup**: **2.01x**
