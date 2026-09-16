
# PDF 表格逻辑 Rust 极限迁移实施计划

> For agentic workers: REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，逐任务执行并在任务间评审。每步用 - [ ] 跟踪。若使用 subagent，model 只能是 gpt-5.6-luna。

**目标：** 在保持 Python/PyMuPDF 输入边界、公开 API 和输出完全兼容的前提下，将所有可表达为 owned DTO 的表格纯算法尽可能迁移到 Rust，并用函数级、FFI 级、区域级、页面级和全量 PDF benchmark 给出真实前后对比。

**架构：** Python 负责 PDF/PyMuPDF 数据采集、ML 推理、语言路由、公开 API、Table/Cell 构造和序列化；Rust 通过 PyO3 接收按页或区域批量传入的 owned DTO，执行几何、线网、span、网格、跨度和表格候选算法，再把 owned result DTO 交给 Python 适配。生产路径支持 python、shadow、rust 三种模式，默认保持 Python，单模块通过输出和性能门禁后才切换。

**技术栈：** Rust 2021、PyO3 0.22.6、maturin、abi3 cp37、Python 3.7+、PyMuPDF、pytest、现有 PDFParser 流水线。

## 全局约束

- Python 最低版本保持 >=3.7；wheel 使用 cp37-abi3，仍按 OS、CPU 架构、glibc 和 native runtime 分别构建。
- 以 feature-dev@dc00211fe0cf95bc8c3412c883311fe86f8d8357 作为行为基线；执行前只允许同步已确认的 feature-dev 提交，不覆盖主工作树改动。
- Python/PyMuPDF 独占 Page、drawing、words、rawdict、native span 和渲染；Rust 不接收或持有 fitz.Page，不回调 Python。
- 所有纯算法按函数粒度执行 RED → GREEN → differential → benchmark → 路由验收；组合入口测试不能替代叶子函数合同测试。
- 顺序、文本、bbox、source、confidence、行列索引、rowspan、colspan、空槽位、异常和空结果按 Python 基线精确保持；不得用宽泛浮点容差隐藏差异。
- 中文/混合无线只消费 native span 派生 DTO；结构恢复不得回读 page.get_text("words")，不得回退 extract_zebra() 或 legacy words 重建。
- 每次 PyO3 调用按页或表格区域批量传输；Rust 无 Python 回调的长计算阶段释放 GIL。
- Benchmark 是强制验收项：没有前后数据的模块不能宣称完成或切换 Rust primary。
- 本机 PDF、页面 PNG、benchmark 原始明细和构建目录不提交 Git；报告只提交小型 summary、差异结论和可复现命令。
- 每个任务完成后运行 git diff --check，并提交一个只包含本任务文件的 commit。

## 文件地图

已有并继续使用：

- rust/lib.rs：PyO3 模块入口和兼容导出。
- src/hexai_pdf_parser/rust_adapter.py：Python DTO 转换、模式选择和结果适配。
- src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py：有线 PDF drawing 提取与 facade。
- src/hexai_pdf_parser/tables/extractors/english_table_extractor.py：英文 drawing/words 提取与 facade。
- src/hexai_pdf_parser/tables/wireless_table_recovery.py：native span 采集与共享恢复 facade。
- src/hexai_pdf_parser/tables/wireless_structure/：中文/混合结构规则的 Python 行为 oracle。
- src/hexai_pdf_parser/core/pipeline.py：现有阶段计时和 timings.json 输出。

计划新增：

- rust/types.rs、rust/geometry.rs、rust/wired.rs、rust/native_span.rs、rust/wireless_structure.rs、rust/english_wireless.rs、rust/table_normalization.rs。
- scripts/benchmark_rust_migration.py、scripts/compare_rust_migration.py。
- src/hexai_pdf_parser/debug/rust_migration_benchmark.py。
- tests/test_rust_migration_benchmark.py、tests/test_pdf_fast_dto.py、tests/test_pdf_fast_wired.py、tests/test_pdf_fast_wireless.py、tests/test_pdf_fast_wireless_structure.py、tests/test_pdf_fast_english_wireless.py、tests/test_pdf_fast_table_normalization.py。
- tests/fixtures/rust_migration/ 下的 JSON 输入向量。
- docs/superpowers/rust-migration/sprints/ 下的 Sprint handoff 和 evaluations/ 下的独立评估记录。

计划修改：

