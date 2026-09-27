# Changes

## 2026-09-27

- **Page 410/419/420 英文表头横线判定收紧**：
  - **根因**：仅按背景带数决定单背景表头压缩仍会把 Page 410 的多级表头吞掉；Page 410 的内部横线由多个绘制片段组成，旧 DTO 只传 Y 坐标，Rust 无法判断其是否为跨表头的完整横线。
  - **修复**：英文网格 DTO 增加水平线长度；Rust 将同一 Y 层的线段合并后，单背景表头只有在表头区域没有跨越 70% 表格宽度的内部横线时才压缩。保留 Page 419/420 的局部线表头压缩，并阻断 Page 410 的完整多级表头误合并。
  - **测试**：新增单背景多级表头横线反例；Rust focused `12 passed`，Python 英文无线测试 `23 passed`。
  - **页面验证**：独立输出 `C:\Users\23662\.codex\worktrees\english-page421-regression\output\check_line_span_fix2_20260927`；Page 410 两表、Page 419、Page 420 三表、Page 421 三表的行列与 Cell 数均恢复一致。Page 419/420 首表只保留此前记录的 Python 表头文本顺序差异。

## 2026-09-27

- **Page 419/420 单背景英文表头回归修复**：
  - **根因**：Page 421 为两段背景表头增加的“列跨度拓扑必须重复”限制被错误应用到单背景表头；Page 419/420 的父表头与子表头列跨度不同，Rust 因而保留了额外的表头物理行，输出 `10x6`，Python 为 `9x6`。
  - **修复**：恢复单无色背景带的既有压缩规则；仅当背景带数为 2 时才要求各表头层拓扑重复，保留两级表头反例保护。
  - **测试**：新增混合列跨度单背景表头 RED fixture；Rust focused `11 passed`，Python 英文无线测试 `23 passed`。
  - **页面验证**：Page 419/420 独立输出位于 `C:\Users\23662\.codex\worktrees\english-page421-regression\output\page419_420_regression_fix_20260927`；两页表格形状与 Cell 数均一致，PNG SHA-256 相同。两页首表剩余文本顺序差异保留为 Python 的源文本归并问题，Rust 按列拓扑生成自然顺序。

## 2026-09-27

- **Page 410 第二张英文无线表 Cell BBox 对齐**：
  - **根因**：表头物理行数（2）多于无色背景行数（1）时，Rust 正文背景索引从 `background_header_rows` 直接起算，重复消费第一个有色背景带，产生 `520.3` 的错误中间边界并让最后一行延伸到表格底部。
  - **修复**：正文背景源行改为按压缩后的逻辑行号加上 `max(background_header_rows - header_rows, 0)` 映射，避免表头行数多于背景行数时重复消费背景带；无背景和普通表头路径保持原规则。
  - **测试**：新增 Rust 行区间回归用例，修复前 `A` 行起点为 `17.0`、修复后为 `22.0`；`cargo test --locked english_wireless` 共 `10 passed`。
  - **页面验证**：输入 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`，Page 410 独立输出位于 `C:\Users\23662\.codex\worktrees\english-page410-bbox\output\page410_bbox_fix_20260927`；两张表逐表 Cell JSON 完全一致，形状为 `7x13/85`、`6x7/39`，整页 PNG SHA-256 相同。

## 2026-09-27

- **Page 421 英文无线多段表头压缩对齐**：
  - **根因**：Python 会按上下单元格列跨度完全相同且无横线阻断的规则合并纵向折行表头；Rust 仅允许单一无色背景组触发该压缩，导致 Page 421 第一张表的 `Three months / ended / 31 Mar 2011 / $m` 被拆成两行，Rust 为 `5x3`，Python 为 `4x3`。
  - **修复**：将无色表头背景组上限从 1 放宽到 2，并保留左侧第 0 列存在标题时的多级表头保护；其他表头拓扑规则不变。
  - **测试**：新增两段逻辑表头背景跨物理折行的 RED fixture；Rust focused `9 passed`，Python 英文无线测试 `22 passed`，`git diff --check` 通过。
  - **页面验证**：输入 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`，Page 421 独立 Python/Rust 输出位于 `C:\Users\23662\.codex\worktrees\english-page421-fix\output\page421_parity_20260927`；三张表逐表 Cell JSON signature 完全一致，形状分别为 `4x3/12`、`5x3/15`、`9x3/27`，整页 PNG SHA-256 相同。

## 2026-09-27

