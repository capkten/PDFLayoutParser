# 英文无线表格逻辑 Rust 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐任务执行并在任务间评审。每步用 `- [ ]` 跟踪。若使用 subagent，model 只能是 `gpt-5.6-luna`。

**目标：** 在共享 native-span 核心验收之后，将英文专属斑马纹、general wireless 与 legacy text-alignment 的纯规则逐函数迁入 Rust，保持 `EnglishTableExtractor` 的公开行为和回退顺序。

**架构：** Python/PyMuPDF 提取 drawing rectangle、背景色、words、blocks、header line 和 bbox，再以 owned DTO 批量传给 Rust。Rust 计算背景带分组、行/列归属、金额/货币处理、标题跨度及 Cell 网格；Python 保留语言路由、候选优先级、异常回退、项目对象适配和输出。

**技术栈：** 已有 `hexai_pdf_parser._pdf_fast`、PyO3、maturin、Rust、pytest、PyMuPDF。

## 全局约束

- 共享 `recover_wireless_tables` 已由上一阶段迁移并通过验收；本计划只改英文专属路径。
- Python 提取 page drawing/words/blocks；Rust 不接收 Page/PyMuPDF 对象、不重读 PDF、不回调 Python。
- `extract_zebra`、`extract_general_wireless`、text alignment 和 legacy callback 的优先级及异常/空结果回退必须与基线一致。
- 精确保持排序、几何、financial token、header row、currency 独立列合并、rowspan/colspan 与 empty-cell 规则；不增业务文字特例或放宽浮点比较。
- `zh`/`mixed` 仍只走 native-span，不可因本计划启用 zebra 或 legacy words 路径。
- 按页/区域批量调用并在 Rust 纯计算阶段释放 GIL；本阶段不跑独立 benchmark。
- 每个纯函数单独按 RED→GREEN→逐字段差分推进；共享入口通过不替代叶子函数输入/输出测试。

## 文件边界

- 修改：`src/hexai_pdf_parser/tables/extractors/english_table_extractor.py`、`src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py`、`src/hexai_pdf_parser/tables/table_extractor.py` 中直接服务 English legacy callback 的 adapter，以及相关测试和 `changes.md`。
- 新增：`rust/english_wireless.rs`、`tests/test_pdf_fast_english_wireless.py`、`tests/fixtures/rust_migration/english/`。
- 不修改 `wireless_structure/` 中文恢复规则、语言检测、ML 检测、通用 header normalizer、JSON/Markdown writer 或服务层。

## 函数迁移清单

| Python 函数/算法 | Rust 对应职责 | Python 保留职责 |
|---|---|---|
| `_detect_row_backgrounds` | 不迁 | `page.get_drawings()` 和 fill/rect 取数，返回背景 DTO |
| `_group_into_tables`、`_is_color_match` | 背景分组与颜色判定 | 将 drawing 色值规范化 |
| `_detect_header_rows`、`_assign_words_to_zebra_rows` | header 带与 word-row 归属 | `get_text("words")` 一次提取并保序 |
| `_process_zebra_group` | 年份标题、data band 与 metric row 判定 | page words DTO 传入、结果适配 |
| `_detect_columns`、`_prune_phantom_columns` | zebra column inference/pruning | 纯数据传递 |
| `_handle_dollar_signs`、`_is_financial_metric`、`_is_pure_amount_dollar` | token/金额分类和列规则 | 不读取 PDF |
| `_promote_grouped_header_cells`、header-underlines 推断 helper | 分组标题及跨度几何 | underline drawing 提取 |
| `_build_wireless_table` | 纯表格/Cell 网格构建 | 输出 DTO 转项目对象 |
| `extract_zebra` | zebra 纯规则批次 | facade 参数、drawing/words 提取、返回 Table |
| `extract_general_wireless`、`extract_cells_from_region` | 纯文字行、列、continuation、rowspan 和空列算法 | 页面文字/线条提取与区域裁剪 |
| `_collect_text_rows`、`_merge_continuation_rows`、`_detect_columns_from_header_lines`、`_build_region_guides`、`_build_text_grid_cells_from_boundaries`、`_infer_sparse_rowspans`、`_prune_empty_columns`、`_assign_words_to_columns` | general/legacy 共享纯算法 | 原始 words/underlines DTO 采集 |
| `EnglishTableExtractor.extract`、`extract_text_alignment_candidates` | 不迁 | 优先级、language guard、exception/fallback 及公开 facade |
| `TableExtractor._extract_legacy_text_alignment` | 只迁其中纯行列规则 | words 提取、callback、region orchestration、monkeypatch surface |

## Task 1：冻结 drawing 与文本输入 DTO

- [ ] 为 `EnglishTableExtractor._detect_row_backgrounds()` 的输出定义纯 DTO：背景 band 的 y0/y1/color；Python 继续调用 `page.get_drawings()` 并按当前规则筛 `rect`/`re`、fill、白色背景和尺寸。
- [ ] 为 words、blocks、underlines、region bbox 定义带有序索引的 owned tuple/struct；adapter 单测逐值验证文字、bbox、索引及输入顺序。
- [ ] 为 `tests/test_pdf_fast_english_wireless.py` 构造背景重叠、背景空输入、白色/彩色交替带、多个分离表格、边界 word 和无效 drawing 数据向量。
- [ ] 跑 `cargo test` 与 `python -m pytest -q tests/test_pdf_fast_english_wireless.py tests/test_page_347_structure.py`，此时生产路由不变。

