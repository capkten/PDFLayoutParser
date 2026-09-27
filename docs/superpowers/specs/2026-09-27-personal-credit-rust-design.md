# 个人征信 Rust 专用提取入口设计

## 目标

在不改变 `feature-dev` 当前 Python 公开接口和输出契约的前提下，为个人征信报告增加 Rust 专用表格提取与结构恢复入口。Rust 只处理页面采集后形成的 owned DTO；Python 继续负责 PDF/PyMuPDF 读取、入口参数、Pipeline 编排、公开 `Table`/`Cell`/`Document` 装配、序列化和最终 compact result。

验收基线为当前 Python 实现。对 `个人信用报告\` 目录内的全部 PDF，Rust 路径必须与 Python oracle 在表格数量、顺序、source、bbox、行列、文字、rowspan、colspan、空槽位和 compact JSON 上逐项一致；任何 DTO、结构或输出校验失败都必须回退 Python 并保留诊断。

## 已确认的约束

- `parse_personal_credit_report()` 的调用签名、默认参数和返回结构保持不变。
- Python 继续读取 `fitz.Page`、drawings、native spans、字符和 words；Rust 不接收或持有 PyMuPDF 对象。
- 中文/混合无线表格继续使用 native-span 新结构，不回退到 `extract_zebra()`、legacy words 重建或结构阶段重新读取 `page.get_text("words")`。
- Rust 只替换表格检测、表格结构恢复和个人征信表格规则；页面分类、ML 模型推理、文本块/布局元素装配和 Markdown/JSON 写出留在 Python。
- 通用 PDF 默认路由不改变。个人征信 Rust 路径先以显式 `python`、`shadow`、`rust` 模式验证；只有全部夹具零差异且无 fallback 后，才允许将个人征信默认路径切到 Rust。
- 所有新增结构化字段必须有 DTO 校验、occupancy 校验和 Python/Rust 差分测试；不使用 broad ignore 隐藏差异。

## 方案与选择

采用“个人征信专用 Rust 算法入口”方案，而不是只迁移查询表或重写整个 Pipeline：

1. Python 在页面读取阶段准备个人征信输入 DTO，包含页面几何、drawings、native spans、字符/词、已识别的查询区域/标题锚点和 wired 容差。
2. Rust 专用入口复用已有 wired、native-span、wireless、header 和 occupancy 算法，补充个人征信查询表恢复、正文误表过滤、报告元数据过滤、重复记录拆分和查询表跨度规则。
3. Python 适配 Rust 输出为现有 `Table`/`Cell`，继续执行公开结果装配；Rust 输出异常或校验失败时走 Python oracle。

## 架构和数据流

### Python 输入边界

在 `PersonalCreditReportTableExtractor` 的页面处理入口，Python 读取当前页面并生成 `PersonalCreditInput`：

- `schema_version`、页面索引和页面 `Rect4`；
- drawings、水平/垂直线和线容差；
- native span、字符级 bbox、source position、字体/字号和 flow evidence；
- words 及其 block/line/order 信息，仅用于页面采集和个人征信查询锚点定位；
- 机构查询/本人查询标题、查询表 header、候选区域和跨页 continuation 信息；
- `wired_line_tolerance=2.2` 及当前个人征信开关配置。

Rust 输入结构必须是拥有型数据，拒绝未知必需字段、非有限坐标、越界 source 引用、字段长度不一致和非法 span。Rust 不反向调用 Python 回调。

### Rust 个人征信入口

新增 Rust 模块和 PyO3 binding，建议公开的内部扩展名为 `recover_personal_credit_tables`。入口接收 `PersonalCreditInput`，返回 `PersonalCreditOutput`：

- 候选表格及其 `TableCandidateDto`/`CellDto` 数据；
- `source`、confidence、bbox、rows/cols、rowspan/colspan、空 Cell；
- 查询表 section title/header 行和 continuation 合并结果；
- occupancy、bbox、输入校验和 fallback 原因诊断。

Rust 内部按以下顺序执行：

1. 有线表格：线段合并、区域检测、边界补全、物理 Cell、文字归属和 2.2 容差规则。
2. native-span 无线表格：span → text run → atom → column band → physical grid → logical grid，保留 source continuity 和 evidence。
3. 个人征信查询表：按 Python 当前标题/列边界/记录连续性规则恢复机构查询和本人查询表，保留标题行、四列结构、续行并入、空槽位和 `personal_query_recovery` source。
4. 专用过滤与拆分：拒绝编号长正文候选、报告身份元数据候选，按现有记录起点拆分重复记录。
5. 对每个跨度提案重新运行 occupancy conflict 检查；冲突、越界或不完整结果不进入 Rust 输出。

### Python 输出边界

`rust_adapter.py` 将 `PersonalCreditOutput` 转为现有 `Table`/`Cell`。`PersonalCreditReportTableExtractor` 保留当前入口和 `_document_result()`；仅将表格算法调用替换为 `run_python_or_rust()` 的个人征信路径。公开 compact result、Markdown 和 JSON 的字段名及排序不变。

## 路由和失败策略

- `python`：完全走当前 Python 实现，作为 oracle。
- `shadow`：返回 Python 结果，同时运行 Rust；使用字段级 normalizer 比较并记录所有差异，不能因为比较失败改变 Python 输出。
- `rust`：运行 Rust；输入、输出、occupancy 或 schema 失败时回退 Python，并记录 `rust_fallback` 诊断。
- 个人征信路径使用独立诊断名，例如 `personal-credit.extract_tables`；不污染通用 wired/wireless 路径的默认模式。
- 首次实现不切换全局 Rust primary。只有全部个人征信 PDF 在新输出目录完成 Python/Rust JSON 和 PNG 对照、差异为零且无 fallback 后，才切换个人征信默认路由；通用报告仍保持当前默认值。

## 测试设计

### 单元和 DTO 测试

- `PersonalCreditInput` 正常字段、空输入、非法 bbox、非有限数、source/cardinality 不一致和未知字段拒绝。
- 查询表标题、四列 header、记录行、续行、跨页 continuation、缺失列和空槽位。
- 编号正文过滤、报告元数据过滤、重复记录拆分、2.2 wired 容差。
- occupancy conflict、rowspan/colspan、bbox union、source 和输出顺序。

每个新增 Rust 行为先写 Python/Rust 共享向量的失败测试，再实现最小代码；测试必须先观察到预期失败。

### 差分测试

用同一页面采集快照分别调用 Python oracle 和 Rust 入口，按以下字段比较：

- table count/order/source/confidence/bbox/rows/cols；
- 每个 Cell 的 text、row_index、col_index、bbox、rowspan、colspan；
- 空槽位数量、occupancy 覆盖和诊断；
- 个人征信 compact JSON 的页面编号、block 顺序和 Markdown 表格文本。

### 端到端测试

对 `个人信用报告\` 下所有 PDF 使用全新输出根目录，分别执行 Python、shadow 和 Rust 模式。每个文件保留输入 hash、配置、运行模式、输出 JSON、逐页 JSON、表格 PNG、页面 PNG、诊断和差分报告。最终报告必须列出每个 PDF 的页数、表格数、Rust fallback 数、差异数和失败原因。

## 验收标准

1. 现有 `tests/test_personal_credit_report.py` 及相关表格回归测试继续通过。
2. 新增 DTO、个人征信 Rust 入口和差分测试全部通过；`cargo test --lib`、`cargo check` 和 binding 构建通过。
3. 个人信用报告目录中的每个 PDF 都完成 Python/Rust 端到端运行，输出目录彼此独立。
4. Rust 模式与 Python oracle 的结构化结果和 compact JSON 零差异，PNG 中的表格边界和单元格结构一致。
5. Rust 模式无 fallback、无 occupancy conflict、无未分类诊断；若任一项不满足，保持 Python 默认路由并报告未完成项。
6. 不修改通用 PDF 的默认行为，不加入 ML 或 OCR，不改变公开 API。

## 不在本次范围内

- 将 PDF 打开、页面读取、ML 推理、布局块、图片、印章或 Markdown/JSON writer 迁移到 Rust。
- 改变 `feature-dev` 的公共 Python API 或输出 schema。
- 为通用报告切换 Rust primary。
- 用容差放宽、业务文字硬编码、删除 occupancy 冲突或 broad ignore 制造“零差异”。