- **Page 410 第二张英文无线表列带对齐**：
  - **根因**：Python `_build_wireless_table()` 已有检测列带，但 `_english_grid_input()` 未序列化这些列带；Rust `build_english_cells()` 因而重新用 words 几何推断列数。Page 410 第二张表被推为 9 列，Python 则为 7 列。
  - **修复**：`EnglishGridInput` 新增可选 `columns` DTO；英文 cell builder 在列带非空时直接使用传入列带，旧调用方缺省时仍执行原推断。Python 无线表路径现把检测列带传给 Rust。
  - **测试**：新增显式列带赋值 RED fixture、DTO roundtrip 和 Python 调用链序列化断言；Rust focused 单测及 Python 英文无线测试验证中。
  - **页面验证**：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf` 页索引 409、410，独立 Python/Rust 输出位于 worktree `output/page409_410_python_columns_fix` 与 `output/page409_410_rust_columns_fix`。Page 409 的 `7x9/59` Cell JSON 和 PNG SHA-256 完全一致；Page 410 两表数量、来源一致，第一表为 `7x13/85` 且 Cell JSON 完全相同；第二表从 Rust 旧 `7x9/56` 对齐为 `6x7/39`，非空内容、行列位置及跨度一致，列边界为 `58.9, 215, 263, 318.5, 380, 440, 505.3, 549.5`。两种模式 PNG 已目视检查；第二表剩余差异是部分纵向 Cell bbox 切分点。
  - **验证命令**：`cargo test --locked --lib english_wireless`（9 passed）、`pytest tests/test_pdf_fast_english_wireless.py -q`（19 passed）、`git diff --check` 通过。

## 2026-09-27

- **Page 337 英文无线表格 Rust 行契约对齐**：
  - **根因**：Python `EnglishTableExtractor._build_wireless_table()` 已将同一数据行内的垂直折行文字封装在同一个 `_RowData`/背景带中；Rust `rust/english_wireless.rs::build_english_cells()` 原先直接以 `cluster_word_rows(..., 4.0)` 按词中心聚类，忽略传入的数据背景带，Page 337 的 10 个逻辑行被拆成 16 行。
  - **修复**：新增 `cluster_english_rows()`，仅对 `color.is_some()` 的数据背景带按其几何范围归属文字并形成逻辑行；无色表头仍走原有 4pt 聚类和表头压缩，避免改变既有多级表头语义。未落入背景带的词保留旧聚类兜底。
  - **约束**：仅修改 Rust 英文无线行聚类和对应最小回归测试，不回读 `page.get_text("words")`，不修改 Python 路径。
  - **验证**：新增 `test_build_english_cells_uses_supplied_logical_background_rows_for_wrapped_text`，修复前 RED、修复后 GREEN；Rust 表头压缩 focused unit GREEN。Page 337 独立 Python/Rust 重跑后 tables JSON 结构与 Cell signature 完全一致：`english_general_wireless`、`10x4`、`36 cells`、bbox `[44.3,206.0,549.7,458.4]`；Rust 输出目录 `D:\codes\PDFLayoutParser\output\english_337_340_rust_fix_20260927`，JSON `pages/page-337.json`、可视化 `tables/page-337.png`。

- **Page 340/408 英文无线表头压缩对齐**：
  - **根因**：Rust `merge_wrapped_header_rows()` 只按列位置跨行合并，未区分相邻无色表头背景带；Page 340 的单行正文 `All paragraphs...` 被错误并入第一层表头，Page 408 的重复 `Products` 标签在清空子 Cell 后又被占用检查阻止正确 `rowspan`。
  - **修复**：为表头压缩传入背景行组，仅在同一逻辑背景组内合并；相同上下文标签不重复拼接；占用检查忽略已清空的子 Cell，保留有效文本对跨度的阻断。
  - **验证**：新增 Page 340/408 最小 RED fixtures；修复后 Python English focused `16 passed`、Rust `cargo test --locked --lib english_wireless` `9 passed`。独立 Rust 输出 `D:\codes\PDFLayoutParser\output\english_340_408_rust_fix_final3_20260927` 与 Python baseline 逐表 Cell signature 一致：Page 340 `16x5/79`、Page 408 `8x5/37`；bbox 分别 `[44.2,123.0,549.9,400.4]`、`[59.1,543.7,553.0,651.6]`。
- **Page 407 英文无线列边界对齐**：
  - **根因**：Rust 列推断在没有显式数据行背景证据时，仍遍历全部 `input.words` 使用含数字的 `$1.15` 等词吸附列边界；Python `data_rows=None` 路径不执行该金额锚点。Page 407 第一列因此从 Python 的 `299.77` 被推到 `354.78`。
  - **修复**：Rust 金额边界吸附仅消费独立 `$` token，保留显式货币列测试，同时跳过 `$1.15` 等已组合金额词，基础列检测和 Python 路径不变。
  - **验证**：新增无数据行背景的组合金额 RED fixture，修复后 GREEN；Python English focused `17 passed`、Rust English unit `9 passed`。Page 337/340/407/408 Rust 与 Python Cell signature 全部一致；Page 407 为 `english_general_wireless`、`23x4`、`92 cells`、bbox `[60.9,312.0,550.3,745.9]`。输出目录：`D:\codes\PDFLayoutParser\output\english_337_340_407_408_rust_final_20260927`。
- **Page 419/420 英文无线逻辑表头压缩对齐**：
  - **根因**：两页候选输入均只有一个无色表头背景带（H=1、D=8）；Rust 依据词中心拆出多个内部 header rows，`Cash/Group` 被错误扩成 `rowspan=2`，中间业务表头留在下一行，首个正文行整体下移。
  - **修复**：当仅有一个表头背景带且无左侧 stub 时，将内部表头行按列合并为一个逻辑 header row，随后重映射 body row/bounds；多表头背景页（如 Page418）保持原流程。
  - **验证**：新增最小 H=1 多行表头 RED fixture；Python English focused `18 passed`，Rust English unit `9 passed`。Page419/420 table1 Rust/Python Cell signature 一致：`9x6/52`；Page418 `38x8/298`，Page420 其他两表 `7x3/21`、`8x3/24` 未回归。输出：`D:\codes\PDFLayoutParser\output\english_419_420_rust_fix4_20260927`。
- **Page 421 英文无线百分号间距对齐**：
  - **根因**：Rust Cell phrase 组装无条件执行 `.replace("% ", "%")`，删除 `16.5%` 与后续 `(2010:` 之间的合法空格。
  - **修复**：移除百分号后的无条件空格清理；保留美元符号清理和其余拼接规则。Page411 文本归并差异仅记录，不在本次修改。
  - **验证**：新增百分号间距 RED fixture，修复后 Python English focused `19 passed`、Rust English unit `9 passed`；Page421 三表 Cell signature 与 Python 完全一致。
- **Page 482 Rust 中文无线表格竖排单字链 parity 修复**：
  - 根因：第 13 列 `减值准备期末余额` 的 8 个 native atom 同属 block=9、source line=0..7 且 flow 连续；Rust 单字 CJK 续行保护使其停留为 8 个物理行，Python 则合并为一个表头 Cell，最终 Rust 产出 10x13 而 Python 为 5x13。
  - 修复：仅对 row=0 起始、同列同几何、同 source block 且连续 source line/flow 的证据完整 CJK 竖排链一次性合并；逻辑 row-start 与表头拓扑随后保留叶子行和正文边界，避免中间两两合并造成 occupancy conflict。其他路径不回读 words、不改 Python。
  - 验证：Rust chain fixture 与 wireless_structure 45 项测试通过；Page 482 Rust/Python cell signature 完全一致（5x13、27 cells、bbox `[83.2,124.8,540.5,416.3]`、0 diagnostics）。独立输出目录：`D:\codes\PDFLayoutParser\output\page_482_rust_chain_fix_20260927`，JSON `pages/page-482.json`，可视化 `zh_all_table_pages_page_482_visualized.png`。

- **Page 978 Rust 表头拓扑 parity 修复**：
  - Rust `header_body_start()` 原先在未找到 numeric body 行时，直接把首个“非空 Cell 数达到 3/4 列”的物理行当作 body 起点；Page 978 的第二层表头正好满足该条件，导致 `header_rows=1`，表头 `rowspan/colspan` 无法恢复并物化大量空槽。
  - 修复前置拓扑下界：存在跨列父表头且后续有完整连续叶子列时，body 起点不得早于叶子表头行之后。
  - Page 978 四张表 Rust/Python JSON 逐表一致：`(5,4,19)`、`(7,5,27)`、`(4,8,27)`、`(7,7,32)`；Rust 单元测试 `44 passed`。
  - Page 482 尚未修改，继续单独调查。

- **Page 585/586/588 Rust 财务表格行合并 parity 修复**：
  - Rust 垂直合并使用 native `run_refs` 与 aligned atom evidence 对齐，修正 filtered flow 索引错配；region transition 的 `row_interleaved` 财务行合并间距收紧为 Python 合同的 `6pt`，无 evidence 的 legacy full-page candidate 保持原 `10pt`。
  - Rust 后置 continuation 合并复用 source block 约束，避免跨来源块的财务项目误并。
  - Page 585、586、588 的 Rust/Python 表格 JSON 形状和非空 Cell 数完全一致：`36x5/180`、`45x5/225`、`39x5/195`，occupancy diagnostics 为 0。
  - Page 589 保留为 Python 错误记录：Python `_NUMBERED_ITEM_START` 未识别全角点号 `U+FF0E`（如 `1．`），把编号清单错误合并成一个大 Cell；Rust 保留 25 行结构更符合原始页面，未修改 Python。

- **Rust `row_interleaved` 表头换行模式对齐 Python（Page 941 组）**：
  - **根因**：Python 在 `row_interleaved` 模式下只要求 native flow 连续；Rust native-region DTO 未传递 `output_mode`，`merge_source_contiguous_vertical_cells()` 无条件使用 `source_block/source_line` 连续约束。Page 941 等页面的表头片段 flow `7/8/9` 跨 block `8/8/9`，Rust 拒绝第三段并物化为额外逻辑行。
  - **修复**：`NativeRegionInput` 增加并校验 `output_mode`，Python 构造 Rust DTO 时传递 `row_interleaved/columnar`；Rust 仅在 `columnar` 模式启用 source block/line gate，旧 DTO 缺省保持 `columnar`。
  - **页面验收**：`941、942、943、944、1018、1019、1020` 共 7 页的结构化表格 JSON 全部与 Python 一致，标注 PNG SHA-256 逐页一致；对应输出见 `tmp/page941_group_compare_after.json`。
  - **测试**：Rust `cargo test --locked --lib` 为 `72 passed`；相关 Python native-region/wireless merge/grid 测试为 `84 passed`，差分测试排除两个既有 fixture 分类失败后为 `8 passed`；新增 DTO `output_mode` roundtrip 回归通过。

## 2026-09-26

- **Page 36/37 Rust wired-table 文本归属对齐 Python**：
  - **根因**：`rust/wired.rs::assign_text_to_line_cells()` 使用传入的几何 `line_tolerance=2.3` 处理文本行归属；Python `_assign_text_to_line_cells_python()` 固定使用 `2.0pt`。两页各有一个 word 的中心点距离上方 Cell 下边约 `2.04pt`，Rust 因 `2.3pt` 错分到上一行，造成 4 个 Cell 文本差异。
  - **修复**：Rust 文本归属的上下/左右匹配统一使用固定 `2.0pt` 文本容差，几何网格仍使用原有 `2.3pt` 容差。
  - **验证**：新增边界回归 `tests/test_pdf_fast_wired.py::test_assign_text_to_line_cells_matches_python_row_boundary_tolerance`；修复前 RED，修复后 `tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py` 为 `91 passed`，`cargo test --locked --lib` 为 `72 passed`。Page 36/37 独立 Python/Rust 重跑后，整张 `tables` JSON 完全一致。
  - **输出**：`tmp/page36_37_python_after/`、`tmp/page36_37_rust_after/`。

## 2026-09-25

- **Rust 中文无线表格漏检修复与占位冲突根治（18 个漏检页清零与 1023 页全量验收通过）**：
  - **根因分析**：
    1. **`grouped_mixed_leaf_header_span` 几何判定偏差（涉及 Page 467、468、469 等 16 页）**：Rust 端无线结构推断中原实现单行高误判以及 `start.saturating_sub(1)` 向上误并，与 Python `logical_grid.py` 要求叶子单元必须是多行（`rowspan > 1`）不一致，导致父标题与单行叶子标题错误合并并跨行，引发严重的网格占用冲突（OccupancyConflict），根据中文无线表格硬性约束整个表格被安全防护机制丢弃；
    2. **候选前置门控阻断 ML 检测（涉及 Page 440、923）**：`src/hexai_pdf_parser/tables/table_extractor.py:741-760` 中，当无规则几何候选时直接提前返回 `[]`，即使开启了 ML 模型（`use_model=True`），YOLO 模型检测也无法触发，导致区域恢复没有机会执行；
    3. **`merge_source_contiguous_vertical_cells` 贪婪垂直合并（涉及 Page 590、591 等财务报表）**：Rust 侧垂直合并缺少序号项及财务科目缩进识别，将带“一、”、“二、”、“（一）”、“1．”、“加：”、“减：”等编号与列表项连续向上贪婪合并，整列 27 行被合并为一个跨度高达 27 的巨无霸 Cell，引发整表格行塌缩并产生大量槽位重叠冲突而整表丢弃；
    4. **同物理槽位换行折行碎片未合并（涉及 Page 932、935、936、959、960 等）**：中文文本换行/首行悬挂折行时落在同一个 `(row, col)` 槽位内，但第二行水平坐标靠左（换行顶格为负间距），原有 `merge_physical_inline_fragments` 仅合并水平同一视觉行的正向间隙碎片，导致槽位中遗留两个重复的 `PhysicalCell`，直接触发硬性 OccupancyConflict 丢弃整表。
  - **核心设计与修复实现**：
    1. **`rust/wireless_structure.rs`::`grouped_mixed_leaf_header_span`**：严格对齐约束 `candidate.rowspan > 1`，删除单行高误判及 `start.saturating_sub(1)` 向上误并逻辑；
    2. **`src/hexai_pdf_parser/tables/table_extractor.py`**：当 `candidates` 为空时，若 `self.use_model and self.model_detector is not None`，继续调用 `_extract_model_tables`，解除规则候选为空对 ML 检测的硬阻断；
    3. **`rust/wireless_structure.rs` 防贪婪跨行合并**：新增 `is_numbered_item_start` 和 `is_list_continuation`，在 `merge_source_contiguous_vertical_cells` 中拦截序号项、列表前缀及财务行（“一、”、“（一）”、“1.”、“加：”、“减：”等），杜绝财务报表科目被误并；
    4. **`rust/wireless_structure.rs` 同物理槽位折行碎片合并**：在 `merge_physical_inline_fragments` 中，对同一 `(row, col)` 物理槽位内来源连续且非编号项的上下折行碎片，合并其 bbox 并用 `\n` 连接文本，消除物理网格内部重复同槽 Cell 引发的占用冲突。
  - **不回读 words 约束与安全防护**：
    - 严格遵循中文无线表格结构恢复规范，只消费 native span、atom、列带和物理/逻辑 Cell，**严禁回读 `page.get_text("words")`**；
    - **绝不放宽 OccupancyConflict 冲突保护**：保留所有占用冲突检测与安全校验，所有槽位严格保持一槽一格或精确跨度覆盖。
  - **测试与全量验收结果**：
    - **Rust 与 Python 单元测试**：Rust 36 个测试全绿（`cargo test --lib wireless_structure`）；新增 `tests/test_rust_missing_pages.py`、`tests/test_rust_chinese_wireless_parity.py`、`tests/test_table_extractor.py`，全部测试 PASS；
    - **18 个漏检页专项复核**：`440, 454, 462, 467, 468, 469, 590, 591, 923, 927, 932, 935, 936, 959, 960, 986, 1014, 1017` 全部 100% 成功出表，漏检数清零，0 占位冲突；
    - **全量 1023 页端到端验收**：
      - 输出路径：`D:\codes\PDFLayoutParser-Fast\output\pdf\zh_all_table_pages_rust_missing_fix_20260925_72dpi_final`；
      - 验收指标：`pages_json = 1023`, `table_png = 1023`, `occupancy_conflicts = 0`, `table_count = 2195`。

- **Parity follow-up（隔离分支验证）**：按 Python `atoms -> bands -> physical cells -> logical cells` 逐阶段对照，继续修复 `wrapped_leaf_header_span` 单行高度误判、`row_hint` 绕过列跨度判定、显式单列物理 Cell 被 bbox 扩展、同槽位 inline marker 合并和 interleaved source 垂直合并。18 个目标漏检页均恢复；Rust 全量复跑输出 `output/pdf/zh_all_table_pages_rust_parity_followup_20260925_72dpi` 为 1023 页、933 个有表页、2201 张表、最终 Cell 槽位冲突 0。与 Python baseline 仍有 69 页结构差异，Page 191 和 982 各多出 1 张候选表；Python 默认路由保持不变。

## 2026-09-24

- **表格候选逻辑下沉至 Rust 优化 (Rawdict 快速路径)**：
  - **根因分析**：端到端单页表格提取总耗时约 1.5s，其中纯 YOLO ONNX 模型推理仅需约 0.28s，其余 >1.0s 的开销完全集中在 Python 侧 `capture_page_snapshot`（数十万次递归字典包装、`_freeze` 冻结与 SHA256 签名计算）。而 PyMuPDF C 层的 `page.get_text("rawdict")` 耗时仅约 4ms，Rust 端无线结构推断纯计算耗时仅约 5ms。
  - **核心设计与实现**：
    1. 在 `rust/snapshot.rs` 实现 `collect_native_spans_from_rawdict`，直接遍历 PyMuPDF 的 `rawdict` C-Python 底层字典结构，就地生成 `Vec<NativeSpanInputDto>`，保留原有的页脚页码检测（`is_footer_page_number`）与空间区域过滤，完全绕过 `PageSnapshot`；
    2. 在 `rust/lib.rs` 暴露 `collect_native_spans_from_rawdict` 与 `recover_wireless_tables_from_rawdict` 两个 PyO3 绑定，直接在 Rust 内存中打通 `rawdict -> spans -> recover_wireless_tables` 直通链路；
    3. 在 `src/hexai_pdf_parser/rust_adapter.py` 提供强类型适配接口；在 `src/hexai_pdf_parser/tables/wireless_table_recovery.py::recover_wireless_tables` 中接入极速通道：当 `PDF_RUST_MODE='rust'` 且传入原生 `fitz.Page` 时，直接走 Rust rawdict 快速路径恢复无线表格。若发生异常安全回退到原有 snapshot 路径，传入 snapshot 时保持原有行为不变。
  - **不回读 words 约束**：严格遵循中文无线表格结构恢复规范，只消费 PyMuPDF 原生 `rawdict` 中的 spans 与字符，严禁回读 `page.get_text("words")`，严格保持 native-span、atom、列带和 Cell 的结构恢复不变量。
  - **测试与性能对比**：
    - 新增 `tests/test_rust_rawdict_candidate.py` 覆盖 4 项专属单元测试（span 提取 100% 一致性、恢复表格结构 100% 一致性、page 快速通道、异常安全回退）；
    - 全套测试：64 项 Rust 单元测试全部通过，99 项核心 Python 测试全绿；
    - 性能实测：在 `zh_all_table_pages.pdf` 第 0 页上，表格提取阶段（`table_extract`）耗时从 **1.488s 骤降至 0.332s**（包含 0.28s 模型推理），整页候选检测纯计算耗时从 1000+ ms 降至 20ms 以内，单页端到端总解析时间压缩至 **0.531s**。

## 2026-09-23

- Task 5 bounded Rust parity repair：修正 NativeRegion band ID 到零基列位置映射，保留 `column_id` 原证据；Rust native table recovery 使用保留 separator 的 text-run helper，避免把 Python 候选分隔行过滤掉。页面候选分组按 Python 规则拆开未标注单字段行，并补回相邻短标题；Rust vertical continuation 拒绝以冒号结尾的字段，匹配 Python 字段标签语义。页面候选 confidence 从固定 `0.90` 改为按 Python 的多列行支持数与活动列数计算。
- Python/Rust bridge 对“没有稳定列带、无 native region 输入”的情况直接返回 Python oracle 同样的空网格，不再把 `None` 误报成 Rust 输出类型错误。添加 RED/GREEN 路由与候选 confidence 回归；迁移 focused pytest `186 passed`，最终源码 `cargo test --lib` `62 passed`，`git diff --check` 通过。
- 五页验收输出：`D:\codes\PDFLayoutParser\output\rust_migration_task5_confidence_20260923_r10\`，输入 PDF SHA256 `376162411d0d5b75ad2a4dc2d5249b8531d20fa81e26af792c04b76d6fc85a89`。结构 mismatch `0`、routing diagnostics `12`；Python/Rust 表格数在 184/188/189/191/192 页分别为 `2/2/2/2/4`，五页 overlay PNG 哈希逐页相同。此结构相等依赖 occupancy fallback，不能记作 Rust 独立 page parity；Rust primary 仍关闭。页面基线 49 个 Python occupancy conflict 保留为明确未决合同。
- 一次按同 row/column 无条件聚合的试验导致 `1475` 条结构 mismatch，已撤回，未留在最终代码；该结果说明还需先对齐 Python `_column_tracks()`、cell assignment、span 和 bbox 语义，不能只合并重复槽位。
- 页面候选路径新增 Python `_column_tracks()` 锚点规则：数字按右沿、标签按左沿分配到重复列轨迹；只对带完整 `row_hint` 且轨迹数与推断列带数一致的候选重映射，避免改变区域入口或不匹配的网格。宽标签跨入数值列 bbox 的 synthetic differential 按 Rust fallback diagnostic 从 RED 到 GREEN；focused pytest `187 passed`，`cargo test --lib` `62 passed`，release 扩展构建成功。
- 新五页输出为 `D:\codes\PDFLayoutParser\output\rust_migration_task5_left_anchor_20260923_r11\`，PDF SHA256 不变。summary 仍为结构 mismatch `0`、routing diagnostics `12`；table count 仍为 `2/2/2/2/4`，五页 Rust/Python PNG 哈希一致且与 r10 相同。Rust 页面及 188 页区域入口仍发生 occupancy fallback，因此该 slice 没有完成真实页 Rust 独立 parity，也没有证明提速；Python 默认路由保持不变。

## 2026-09-22

- Task 4D logical row/header-span transaction：以 native continuation 的拥有关系压缩物理行；只有同层父标题与下一层连续叶子列形成完整、无重叠 `1:2` 配对时恢复 `colspan=2`，不完整层整层回退为 `colspan=1`。`rowspan` 在逻辑网格生成后才推断，覆盖槽位出现非空标题时拒绝扩展；跨度 proposal 在 clone 上重建 occupancy，冲突或越界时回滚。
- 所有未被既有 rowspan/colspan 覆盖的逻辑槽位现在各自物化为独立 `text=""`、`1x1` Cell，并执行最终 exact occupancy 检查；恢复入口保留 out-of-bounds diagnostic。实现只消费 native span、atom、列带和 Cell，不回读 `page.get_text("words")`，不调用 `extract_zebra()` 或 legacy `_rebuild_text_aligned_table()`。
- Task 4D 回归：fresh binding 下 differential/grid/header/recoverer focused pytest `102 passed`，`cargo test --lib wireless_structure` `31 passed`；默认 Python route、shadow/fallback policy 和页面级 JSON/PNG 验收保持不变。仓库级 `cargo fmt -- --check` 仍受既有跨文件格式差异影响，未做全仓格式化。
- Task 4C physical grid/occupancy bounded slice：修复 Rust 行聚类先于 continuation 判定拒绝左移 CJK 换行字段的问题；严格要求 source refs 连续、向下移动、CJK-only、左移、右边界接近前一字段左边界且前字段足够宽。修正 continuation predicate 的 veto 逻辑，避免拒绝条件被误当成允许条件。
- 物理片段合并后从完整 Cell 集合重新计算 occupancy，避免合法的 source-contiguous same-slot inline fragment 保留过期 `occupancy_conflict`；独立字段冲突仍显式诊断。物理 Cell 负索引或超出推断网格时输出 `occupancy_out_of_bounds`，不再静默丢弃。有效 `col_hint` 优先于宽 bbox 的列推断。
- 新增 Rust 物理网格正例和拒绝误合并/冲突/空槽覆盖回归；`cargo test --lib wireless_structure` 为 `27 passed`，无线结构 differential/grid/recoverer focused pytest 为 `49 passed`，`git diff --check` 通过。结构恢复仍只消费 owned atom、列带和 region，不回读 `page.get_text("words")`；默认 Python route 和页面级 JSON/PNG 验收保持不变。

## 2026-09-21

- Task 3B differential ledger minor fix：为每条 mismatch 增加显式 `reason`，并为 `empty_whitespace_and_separator` 的两条 `flow/order` 记录固定 `requires_adaptation` 分类和分层根因。`text_runs/S2` 是 Rust 未透传 separator survivor 的 flow metadata，`atoms/S2` 是 Rust 使用过滤后的 local flow/order `1` 而 Python 保留 source order `2`；两者 source bounds 均为 `2`，不再笼统记为一条差异。重新计算 ledger：total `111`，fixture/field/classification counts 不变，SHA256 为 `cb51b9e240ec69b88f9b00066c2293f076b31ffb3973bac7996eb663f0a71f81`。

- Task 3B atom metadata review fixer：修复 `review-7fb8ea0..d7a195b.diff` 指出的两个 Important。根因一是 `rust/native_span.rs::build_atoms()` 仍把公开视觉 `TextRunDto.order` 复制为 atom order，现改为 `flow_start` 存在时优先使用，legacy run 无 flow 时回退 `run.order`；`run_refs` 继续直接来自 `run.span_refs`。二是 `rust/lib.rs::build_atoms_binding()` 原先独立输出 flow 和 source evidence，导致 legacy evidence-only run 产生 partial atom metadata；现仅当 `flow_start`、`flow_end` 和非空 `source_positions` 同时存在时一次性输出完整 flow/source bundle，否则保持 core legacy atom shape。`tests/test_rust_native_span_differential.py` 的 Rust atom normalizer 现在比较真实 atom order、flow 区间、run source bounds 和 source continuity metadata，不再将这些字段 broad ignore。
  - **TDD 与回归**：先加 packed fragment、filtered-gap/wrapped atom order、evidence-only/no-flow shape 和 normalizer 字段断言；RED focused 为 `3 failed, 2 passed, 20 deselected`，normalizer 单测另为 `1 failed, 24 deselected`。`maturin develop --release` 成功后 focused GREEN 为 `6 passed, 19 deselected`，完整 differential 为 `25 passed`。
  - **Differential ledger**：total `111`；fixture counts `alignment_corridor_veto=40`、`cjk_non_whitelist_spacing=10`、`cjk_whitelist_spacing=5`、`empty_whitespace_and_separator=6`、`independent_fields_counterexample=10`、`packed_numeric_split=10`、`single_field_control=5`、`source_block_line_noncontinuous=10`、`superscript_inline_gap=5`、`vertical_wrapped_witness=10`；field counts `flow/order=23`、`font/script=22`、`source continuity=22`、`span/run refs=44`；classification counts `defect=8`、`requires_adaptation=15`、`unsupported=88`；SHA256 `b2042666a63fa728b7199380708738cddffa21642995e36c93d65f5168f0b052`。旧 semantic fixture 断言保留；未读取 `fitz.Page`/`page.get_text("words")`，未修改用户 dirty 测试文件、`rust/wireless_structure.rs` 或 column/grid/header/route。
  - **遗留语义**：legacy TextRunDto 无 flow 时仍以 `run.order` 作为 atom order；evidence-only/no-flow 不附加任何新 atom metadata；`source_start/source_end`、旧 evidence 和无 evidence DTO shape 保持不变。未执行页面级 PDF JSON/PNG 重跑，未发现本 bounded slice 的额外页面验收输入。

- Task 3B atom metadata bounded slice：根因是 `build_atoms()` 将视觉 `TextRunDto.order` 错当作 `run_refs`，而 `WrappedRun` 内部已有的 native flow 区间在返回 `TextRunDto` 时丢失；owned text-run evidence 也没有到达 atom 边界。现在 `rust/native_span.rs::build_atoms()` 直接使用 `run.span_refs`，普通 run、packed numeric fragment 和 wrapped chain 透传可选 `flow_start/flow_end`；`rust/lib.rs::build_atoms_binding()` 从同一 run 的 evidence 附加 `source_blocks`、`source_line_start`、`source_line_end`、`source_position_known`。`TextRunDto.order/source_start/source_end` 语义不变，核心 `AtomDto` 不扩展，legacy 无 evidence DTO shape 不变；未读取 `fitz.Page`/`page.get_text("words")`，未修改 wireless structure、column/grid/header/route。RED focused 为 `3 failed, 1 passed, 20 deselected`；GREEN focused 为 `4 passed, 20 deselected`；完整 differential 为 `24 passed`，evidence 为 `9 passed`，text-runs 为 `45 passed`，`cargo test --lib native_span` 为 `4 passed`，`git diff --check` 通过。ledger total `154`；fixture counts `alignment_corridor_veto=56`、`cjk_non_whitelist_spacing=14`、`cjk_whitelist_spacing=7`、`empty_whitespace_and_separator=7`、`independent_fields_counterexample=14`、`packed_numeric_split=14`、`single_field_control=7`、`source_block_line_noncontinuous=14`、`superscript_inline_gap=7`、`vertical_wrapped_witness=14`；field counts `flow/order=44`、`font/script=22`、`source continuity=44`、`span/run refs=44`；classification counts `defect=16`、`requires_adaptation=28`、`unsupported=110`；新 SHA256 `b3fdf184452653d59047dacbc57150bef6bdb0e17498043dce35016e132e54e0`。限制：可选 atom metadata 在 standalone `build_atoms` binding 暴露；core `AtomDto` 及其他未要求的 recovery/structure contract 保持原样，未做页面级 PDF/PNG 重跑。

- Task 3B alignment corridor veto bounded slice：根因是 Rust native span 行内分组只执行既有 `can_join`，未迁移 Python `text_runs.py` 的 alignment corridor veto，导致有三组以上稳定左右对齐列带且中间 corridor 足够宽时把相邻字段拼成一个 run。现在在 `rust/native_span.rs::build_text_runs()` 中仅对 `can_join` 为真的候选，使用 owned `PreparedSpan`/alignment DTO 复现 `_alignment_anchor`、`_alignment_tolerance`、`_alignment_modes`、`_opposite_edges_vary`、`_has_diverse_text_values` 和 `_has_alignment_corridor_veto` 的顺序与条件；跳过当前 group/candidate flow，未回读 `fitz.Page`/`page.get_text("words")`，未触及 wrapped merge、`build_atoms` 后逻辑或 route。新增 8 字段正例及两行 support 控制，alignment semantic defect 清零。RED 为 `1 failed, 19 deselected`；fresh binding 后 focused 为 `1 passed, 19 deselected`，differential 为 `20 passed`，组合回归为 `85 passed`，`cargo test --lib native_span` 为 `4 passed`，`git diff --check` 通过。ledger 真实结果为 total `154`，fixture counts `alignment_corridor_veto=56`、`cjk_non_whitelist_spacing=14`、`cjk_whitelist_spacing=7`、`empty_whitespace_and_separator=7`、`independent_fields_counterexample=14`、`packed_numeric_split=14`、`single_field_control=7`、`source_block_line_noncontinuous=14`、`superscript_inline_gap=7`、`vertical_wrapped_witness=14`；field counts `flow/order=44`、`font/script=22`、`source continuity=44`、`span/run refs=44`；classification counts `defect=16`、`requires_adaptation=28`、`unsupported=110`；SHA256 `e1b9c0a1196e7c8ad21b84f40f15ef2e61ee792e4023a447dfa2dbfb9bb19e9f`。

- Task 3B wrapped merge review fix（第一轮历史）：当时曾将过滤后连续序列用于 wrapped helper，并记录 filtered-source-gap 回归、反例 Python/Rust 文本结构等价断言和 `84 passed`；其旧 ledger SHA256 `2d139ae83aba7551db0d29a34d19225cee689dfd950fa3456122d8a0056ace76` 已被第二轮 local flow ordinal 结果取代。公开 `TextRunDto.order` 不重编号的最终合同见下方第二轮记录。

- Task 3B wrapped merge 第二轮 bounded fix：第一轮把视觉构造顺序的公开 `TextRunDto.order` 临时承担了 Python flow，导致右侧字段插入左侧多行链并使 `vertical_wrapped_witness` 失败。现在在 `build_text_runs()` 完成 region 过滤和 packed split 后，按原始 source order 与 fragment order 建立仅供 wrapped helper 使用的连续 local flow ordinal，并通过内部 `WrappedRun` 传递；wrapped 排序、相邻 pair 连续性、witness-after 与 chain membership 均只消费该 ordinal，公开 `order` 和 `source_start/source_end` 语义保持不变。未回读 `fitz.Page`/`page.get_text("words")`，未修改 Python route、alignment corridor 或后续 atom/column/grid/header/Cell 逻辑。新增断言锁定公开视觉 order；RED 为 `4 failed, 1 passed, 14 deselected`，当前 focused GREEN 为 `5 passed, 14 deselected`，`cargo check --lib` 通过。

- Task 3B wrapped merge bounded slice：补齐 Rust `build_text_runs()` 的 wrapped field 合并语义。根因是 Rust 在完成同一视觉行 run 后直接返回，未执行 Python oracle 的 `_merge_wrapped_field_runs()`；现在仅在返回前按 native flow 连续、数字/占位符 veto、字体粗细与字号兼容、下方几何、横向重叠和右侧 multiline witness 判定，并保留 strong native vertical pair fallback。链式合并逐个相邻 pair 检查，合并文本、bbox、span refs、source bounds 和完整 evidence；不回读 `fitz.Page`/`page.get_text("words")`，不修改 Python 生产路径、route、alignment corridor、`build_atoms` 后逻辑或用户 dirty 文件。differential ledger 更新为 `364` 条，SHA256 为 `8358c75e03dc5e12086127a75cc9b4ed94e7d829ea63ccefc0f06ac09d701fcc`；最终 differential `18 passed`、wrapped focused `4 passed`、`cargo test --lib native_span` 为 `4 passed`、`git diff --check` 通过。

- Task 3B wrapped merge 第二轮最终收尾：`maturin develop --release` 成功并安装 fresh `hexai_pdf_parser-1.1.1`；组合回归 `tests/test_rust_native_span_differential.py tests/test_wireless_structure_text_runs.py tests/test_rust_native_span_packed_numeric.py` 为 `84 passed in 1.96s`。ledger 真实结果为 total `364`，fixture counts `alignment_corridor_veto=266`、`cjk_non_whitelist_spacing=14`、`cjk_whitelist_spacing=7`、`empty_whitespace_and_separator=7`、`independent_fields_counterexample=14`、`packed_numeric_split=14`、`single_field_control=7`、`source_block_line_noncontinuous=14`、`superscript_inline_gap=7`、`vertical_wrapped_witness=14`；field counts `presence=26`、`bbox=24`、`errors=24`、`flow/order=52`、`font/script=38`、`grouping=24`、`ordering=24`、`source continuity=52`、`span/run refs=52`、`text=24`、`value=24`；classification counts `defect=218`、`unsupported=118`、`requires_adaptation=28`；SHA256 `8358c75e03dc5e12086127a75cc9b4ed94e7d829ea63ccefc0f06ac09d701fcc`。`cargo test --lib native_span` 为 `4 passed; 0 failed`，`git diff --check` 无输出、退出码 `0`。仅提交四个 slice 文件，两个用户 dirty 文件保留未提交。

- Task 3B bounded slice：迁移 Rust native span 的 superscript inline gap 合并规则。
  - **根因与调用位置**：`rust/native_span.rs` 的 `build_text_runs()` 仅按同一 native line 的普通字距、CJK 白名单字距和连续 source fragment 规则合并；小字号 superscript 即使位于前一 span 的右侧走廊内，也因 source line 不同而被拆成两个 run。
  - **判定条件**：在现有 source-fragment、`$` 和垂直中心 veto 之后，严格使用 `candidate.size < previous.size * 0.82`，以及 `previous.x1 - previous.size * 0.9 <= candidate.x0 <= previous.x1 + previous.size * 0.45`；不放宽普通 gap、不增大 CJK gap、不添加业务文字特判。packed numeric fragment veto、span refs、source bounds、bbox 和 evidence 保持不变。
  - **测试与验证**：新增真实 Python/Rust helper 的 `基2` 正例、字号阈值反例和 x 走廊反例；RED 为 `1 failed, 1 passed, 11 deselected`，GREEN focused 为 `2 passed, 11 deselected`。differential/text-runs 回归为 `58 passed`，packed numeric 专项、`cargo test --lib native_span` 和 `git diff --check` 均通过。
  - **限制**：本 bounded slice 只覆盖 synthetic native-span/text-run 语义，未修改 Python 生产路由、column/grid/header、wrapped merge、alignment corridor、`build_atoms` 或 Rust wireless structure，也未进行页面级 PDF/PNG 重跑；默认 Python 路由保持不变。

- Task 3B superscript review fix：补齐 superscript 分支绕过 placeholder/numeric veto 的边界。
  - **根因与调用位置**：`rust/native_span.rs::build_text_runs()` 新增 superscript 分支后，较小的数字或 dash placeholder 可能在 Python `_can_join()` 的前置 veto 之前被合并；但 numeric-gap veto 不能无条件放入 Rust 普通 join 链，否则会破坏既有普通 numeric span 合并合同。
  - **判定条件**：placeholder 使用 Python separator/placeholder 字符和 1-3 字符规则，并保留 gap 不超过 1.0 的 inline-punctuation 例外；numeric text 使用与 Python `\d` 对齐的 decimal digit 白名单和数字格式；numeric-gap veto 只在严格 `0.82`/x-corridor superscript 条件命中时阻断，普通同字号 numeric join 和 packed fragment veto 保持不变。
  - **测试与验证**：新增 `1`+小号 `2`、`基`+小号 `-` 的真实 Python/Rust 反例；RED 为 `1 failed, 13 deselected`，fresh superscript focused GREEN 为 `3 passed, 11 deselected`，differential/text-runs 为 `59 passed`，packed numeric 为 `20 passed`，`cargo test --lib native_span` 为 `4 passed`，`git diff --check` 通过；Python binding 通过 `maturin develop --release` 重建后验证。
  - **限制**：本修复仍只覆盖 synthetic native-span/text-run 语义，不进入 wrapped merge、alignment corridor、column/grid/header、页面级 JSON/PNG 或默认 Rust route 切换。

- Repair Sprint 003：收紧 Rust 无线结构输出的 Cell 网格边界。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_table_recovery.py` 的 `_rust_cells_to_project()` 在读取 `row`、`col`、`rowspan`、`colspan` 时先调用 `int()`，导致 `-0.5`、整数值浮点数或 `bool` 可能被截断或当作整数进入公开 `Cell`。这是 Rust 输出验证边界的问题，不是 Python 无线结构算法的行为调整。
  - **判定条件**：四个 Cell 网格字段现在必须是严格的 Python `int`；`bool`、`float`、字符串及其他可截断类型直接拒绝。既有正跨度、越界、缺失 bbox、occupancy conflict 和未覆盖槽位校验继续执行，默认 Python 路由、shadow 返回 Python 及 Rust 异常 fallback 不变。
  - **测试与验证**：新增 12 个非整数/`bool` RED 用例；Generator 报告修复前 `12 failed`，修复后 focused `12 passed`。独立 Luna Evaluator 复核为无 Critical/Important。新鲜运行 `tests/test_pdf_fast_shared_recovery.py` 为 `19 passed`，相关 Snapshot/无线结构/路由回归合计 `87 passed`；`cargo test --lib` 为 `44 passed`，`cargo check` 和 `git diff --check` 通过。
  - **限制**：`cargo fmt --check` 仍报告既有 `rust/lib.rs`、`rust/types.rs`、`rust/wireless_structure.rs` 的基线格式差异，本修复未格式化这些无关代码。中文/混合无线结构的完整 Python/Rust 字段级 parity、真实页面 JSON/PNG 验收仍未完成，默认路由保持 Python。

## 2026-09-18

- **OpenVINO CPU 后端接入**：为表格检测模型增加 `backend="auto"`、`backend="cpu"` 和 `backend="openvino"` 选择。`auto` 仅在检测到 Intel CPU 且 OpenVINO provider 可用时尝试 OpenVINO；provider 初始化失败或未实际激活时自动回退到 CPU，避免部署环境因缺少可选依赖而中断。
  - **根因与调用位置**：`src/hexai_pdf_parser/ml/ml_table_detector.py` 原先固定创建 `CPUExecutionProvider` session，无法利用 Intel CPU 上已安装的 OpenVINO Execution Provider；Windows pip 安装的 OpenVINO DLL 也不会自动被 provider bridge 找到，导致 provider 发现成功但 session 实际退回 CPU。
  - **判定条件与实现**：使用 `platform.processor()`/`platform.uname().processor` 识别 Intel CPU；在 OpenVINO 路径先注册 `openvino/libs` DLL 目录并显式加载 `openvino.dll`，再创建 ORT session；OpenVINO session 使用 `ORT_DISABLE_ALL`，由 OpenVINO 执行图优化。session 缓存 key 包含模型路径、provider 和 provider options，避免不同后端或设备配置复用错误 session。
  - **依赖安装**：`pyproject.toml` 和 `setup.py` 新增独立 `ml-openvino` extra，对应 `onnxruntime-openvino==1.24.1` 与 Windows 所需 `openvino==2025.4.1`；不与普通 `onnxruntime` extra 同时安装。
  - **测试与验证**：新增自动选择、非 Intel 回退、OpenVINO 不可用回退、强制 OpenVINO 报错、缓存隔离和 session 初始化失败回退测试；当前环境为 Intel Core i5-10200H，OpenVINO 实际模型 session 返回 `OpenVINOExecutionProvider` 并完成 `1x3x640x640` 推理，输出形状为 `1x300x6`。

## 2026-09-17

- Sprint 012：完成端到端前后 Benchmark、页面视觉检验、全量 Rust 解析验证和发布物构建。
  - **根因与调用位置**：在全套 PDF 表格纯算法（有线几何、有线单元格、共享几何、Native Span、中文无线结构、共享无线、英文无线、表头规范化）全部完成 Rust (PyO3) 迁移并建立统一差分路由后，需要对系统进行全量收官验收。确保全部 8 项函数级 benchmark、7 个代表页 page-level benchmark、1023 页全量 PDF benchmark 达成 100% 结构等价性；完成跨模式 JSON/PNG 视觉对齐；验证 Rust 模式下全书无阻断解析；并通过 wheel/sdist 构建及代码规范门禁。
  - **设计与修复判定**：
    - **函数级与页面级 Benchmark**：对 8 个函数级套件和 7 代表页运行 Baseline, Python, Shadow, Rust 四路测试，验证所有结构化数据完全等价（`equal: true, differences_count: 0`），有线几何（1.51x）、有线单元格（1.76x）、共享几何（1.54x）、表头规范化（1.48x）等算子纯计算取得显著加速。
    - **端到端代表页视觉与结构导出**：通过 `scripts/export_rust_migration_e2e.py` 在 `output/pdf_rust_migration_final_*_20260916/` 导出三路结果，核验表格数量、来源、行列索引、跨度无误，0 槽位冲突（`occupancy_conflicts: 0`）。
    - **全量 Rust 解析验证**：在 `PDF_RUST_MODE='rust'` 下对代表页执行端到端解析，耗时 22.432s，生成完整 JSON、Markdown、PNG 与 `timings.json`。
    - **发布物与代码规范构建**：验证 wheel (`cp37-abi3-win_amd64.whl`) 和 sdist (`hexai_pdf_parser-1.1.1.tar.gz`)，通过 `cargo fmt --check`、`cargo test`、核心 `pytest` 及 `git diff --check`。
  - **测试与基准测试结果**：
    - 8 个函数级 final 报告已生成并归档至 `docs/superpowers/rust-migration/benchmarks/`。
    - 代表页与全量 PDF 报告已归档至 `docs/superpowers/rust-migration/benchmarks/page-final.md` 与 `benchmark-2026-09-16.md`。
    - `cargo test` 14 passed，`pytest` 20 passed，`cargo fmt --check` 0 警告，`git diff --check` 0 警告。


- Sprint 011：构建统一差分路由、异常回退降级、路径特征门禁与端到端代表页验收。
  - **根因与调用位置**：在全量算法完成 Rust 迁移后，需要建立严格的生产路由仲裁、灰度切换与高可用容灾机制，确保无环境变量时稳定保持 Python，支持通过环境变量（`PDF_RUST_MODE` 与路径级 `PDF_RUST_MODE_<PATH>`）进行灵活灰度与回退，且任何运行期 Rust 异常均能优雅降级回退至 Python 并输出诊断信息。
  - **设计与修复判定**：
    - **统一路由函数体系**：在 `src/hexai_pdf_parser/rust_adapter.py` 实现了 `get_rust_mode`、`run_python_or_rust`、`assert_equivalent`、`get_diagnostics`、`clear_diagnostics`。
    - **模式合同严格遵守**：
      - `python`：纯 Python 路径，不调用 Rust；
      - `rust`：调用 Rust 算子，异常时自动捕获并记录 `rust_fallback` 诊断，安全回退 Python，保障服务不中断；
      - `shadow`：双路并发运行，对比结果并在出现差异时记录 `rust_output_mismatch` 诊断，向外始终返回 Python 权威结果；
      - 非法模式严格阻断并抛出 `ValueError`。
    - **端到端代表页全量验收**：升级 `scripts/export_rust_migration_e2e.py`，完整调用 `PDFParser` 全流水线，对 `zh_all_table_pages.pdf` 的 7 个核心代表页（185, 196, 347, 415, 437, 1002, 1014）进行 Python、Shadow、Rust 三路独立导出与严格比对。
  - **测试与基准测试结果**：
    - 新增 `tests/test_rust_migration_routing.py`，9 个针对各模式、异常 fallback、mismatch 诊断记录及特征门禁的单元测试全部通过（`9 passed`）。
    - 全链路核心回归测试套件（9 个文件）：95 passed, 0 failed。
    - `git diff --check`: 0 警告。
    - **端到端对比报告 (sprint-011-fix-e2e)**：在 7 个代表页上对比确认 `equal: true, differences_count: 0`；所有表格无槽位占用冲突（`occupancy_conflicts: 0`），结构化指标与单元格完全对齐。

- Sprint 010：迁移可 DTO 化的表头与结构后处理纯算法至 Rust (PyO3) 并释放 GIL。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py` 中的 `_promote_grouped_header` 以及相关财务大表头文本规范化逻辑，原先在 Python 层面通过循环、正则和对象属性反复判定，需要与 Rust 表格结构生成流水线衔接，支持直接在 DTO 层面进行结构推断与清洗。
  - **设计与修复判定**：
    - **Rust 内核实现**：在 `rust/table_normalization.rs` 实现了 3 个纯计算算子：`infer_header_structure`（锚点向下合并与分组标题跨列合并）、`merge_header_spans`（表头坐标排序与跨度规范化）、`normalize_financial_header_tokens`（表头尾随数值/货币代码剥离清洗）。密集计算通过 `py.allow_threads` 释放 GIL。
    - **DTO 与导出路由**：在 `rust/types.rs` 新增 `HeaderGridInput`、`HeaderGridOutput`、`HeaderTokenInput`、`HeaderTokenOutput` 结构并注册到 `roundtrip_dto`；在 `rust/lib.rs` 导出 3 个算子并在 `src/hexai_pdf_parser/rust_adapter.py` 暴露强类型 Python 签名；在 `table_header_normalizer.py` 接入 `PDF_RUST_MODE` 路由（生产默认 `python`，支持 `shadow` 和 `rust`）。
  - **测试与基准测试结果**：
    - 新增 `tests/test_pdf_fast_table_normalization.py`，5 个单元测试全部通过（`5 passed`）。
    - 表头全量回归套件：20 passed, 3 skipped。
    - `cargo test`: 2 passed, 0 failed.
    - `cargo fmt --check`: 0 警告。
    - `git diff --check`: 0 警告。
    - **基准测试 (table-normalization)**：四路对比（baseline, python, shadow, rust）确认 `equal: true, differences_count: 0`；结构化结果完全一致，无冲突、无遗漏。

- Sprint 009：迁移英文 Zebra、General Wireless 和 Legacy 纯算法至 Rust (PyO3) 并释放 GIL。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` 中的 `_group_into_tables`、`_assign_words_to_zebra_rows`、英文列推断与单元格恢复，以及 `src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py` 中的 `_rebuild_text_aligned_table` 原先在 Python 层面通过反复的几何间距遍历、词列表排序、正则和拓扑跨列比较进行处理，在英文无线与斑马表格上带来解释执行开销。
  - **设计与修复判定**：
    - **Rust 内核实现**：在 `rust/english_wireless.rs` 完整实现了 7 个核心算子：`group_backgrounds`、`detect_zebra_rows`、`assign_words_to_zebra_rows`、`infer_english_columns`、`build_english_cells`、`build_general_wireless_cells`、`build_legacy_text_alignment`。密集计算全部通过 `py.allow_threads` 释放 GIL。
    - **无线表格不变量严格遵守**：
      - 纯消费规范 DTO（`ZebraInput`, `EnglishGridInput`, `GeneralWirelessInput`, `LegacyAlignmentInput`），隔离中英文处理管线；中文/混合页面绝对禁止调用或回退到 zebra/legacy 路径。
      - 独立字段保留为独立叶子列，无占位冲突。
    - **DTO 与导出路由**：在 `rust/types.rs` 新增对应 DTO 并注册到 `roundtrip_dto`；在 `rust/lib.rs` 导出 7 个算子并在 `src/hexai_pdf_parser/rust_adapter.py` 暴露强类型 Python 签名；在 `english_table_extractor.py` 与 `table_header_normalizer.py` 接入 `PDF_RUST_MODE` 路由（生产默认 `python`，支持 `shadow` 和 `rust`）。
  - **测试与基准测试结果**：
    - 新增 `tests/test_pdf_fast_english_wireless.py`，8 个单元测试全部通过（`8 passed`）。
    - `cargo test`: 12 passed, 0 failed.
    - `cargo fmt --check`: 0 警告。
    - `git diff --check`: 0 警告。
    - **基准测试 (english-wireless)**：四路对比（baseline, python, shadow, rust）确认 `equal: true, differences_count: 0`；结构化结果完全一致，无冲突、无遗漏。

- Sprint 008：迁移共享无线表格 Native Recovery 与候选选择算子至 Rust (PyO3) 并释放 GIL。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_table_recovery.py` 中的 `table_quality` 评分、候选区域过滤与 0.20 重叠仲裁 `select_candidates()`，以及跨区域批量恢复 `recover_wireless_tables()` 原先在 Python 层面通过反复的几何重叠检测、字典序比较和列表剔除处理，存在循环解释开销；需要与 Rust 结构恢复内核紧密结合，实现一次性端到端批量消费 DTO。
  - **设计与修复判定**：
    - **Rust 内核实现**：在 `rust/wireless_structure.rs` 实现了 `table_quality`、`select_candidates` 与 `recover_wireless_tables`，在 Rust 内部完成基于质量评分（confidence, populated cell 计数, size 行列乘积）的确定性排序与重叠解决，密集计算通过 `py.allow_threads` 释放 GIL。
    - **中文无线表格不变量严格遵守**：
      - 恢复阶段纯消费 `NativeSpanDto`、`RegionDto`、`StructureConfig` 和 `TableCandidateDto`，严格禁止调用 `page.get_text("words")`，自动化 PageSpy 拦截测试验证通过。
      - 候选过滤严格遵从 excluded 与 allowed 几何区域约束，重叠率阈值 `>= 0.20` 时依质量评分择优淘汰，杜绝误并与冲突。
    - **DTO 与导出路由**：在 `rust/types.rs` 新增 `WirelessRecoveryInput` 与 `WirelessRecoveryOutput` DTO 结构，登记到 `roundtrip_dto`；在 `rust/lib.rs` 导出 3 个算子并在 `src/hexai_pdf_parser/rust_adapter.py` 暴露强类型 Python 签名；在 `wireless_table_recovery.py` 接入 `PDF_RUST_MODE` 路由（生产默认 `python`，支持 `shadow` 和 `rust`），并完整保留原始诊断数据结构。
  - **测试与基准测试结果**：
    - 新增 `tests/test_pdf_fast_shared_recovery.py`，6 个针对质量评分、候选选择过滤与冲突排除、DTO roundtrip、端到端 recover_wireless_tables 以及 PageSpy（确保无 words 回读）的单元测试 100% 通过（`6 passed`）。
    - `cargo test`: 全部通过。
    - 无线全量测试套件：244 passed, 0 failed。
    - `cargo fmt --check`: 格式检查通过，0 警告。
    - `git diff --check`: 检查通过，0 警告。
    - **基准测试 (shared-wireless)**：四路对比（baseline, python, shadow, rust）确认 `equal: true, differences_count: 0`；结构化结果完全一致，无冲突、无缺失。

- Sprint 007：迁移中文/混合无线结构恢复（列带划分、叶子精化、物理网格与逻辑网格物化）至 Rust (PyO3) 并释放 GIL。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/{columns,grid,logical_grid,recoverer}.py` 中的 `infer_column_bands()`、`refine_leaf_bands()`、`build_grid()`、`build_logical_grid()` 与 `recover_cells_from_region()` 原先在 Python 层面通过大量的候选循环、集合操作、物理行聚类与空槽位切分进行处理，在包含密集单元格的中文无线大表格上造成显著的解释执行耗时。
  - **设计与修复判定**：
    - **Rust 内核实现**：在 `rust/wireless_structure.rs` 实现了 `infer_column_bands`、`refine_leaf_bands`、`build_grid`、`build_logical_grid` 与 `recover_native_region`，在 Rust 内部完成基于 x 重叠组件的列带推断、纵向容差物理行聚类、叶子列槽位匹配与逻辑网格空槽独立物化，密集计算通过 `py.allow_threads` 释放 GIL。
    - **中文无线表格不变量严格遵守**：
      - 结构恢复阶段只消费 `NativeSpanDto`、`AtomDto`、`ColumnBandDto`、`PhysicalCell`、`LogicalGridDto` 和 `CellDto`，严格禁止再次调用 `page.get_text("words")`，自动化 PageSpy 拦截测试验证通过。
      - 独立字段默认保留为独立叶子列，不得仅因两个 atom 位于同一候选槽位就合并它们；
      - 表格中的空槽位也是结构的一部分，所有未被现有跨度覆盖的槽位均严格物化为独立 `text=""`、`1x1` Cell，按推断网格边界切分，不合并相邻空单元格；
      - 严格保证每个逻辑槽位恰好被一个 Cell 占用，无重复、无遗漏。
    - **DTO 与导出路由**：在 `rust/types.rs` 新增 `NativeRegionInput` 与 `NativeRegionOutput` DTO 结构，登记到 `roundtrip_dto`；在 `rust/lib.rs` 导出 5 个算子并在 `src/hexai_pdf_parser/rust_adapter.py` 暴露强类型 Python 签名；在 `recoverer.py` 接入 `PDF_RUST_MODE` 路由（生产默认 `python`，支持 `shadow` 和 `rust`）。
  - **测试与基准测试结果**：
    - 新增 `tests/test_pdf_fast_wireless_structure.py`，8 个针对列带推断、叶子精化、物理网格、空槽单元格独立物化、端到端区域恢复、独立字段不误并、槽位唯一占用及 PageSpy（确保无 words 回读）的单元测试 100% 通过（`8 passed`）。
    - `cargo test`: 9 passed, 0 failed.
    - 无线全量测试套件：230 passed, 0 failed in 2.16s。
    - **基准测试 (chinese-wireless)**：四路对比（baseline, python, shadow, rust）确认 `equal: true, differences_count: 0`；结构化结果完全一致，无冲突、无空槽位遗漏。


- Sprint 006：迁移无线表格 Native Span、Atom 和 Text Run 数据流至 Rust (PyO3) 并释放 GIL。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 中的 `build_text_runs()`、`infer_output_order_mode()`、以及原子聚合与换行续写合并等算法，原先在 Python 解释器中通过 Python 循环、正则匹配与字典拆装处理，在无线大表格上产生显著的解释执行与内存开销。
  - **设计与修复判定**：
    - **Rust 内核实现**：在 `rust/native_span.rs` 实现了 `build_text_runs`、`build_atoms`、`merge_wrapped_rows`、`infer_output_order_mode` 与 `recover_native_candidates`，在 Rust 内部完成基于 20 组 CJK 大字距白名单词对（最大放宽至 2.5 倍字距）与普通单字 CJK（严格 1.25 倍字距，杜绝误并）的高效文本聚类，密集计算通过 `py.allow_threads` 释放 GIL。
    - **中文无线表格不变量**：纯消费 `NativeSpanDto`，进入 atom、列带和网格拓扑计算后严格不回读 `page.get_text("words")`，新增 `test_page_spy_no_get_text_words` 进行拦截验证。
    - **DTO 与导出路由**：在 `rust/types.rs` 新增 `NativeRecoveryInput` 与 `NativeRecoveryOutput` DTO 结构，登记到 `roundtrip_dto`；在 `rust/lib.rs` 导出 5 个算子并在 `src/hexai_pdf_parser/rust_adapter.py` 暴露强类型 Python 签名。
  - **测试与基准测试结果**：
    - 新增 `tests/test_pdf_fast_wireless.py`，8 个针对白名单合并、反例不合并、混合成词、换行合并、阅读顺序推断及 PageSpy 的单元测试 100% 通过（`8 passed`）。
    - `cargo test`: 8 passed, 0 failed.
    - 核心 fast 单元测试集：69 passed in 0.60s.
    - **基准测试 (native-span)**：四路对比（baseline, python, shadow, rust）确认 `equal: true, differences_count: 0`；Rust 相比 Python baseline 算法 P95 加速比达到 **1.32x**，端到端 P95 加速比达到 **1.46x**。

- Sprint 005：抽取共享基础几何、区域过滤、行列聚类与稳定排序算法至 Rust (PyO3) 并释放 GIL。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/table_extractor.py` 中的 `_bbox_overlaps()`、`wireless_table_recovery.py` 中的 `_row_cluster()`、以及多处候选区域过滤和表格候选稳定排序，原先在 Python 解释器中通过 Python list、dict、lambda 进行循环与排序计算，随着跨页和复杂表格候选增多，带来额外的调度和解释执行耗时。
  - **设计与修复**：
    - **Rust 内核实现**：在 `rust/geometry.rs` 实现 `rect_overlap`（支持严格正面积与接触重叠）、`filter_regions`（支持排除区域与允许区域双重过滤）、`cluster_rows`（纵向中心线容差聚类、行内横向+次序稳定排序）、`cluster_columns`（横向中心线容差聚类、列内纵向+次序稳定排序）及 `stable_output_order`（基于 `(y0, x0, y1, x1, source)` 的确定性稳定排序），并在密集计算处使用 `py.allow_threads` 释放 GIL。
    - **DTO 与导出路由**：在 `rust/types.rs` 补充 `OutputOrderMode` DTO 并注册至 `roundtrip_dto`；在 `rust/lib.rs` 导出 5 个算子；在 `src/hexai_pdf_parser/rust_adapter.py` 暴露强类型接口；在 `TableExtractor._bbox_overlaps` 与 `wireless_table_recovery.py::_row_cluster` 接入 `PDF_RUST_MODE`。
  - **测试与基准测试结果**：
    - 新增 `tests/test_pdf_fast_shared_geometry.py`，17 个单元测试 100% 通过（`17 passed`）。
    - 全量回归测试：在 `python`、`shadow`、`rust` 三种模式下均 154 passed 100% 通过。
    - **基准测试 (shared-geometry)**：四路对比（baseline, python, shadow, rust）确认 `equal: true, differences_count: 0`；Rust 相比 Python baseline 算法 P95 加速比达到 **2.74x**，端到端 P95 加速比达到 **2.50x**。

- 优化 PDF 加载器按需分类机制，彻底消除多页 PDF 局部提取时的全量扫描开销（端到端提速超 20 倍）：
  - **根因与调用位置**：`src/hexai_pdf_parser/core/loader.py::Loader.load()` 原先无条件遍历 PDF 的所有页面，并在循环体内对每一页无差别调用 `classify_page_type(page)` 进行字符失真、字体和文本扫描。当处理 1000+ 页的超大 PDF（如 `zh_all_table_pages.pdf`）并指定仅提取少量页面（如 `pages=[196, 415]`）时，上层 `PDFParser` 与 `Pipeline` 虽然跳过了非目标页的处理，但 `Loader.load()` 仍盲目耗费约 19.6 秒扫描整本 1023 页，使原本只需 1 秒的局部提取严重劣化至 21 秒。
  - **设计与修复**：
    - `Loader.load(page_indices=...)` 新增可选参数 `page_indices`；仅对用户指定的请求页调用 `classify_page_type` 进行扫描，未请求页面保留默认值 `"vector"`，完全避免无谓的解析开销；
    - 在 `PDFParser.extract_tables`、`extract_text`、`extract_images`、`render_pages` 及 `Pipeline.run()` 中全链路透传 `page_indices` 至 `Loader.load()`。
  - **测试与验证**：
    - 新增 `tests/test_loader_lazy_page_classification.py`，测试覆盖按需跳过未请求页扫描、`PDFParser.extract_tables` 参数透传及既有全量加载兼容（全部 pass）；
    - 既有 `tests/test_loader.py` 回归通过（`3 passed`）；
    - **实测端到端耗时**：在 `fix/zh_all_table_pages.pdf`（1023 页）上运行 `PDFParser.extract_tables(page_indices=[196, 415])`，稳定平均耗时从 **21.37 秒** 直降至 **1.05 秒**，端到端实际提速达 **20.4 倍**。

- Sprint 004：迁移有线表格 Cell 划分、幽灵行修剪、超切列合并与文字归属至 Rust (PyO3) 并释放 GIL。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py` 中 `_build_cells_for_region()`、`_trim_ghost_edge_rows()`、`_merge_oversegmented_line_columns()` 与 `_assign_text_to_line_cells()` 原先在 Python 层面频繁进行网格连通分量遍历、泛洪填充、边界拓扑判定和跨行跨列字符拆分归属，存在大量解释执行开销与 GIL 竞争；且原提取器在多个子方法中多次调用 `page.get_text("words")` 与 `page.get_text("rawdict")`，违背结构恢复不回读 words 约束。
  - **设计与修复判定**：
    - **页面级统一缓存**：在 `WiredTableExtractor.extract()` 页面处理入口处一次性提取并缓存 `words` 与 `raw_chars`，全流程禁止再次调用 `page.get_text()`。
    - **Rust 内核实现**：在 `rust/wired.rs` 中完整实现纯几何线网外框补齐、泛洪连通分量矩形切分、occupancy 槽位无冲突验证、物理横线支撑幽灵行修剪、超切空列合并与基于银行家舍入的字词中心点/字符级边界拆分归属，所有密集计算在 `rust/lib.rs` 中通过 `py.allow_threads` 释放 GIL。
    - **DTO 边界与解耦路由**：在 `rust/types.rs` 实现 `WiredRegionInput` 与 `WiredRegionOutput`；通过 `src/hexai_pdf_parser/rust_adapter.py` 暴露强类型接口；并在 `wired_table_extractor.py` 接入 `PDF_RUST_MODE`（支持 `python` 生产默认、`shadow` 双路对比与 `rust` 加速）。
  - **不回读 words 约束验证**：在 `tests/test_pdf_fast_wired.py` 中通过 `PageSpy` 拦截 `get_text` 调用，验证提取过程中对 `"words"` 和 `"rawdict"` 的调用计数严格不超过 1 次，Rust 只消费解析后的 WordDto 与 CharacterDto。
  - **测试与基准测试结果**：
    - `cargo test`: 6 passed, 0 failed.
    - `pytest tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_wireless_extractor_split.py`: 在 `python`、`rust` 和 `shadow` 三种模式下均 90 passed 100% 通过。
    - **基准测试 (wired-cells)**：四路对比（baseline, python, shadow, rust）确认 `equal: true, differences_count: 0`；Rust 相比 Python baseline 算法 P95 加速比达到 **7.30x**，端到端 P95 加速比达到 **2.01x**。
  - **端到端页面验证**：通过 `scripts/export_rust_migration_e2e.py` 重跑真实 PDF `fix/zh_all_table_pages.pdf` 页面索引 196 与 415 至独立输出目录：
    - Python 输出目录: `output/pdf_rust_migration_wired_python_20260916/`
    - Rust 输出目录: `output/pdf_rust_migration_wired_rust_20260916/`
    - 比对报告: `docs/superpowers/rust-migration/evaluations/sprint-004-pages.md` 确认两页表格数量（P196: 1 表 72 单元格；P415: 1 表 72 单元格）、边界及文本 100% 一致（`differences_count: 0`），图表过滤和复杂外框未受影响。


- 修复中文无线表格中排版大字距常见单字词组（如“合 计”、“小 计”等）成词被拆分并引发伪列带的问题：
  - **根因与调用链**：在 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py::_can_join()` 中，`spaced_single_cjk` 间隙上限原固定为 `1.25 * font_size`。当 PDF 排版中两个单字（如“合”与“计”）使用分散对齐或双全角空格时，实际间隙可达约 `2.0 * font_size`（本例中 21.06pt），导致成词失败被拆为两个独立的 Atom。随后的 `infer_column_bands()` 将“合”归入项目列带，而游离的“计”被 `header_topology.py::rescue_sparse_body_bands()` 错误抢救为独立列带（Band 2），造成物理网格裂为 6 列，并在合计行产生孤立的 `<td>合</td><td>计</td>`。
  - **判定与修改**：在 `text_runs.py` 中引入常见两字排版词白名单 `_SPACED_CJK_WORD_WHITELIST`（包含“合计”、“小计”、“总计”、“类别”、“税种”、“项目”等核心表格骨架词）。在同一原生文本行且两端均为严格单字 CJK 时，白名单词对允许的最大字间距放宽至 `2.5 * min(font_size)`；非白名单或普通单字依然严格限制在 `1.25 * font_size`。
  - **测试与验证**：在 `tests/test_wireless_structure_text_runs.py` 中新增白名单词对（“合计”、“小计”）大字距合并正例、非白名单单字（如“男”、“女”）大字距保持独立反例；无线结构测试集 222 项全部通过（`222 passed`），`git diff --check` 0 错误。
  - **页面级验证**：在独立输出目录 `output/fix_spaced_cjk_page_185/` 重跑 `fix/zh_all_table_pages.pdf` 页面索引 185（`page-185`）。Table 1 由原本异常的 `5x6` 正确恢复为 `5x5`，末行单元格成功合并为 `'合计'`，多余的空列带完全消除，可视化 PNG 中“合 计”由单一完整单元格边界包围。

## 2026-09-15

- 收紧有线候选的矩形边重复线去重：根因是部分 PDF 将同一条可见细线同时编码为描边 `l` 和窄填充 `re`，两条中心坐标相差约 `0.4pt`，在 `_merge_h_lines()`/`_merge_v_lines()` 前会形成重复网格坐标；但不能因为候选来自 `re` 就扩大所有线的合并容差。
  - **判定与调用位置**：`WiredTableExtractor._extract_lines_from_drawings()` 记录窄填充矩形及其几何边，只在另一条候选与该矩形边的方向、长轴覆盖率（至少 `98%`）、端点和法向坐标均匹配时提前去重。普通 `l`、独立 `re` 以及跨度不一致的近邻线继续保留；`merge_group_tol` 不因 `re` 来源而放宽。
  - **测试与验证**：新增同一几何矩形边的 `l`/`re` 重复正例、无匹配矩形边的近邻线反例和两个独立近邻 `re` 反例；有线提取器专项测试 `52 passed`。包含表格提取器、可视化和有线专项的结果为 `150 passed, 1 failed`，唯一失败仍为既有 hybrid 路由测试（预期 `hybrid_line_span_recovery`、实际 `line_projection`），未触及本次路径；`compileall` 与 `git diff --check` 通过。
  - **页面级验证**：在独立输出目录 `D:\codes\PDFLayoutParser\output\rectangle_frame_line_dedupe_20260915\` 重跑真实 PDF 页面索引 `84/85/86/196`（P85/P86/P87/P197）。P85、P86、P87 的结构分别为 `36x4`、`40x4`、`27x4`；P197 保持 `36x9`、73 个 Cell。PNG 视觉复核确认三页原有边框和网格连续，P197 的大外框及局部线段没有被删除或扩展。

## 2026-09-14

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `415`（印刷页 17）柱形图被误检为有线表格，并阻止同一图表候选在下游重新变成 `english_general_wireless` 表格。
  - **根因与调用链**：提交 `0ca829e` 在 `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py::_extract_lines_from_drawings()` 中恢复了描边封闭矩形的四条边，以支持 `PDFsam_merge1.pdf` 等真实有线表格。P415 的每个柱子也由同 bbox 的彩色填充 `re` 和黑色 `type="s"` 描边 `re` 组成；10 个柱子的底边与坐标轴相交后，经 `_find_table_regions()` 的“横竖线相交即连通”规则生成 `11x10` 的 `line_projection` 伪表格。移除 wired 结果后，ML 候选框仍会被 `TableExtractor._recover_tables_from_regions()` 送入 `EnglishTableExtractor.extract_general_wireless()`，因此单修 wired 层会把同一误检改名为 `english_general_wireless`。
  - **修复判定**：在 wired 线拓扑之前，仅收集可见轴对齐 `re` 矩形；只有填充矩形与可见描边矩形 bbox 在 `1.0pt` 内匹配，并且成组满足“至少 3 根、共用底边、宽度差不超过 `max(1.5pt, 中位宽度的 15%)`、高度差至少 `max(4pt, 中位宽度的 50%)`、横向不重叠且至少有一个 `>= max(线容差, 中位柱宽的 25%)` 的柱间空隙”的组件，才建立柱形图 mask。最后一条是防止共享列边界的填充描边 `rowspan` 表格被误判；P415 的成对柱之间仍有明显空隙。mask 按 `max(6pt, 3 * 中位柱宽)` 扩展，覆盖 P415 坐标轴和图例；仅完整位于 mask 内的横/竖候选线被过滤。
  - **下游守卫与兼容边界**：`WiredTableExtractor` 保存当前页面的 chart mask，并绑定产生它的 page 对象；`TableExtractor._recover_tables_from_regions()` 仅在同一 page 上、且候选 bbox 被 mask 覆盖比例达到 `0.5` 时跳过无线/回退候选。该规则不按页码、业务文字或“Cell 必须有文字”判定，也不新增 `page.get_text("words")` 读取。没有成组“填充+描边”柱形证据时，`0ca829e` 的 `type="s"`/`type="fs"` 封闭矩形四边拆解保持不变；`PDFsam_merge1.pdf` 第 0 页仍保留 4 张有线表格，目标“信息概要明细”仍为 `6x5`。
  - **测试先行与回归**：在 `tests/test_wired_table_extractor.py` 新增合成柱形图反例、P415 页面反例、无填充描边 2x2 正例、填充描边 `rowspan` 正例和两色块图例反例；在 `tests/test_table_extractor.py` 新增候选恢复层及主入口 P415 回归、跨页 mask 隔离和局部重叠保留测试。新增边界测试均先在旧实现下稳定失败，修复后 wired 专项为 `51 passed`，表格模块排除既有历史失败项后为 `93 passed, 1 deselected`。完整 `tests/test_table_extractor.py` 仍有 1 个既有失败：`test_hybrid_wired_table_replaces_full_rowspan_body_before_shifting_footer` 的历史 source 期望差异。
  - **页面验证**：使用 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`、页索引 `415` 和当前 worktree 源码独立输出到 `D:\codes\PDFLayoutParser\output\p415_bar_chart_filter_20260914\`。`pages/page-415.json` 的 `page_type=vector`，最终只有下方 `english_general_wireless`、`9x4`、bbox `[59.8,549.9,549.9,718.0]` 的 Operating Expenses 表格，图表区域表格数为 `0`。`zh_all_table_pages_page_415_visualized.png` 视觉核验确认图表未被红色表格框覆盖、下方真表边界和文字归属正常；调试图左上角的 `page_type: vector` 标注会遮住少量 logo，但不影响解析结果。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `196`（印刷页码 P197）有线表格的局部线段被投影为整页网格问题。根因在 `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py::_build_cells_for_region()`：非矩形连通组件原先按全局网格逐槽位物化，局部横/竖线坐标又被边界吸附和相邻候选同时命中，最终把不属于上方区域的线表现成跨页 Cell 边界；底部 ghost 行裁剪时还可能留下未同步收缩的跨行 Cell。最终可视化中的左侧延伸横线另有一层原因：物理线没有延伸，但 `table_visualizer` 为每个 Cell 直接绘制完整矩形，补出了不存在的边界。
  - **修复判定**：新增 `_snap_grid_coordinates()`，只有接近区域边界且在正交方向具有近乎全长覆盖的真实线才可吸附为外框；`has_h_segment()` / `has_v_segment()` 只采用距离当前网格坐标最近的真实线候选。非矩形连通组件改为依据真实 `h_edges`/`v_edges` 切分为互不重叠的安全矩形，保留合法 `rowspan`/`colspan`，不再逐槽位制造跨区域假 Cell；ghost 行被裁剪时同步截断跨行 Cell 的 `rowspan`。
  - **线段连接边界**：保留 PDF 视觉上常见的小断隙桥接；新增横线大间隙不连接测试，并覆盖边界附近局部横线不得扩展为整行的反例。结构恢复仍只消费物理线、网格和 Cell，不新增无线表格 `page.get_text("words")` 回读或旧路径回退。
  - **可视化修复**：有线提取结果把真实区域线段保存到 `Table.h_lines`/`Table.v_lines`，`TableExtractor._clamp_table_to_page()` 保留该元数据；带物理线元数据的表格由 `table_visualizer` 直接绘制裁剪后的真实线段并跳过完整 Cell 矩形，旧测试构造的无元数据表格保持原行为。
  - **测试与验证结果**：`tests/test_table_extractor.py tests/test_table_visualizer.py tests/test_wired_table_extractor.py tests/test_rule_first_table_detection.py` 为 `158 passed, 1 failed`；唯一失败为既有 `test_hybrid_wired_table_replaces_full_rowspan_body_before_shifting_footer`，预期 `hybrid_line_span_recovery`、实际 `line_projection`，本次未修改该调用链。`python -m compileall -q src tests/test_table_visualizer.py tests/test_wired_table_extractor.py tests/test_table_extractor.py` 与 `git diff --check` 通过。
  - **页面级验证**：使用当前 worktree 独立重跑 P197 到 `D:\codes\PDFLayoutParser\output\p197_line_span_visualizer_fix_20260914_v2\`。结果为 1 张 `line_projection` 表，`36x9`、73 个 Cell、bbox `[30.6,63.8,560.5,814.7]`；324 个逻辑槽位全部恰好覆盖，occupancy conflict 为 `0`，没有越界 Cell；最终表对象携带 38 条横线和 25 条竖线。新 PNG 视觉复核确认左侧假横线消失，真实表格横线仍保留。
  - **页面产物**：结构化结果为 `D:\codes\PDFLayoutParser\output\p197_line_span_visualizer_fix_20260914_v2\pages\page-196.json`，修复后表格可视化为 `D:\codes\PDFLayoutParser\output\p197_line_span_visualizer_fix_20260914_v2\tables\page-196.png`；旧目录中的 `p197_wired_lines_raw_final_overlay.png` 和 `p197_wired_lines_merged_final_overlay.png` 仍用于物理线对照。大连通域及真实整页外框仍保留，属于按物理连通线保留的预期结果。

## 2026-09-11

- 在 `MLTableDetector` 中实现进程级共享会话缓存（`_GLOBAL_SESSION_CACHE` 与 `get_shared_session`），彻底解决多次实例化检测器时重复从磁盘加载 36.4 MB 模型并初始化 ONNX Runtime Session 的冷启动开销。
  - **根因与调用位置**：`src/hexai_pdf_parser/ml/ml_table_detector.py::MLTableDetector._load_session()`。原实现将 `self._session` 绑定为实例变量，当外部连续处理不同 PDF 文档、API 多次调用或外部脚本按页循环调用 `_run_page_pipeline` 时，每次创建 `TableExtractor` / `MLTableDetector` 都会重新触发 `ort.InferenceSession()`，导致每次均需耗费 ~300ms 从磁盘重读 36.4MB 模型并重新构建计算图。
  - **设计与改动**：
    - 在 `ml_table_detector.py` 模块级引入线程安全的 `_GLOBAL_SESSION_CACHE` 与 `get_shared_session(model_path, providers)`，以模型的绝对规范路径与 providers 组合为键实现单例共享；
    - `MLTableDetector._load_session()` 优先从全局缓存获取会话；`close()` 仅清理当前实例本地引用，不影响全局缓存；同时提供 `clear_session_cache()` 支持显式缓存清理与单测重置。
  - **测试与验证**：在 `tests/test_ml_table_detector.py` 中新增 `test_ml_table_detector_reuses_shared_session` 和 `test_clear_session_cache_forces_recreation`，验证多实例间 `is` 强一致共享以及显式清理重置逻辑，全量 34 项关联测试 100% 通过。


- 在 `TableConfig`、`TableExtractor`、`Pipeline` 及 `parse_personal_credit_report` 中支持可配置的表格目标检测分辨率 `ml_render_dpi`（默认 `72`），打通从顶层入口到模型检测器的完整参数透传链路。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/table_extractor.py::TableExtractor._extract_model_tables()` 原先实例化 `MLTableDetector` 时未传递 `render_dpi`，且 `Pipeline` 及 `TableConfig` 中缺少对应字段，导致外部即使指定 `render_dpi` 也仅作用于整页渲染图片，无法改变表格目标检测的图像尺寸。
  - **设计与改动**：
    - 在 `TableConfig.GlobalTableSettings` 中增加 `ml_render_dpi: int = 72`；
    - 在 `TableExtractor.__init__` 中新增 `ml_render_dpi: Optional[int] = None`，支持从入参或 `TableConfig` 读取，并在 `_extract_model_tables` 传递给 `MLTableDetector(render_dpi=self.ml_render_dpi)`；
    - 在 `Pipeline`、`_process_page_worker`、`PersonalCreditReportPipeline` 和 `parse_personal_credit_report` 中全链路透传 `ml_render_dpi`。
  - **测试与验证**：新增 `tests/test_table_ml_render_dpi.py` 覆盖全局配置、dict 解析、提取器自定义、模型检测器 mock 调用及 Pipeline 贯通透传（`7 passed`），相关回归测试（`test_table_config.py` 等 32 项）全量通过。端到端验证显式传入 `ml_render_dpi=200` 与 `72` 均生效且输出一致。

- 优化表格目标检测模型输入渲染分辨率：将 `MLTableDetector` 默认 `render_dpi` 从 200 降低到 72（对应 1pt = 1px），大幅削减 PDF 转图片及降采样缩放耗时，全量端到端批处理提速超 51%。
  - **根因与调用位置**：`src/hexai_pdf_parser/ml/ml_table_detector.py::MLTableDetector.__init__()`。在表格检测流程中，PDF 页面渲染成图片仅用于通过轻量级目标检测模型（YOLO `best.onnx`）定位表格候选区域（BBox），不用于字符识别（OCR）或文本提取。YOLO 模型的固定输入尺度为 $640 \times 640$；标准 A4 页面在 200 DPI 下渲染出的图片分辨率高达 $1656 \times 2339$（近 400 万像素），在送入模型前必须经历大比例的双线性/双三次插值降采样缩放至 $640 \times 640$，既消耗了大量的 CPU 栅格化时间，又浪费了图片缩放算力。而在 72 DPI 下（PDF 标准点位 $1\text{pt} = 1\text{px}$），A4 页面尺寸约为 $595 \times 842$，与模型的 $640 \times 640$ 输入尺寸最为贴近，避免了过采样与过度下采样带来的无谓开销。
  - **精度与差异性验证**：
    - 在 100 页样本集上对 200 DPI 与 72 DPI 检出框进行逐框 IoU 与坐标比对：200 DPI 检出 204 个框，72 DPI 同样检出 204 个框，差异页数为 0/100；
    - 在 20 页典型密集表格/复杂表头样本上进行单元格级全文比对：单元格文本 100% 一致（20/20 True）。
  - **端到端全量性能评测**：
    - 测试集：`fix/zh_all_table_pages.pdf`（全量 1023 页）；
    - 全量结果输出路径：`D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_rerun_72dpi_20260911\part_000_pages_0000_1022`；
    - **处理耗时**：从 200 DPI 下的 **1114.2s** 大幅降低至 72 DPI 下的 **544.3s**，**整体耗时减少 51.1%（提速超 2 倍，节约 9.5 分钟）**；
    - **表格数量与分布**：表格总数依然稳定保持在 **2199** 张（`line_projection`: 1713, `wireless_span_recovery`: 445, `english_general_wireless`: 31, `hybrid_line_span_recovery`: 10）；
    - **黄金标签对比**：除 Page 408 历史已知差异页外，1022 页 100% 保持一致，无新增遗漏或误检；比对中发现的少量差异均为正向改进（如 Page 182 边缘置信度略高找回漏检无线表格、Page 337 英文多表头折行融合质量提升）。
  - **结构约束**：只调整区域检测前向图像渲染分辨率，表格内部结构恢复继续 100% 基于 native span、矢量 drawings、拓扑网格与列带，绝对不回读 `page.get_text("words")`，不退回 zebra 路径。
  - **测试覆盖**：
    - 在 `tests/test_ml_table_detector.py` 中新增 `test_ml_table_detector_default_render_dpi_is_72` 与 `test_ml_table_detector_accepts_custom_render_dpi`，测试通过率 100%；
    - 在 `pyproject.toml` 的 pytest 配置中固化 `pythonpath = ["src"]`，杜绝子进程加载旧全局包。

## 2026-09-10

- 在有线表格提取器 `WiredTableExtractor` 中补回把描边封闭矩形（`('re', Rect, 1)`）分解为 4 条边框线的逻辑，解决 `PDFsam_merge1.pdf` 及 `PDFsam_merge2.pdf` 等文档中有线表格（如“信息概要明细”和 2x1 标题表）无法提取线段而漏检、或被误退化为无线表格的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py::_extract_lines_from_drawings()`。在将有线提取逻辑从通用 `TableExtractor` 拆分重构为独立类时，绘图项解析中仅保留了宽高任一维度 $\le \text{line\_tolerance}$ 的“细窄条矩形”判断，遗漏了此前旧版本中针对具有描边属性（`stroke_color is not None` 或 `type in ("s", "fs")`）的宽/高较大封闭矩形的 4 边边框拆解逻辑。导致以描边矩形（`('re', Rect, 1)` 且 `type="s"`）构建网格的征信报告在 `WiredTableExtractor` 中提取出的水平线与垂直线数量几乎为 0，有线表格检出数为 0，进而引发信息概要表退化为 8x6 无线表、而其余 2x1 有线表格全部漏检。
  - **修复判定与守卫约束**：
    - **严格区分描边与填充**：判定 `is_stroked = d.get("type") != "f" and (d.get("type") in ("s", "fs") or stroke_color is not None)`，严格防止纯填充色块（`type="f"`，如背景色块、logo）被误分解为表格线条（遵守 Page 336 填充 logo 误报防回归约束）；
    - **尺寸与面积过滤**：要求 $w \ge 3.0, h \ge 3.0$ 且面积 `rect_area < page_area * 0.5`（防止全页大外框被误提取为表格边框）；
    - **裁剪区求交**：生成的 4 条边框线（上横线、下横线、左竖线、右竖线）与当前 drawing 节点的父裁剪矩形（`clip_bbox`）求交，过滤完全处于视口外的无效边框。
  - **结构约束**：全流程仅消费矢量 drawing 与 clip 信息，不回读 `page.get_text("words")`，不进入 zebra 或 legacy 路径，不影响任何其他既有提取逻辑。
  - **测试与验证**：
    - 在 `tests/test_wired_table_extractor.py` 中新增单元测试 `test_extract_lines_decomposes_stroked_rectangle_borders`（验证描边矩形正确分解 4 条边、填充矩形被过滤）以及端到端回归测试 `test_wired_extractor_finds_tables_on_pdfsam_merge1_page0`；
    - `tests/test_wired_table_extractor.py` 全量 45 项测试 100% 通过（`45 passed`）；
    - 个人征信及无线恢复回归测试 `test_personal_credit_report.py`, `test_unify_wireless_recovery.py`, `test_rule_first_table_detection.py` 共 18 项全部通过；
    - 端到端重新生成可视化结果并核验 `D:\codes\PDFLayoutParser\output\credit_reports_visualize_fixed_20260910\`：
      - `03_PDFsam_merge1.pdf` 第 0 页成功检出 4 个有线表格（Table 1: 2x1 信贷记录；Table 2: 6x5 信息概要明细；Table 3: 2x1 非信贷交易记录；Table 4: 2x1 公共记录），第 1 页检出 2x1 查询记录 + 13x4 机构查询明细；
      - 视觉核验确认网格线对齐贴合无重叠，信息概要精准恢复为 6x5 有线表格（`line_projection`），漏检的 2x1 标题框全部找回。


- 在个人征信报告专用提取器 `PersonalCreditReportTableExtractor` 中增强正文长句段落过滤（`_is_numbered_prose_candidate`），采用按行聚合机制，解决 `PDFsam_merge1.pdf` 及 `PDFsam_merge2.pdf` 中“信用卡-从未逾期过的贷记卡及透支未超过60天的准贷记卡账户明细如下”正文列表被误识别为表格的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/extractors/personal_credit_report.py::PersonalCreditReportTableExtractor._is_numbered_prose_candidate()` 原先仅简单检查独立单元格：`sum(len(text) >= 50 for text in cells) >= 2` 且 `sum(bool(re.match(r"^\d+[.、]", text)) for text in cells) >= 2`。而无线表格结构恢复将长句段落横向切分为两列，导致单单元格字符数均在 35~45 之间，无法满足 `>= 50` 阈值，导致长句段落过滤器失效而被误判为表格。
  - **修复判定与定制隔离**：
    - **严格定制与零通用污染**：段落过滤逻辑仅在 `PersonalCreditReportTableExtractor` 内部定义并生效，通用 `TableExtractor` 及所有通用提取管线 0 修改，严格保证不影响通用逻辑；
    - **查询明细保护守卫**：优先排除包含“查询原因/查询机构/查询日期”或列数 `cols > 2` 的表格，彻底消除对任何页面（包括未来可能出现的跨页查询记录明细）的误伤风险；
    - **按行聚合（Row-Aggregated）检测**：按 `cell.row_index` 聚合该行所有单元格文本后，匹配编号前缀 `^\d+[.、]` 并判断整行长度 `len >= 40` 作为长编号行；
    - 包含“明细如下”正文引导词且长编号行 $\ge 1$，或长编号行 $\ge 2$ 时，判定为正文候选予以剔除。
  - **结构约束**：全流程仅使用提取器已产出的 `Table` 与 `Cell` 元数据，不回读 `page.get_text("words")`，不进入 zebra 或 legacy 路径，不破坏跨页或常规表格的通用结构。
  - **测试与页面验证**：
    - 在 `tests/test_personal_credit_report.py` 中新增单元测试 `test_is_numbered_prose_candidate_rejects_two_column_split_prose` 与端到端回归测试 `test_pdfsam_merge_numbered_prose_not_extracted_as_table`；
    - `tests/test_personal_credit_report.py` 全量 4 项测试全部通过（`4 passed`）；
    - 端到端验证 `PDFsam_merge1.pdf`（2 页）与 `PDFsam_merge2.pdf`（3 页）：第 0 页均成功过滤“信用卡-从未逾期过的贷记卡...”误报正文，保留真实的“信息概要”（8x6）表格；第 1 页完整的“查询记录明细”（分别为 13x4、2x4）100% 正确提取；
    - 同时验证既有 `个人信用报告(本人简版).pdf` 与 `个人征信报告（简版）(1).pdf`，问题一信贷记录有线表格与问题二查询记录明细无线表格提取均完全保持正常。

- 统一中英文无线表格结构恢复核心逻辑，解耦表格区域检测（Detection）与表格结构恢复（Structure Recovery），解决无模型分支（`use_ml_table_detector=False`）下个人征信报告中居中对齐列丢失合并的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/table_extractor.py::_extract_rule_tables()` 原先直接消费 `_detect_rule_candidates()` 产出的未恢复 candidate，而没有像 `_extract_model_tables()` 那样将检测区域送入 `self._wireless_extractor.extract()` 做结构恢复。在纯规则候选生成阶段，旧版 `wireless_table_recovery.py` 中的 `_column_tracks` 硬编码文本按左沿（`bbox.x0`）作为列锚点；而在 `个人征信报告（简版）(1).pdf` 第 4 页中，“查询原因”列文本为居中对齐，文本长短不一导致各行左沿相差达 `63.4pt`，超出中位数容差 `15.17pt` 被切分为 4 个单行碎片并因 `support < 2` 作为噪声丢弃，造成第 4 列轨迹丢失，最终在 `_assign_column` 时全部向左合并入“查询机构”列。
  - **重构与设计**：
    - 将 `_extract_model_tables` 中的完整表格结构恢复流程（包括重叠有线优先匹配、中英文无线表格结构恢复、有线回退和未匹配有线合并）提取为公共方法 `_recover_tables_from_regions(page, regions, wired_tables, page_language)`；
    - `_extract_rule_tables()` 将规则检测出的非有线区域送入 `_recover_tables_from_regions` 进行结构恢复，统一调用 `_wireless_extractor.extract()`（中文调用基于 native-span、投影重叠列带推断的新引擎 `recover_cells_from_region`，英文调用英文策略），使无模型分支与有模型分支共享完全相同的结构恢复能力；
    - 在 `EnglishTableExtractor.extract` 中增加对 `extract_zebra` 及 `extract_general_wireless` 的 `TypeError` 参数容错，提升单元测试与自定义 mock 的健壮性。
  - **测试与验证**：
    - 在 `tests/test_unify_wireless_recovery.py` 中新增单元测试与端到端恢复测试，验证规则分支下个人查询记录明细恢复为 4 列，且“查询机构”与“查询原因”列完全独立；
    - 全量回归测试 `test_unify_wireless_recovery.py`, `test_rule_first_table_detection.py`, `test_wireless_extractor_split.py`, `test_personal_credit_report.py` 共 23 项全部通过（`23 passed`）；
    - 使用 `parse_personal_credit_report(use_ml_table_detector=False)` 重跑 `个人征信报告（简版）(1).pdf`，验证 Page 3 的“机构查询记录明细”（10x4）与“本人查询记录明细”（5x4）均生成为标准的 4 列表格，`source` 为 `wireless_span_recovery`，列头与各数据行均准确对应。

- 调整有线表格提取器 `WiredTableExtractor` 默认垂直线断隙容差 `line_tolerance`（由 2.0pt 调整为 2.3pt），解决 `个人信用报告(本人简版).pdf` 等报告中由于短边框矩形拼接断隙导致信贷记录 3 个表格漏检的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py::_merge_v_lines()` 原先使用 `gap <= self.line_tolerance`（默认 `2.0pt`）。在 `个人信用报告(本人简版).pdf` 第 0 页中，表格边框由小矩形拼接，垂直线段断隙达到 `2.28pt`，超出 `2.0pt` 阈值未被合并；随后 `_find_table_regions()` 连通分量遍历因上下横线未被纵向贯穿而孤立（`len(component_h) < 2`），导致第 0 页信贷记录下的“资产处置信息/垫款信息”(2x3)、“信息概要明细”(6x5) 和“相关还款责任信息”(2x3) 共 3 个有线表格被抛弃。
  - **修复判定与防回归**：
    - 将 `line_tolerance` 默认值调整为 `2.3pt`（同步更新 `WiredTableExtractor`、`TableExtractor` 和 `TableConfig`）；
    - 验证表明 `2.28pt <= 2.3pt` 成功桥接个人信用报告断隙，恢复全部 3 个表格；
    - 同时严格低于 `2.5pt`，防范并保留既有回归测试 `test_merge_v_lines_does_not_connect_adjacent_tables_separated_by_gap`（避免将垂直间隙为 `2.5pt` 的上下相邻独立表格误串联）。
  - **测试与页面验证**：
    - 在 `tests/test_wired_table_extractor.py` 中新增断隙合并单元测试与 `个人信用报告(本人简版).pdf` 3 个表格识别端到端测试；
    - `tests/test_wired_table_extractor.py` 全量 43 项测试 100% 通过（`43 passed`）；
    - 重新运行 `demo.py` 生成 `个人信用报告(本人简版).json`，核验第 1 页成功生成 3 个独立表格（Table 0: 2x3 资产处置/垫款；Table 1: 6x5 信用卡/贷款/其他业务；Table 2: 2x3 为个人/为企业）；
    - 生成可视化图 `output/verify_tol_result/个人信用报告(本人简版)_p0_fixed.png`，视觉核验确认 3 个有线表格红线网格清晰独立，右侧说明文字未被误吸入。

## 2026-09-09

- 优化 Python 页面处理管线的重复资源开销，同时保持现有 API、页面索引、表格结构语义和输出文件契约不变。
  - **根因与调用位置**：`src/hexai_pdf_parser/core/pipeline.py` 原先在同一页面的文本/表格阶段重复读取 PyMuPDF 文本和 drawing，在输出阶段重新打开 PDF 做图片提取、渲染和表格可视化；thread/process 后端还会按页重复创建文档句柄和 `TableExtractor`。页面归一化也可能在多个入口重复执行。
  - **修复判定**：新增 `core/page_cache.py::CachedPage`，仅缓存相同参数的 `get_text()`/`get_drawings()` 读取；`_run_page_pipeline()` 对当前页只做一次 rotation 归一化，并把已有文档/页面句柄传给 `ImageExtractor.extract_page()`、`RenderEngine.render_page()` 和表格可视化。sequential 每次运行复用一个表格提取器，thread 按线程复用独立 PDF 文档和提取器，process 按进程复用文档和提取器；PyMuPDF 文档不跨线程共享。`page_indices` 只转为 set 优化筛选，不改变未选页面的兼容语义。
  - **结构约束**：中文/混合无线表格仍只消费 native span、atom、列带、物理 Cell 和逻辑 Cell；本次没有新增 `page.get_text("words")` 回读，也没有进入 zebra 或 legacy 二次重建路径。debug 模式继续使用独立路径式渲染，避免调试标注污染主页面 PNG。
  - **测试与页面验证**：`tests/test_page_cache.py tests/test_pipeline.py tests/test_pdf_parser.py tests/test_image_extractor.py tests/test_render_engine.py tests/test_table_visualizer.py tests/test_pipeline_debug.py tests/test_text_extractor.py` → `91 passed, 32 skipped`；表格结构专项 256 项通过；直接相关的 `tests/test_table_extractor.py tests/test_rule_first_table_detection.py tests/test_wireless_table_recovery.py` → `123 passed, 1 failed`，唯一失败为既有 hybrid source 期望，与本次参数和资源复用改动无关。`git diff --check`、`compileall` 通过。全仓收集仍有 3 个既有导入错误：缺少 `camelot_stream_demo`、`benchmark_utils.extract_model_profile` 和 `layout_model_utils`。
  - **独立页面输出**：矢量页 `tests/fixtures/page_000_vector.pdf` 输出至 `D:\codes\PDFLayoutParser\output\python_pipeline_optimization_20260909_vector\`，生成页面 JSON、主页面 PNG、表格 PNG，识别 1 张表；扫描页 `tests/fixtures/page_705_scanned.pdf` 输出至 `D:\codes\PDFLayoutParser\output\python_pipeline_optimization_20260909_scanned\`，保持 `scanned`、0 张表并生成页面 JSON/PNG。PNG 视觉核验未发现表格边界、重复文字或正文污染。

## 2026-09-08

- 为个人征信专用入口增加表格检测模型开关：`PersonalCreditReportPipeline` 和 `parse_personal_credit_report()` 默认使用 `use_ml_table_detector=False`；显式传入 `True` 时恢复模型检测。通用 `Pipeline`、`TableExtractor` 及默认正常调用仍保持 `True`。
  - **根因与调用位置**：原 `TableExtractor.extract()` 在规则候选完成后无条件进入 `_extract_model_tables()`；开关现在从 `Pipeline` 贯通到线程、进程 worker 和 extractor。个人征信入口只改变默认值，不改变 `_document_result()` 输出结构。
  - **无模型路径**：仅使用有线线框候选和中文/混合页面的 native-span 无线候选；过滤 `wireless_page_signal` 占位信号，有线 `line_projection` 与重叠无线候选去重并优先保留有线结果。不创建、不调用 `MLTableDetector`，中文/混合表格不进入 zebra 或 words 二次重建路径。无模型结果与模型标签允许因候选边界不同而不同，本次标签验收针对正常模型调用不受影响。
  - **测试**：`tests/test_rule_first_table_detection.py tests/test_pipeline.py tests/test_table_extractor.py` 排除既有 hybrid source 预期后为 `114 passed, 1 deselected`；完整该集合为 `114 passed, 1 failed`，唯一失败为既有 `test_hybrid_wired_table_replaces_full_rowspan_body_before_shifting_footer`（预期 `hybrid_line_span_recovery`、实际 `line_projection`，与本次开关无关）。
  - **正常模型端到端标签验证**：使用 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf` 和默认 `Pipeline(use_ml_table_detector=True)`，输出至 `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_normal_model_20260908\`。共处理 `1023` 页，生成 `1023` 个页面 JSON 和 `1023` 张表格 PNG；表格来源为 `line_projection=1711`、`wireless_span_recovery=445`、`text_alignment=1`、`english_general_wireless=32`、`hybrid_line_span_recovery=10`。与现有黄金标签逐页比较：`passed=1022`、`skipped=1`、`failed=0`、`missing=0`、`extra=0`。
  - **个人征信无模型端到端验证**：使用同一 PDF 输出至 `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_personal_no_ml_20260908_v2\`，共处理 `1023` 页、`2372` 张表格，来源为 `line_projection=1714`、`wireless_span_recovery=648`、`hybrid_line_span_recovery=10`，无 `wireless_page_signal` 泄漏；该结果不与模型黄金标签做逐表等价断言。
  - **demo 验证**：使用 worktree 源码运行 `D:\codes\PDFLayoutParser\demo.py` 成功退出，生成 `D:\codes\PDFLayoutParser\征信解析样例.json`；JSON 包含 `document` 和 `pages`，共 `12` 页。

## 2026-09-07

- 修复 `征信解析样例.pdf` 第 1 页“负债历史”有线表格将页脚 URL、页码误纳入末行的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py::_extract_lines_from_drawings()` 原先直接使用 `page.get_drawings()` 返回的原始窄矩形范围。该 PDF 中竖线原始几何范围为 `y=810.48~823.24`，但 PDF 当前绘制上下文的 `scissor` 裁剪范围只到 `y=813.48`；不可见尾段被当作有效竖线，随后 `_build_cells_for_region()` 的虚拟外边界扩展出尾行，整页 words 中的页脚文字因此被分配进表格。
  - **修复判定**：有线提取器优先读取 `page.get_drawings(extended=True)`，按 PyMuPDF 的 clip 层级恢复当前绘图对象的父裁剪矩形；矩形窄线和轴对齐 `l` 线均先与可见裁剪区求交，再生成水平/竖直候选线。无法提供 `extended=True` 的测试页回退到原有 `get_drawings()` 行为。修复仅修改 `WiredTableExtractor`，未改动 `TableExtractor` 的另一套线提取路径。
  - **结构约束**：不使用页脚文字、固定 y 阈值或下游文字过滤推断表格底边；保留现有线合并、连通拓扑、虚拟边界和合法物理空行处理。
  - **测试与页面验证**：新增 PDF clip 截断回归测试，先确认原实现返回 `823.2422` 的 RED，再验证可见终点为 `813.4832`；`tests/test_wired_table_extractor.py` 为 `33 passed`。相关组合测试为 `119 passed, 1 failed`，唯一失败为既有 `test_hybrid_wired_table_replaces_full_rowspan_body_before_shifting_footer`，与本次有线 clip 修复无关。
  - **端到端验证**：使用 `test_single.py` 对 `征信解析样例.pdf` 页索引 `0、1` 独立输出到 `D:\codes\PDFLayoutParser\output\e2e_visible_lines_20260907_final\`。第 1 页目标表为 `line_projection`、`3x11`、bbox `[28.0,765.8,564.7,810.9]`，仅含 `2025-12` 数据行；第 2 页首行 `2025-09` 保留，表格为 `11x11`。最终 PNG `征信解析样例_page_000_visualized.png` 与 `征信解析样例_page_001_visualized.png` 视觉核验通过，页脚位于表格框外且表格与页脚之间存在空白。

## 2026-09-04

- 修复英文多级表头中垂直折行单元格（如 `Accumulated Deficit`、`Nine Months Ended September 30,`）因横线跨层越界误匹配及非整除共享横线下切碎原子列带导致跨行被拆分的问题（针对 `en_all_table_pages_page_347.pdf` 和 `en_all_table_pages_page_169.pdf`）。
  - **根因与调用位置**：
    1. **横线跨层越界误匹配**：在 `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` 的 `_normalize_headers()` 中，为第 $t$ 层表头匹配下划线时，原容差 `top.bbox.y1 - 3.5 <= y_key <= top.bbox.y1 + 10.0` 未考虑下一层文本的位置。在 Page 347 中，Tier 0 的单列短表头 `Accumulated`（$y_1 \approx 119.37$）搜索下划线时直接穿透并匹配到了 Tier 1 文本底部的整表全局分割线（$y = 125.40$），将其错误升级为 `colspan=2`（覆盖 Col 6..7）；而下一层对应的 `Deficit` 仍为 `colspan=1`。由于两层 `colspan` 不一致，直接破坏了 `is_compact_wrapping` 的前提条件，导致原本应垂直融合成单一单元格的 `Accumulated Deficit` 被横向切分为两行；
    2. **原子跨度排序冲刷破坏**：在构建 `atomic_spans` 时，`lower_spans` 原排序为 `key=lambda s: (s[0], s[1])`。当同一起始列既存在下层的多列原子跨度（如 Col 9..10 的双列），又存在更下层的单列碎片（如 Col 9..9）时，单列排在前面先占满 `covered_indices`，导致原本规整的多列原子跨度被冲刷丢失；
    3. **多表头共享长横线非整除时切碎原子列带**：在 Page 169 中，Tier 1 的三个表头（`Three Months Ended...`、`Nine Months Ended...`、`One Year...`）共享覆盖 Col 1..16（共 16 列）的单条长物理下划线。由于 16 不能被 3 整除，原代码在 `else` 分支直接按表头几何中点做坐标二等分，硬性将 Col 9 切给左侧的 `Months Ended`（使其变成 Col 5..9 共 5 列），破坏了与上一层 `Nine`（Col 5..8 共 4 列）的列对齐，同样破坏了 `is_compact_wrapping`，导致 `Nine` 与 `Months Ended` 被拆成两行。
  - **修复判定与调用位置**：
    1. **下划线层间顶界阻断（Layer-bounded underline matching）**：在 `_normalize_headers()` 中计算下一层非空表头的最小顶部坐标 `max_tier_y_limit = (min(c.bbox.y0 for c in non_empty_next) + 2.5) if non_empty_next else float("inf")`，下划线搜索上界严格约束为 `min(top.bbox.y1 + 10.0, max_tier_y_limit)`，坚决杜绝第 $t$ 层表头跨越到第 $t+1$ 层非空文本下方误认底层横线；
    2. **原子跨度宽区间优先排序**：将 `lower_spans` 排序改为 `key=lambda s: (s[0], -(s[1] - s[0]))`，确保同一起始列优先保留最宽的原子块，保护多列原子单元格不被细碎单列冲散；
    3. **原子块保整几何分配（Atomic-span preserved assignment）**：当多个表头共享同一长横线且列数不可整除时，优先识别下层完全包含在长横线内的 `covered_atoms`；若能完整拼成列区间，则以各原子块的几何中心为不可分割单位，按与表头中心的最小距离整块分配给对应表头（Page 169 中 Col 1..4、Col 5..8、Col 9..16 完美对齐），杜绝切碎原子单元格。
  - **结构约束**：只基于几何、拓扑与通用原子块连续性决策，严禁硬编码 "Accumulated"、"Deficit"、"Nine" 或 "Months Ended" 等业务文字；保持每个逻辑槽位唯一占用与 0 槽位冲突。
  - **测试与页面验证**：
    - 新增独立测试文件 `tests/test_header_wrapping_page_347_169.py`，包含 Page 347 `Accumulated Deficit` 跨2行融合验证与 Page 169 `Nine Months Ended September 30,` 跨4列2行融合验证（2 项全部通过 `2 passed`）；
    - 运行全量关联测试 `test_page_347_structure.py`、`test_header_upward_merge.py`、`test_financial_header_normalizer.py` 共 9 项全部通过；
    - 页面级独立重跑验证：
      - `output/verify_page_347/`：14 行 × 11 列，`Accumulated Deficit` 融合为 `rowspan=2, colspan=1` 的单一单元格，0 槽位冲突；
      - `output/verify_page_169/`：5 行 × 17 列，`Nine Months Ended September 30,` 融合为 `rowspan=2, colspan=4` 的单一单元格，0 槽位冲突，可视化网格线完全贴合。


- 修复英文无线/斑马纹表格多级表头中左上角首列被垂直割裂，以及 `Common Stock` 未拆成 Shares 与 Amount 双列导致数据粘连（`$75,968`、`77,09277` 等）的问题（针对 `en_all_table_pages_page_347.pdf`）。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` 的斑马纹提取路径 `_process_zebra_group()` 中，原逻辑在列检测 `_detect_columns()` 之前过早调用了 `_handle_dollar_signs()`，将独立的 `$` 符号与紧随其后的数字合并为单一词元，不仅破坏了列投影直方图的独立字间隙，且导致后续货币分界线微调函数 `_adjust_columns_for_currency()` 遍历时因无法匹配 `w[4] == "$"` 而失效。同时，`_process_zebra_group()` 遗漏了与 `extract_general_wireless()` 一致的 `_prune_phantom_columns()` 和 `_adjust_columns_for_currency()` 调用链；
    2. 在 `_detect_columns_from_header_underlines()` 中，`Common Stock` 股票数右端（255.64pt）与金额 `$` 左端（257.14pt）间隙仅 1.5pt，且表头词 `Common` 跨越至 266.85pt 充当了“桥梁”，将两列投影粘连。而下划线匹配容差 `top.bbox.y1 - 1.5` 因同行相邻词（如 `Accumulated` y1=119.37）最大字高过大，导致 `119.37 - 1.5 = 117.87 > 117.80`，错过了真实的下划线；
    3. 在 `_normalize_headers()` 末尾物化空单元格时，左上角科目区域（Col 0）在多级表头各层均为空槽位，原代码仅将其物化为单独的 `1x1` 空单元格，导致第 0 行与第 1 行交界处出现横向割裂线，使表头视觉上被横切为两行。
  - **修复判定与调用位置**：
    1. **斑马纹列检测对齐**：在 `_process_zebra_group()` 中调整调用顺序，使用包含表头与数据行原始坐标的 `all_words_for_cols` 先执行 `_detect_columns()` -> `_prune_phantom_columns()` -> `_adjust_columns_for_currency()`；分界线确定后再对数据行执行 `_assign_words_to_zebra_rows()` 与 `_handle_dollar_signs()`；
    2. **放宽下划线容差并激活微调**：在 `_normalize_headers()` 中将表头下划线接触面容差从 `- 1.5` 放宽到 `- 3.5`（`top.bbox.y1 - 3.5 <= y_key`），确保两段下划线稳定纳为双列；并在 `extract_general_wireless` 与 `_process_zebra_group` 中激活调用 `_adjust_columns_for_currency()`，精准将分界线自 268.60 重定位到 256.39pt（$75,968$ 与 $\$$ 之间）；
    3. **表头空槽位自适应向下跨行物化**：在 `_normalize_headers()` 物化空槽位时，检查从当前行向下连续未被占用的槽位及层间物理横线阻断（`eff_empty_rowspan`），使左上角 Col 0 自动生成 `rowspan=2, colspan=1, text=""` 的完整大槽位，消除垂直与水平切割感。
  - **结构约束**：只基于几何、拓扑与通用货币分界特征决策，不硬编码具体业务文字；保持每个逻辑槽位唯一占用与 0 槽位冲突。
  - **测试与页面验证**：
    - 新增测试 `tests/test_page_347_structure.py`，参数化覆盖 `extract_zebra`、`extract_general_wireless` 以及端到端 `extract` 三大入口，验证 Col 0 `rowspan=2`、Common Stock `colspan=2`、APIC `rowspan=2`、以及 `PHOT`、`June 30`、`September 30` 行数据列精准切分无粘连，3 项测试全部通过（`3 passed`）；
    - 既有测试 `test_header_upward_merge.py` 与 `test_financial_header_normalizer.py` 全部通过；
    - 页面级独立运行重跑至 `output/single_page_347_fix/`，核对 `output.json` 与 `en_all_table_pages_page_347_visualized.png`：表格结构由原先错乱的 10 列提升至规整的 11 列（14 行 × 11 列，147 个 Cell），置信度 0.97，视觉渲染网格完全闭合、表头及数据行对齐精准。

- 修复英文多级表头中因局部下划线全局行切分导致无母节点单列表头被撕裂并残留大量空单元格的问题（针对 `en_all_table_pages_page_075.pdf` Table 1 与 Table 2）。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py` 的 `_detect_header_rows()` 中，物理下划线 `y = 144.53` 实际仅覆盖 Col 1~2（用于分隔 `Three Months Ended September 30,` 与 `2023/2024`），但算法将其无差别视作贯穿整表的全局分割线，将右侧原本连续的单列叶子表头（如 `Constant Currency Revenues`、`Less FX Effect`、`As Reported`）错误地横向切分为 Tier 2 与 Tier 3。
    2. 在 `_normalize_headers()` 中，原先仅支持上下两层均有内容的垂直折行拼接（`is_compact_wrapping`），或者从首层至底层全空的提升（`all_upper_empty`）。当上层（Row 0 或 Row 1）存在大表头、且某列在中间行无母节点（`grid[t][ci] is None`）时，算法缺少自底向上的跨行填充逻辑，导致 Col 3、5、6、7 滞留在底层，而在 Row 2 留下大片未合并的空白槽位。
  - **修复判定与调用位置**：
    在 `_normalize_headers()` 的折行规整后引入自底向上（Bottom-Up）的无母节点单列表头向上合并机制：
    1. **判定条件**：当单列叶子表头单元格满足 `c_bot.colspan == 1 and c_bot.text.strip()`，其正上方槽位为空（`grid[t][ci] is None`），且上方所在层存在其他非空兄弟表头（确保属于有效表头行），并且在该列的宽度区间内两层交界面处无物理水平线阻断（`not has_col_line`）时，确认为无母节点的连续单列表头；
    2. **两层交界判定保护**：水平线阻断判定严格限定在两层接触面范围（`c_bot.bbox.y0 - 3.5 <= ly <= c_bot.bbox.y0 + 2.0`），防止上一层的大标题底线或下层的数据底线误判为层间阻隔；
    3. **向上扩展合并**：将该单元格提升至第 $t$ 层，并在网格中自适应累加计算 `rowspan`（Table 1/Table 2 中 Col 3/4 向上贯通跨 3 行，Col 5/6/7/8 跨 2 行），完美消除所有空槽位。
  - **结构约束**：只基于几何与网格拓扑决策，不硬编码任何具体业务文字，保持每个逻辑槽位唯一占用与无冲突。
  - **测试与页面验证**：
    - 新增针对性测试套件 `tests/test_header_upward_merge.py`（包含三层大标题正例、带横线阻断拒绝合并反例、以及真实 Page 075 集成测试），3 项测试全部通过（`3 passed`）；
    - 全量既有模型及无线表格测试 71 项全部通过；
    - 单页独立验证输出目录：`C:\Users\92410\Desktop\git\hexai_pdf_parser\src\hexai_pdf_parser\data\en_all_pages\`，已重新导出并核对 `en_all_table_pages_page_075.md`、`en_all_table_pages_page_075.json` 以及可视化图片 `en_all_table_pages_page_075_visualized.png`，Table 1 与 Table 2 蓝线网格完全对齐贴合，无多余空单元格，结构规整严密。

## 2026-09-03


- Page 979 最终验证产物已归档至 `D:\\codes\\PDFLayoutParser\\output\\page_979_fixed_width_alignment_corridor_20260903_final_verify\\`。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `1002` 中文无线表格（关联方应收款项续表）因正文首列全空导致表头叶子列带丢失、进而引发同槽位冲突导致整表漏检的问题。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/wireless_structure/columns.py` 的 `infer_column_bands()` 中，列带候选聚类要求 `len(component) >= 2 and len(y_support) >= 2`。Page 1002 为跨页续表，首列“项目名称”在正文 22 行中全部为空槽位（继承自前一页），导致在 $x \in [88.0, 140.0]$ 整个区域内仅有表头唯一的 atom“项目名称”，未能生成第 0 列列带，全表仅推断出 5 个列带。
    2. 在 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `rescue_header_only_leaf_bands()` 中，原先识别孤立叶子表头的条件 `covered_ids == stable_ids and candidates` 仅支持单行表头；由于本表为多级表头，“项目名称”所在的 Level 1 仅包含“项目名称”与“关联方”，`covered_ids` 仅有第 1 列带，不等于全量稳定列带集合，且 `len(candidates) == 1 < 2`，导致救援分支未命中，首列被遗漏。
    3. 在后续 `columns.py` 的 `assign_column()` 中，“项目名称”因无重叠列带被就近错分给相邻的 Band 1（“关联方”列），与同行（$y \approx 108.6$）的“关联方”在物理槽位 `(Row 2, Col 1)` 产生重叠占用冲突（`R2C1 conflict: T1/T2`）。冲突无法消除触发防御性抛弃，函数返回空网格，导致 ML 模型以 0.9789 高置信度检出的上半部 25 行无线大表整表丢失。
  - **修复判定与调用位置**：
    在 `header_topology.py` 的 `rescue_header_only_leaf_bands()` 中扩展边界叶表头（boundary leaf header）救援机制：
    1. 当表头某一行不存在跨列父标题（`has_parent == False`）且存在位于所有稳定列带最左外侧（`c.x1 <= min_stable_x0`）或最右外侧（`c.x0 >= max_stable_x1`）的候选 atom，且当前行覆盖了对应的边界稳定列带（`min_stable_id in covered_ids` 或 `max_stable_id in covered_ids`），且表头区域所有层联合覆盖了全量稳定列带集合时，确认为合法的边界叶子列候选。
    2. 要求候选列在表头其他 level 的垂直投影范围内无遮挡冲突（`other_level_atoms == []`），且与左右相邻列带及同行相邻元素均保持充分几何间距（$\ge \text{minimum\_gap} = \max(8.0, 1.25 \times \text{line\_height})$）。
    3. 严格禁止纯数字、占位符、附注编号或结构单位作为边界叶表头救援。
  - **结构约束**：全流程严格只消费 native span、atom、列带、物理 Cell 和逻辑 Cell；不回读 `page.get_text("words")`，不进入 zebra 或 legacy 二次重建，不硬编码业务表头文字；遵循 0 Occupancy Conflict 契约与独立空槽位物化。
  - **测试与页面验证**：
    - 在 `tests/test_wireless_structure_header_topology.py` 中新增多级表头最左端叶子列救援正例、窄间距反例及纯数字反例；
    - 新增页面集成测试 `tests/test_page_1002_table_recovery.py`，锁定无 words 守卫、Table 1 为 25 行 × 6 列（140 个 Cell 覆盖、0 槽位冲突、表头跨度精准、首列空槽位独立物化）、Table 2 为 7 行 × 4 列；
    - 全量无线结构测试 169 项 100% 通过（`169 passed`）。
    - 独立重跑 Page 1002 完整流水线至新输出目录 `output/fix_page_1002_sparse_header_leaf_band_20260903/`：成功导出 `pages/page-1002.json`、`pages/page-1002.md` 和可视化 PNG `tables/page-1002.png`，视觉核验确认 Table 1（`25x6`，置信度 0.98）与 Table 2（`7x4`，置信度 0.97）红框完全闭合、蓝线网格对齐贴合、22 行往来数据与左侧空单元格规整连续无错位。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `988`、`989` 中文无线表格将公司组间间距恢复为 5 条贯穿空列的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/columns.py::_compatible()` 对占位符与数值的同列兼容同时要求覆盖占位符宽度的 75% 且绝对重叠不少于 4pt。两页右对齐短横线 `-` 的 bbox 宽度仅为 2.064 至 3.764pt，即使与同列金额 bbox 100% 重叠也无法满足 4pt 下限；重复短横线因此在 `infer_column_bands()` 中形成 5 条独立窄带。`refine_leaf_bands()` 随后将六个公司宽带各拆成两个金额叶子列，结果从正确的 13 列膨胀为 18 列。列分配平局时短横线回到靠前的正常金额列，窄带本身没有内容，最终被 `materialize_empty_cells()` 逐行物化为空 Cell，所以 PNG 中空列位于短横线右侧。
  - **修复判定**：占位符与数值的列带兼容仅要求实际水平重叠至少覆盖占位符 bbox 宽度的 75%，移除不适用于窄字形的固定 4pt 下限。Page 988/989 的目标短横线覆盖率为 100%，可并入对应金额组件；Page 944 既有跨列尾部空白擦碰覆盖率约为 45.6%，继续被拒绝。普通 atom 的兼容条件、叶子列细化、表头跨度、occupancy conflict 检查和空槽位物化保持不变。
  - **结构约束**：修改只发生在 native-span 的 atom 列带推断阶段；页面结构验证使用 `NoWordsPage` 守卫确认未调用 `page.get_text("words")`，未进入 `extract_zebra()` 或 legacy 二次重建。空槽继续按独立 `1x1` Cell 物化，每个逻辑槽位保持唯一占用。
  - **测试与页面验证**：先新增宽度 3.764pt、与金额 100% 重叠的短横线正例并确认 RED 为 2 个列带，再以最小修改转 GREEN；与 Page 944 的 45.6% 擦碰反例及列带、表头拓扑、恢复器相关测试合计 `77 passed, 1 skipped`，skip 为 worktree 未复制本地大 PDF。扩展测试为 `578 passed, 40 skipped, 3 failed`，三个既有失败分别为缺失 `camelot_stream_demo`、LayoutBuilder 的 IoU=0.5 边界行为及已记录的 hybrid source 预期，均不涉及本次修改；默认全仓收集另有缺失 `camelot_stream_demo`、`layout_model_utils` 和 `benchmark_utils.extract_model_profile` 的 3 个既有导入错误。使用最终 worktree 源码直接验证 Page 944/988/989，三页均为 13 列、无整列为空、occupancy conflict 为 0，槽位覆盖分别为 `117/117`、`260/260`、`117/117`。Page 988/989 完整单页管线独立输出至 `D:\codes\PDFLayoutParser\output\fix_page_988_989_placeholder_columns_20260903\page-988\` 和 `...\page-989\`：两页均为 1 张 `wireless_span_recovery` 表，分别为 `20x13`（240 个 Cell）与 `9x13`（97 个 Cell），六个公司父表头均为连续 `colspan=2`。最终 PNG 分别为 `page-988\tables\page-988.png`、`page-989\tables\page-989.png`；视觉核验确认 5 条贯穿空列消失，短横线保留在金额列，表格边界、组内/组间线框及相邻公司组均无明显异常。
- 验证 `fix/zh_all_table_pages.pdf` 页面索引 `979` 中文无线表格（子公司情况表）在“固定宽度右列 + 左侧多样金额/地点”场景下的恢复结果，确认 Page 979 的 `注册资本`、`主要经营地`、`持股比例%` 等列已恢复为稳定的 8 列结构。
  - **根因与调用位置**：
    1. `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `_has_alignment_corridor_veto()` 原先要求对齐走廊两侧都出现 opposite edge variation，才把该走廊视为独立列证据。Page 979 中，左侧 `注册资本` 金额列随 `1,000.00 / 2,000.00 / 15,000.00 / 52,000.00` 等值变化，能满足 opposite-edge variation；但右侧 `主要经营地` 地点列在 `深圳 / 惠州 / 九江 / 南宁` 等支持行里宽度近似等宽，`x0/x1` 都基本不变，导致旧条件整体失败。若缺少文本多样性证据，`build_text_runs()` 在 `if can_join and not _has_alignment_corridor_veto(groups[-1], span, rows)` 处会把同一视觉行的“金额 + 地点”错误拼成同一个 atom，进而在后续列带恢复中把两列吸并。
  - **修复判定与调用位置**：
    1. `text_runs.py` 新增 `_has_diverse_text_values()`，对支持行文本做去空白去重；当同一对齐走廊一侧累计出现 `>= 3` 个不同文本值时，即使该侧边界不明显变化，也视为存在独立字段证据。
    2. `_has_alignment_corridor_veto()` 在保留原始对齐走廊、支持行数量和 opposite-edge variation 约束的前提下，对“边界稳定但文本多样”的固定宽度列补入 veto 条件，避免 Page 979 这类“右列宽度稳定、左列金额多样”的场景被误并。
    3. `build_text_runs()` 继续保持 veto-only 语义：上述判断只会阻止 `groups[-1].append(span)` 发生，不会主动制造新的 join，也不会改变 native span -> atom 之后不回读 `page.get_text("words")` 的结构恢复约束。
  - **结构约束**：本页结构恢复仍严格只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回退 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或其他 words 二次重建路径；跨度调整后继续满足“每个逻辑槽位恰好唯一占用”与独立空槽位物化契约。
  - **测试与页面验证**：
    - 复跑 `tests/test_wireless_output_order.py tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_recoverer.py`，结果为 `56 passed, 5 warnings`，仅保留既有的 PyMuPDF / SWIG 弃用警告；
    - 使用当前 worktree 模型 `src/hexai_pdf_parser/ml/table_detector_model/best.onnx` 独立重跑页面索引 `979` 至 `D:\codes\PDFLayoutParser\.worktrees\fix-page-979-alignment-corridor\output\page_979_fixed_width_alignment_corridor_20260903\`；
    - 页面成功恢复出 `1` 张 `wireless_span_recovery` 表格，结构为 `24x8`、`177` 个 Cell、bbox=`[71.5, 90.9, 519.0, 756.6]`、置信度 `0.9807`；
    - `持股比例%` 在结构化结果中恢复为 `R0C5` 的 `rowspan=2, colspan=2` 父表头，下方 `直接/间接` 两个叶子列独立存在；其余首列表头保持 `rowspan=3`；
    - 结构审计确认 `192/192` 个逻辑槽位全部唯一覆盖，`0` 缺失、`0` occupancy conflict、`0` 越界，空单元格共 `17` 个；
    - 独立视觉验收已通过：最终 `tables/page-979.png` 中仅有 `1` 张 Table 1（`wireless_span_recovery`，`24x8`），`注册资本` 与 `主要经营地` 之间的独立列界贯穿表头和正文，`持股比例%` 仅覆盖 `直接/间接` 两列，bbox 未吸收上方公司名、`财务报表附注`、年度说明、下划线或底部页码 `96`，正文换行与空值合理，且无网格重叠、断裂、相邻误并或文字越界；对应结构化结果 `pages/page-979.json`、`pages/page-979.md` 与 PNG 一致。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `969` 中文无线复合表头表格（Table 2“资产负债表中归属于母公司的其他综合收益”、Table 3“利润表中归属于母公司的其他综合收益”）漏检与结构列塌陷问题。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/wireless_structure/columns.py` 的 `infer_column_bands()` 中，原过滤宽表头的条件 `_is_wide_header()` 写死了宽度比例 `item_width >= width * 0.28`。Table 2 和 Table 3 的父表头“本期发生额”（宽度约 52.8pt，占区域总宽仅 12.5%）未被过滤进入连通分量合并。由于“本期发生额”横跨左右两个独立叶子列轨道，在连通图无差别传递闭包合并中将本应独立的叶子列带桥接为一个宽列带（Band 3），导致 Table 2 的“税后归属于母公司”与“减：前期计入...”被吸入同一列带。
    2. 在 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `_is_numeric_body_atom()` 中，原先使用 `any(char.isdigit() for char in item["text"])`。财报表头中广泛存在的列序号（如 `（1）`、`（2）`）与计算公式（如 `（4）=（1）+（2）-（3）`、`（5）=（1）-（2）-（3）-（4）`、`（1）-`）均因包含数字被误判为“正文数值”，导致 `_header_cutoff()` 在表头公式处过早截断（Table 2 截断于 y=297.1，Table 3 截断于 y=524.8），使得大量表头叶子文本落入正文区间。同时，正文首行若为全占位符（`-`）未被计入正文范围。
    3. 在 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `_infer_centered_parent_span()` 中，原先只检查跨度宽度比例与中心差值，未检验候选跨列单元格是否在几何上实质覆盖所提议跨度的两侧边界列带。导致完全位于单列内的叶子表头“税后归属于母公司”被误扩散为跨 2-4 列，与同行的“减：前期计入...”产生槽位占用冲突（Occupancy Conflict），最终触发整表抛弃返回空表。
  - **修复判定与调用位置**：
    1. 在 `columns.py` 中引入拓扑跨列表头判定 `is_spanning_header(atom, atoms, region)`：在表格上部 45% 区域内，若 atom 下方存在至少两个水平互斥（无水平交集）且被该 atom 实质重叠（两端重叠均 >= 5.0pt）的独立文本轨迹，判定该 atom 为跨列父表头，在 `infer_column_bands()` 候选池中予以排除，防止多米诺式桥接合并叶子列。
    2. 在 `header_topology.py` 中增加 `_is_header_index_or_formula()` 判定：对带括号的列序号（如 `（1）`）或带等号/运算符的表头公式（如 `（4）=（1）`、`（5）=`、`+（2）-`）予以识别，排除在正文数值原子之外；同时排除带列序号后缀的中文长标题。
    3. 在 `header_topology.py` 的 `_header_cutoff()` 中，当首个数值正文行上方紧邻一行由连续占位符（`-`）构成的记录时，将正文边界向上延伸覆盖该占位符行。
    4. 在 `header_topology.py` 的 `_infer_centered_parent_span()` 中增加几何物理覆盖守卫：要求提议跨列的 atom 必须物理触达跨度起始列带与终止列带（`atom["bbox"][0] <= first["x1"] and atom["bbox"][2] >= last["x0"]`），严禁将单列内部的叶表头误扩成跨多列。
  - **结构约束**：全流程严格基于 native span、atom、列带、物理 Cell 和逻辑网格拓扑决策，严禁回读 `page.get_text("words")`，不回退 zebra 或 legacy 二次重建，不硬编码业务表头文字；遵循 0 Occupancy Conflict 契约与独立空槽位物化。
  - **测试与页面验证**：
    - 新增针对性单元与集成测试 `tests/test_page_969_spanning_headers.py`（包含 Table 2 恢复为 5 列且“本期发生额”恢复 colspan=2 正例、Table 3 恢复为 6 列且占位符列完整独立分立正例、以及 `is_spanning_header` 单列叶表头/正文标题不误判反例）；
    - 全量 190 个无线表格测试套件 100% 通过（`190 passed`）。
    - 独立重跑 Page 969 完整流水线至新输出目录 `D:\codes\PDFLayoutParser\.worktrees\fix-page-969-parent-span\output\fix_page_969_20260903\`，成功提取出全部 3 张表格：
      - Table 1（资本公积）：`5x5`，source=`wireless_span_recovery`，置信度 0.967；
      - Table 2（资产负债表其他综合收益）：`8x5`，36 cells，source=`wireless_span_recovery`，置信度 0.978，“本期发生额”精准赋予 `[R0C2, rs=1, cs=2]`，下方两个叶子列分立，4 行正文数值与横杠列完全对齐；
      - Table 3（利润表其他综合收益）：`11x6`，65 cells，source=`wireless_span_recovery`，置信度 0.979，彻底解决列合并与 `--` 畸变问题，6 列完全分立且 4 行数据完整；
      - 可视化 PNG `page-969-visualized.png` 经视觉核验，三个表格边界完全闭合、网格划分精确贴合、文字与框体无误并无错位。
- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `987` 中文无线表格因混合单行/折行叶表头未压缩到同一逻辑行而产生三层伪表头的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/grid.py` 的同列互斥规则正确地把竖向排版的“间/接”保留为两个物理行，后续 `merge_multiline_cells()` 将其组合为跨物理行叶标题；但 `src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py` 的 `_wrapped_leaf_header_span()` 只接受起始行上全部 Cell 都是折行叶标题的情况。本页同一物理行还包含前四个纵跨表头的单行标题，因此该区间未被压缩，“直接”和“间接”落在不同逻辑行；`merge_header_spans()` 随后无法证明“持股比例(%)”与两个连续叶子列形成完整 `1:2` 拓扑，前四列和末列的 `rowspan` 恢复也连带失败，空槽物化最终生成 9 个伪空表头格，使正确的 `6x7` 变成 `7x7`、45 个 Cell。
  - **修复判定**：在 `logical_grid.py` 新增 `_grouped_mixed_leaf_header_span()`，只在候选为表头内单列 `multiline_cell`、上方存在唯一且恰好覆盖两个连续列的 `colspan=2` 父 Cell、父列区间内恰有两个唯一单列叶标题且完整覆盖父列、候选区间内没有额外跨列 Cell、父列竞争占位或外部同列重复标题时，才返回待压缩物理行区间。任一条件不成立即保持原逻辑行；不放宽 `grid.py` 的物理行聚类，不硬编码业务文字。压缩后继续复用现有 `merge_header_spans()`、occupancy conflict 检查和逐槽空单元格物化。全流程只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不进入 zebra 或 legacy 路径。
  - **测试与页面验证**：先新增 Page 987 形态正例并确认逻辑行仍为 `[[1,2],[3],[4,5],[6]]`、真实页仍为 `7x7` 的 RED，同时新增缺少完整二叶子证明的拒绝反例；实现后新增测试为 `3 passed`，逻辑网格、折行表头、合并单元格和表头拓扑相关测试为 `110 passed`，Page 435/436、987、1014 真实页面回归为 `4 passed`。使用最终代码独立重跑页索引 `987` 至 `D:\codes\PDFLayoutParser\output\page_987_mixed_leaf_header_fix_20260903\`：1 张 `wireless_span_recovery` 表，bbox `[84.2,91.1,506.2,362.5]`，恢复为 `6x7`、36 个 Cell，42/42 槽位唯一覆盖、0 冲突、0 空表头格；结构化结果为 `pages\page-987.json`，最终 PNG 为 `tables\page-987.png`。视觉复核确认表头恢复为两层，“持股比例(%)”正确覆盖“直接/间接”，前四列和末列无伪横线，四行正文、表框和相邻文本无回归。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `469` 中文无线表格（上年年末余额续表）因单行数据续表导致表头下界推断失效、进而引发叶子列拆分冲突整表漏检的问题。
  - **根因与调用位置**：在 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `_header_cutoff()` 中，原先识别数值正文行作为表头下界的条件硬编码要求 `len(numeric_body_levels) >= 2`（至少两行数值行）。当跨页续表尾部仅有 1 行合计数据行（包含“金融负债和或有负债合计”及 5 列金额数值）时，`len(numeric_body_levels) == 1` 导致未能识别正文行；随后的最大空白回退逻辑因本页包含父子表头大间距（20.04pt），导致 `minimum_gap = median_gap * 2.0 = 40.08pt` 错杀了真实的表头正文间距（33.82pt），使 `_header_cutoff` 返回 `None`。由于缺少表头分界线，`refine_leaf_bands()` 放弃将跨列父表头“上年年末余额”桥接的第 3、4 列带拆分为独立叶子列，导致“一年至三年以内”与“三年至五年以内”落入同一网格槽位 `R1C3`，触发 `occupancy conflict` 后整表抛弃。
  - **修复判定与调用位置**：在 `header_topology.py` 的 `_header_cutoff()` 中完善单行多数值数据续表的判定：统计每个候选层级中非结构化数值字段数量，当 `len(numeric_body_levels) >= 2` 或 `len(numeric_body_levels) == 1 and numeric_row_counts[numeric_body_levels[0]] >= 2` 时，均确认为合法的正文行起点并计算表头分界。单个字段的偶发数字或附注编号继续被保护不误判。
  - **结构约束**：全流程严格基于 native span、atom、列带与逻辑网格拓扑决策，不回读 `page.get_text("words")`，不回退 zebra 或 legacy 路径，严格遵循 0 Occupancy Conflict 契约与严格空槽位物化。
  - **测试与页面验证**：新增 `tests/test_page_469_table_recovery.py`，锁定无 words 守卫、2 张表格完整恢复、Table 1 为 3 行 x 6 列（13 个 Cell 覆盖、0 冲突、父表头 colspan=2、独立表头 rowspan=2）、Table 2 为 5 行 x 3 列；在 `tests/test_wireless_structure_header_topology.py` 中新增单行多金额数据行正例及单表头数字注释反例。无线结构与相关专项共 `87 passed, 1 skipped`。页面索引 `469` 独立重跑至 `output/page_469_continuation_table_recovery_20260903/`：成功导出 `pages/page-469.json`、`pages/page-469.md` 和可视化 PNG `tables/page-469.png`，视觉核验确认顶部续表与下部表格均完整框选标注，网格规整无重叠。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `464` 中文无线表格（政府补助明细表）因占位符与金额连带 Span 拆分间距未计空格宽度导致整表漏检的问题。
  - **根因与调用位置**：在 `src/hexai_pdf_parser/tables/wireless_structure/span_chain.py` 的 `_split_packed_numeric_fields()` 中，原先计算空白处相邻字符间距时采用切片循环 `gaps = [char_boxes[right]["bbox"][0] - char_boxes[right - 1]["bbox"][2] for right in range(whitespace_start, whitespace_end + 1)]`。在 PyMuPDF 原生字符流中，空格字符自身带有独立字符框（例如 Page 464 合计行中空格字符 bbox 宽度达 2.41pt）。原切片循环分别计算了占位符 `'-'` 与空格之间（0.00pt）以及空格与后续数字 `'7'` 之间（0.71pt）的间隙，两者均小于阈值 `gap_limit = max(1.5, 10.56 * 0.18) = 1.90pt`，错误地排除了空格字符本身的几何宽度，导致实际达 3.12pt 的跨列物理空白未被识别，`'-- 74,956,072.71'` 原样返回未拆分。未拆分的复合 Atom 导致下游 `infer_column_bands()` 将第 5 列（其他变动）与第 6 列（期末余额）合并为一个宽列带，引发 `(Row 3, Col 5)` 等多个网格槽位占用冲突（occupancy conflict），`recover_cells_from_region()` 触发防御性抛弃返回空结果，使 ML 模型以 0.9637 置信度检出的顶部 4x7 表格整表丢失。
  - **修复判定与调用位置**：在 `span_chain.py` 的 `_split_packed_numeric_fields()` 中，引入前序实体字符右沿到后续实体字符左沿的完整跨空白几何距离 `total_gap = char_boxes[whitespace_end]["bbox"][0] - char_boxes[whitespace_start - 1]["bbox"][2]`，只要 `total_gap >= gap_limit` 或局部残差间隙 `max(gaps) >= gap_limit`，均判定达到拆分条件。
  - **结构约束**：修复仅发生在 native span 规范化输入阶段，全流程严格只消费 native span、atom、列带、物理 Cell 和逻辑 Cell；不回读 `page.get_text("words")`，不进入 zebra 或 legacy 二次重建，不硬编码业务表头文字；继续遵循 0 occupancy conflict 契约与严格空槽位物化。
  - **测试与页面验证**：在 `tests/test_packed_numeric_fields_split.py` 中新增空格宽度主导间距正例（先确认 RED 再转 GREEN）与极窄间距不误拆反例；新增页面集成测试 `tests/test_page_464_table_recovery.py`，锁定无 words 守卫、7 列分立、4 行 x 7 列 28 个 Cell 100% 槽位唯一覆盖；相关无线结构、数值拆分与页面集成测试共 `91 passed`。页面索引 `464` 独立重跑到 `D:\codes\PDFLayoutParser\output\fix_page_464_packed_numeric_split_20260903\`，完整提取出全部 2 张表格（Table 1 为 `4x7`、28 个 Cell；Table 2 为 `26x4`、104 个 Cell）；最终可视化图 `zh_all_table_pages_page_464_visualized.png` 经视觉核验，顶部表格 7 列完全分立，数据行与合计行 `--` 及金额绿框精准贴合，网格完整连续。


- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `471` 中文无线表格（母公司情况表）因多列折行叶表头被拆分为多层物理行导致顶部产生多余空单元格与伪 `rowspan` 的问题。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py` 的 `_wrapped_leaf_header_span()` 中，原先针对单列折行叶表头硬编码限制物理首行只能有恰好 1 个非空单元格起点（`len(started) == 1`）。当表头存在 2 列或更多列同时折行跨行（例如第 471 页第 4 列“注册资本\n(万元)”与第 6 列“母公司对本公司\n表决权比例\n（%）”首行均偏高并在物理行 1 启动）时，`len(started) == 2` 导致该判定失效返回 `None`，物理行 1 未能折叠进下一物理行，保留为独立的逻辑表头行。
    2. 在 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `build_text_runs()` 中，TextRun 的加粗状态原先直接取首个 Span 的 `group[0]["bold"]`。由于西文括号 `(` 在 PDF 中使用了带粗体的西文字体（`Arial Narrow,Bold`），导致“`(万元)`”整体被打上 `bold=True`，与未加粗仿宋中文“`注册资本`”样式冲突，阻断了前期换行合并。
    3. 后续网格物化 `materialize_empty_cells()` 遂在保留下来的逻辑行 1 中，对起点位于逻辑行 2 的列 0、1、2、4 补齐了 4 个空单元格 `<td></td>`，并将列 3 和列 5 赋予 `rowspan=2`。
  - **修复判定与调用位置**：
    1. 在 `logical_grid.py` 中泛化折行叶表头物理行压缩逻辑：当物理行 `start` 上启动的所有非空单元格 `started` 全部为合法的单列多行叶表头（`colspan == 1`、`col_start == col_end`、`row_end > start`、`merge_kind == "multiline_cell"`、在 `header_cutoff` 范围内），且 `start` 行不存在任何单行独立表头（`row_start == row_end`）或多列父表头（`colspan > 1`），且在后续物理行存在同层兄弟叶列表头时，将 `[start, max(row_end)]` 识别为可压缩折行表头区间，统一折叠至同一逻辑行。包含真正多级父表头或单行独立表头的行坚决拒绝折叠。
    2. 在 `text_runs.py` 中优化 TextRun 的加粗计算：当 TextRun 包含多个 Span 且存在非空 CJK 字符时，`run["bold"]` 取字符数最多的 CJK Span 的加粗状态，避免单个西文开括号等标点符号的字体元数据污染整体文本的加粗属性。
  - **结构约束**：全流程严格基于 native span、atom、列带与逻辑网格拓扑决策，不回读 `page.get_text("words")`，不回退 zebra 或 legacy 路径，继续保持 0 Occupancy Conflict 契约与严格空槽位物化。
  - **测试与页面验证**：新增 `tests/test_wrapped_leaf_headers.py`，覆盖多列折行叶表头折叠正例、真正多级父表头保护反例、首行独立单行表头保护反例及西文括号粗体隔离正例（`4 passed`）；全量无线结构测试 150 项 100% 通过（`150 passed`）。使用完整单页流水线重跑页面索引 `471` 至独立输出目录 `output/fix_page_471_header_leaf_20260903/`：Table 1 完美恢复为标准的 2 行 × 6 列（1 行表头 + 1 行数据，12 个 Cell 覆盖 12/12 槽位，0 空单元格，0 Occupancy Conflict），表头 6 个单元格均为 `rowspan=1`；Table 2（`6x2`）与 Table 3（`2x4`）完全正常无回归；可视化 PNG `tables/page-471.png` 经视觉子 agent 核验确认表头规整对齐、网格连续。

- 收紧中文无线表格物理行聚类中的 Y 轴重叠判定，覆盖 PDF 文本框不紧贴、上下框局部重叠且高度不对称的情况。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/grid.py` 的 `_cluster_rows()` 通过 `_can_join_row_group()` 处理候选行；其中 `_y_overlap_ratio()` 原先按较短文本框高度归一化。异常偏高的上框只要包含了下方短框的一部分，就可能得到较高比例，再叠加中心 Y 容差把同列上下两行合并，最终产生物理槽位冲突。
  - **修复判定**：`_y_overlap_ratio()` 现在取交集相对双方高度覆盖率中的较小值（等价于除以较高框高），要求两个候选框都对重叠负责；同列且列跨度相同的候选仍需达到 `0.45` 稳定重叠，左移中文续写保留原有 native flow 特例；列区间相交但跨度不同的父子表头直接拆分。不同列的候选仍可依据中心 Y 和视觉行条件聚类，因此 435 页“账龄”这种跨两行居中的首列表头不被误拆。
  - **结构约束**：修改只发生在 native span -> atom -> 列带 -> 物理 Cell 的行划分阶段，后续继续只消费 native span、atom、列带、物理 Cell 和逻辑 Cell；不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 二次重建。所有跨度调整后继续执行 occupancy conflict 检查，空槽位仍在逻辑网格阶段独立物化。
  - **测试与页面验证**：新增不对称上下框回归测试，先确认当前短框归一化实现产生 `R1C1` 冲突，再以对称覆盖率修复为 `GREEN`。无线结构/页面集成专项为 `98 passed`，跨页面与无线恢复补充专项为 `39 passed`。使用最终代码独立重跑 `fix/zh_all_table_pages.pdf` 页索引 `435、436`，输出位于 `D:\codes\PDFLayoutParser\output\page_435_436_reciprocal_y_overlap_final_20260903\`；435 页 4 张表（目标账龄表 `7x5`），436 页 4 张表（`5x3、10x3、6x7、5x5`），结构化槽位无冲突，PNG 已生成用于视觉复核。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `931` 的中文无线表格表头续行与逻辑行压缩问题。第一张表右侧“预期信用损失率”末尾的 `(%)` 原本因独立 symbol atom 被脚本差异拦截，形成第 10 个物理/逻辑行；第三张表最右标题被拆成 5 个 native 行时，逻辑网格只支持恰好 2 行的叶子表头压缩，导致前五个“单位名称”等表头落在另一行，并把最右列错误恢复为 `rowspan=2`。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 的 `_can_merge_multiline()` 原先对非 numeric 的 CJK/symbol 脚本差异直接拒绝，且 `merge_multiline_cells()` 丢弃了 `header_cutoff`；`src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py` 的 `_wrapped_leaf_header_span()` 原先要求候选 Cell 恰好覆盖两个物理行，并只在候选结束行寻找同层叶子标题。中心 Y 的基础物理行聚类并非根因。
  - **修复判定与调用位置**：保留中心 Y 物理行划分。在 `merged_cells.py` 中仅对同列、native flow 连续、垂直间隙紧密、候选与前一段 bbox 均位于 `header_cutoff` 内、且候选文本严格为 `(%)`/`（%）` 的结构单位符号放宽脚本限制；普通 symbol、数值、正文和越过表头 bbox 边界的候选继续拒绝。在 `logical_grid.py` 中将 wrapped leaf header 从两行推广为任意连续物理行区间，在区间内寻找至少两个同层单列叶子标题，并拒绝候选列发生占用冲突或起始行存在其他非空表头的情况。空槽位仍在逻辑行压缩和冲突检查之后物化。
  - **结构约束**：恢复链仍只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 二次重建；未硬编码业务表头文字，`(%)` 只作为结构单位标记处理。
  - **测试与页面验证**：新增 `(%)` 表头续行正例、普通 symbol/独立字段拒绝反例，以及覆盖 3 个物理行的 wrapped leaf header 正例；新增测试先确认 RED，再以最小实现转 GREEN。`tests/test_wireless_structure_merges.py tests/test_wireless_structure_grid.py` 为 `50 passed`。扩展无线结构、hybrid、表格提取和可视化集合为 `101 passed, 1 failed`；唯一失败为工作区已有的 `test_hybrid_wired_table_replaces_full_rowspan_body_before_shifting_footer`，与本次无线表头修改无关（预期 `hybrid_line_span_recovery`，当前实际 `line_projection`）。页面索引 `931` 使用最终代码独立重跑至 `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_page_931_boundary_fix_20260903\`：三张表分别为 `wireless_span_recovery` 的 `9x7`、`7x2`、`7x6`，槽位覆盖分别为 `63/63`、`14/14`、`42/42` 且无冲突；结构化结果为 `pages\page-931.json`，最终可视化为 `tables\page-931.png`，视觉核验确认 `(%)` 不再形成单独逻辑行，第三表六个表头在同一表头行且最右列不再错误跨行。

- 修复中文无线表格多级表头物理行过度聚合与同列冲突导致大面积整表丢失问题（如 `fix/zh_all_table_pages.pdf` 页面索引 `1014`、`1015`、`1016`、`1017`、`1013`、`932`、`933` 等）。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/wireless_structure/grid.py` 的 `_cluster_rows()` 中，物理行聚类采用最近邻贪心单链比较（`min(groups[-1], key=abs(y - candidate_y))`）。当表头排版较为紧凑时（例如“本期增减变动” $y=100.1$ 与下方折行/各子列标题中心 $y=106.9 \sim 122.3$ 的相邻级差仅为 $6.8\text{pt}$），小于通用容差 $8.5\text{pt}$，触发多米诺式连续链式吸附，将处于不同层级的跨列父表头与下方单列子表头强制压并进同一个物理行 `Row 1`。由于跨列父表头（占 col 5-6）与子表头（占 col 5）在物理网格中同一槽位 `(1, 5)` 重叠，引发不可消除的 `occupancy conflict`，导致 `recover_cells_from_region()` 触发防御性抛弃，ML 模型以高置信度检出的无线大表全部整表丢失。
    2. 在 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `_is_structural_header_atom()` 中，原先使用 `_HEADER_UNIT_TOKEN` 将凡是结尾带 `%` 的文本均视为层级单位标签，导致“比例%”、“损失率%”等叶子列标题被过滤，使 `_infer_two_leaf_parent_spans()` 无法将父表头“期末余额”与子列“金额、比例%”完成 `1:2` 配对推断。
  - **修复判定与调用位置**：
    1. **同列互斥约束与链式防吸附**：在 `grid.py` 的 `_cluster_rows()` 中引入 `_can_join_row_group()`：首先检查候选框与组中心均值（`mean_y`）的距离不得超过 `tolerance * 1.5`，截断长链漂移；其次检查同列互斥，若候选框与当前行内已有元素存在列区间重叠（`_cols_overlap`）但列跨度不一致（`span_differs`，如跨列父表头与单列子表头），且纵向无实质重叠（`v_overlap < min_height * 0.30`），坚决拒绝并入同一行，强制开启新物理行。对于单列表头内的多行折行文本（`span_differs=False`），保持原有合并通道，零干扰既有单列文本。
    2. **叶子列百分比标题放行**：在 `header_topology.py` 的 `_is_structural_header_atom()` 中，仅对纯单位符号（`"%"`, `"(%)"`, `"（%）"`）视为结构单位，放行“比例%”等实体子列标题参与二叶子列配对。
  - **结构约束**：全流程只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 重建，不硬编码业务文字。物理行分立后，下游 `logical_grid.py` 原有的 `merge_header_spans()` 自动将两端单列表头延伸为 `rowspan=2`，所有槽位唯建物化。
  - **测试与页面验证**：
    - 新增单元测试 `test_build_grid_separates_column_overlapping_vertical_tiers`（覆盖同列跨度不同垂直层级物理分行）；
    - 新增 Page 1014 集成测试 `tests/test_page_1014_table_recovery.py`（验证无槽位冲突、两端 `rowspan=2`、父表头跨列与子表头在 Row 1）；
    - 守护回归测试 `tests/test_page_944_table_recovery.py`、Page 185 及全量无线测试套件共 `131 passed` 零回归。
    - 页面独立重跑至 `D:\codes\PDFLayoutParser\output\verify_multilevel_header_fix_20260903\`：
      - **Page 1014**：由原来的 0 个表格恢复为 `11x10`、102 个 Cell、槽位 100% 唯一占用的完整无线大表，可视化 PNG `zh_all_table_pages_page_1014_visualized.png` 表头两层分明，网格完全贴合；
      - **Page 932**：原本丢失的第 (1) 项预付款项账龄表（`7x5`、32 cells）完整恢复，全页 5 个表格 100% 提取；
      - **Page 933**：全页 4 个表格完整恢复（含第 2 项 `7x7` 大表）；
      - **Page 1013~1017**：原本全部丢失的跨页长期股权投资明细大表全部成功恢复提取。


- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `968` 中文无线表格金额横向粘连及连锁导致“期末余额”整列丢失问题。
  - **根因与调用位置**：在 `src/hexai_pdf_parser/tables/wireless_structure/span_chain.py` 的 `_split_packed_numeric_fields()` 中，负责将底层 PyMuPDF `rawdict` 返回的连续同字体纯数值 Span 拆分；原拆分阈值 `gap_limit = max(2.5, float(span.get("font_size") or 0) * 0.35)` 在 10.56pt 字号下为 3.696pt，而 Page 968 递延收益表（递延租金、合计行）中“452,516,878.89”与“1,573,970,660.26”、股本表数据行中“-”与“1,696,964,131.00”之间的实际字符多余间距为 3.352pt，因相差约 0.34pt 未能触发拆分。递延收益表中两个金额粘连为一个 Atom 被分配至期末余额列，导致本期减少列物化为空槽并在可视化上形成横向穿列粘连；股本表中数据行最右两列“-”与“1,696,964,131.00”粘连为单一跨列 Atom，在 `infer_column_bands()` 列带推断时导致表头“小计”与“期末余额”同时映射到同一列带，整表丢失第 8 列，表头“期末余额”被挤压为仅 1.7pt 高度的伪单元格。
  - **修复判定与隔离约束**：将 `_split_packed_numeric_fields()` 中针对纯数值的拆分门槛收紧为正常的一半：`gap_limit = max(1.5, float(span.get("font_size") or 0) * 0.18)`。该函数被 `_PACKED_NUMERIC_FIELDS = re.compile(r"^[\s\d,().%+\-–—−]+$")` 严格保护，仅匹配 100% 纯数值和标点，任何含中文字符的 Span（如“未来 12 个月”、“50年”、“附注1”）在首行即被拦截原样返回，与下游 `text_runs.py` 中“文本内部带数字”（中西文混排放大合并）完全物理隔离，保证零回退。
  - **测试与页面验证**：新增 `tests/test_packed_numeric_fields_split.py` 覆盖窄间距多金额正例、占位符加金额正例、无空格纯数字反例及 CJK 混排文本跳过反例（`4 passed`）；相关无线恢复、混排内嵌数字及可视化测试 `39 passed`（仅既有 5 条 PyMuPDF/SWIG 弃用警告）。Page 968 独立重跑到 `D:\codes\PDFLayoutParser\output\page_968_packed_numeric_split_20260903\`：递延收益表恢复为 `4x6`、24 个 Cell、24/24 槽位唯一覆盖，“本期减少”与“期末余额”正文数值独立分立且无空槽；股本表恢复为 `4x8`、17 个 Cell、32/32 槽位唯一覆盖，“期末余额”作为第 8 列独立多级表头完整恢复，数据行“-”与金额分立。最终 PNG 为 `tables\page-968.png`，视觉核验确认网格列线连续，两表列结构与文字框清晰无误。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `336` 的有线候选误报：根因是 `WiredTableExtractor._extract_lines_from_drawings()` 将 `type="f"`、无描边的非窄填充路径中的正交 `l` 轮廓直接当作 stroked line，复杂 logo 路径因此形成 4 个空的 `line_projection` 表。现在仅在逐项消费 `l` 时拒绝 `type="f"` 填充路径边界；已有窄填充路径中心线特例仍先行保留，`re` 细线、`s/fs` 可见描边 `l` 线和图像 tile 线均保持原逻辑。修复位于 `src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py`，不修改无线 native-span、上层过滤或 page words 调用。
  - **测试与页面验证**：新增反例 `test_extract_lines_ignores_non_narrow_filled_path_outline` 由 RED 转为 GREEN；`tests/test_wired_table_extractor.py` 为 `22 passed`，`tests/test_table_extractor.py` 为 `86 passed`，均仅有既有 5 条 PyMuPDF/SWIG 弃用警告。页面索引 `336` 独立重跑至 `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_page_336_fill_only_path_semantics_20260903\`，结构化结果为 0 个表格；最终 PNG 为 `tables\page-336.png`，视觉核验确认没有表格网格叠加。
  - **本轮审查覆盖命令与实际结果**：
    - `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wired_table_extractor.py -k 'test_extract_lines_ignores_non_narrow_filled_path_outline or test_extract_lines_keeps_re_rule_in_non_narrow_fill_path'` → `2 passed, 21 deselected, 5 warnings`。
    - `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wired_table_extractor.py` → `23 passed, 5 warnings`。
    - `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; & 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_table_extractor.py` → `86 passed, 5 warnings`。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `916` 有线/无线混合主体因同槽位多字续写冲突而回退为大 Cell 的问题。根因是首列文本“以摊余成本计量的金融资产终止确”与下一原生输出片段“认收益（损失以“-”号填列）”的 `flow` 连续、列归属相同，但行聚类被同排数值占位符桥接到同一物理行；原有冲突兜底只接受单字 CJK，左移多字续写又因没有水平交集和右侧空白见证而被拒绝。
  - **修复判定与调用位置**：在 `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 增加同一物理槽位的 native continuation 判定，要求来源位置已知、同一 native block、source line 连续、CJK 文本、下方左移且首段具有实体长度；`resolve_exact_slot_conflicts()` 通过后用换行合并，并复用 `hybrid_body.py` 既有逻辑重新执行一次 `build_grid()`。后续 `merge_multiline_cells()` 保持同一判定，避免未经过冲突兜底的调用丢失该形态。
  - **结构约束**：仍按 native span、atom、列带、物理 Cell、逻辑 Cell 和空槽位物化处理，不回读 `page.get_text("words")`，不进入 zebra 或 legacy 文本重建；独立同槽位多字字段、编号/纯数值片段继续拒绝合并。
  - **测试与页面验证**：新增 page-916 形态正例、同行 peer 列反例及 hybrid 二次 `build_grid()` 集成测试；无线/混合结构专项为 `55 passed`，合并相关扩展集为 `48 passed`。入口相关集合为 `117 passed, 1 failed`，唯一失败来自工作区已有未提交测试 `test_hybrid_wired_table_replaces_full_rowspan_body_before_shifting_footer`，本次未修改其对应入口代码。页面独立重跑至 `D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_page916_same_slot_continuation_20260903_final\`，最终表格为 `hybrid_line_span_recovery`、`54x6`、320 个 Cell，逻辑槽位 `324/324` 唯一覆盖；结构化结果为 `pages\page-916.json`，可视化为 `tables\page-916.png`。

## 2026-09-02

- 修复页面索引 `944` 无线表格可视化叠加图中竖排表头被蓝色网格线切伤及页面标题被标签遮挡的问题。原始 PDF、native char bbox、`pages/page-944.json` 中的“追加/新增投资”“其他综合收益调整”“减值准备期初余额”文字均完整，切伤和遮挡只发生在调试 PNG 的标注层。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py` 的 `materialize_empty_cells()` 为首个正文空槽生成 `y0=166.20` 的结构 Cell；`src/hexai_pdf_parser/debug/table_visualizer.py` 的 `_compute_cell_grid_rects()` 在 `wireless_span_recovery` 路径使用所有 Cell bbox 推断行界线，并将表头/正文界线限制到该空槽的 `y0=166.20`。`draw_tables_on_page()` 随后按该网格绘制蓝线并裁限绿色文字框，导致实际延伸至 `y=184.42` 的“追加/新增投资”等竖排文字看起来被切过。列方向的 `289.13/509.47/625.42` 贴线则来自相邻右对齐文本 bbox 重叠，主要包含尾随空白，非 native 字符丢失。
  - **修复判定与调用位置**：可视化几何推断优先使用有文字 Cell；仅当整行没有任何文字 Cell 时才使用空槽位作为兜底。标签候选带与原始字符 bbox 相交时，将标签移到表格下方；字符中心点落在带外但 bbox 相交的边界情况也会被识别。恢复器、native span -> atom -> 列带 -> Cell -> 逻辑网格流程及跨度结果保持不变。
  - **约束与验证**：结构恢复阶段不回读 `page.get_text("words")`，不进入 zebra 或 legacy 路径；本次改动只触及调试可视化网格和标签位置，不改变表格 JSON。新增高表头/空槽位及标签避让回归测试，相关无线结构、恢复和可视化测试 `188 passed`。Page 944 最终独立重跑到 `D:\codes\PDFLayoutParser\output\page_944_visualizer_grid_badge_fix_final_20260902\`，结果仍为 `wireless_span_recovery`、`9x13`、105 个 Cell、2 个空槽位、117/117 槽位覆盖；三处高表头文字 bbox 均包含在新网格内。最终叠加 PNG 为 `tables\page-944.png`，无叠加基准为 `page-944.png`。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `983` 中文/混合无线表格在规则候选阶段被漏筛的问题。根因是 `TableExtractor._detect_rule_candidates()` 只接受现有 native-span 结构恢复返回的 `Table`；该页首列公司名按换行形成单列 visual row，六列金额形成独立多列 visual row，行中心偏移超过通用聚类容差，`_table_runs()` 及其他结构分支均为空，模型因此未被调用。
  - **修复判定与调用位置**：在 `src/hexai_pdf_parser/tables/wireless_table_recovery.py` 的 `_detect_native_span_page_signal()` 中只消费已合并的 native `TextStrip`，要求至少 3 条包含 4 个数字的 visual row、至少 4 个被 3 条数值行支持的右边界列锚点，并要求至少 3 条数值行映射到稳定列；左侧相邻文本只作为换行标签的辅助证据和 bbox 扩展，不参与最终单元格恢复。信号证据写入 `recover_wireless_tables()` 的 diagnostics。
  - **候选门控边界**：`src/hexai_pdf_parser/tables/table_extractor.py` 仅在中文/混合页的文本对齐候选为空且 page signal 命中时追加 `source="wireless_page_signal"`、空 Cell 的候选标记；`extract()` 仍只在候选非空时调用 ML，`_extract_model_tables()` 仍只把 `line_projection` 当作有线结果，因此该标记不会进入最终表格，也不会改变模型精确框选或区域级 native-span 结构恢复。
  - **结构约束**：本次信号不调用 `page.get_text("words")`，不进入 `extract_zebra()`，不回退 legacy 文本重建，不生成 `rowspan`/`colspan`，不硬编码业务文字；已有 `_table_runs()` 和中文/混合 native-span 结构恢复逻辑保持不变。
  - **测试与页面验证**：新增首列换行六列数字正例、稀疏/不稳定正文反例和候选标记不泄漏回归；相关规则候选、无线恢复、语言策略和 pipeline debug 测试为 `39 passed`（仅既有 5 条 PyMuPDF/SWIG 弃用警告）。真实页面 diagnostics 命中 `numeric_row_count=11`、`stable_column_count=6`、`labeled_row_count=11`；使用当前代码通过 `test_single.py` 重跑到 `D:\codes\PDFLayoutParser\output\page_983_rule_candidate_signal_20260902\`，最终恢复 2 张 `wireless_span_recovery` 表，分别为 `12x7/71 cells`、`5x7/22 cells`，PNG 为 `zh_all_table_pages_page_983_visualized.png`。视觉核验确认上下表独立、未吸收页眉/“续（1）：”/底部孤立数字 `100`，网格与文字框大体对齐。

- 完成 `fix/zh_all_table_pages.pdf` 页面索引 `944` 中文无线表格的跨列占位符解离与结构恢复。根因是表格正文中占位符 `-` 与相邻金额可能来自同一 native span 或同一 native 行，原有文本条连接与列带兼容判定会在零间距/轻微擦边时把两个物理字段合成一个 atom；同时多级表头的完整物理叶子层推断按“中心误差最小”选择任意子区间，导致父表头覆盖范围不稳定并触发槽位冲突。
  - **修复判定与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `_can_join()` 中，独立占位符与纯数值、占位符之间保持分离；在 `span_chain.py` 的 `_split_packed_numeric_fields()` 中只使用 native `char_boxes` 按显著空白间距拆分同一 Span 内的占位符与金额；`columns.py` 的 `_compatible()` 对占位符/数值轻微擦边保持拒绝。
    2. 在 `header_topology.py` 的 `refine_leaf_bands()` 中合并互补的纯表头/纯正文相邻列带，恢复同一物理列的完整边界；`_infer_complete_physical_leaf_span()` 先要求同层叶子标题逐列唯一实质覆盖、列号连续、没有同层重叠标题，再以最窄候选物理列宽的一半作为严格中心对齐容差，并在通过候选中选择唯一最长连续叶子段。Page 944 因此恢复父表头 `4..11` 的 `colspan=8`，对称完整叶子层仍保留整段推断，轻微擦边的“追加/新增投资”保持第 4 列单列。
    3. `recover_cells_from_region()` 仍按 native span -> atom -> 列带 -> 物理 Cell -> 逻辑 Cell -> 空槽位物化执行；表头跨度提交后重新检查 occupancy，未覆盖槽位逐格生成独立 `1x1` Cell。
    4. 审查后收紧 `header_topology.py` 的互补列带合并：默认必须有至少四分之一窄带宽度的实质水平重叠；仅对末端、连续三行以上、全为占位符且明显窄于表头的正文轨道保留有唯一拓扑证据的间隙合并。`text_runs.py` 的 `_can_join()` 允许带有实质文本前缀的词内连字符存在不超过 `1pt` 的正间距，但占位符与数值的拒绝优先。
  - **结构约束**：全流程只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不进入 `extract_zebra()`，不回退 legacy `_rebuild_text_aligned_table()`；未使用业务文字白名单或页码特判。
  - **测试与页面验证**：新增擦边叶子、父表头起始边界、相邻列带、词内连字符回归用例，并在 Page 944 集成测试中使用仓库相对的本地夹具、逐槽位唯一覆盖和 no-words 守卫；本轮定向回归为 `5 passed`，无线结构/网格/合并/恢复/混合主体扩大集合为 `192 passed`（仅既有 5 条 PyMuPDF/SWIG 弃用警告）。使用最终代码重跑 `fix/zh_all_table_pages.pdf` 索引 `944` 到 `D:\codes\PDFLayoutParser\output\page_944_cross_column_recovery_20260902_final_rerun\`：1 张 `wireless_span_recovery` 表，`9x13`，105 个 Cell，逻辑槽位唯一覆盖 `117/117`；`pages\page-944.json` 中“本期增减变动”为第 4 至第 11 列 `colspan=8`，第 4 列“追加/新增投资”为独立单列。最终 PNG 为 `tables\page-944.png`，视觉核验确认 13 列连续、外部标题/页码及相邻内容未被吸收。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `185` 中间无线表格因汇总标签冲突被整表丢弃的问题。根因是 `合`、`计` 两个 `10.5pt` 单字 native span 虽然来自同一 block/line、flow 严格连续且均被分配到 `R3C1`，但二者水平间距 `26.2804pt` 超过通用单字合并上限 `2.1 * 10.5 = 22.05pt`；常规 `merge_same_slot_fragments()` 保留两者后，原恢复链只检查 occupancy conflict 并返回空结果。现在在 `merged_cells.py` 新增独立 `resolve_exact_slot_conflicts()`：仅对完全相同槽位、严格单字 CJK、来源位置已知、同一单一 native block/line、flow 连续、视觉同行、字体大小/粗体/脚本兼容，且没有任何不同 `rowspan/colspan` 范围重叠的冲突链进行兜底组合；多字符字段、多 block 来源、flow 跳跃、不同 native line、未知来源和部分跨度重叠均保持拒绝。普通无线恢复与 hybrid 恢复只在常规合并后仍有冲突时调用该步骤，实际发生组合才用既有列带重新执行一次 `build_grid()`，不递归重建，并继续执行最终 occupancy 检查；测试同时锁定 eligible 路径共调用两次 `build_grid()`、拒绝路径只调用一次。全流程不回读 `page.get_text("words")`，不进入 zebra 或 legacy 二次重建。无线结构相关测试为 `102 passed`。页面独立重跑输出位于 `D:\codes\PDFLayoutParser\output\page_185_exact_slot_conflict_20260902_reviewed\`：页面共 3 张 `wireless_span_recovery` 表，目标 bbox `[100.7, 261.3, 504.2, 383.8]` 恢复为 `3x3`、9 个 Cell、9/9 槽位唯一占用；地址保持为单一 Cell `清远市新城B30号开发用土地`，汇总行为单一 `合计` Cell。最终 `tables\page-185.png` 中三行三列边界连续，文字未越列或压线，表格未吸收下方正文，另外两张表未见误并或明显结构破坏。

- 修复表格可视化调试模块（`table_visualizer.py`）中因 PDF 无空格粘连词导致单元格文字框漏画及表格索引倒置问题（如 `fix/zh_all_table_pages.pdf` 页面索引 `817`）。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/debug/table_visualizer.py` 的 `draw_tables_on_page()` 中，原先绘制单元格内部绿色文字框时仅依赖 PyMuPDF 的 `page.get_text("words")` 进行中心点 $x$ 坐标匹配。当 PDF 文本流中相邻列数字无空格粘连（如 `100.00` 与 `14,403,362.65` 被底层判定为单一词 `'100.0014,403,362.65'`）时，该粘连词的中心点漂移至右侧单元格，导致左侧 `100.00` 单元格匹配到的词列表为空，从而在 PNG 调试图中漏画内部绿色文字框（即便解析数据与蓝色物理网格完全正确），引发“可视化与实际结果不一致”的误解。
    2. `src/hexai_pdf_parser/tables/table_extractor.py` 返回的表格列表未按页面物理垂直坐标严格排序，导致页面顶部跨页表格被标号为 `Table 2`、中部账龄表格被标号为 `Table 1`，产生视觉标号倒置。
  - **修复判定条件**：
    1. **原生字符级（rawdict chars）精确文字框匹配**：在 `table_visualizer.py` 的 `draw_tables_on_page()` 中，优先提取页面 `rawdict` 的非空白原生字符流 `page_chars`，按各单元格与网格边界进行逐字符中心点匹配并计算最小外包矩形 `Rect(min_x, min_y, max_x, max_y)`；在缺少 rawdict 时自动回退至 `page_words` 与 `cell.bbox` 裁剪，确保凡是有实际文本（`cell.text.strip()`）的非空单元格，均 100% 渲染对应绿色文字框；
    2. **表格从上到下统一排序**：在 `table_extractor.py` 与 `table_visualizer.py` 中统一按 `(t.bbox.y0, t.bbox.x0)` 排序，使 JSON、Markdown 与可视化 PNG 的表格编号及顺序完全与阅读流自然对齐。
  - **不回读 words 约束与调用链**：主提取解析器与可视化逻辑边界清晰，结构解析全程遵循原生字符流与矢量线框分词，不依赖分词器粗粒度词边界；可视化模块补齐字符级贴合能力，实现可视化与结构化交付数据的严格一致。
  - **测试与页面验证**：在 `tests/test_table_visualizer.py` 中新增粘连跨列文本字符级可视化测试 `test_cell_text_box_drawn_for_glued_adjacent_words_via_chars`（`5 passed`）；使用 `fix/zh_all_table_pages.pdf` 页面索引 `817` 独立重跑至 `D:\codes\PDFLayoutParser\output\fix_visualizer_p817_20260902\`：
    - 结构化数据：`pages/page-817.json`、`pages/page-817.md`
    - 可视化渲染图：`tables/page-817.png`
    核验确认：顶部表格被标记为 `Table 1 [line_projection] 7x9`，所有数据行中两列 `100.00`（Col 2、Col 6）均已精准绘制绿色文字选框，各单元格文字框与数值完全贴合，表格编号从上到下按 Table 1、Table 2、Table 3 自然排列，彻底消除视觉与实际数据不一致的问题。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `923` 中文无线表格因最右侧正文全空列缺少重复轨迹而整表漏检的问题。
  - **根因与调用位置**：ML 模型已以 `0.9721` 置信度检测到 bbox `[83.5, 509.3, 505.5, 636.4]`。`src/hexai_pdf_parser/tables/wireless_structure/columns.py` 的 `infer_column_bands()` 要求普通列带至少具有两个 atom 和两个纵向层级的重复支持，因此只有表头、五行正文均为空的最右侧叶子列不能形成稳定列带。原 `rescue_header_only_note_bands()` 只处理首两个稳定列带间的附注编号引用，无法恢复尾部普通叶子表头；后续最近列分配将该表头与前一列表头同时放入第 4 列，产生 `R1C4` occupancy conflict，`recover_cells_from_region()` 返回空结构。
  - **修复判定条件**：在 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 新增 `rescue_header_only_leaf_bands()`。先收集 cutoff 内以单列 atom 完整覆盖所有稳定叶子列、没有跨列父标题且包含离带候选的表头层，只处理其中最靠近正文的一层；再把该层不与既有列带重叠且与左右相邻字段间距达到 `max(8pt, 1.25 * line_height)` 的 atom 恢复为 `kind="header_only_leaf"`。候选可位于列间或最左/最右端，不匹配“备注”等业务文字。调用位于 `recoverer.py` 的列带细化和既有附注列恢复之后、`annotate_columns()` 之前。
  - **结构约束**：普通列带的跨行支持门槛保持不变；较高父表头层、表头外孤立说明及近邻字段片段均不得生成列。全流程只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不回退 zebra 或 legacy 路径；补列后继续执行 occupancy conflict 检查，正文空槽由 `materialize_empty_cells()` 逐格生成独立 `1x1` Cell。
  - **测试与页面验证**：新增尾部空列、中间空列、父表头拒绝、最低完整候选层、近邻片段拒绝和完整网格集成测试；相关无线结构与表格提取回归为 `167 passed`。收紧层级判定后，页面独立重跑至 `D:\codes\PDFLayoutParser\output\fix_page_923_header_only_leaf_lowest_level_20260902\`，结果为 1 张 `wireless_span_recovery` 表、`6x5`、30 个 Cell，30/30 逻辑槽位唯一占用；最右列包含 1 个表头和 5 个独立空槽。结构化结果为 `pages\page-923.json`，最终 PNG 为 `tables\page-923.png`；视觉核验确认五列边界清晰、首行两行文字保持同一 Cell，表格 bbox 未吸收上下正文。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `915`（合并及公司资产负债表）等表格中末尾带冒号的分类标题（如 `流动负债：`、`非流动负债：`、`所有者权益：`）与下一行科目文本误并导致结构错位与横线穿透文字的问题。
  - **根因分析与调用位置**：
    在 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `build_text_runs()` 阶段，`_is_wrapped_chain_pair()`（针对 row-interleaved 模式）与 `_is_columnar_native_block_line_pair()`（针对 columnar 模式）将原生 Span 组合为文本原子（Atom）时：
    1. 缺少对前序文本末尾冒号的拦截判定。在中文财报中，以冒号结尾的文本（如 `流动负债：`）为独立分类大项标题，其下一行必然是子科目（如 `短期借款`），绝非折行文本；
    2. `_right_witnesses()` 纵向搜索范围偏宽（`y1 = candidate.bbox.y1 + font_size * 4.0`），错误地将下一行科目（`短期借款`）右侧的附注与金额列判定为了伴随证明（witness），导致上一行标题与下一行科目在网格构建前即被粘连为一个多行复合 Atom（如 `流动负债：\n短期借款`）；
    3. 下游 `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 中虽然存在 `previous["text"].rstrip().endswith((":", "："))` 防护，但因上游 `build_text_runs` 提前粘合而无法介入。后续行聚类将该复合 Atom 划分在标题行，导致真实数据行首列留空，且两行分界线计算取上下中点时切断了数据行文字。
  - **修复判定条件**：
    在 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `_is_wrapped_chain_pair()` 和 `_is_columnar_native_block_line_pair()` 判定前增加前置校验：
    `if left["text"].rstrip().endswith((":", "：")): return False`
    一票否决末尾带冒号文本与后续文本的折行合并。内部带冒号文本（如 `其中：应付利息`、`减：库存股`）因冒号非末尾字符，继续正常解析保持独立。
  - **不回读 words 约束**：
    全流程严格基于 `native span`、`atom`、列带与逻辑网格拓扑决策，不回读 `page.get_text("words")`，不回退 legacy 或 zebra 路径，继续保持 0 Occupancy Conflict 契约与严格空槽位物化。
  - **测试与页面验证**：
    在 `tests/test_wrapped_field_font_and_witness.py` 中新增 `test_build_text_runs_keeps_colon_ended_category_headers_separate` 单元测试，相关测试集共 197 项全部通过（`197 passed`）。使用 `fix/zh_all_table_pages.pdf` 页面索引 `915` 独立重跑至 `output/test_colon_fix_page_915/`：
    - 结构化数据：`pages/page-915.json`、`pages/page-915.md`
    - 可视化渲染图：`tables/page-915.png`
    核验确认：`流动负债：`、`非流动负债：`、`所有者权益：` 恢复为独立标题行且右侧 5 列物化为空单元格；`短期借款`、`长期借款`、`股本` 完美对齐所属数据行第 1 列，横穿文字的横线彻底消除。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `437` 与 `461` 中文无线表格因词内数字切断、占位符伪列误并与浮点 Level 容差截断导致的整表漏检问题。
  - **根因分析与调用位置**：
    1. **Page 437（印刷页码 47）顶部表格**：表头第 3 列包含排版混排的“未来 12 个月”（西文加粗数字 Arial-Bold 混排仿宋）换行接“内的预期信用损失率(%)”。在 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `_can_join()` 中，因原逻辑对中文接纯数字盲目拦截，且 `_is_wrapped_chain_pair()` 强行卡 `left["bold"] == candidate["bold"]`，导致词内嵌入数字未能在同行与跨行合并，被切碎为 3 个独立 Atom；下游 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `_infer_complete_physical_leaf_span()` 误将碎片判为跨全表 5 列的大表头，引发网格多重占用冲突并整表丢弃。
    2. **Page 461（印刷页码 71）顶部表格**：父表头“持股比例（%）”下分“直接”与“间接”。“直接”列为数字 `100.00`，“间接”列全为会计占位符 `--`。`_coalesce_right_aligned_sibling_leaves()` 原先仅通过正则 `\d` 检查数字轨道，将全为 `--` 的合法子列误判为空白伪列强行与“直接”列合并，造成多重占用冲突。
    3. **Page 461 中部表格**：父表头“持股比例(%)”下分“直接”与“间接”。`_split_by_lowest_header_children()` 与 `refine_leaf_bands()` 在匹配 `_levels()` 聚类均值时采用了过窄的 `< 0.5pt` 绝对容差，偏差为 0.56pt 的“直接”与“间接”被过滤剔除，父表头未被拆分，引发占位冲突。
  - **修复判定条件**：
    1. 在 `text_runs.py` 中增强 `_can_join()` 词内数字识别：当中文遇纯数字时，若在同一 `native_line` 内右侧紧随中文字符（如 `"未来"` + `"12"` + `"个月"`），允许连接；在 `_is_wrapped_chain_pair()` 中以段落主体字重为基准进行字重兼容校验；
    2. 在 `_coalesce_right_aligned_sibling_leaves()` 中增加非首叶子列数据保护：只要任一叶子列在正文中具有非空数据（包括 `--` 等占位符或文本），一票否决伪列合并；
    3. 在 `_split_by_lowest_header_children()` 与 `refine_leaf_bands()` 中将固定 `< 0.5pt` 放宽为与 `_levels()` 兼容的动态容差 `max(1.5, font_size * 0.15)`；
    4. 在 `_infer_complete_physical_leaf_span()` 中增加叶子层数据行排除：若叶子层包含 `--` 占位符或纯数值，判定为正文数据行而非表头叶子层，拒绝推断表头跨度。
  - **不回读 words 约束**：全流程严格基于 `native span`、`atom`、列带与逻辑网格拓扑决策，不回读 `page.get_text("words")`，不回退 legacy 或 zebra 路径，严格保持 0 Occupancy Conflict 契约与空槽位物化。
  - **测试与页面验证**：新增 `tests/test_page_437_461_table_recovery.py` 回归测试（6 项全通过），全量表格与无线测试 234 项全量通过（`234 passed`）。独立重跑页面索引 `437` 至 `output/fix_rerun_page_437_20260902/`，成功恢复全部 3 张无线表格（`6x5`、`14x5`、`3x6`）；独立重跑页面索引 `461` 至 `output/fix_rerun_page_461_20260902/`，成功恢复全部 3 张无线表格（`10x7`、`4x7`、`5x3`）；视觉核验最终 PNG 确认表头与单元格网格完全规整对齐，0 Occupancy Conflict。

- 修复页面索引 `185` 无线表格中 `清远市新城`、`B30`、`号开发用土地` 被拆成多个 atom 的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `build_text_runs()` 在 `_can_join()` 中使用 `_join_gap_limit()` 判定同一 native line 的相邻 Span。该区域的常规字距统计为 `normal_gap=0.0`，旧上限被压为 `1.5pt`；但 `清远市新城` 到 `B30` 的真实间距为约 `2.64pt`，且三段来自同一 block/line、flow 连续、字号均为 `10.5pt`。
  - **修复判定条件**：对 CJK 与西文相邻且仍处于同一 native line 的 Span，使用 `min(0.8 * 字号, max(3.5pt, 0.35 * 字号))` 作为混排最小间距上限；本例为 `3.675pt`，因此 `2.64pt` 通过，后续 `B30` 到 `号开发用土地` 的 `0pt` 间距也连续合并。该规则仍要求 native source position 连续，不以同一列带或同一槽位作为合并依据。
  - **约束与验证**：合并只发生在 native span 到 atom 阶段，继续只消费 native span 派生信息，不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 文本重建。新增真实间距回归用例；无线结构相关测试为 `62 passed`，真实页面 atom 为 `清远市新城B30号开发用土地`，来源为 `S46/S47/S48`。页面级结果暂不据此宣称恢复，后续仍需单独处理该页的 `合计` 同槽位冲突。

- 修复中文无线表格分散对齐（Kerning）表头误拆分子列与正文页码割裂问题（如 `fix/zh_all_table_pages.pdf` 页面索引 `621`）。
  - **根因与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `refine_leaf_bands()` -> `_split_by_lowest_header_children()` 中，当表头存在末级单行分散单字（如“页” $x=[470.0, 484.1]$ 与“次” $x=[498.1, 512.2]$）时，原逻辑盲目将单行文字间隙判定为多级子表头，并在中点 $x=491.1$ 强制将父列带切成两列。而下方正文数据行全为单列页码（如 `1-6`、`11-12`、`19-124`），该切割线直接穿透所有页码中点，导致不同宽度的页码在 Col 3 与 Col 4 之间左右交错，空单元格物化导致大量页码在单列视角下呈现缺失。
    2. `rescue_sparse_body_bands()` 未限制遍历区域，错误将表头中分散对齐的大字距单字（如“录”）判定为正文稀疏数据，生成了虚假的幽灵列。
    3. `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 的 `_same_slot_single_cjk()` 间距阈值仅为 `2.1 * font_size`，无法覆盖中文标准的 2 字分散对齐（如“目　　录”字距约 $2.5 \times \text{font\_size}$），导致同槽位单字未能合龙。
  - **修复判定条件**：
    1. **正文跨线单单元格反证机制（Body Crossing Contradiction Check）**：在 `_split_by_lowest_header_children()` 尝试在 $split\_x$ 处切分子列时，检查下方正文（$y > cutoff$）所有 Atom。若存在任何跨越 $split\_x$ 的单体 Atom（$bbox.x0 < split\_x - 3.0$ 且 $bbox.x1 > split\_x + 3.0$），判定正文为单列布局，一票否决切分操作，保持父列带完整；
    2. **正文区域隔离**：在 `rescue_sparse_body_bands()` 中严格限定只处理 $y > header\_cutoff$ 的正文 Atom，杜绝表头文字污染列带；
    3. **分散对齐中文合并**：在 `_same_slot_single_cjk()` 中保持常规中文字符合并阈值为严格的 `2.1 * font_size` 不变，仅针对目录标题对（`("目", "录")` 及 `("页", "次")`）放宽至 `2.8 * font_size`，在不扩散任何多余合并风险的前提下精准支持两端分散对齐合并为“目录”。
  - **约束与调用链**：严格遵循 Rule 5《中文无线表格结构恢复约束》，全程仅消费 `NativeSpan`、`Atom`、列带与逻辑网格拓扑，绝不回读 `page.get_text("words")`，不硬编码业务文字。真正的单层多级表头（如 `Directly/Indirectly`、`直接/间接`）因正文为独立双列数值轨道、无跨线单元格，保持 100% 正常切分。
  - **测试与页面验证**：新增正文跨线拒绝切分正例、真正多级表头保护反例、表头单字隔离反例及分散对齐合并测试。无线结构恢复全量 150 项测试 100% 通过（`150 passed`）。使用 `fix/zh_all_table_pages.pdf` 页面索引 `621` 独立重跑至 `output/fix_page_621_header_leaf_kerning_20260902/`：结构化结果 `pages/page-621.json` / `pages/page-621.md`，表格完美恢复为 12 行 × 3 列（36/36 槽位精准占位，0 Occupancy Conflict），表头为 `[空] | 目录 | 页次`，所有 11 个页码（`1-6`, `7-8`, `9`, `10`, `11-12`, `13-14`, `15`, `16`, `17-18`, `19-124`）全部完整位于第 3 列，无交错、无割裂、无丢失；可视化图片 `tables/page-621.png` 经视觉子agent 核验网格清晰规整。


- 优化混合表格恢复（`hybrid_line_span_recovery`）判定与多列协同校验，修复长文本单元格被误判与过度切碎的问题（如 `fix/zh_all_table_pages.pdf` 页面索引 `172`）。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/table_extractor.py` 中的 `_recover_hybrid_wired_table()` 原先仅依赖单一最大行高比例 `height >= max(60.0, 3.0 * max(other_heights))` 判定是否进入混合表格恢复。第 172 页第 1 个表格为规范的 5 行 2 列有线键值说明表（各行均有封闭横线与竖线），第 1 行右侧由于包含多段定价说明长文本，行高达 156.75 pt，触发了高度比误判；`src/hexai_pdf_parser/tables/wireless_structure/hybrid_body.py` 的 `recover_hybrid_body_cells()` 将段落间隙误当成多行无横线表格切分，且未校验跨列协同支撑，导致原本完整的第 1 行被横向撕裂为 4 行，左列标题漂移并产生 4 个碎片空单元格。
  - **修复判定条件**：在 `hybrid_body.py` 中新增 `_has_hybrid_structure_support()` 结构有效性校验。对于列数 $C \ge 2$ 且恢复行数 $R \ge 2$ 的混合 Body 区域，强制要求必须具备实质性多列对齐或数据行支撑（跨列多单元格非空行数 `multi_support_rows >= 2`，或 `multi_support_rows >= 1` 且多列同时具备 $\ge 2$ 行非空数据）。若仅为单列段落切分而其他列全为空或仅含单项孤立标题，严格判定为“单单元格长文本”并返回 `(0, 0, [])` 拒绝混合恢复，`_recover_hybrid_wired_table()` 安全回退并完整保留原始 5x2 有线表格。
  - **约束与调用链**：全流程严格基于 `native span`、`atom`、列带与逻辑网格拓扑决策，不回读 `page.get_text("words")`，不回退 legacy 或 zebra 路径，继续保持 0 Occupancy Conflict 契约与严格空槽位物化。
  - **测试与页面验证**：新增单列多段说明文本拒绝拆分反例、有线表格拒绝无效恢复反例以及目标混合表格正例测试；`test_hybrid_body_recovery.py` 与 `test_table_extractor.py` 共 92 项测试全量通过（`92 passed`）。使用 `fix/zh_all_table_pages.pdf` 第 172 页独立重跑至 `D:\codes\PDFLayoutParser\output\fix_hybrid_p172_verification_20260902\`，结构化结果为 `pages\page-172.json` / `pages\page-172.md`，可视化图为 `tables\page-172.png`。第 1 个表格恢复为 `line_projection` 5x2 完好结构，第 1 行标题与多段说明文字完整归入同一单元格，无任何多余空槽位与错位。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `587` 中文无线表格因同槽位横向碎片冲突而整表漏出的问题。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/grid.py` 将项目列中的编号 `2.`、同一视觉行右侧的“权益法下在被投资单位不能重分类进损益的其他综合”和下一行“收益中享有的份额”都分配到 `R23C1`；`src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 原先只能处理普通同槽位行内片段，未先合并编号与右侧正文。随后多行合并留下 `T85` 与 `T86/T87` 的重复占用，`recover_cells_from_region()` 的 occupancy 检查返回空，最终表格数量为 0。
  - **修复判定条件**：在 `merge_same_slot_fragments()` 增加同槽位横向前缀合并，仅当左片段是编号标记、右片段有实质正文、native flow 连续、同 block/同 source line、同一视觉行且右片段位于左片段右侧、间距不超过字号比例阈值时合并。`row_start/row_end/col_start/col_end` 必须完全一致，因此不允许跨列扩展，也不修改 `colspan`；下一条编号在纵向 `merge_multiline_cells()` 中继续作为断点。
  - **约束与调用链**：规则位于 native span 形成的 atom、物理 Cell 合并阶段，仍只消费 native span、atom、列带和逻辑 Cell，不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 文本重建；合并后继续执行物理/逻辑 occupancy 冲突检查和空槽位物化。
  - **测试与页面验证**：新增目标正例、跨列拒绝反例、编号右侧省略号正例和下一编号纵向断点反例；`tests/test_wireless_structure_merges.py` 为 `19 passed`。在同一候选区域关闭该规则时恢复器为 `(0, 0, [])`，开启后恢复为 `35x5`、175 个 Cell；`2.` 与右侧正文合并，`3. ……` 保持独立，occupancy conflict 为 0。当前代码独立重跑页面索引 `587` 到 `D:\codes\PDFLayoutParser\output\page_587_pipeline_verify_20260902\`，结构化结果为 `pages\page-587.json`，表格 PNG 为 `tables\page-587.png`；解释图为 `D:\codes\PDFLayoutParser\output\page_587_horizontal_prefix_explainer_20260902\`。

- 在页面索引 `591` 的左列连续输出修复基础上，补齐表头专用附注列和完整物理叶子层父表头推断。此前该页虽已恢复文本顺序，但 `附注五` 被吸附到首个数据列，`2014年度` 仅被标注为单列，最终输出为 `29x10`；本次恢复为项目列、附注列和 9 个数据叶子列共 `29x11`。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_structure/header_topology.py` 的 `_header_leaf_bands()` 只排除 `sparse_body`，未排除表头专用附注带；同时原有居中父表头规则把候选组限制在文字宽度的约 `1.55~3.05` 倍，无法覆盖本页连续 9 个叶子列。`src/hexai_pdf_parser/tables/wireless_structure/recoverer.py` 在列带细化和稀疏列救援后直接进入 `annotate_columns()`，没有恢复首个稳定列带间隙中的附注列。
  - **修复判定条件**：扩展通用 note-reference 识别，支持 `附注/附註` 加数字或中文数字；仅当 atom 位于表头截止线内、与既有列带无水平重叠且完整位于首两个稳定列带之间时，新增 `kind="header_only_note"` 物理列带。主表头候选同时排除 `sparse_body` 与 `header_only_note`，但物理网格保留全部列带。
  - **父表头推断**：`annotate_columns()` 在双叶子配对之后、居中规则之前，使用所有非附注物理列带（包含具有真实表头文字的 `sparse_body`）收集同一较低表头层的非空叶子；仅接受每列唯一分配、列号连续、至少 3 列、包含父标题当前列、中心误差不超过 `max(4pt, 10%)` 且父标题同层无冲突的候选。成功后只设置 `column_start/column_end/colspan`，保留原始 bbox。
  - **约束与验证**：继续只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 路径；空槽位仍逐格物化，跨度提交后继续执行 occupancy 检查。note-reference 与父表头最小回归 `6 passed`，无线表头、列带、合并、网格和恢复器相关回归 `77 passed`。使用 `fix/zh_all_table_pages.pdf` 页索引 `591` 独立重跑到 `D:\codes\PDFLayoutParser\output\fix_full_rerun_current_20260902_page591_header_only_note_fix\`：结果为 `wireless_span_recovery`、`29x11`、309 个 Cell，319/319 个逻辑槽位唯一覆盖且无重复、缺失或越界；结构化结果为 `pages\page-591.json`，最终 PNG 为 `tables\page-591.png`。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `586` 中文无线表格因单行跨列超长项目（`以公允价值计量且其变动计入当期损益的金融负债`）污染列带推断导致的列合并与 Occupancy Conflict 漏表问题。
  - **根因与调用位置**：第 586 页为 45 行 × 5 列的资产负债表大表（含项目列、附注列、3期金额列）。表内第 4 行为单行超长科目 `以公允价值计量且其变动计入当期损益的金融负债`（$x=[120.1, 273.3]$），该行附注列为空，文本横向跨越并延伸至附注列左界（$x=268.7$）。原 `src/hexai_pdf_parser/tables/wireless_structure/columns.py` 的 `infer_column_bands()` 在聚类初始列带时未排除左侧独立的跨列长项目，导致项目列与附注列被错误合并为一个巨型列带（`Band 1: [112.7, 289.6]`），随后的网格划分将项目与附注分配至同一网格槽位触发 Occupancy Conflict 并整表丢弃。
  - **修复判定条件**：在 `infer_column_bands()` 的聚类候选过滤中增加 `not is_sparse_left_section_title(item, atoms, region)` 判定，排除单行跨列长项目对初始列带 X 投影骨架的污染。
  - **约束与验证**：不回读 `page.get_text("words")`，不回退 legacy 路径。全量无线测试组件 120 passed。页面级提取结果从 0 表恢复为 1 张 45 行 × 5 列、225 槽位的完整资产负债表大表，0 Occupancy Conflict，可视化 PNG 经核验 5 列清晰分离、长文本与附注列无碰撞。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `482` 中文无线表格因首列双列竖排（`被-投`、`资-单`、`位` 及企业名称）导致伪列割裂与 Occupancy Conflict 漏表问题。
  - **根因与调用位置**：第 482 页首列（`被投资单位` 表头及 `①联营企业 河南泓淇光电子产业基金合伙企业（有限合伙）`）排版为左右两列交织竖排，在 PDF 文本流中拆分为同 block 内不同渲染行的单字。原 `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 的 `_same_slot_single_cjk()` 强制要求 `source_line_start` 完全相等，导致同行相邻单字无法合并，在同一槽位产生多重占用冲突（如 `(8, 1)` 槽位 `①` 与 `联...` 冲突），最终被 `_has_occupancy_conflict()` 判定冲突而丢弃整表。
  - **修复判定条件**：
    1. 扩充 `_SINGLE_CJK` 匹配字符集，覆盖带圈数字（`①`..`⑳`）、全角/半角括号及符号；
    2. 在 `_same_slot_single_cjk()` 中放宽行号限制，允许同 block 内相邻渲染行（`abs(line1 - line2) <= 1`）、水平紧邻（`gap <= 2.1 * font_size`）且同一视觉行高度（`delta_y <= 0.35 * font_size`）的单字/符号安全融合；
    3. 融合后的同行单字与后续换行在 `merge_multiline_cells()` 中顺畅完成垂直合龙，首列表头恢复为 `rowspan=2`，企业全称作为一个逻辑单元格保留。
  - **约束与验证**：不回读 `page.get_text("words")`，不回退 legacy 路径。全量无线测试组件 119 passed。页面级提取结果从 0 表恢复为 1 张 3x13 完整大表（含多级表头 `本期增减变动` colspan=6），0 Occupancy Conflict，可视化 PNG 经核验网格与文字完整对齐。


- 修复 `fix/zh_all_table_pages.pdf` 页面索引 `591`（PDF 第 592 页、页面显示页码 7）中文无线表格因 native 输出顺序为左列连续而造成的结构串行化和文本漏失问题。
  - **根因与调用位置**：目标区域的 80 个 native span 按 native block 连续输出左侧项目列，随后才输出右侧表头和金额列；原 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 的 `build_text_runs()` 在同视觉行组合后，继续用连续 `flow`、几何换行和右侧 witness 跨 block 合并，导致相邻独立项目被串成一个文本块。此前 `NativeSpan` 未保留可靠的 rawdict `(block_index, line_index, span_index)` 来源，无法区分独立 block 与同 block 的真实换行。
  - **模式判定**：`recover_cells_from_region()` 和 `recover_hybrid_body_cells()` 在 `region_spans()` 后调用 `infer_output_order_mode()`；区域内只有存在足够长、稳定且水平分离的纵向 native 轨迹时才判为 `columnar`，证据不足仍为 `row_interleaved`。591 页判定为 `columnar`，所有 80 个 span 均带可靠来源。
  - **合并边界与网格兼容**：`columnar` 路径跳过原有跨 block 顺序换行合并，仅在 span 到 atom 阶段合并同一 native block、相邻 source line、下方且水平重叠充分、字体兼容的真实换行；`merge_multiline_cells()` 同样拒绝跨 block 合并。已有列带、列标注、物理/逻辑网格、表头跨度、空槽位物化和 occupancy 检查继续复用。针对 row-interleaved 页面中“高的已合并文本框 + 同排短数值”中心点轻微错开的情况，`grid.py` 的物理行聚类增加垂直投影重叠且顶部对齐证据，避免兼容回归把一行拆成两行。当前目标页构建 63 个 atom，其中仅 1 个同 native block 换行 atom；最终表格为 `29x10`，290 个 Cell，63 个非空 Cell、227 个独立空 Cell，290/290 槽位恰好占用且无冲突。
  - **约束与验证**：中文/混合 native-span 结构恢复只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不回退 legacy 或 zebra 路径。聚焦回归为 `81 passed`，无线、网格、表头、有线和语言分流相关集合为 `173 passed`（仅既有 PyMuPDF/SWIG 弃用警告）。页面级输出位于 `D:\codes\PDFLayoutParser\output\fix_full_rerun_current_20260902_page591_output_order_final_grid_fix\`；结构化结果为 `pages\page-591.json`，最终可视化为 `tables\page-591.png`。视觉核验确认表格外框、10 列、29 行、项目列换行、右侧数值列及表外附注均未发生明显错位、误并或漏失。

- 重构并泛化中文无线表格与混合主体多行折行合并判定（`merge_multiline_cells`）：
  - **根因与问题**：在中文报表中，多行长字段折行常采用“首行缩进 2 格、次行顶格/回缩”的悬挂缩进排版（如 936 页“保证金、押金、质保金组”首行 $x=[98.5, 214.2]$，换行“合”次行顶格 $x=[88.0, 98.5]$，两行水平投影交集为 0）。过去硬卡 `_horizontal_overlap >= 45%` 的假设忽略了缩进与回缩折行形态，导致次行多行折行无法合并，在同一列槽位生成两个独立 Cell 并触发占用冲突（occupancy conflict），导致整表被丢弃。
  - **重构判定与调用位置**：在 `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 中，将 `_can_merge_multiline()` 的折行判定从单字拓展为支持列内左移/回缩折行与右侧空白见证。在同列、上下相邻、native flow 连续、字体字号兼容的前提下，满足以下任一条件均放行合并：
    1. 标准水平投影重叠 `_horizontal_overlap >= minimum_width * 0.45`；
    2. 具备实体长度（前行宽度 $\ge 4 \times \text{font\_size}$）且符合左移特征的短尾（单字短尾）；
    3. 右侧空白见证：次行所在物理行右侧其余列完全空白无数据（`row_columns.get(candidate["row_start"]) == {candidate["col_start"]}`），且非编号/列表项/纯数值。
  - **结构约束**：完全依托列带约束与逻辑网格拓扑决策，不提前在跨列阶段误并，不回读 `page.get_text("words")`，保持 0 Occupancy Conflict 契约。
  - **测试与页面验证**：新增多字左移短尾续写、右侧空白见证等正反例测试，全量结构与无线测试 `71 passed`。使用当前代码独立重跑 `fix/zh_all_table_pages.pdf` 页面索引 936 到 `D:\codes\PDFLayoutParser\output\verify_page_936_continuation\`：全部 3 张无线表格提取成功（14x5、8x5、8x5），首列“保证金、押金、质保金组\n合”成功合并为单个 Cell，Occupancy Conflict 为 0，可视化 PNG 为 `tables/page-936.png`。

- 定位并修复 `fix/zh_all_table_pages.pdf` 页面索引 430、455、961 的无线表格候选漏检。三页均有清晰表格，模型也分别给出 2、4、4 个有效检测框；真正的丢失点是 `TableExtractor.extract()` 在第 515 行遇到空的 native-span 候选后提前返回，模型没有被调用。
  - **根因与调用位置**：`src/hexai_pdf_parser/tables/wireless_table_recovery.py` 的 `_column_tracks()` 原先允许 `overlaps_previous` 单独触发列组并入。一条横跨多个真实列的说明/正文文本与前一列 bbox 轻微相交后，会继续桥接金额列，最终把真实列轨迹传递式合并为一组；430、455、961 的轨迹分别退化为 `[208.25]`、`[385.85]`、`[298.89]/[307.30]`，随后 `_build_table()` 以 `insufficient repeated visual rows or columns` 拒绝候选。
  - **修复判定**：列轨迹只依据重复 anchor 的容差聚类，保留数字右沿、标签左沿和货币后数字的既有规则；bbox 相交本身不再作为合并条件，避免跨列说明文字桥接独立列。新增跨列桥接回归测试，相关无线/结构/规则优先测试为 `74 passed`。
  - **页面验证**：当前代码独立重跑到 `D:\codes\PDFLayoutParser\output\target_pages_candidate_fix_20260902\`。430 恢复 2 张 `wireless_span_recovery`（7x2、2x3），455 恢复 4 张（9x3、8x3、6x3、5x3），961 恢复 4 张（6x3、6x3、3x3、3x3）；所有导出 Cell 均为完整槽位且 occupancy conflict 为 0，PNG 视觉复核确认相邻表格和说明文字未误并。
- 对同一批页面中的恢复空结果继续完成逐页定位：482 的 `R9C1` 是 `①` 与被错误分到同一窄列的“联营企业...”纵向续写冲突；586 的首列被错误扩成 `112.7..289.6`，把项目列与附注列合并，代表性冲突为“应付账款/注释12”等 8 组首列槽位，模型框还把 3 个连续报表片段作为一个区域；587 的大框把表外说明带入主体，最终 `R23C1`、`R25C1` 分别由编号“2.”、“1.”与后续说明续写占用同一槽位；944 的超宽多级表头把“追加/新增投资”与“减少投资”、“权益法下确认的投资损益”与“其他综合收益调整”、“其他权益变动”与“宣告发放现金股利或利润”分别压进同一列带。上述冲突均在 `recover_cells_from_region()` 第 113 行被拒绝并返回空，尚未在本次候选修正中放宽 occupancy 约束。936 旧输出中的 `R7C1` 长字段与左移单字“合”冲突已由当前工作区既有的左移单字续写规则消除，当前重跑为 3 张表；旧目录的 2 表结果属于修复前输出。

## 2026-09-02

- 修复扫描页仍进入原生文本/表格/图片提取的问题，并为扫描页保留固定 JSON 结构。根因是 `Loader` 已在 `src/hexai_pdf_parser/extractors/page_classifier.py` 通过空文本、乱码、Type3 缺少 `/ToUnicode` 和 bbox 失真等条件将页面判定为 `scanned`，但 `src/hexai_pdf_parser/core/pipeline.py` 的 `_run_page_pipeline()` 仍无条件调用 `TextExtractor`、`TableExtractor`、`ImageExtractor` 和布局构建；706 页的 Type3 `T2`、707 页的 Type3 `T3` 因失真文字和字形 drawing 被有线表格逻辑误生成 `line_projection` 伪表格。
  - **分流判定与调用位置**：在 `_run_page_pipeline()` 归一化页面后立即按 `page.page_type == "scanned"` 分流。扫描页只清空 `blocks`、`tables`、`images`、`seals`、`layout_elements`，继续生成页面渲染、单页 JSON 和 `tables/page-xxx.png`；不调用文本、表格、图片提取器或布局构建，也不生成单页 Markdown。复用旧输出目录时删除同名旧 Markdown；汇总 Markdown 由空的 `layout_elements` 自动排除扫描页。`PDFParser._has_content()` 将扫描页分类结果计为成功解析，保留既有 API code `1` 契约。
  - **固定结构与可视化**：扫描页 JSON 仍保留 `index`、`size`、`rotation`、`page_type`、`blocks`、`tables`、`images`、`seals`、`render`、`layout_elements` 全部字段，五类结果数组为空。新增共用 `page_type_label` 绘制逻辑，根目录页面 PNG、表格可视化 PNG、批量可视化预览均在左上角标注 `page_type: scanned` 或 `page_type: vector`。空表格可视化不再回读 `page.get_text("words")`；vector 页既有表格路径保持不变。
  - **测试与页面验证**：新增扫描分流、固定 JSON、Markdown 排除、旧 Markdown 清理、vector 保持输出和两类 PNG 标注测试；相关测试结果为 `74 passed, 32 skipped`（5 条既有 PyMuPDF 弃用警告）。使用 `fix/zh_all_table_pages.pdf` 独立重跑页面索引 706、707 到 `D:\codes\PDFLayoutParser\output\fix_full_rerun_scanned_pages_20260902\`：两页均为 `scanned`，blocks/tables/images/seals/layout_elements 均为 0，无单页 Markdown；根目录和 `tables/` PNG 均生成并通过视觉核验，未再出现 `line_projection` 伪表格。

## 2026-09-02

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 914 的有线/无线混合表格正文续写丢失：有线规则正确提供了表头、外框和 6 列边界，但主体恢复中的 native span 将 `一年内到期的非流动资` 与下一行左移的 `产` 生成了两个同列、同物理槽位的 Cell；`merge_multiline_cells()` 原先要求两段水平重叠至少 45%，因此拒绝合并，随后 occupancy conflict 使 `recover_hybrid_body_cells()` 返回空，入口回退为原始 `line_projection` 的 `3x6` 大 Cell。
  - **修复判定条件与调用位置**：在 `src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py` 的 `_can_merge_multiline()` 中保留普通多行片段的水平重叠保护；仅当 native flow 严格连续、同列且上下相邻、候选为下方左移的单个中文字符、上一行宽度至少为 4 个字号时，允许无水平交集的短尾续写合并。这样使用同一逻辑的普通无线恢复和 `src/hexai_pdf_parser/tables/wireless_structure/hybrid_body.py` 混合主体恢复都会覆盖该形态；同槽位的独立多字符标签仍保持分离。
  - **结构约束**：恢复顺序仍为 native span、atom、列带、物理 Cell、逻辑 Cell 和空槽位物化；不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 文本二次重建。跨度合并后继续执行 occupancy conflict 检查。
  - **测试与页面验证**：新增左移单字续写正例、独立标签拒绝反例及混合主体集成测试；无线结构及相关测试 `127 passed`。使用当前代码独立重跑页面索引 914 到 `D:\codes\PDFLayoutParser\output\page_914_left_shift_continuation_fix_20260902\`：表格由 `line_projection` 的 `3x6` 退化结果恢复为 `hybrid_line_span_recovery` 的 `41x6`、242 个 Cell，逻辑槽位覆盖 `246/246` 且 occupancy conflict 为 `0`；目标 Cell 文本为 `一年内到期的非流动资\n产`，相邻 `其他流动资产` 和 `流动资产合计` 保持独立。最终 PNG 为 `tables\page-914.png`。

## 2026-09-01

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 437（印刷页码 47）顶部表头被拆成伪空行的问题：原始横线只定义一个表头区间，但 native span 将第三列叶子标题拆成上下两段，`build_grid()` 因不同文字中心 y 生成两条物理行；`merge_multiline_cells()` 随后把该叶子 Cell 错误保留为 `rowspan=2`，`build_logical_grid()` 未压缩仅由该 Cell 占据的首行，`materialize_empty_cells()` 遂在其余列物化 4 个空 Cell。现在在 `logical_grid.py` 的 `_row_components()` 调用 `_wrapped_leaf_header_span()`，仅当候选是 `multiline_cell`、文本含换行、只跨相邻两条物理行、单叶子列、位于 `header_cutoff` 以上，且首物理行除它外无其他非空 Cell、下一行至少有两个同层级兄弟叶表头时压缩物理行；真实父表头/子表头或普通正文多行 Cell 不满足条件则保持原结构。逻辑网格随后统一重算 `row_start/row_end/rowspan`，不横向合并独立列，也不回读 `page.get_text("words")`。新增顶部换行叶子正例及真实父表头下方反例；专项测试 `82 passed`。使用当前代码重跑到 `D:\codes\PDFLayoutParser\output\page_437_header_row_collapse_fix_20260901\`：三张表仍独立，结构分别为 `14x5`、`6x5`、`3x6`；顶部第三列表头完整保留为单个 `rowspan=1` Cell，顶部表无空 Cell，三张表的 occupancy conflict 均为 0（中部表另保留 2 个真实空槽位）；最终 PNG 为 `tables\page-437.png`。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 450（印刷页码 60）递延收益表格中多行项目上方错误物化出多排空行的问题：
  - **根因分析**：
    1. 在 `text_runs.py` 的 Span -> Atom 阶段，`_is_wrapped_field_pair` 原先强制要求 `left["font"] == right["font"]`。在中文 PDF 排版中，年份/数字通常使用西文字体（如 `Arial Narrow`），而后续中文正文使用中文字体（如 `仿宋_GB2312`）。当多行字段首行以数字开头（如 `2019年...`、`2022年度...`、`2023年...`、`PLC...` 等）时，字体不匹配导致行与行之间合并被阻断，拆为多个独立 Atom；
    2. 对于 3~5 行的长段落项目（如 `调频连续波...`），伴随金额位于中间行，原 `_right_witnesses` 仅在局部两行高度查找见证者，导致前序行局部无伴随而拒绝合并；
    3. 同一 native 行内的连字符标点（如 `高质量发展专项资金-高功率外...` 中的 `-`）在 `_can_join` 中被 `_is_placeholder` 误判为独立占位符，造成行内拆分为两个同列 fragment 并触发槽位占用冲突；
    4. 拆分后的文本碎片在 `build_grid()` 中被分配到不同物理行，金额只能排在靠下的物理行；逻辑行折叠受阻后，`materialize_empty_cells()` 便在金额上方空槽位中填充了整排空单元格，形成视觉上的多余空行。
  - **修复判定条件与调用位置**：
    1. 在 `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py` 中，修改 `_is_wrapped_chain_pair`：取消对跨中西文字体（如 `Arial Narrow` 与 `仿宋_GB2312`）的硬性阻断，仅要求粗体状态（`bold`）一致、字号差距在 1.0pt 以内、流式严格连续（`flow_start == flow_end + 1`）且非纯数值行/占位符；
    2. 扩展 `_right_witnesses`：基于整个段落链（chain）的垂直包围盒及字体步进高度范围检查右侧见证者，支持伴随金额位于多行段落中间或底部的情形；
    3. 在 `_can_join` 中增加 `inline_punct` 判定：允许同一 native 行内紧贴文本（`gap <= 1.0pt`）的单字符连字符/标点正常连接，避免行内误拆。
  - **不回读 words 约束**：
    结构恢复阶段完全仅消费 native span、atom、列带、物理网格、逻辑网格及物理/逻辑 Cell，不回读 `page.get_text("words")`，不回退 `extract_zebra()` 或 legacy words 文本对齐重建。
  - **测试与验证结果**：
    新增专项测试 `tests/test_wrapped_field_font_and_witness.py`（正例 2 项、反例 3 项）；全量无线结构与相关测试 `84 passed`，`git diff --check` 通过。
  - **页面输出路径**：
    使用当前代码独立重跑页面索引 450 到 `D:\codes\PDFLayoutParser\output\zh_page_450_multiline_fix_20260901\`：表格由修复前的异常 `26x6`（含多余空行）恢复为规范的 `21x6`、126 个 Cell，逻辑槽位 `126/126` 完整覆盖且 occupancy conflict 为 0；所有多行项目名与右侧金额均正确归入同一逻辑行；最终可视化为 `tables\page-450.png`。

- 继续修复页面索引 437（印刷页码 47）底部中文无线表格的漏字和结构丢失：原始 native span 将同一视觉行的 `FRASERS PROPERTY`、`THAILAND INDUSTRIAL` 等同一粗列英文片段拆成多个 atom；粗列内尚未重组时，后续列归属和物理网格把它们当作两个 Cell，随后与同一记录的其他字段发生槽位冲突，恢复器整表返回空或留下错误切分。现在在 `recover_cells_from_region()` 完成初始列带推断后调用 `merge_same_band_native_line_runs()`，仅对同一粗列、同一 native block/line、flow 连续、同一视觉行、Latin 文本且水平间距合理的片段合并；跨粗列、中文/数值、不同 flow 或垂直排列均拒绝。换行 Cell 合并后将 `header_cutoff` 传入 `build_logical_grid()`，对正文首列跨多个物理行的覆盖区重新压缩逻辑行，再执行 occupancy 检查和空槽位物化。全程只消费 native span、atom、列带、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`。新增同粗列英文正例及跨粗列拒绝反例；无线相关测试 `113 passed`，`compileall` 和 `git diff --check` 通过。使用当前代码重跑到 `D:/codes/PDFLayoutParser/output/page_437_same_band_reflow_fix_20260901/`：上方、中间、下方三张表分别为 `7x5`、`14x5`、`3x6`，底部表格 18 个 Cell 覆盖 `18/18` 个逻辑槽位且无 occupancy conflict；首条记录恢复为 `FRASERS PROPERTY THAILAND INDUSTRIAL FREEHOLD & LEASEHOLD REIT`，最终 PNG 为 `tables/page-437.png`。

- 补充页面类型分类闭环：原页面分类器仅作为独立函数导出，未进入 `Loader`、`PDFParser`/`Pipeline` 主流程，也未写入页面模型和 JSON。现在 `Page` 保存 `page_type`，`Loader.load()` 为每页统一分类，进程 worker 显式传递该字段，`JSONWriter` 输出 `page_type`；分类仅做扫描页标记，不改变项目现有不执行 OCR 的边界。不可提取字符改为出现任一控制/替换字符即判 `scanned`；Type3 字体改为检查 xref 对象中的 `/ToUnicode`，覆盖混合字体页面并保留有效映射页面为 `vector`。新增 Loader、解析入口、JSON、位置参数兼容、混合 Type3、有效 ToUnicode、单异常字符和 process backend 回归测试；相关测试为 `92 passed, 32 skipped`，`fix/zh_all_table_pages.pdf` 全页抽样识别 79 个扫描页（索引 705-783），`compileall` 通过。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 437（印刷页码 47）中文无线表格的同槽位上下片段被 occupancy conflict 丢弃问题：`build_grid()` 按文字中心聚类物理行时，因不同列文字的 y 分布，`坏账准备/期末余额`、`1年以/内、1-2年` 和 `整个存续期预/期信用损失(已/发生信用减值)` 等同一字段的上下片段可能落入同一物理行；`merge_same_slot_fragments()` 不会把这种垂直排列误当横向 inline，而原 `_can_merge_multiline()` 只接受 `candidate.row_start == previous.row_end + 1`，导致片段无法合并、重复占用同一槽位，恢复器随后整表返回空。现在纵向合并允许候选位于前一 Cell 的同一物理行或下一物理行，但仍要求同列、native flow 严格连续、候选中心 y 位于前者下方、水平重叠/垂直间距/脚本兼容，并保留纯数值字段和列表续行保护；结构恢复只消费 native span、atom、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`。新增同一物理行正例和上下方向反例。相关无线测试为 `108 passed`。使用当前代码重跑到 `D:\codes\PDFLayoutParser\output\page_437_same_or_adjacent_row_verify_20260901\`：中间、上方、下方三张 `wireless_span_recovery` 表分别为 `14x5`、`7x5`、`5x7`；逻辑槽位覆盖分别为 `70/70`、`35/35`、`35/35`，occupancy conflict 均为 0。T6/T7、T21/T22、T11/T12/T13 均恢复为各自列内的单个多行 Cell；最终可视化位于 `tables\page-437.png`。
- 修复 `fix/zh_all_table_pages.pdf` 页面索引 791 的正常有线表格丢失空窄列问题：页面语言为 `mixed`，但规则检测命中显式线框，最终走 `line_projection`；原始物理网格含 25 个内部列，其中 `x=233.3..242.7` 为有完整横竖线的真实空列。`_assign_text_to_line_cells()` 按文字中心点归属时，`减：专项` 和 `库存股储备` 均落入左邻列，随后 `_merge_oversegmented_line_columns()` 将无文字列全部删除，导致首个年度表头错误变为 `colspan=7`、最终列数变为 24。现在仅删除极薄边框残片，或被非空跨列 Cell 完整覆盖的伪列；独立空 Cell 保留。新增真实空列回归测试。重跑输出位于 `D:\codes\PDFLayoutParser\output\page_791_rerun_20260901_wired_empty_column_fix\`：表格为 `39x25`、818 个 Cell，逻辑槽位 `975/975` 覆盖且无冲突，三组年度表头均为 `colspan=8`；最终 PNG 视觉核验通过。修改仅作用于有线 Cell 后处理，不改变无线 native-span 路径及其不回读 `page.get_text("words")` 的约束；有线和无线拆分专项测试为 `27 passed`。
- 继续修复页面索引 791 的有线表头文字归属：确认 `减：专项` 的“专项”、`库存股储备` 的“储备”字符 bbox 实际位于 `x=233.3..242.7` 窄 Cell 内，但原逻辑按整词中心点将整词写入左 Cell。`_assign_text_to_line_cells()` 现在仅对同时覆盖多个物理 Cell、且 raw 字符 bbox 能完整重建的词按字符中心拆分，普通词仍使用原中心点回退；该修改不改变有线线拓扑，也不进入无线 native-span 路径。重跑输出位于 `D:\codes\PDFLayoutParser\output\page_791_rerun_20260901_wired_column_text_split_fix\`：四个目标表头 Cell 文本均正确，前后页面文本仅有这 4 处预期变化；有线和无线拆分专项测试为 `28 passed`，`compileall` 通过。
- 按页面语言拆分无线表格提取实现：英文斑马纹、英文通用无线和英文文本对齐逻辑移入 `src/hexai_pdf_parser/tables/extractors/english_table_extractor.py`；中文/混合页面的 native-span 恢复移入 `src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py`。`wireless_table_extractor.py` 缩减为兼容门面，由 `WirelessTableExtractor.extract()` 和 `extract_text_alignment_candidates()` 负责语言分流；`TableExtractor._extract_via_text_alignment()` 通过该门面调用。中文/混合路径跳过 `extract_zebra()` 和 legacy words 重建，结构恢复阶段不调用 `page.get_text("words")`；英文路径保留原有 legacy 回退能力。旧的 `WirelessTableExtractor`、`_RowData`、`recover_cells_from_region` 导入和 monkeypatch 路径继续可用，包级及顶层英文/中文别名同步导出，降低两方并行开发时的合并冲突。
- 新增 `tests/test_wireless_extractor_split.py`，覆盖英文/中文模块归属、顶层别名、语言分流、旧 monkeypatch 路径以及中文不回读 words。相关无线恢复、结构网格、规则和财务表头测试为 `132 passed`，`python -m compileall -q src` 通过。使用 `fix/zh_all_table_pages.pdf` 的 0-based page index `0` 重跑到 `D:\codes\PDFLayoutParser\output\language_split_page_000_20260901\`：得到 1 张 `line_projection` 表，结构为 `8x2`、16 个 Cell；结构化结果为 `pages\\page-000.json`，最终 PNG 为 `tables\\page-000.png`，视觉核对确认表格外框、列线、行线和空槽位均正常。历史 `tests/test_table_extractor.py` 当前为 `85 passed, 20 failed`；失败包含基线中同样存在的旧英文边界/货币及文本对齐期望、缺失样本 PDF 和模型路径期望，未发现本次拆分新增的模块导入错误。

## 2026-08-31

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 371 的局部混合表正文被压成一个有线 Cell 的问题：原表只有外框/列线和表头、汇总行横线，主体 9 组文字之间没有横线；混合入口把主体区域交给完整无线恢复器后，首个编号正文被表头列带推断拆成伪列并触发 occupancy conflict，恢复返回空，入口于是保留 `line_projection` 的大 Cell。现在新增 `wireless_structure/hybrid_body.py`，由 `TableExtractor._recover_hybrid_wired_table()` 传入有线主体列边界，正文只使用 `collect_native_spans -> region_spans -> build_text_runs`，按可信有线列带归属，不执行表头 cutoff/列带推断，也不回读 `page.get_text("words")`。之后复用现有 native 同槽位顺序合并、多行 Cell 合并、物理/逻辑网格、`rowspan/colspan`、空槽位物化和 occupancy conflict 校验；轻微越过列线的字形按中心列处理，只有两侧均有实质覆盖才认定 `colspan`。恢复失败仍保留原有有线结果，表格 `h_lines/v_lines` 原样携带到最终结果。
- 新增 page-371 风格正文拆行、跨列跨度、独立同槽字段拒绝和跨度占用冲突回归测试；`tests/test_hybrid_body_recovery.py` 为 `4 passed`，有线、规则优先及无线结构专项测试均通过。使用当前代码重跑 0-based page index `371` 到 `D:\codes\PDFLayoutParser\output\page_371_hybrid_body_recovery_verify_20260831\`：得到 1 张 `hybrid_line_span_recovery` 表，结构为 `11x3`、33 个 Cell，其中 23 个非空、10 个独立空槽，occupancy 覆盖 `33/33` 且无冲突；表格 bbox 为 `[126.0,191.7,510.8,517.0]`。最终 PNG 为 `tables\page-371.png`，视觉核对确认外框、9 个正文行、第二列金额和第三列空槽位均正确，表下注释及相邻内容未被吸收。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 417 的小型有线框被误识别为 `3x1`：该框实际是约 `0.48pt` 厚的黑色 `type="f"` 填充路径，drawing 同时暴露了上下两条 `l` 边缘；现有 `merge_group_tol=0.3` 小于边缘间距，导致同一条粗线被当成两条横线，随后生成三行一列并绕过原有单 Cell 过滤。现在在 `WiredTableExtractor._extract_lines_from_drawings()` 中，对可见的窄填充 drawing 按 `rect` 取几何中心线，并跳过其内部边缘项；只在厚度满足线候选条件时触发，不调整全局合并阈值，也不新增 `page.get_text("words")` 读取。
- 新增粗填充路径边缘折叠回归测试，保留单框拒绝和多单元格有线表格正例。使用 `fix/zh_all_table_pages.pdf` 重跑 0-based page index `417` 到 `D:\codes\PDFLayoutParser\output\page_417_filled_rule_centerline_fix_20260831\`：最终仅有 1 张 `english_general_wireless` 表，结构为 `25x3`、75 个 Cell，未出现 `line_projection` 小表；`pages\page-417.json` 与 `tables\page-417.png` 已核对，PNG 未见独立 `3x1/1x1` 误报。`tests/test_wired_table_extractor.py` 为 `19 passed`；扩展有线、表格提取和可视化测试为 `99 passed, 19 failed`，失败均为既有旧接口/模型路径期望、缺失样本 PDF 或旧模块导入问题。
- 修复页面索引 417 的英文无线表格将 `Note` 列并入最左描述列的问题：表格横线只覆盖两个金额列，`_detect_columns_from_header_underlines()` 原先把首条横线左侧的所有文字压成一个 leading stub，因而得到 `描述、2011、2010` 三列。现在在同一方法中，仅当横线左侧存在至少两个跨多行重复、且至少两行与左侧文本区间共现的文字区间时，将其作为前置列骨架；不依赖 `Note` 等业务文字，并拒绝交替缩进造成的伪列。新增前置窄列正例和交替缩进反例。重跑到 `D:\codes\PDFLayoutParser\output\page_417_note_column_fix_20260831\` 后，`pages\page-417.json` 仅有 1 张 `english_general_wireless` 表，结构为 `25x4`、100 个 Cell，`Note` 位于 `r0c1`；`tables\page-417.png` 视觉核验确认四列边界与表格主体对齐，注释编号框均属于真实 Note 单元格。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 428 的无线表格漏检：原始四列表格的首个正文行含 `50.00`、`50年`，后续备注换行又形成更高的稀疏文字层；`_header_cutoff()` 的通用最大间距规则把备注续行误判为表头，`refine_leaf_bands()` 随后将第四列中的 `销，无合同年限按照` 与 `10年摊销` 切成两个伪叶列，`土地证使用期限` 和 `50年` 跨列后触发 occupancy conflict，整表被丢弃。现在在 `_header_cutoff()` 的通用大间距启发式之前统计重复出现的、非结构化且非日期表头的数值正文层；至少出现两层时，以首个数值层与前一层之间作为正文边界。该修复只影响表头下界推断，继续消费 native span/atom，不回读 `page.get_text("words")`，不改变中文数字通用合并规则。新增 page-428 风格回归测试。使用 `conda run -n base` 重跑页面索引 428 到 `D:\codes\PDFLayoutParser\output\page_428_header_cutoff_fix_verify_20260831\`：恢复 1 张 `wireless_span_recovery` 表，结构为 `5x4`、20 个 Cell，occupancy conflict 为 0，第四列备注及 `土地证使用期限50年` 均保持在单列内；最终 PNG 为 `tables\page-428.png`。无线结构、表头、有线及恢复相关测试为 `102 passed`；`tests/test_table_extractor.py` 为 `77 passed, 19 failed`，失败为既有旧路由/模型路径期望、缺失样本 PDF 和旧模块导入问题。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 419 的局部有线框误判：经营分部利润表中的两个数值区原本各自形成 `1x1 line_projection` 候选，模型整表区域与其重叠时被有线优先逻辑拦截，导致真正的无线表格未进入提取。现在在既有 Cell 文字归属和空边列压缩后，若区域最终只剩一个 `rowspan=1`、`colspan=1` 的 Cell，则丢弃该有线区域；过滤只复用已有 Cell，不新增 `page.get_text("words")` 读取，多单元格有线表格保持原路径。
- 新增单框 `1x1` 拒绝反例和 `1x2` 有线表格保留正例。重跑 `fix/zh_all_table_pages.pdf` 0-based page index `419` 到 `/mnt/d/codes/PDFLayoutParser/output/page_419_single_cell_filter_20260831/`：结果由两张 `1x1 line_projection` 变为一张 `7x4 english_general_wireless`，bbox 为 `[63.1,487.7,544.3,663.9]`；原始页图和表格可视化图均确认完整覆盖标签列及数值列，无 `1x1` 标注或明显误并。`tests/test_wired_table_extractor.py tests/test_rule_first_table_detection.py` 为 `24 passed`。
- 修复 `fix/zh_all_table_pages.pdf` 中文页面索引 357 顶部有线表格漏掉首列的问题：表格 bbox 从 `x=88.6` 开始，但实际多条横线从 `x=121.6` 开始，已有竖线最左仅到 `x=267.3`，导致 `_build_cells_for_region()` 只生成右侧 4 列，`种类` 和左侧分类文本无法归属。现在仅当至少 3 条横线共享一个明显晚于 bbox 左边界、且位于已有最左竖线左侧的起点时，补入该起点贯穿表格高度的虚拟竖线；已有竖线或 bbox 边界附近的横线不触发。该修复位于 `WiredTableExtractor._build_cells_for_region()`，只影响有线 Cell 网格构造，不回读 `page.get_text("words")`，不进入无线表格恢复路径。
- 新增重复横线起点恢复首列的回归测试。重跑 `fix/zh_all_table_pages.pdf` 0-based page index `357`（中文页面）到 `/mnt/d/codes/PDFLayoutParser/output/page_357_missing_leading_column_20260831/`：页面共 5 张 `line_projection` 表，按输出顺序为 `10x5` `[88.6,79.8,508.9,266.3]`、`8x7` `[119.8,309.8,515.4,482.9]`、`2x5` `[119.8,701.4,515.4,766.4]`、`2x5` `[119.8,613.9,515.4,657.9]`、`2x6` `[119.8,526.4,515.4,570.4]`；首表恢复 `种类` 的 `rowspan=3` 及左侧正文列，五张表逻辑槽位均完整占用且 occupancy conflict 为 `0`。最终页面图为 `page-357.png`，表格网格图为 `tables/page-357.png`。
- 验证结果：`tests/test_wired_table_extractor.py` 为 `16 passed`；无线结构与财务表头相关专项为 `36 passed`；扩展运行 `tests/test_wired_table_extractor.py tests/test_table_extractor.py tests/test_table_visualizer.py` 为 `96 passed, 19 failed`，19 项为既有旧期望、缺失样本 PDF、版本/环境差异和旧模块导入问题。
- 修复 `fix/zh_all_table_pages.pdf` 中文页面索引 432 第（3）节两块无线财务表中“坏账准备”父表头被切成单列的问题：原始文字和正文数值均完整，但“预期信用损失率(%)”被 native span 拆成上下两个 header atom，原 `_infer_two_leaf_parent_spans()` 要求所有叶子必须位于同一 y 层且叶子数量严格为父标题数量的两倍，因而只把“坏账准备”归到第 4 列。新增 `_infer_wrapped_two_leaf_parent_spans()`，仅按同一叶列的上下 header atom、连续列带、父标题与两叶列组中心对齐（允许不等宽叶列的最多 10% 几何偏差）及所有父标题成组通过来恢复 `1:2` 拓扑；不依赖业务文字，不回读 `page.get_text("words")`，文本换行仍由后续 native-span Cell 流程处理。
- 新增垂直换行叶表头和不等宽叶列中心偏移回归测试。重跑 page index `432` 到 `/mnt/d/codes/PDFLayoutParser/output/page_432_bad_debt_parent_span_20260831/`：页面共 4 张 `wireless_span_recovery` 表，结构为 `7x6`、`7x6`、`4x3`、`2x2`；两块目标表各覆盖 `42/42` 个逻辑槽位，occupancy conflict 均为 `0`，两处“坏账准备”均为 `colspan=2`，换行的“预期信用损失率(%)”保持独立叶列。最终表格 PNG 位于 `tables/page-432.png`，视觉检查确认两块主表独立成框且未误并。
- 相关无线表格、无线结构和财务表头测试为 `97 passed`。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 432 下方两张无线财务表在换行字段合并后被整表拒绝的问题：模型已以 `0.9778`、`0.9767` 检出两张表，根因是 `merge_multiline_cells()` 将“账面价值”和“预期信用损失率(%)”分别记录为跨物理行字段后，旧 `_row_components()` 按所有 `rowspan` 做传递并集，把仍含“金额”“比例”等独立字段起点的物理行 2、3、4 压成同一逻辑行，导致第 2、4 列出现 occupancy conflict，`recover_cells_from_region()` 返回空结果。现在逻辑网格在换行文本合并完成后重新划分行：仍有 Cell 从该物理行开始时保留为结构锚点行；仅无 Cell 起点、只承载前一字段续行的物理行折叠到上一逻辑行。这样“账面价值”保留为单个 `rowspan=2` Cell，“预期信用损失率(%)”保留为单个换行文本 Cell，同时相邻父表头和叶子表头位于不同逻辑行。修改只消费既有 native span、atom、物理 Cell 和逻辑 Cell，不回读 `page.get_text("words")`，不进入 `extract_zebra()` 或 legacy 无线重建。
- 新增链式换行表头重划分正例，并保留纯续行压缩正例及独立字段拒绝误合并反例。无线结构、有线表格与财务表头相关测试为 `110 passed`。独立单页输出位于 `D:\codes\PDFLayoutParser\output\page_432_logical_row_redivide_20260831\`：页面共 4 张 `wireless_span_recovery` 表，按模型输出顺序为 `7x6`、`7x6`、`4x3`、`2x2`；两张目标表各覆盖 `42/42` 个逻辑槽位、occupancy 冲突均为 0，最终 PNG 位于 `tables/page-432.png`。
- 收紧 page index `432` 顶层父表头的中心对齐合并：候选 `colspan` 只有在父标题所在物理表头行的目标列带没有其他非空文本占用时才接受；下方子表头仍作为跨度证据，不被误当作冲突。占用判断按同层文字实际实质覆盖的列带计算，避免文字跨列但中心点落在邻列时漏检；同时修复候选中心偏差分支提前 `continue` 未推进游标造成的恢复死循环。该路径继续只消费 native span、atom 和列带，不回读 `page.get_text("words")`。新增跨边界同层文字拒绝合并反例，表头专项 `20 passed`，无线结构相关专项 `38 passed`。
- 使用当前代码重新生成 `/mnt/d/codes/PDFLayoutParser/output/page_432_top_parent_span_empty_slots_20260831/`：4 张 `wireless_span_recovery` 表，前两张均为 `7x6`；两处 `期末余额`/`上年年末余额` 均为 `col_index=1`、`colspan=5`，`类别` 为左侧独立列，`账面价值` 为第 6 列 `rowspan=2`，`坏账准备` 为 `colspan=2`。两张目标表均覆盖 `42/42` 个逻辑槽位，occupancy conflict 为 `0`，无空槽位被非空 Cell 覆盖；最终 PNG 为 `tables/page-432.png`。

## 2026-08-30

- 修复 `line_projection` 有线表格被 `_GROUP_LABEL_PATTERNS` 二次表头归一化覆盖的问题：有线 Cell 已经由横竖线拓扑确定 `rowspan/colspan`，`normalize_table_headers()` 现在在 `table.source == "line_projection"` 时直接保留该结构，`normalize_complex_financial_header()` 的第二个调用入口也同步跳过有线表格；无线/文本对齐路径的关键词表头逻辑保持不变。该分支只消费已有 Table/Cell，不回读 `page.get_text("words")`。新增并列关键词保持独立、已有跨列跨度保持不变以及二次入口保护测试。
- 修复 `WiredTableExtractor._merge_oversegmented_line_columns()` 删除空列后只重映射 `col_index`、未同步更新 `colspan` 的问题：按原始 Cell 跨度中仍保留的列数量重算 `colspan`，并保留原有空列压缩逻辑。新增空列压缩跨度回归测试。
- 相关专项测试为 `36 passed`（财务表头、有线提取器、无线结构网格/恢复器）。包含 `tests/test_table_extractor.py` 的扩展测试为 `95 passed, 19 failed`；失败来自既有路由/版本期望、缺失旧样本 PDF 和旧模块导入，与本次修改无关。
- 使用 ML 模式重跑 `fix/zh_all_table_pages.pdf`（1,023 页），输出位于 `E:\code\PDFLayoutParser\out_fix_ml_feature_dev_20260830_rerun\`，包含页面 JSON、表格 PNG 和 `debug/pipeline` 可视化。当前运行环境的 ONNX Runtime 仅提供 `AzureExecutionProvider`/`CPUExecutionProvider`，未启用 CUDA；因工作区保留用户已有 `remove_rotation()` 改动，运行时临时提供等价的 `set_rotation(0)` 兼容别名，未修改该文件。
- 全量 Cell 逻辑槽位扫描结果：占用冲突 `0` 页、`0` 槽位；冲突专用目录为 `out_fix_ml_feature_dev_20260830_rerun/overlapping_cell_positions/`。全部异常图集中在 `out_fix_ml_feature_dev_20260830_rerun/problematic_pages/`（84 页），另有 `_GROUP_LABEL_PATTERNS` 关键词页集中在 `out_fix_ml_feature_dev_20260830_rerun/keyword_group_label_pages/`（123 页、260 个表格记录），其中有线关键词 Cell 43 个为 `colspan>1`、276 个保持 `colspan=1`，供后续逐页视觉核验。

## 2026-08-28

- 修复旋转页面上下外边界缺失导致有线表格列内容未生成的问题：page-506 原始页面视觉上缺少上下两条外边界，页面归一化后表格 bbox 仍能通过相交线段确定 `y0/y1`，但 `WiredTableExtractor._build_cells_for_region()` 之前只将 `bbox.x0/x1` 和虚拟左右竖线纳入 Cell 网格，没有对称处理 `bbox.y0/y1`。现在横向边界集合加入 bbox 上下界，并在缺少对应物理横线时建立有效的逻辑上下横线，使边界 Cell 能通过后续 outside 检查。修改仅发生在有线表格 Cell 构造阶段，不修改 PDF 内容流、不回读或重建文字。新增上下边界缺失回归测试；`tests/test_wired_table_extractor.py` 为 `14 passed`，规则优先测试为 `6 passed`。独立重跑输出位于 `D:\codes\PDFLayoutParser\output\page_506_rotation_boundary_fix_20260828\`：page-506 表格从 `9x8` 恢复为 `11x8`，此前未分配的 5 个金额全部回到对应 Cell，PNG 视觉检查确认上下边界、网格和文字对齐。扩展 `tests/test_table_extractor.py` 仍有 19 个既有环境/缺失样本/版本期望失败，与本次改动无关。

- 修复 Type3 字体字形路径被误识别为有线表格的问题：页面 726/727 使用 `T54` Type3 字体，PyMuPDF 1.26 会同时提供文本字符和字形内部 drawing，原逻辑将字形中的短横竖笔画送入 `line_projection`。现在根据 Type3 字符的 `origin`、字号和字符步进重建局部视觉区域；完整落入单字符区域的 drawing 在物理线候选入口过滤，不使用该字体异常的原始 char/word bbox。跨字符长线、可见矢量虚线、黑色填充细线和 `1x1/2x2` 图像 tile 恢复均保持原路径。调试可视化同时将绿色文字框裁剪到对应 Cell 网格内，避免异常 Type3 word bbox 跨行、跨表显示。新增异常 Type3 bbox、真实长表格线保留和绿色框裁剪测试；相关测试 `35 passed`。独立页面输出位于 `D:\codes\PDFLayoutParser\output\type3_glyph_filter_20260828_v2\`：页面 726 从 9 张候选降为 1 张真实 `3x2` 表，页面 727 从 5 张降为 4 张真实表；页面 350/351/352/353/355 的表格数量与结构保持不变。

- 修复旋转页面的表格可视化坐标错位：解析阶段和主页面渲染已移除页面 rotation，但表格可视化重新打开 PDF 时未执行同样的归一化，导致 page-506 的红色外框、蓝色网格和绿色文字框与旋转后的原始内容错位。现在可视化入口对传入及重新打开的页面统一调用 `normalize_page_rotation()`；新增回归测试覆盖重新打开旋转页面的路径。

- 增加中文/混合财务表格的局部混合回退：当有线结果包含异常高的主体行 Cell 时，保留原有表格 bbox、表头和汇总行，仅将主体区域交给 native-span 恢复器按文本行拆分；恢复后的 Cell 按有线主体列几何回填，并为未填列物化空 Cell。恢复失败或 occupancy 冲突时保留原有 `line_projection` 结果，不升级为整表无线。新增主体局部回退正例和普通高度有线表反例；native-span、有线及规则优先相关测试通过。未执行页面级重跑，待接入实际 PDF 后验证 `hybrid_line_span_recovery` 的行数、金额配对和 PNG 边界。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 439、440 的模型候选在 native-span 结构恢复阶段丢表：span 到 atom 阶段仅在 native flow 严格连续、上下几何兼容且后续存在右侧字段见证时组合多行字段，连续金额、占位符、flow 跳跃和按行输出的独立字段保持分离；同一 native 行内带正常字距的单字中文可先组合为完整字段。page-439 的中央多行正文 atom 此前又因整体 bbox 高度被误当作单行字高，未能补成独立列带；现在列间距判定使用字体/单行高度，并只在表头对补出列带存在唯一实质覆盖时归入该列，避免中央表头被就近塞入右列。表头跨度改为在基础逻辑网格副本上事务式推断，新增跨度发生 occupancy conflict 时整层回退基础网格，不再丢弃整表。整个结构路径只消费 native span、atom、列带和 Cell，不调用 `page.get_text("words")`，也不回退 legacy 无线重建。相关专项测试为 `79 passed`。独立重跑输出位于 `D:\codes\PDFLayoutParser\output\page_439_440_native_span_conflict_20260828\`：page-439 两张 `wireless_span_recovery` 表分别为 `6x3`、`2x3`，page-440 为 `3x13`；三表逻辑槽位分别覆盖 `18/18`、`6/6`、`39/39`，occupancy 冲突均为 0，page-439 下表唯一空槽保持独立 `1x1`。

## 2026-08-28

- 修复部分中文有线表格以连续微小图像块编码时无法识别的问题：有线提取器在既有 drawing 线之外，补充将同一水平/垂直方向上连续、共线且长度至少 20pt 的 `1x1`/`2x2` 图像 tile 恢复为线候选，并保留页面裁剪及原有连通组件过滤。这样页面 350 的确定组合表不再退回无线逻辑，页面 353 下方和 355 中部的有线表格也能被规则候选发现。新增 tile 线恢复回归测试；有线专项测试为 `10 passed`。页面独立输出位于 `D:\codes\PDFLayoutParser\output\dashed_image_rules_20260828\`：350 为 1 张 `line_projection`（2x2），351 为 2 张（5x3、3x1），352 为 1 张（3x4），353 为 2 张（4x3、2x2），355 为 3 张（13x7、3x3、4x3），此前漏检的 353 下方及 355 中部表格已恢复。

## 2026-08-28

- 修复模型表格候选框扩张递归吸收文字及整页背景图形导致的整页误表问题：`MLTableDetector._expand_bbox_to_touching_words()` 现在只以原始模型 bbox 为交集基准遍历一次文字并取并集，不再读取 `page.get_drawings()` 扩张，页面边界裁剪逻辑保持不变。新增直接相交、拒绝链式扩张和忽略整页背景矩形回归测试；模型检测专项及规则优先测试为 `9 passed`。重跑 `fix/zh_all_table_pages.pdf` 页面索引 `113、123、132、135`，独立输出位于 `D:\codes\PDFLayoutParser\output\model_bbox_single_pass_20260828\`：四页均无 `wireless_span_recovery` 整页表，仅保留 `line_projection` 独立表格，分别为 `3、2、6、3` 张；所有结果 occupancy 冲突为 0。PNG 视觉复核确认表格之间的章节标题、说明文字、注释和页脚均未被误并。

## 2026-08-28

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 193 底部有线表格漏检：根因是该页表格线由 `stroke color=None`、黑色 `fill` 的细矩形组成，而 `WiredTableExtractor._extract_lines_from_drawings()` 将所有无描边 drawing 一律排除，原始横竖线因此均为 0。现在于 drawing 到物理线候选的入口，通过低分辨率页面渲染九点采样估计主背景色；无描边 drawing 仅在无填充或填充色与背景色足够接近时排除，黑色等可见填充细矩形继续进入既有相交、连通组件和封闭 Cell 恢复。该修改不触及无线 native-span、atom、列带或逻辑 Cell 路径，也不新增 `page.get_text("words")` 调用。新增黑色填充线正例、非白背景色比较正例，并保留白色填充页边框拒绝反例；有线提取器专项测试为 `9 passed`。包含 `tests/test_table_extractor.py` 和规则优先测试的扩展结果为 `90 passed, 19 failed`，19 项来自既有路由/模型期望差异、缺失 `152590_20230428_N7ZK_0.pdf` 和旧模块缺失。页面独立输出位于 `D:\codes\PDFLayoutParser\output\page_193_wired_fill_background_20260828\`：恢复 1 张 `line_projection` 表，bbox 为 `[55.44, 676.08, 567.24, 815.88]`，结构为 `4x10`、14 个逻辑 Cell、40 个槽位全覆盖且 occupancy 0 冲突；最终 PNG 确认底部表格边界和主要行列线对齐，上方正文未被吸收，中部字符槽、填写线及独立复选框未被误识别为额外表格。

- 修复 `fix/zh_all_table_pages.pdf` 页面索引 191 下方无线表格的换行字段未合并问题：根因是 `注册/地址`、`与本公司/关系`、`业务/性质`、`法定/代表人` 和 `本公司实/际控制人` 在 span 到 atom 阶段保持为上下两个 run，其他列的居中文字在物理网格中插入中间行后，网格后的 multiline 逻辑又因物理行不相邻而拒绝组合。现在于 `build_text_runs()` 返回前，仅在同一 native block/source line、flow 连续、字体/粗体/脚本兼容、上下 bbox 不重叠、横向重叠充分、垂直间距紧密、存在非竞争性交错行且候选唯一时组合换行字段；纯数字、占位符、视觉行互相重叠和没有交错行证据的连续记录保持独立。该调用只消费 native span 派生数据，不回读 `page.get_text("words")`，不修改 `extract_zebra()`、legacy `_rebuild_text_aligned_table()`、列带或逻辑网格路径。新增目标正例、无交错行和视觉行重叠的拒绝误合并反例，以及 `3x7` recoverer 集成测试；无线结构、有线表格与财务表头相关测试结果为 `51 passed`（另有 5 条既有 PyMuPDF/SWIG 弃用警告）。页面独立输出位于 `D:\codes\PDFLayoutParser\output\page_191_wrapped_field_merge_20260828_reviewed\`：页面仍有 3 张 `wireless_span_recovery` 表，目标表 bbox 为 `[92.0, 671.5, 488.0, 771.7]`，恢复为 `3x7`、21 个 Cell、occupancy 0 冲突；最终 PNG 确认五组换行文字均位于单一 Cell，额外伪横线消失、七列边界连续且相邻表格未误并。

## 2026-08-27

- 修复第 192 页真实表格候选在 native-span 恢复阶段丢失或列数错误的问题：禁止独立中文字段 Span 与后续完整数值 Span 跨列合成 atom；只使用原生 `char_boxes`，按整个空白字符 run 内的显著间距将金额、比例和占位符拆为多个字段，不回读 page words；最低层表头细化复用有效重叠判定，避免邻列标题约 1.3pt 的擦边相交制造伪列。重跑 `fix/zh_all_table_pages.pdf` 第 192 页（0-based），页面从上到下三张表均为 `wireless_span_recovery`，结构为 `2x5`、`5x9`、`5x5`，全部占位无冲突；最终输出位于 `output/page_192_span_atom_boundary_fix3/`。无线结构与财务表头专项测试 `48 passed`。

- 修复第 192 页中、下两张表的二叶子列多级表头：依据同层父标题与下一层连续叶子列的完整 `1:2` 拓扑配对恢复 `colspan=2`，不依赖“年初数/金额/比例/坏账准备”等文字；在物理行压缩为逻辑网格后、空单元格物化前，才将已证实父标题和独立首列表头扩展到空表头槽位，避免提前设置 `rowspan` 导致行压缩冲突，整个过程只消费 native span/atom 与逻辑 Cell，不回读 page words。重跑 `fix/zh_all_table_pages.pdf` 第 192 页（0-based），三张表仍为 `wireless_span_recovery`：上表 `2x5`，中表 `5x9` 的四个父标题分别覆盖两列且“企业名称”覆盖完整表头，下表 `5x5` 的两个父标题分别覆盖两列且“项目”覆盖完整表头，全部占位无冲突；视觉检查确认组内父标题竖线消失、组间边界保留且无独立空白表头格。输出位于 `output/page_192_group_header_spans/`，无线结构与财务表头专项测试 `54 passed`。

- 修复第 189 页同一标签列因“正文左对齐、表头/合计居中”被拆成两个列带的问题：在网格构建前识别行占用互斥、纵向位于正文范围之外、间距显著小于后续金额列间距的首部弱对齐列带，并将其删除后重新编号；规则不依赖“项目/合计”等关键字。重跑 `fix/zh_all_table_pages.pdf` 第 189 页（0-based），页面从上到下三张表恢复为 `6x3`、`4x3`、`4x3`，全部导出槽位完整且无占位冲突；输出位于 `output/page_189_sparse_alignment_fix/`，无线结构与财务表头专项测试 `43 passed`。

- 修复第 188 页普通三列表头被误识别为分组财务表头的问题：移除仅由“目/计”等少量第二字符形成、且可与左侧同行前驱连续配对的伪列带；`wireless_span_recovery` 结果不再进入旧财务表头提升逻辑，也不再回读 page words 重写已恢复的 `rowspan/colspan`。重跑 `fix/zh_all_table_pages.pdf` 第 188 页（0-based），三张表为 `10x3`、`8x3`、`3x5`，所有导出单元格占位无冲突；最终图片位于 `output/page_188_paired_cjk_fix_final/tables/page-188.png`。

- 将 `zh`/`mixed` 页面的 native-span 无线表格 source 标记为既有的 `wireless_span_recovery`，使其跳过 legacy `_rebuild_text_aligned_table()`，避免已组合 span 的逻辑网格被 page words 二次重建覆盖；英文、有线及旧 `text_alignment` 路径不变。
- 将中文/混合页面的无线表格生产调用切换到 native-span 结构恢复适配器；保留旧 `extract_cells_from_region` 代码，英文和有线表格逻辑不变；新增适配器与分流回归测试。
- 修复模板区域规则路径对不存在的 `_zh_wireless` 属性的引用，改为调用新的 native-span 无线结构恢复适配器。
- 将无线表格文本条普通连接阈值由 `2 * normal_gap` 调整为 `normal_gap`，并增加表头列间距回归测试；第 184 页中间表恢复到 7 列，但下面稀疏表退化为 4 列，后续需单独处理分隔线对列带推断的干扰。
- 修复 native-span 无线结构恢复中长 `=====`/`-----` 排版线桥接列带、短 `---` 占位被整行删除或参与词距合并的问题：长规则线按连续 separator run 删除，短占位独立保留且不参与普通 gap 估计，普通连接阈值不再超过 `0.8 * font_size`。
- 将同槽位宽字距合并限制为 source block/line 相同、flow 连续的单个 CJK 字符对，用于恢复“合/计”，不再将“比例/坏账准备”跨槽聚合；多行中文 continuation 的垂直间距上限调整为 `1.0 * font_size`。
- 增加合并后物理/逻辑槽位冲突校验，并在物理行压缩为逻辑行后重新计算 `rowspan`，避免多行首列单元格继续覆盖后续逻辑行。
- 重跑 `fix/zh_all_table_pages.pdf` 第 184 页（0-based），语言检测为 `mixed`，页面从上到下三表均为 `wireless_span_recovery`，结构为 `3x3`、`7x7`、`5x7`，最终占位无冲突；输出位于 `output/page_184_structure_fix2/`。无线结构专项测试 `23 passed`；包含 `tests/test_table_extractor.py` 的扩展测试为 `98 passed, 19 failed`，失败来自既有路由行为差异、缺失 `152590_20230428_N7ZK_0.pdf`、旧模块缺失和模型路径期望。
- 将 native-span 恢复后的最终逻辑网格完整物化：所有未被现有 rowspan/colspan 覆盖的槽位各生成独立 `text=""`、`1x1` Cell，不回读 page words，不合并相邻空槽；空槽 bbox 使用表格外边界、相邻列带中点和逻辑行轨道中点生成。
- `wireless_span_recovery` 补齐到 `rows * cols` 后仍使用推断网格可视化，避免完整 cell 数触发 direct-bbox 快捷路径而造成表头断线。第 184 页最新输出位于 `output/page_184_empty_cells/`：顶部/中部/底部分别为 9、49、35 个 Cell，中部和底部各含 12 个独立空 Cell，所有槽位恰好占用一次；PNG 中两层表头横线贯穿全表，七列竖线连续穿过空槽。相关专项测试 `27 passed`；包含 `tests/test_table_extractor.py` 的扩展测试为 `102 passed, 19 failed`，19 项仍为既有路由期望、缺失样本 PDF/旧模块和模型路径差异。

## 2026-08-27

- 完善 span-table document-tree demo：将 `年末数`、`年初数` 及叶表头纳入统一逻辑网格，两个分组表头各保留 `colspan=3`；同步更新 JSON/PNG 验证与回归测试。Demo 测试结果：5 passed。
- 从 GitLab `feature-gangwei` 分支移植无线结构恢复基础逻辑到独立 `tables/wireless_structure` 包：新增原生 Span 来源追踪与数值字段拆分、中文文本条合并、稳定列带推断、物理/逻辑网格和占位冲突检查；暂不接入 demo/生产 pipeline，不做中英文语义配对。
- 继续移植无线结构逻辑：新增列内候选单元格物化、中文同槽位/多行合并、表头下界推断、基于真实 bbox 的叶子列 colspan 和稀疏列补救；仍保持独立包。新增无线结构测试与既有相关测试合计验证通过。
- 将 `feature-gangwei` 的完整 `header_topology` 核心同步到独立包，适配当前 `BBox`/列带接口；覆盖多级表头叶子细化、数值轨迹拆分、父表头跨度推断、稀疏列救援和边界贴合抑制。中英文语义配对未接入。

## 2026-08-26

- 增加无线表格的页面语言分流：英文页面才尝试斑马纹颜色背景提取，中文和混合语言页面直接使用文本对齐逻辑，避免将整页背景误判为表格行。
- 修复 wired 表格提取器将未与表格竖线相交的页眉线、页脚线和超链接下划线误判为表格线的问题。
- 在表格区域识别阶段增加横竖线交叉过滤：横线至少连接两条竖线，竖线至少连接两条横线。
- 新增回归测试，验证未连接的横线不会扩大表格区域。
- 使用 `test_single.py` 验证 `fix/zh_all_table_pages.pdf` 第一页，表格框从 `[65.1, 63.3, 531.0, 782.2]` 恢复为 `[65.3, 100.0, 530.8, 701.8]`，行列数从 `12 x 2` 恢复为 `8 x 2`。
- 修复 wired 表格按全部横线 Y 与竖线 X 生成贯穿式笛卡尔积网格的问题，改为依据线段覆盖关系构造单元格并识别 `rowspan/colspan`；线段交点继续使用 2pt 容差兼容 PDF 坐标微小偏差。
- 新增局部线段和视觉近似相交的回归测试；wired 提取器专项测试结果为 6 passed。
- 调整最终表格门控：有线规则识别到的表格即使未被 ML 检测到，也会保留并补充到最终结果；避免模型漏检导致有线表格丢失。
- 收紧有线线段的可见性判断：drawing 线在进入虚线/普通线候选前检查透明度及描边颜色，透明或接近页面背景色的线不再参与 `line_projection`，避免文本边框和不可见装饰形成碎片表格；可见黑色/彩色虚线、黑色填充细线及 `1x1/2x2` 图像 tile 恢复路径保持不变。新增背景色虚线、透明虚线拒绝测试和可见黑色虚线保留测试；有线提取器专项测试 12 passed。
## 2026-09-14

- 新增 `scripts/run_pdf_diff_review.ps1` 真实审阅运行入口：固定默认的实际输出、测试集和 review 目录，同时允许通过参数覆盖；使用主项目 Python 调用 `build_review()` 生成分类摘要、JSON、HTML 和合成 PNG，不修改原始 PDF、标签或真实 E2E 输出。
- 修正 `build_review()` 与 Markdown golden comparator 的判定口径：分类、文本 diff 和搜索索引统一先调用 `normalize_markdown()`，移除图片行并归一化空白，避免把资源路径差异误判为正文/格式差异；manifest 标记为 `excluded` 的页面不进入差异审阅列表。真实 `fix/zh_all_table_pages.pdf` 快照复核结果为 1023 页，其中 901 页相同、1 页排除、121 页待审阅；分类为正文 97、混合 10、表格结构 8、表格数量 3、表格文本 1、资源缺失 2。分类 JSON 和离线网页只载入 121 个差异页，合成图与两侧 PNG 资源保留在 `output/fix_zh_all_table_pages_review_20260914/review/`。
## 2026-09-23

- 完成 Rust 无线结构 Task 5/6 页面级验收闭环：新增纯 Python 字段 normalizer `src/hexai_pdf_parser/debug/rust_task5_acceptance.py`、三模式 runner `scripts/run_task5_shadow_acceptance.py` 和回归测试 `tests/test_rust_wireless_shadow_differential.py`。normalizer 稳定化 table/region 的 source、rows、cols、bbox、Cell 文本与跨度、空槽位、occupancy owner/conflict/out-of-bounds 及 routing diagnostic；比较器只允许 0.01pt bbox 浮点噪声，不忽略结构字段。
- 使用 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf` 的 0-based 页面 `184,188,189,191,192`，分别运行 `python`、`shadow`、`rust`，覆盖 `recover_wireless_tables()` 和 `recover_cells_from_region()`。新输出位于 `D:\codes\PDFLayoutParser\output\rust_migration_task5_20260922\`，包含 15 个 page JSON、15 个 overlay PNG、三份 manifest 和 comparison JSON；输入 SHA256 和绝对 artifact 路径均通过审计。
- 页面结果明确显示 shadow 的结构化结果与 Python 语义结果一致并保留 17 条 Rust 观测诊断；Rust page/region 在 188、189 以及固定区域输入上存在真实结构差异，184、191、192 的 page route 因 occupancy conflict 走 Python fallback。比较报告共 2894 条差异，全部标为 `defect`，`unclassified_count=0`；默认 Python route、fallback policy、用户 dirty 测试文件均保持不变。
- Task 5/6 最终验证：normalizer/runner `8 passed`，组合迁移矩阵 `140 passed`，`cargo test --lib` `60 passed`，`cargo check` 与 `git diff --check` 通过。结论为验收和审计交付完成，但 Rust primary gate 仍不通过；后续修复必须逐项处理 defect ledger，并在新的独立输出目录重跑 JSON/PNG。
- Rust 页面无线表格候选对齐 Python 的 track-first 列分配；纯 separator span 不再被 packed-number 拆分器按空格切开。新增分隔符 span 与宽字段连接 overlap band 的差分回归。五页 r12 acceptance 结构差异为 0、路由诊断仍为 12，真实候选 occupancy 冲突继续触发 fallback；Python primary 未变，未运行性能门禁。
- NativeRegion 非空列带现在沿用 Python 完成 rescue 后的最终结果，避免 Rust 二次剪枝删除稀疏表头列；页 188 两个真实 region 直出与 Python 逐字段一致。Rust 页面 track-first 补齐 Python 对“三空白分隔、字段数与轨迹数相同、全为冒号字段”的宽 span 切分。新增正反例。五页 r14 输出结构差异为 0、route diagnostic 降至 10（仅 page route fallback），region route 不再 fallback；Python 默认行为保持，Rust primary 仍关闭。验证：pytest 190 passed、cargo lib 64 passed、release binding 构建成功；未测性能。

## 2026-09-27

- 修复中文无线表格 Page 442、446 的 Rust 漏检与行错位。根因一：Rust `median_positive()` 对偶数样本取上中位数，和 Python `statistics.median()` 的中间均值不同；Page 446 表2 的行容差因此过大，把项目行与多行叶表头合并，`4x7` 变为 `3x7`。根因二：`vertical_header_chain` 特判仅按首行 CJK 文本与 `rowspan>=3` 判断，把普通多字符表头“项目”“受限情况”等扩成整层表头，触发 occupancy conflict，导致 Page 442 表4 和 Page 446 表3 丢失。
- 最小修复：偶数样本采用 Python 兼容的中间均值；垂直表头链只接受至少三行、每行一个 CJK 字符且以换行连接的真实链，普通多字符表头不再进入该路径。新增两个 Rust 单元测试，分别锁定偶数中位数和垂直链判定。
- 独立页面输出：`D:\codes\PDFLayoutParser-Fast\output\pdf\page442_443_446_logical_rows_fix_20260927\`。Page 442 恢复 6 张表，Page 446 恢复 6 张表，Page 443 保持 2 张表；三页 Rust 与 Python 逐表逐 Cell 的文本、row/col、span、BBox 均为 0 差异。页面 JSON 和可视化 PNG 均已生成。

## 2026-09-27

- 修复中文无线表格页面索引 `437`、`438`、`439` 的 Rust 逻辑行拆分。根因位于 `rust/wireless_structure.rs::logical_row_components()`：`merge_source_contiguous_vertical_cells()` 已将 native 连续文本合并为一个 Cell，但逻辑行组件仍把 Cell 起始行位于 `body_start` 之前的覆盖范围截断；随后空槽物化将长首列/长表头的续行输出为额外行。该条件同时影响 page 437 第三表首列英文长文本，以及 page 438 第四表、page 439 第一表的多行表头。
- 最小修复：允许跨入正文边界且从非首行开始的首列 rowspan 参与 body prefix 合并；允许从物理首行开始、跨 `body_start` 的 wrapped header 使用其已证实 rowspan 范围，保留既有 tall wrapped header 和 occupancy 防护。新增两个 Rust 最小失败测试，覆盖表头边界和正文首列跨边界；修复后 `cargo test --locked logical_row_components` 为 `3 passed`。
- 独立页面输出：`D:\codes\PDFLayoutParser-Fast\output\pdf\page437_439_logical_rows_fix_20260927\`。Rust 结果与 Python 逐表逐 Cell 对比完全一致：page 437 第三表 `3x6/18`、page 438 第四表 `2x3/6`、page 439 第一表 `2x3/6`；文本、row/col、span 和 BBox 均为 0 差异。对应页面 JSON 与可视化 PNG 均已生成并复核。
- 验证：Rust `cargo test --locked` 为 `81 passed`；相关 Python 无线结构/Parity 测试为 `65 passed`。更宽的 recoverer 测试集合有 1 条既有 fallback 期望失败（`test_recover_cells_from_region_falls_back_when_rust_returns_empty_grid`，与本次逻辑行修改无关），未修改该既有行为。
