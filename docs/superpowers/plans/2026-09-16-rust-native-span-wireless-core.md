# Native-span 无线核心 Rust 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐任务执行并在任务间评审。每步用 `- [ ]` 跟踪。若使用 subagent，model 只能是 `gpt-5.6-luna`。

**目标：** 将中文/混合 native-span 结构恢复及英文/中文共享候选恢复中的纯算法逐函数迁入 Rust，同时保留 Python/PyMuPDF 的原生文字提取和现有路由。

**架构：** Python 采集 native spans、字符 bbox、遍历顺序和 source position，按页或 region 传给 Rust。Rust 处理 span/atom/text run、行列带、候选/table topology、逻辑网格、跨度与空槽位；Python 将 owned result DTO 适配回当前 `Table`/`Cell` 和 diagnostics。

**技术栈：** 已建立的 `hexai_pdf_parser._pdf_fast`、PyO3、maturin、Rust、pytest、PyMuPDF。

## 全局约束

- 基线是 `feature-dev@dc00211fe0cf95bc8c3412c883311fe86f8d835b`；所有可观察输出按精确规则保持，不增加容差或业务文字分支。
- PDF/Page/rawdict/native span 只由 Python 读取。Span DTO 保留 text、bbox、font、size、原始顺序、character bbox 与 source position。
- `zh`/`mixed` 只走 native-span；span 到 atom/text run 阶段完成同字段文字组合并保留来源连续性；结构阶段不调用 `page.get_text("words")`，不回退 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或 page words 二次重建。
- 列带/网格保留独立叶子列；span/atom 位于同槽位不构成合并证据。多层标题只按已有几何/拓扑规则推导，不硬编码业务文本。
- `rowspan` 在物理行到逻辑网格之后、空槽位物化之前判定；跨度变化后重跑 occupancy；每个未覆盖槽位单独物化空 `1x1` Cell。
- 每个 FFI 调用按页/region 批量传值并在纯计算时释放 GIL；每个迁移函数和完整 native-span 路径都必须执行独立 benchmark。
- 每个迁移函数单独写 Python 与 Rust 精确向量，确认 RED 后实现 GREEN；对该函数所有返回字段做精确差分后才进入下一函数。组合入口测试不能代替 helper 的直接合同测试。

## 文件边界

- 修改：`src/hexai_pdf_parser/tables/wireless_table_recovery.py`、`src/hexai_pdf_parser/tables/wireless_structure/{recoverer,span_chain,text_runs,columns,grid,logical_grid,header_topology,merged_cells,hybrid_body,continuations}.py`、`src/hexai_pdf_parser/tables/extractors/{chinese_table_extractor,english_table_extractor,wireless_table_extractor}.py`。
- 新增：`rust/wireless_native.rs`、`rust/wireless_native/{span_runs,columns,grid,recovery}.rs`、`tests/test_pdf_fast_wireless.py`、`tests/fixtures/rust_migration/wireless/`。
- 不修改 PDF extraction adapter 和 `Table`/`Cell` 公共数据类型；仅在原 Python 调用点替换纯计算实现。

## 函数迁移清单