- Cargo.toml、rust/lib.rs、pyproject.toml、build.sh：扩展模块、ABI 和发布配置。
- rust_adapter.py、三类 extractor、wireless_table_recovery.py、wireless_structure/*.py：只替换已验收的纯计算调用点。
- src/hexai_pdf_parser/debug/benchmark_utils.py：保留 legacy `summarize_timings` 的五键结果，并提供供迁移 benchmark 使用的显式 `summarize_timings_with_percentiles`（含 p50/p95/p99）。
- tests/、changes.md、迁移记录和 .gitignore：记录每个 Sprint 的结果和输出约束。

## Sprint 000：确认基线、分支和迁移矩阵

Files:

- Read: docs/superpowers/specs/2026-09-16-rust-extreme-migration-design.md
- Read: docs/superpowers/rust-migration/baseline.md
- Read: docs/superpowers/rust-migration/capability-matrix.md
- Modify: docs/superpowers/rust-migration/baseline.md
- Modify: docs/superpowers/rust-migration/capability-matrix.md
- Create: docs/superpowers/rust-migration/sprints/sprint-000-benchmark-baseline.md

Interfaces:

- Consumes: 当前分支 codex/pdf-fast-rust-migration、基线 commit dc00211、已有 Sprint 001 Rust 扩展。
- Produces: 每个 Python 纯函数的 exact reproduction、semantic reproduction 或 redesign 分类；每个函数对应的输入 DTO、输出 DTO、测试文件和 benchmark suite。

- [ ] Step 1: 验证隔离工作树和基线 commit。

~~~powershell
git status --short --branch
git branch --show-current
git merge-base HEAD feature-dev
git show -s --format=%H feature-dev
git show -s --format=%H HEAD
~~~

Expected: 当前分支为 codex/pdf-fast-rust-migration；feature-dev 为 dc00211fe0cf95bc8c3412c883311fe86f8d8357；主工作树未提交改动不出现在本 worktree。

- [ ] Step 2: 逐文件补齐 capability matrix。

逐一盘点以下目录中被调用的纯函数：

~~~text
src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py
src/hexai_pdf_parser/tables/table_extractor.py
src/hexai_pdf_parser/tables/wireless_table_recovery.py
src/hexai_pdf_parser/tables/wireless_structure/*.py
src/hexai_pdf_parser/tables/extractors/english_table_extractor.py
src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py
src/hexai_pdf_parser/tables/normalizers/financial_header_handler.py
~~~

每行必须包含 Python 符号、调用者、输入字段、输出字段、分类、Rust 文件、测试文件、benchmark suite、当前状态和 Python 保留理由（若保留）。

- [ ] Step 3: 建立 Sprint 000 记录并确认旧 Sprint 001 结论。

记录已有 merge_h_lines 已实现但未接生产路由；记录当前没有性能结论，后续所有性能结论必须来自新的 benchmark runner。

- [ ] Step 4: 验证文档一致性并提交。

~~~powershell
git diff --check
git add -f docs/superpowers/rust-migration
git commit -m "docs: define Rust migration benchmark baseline"
~~~

Expected: 文档 commit 成功，未加入 PDF、PNG、output/ 或 target/。

## Sprint 001：建立可复现 Benchmark 基础设施

Files:

- Create: scripts/benchmark_rust_migration.py
- Create: scripts/compare_rust_migration.py
- Create: tests/test_rust_migration_benchmark.py
- Modify: src/hexai_pdf_parser/debug/benchmark_utils.py
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: .gitignore
- Create: docs/superpowers/rust-migration/sprints/sprint-001-benchmark-baseline.md

Interfaces:

~~~python
# src/hexai_pdf_parser/debug/rust_migration_benchmark.py
def summarize_timings(values: Sequence[float]) -> Dict[str, float]: ...
def summarize_timings_with_percentiles(values: Sequence[float]) -> Dict[str, float]: ...
def canonicalize_tables(tables: Sequence[object]) -> List[Dict[str, object]]: ...
def compare_canonical_tables(python_tables, rust_tables) -> Dict[str, object]: ...
def write_benchmark_run(path: Path, payload: Mapping[str, object]) -> None: ...

# scripts/benchmark_rust_migration.py
def run_suite(mode: str, suite: str, input_path: str, pages: Sequence[int],
              warmups: int, runs: int, output_dir: str) -> Dict[str, object]: ...

# scripts/compare_rust_migration.py
def compare_runs(python_run: str, rust_run: str) -> Dict[str, object]: ...
~~~

`hexai_pdf_parser.benchmark_utils.summarize_timings` 是 legacy public API，结果严格保持 `count`、`total`、`mean`、`min`、`max` 五个键；迁移 benchmark 必须调用显式的 `summarize_timings_with_percentiles`，不得通过扩展 legacy 返回值来获取百分位统计。

Modes are exactly python、shadow、rust；unknown modes raise ValueError；default mode remains python。

- [ ] Step 1: Write failing percentile and canonicalization tests。

测试空 timings、单值、奇偶数量、稳定表格顺序、稳定 Cell 顺序、float 序列化、empty slots 和一个 deliberate text difference。断言 differences 中包含 field、python_value、rust_value 和 classification。

- [ ] Step 2: Run the new tests and confirm RED。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_benchmark.py
~~~

Expected: collection 或 assertion failure 明确指出 benchmark functions 尚未实现，而不是环境失败。

- [ ] Step 3: Implement deterministic statistics and output manifests。

实现 percentile interpolation、Table/Cell canonicalize 和 sorted-key JSON。每次运行至少写入以下字段：

~~~json
{
  "commit": "...",
  "mode": "python",
  "suite": "...",
  "input_sha256": "...",
  "warmups": 3,
  "runs": 10,
  "timings": {"count": 10, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
  "output_manifest": {"pages": 0, "tables": 0, "cells": 0, "failures": 0}
}
~~~

- [ ] Step 4: Add runner CLI and mode routing without changing the default。

Runner 接受 --mode、--suite、--pdf、--pages、--warmups、--runs、--output-dir 和 --fixture。它记录命令、环境、PDF hash、模型 hash（可用时）和现有 pipeline stage timings。PDF_RUST_MODE 只由迁移 facade 读取，默认 python。

- [ ] Step 5: Verify RED → GREEN and commit。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_benchmark.py
python scripts/benchmark_rust_migration.py --mode python --suite fixture --pdf tests/fixtures/page_000_vector.pdf --pages 0 --warmups 1 --runs 2 --output-dir output/rust_migration_benchmark/sprint-001
git diff --check
git add scripts src/hexai_pdf_parser/debug tests .gitignore
git add -f docs/superpowers/rust-migration/sprints/sprint-001-benchmark-baseline.md
git commit -m "feat: add Rust migration benchmark harness"
~~~

Expected: tests pass；summary JSON 写入；output/ 保持 ignored；python 模式不调用 Rust 路径。

## Sprint 002：扩展统一 DTO 和 PyO3 批量边界

Files:

- Create: rust/types.rs
- Modify: rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Create: tests/fixtures/rust_migration/dto/basic.json
- Create: tests/test_pdf_fast_dto.py
- Create: docs/superpowers/rust-migration/sprints/sprint-002-rust-core.md

Interfaces:

~~~rust
pub struct Rect4 { pub x0: f64, pub y0: f64, pub x1: f64, pub y1: f64 }
pub struct Line4 { pub x0: f64, pub y0: f64, pub x1: f64, pub y1: f64 }
pub struct WordDto { pub text: String, pub rect: Rect4, pub order: usize }
pub struct CharacterDto { pub text: String, pub rect: Rect4, pub order: usize }
pub struct NativeSpanDto { pub text: String, pub rect: Rect4, pub font: Option<String>, pub size: Option<f64>, pub order: usize, pub characters: Vec<CharacterDto>, pub source_position: usize }
pub struct CellDto { pub text: String, pub row: usize, pub col: usize, pub rect: Rect4, pub rowspan: usize, pub colspan: usize }
~~~

- [ ] Step 1: Add round-trip fixtures and failing binding tests。覆盖 normal、empty、非 ASCII、缺失 font/size、字符框、NaN、负坐标、order 字段和 malformed values。
- [ ] Step 2: Run DTO tests RED。

~~~powershell
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_dto.py
~~~

Expected: 新 DTO binding tests 失败；已有 Sprint 001 测试仍可区分。
- [ ] Step 3: Implement DTO structs and conversion errors。使用显式字段提取和 PyResult；禁止 unwrap、静默默认值和 Python object 引用。
- [ ] Step 4: Release the GIL only around owned Rust computation。Python extraction 和 result adaptation 在 allow_threads 外部执行。
- [ ] Step 5: Verify package and commit。

~~~powershell
cargo fmt --check
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_dto.py tests/test_pdf_fast_binding.py
git diff --check
git add Cargo.toml rust src/hexai_pdf_parser/rust_adapter.py tests
git add -f docs/superpowers/rust-migration/sprints/sprint-002-rust-core.md
git commit -m "feat: add owned DTO boundary for Rust table kernels"
~~~

## Sprint 003：迁移有线几何和线网区域算法

Files:

- Create: rust/geometry.rs
- Create: rust/wired.rs
- Modify: rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py
- Modify: tests/test_wired_table_extractor.py、tests/test_table_extractor.py
- Create: tests/test_pdf_fast_wired.py
- Create: tests/fixtures/rust_migration/wired/geometry.json
- Create: docs/superpowers/rust-migration/sprints/sprint-003-wired-geometry.md

Interfaces:

~~~rust
pub fn merge_h_lines(lines: Vec<Line4>, merge_group_tol: f64) -> Vec<Line4>;
pub fn merge_v_lines(lines: Vec<Line4>, h_lines: Vec<Line4>, line_tolerance: f64) -> Vec<Line4>;
pub fn merge_region_line_coordinates(lines: Vec<Line4>, horizontal: bool, tolerance: f64) -> Vec<Line4>;
pub fn lines_intersect(a: Line4, b: Line4, tolerance: f64) -> bool;
pub fn find_table_regions(h_lines: Vec<Line4>, v_lines: Vec<Line4>, tolerance: f64) -> Vec<RegionDto>;
pub fn snap_coordinates(values: Vec<f64>, anchors: Vec<f64>, tolerance: f64) -> Vec<f64>;
pub fn snap_grid_coordinates(region: RegionDto, tolerance: f64) -> GridDto;
pub fn complete_partial_outer_boundaries(grid: GridDto, tolerance: f64) -> GridDto;
~~~

- [ ] Step 1: 从 Python oracle 复制测试向量。覆盖空输入、equal coordinates、Python rounding/NaN ordering、tolerance 边界、端点接触、断开组件、相邻表格 gap、partial lines 和 open boundaries。
- [ ] Step 2: 确认 RED。

~~~powershell
cargo test wired
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py
~~~

- [ ] Step 3: 先实现 shared geometry，再实现 wired region。保留 comparison ordering、arithmetic order、tolerance inclusivity 和输出顺序。
- [ ] Step 4: 在 wired adapter 增加 shadow 比较；同一 extracted drawing DTO 同时执行 Python 和 Rust，差异必须生成诊断。
- [ ] Step 5: 验证和提交。

~~~powershell
cargo fmt --check
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_table_extractor.py
git diff --check
git add rust src tests
git add -f docs/superpowers/rust-migration/sprints/sprint-003-wired-geometry.md
git commit -m "feat: migrate wired table geometry kernels to Rust"
~~~

## Sprint 004：迁移有线 Cell、文字归属和区域装配

Files:

- Modify: rust/wired.rs、rust/types.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py
- Modify: tests/test_pdf_fast_wired.py、tests/test_wired_table_extractor.py、tests/test_table_extractor.py
- Create: tests/fixtures/rust_migration/wired/cells.json
- Create: docs/superpowers/rust-migration/sprints/sprint-004-wired-cells.md

Interfaces:

~~~rust
pub fn build_cells_for_region(region: RegionDto, grid: GridDto) -> Vec<CellDto>;
pub fn trim_ghost_edge_rows(cells: Vec<CellDto>, lines: Vec<Line4>, tolerance: f64) -> Vec<CellDto>;
pub fn merge_oversegmented_line_columns(cells: Vec<CellDto>, grid: GridDto, tolerance: f64) -> Vec<CellDto>;
pub fn assign_text_to_line_cells(cells: Vec<CellDto>, words: Vec<WordDto>, tolerance: f64) -> Vec<CellDto>;
pub fn extract_wired_region(input: WiredRegionInput) -> WiredRegionOutput;
~~~

- [ ] Step 1: 添加 Cell topology failing tests。覆盖 partial line、non-rectangular component、open boundary、physical empty row、ghost row、独立 empty column、colspan recompute、word crossing boundary、Cell order 和 line metadata。
- [ ] Step 2: 使用 page spy 验证 words 只在 Python 获取一次，Rust 只收到 WordDto。
- [ ] Step 3: 实现 Cell DTO 和 occupancy checks。每个槽位恰好被占用一次；任何 span 调整都重新检查冲突。
- [ ] Step 4: 仅在 rust 模式接入 wired extraction；shadow 模式比较完整 region result；保留 drawing、chart mask、clip、type3 glyph 和 Python Table/Cell。
- [ ] Step 5: 运行页面对比并提交。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_table_extractor.py tests/test_wireless_extractor_split.py
$env:PDF_RUST_MODE='python'
python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --output-dir output/pdf_rust_migration_wired_python_20260916
$env:PDF_RUST_MODE='rust'
python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --output-dir output/pdf_rust_migration_wired_rust_20260916
python scripts/compare_rust_migration.py --python output/pdf_rust_migration_wired_python_20260916 --rust output/pdf_rust_migration_wired_rust_20260916
git diff --check
git add rust src tests changes.md
git add -f docs/superpowers/rust-migration/sprints/sprint-004-wired-cells.md
git commit -m "feat: route wired cell assembly through Rust"
~~~

Expected: comparison equal true；page 415 chart filtering 和 page 196 table boundaries unchanged。

## Sprint 005：抽取共享几何、排序和候选算法

Files:

- Modify: rust/geometry.rs、rust/types.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/table_extractor.py、src/hexai_pdf_parser/tables/wireless_table_recovery.py
- Create: tests/test_pdf_fast_shared_geometry.py
- Create: tests/fixtures/rust_migration/shared/geometry.json
- Create: docs/superpowers/rust-migration/sprints/sprint-005-shared-geometry.md

Interfaces:

~~~rust
pub fn rect_overlap(a: Rect4, b: Rect4, strict: bool) -> bool;
pub fn filter_regions(regions: Vec<Rect4>, excluded: Vec<Rect4>, allowed: Vec<Rect4>) -> Vec<Rect4>;
pub fn cluster_rows(items: Vec<OrderedRectDto>, tolerance: f64) -> Vec<RowClusterDto>;
pub fn cluster_columns(items: Vec<OrderedRectDto>, tolerance: f64) -> Vec<ColumnClusterDto>;
pub fn stable_output_order(tables: Vec<TableCandidateDto>) -> Vec<TableCandidateDto>;
~~~

- [ ] Step 1: 为 overlap、region exclusion、row/column clustering 和 output order 增加直接 vectors。
- [ ] Step 2: 运行 focused tests RED。
- [ ] Step 3: 实现共享 kernels；wired 和 wireless 不再保留重复实现。
- [ ] Step 4: 在 TableExtractor 和 wireless candidate boundary 做 shadow compare。
- [ ] Step 5: 运行回归、benchmark 和提交。

~~~powershell
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_shared_geometry.py tests/test_table_extractor.py tests/test_wireless_table_recovery.py
python scripts/benchmark_rust_migration.py --mode both --suite shared-geometry --pdf tests/fixtures/page_437_wireless.pdf --pages 0 --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-005
git diff --check
git add rust src tests
git add -f docs/superpowers/rust-migration/sprints/sprint-005-shared-geometry.md
git commit -m "feat: share Rust geometry kernels across table paths"
~~~

## Sprint 006：迁移 Native Span、Atom 和 Text Run

Files:

- Create: rust/native_span.rs
- Modify: rust/types.rs、rust/lib.rs、src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/wireless_table_recovery.py
- Modify: src/hexai_pdf_parser/tables/wireless_structure/span_chain.py、text_runs.py
- Create: tests/test_pdf_fast_wireless.py
- Create: tests/fixtures/rust_migration/wireless/native_span.json
- Create: docs/superpowers/rust-migration/sprints/sprint-006-native-span.md

Interfaces:

~~~rust
pub fn build_text_runs(spans: Vec<NativeSpanDto>, region: Rect4) -> Vec<TextRunDto>;
pub fn build_atoms(runs: Vec<TextRunDto>, region: Rect4) -> Vec<AtomDto>;
pub fn merge_wrapped_rows(atoms: Vec<AtomDto>, tolerance: f64) -> Vec<AtomDto>;
pub fn infer_output_order_mode(atoms: Vec<AtomDto>) -> OutputOrderMode;
pub fn recover_native_candidates(input: NativeRecoveryInput) -> NativeRecoveryOutput;
~~~

- [ ] Step 1: 增加 source continuity 和 text composition failing vectors。覆盖 ASCII、CJK、mixed text、missing font/size、character bboxes、source positions、wrapped fields、currency separators、whitelisted spaced CJK words 及男/女不合并反例。
- [ ] Step 2: 用 page spy 确认 native-span adapter 不调用 get_text("words")。
- [ ] Step 3: 实现 span → run → atom；保留 source refs、text order、bbox witness、flow range 和 merge kind。
- [ ] Step 4: 添加 text、bbox、source position、span refs、order mode 和 field boundary 的 differential report。
- [ ] Step 5: 测试、benchmark 和提交。

~~~powershell
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wireless.py tests/test_wireless_structure_span_chain.py tests/test_wireless_structure_text_runs.py tests/test_wireless_output_order.py
python scripts/benchmark_rust_migration.py --mode both --suite native-span --pdf tests/fixtures/page_437_wireless.pdf --pages 0 --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-006
git diff --check
git add rust src tests
git add -f docs/superpowers/rust-migration/sprints/sprint-006-native-span.md
git commit -m "feat: migrate native span and text run kernels to Rust"
~~~

## Sprint 007：迁移中文/混合无线结构恢复

Files:

- Create: rust/wireless_structure.rs
- Modify: rust/native_span.rs、rust/types.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/wireless_structure/{columns,continuations,grid,header_topology,hybrid_body,logical_grid,merged_cells,recoverer}.py
- Modify: src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py
- Modify: tests/test_wireless_structure_*.py、tests/test_wireless_table_recovery.py、tests/test_wireless_extractor_split.py
- Create: tests/test_pdf_fast_wireless_structure.py
- Create: docs/superpowers/rust-migration/sprints/sprint-007-chinese-structure.md

Interfaces:

~~~rust
pub fn infer_column_bands(atoms: Vec<AtomDto>, region: Rect4, config: StructureConfig) -> Vec<ColumnBandDto>;
pub fn build_logical_grid(atoms: Vec<AtomDto>, bands: Vec<ColumnBandDto>, config: StructureConfig) -> LogicalGridDto;
pub fn infer_header_topology(grid: LogicalGridDto, config: StructureConfig) -> LogicalGridDto;
pub fn resolve_exact_slot_conflicts(grid: LogicalGridDto) -> LogicalGridDto;
pub fn materialize_empty_cells(grid: LogicalGridDto) -> Vec<CellDto>;
pub fn recover_cells_from_region(input: NativeRegionInput) -> NativeRegionOutput;
~~~

- [ ] Step 1: 增加 independent leaf columns、incomplete 1:2 header pairs、non-empty rowspan blockers、exact slot conflicts、empty slots、wrapped leaf headers、paired CJK artifacts、sparse alignment artifacts 和 continuation rows 的 RED vectors。
- [ ] Step 2: 运行完整 structure tests，确认 Rust entry points 尚未实现时按预期失败。
- [ ] Step 3: 按 columns → rows → logical grid → header topology → spans → empty slots 的顺序实现；进入结构层后只允许 Atom、ColumnBand、PhysicalCell 和 LogicalGrid DTO。
- [ ] Step 4: 每次 colspan/rowspan 调整后重算 occupancy；冲突 span 拒绝；未覆盖槽位生成独立空 1x1 Cell。
- [ ] Step 5: 增加 Chinese facade shadow/rust；测试 get_text("words")、zebra 和 legacy 在 zh/mixed 路径中一旦被请求就失败。
- [ ] Step 6: 测试、benchmark 和提交。

~~~powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wireless_structure.py tests/test_wireless_structure_*.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_wireless_output_order.py tests/test_unify_wireless_recovery.py
python scripts/benchmark_rust_migration.py --mode both --suite chinese-wireless --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,1002,1014 --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-007
git diff --check
git add rust src tests changes.md
git add -f docs/superpowers/rust-migration/sprints/sprint-007-chinese-structure.md
git commit -m "feat: migrate Chinese wireless structure recovery to Rust"
~~~

## Sprint 008：迁移共享 Native Recovery 和候选选择

Files:

- Modify: rust/native_span.rs、rust/wireless_structure.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/wireless_table_recovery.py
- Modify: src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py、wireless_table_extractor.py
- Modify: tests/test_wireless_table_recovery.py、tests/test_wireless_extractor_split.py、tests/test_unify_wireless_recovery.py
- Create: docs/superpowers/rust-migration/sprints/sprint-008-shared-recovery.md

Interfaces:

~~~rust
pub fn recover_wireless_tables(input: WirelessRecoveryInput) -> WirelessRecoveryOutput;
pub fn select_candidates(candidates: Vec<TableCandidateDto>, excluded: Vec<Rect4>, allowed: Vec<Rect4>) -> Vec<TableCandidateDto>;
pub fn table_quality(candidate: &TableCandidateDto) -> f64;
~~~

- [ ] Step 1: 为 row clustering、column tracks、candidate runs 和 quality selection 增加 RED vectors。
- [ ] Step 2: 基于已验证的 native-span 和 structure DTO 实现共享 Rust recovery batch。
- [ ] Step 3: Python 保留 diagnostics、excluded/allowed filtering、empty result、exception mapping 和 monkeypatch surface。
- [ ] Step 4: 运行 differential tests 和 shared-wireless benchmark。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_unify_wireless_recovery.py tests/test_wireless_output_order.py
python scripts/benchmark_rust_migration.py --mode both --suite shared-wireless --pdf tests/fixtures/page_437_wireless.pdf --pages 0 --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/sprint-008
~~~

- [ ] Step 5: 只有 zh/mixed 输出和 no-words tests 通过后提交。

~~~powershell
git diff --check
git add rust src tests changes.md
git add -f docs/superpowers/rust-migration/sprints/sprint-008-shared-recovery.md
git commit -m "feat: migrate shared wireless candidate recovery to Rust"
~~~

## Sprint 009：迁移英文 Zebra、General Wireless 和 Legacy 纯算法

Files:

- Create: rust/english_wireless.rs
- Modify: rust/types.rs、rust/lib.rs、src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/extractors/english_table_extractor.py、wireless_table_extractor.py
- Modify: src/hexai_pdf_parser/tables/table_extractor.py only at legacy pure-rule adapter boundary
- Create: tests/test_pdf_fast_english_wireless.py
- Modify: tests/test_page_347_structure.py、test_rule_first_table_detection.py、test_table_extractor.py
- Create: docs/superpowers/rust-migration/sprints/sprint-009-english-wireless.md

Interfaces:

~~~rust
pub fn group_backgrounds(backgrounds: Vec<BackgroundDto>, tolerance: f64) -> Vec<BackgroundGroupDto>;
pub fn detect_zebra_rows(input: ZebraInput) -> Vec<RowBandDto>;
pub fn assign_words_to_zebra_rows(rows: Vec<RowBandDto>, words: Vec<WordDto>) -> Vec<RowBandDto>;
pub fn infer_english_columns(input: EnglishGridInput) -> Vec<ColumnBandDto>;
pub fn build_english_cells(input: EnglishGridInput) -> Vec<CellDto>;
pub fn build_general_wireless_cells(input: GeneralWirelessInput) -> Vec<CellDto>;
pub fn build_legacy_text_alignment(input: LegacyAlignmentInput) -> Vec<CellDto>;
~~~

- [ ] Step 1: 增加 drawing/background/words DTO fixtures 和 RED tests。覆盖 empty drawings、white/colored bands、separated tables、header rows、boundary words、dollar signs、pure amounts、metric tokens、continuation rows、sparse rowspans、empty columns 和 legacy flags。
- [ ] Step 2: 保持 extraction 和 routing 在 Python；Rust 只接 normalized background/word DTO；保留 zebra → general wireless → text-alignment/fallback 顺序。
- [ ] Step 3: 实现 Rust English kernels；currency 和 financial token rules 必须有直接 vectors，不增加 Python oracle 之外的业务特例。
- [ ] Step 4: 运行英文回归和 benchmark。

~~~powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_english_wireless.py tests/test_page_347_structure.py tests/test_rule_first_table_detection.py tests/test_wireless_extractor_split.py tests/test_wireless_output_order.py tests/test_table_extractor.py
python scripts/benchmark_rust_migration.py --mode both --suite english-wireless --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 347,415,437 --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-009
git diff --check
git add rust src tests changes.md
git add -f docs/superpowers/rust-migration/sprints/sprint-009-english-wireless.md
git commit -m "feat: migrate English wireless kernels to Rust"
~~~

Expected: page 347 preserves English recovery；page 415 chart masking unchanged；zh/mixed still do not request words/zebra/legacy。

## Sprint 010：迁移可 DTO 化的表头和结构后处理

Files:

- Create: rust/table_normalization.rs
- Modify: rust/types.rs、rust/lib.rs、src/hexai_pdf_parser/rust_adapter.py
- Inspect and modify only tested pure sections of src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py and financial_header_handler.py
- Modify: tests/test_financial_header_normalizer.py、test_header_upward_merge.py、test_header_wrapping_page_347_169.py、test_wrapped_leaf_headers.py、test_wrapped_field_font_and_witness.py
- Create: tests/test_pdf_fast_table_normalization.py
- Create: docs/superpowers/rust-migration/sprints/sprint-010-table-normalization.md

Interfaces:

~~~rust
pub fn infer_header_structure(input: HeaderGridInput) -> HeaderGridOutput;
pub fn merge_header_spans(input: HeaderGridInput) -> HeaderGridOutput;
pub fn normalize_financial_header_tokens(input: HeaderTokenInput) -> HeaderTokenOutput;
~~~

- [ ] Step 1: 审计每个 normalizer function 并写入 capability matrix。只消费 DTO 的函数必须排入 Rust；构造公开 Python object、调用外部服务或编码未批准 domain policy 的函数保留 Python 并记录理由。
- [ ] Step 2: 为 header topology、wrapped labels、witness、financial tokens 和 rejection cases 增加 RED vectors。
- [ ] Step 3: 实现已分类纯 kernel，Python 保留公开对象装配。
- [ ] Step 4: 运行 normalizer tests 和 benchmark。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_table_normalization.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_header_wrapping_page_347_169.py tests/test_wrapped_leaf_headers.py tests/test_wrapped_field_font_and_witness.py
python scripts/benchmark_rust_migration.py --mode both --suite table-normalization --pdf tests/fixtures/page_437_wireless.pdf --pages 0 --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-010
~~~

- [ ] Step 5: 提交时附上 Python-retained functions 清单。

~~~powershell
git diff --check
git add rust src tests changes.md
git add -f docs/superpowers/rust-migration/sprints/sprint-010-table-normalization.md docs/superpowers/rust-migration/capability-matrix.md
git commit -m "feat: migrate DTO-compatible table normalization to Rust"
~~~

## Sprint 011：Shadow 模式、逐路径切换和回归门禁

Files:

- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: wired、Chinese/shared wireless 和 English extractor facades
- Modify: src/hexai_pdf_parser/core/pipeline.py only for stable stage labels if required
- Create: tests/test_rust_migration_routing.py
- Create: docs/superpowers/rust-migration/sprints/sprint-011-routing.md

Interfaces:

~~~python
def get_rust_mode() -> str: ...
def run_python_or_rust(mode: str, python_fn, rust_fn, input_dto): ...
def assert_equivalent(path: str, python_value, rust_value) -> None: ...
~~~

- [ ] Step 1: 为 python、shadow、rust 和 invalid mode 增加 routing tests。无环境变量时必须为 python；shadow 比较后返回 Python；rust 返回 Rust；invalid mode 抛出清晰配置错误。
- [ ] Step 2: 添加 path-specific feature gates。已验证 wired 可独立启用，native-span/English 可保持 Python；不改变公开 API 或 CLI flags。
- [ ] Step 3: 对代表页运行 shadow。

~~~powershell
$env:PDF_RUST_MODE='shadow'
python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --output-dir output/pdf_rust_migration_shadow_20260916
~~~

Expected: no unclassified difference；没有 Chinese/mixed words access；没有 chart/table boundary regression。
- [ ] Step 4: 按 wired → shared geometry → native-span → Chinese/mixed → English → normalization 的顺序逐路径切换，每次复跑该路径测试和 benchmark。
- [ ] Step 5: 通过所有 Evaluator 后提交。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_routing.py tests/test_pdf_fast_binding.py tests/test_pdf_fast_dto.py tests/test_pdf_fast_wired.py tests/test_pdf_fast_wireless.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_english_wireless.py tests/test_wireless_extractor_split.py tests/test_rule_first_table_detection.py
git diff --check
git add src tests changes.md
git add -f docs/superpowers/rust-migration/sprints/sprint-011-routing.md
git commit -m "feat: add differential routing for Rust table paths"
~~~

## Sprint 012：完整前后 Benchmark、页面视觉验证和发布物

Files:

- Modify: scripts/benchmark_rust_migration.py、scripts/compare_rust_migration.py
- Create: docs/superpowers/rust-migration/benchmarks/benchmark-2026-09-16.md
- Create: docs/superpowers/rust-migration/sprints/sprint-012-final-evaluation.md
- Modify: changes.md
- Inspect: Cargo.toml、pyproject.toml、build.sh、setup.py、version

- [ ] Step 1: 运行函数级 benchmark suites。

~~~powershell
python scripts/benchmark_rust_migration.py --mode both --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/final/wired-geometry
python scripts/benchmark_rust_migration.py --mode both --suite native-span --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/final/native-span
python scripts/benchmark_rust_migration.py --mode both --suite table-normalization --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/final/table-normalization
~~~

- [ ] Step 2: 运行区域和页面 benchmark。

~~~powershell
python scripts/benchmark_rust_migration.py --mode both --suite page --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/final/pages
~~~

- [ ] Step 3: 运行全量 PDF Python 和 Rust 测量。

~~~powershell
python scripts/benchmark_rust_migration.py --mode python --suite full-pdf --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/final/python
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --suite full-pdf --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/final/rust
python scripts/compare_rust_migration.py --python output/rust_migration_benchmark/final/python --rust output/rust_migration_benchmark/final/rust --report docs/superpowers/rust-migration/benchmarks/benchmark-2026-09-16.md
~~~

- [ ] Step 4: 运行结构和视觉页面验证。

~~~powershell
$env:PDF_RUST_MODE='python'
python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --output-dir output/pdf_rust_migration_final_python_20260916
$env:PDF_RUST_MODE='rust'
python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --output-dir output/pdf_rust_migration_final_rust_20260916
python scripts/compare_rust_migration.py --python output/pdf_rust_migration_final_python_20260916 --rust output/pdf_rust_migration_final_rust_20260916
~~~

Inspect both JSON and PNG for table count, source, rows/cols, bbox, text, Cell order, spans, empty slots, frame boundaries, chart masking and neighboring-table separation。

- [ ] Step 5: 运行 Rust 全量输出到新目录。

~~~powershell
$env:PDF_RUST_MODE='rust'
python -c "from hexai_pdf_parser.core.pdf_parser import PDFParser; p=PDFParser(r'D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf'); r=p.parse(output_dir=r'output/pdf_rust_migration_final_full_20260916'); assert r.code == 1, r.message; assert r.data.page_count == 1023"
~~~

确认所有页覆盖、timings.json 存在、输出目录不是旧目录。

- [ ] Step 6: 验证测试、构建和发布物。

~~~powershell
cargo fmt --check
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q
maturin build --release
maturin sdist
git diff --check
~~~

检查生成物：

- wheel tag 含 cp37-abi3，不能是 py3-none-any；
- metadata version 为 1.1.1；
- Requires-Python 为 >=3.7；
- console entry point 为 hexai_pdf_parser=hexai_pdf_parser.cli:main；
- sdist 含 Cargo.toml、rust/ 和 Python src/；
- sdist 排除 output/、target/、.venv/、本机 PDF 和开发目录。

- [ ] Step 7: 写最终评估并提交小型报告。

最终报告包含 Python total、Rust total、pure algorithm time、FFI/adapter time、P50/P95/P99、speedup/regression、output equality、page coverage、failed pages 和所有明确保留 Python 的函数。

~~~powershell
git diff --check
git add changes.md
git add -f docs/superpowers/rust-migration/benchmarks docs/superpowers/rust-migration/sprints/sprint-012-final-evaluation.md
git commit -m "docs: record Rust migration benchmark and final evaluation"
~~~

## 最终验收清单

- [ ] capability-matrix.md 没有未分类的纯 Python 表格算法。
- [ ] 每个迁移函数都有直接输入/输出测试，执行记录包含 RED → GREEN。
- [ ] cargo test、相关 pytest、完整 pytest、cargo fmt --check 和 git diff --check 通过。
- [ ] wired、中文/混合 wireless、英文 wireless 和表头后处理均有 Rust/Python differential report。
- [ ] Python、shadow、Rust 三种模式均可运行，默认模式和公开 API 兼容。
- [ ] 中文/混合路径没有 words 回读、zebra 或 legacy 回退。
- [ ] 函数、FFI、区域、页面、全量 PDF 五层 benchmark 已保存。
- [ ] 最终结构化 JSON 和 PNG 逐页核验无未分类差异。
- [ ] 全量 PDF 解析输出位于新目录，覆盖 1023 页，未覆盖旧结果。
- [ ] wheel、sdist、abi3、版本、入口和 Python 下限检查通过。
- [ ] Evaluator 报告为 pass；否则只报告 repair 或待决策状态，不宣称完成。
