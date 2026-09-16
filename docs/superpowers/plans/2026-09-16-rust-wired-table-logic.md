# 有线表格逻辑 Rust 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐任务执行并在任务间评审。每步用 `- [ ]` 跟踪。若使用 subagent，model 只能是 `gpt-5.6-luna`。

**目标：** 保留 Python 的 PDF 数据提取和对外对象，在 PyO3 中按函数精确复现 `WiredTableExtractor` 的纯线网/单元格计算。

**架构：** Python `_extract_lines_from_drawings()` 及页面文字提取保持原样，并将结果批量转成 owned DTO。Rust 负责线段归并、交点连通、区域边界、cell 几何和 words DTO 的文字归属；Python facade 仍构造 `Table`/`Cell` 并保留 chart-mask 状态。

**技术栈：** Rust、PyO3、maturin、现有 setuptools 包、pytest、PyMuPDF。

## 全局约束

- Python 最低版本保持 `>=3.7`；wheel 采用 abi3 且按 OS、CPU 架构/native runtime 分别构建，不输出或假定通用 `py3-none-any` wheel。
- Python/PyMuPDF 独占 PDF/Page/drawing/words 访问；Rust 只消费显式 owned DTO，不回调 Python。
- 逐函数等价；不改算法策略、容差、排序、舍入、异常/空结果、表格来源或公开 API。
- 批量 FFI 以页或表格区域为边界；Rust 长计算期间释放 GIL；不做 benchmark 或性能门槛。
- 保留 page 415 chart 过滤、矩形边去重、clip、type3 glyph 和 open-boundary cell 等 feature-dev 基线行为。
- 先写失败的精确输入/输出测试，再实现函数；生产调用只有阶段验收后才接 Rust。
- 每个下面列出的纯函数单独执行 RED（pytest 与 cargo test 至少一侧按预期失败）→ GREEN（两侧同向量精确通过）→ Python/Rust 逐字段对照；通过后再开始下一个函数，不将整文件重写作为一个任务。

## 文件边界

- 新增：`Cargo.toml`、`rust/lib.rs`、`rust/wired.rs`、`src/hexai_pdf_parser/rust_adapter.py`、`tests/test_pdf_fast_binding.py`、`tests/fixtures/rust_migration/wired/`。
- 修改：`pyproject.toml`、`build.sh`、`src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py`、`tests/test_wired_table_extractor.py`、`changes.md`。
- 页面数据提取方法 `_extract_lines_from_drawings()`、其 drawing helper 与 Python Table/Cell 适配器继续留在 Python；本计划不迁 `TableExtractor` 编排或 visualizer。

## 函数迁移清单

| Python 函数 | Rust 对应函数 | 基线用例 |
|---|---|---|
| `_merge_h_lines` | `merge_h_lines` | 首批绑定向量；同坐标、容差边界、3pt 线段间隙和空输入 |
| `_merge_v_lines` | `merge_v_lines` | 竖线段容差连接与相邻表格 gap 反例 |
| `_merge_region_line_coordinates` | `merge_region_line_coordinates` | 区域内近邻片段连接、互不连接和 region 隔离 |
| `_lines_intersect` | `lines_intersect` | 端点接触、容差内接触、超容差不接触 |
| `_find_table_regions` | `find_table_regions` | 无交点横线过滤、断开组件拆分、短竖线参与 |
| `_snap_coordinates` | `snap_coordinates` | anchor 最近匹配、重复坐标合并和排序 |
| `_snap_grid_coordinates` | `snap_grid_coordinates` | 短线不扩张边界、完整边界吸附与局部坐标保留 |
| `_complete_partial_outer_boundaries` | `complete_partial_outer_boundaries` | 开放右边/底边恢复与内部部分线不扩张 |
| `_build_cells_for_region` | `build_cells_for_region` | 非矩形组件、span、occupancy、空槽和开放边界 |
| `_trim_ghost_edge_rows` | `trim_ghost_edge_rows` | 物理空行保留、无支撑或超薄 ghost 行移除 |
| `_merge_oversegmented_line_columns` | `merge_oversegmented_line_columns` | 删除伪列后 colspan 重算、独立空列保留 |
| `_assign_text_to_line_cells` | `assign_text_to_line_cells` | Python words DTO、物理列边界拆分和单词归属 |
| `_extract_lines_from_drawings` | 保留 Python | PyMuPDF drawing/clip/background/chart/type3/tiled-image 提取合同 |
| `extract` | 保留 Python facade | `Table`/`Cell` 构造、confidence/source、chart mask 与 API 兼容 |

## Task 1：固定首个函数合同并搭建扩展

**接口：** Rust `merge_h_lines(Vec<Line4>, f64) -> Vec<Line4>`；PyO3 同名批量入口；Python adapter 输入/输出 `list[tuple[float,float,float,float]]`。首个提交保持生产路由不变。

- [ ] 在 `tests/test_pdf_fast_binding.py` 增加 sprint-001 列出的三组精确输入/输出测试，并确认扩展缺失时失败。
- [ ] 在 Rust `#[cfg(test)]` 中使用同一三组向量，先确认 `cargo test` 因函数缺失失败。
- [ ] 创建 PyO3 abi3 模块和 `merge_h_lines`，保留 Python 侧类型适配；在 Maturin mixed-project 构建中将模块安装到 `hexai_pdf_parser._pdf_fast`。
- [ ] 将 `pyproject.toml` 构建后端切到 maturin，保留 Python package/data、console entry point 和 `requires-python >=3.7`；调整 `build.sh` 通过实际生成的 abi3 平台 wheel 选取发布文件。
- [ ] 运行 `cargo test`、`maturin develop --release`、`python -m pytest -q tests/test_pdf_fast_binding.py`、`maturin build --release`；检查 wheel tag 与 metadata。