| 边界 | 逐函数迁移的入口 | 留在 Python 的工作 |
|---|---|---|
| `wireless_table_recovery.py` | `merge_text_strips`、`_split_raw_field_strip`、`_detect_native_span_page_signal`、`_split_wide_field_strip`、`_row_cluster`、`merge_wrapped_rows`、`_column_tracks`、`_assign_column`、`_table_runs`、`_field_record_runs`、`_two_line_field_record_runs`、`_single_field_record_runs`、`_two_row_field_runs`、`_prepend_short_title`、`_prepend_headers`、`_drop_orphan_field_before_title`、`_completion_date_continuations`、`_build_table`、`_significant_overlap`、`_table_quality`、`recover_wireless_tables` 的纯候选/选择计算 | `collect_native_spans`、PyMuPDF rawdict 读取、`Table` 构造、debug PDF/HTML/overlay 输出 |
| `span_chain.py` | `_split_packed_numeric_fields`、`region_spans` 及其 bbox/native-span 纯 helper | 从 `NativeSpan` 转 owned DTO |
| `text_runs.py` | `script_kind`、`infer_output_order_mode`、`build_text_runs`、`merge_same_band_native_line_runs` 及其全部判定/几何 helper | facade 调用和 DTO 适配 |
| `columns.py` | `horizontal_overlap`、`is_sparse_left_section_title`、`is_spanning_header`、`infer_column_bands`、`assign_column`、`prune_paired_cjk_artifact_bands`、`prune_sparse_alignment_artifact_bands` | BBox/Python 类型转换 |
| `grid.py` | `_same_visual_row`、`_can_join_row_group`、`_cluster_rows`、`build_grid` 及行几何 helper | DTO 适配 |
| `header_topology.py` | `infer_header_cutoff`、`refine_leaf_bands`、`rescue_sparse_body_bands`、`rescue_header_only_note_bands`、`rescue_header_only_leaf_bands`、父叶 span 推断、`annotate_columns` 及其纯 helper | BBox/Python 类型转换 |
| `logical_grid.py` | `_wrapped_leaf_header_span`、`_grouped_mixed_leaf_header_span`、`_row_components`、`build_logical_grid`、`merge_header_spans`、`materialize_empty_cells` | 项目 `Cell` 实例化 |
| `merged_cells.py` | `resolve_exact_slot_conflicts`、`merge_same_slot_fragments`、`merge_multiline_cells` 及 continuity/slot helper | Atom DTO 输入输出 |
| `hybrid_body.py` / `continuations.py` | `recover_hybrid_body_cells`、`merge_column_continuations` 及其纯几何/occupancy helper | 页面提取与最终 `Cell` 构造 |
| `recoverer.py` | `_has_occupancy_conflict`、`_commit_header_spans_or_keep_base`、region 结构组合；`recover_cells_from_region` 的 Rust 计算核心 | `collect_native_spans(page, region)`、API tuple 与 `Cell` 适配 |

表中入口调用的所有私有纯 helper 一并逐函数迁移并添加直接 Rust 单测；不得把“文件已迁移”当作函数验收证据。

## Task 1：定义共享 NativeSpan DTO 与输入快照

- [ ] 在 Python binding 测试中构造 `NativeSpan` 向量，逐字段覆盖 `text/bbox/font/size/order/characters/source_position`，包含缺省 font/size、空字符数组和非 ASCII 文本。
- [ ] 在 Rust 定义 owned `NativeSpanDto` 与 `CharacterDto`，用 PyO3 一次传入 spans、允许区域和排除区域；Rust 不保存 Python 引用。
- [ ] 对同一 JSON fixture 验证 Python DTO adapter 的 round-trip 保留值与列表顺序；对 malformed 类型保持当前 Python 入口的异常/空结果行为。
- [ ] 运行 `cargo test`、`maturin develop --release`、`python -m pytest -q tests/test_pdf_fast_wireless.py tests/test_wireless_output_order.py`。

## Task 2：迁移 span 规范化及 atom/text run

- [ ] 逐函数为 `wireless_structure.span_chain` 与 `text_runs` 中被 `recoverer` 调用的纯函数加精确向量；复用 `tests/test_wireless_structure_span_chain.py` 和 `tests/test_wireless_structure_text_runs.py` 的现有正反例。
- [ ] 明确锁定来源连续性字段、字符 bbox、文本顺序、换行、空格、font witness、currency 分隔以及中文白名单字距行为；包含 `合计/小计` 大字距合并与 `男/女` 不合并反例。
- [ ] 在 Rust 逐函数实现并使用同一测试向量；Python 测试按字段比较 text、bbox、span refs、source position、flow range 和 merge kind。
- [ ] 仅在 Span 到 atom/text run 层合并文本；传入后续 column/grid 的 Atom DTO 不再访问 PDF 页面。

## Task 3：迁移列带、行和逻辑网格

