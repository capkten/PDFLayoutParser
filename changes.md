# Changes

## 2026-09-03

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
