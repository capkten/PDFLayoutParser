# Rust 迁移能力矩阵

| 能力 | 当前归属 | Rust 迁移边界 | 主要验证 |
|---|---|---|---|
| PDF 打开、页访问、旋转归一化 | Python / PyMuPDF | 不迁移；Python 将页面数据转成 owned DTO | `tests/test_pdf_parser.py`、页面输出 |
| 有线 drawing、clip、颜色、字符区域和图表候选读取 | `WiredTableExtractor` Python | 保留 extraction；将线段、矩形和文字快照交给 Rust | `tests/test_wired_table_extractor.py` 中 `_extract_lines_from_drawings` 与 page 415 用例 |
| 有线线段合并、交点、连通区域、网格 snap、部分外边界、Cell 拓扑 | `wired_table_extractor.py` Python | 按纯函数迁 Rust；Python 继续装配项目 `Table`/`Cell` | `tests/test_wired_table_extractor.py`、`tests/test_table_extractor.py` |
| 有线文字读取 | PyMuPDF `get_text("words")` | Python 读取；Rust 仅消费 words DTO 并按原规则分配文字 | `test_assign_text_to_line_cells_splits_word_at_physical_column_boundary` 等 |
| 英文/共享 native span 读取 | `wireless_table_recovery.collect_native_spans` | 保留 PDF adapter；Rust 消费文字、bbox、font、size、字符框、遍历顺序和来源位置 | `tests/test_wireless_table_recovery.py`、`tests/test_wireless_output_order.py` |
| Native span 候选表恢复 | `wireless_table_recovery.py` | 将纯文本/几何/排序/候选分组与结果选择逐函数迁 Rust；Python 构造公开对象和诊断外壳 | `tests/test_wireless_table_recovery.py`、英文/中文 extractor 路由测试 |
| 中文/混合 span 到 atom、text run、列带及结构网格 | `wireless_structure/` | 逐函数迁 Rust；Python 只采集 spans 并将结果 Cell DTO 适配为 `Cell` | `tests/test_wireless_structure_*.py`、中文路由测试 |
| 中文/混合禁止 words 回读、禁止 zebra/legacy 回退 | Python 路由合同 | 保持 facade；Rust 不具备 PDF 对象访问能力；增加调用约束测试 | `test_chinese_page_candidates_do_not_request_words`、路由测试 |
| 英文 drawing 背景与 words 读取 | `english_table_extractor.py` | Python 提取并规范化；Rust 实现背景分组、行列、文字归属和 cell 规则 | `tests/test_page_347_structure.py`、`tests/test_rule_first_table_detection.py`、wireless 回归 |
| 英文斑马纹、general wireless 和 legacy words 算法 | `EnglishTableExtractor` / `TableExtractor` | 分批迁入 Rust；保留 Python facade、回退选择和序列化 | `tests/test_wireless_extractor_split.py`、`tests/test_table_extractor.py`、页面验证 |
| ML 检测、语言识别、表格后处理/模板、Markdown/JSON、渲染和服务层 | Python | 本轮不迁移；不得因相邻关系扩大范围 | 现有 API/端到端输出测试 |
| Rust crate、PyO3、maturin、wheel 构建 | 当前不存在 | 新增一个扩展和受控 DTO 边界；首先验证发布物 | `cargo test`、maturin build、wheel tag/metadata 检查 |

## 单元分类

- **Exact reproduction**：输入 DTO 和边界规则完整的线段合并、矩形/交点几何、排序、空槽位物化等纯确定性函数。
- **Semantic reproduction**：PDF span/word 的上游分组结果依赖 PyMuPDF 的真实返回值；Rust 仅重现 Python 当前对这些已提取 DTO 的处理。差异逐字段归类，不把 PyMuPDF 行为默认为 Rust 的职责。
- **Redesign**：本轮没有已批准的 redesign。若出现 Python 异常、动态类型、线程或 ABI 差异而不能精确复现，暂停该函数并提交决策，不在 Rust 侧静默默认。
