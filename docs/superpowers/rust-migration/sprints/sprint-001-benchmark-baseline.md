# Sprint 001：建立可复现 Benchmark 基础设施

## 目标与范围

建立统一且确定性的三路基准测试（runner）与差异比对（comparator）基础设施，捕获真正的 `feature-dev@dc00211` 基线测量工件，供后续所有迁移 Sprint 进行函数级、FFI 级、区域级和全量端到端对比。未改动生产路由默认值（保持 `python`），未修改 Rust 核心算法。

## 拥有的文件与变更清单

- `scripts/benchmark_rust_migration.py`: 扩展三路 runner，支持 `--pdf`/`--fixture` 互斥解析、`--pages all` 展开、独立全新子进程 Worker（每轮全新 PID）、多阶段耗时采样（`extract`, `dto`, `ffi`, `algorithm`, `adapt`, `total`）、OS 峰值内存采样（Windows `PeakWorkingSetSize` / Linux `ru_maxrss`）以及页面级模型检测透明缓存。
- `scripts/compare_rust_migration.py`: 扩展为完整的三路/四路（baseline, python, rust, shadow）runner 比较器及页面 manifest 比较器，输出结构化差异、分类（defect/unsupported）及 P95 算法与端到端 speedup。
- `src/hexai_pdf_parser/debug/rust_migration_benchmark.py`: 统一确定性差异分类器（`missing_key`, `extra_key`, `list_length`, `text`, `bbox`, `span`, `order`, `value`）、原子 bbox 比对以及 `write_benchmark_run` 防止覆盖。
- `tests/test_rust_migration_benchmark.py`: 补充 32 项自动化测试，覆盖显式百分位接口、差异分类、无静默回退、独立 worker 进程检测、命令行互斥解析及来源追溯。

## 模式与合同约定

- 支持模式严格为 `python`、`shadow`、`rust`；非法或 `both` 模式抛出 `ValueError`。
- 未指定环境变量 `PDF_RUST_MODE` 时默认为 `python`。
- 单模块未通过输出完整一致性（equality）与性能门禁前，生产路由保持 Python。
- runner 输出固定为 `<output-dir>/<suite>-<mode>.json`；重复输出拒绝静默覆盖。

## 基线工件 (Baseline Artifacts)

### 1. Fixture 验证基线
- 路径: `output/rust_migration_benchmark/sprint-001/fixture-python.json`
- 输入: `tests/fixtures/page_000_vector.pdf` (页 `0`)
- 输出: 1 表格，16 单元格，完整 6 阶段样本。

### 2. Feature-dev 全量 1023 页黄金基线
- 路径: `output/rust_migration_benchmark/baselines/feature-dev-dc00211/full-pdf-python.json`
- Source Root Commit: `dc00211fe0cf95bc8c3412c883311fe86f8d8357`
- Baseline ID: `feature-dev-dc00211`
- 输入 SHA256: `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`
- 覆盖页数: 1023 页（`pages: all`）
- 提取表格数: 2312
- 单元格总数: 86361
- 失败页数: 0
- 运行轮次: 3 轮独立子进程（PIDs: `[18396, 26356, 48920]`）
- Peak RSS P50: `824,500,224` bytes (~824 MB)
- 阶段 P95 耗时:
  - `total`: ~693.95 秒
  - `algorithm`: ~416.37 秒
  - `extract`: ~138.79 秒
  - `adapt`: ~104.09 秒
  - `dto`: ~34.70 秒
  - `ffi`: 0.0 秒 (Python 基线)

## 验证结果

- `tests/test_rust_migration_benchmark.py`: 32 passed, 0 failed.
- `git diff --check`: 无空白或格式违规。