- [ ] 对 `columns.py`、`grid.py`、`logical_grid.py` 的每个被恢复入口调用的纯函数写 failing vectors；保留分栏、稀疏列、paired CJK artifact 和 wrapped field 的当前判定。
- [ ] 迁移 `header_topology.py` 的父叶列拓扑、`merged_cells.py` 的跨度候选与冲突处理、`hybrid_body.py`/`continuations.py` 的输入输出规则；函数之间仅传 typed DTO。
- [ ] 同一槽位的独立叶子字段必须保持独立；不完整的任一 1:2 父标题配对不恢复该层；父标题下已有非空 Cell 时拒绝 rowspan 扩展。
- [ ] 在每次 colspan/rowspan 修改后重新计算 occupancy；冲突时拒绝该跨度，不允许冲突 DTO 进入最终 Cell 列表；空槽单独物化且不得合并相邻空槽。
- [ ] 运行 `tests/test_wireless_structure_columns.py`、`grid.py` 对应测试 `tests/test_wireless_structure_grid.py`、`tests/test_wireless_structure_header_topology.py`、`tests/test_wireless_structure_merges.py` 和 `tests/test_hybrid_body_recovery.py`。

## Task 4：迁移中文 region recoverer 和共享 page recovery

- [ ] 将 `recover_cells_from_region(page, region)` 拆成 Python `collect_native_spans()` adapter 与 Rust 纯恢复入口；保持当前 tuple 返回数量、Cell 顺序和空结果策略。
- [ ] 将 `recover_wireless_tables(page, excluded_regions, allowed_regions)` 的 native-span 采集留在 Python，把 span strip、row clustering、column tracks、candidate runs、table build、overlap selection/quality 的纯规则迁 Rust；Python 继续输出现有 `WirelessRecovery` 外壳、`Table` 对象和 diagnostics。
- [ ] 英文与中文 `extract_text_alignment_candidates` 都调用共享 Rust recovery 入口；保留现有 excluded/allowed region 过滤、legacy callback 选择、异常捕获和 facade monkeypatch surface。
- [ ] 运行 `python -m pytest -q tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_span_chain.py tests/test_wireless_structure_columns.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_recoverer.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_wireless_output_order.py`。

## Task 5：中文/混合路由验证和页面验收

- [ ] 切换中文/共享候选 Rust 路由前，先对索引 `185,1002,1014` 运行 `python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,1002,1014 --output-dir output/pdf_rust_migration_native_wireless_baseline_20260916` 保存 Python JSON/PNG，作为下方 Rust 输出比较基线。
- [ ] 增加 facade 守卫：调用 `zh`/`mixed` `extract()` 与 candidates 时，伪造的 `get_text("words")` 一旦被请求就令测试失败；确认不会调用 zebra 或 legacy callback。
- [ ] 运行 `tests/test_wireless_extractor_split.py`、所有 `tests/test_wireless_structure_*.py`、`tests/test_wireless_table_recovery.py`、`tests/test_unify_wireless_recovery.py`。
- [ ] 用 `python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,1002,1014 --output-dir output/pdf_rust_migration_native_wireless_20260916` 生成新输出；核对 JSON/PNG 中表格数、source、行列、文字、bbox、跨度、空槽位和 occupancy。
- [ ] 与原基线结构化结果逐字段比较；所有差异归类并修复后才切换中文/共享候选的 Rust 路由。结果写入 `changes.md`。

## 验收命令

```powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_span_chain.py tests/test_wireless_structure_columns.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_recoverer.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_wireless_output_order.py tests/test_unify_wireless_recovery.py
git diff --check
```

## 验收合同

每个恢复表的 rows、cols、source、bbox、confidence、Cell 顺序、text、索引、bbox、rowspan、colspan 和空 text 必须与 Python 基线一致。每个逻辑槽位恰好被一个 Cell 占据；页面输出还必须完成 PNG 视觉核验。任何 native span 获取差异都归属 Python extraction adapter，不以 Rust 输出覆盖。
