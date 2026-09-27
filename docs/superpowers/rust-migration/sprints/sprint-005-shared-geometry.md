# Sprint 005：抽取共享几何、排序和候选算法

## 目标与范围

抽取有线表格与无线表格共用的核心基础几何、候选过滤、行列聚类及输出稳定排序算法到 Rust (PyO3) 并释放 GIL：
1. 
ect_overlap: 矩形相交检测，支持 strict（正面积重叠）与非 strict（边/角重合接触）。
2. ilter_regions: 依据排除区域集（如 chart masks）与允许范围集（如有效检测边界）过滤候选区域。
3. cluster_rows: 将带有次序的矩形序列（OrderedRectDto）依据纵向中心线容差聚类为网格行，行内元素按横向坐标与输入顺序稳定排序。
4. cluster_columns: 将矩形序列依据横向中心线容差聚类为网格列，列内元素按纵向坐标与输入顺序稳定排序。
5. stable_output_order: 对候选表格集合（TableCandidateDto）依据空间几何坐标 (y0, x0, y1, x1) 及来源标识执行确定性的稳定排序。

在 TableExtractor 与 wireless_table_recovery.py 中接入上述 Rust 接口，接入 PDF_RUST_MODE 路由，保持 Python 默认行为，并通过单元测试与四路基准测试验证 100% 一致性。

## 拥有的文件与变更清单

- 
ust/geometry.rs: 实现 
ect_overlap、ilter_regions、cluster_rows、cluster_columns 与 stable_output_order 算法内核。
- 
ust/types.rs: 新增 OutputOrderMode DTO 结构，登记到 
oundtrip_dto。
- 
ust/lib.rs: 导出上述 5 个算子并在密集计算处使用 py.allow_threads 释放 GIL。
- src/hexai_pdf_parser/rust_adapter.py: 暴露强类型 Python 包装签名。
- src/hexai_pdf_parser/tables/table_extractor.py: 在 _bbox_overlaps 接入 
ect_overlap 的 PDF_RUST_MODE 路由。
- src/hexai_pdf_parser/tables/wireless_table_recovery.py: 在 _row_cluster 接入 cluster_rows 的 PDF_RUST_MODE 路由。
- 	ests/test_pdf_fast_shared_geometry.py: 新增 17 个纯几何、排除/允许过滤、行列聚类和稳定排序的单元测试。
- 	ests/fixtures/rust_migration/shared/geometry.json: 共享几何与排序算法基准测试输入工件。
- scripts/benchmark_rust_migration.py: 增加 shared-geometry fixture 的四路分段采集支持。
- docs/superpowers/rust-migration/evaluations/sprint-005-benchmark.md: 四路基准测试比对报告。
- docs/superpowers/rust-migration/sprints/sprint-005-shared-geometry.md: 本总结文档。

## 验证与测试结果

- **TDD RED 阶段**: 先编写 	ests/test_pdf_fast_shared_geometry.py，确认 ImportError: cannot import name 'rect_overlap' 预期失败。
- **TDD GREEN 阶段**:
  - cargo fmt --check: 格式检查通过。
  - cargo test: 6 passed, 0 failed.
  - pytest tests/test_pdf_fast_shared_geometry.py: 17 passed, 0 failed.
  - 全量回归测试（排除 1 个既有历史测试）：
    - PDF_RUST_MODE=python: 154 passed, 0 failed.
    - PDF_RUST_MODE=shadow: 154 passed, 0 failed.
    - PDF_RUST_MODE=rust: 154 passed, 0 failed.
  - git diff --check: 检查通过，0 警告。

## 基准测试测量工件 (Benchmark Artifacts)

在 --suite shared-geometry --fixture tests/fixtures/rust_migration/shared/geometry.json --warmups 3 --runs 10 下采集四路对比：
- 基线输出: output/rust_migration_benchmark/sprint-005/baseline/shared-geometry-python.json
- Python 输出: output/rust_migration_benchmark/sprint-005/python/shared-geometry-python.json
- Shadow 输出: output/rust_migration_benchmark/sprint-005/shadow/shared-geometry-shadow.json
- Rust 输出: output/rust_migration_benchmark/sprint-005/rust/shared-geometry-rust.json
- 对比报告: docs/superpowers/rust-migration/evaluations/sprint-005-benchmark.md
  - equal: True
  - differences_count: 0
  - **Algorithm P95 Speedup**: **2.74x**
  - **Total P95 Speedup**: **2.50x**