## Task 2：迁移斑马纹背景分组与表格构造

- [ ] 逐函数迁移 `_group_into_tables`、`_detect_header_rows`、`_assign_words_to_zebra_rows`、`_detect_columns`、currency/header/column prune helper 和 `_build_wireless_table` 中纯规则。
- [ ] 保持 `_process_zebra_group` 当前规则：年标题判定、data band 起始选择、metric 计数、首列/尾列、row merge 与 confidences；`page.get_text("words")` 只在 Python adapter 执行一次并作为 DTO 传入。
- [ ] 复用 `tests/test_page_347_structure.py` 的 `extract_zebra` 覆盖、`tests/test_rule_first_table_detection.py` 的路由顺序用例，并为每个迁移函数加入 Rust 与 pytest 同向量测试。
- [ ] 在页 347 和其他当前 zebra 正例上逐字段比较结果，覆盖 table/cell 顺序、bbox、source、空格、数值及跨度。

## Task 3：迁移 general wireless 与区域文字网格

- [ ] 对 `extract_general_wireless` 调用链中的纯文本/几何函数逐一加向量测试；保留 Python 的 `get_text` 与 drawing 提取和 region clip。
- [ ] 按当前调用链迁移 `_collect_text_rows`、`_merge_continuation_rows`、`_detect_columns_from_header_lines`、`_build_region_guides`、`_build_text_grid_cells_from_boundaries`、`_infer_sparse_rowspans`、`_prune_empty_columns` 与 word-to-column 分配。
- [ ] 保持现有 standalone `$` 与数值列规则、连续行、header line、sparse rowspan、ghost/empty column 和文本拼接输出精确一致。
- [ ] 运行 `tests/test_wireless_table_recovery.py` 中英文结果用例、`tests/test_page_347_structure.py`、`tests/test_rule_first_table_detection.py` 和 `tests/test_table_extractor.py` 相关用例。

## Task 4：迁移 legacy text-alignment callback 并保持 facade

- [ ] 沿 `TableExtractor._extract_legacy_text_alignment()` 调用链逐个识别实际运行的纯 Python 算法；Python 负责 words 取数与当前 callback 选择，Rust 只接数据 DTO。
- [ ] 为 `use_legacy_fallback=True/False`、excluded/allowed regions、空候选、异常回退与 monkeypatch surface 建立 pytest 合同；旧 callback/公开签名继续有效。
- [ ] 将英文调用方逐个切换到 Rust batch API；确认 `EnglishTableExtractor.extract()` 仍按 zebra → general wireless → region fallback 的现有次序返回。
- [ ] 跑 `tests/test_wireless_extractor_split.py`、`tests/test_wireless_output_order.py`、`tests/test_rule_first_table_detection.py`、`tests/test_page_347_structure.py` 与 `tests/test_table_extractor.py`。

## Task 5：英文路径集成验收

- [ ] 切换英文专属 Rust 路由前，先对索引 `347,415,437` 运行 `python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 347,415,437 --output-dir output/pdf_rust_migration_english_wireless_baseline_20260916` 保存 Python JSON/PNG，作为 Rust 输出对照基线。
- [ ] 运行 `cargo test`、完整 English wireless pytest 集与所有已迁移函数向量，比较 `source`、rows/cols、bbox、confidence、cell 顺序/文本/跨度和空单元格。
- [ ] 用 `python test_single.py --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 347,415,437 --output-dir output/pdf_rust_migration_english_wireless_20260916` 输出独立 JSON/PNG；确认 347 英文页面按原优先级恢复、415 图表不被误当表格，并逐字段比较 437 页的 table/cell 输出顺序。
- [ ] 将中文/混合页面请求加入同次 facade 回归，确认仍不请求 words、不走 zebra/legacy。
- [ ] 通过结构化和视觉检查后，才删除已替代的 Python 算法实现并更新 `changes.md`；最后执行全量 `fix` PDF 解析交付总计划规定的目录。

## 验收命令

```powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_english_wireless.py tests/test_page_347_structure.py tests/test_wireless_extractor_split.py tests/test_wireless_output_order.py tests/test_rule_first_table_detection.py tests/test_wireless_table_recovery.py tests/test_table_extractor.py
git diff --check
```

页面 JSON/PNG 必须来自本轮源码和新输出目录；命令里的 437 是 `fix/zh_all_table_pages.pdf` 的页索引。`tests/fixtures/page_437_wireless.pdf` 是独立单页样本，只由相应 pytest 打开，不由这个页索引参数读取。

所有三阶段完成后的全量端测使用新的输出目录：

```powershell
python -c "from hexai_pdf_parser.core.pdf_parser import PDFParser; p=PDFParser(r'D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf'); r=p.parse(output_dir=r'output/pdf_rust_migration_all_full_20260916'); assert r.code == 1, r.message; assert r.data.page_count == 1023"
```