## Task 2：逐函数迁移线段归并和区域发现

**Rust 输入/输出：** `Line4=(x0,y0,x1,y1)`；区域结果按 `(BBox4, Vec<Line4>, Vec<Line4>)` 顺序输出。容差从 Python 当前实例参数显式传入。

- [ ] 先为 `_merge_v_lines`、`_merge_region_line_coordinates`、`_lines_intersect` 和 `_find_table_regions` 增加重复/精确预期用例；复用现有测试 `test_merge_v_lines_bridges_segmented_borders_within_tolerance`、`test_merge_v_lines_does_not_connect_adjacent_tables_separated_by_gap`、`test_region_line_merge_connects_nearby_vertical_fragments`、`test_region_line_merge_keeps_disconnected_vertical_fragments_separate`、`test_find_table_regions_splits_disconnected_line_components`。
- [ ] 在 Rust 模块逐函数实现各纯几何函数，并以对应 `cargo test` 用例锁住容差、连通组件和排序；Python 测试用同一 fixture 逐字段比较。
- [ ] 扩展 Rust 批处理入口接收完整线段批次；Python 的 `extract()` 暂不切生产路径，先将 Rust 结果与 Python 当前方法结果比较。

## Task 3：迁移坐标 snap、外边界和 ghost 行规则

- [ ] 为 `_snap_coordinates`、`_snap_grid_coordinates`、`_complete_partial_outer_boundaries` 和 `_trim_ghost_edge_rows` 固定边界向量；包含 anchor 相撞、短线不得吸附区域边界、物理闭合空行保留、无物理支撑 ghost 行删除。
- [ ] 在 Rust 使用与 Python 等价的 `f64` 运算顺序、排序键和阈值；每个函数先有 Rust 单测和 Python binding 差分用例。
- [ ] 通过 `test_trim_ghost_edge_rows_preserves_physically_closed_empty_rows`、`test_trim_ghost_edge_rows_removes_virtual_or_thin_edge_rows`、`test_page_291_bottom_physical_empty_row_is_preserved` 及现有 snap/boundary 测试。

## Task 4：迁移 Cell 拓扑、合并与文字归属

**DTO 合同：** Rust 输入 bbox、横/竖 `Line4` 与由 Python `page.get_text("words")` 提取并排序的 word 元组；输出有序 `CellDto(text,row_index,col_index,bbox,rowspan,colspan)` 及区域真实线段元数据。转换为项目 `Cell` 仅在 Python 完成。

- [ ] 为 `_build_cells_for_region`、`_merge_oversegmented_line_columns`、`_assign_text_to_line_cells` 建立逐字段测试；覆盖 partial line、open edge、span、独立空列、word 跨物理列边界和文字命中。
- [ ] Rust 单测固定 occupancy、Cell 输出顺序、bbox、空文本、rowspan/colspan 与文字；Python 输入 DTO 测试确保 PDF 的 words 获取留在 Python。
- [ ] 跑 `test_build_cells_respects_partial_line_segments_and_merges_missing_edges`、`test_build_cells_materializes_non_rect_component_as_safe_spans`、`test_merge_oversegmented_line_columns_recomputes_colspan_after_pruning`、`test_merge_oversegmented_line_columns_preserves_independent_empty_column`、`test_assign_text_to_line_cells_splits_word_at_physical_column_boundary` 及 open-boundary 用例。

## Task 5：切换有线路由并端到端验收

- [ ] 切换 Rust 路由前，使用 `python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --output-dir output/pdf_rust_migration_wired_baseline_20260916` 保存 Python JSON/PNG；将其与 Task 5 的 Rust 输出目录逐字段、逐页对照。
- [ ] 在 `WiredTableExtractor.extract()` 将当前已通过等价检查的 Rust 批处理结果适配成原有 `Table`；保留 drawing 提取、chart-mask 绑定和 method/monkeypatch 兼容面。
- [ ] 跑 `cargo test` 与 `python -m pytest -q tests/test_pdf_fast_binding.py tests/test_wired_table_extractor.py tests/test_table_extractor.py`，另跑 `tests/test_wireless_extractor_split.py` 确认共享 facade 未受影响。
- [ ] 使用 `python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --output-dir output/pdf_rust_migration_wired_20260916` 产生全新页面 JSON/PNG；对照基线 table 数、source、bbox、Cell 文本/跨度与 page 415 图表屏蔽。
- [ ] 有线完整路径稳定后，以 `PDFParser.parse(output_dir=...)` 对 `fix/zh_all_table_pages.pdf` 全量解析到新的 `output/pdf_rust_migration_wired_full_20260916`；核验 1023 页覆盖、结果 JSON 和 table PNG 数量，再记录 `changes.md`。
- [ ] 只有以上结构化和视觉检查通过，才移除已不再被生产使用的 Python 算法实现；保留必要 golden vectors 和测试输入。

## 验收命令

```powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_binding.py tests/test_wired_table_extractor.py tests/test_table_extractor.py tests/test_wireless_extractor_split.py
maturin build --release
maturin sdist
git diff --check
```

页面端测按 Task 5 的 `test_single.py` 命令执行；全量解析的 `ApiResult.code` 必须为 `1`，`Document.page_count` 必须与输入 PDF 页数一致。

全量解析命令：

```powershell
python -c "from hexai_pdf_parser.core.pdf_parser import PDFParser; p=PDFParser(r'D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf'); r=p.parse(output_dir=r'output/pdf_rust_migration_wired_full_20260916'); assert r.code == 1, r.message; assert r.data.page_count == 1023"
```
