# Rust 表格逻辑迁移基线

## 基线来源

- Python 行为基线：`feature-dev@dc00211fe0cf95bc8c3412c883311fe86f8d835b`。
- 实施分支：`codex/pdf-fast-rust-migration`，从该基线创建。
- 用户确认日期：2026-09-16。
- 当前 Rust 状态：仓库没有现有 Cargo crate；迁移从 PyO3/maturin 扩展起步。

## 已确认的兼容合同

- Python/PyMuPDF 继续打开 PDF、读取页面、drawing、文字和 native span；Rust 不接收或持有 `fitz.Page`、PyMuPDF 对象或其他 Python 对象。
- Rust 接收 owned DTO，完成有线、中文/混合无线、英文无线的纯算法；Python 保留公开 API、语言路由、服务编排、`Table`/`Cell` 构造和序列化。
- 逐函数迁移，以相同输入的精确输出测试锁定兼容性；顺序、文本、坐标、source、置信度、跨度、空槽位、错误与空结果均按 Python 基线复现。不得通过增加浮点容差隐藏差异。
- 每个 Rust 入口按页或表格区域批量接收数据；无 Python 回调的计算段释放 GIL。
- 本阶段不做独立 benchmark，不设未经用户确认的性能门槛，也不宣称性能收益。
- 保留现有 Python API、JSON 结构和调用方可观察行为；一个路径验证通过前不得切换该路径的生产路由。
- 保持 `requires-python >=3.7`。使用 PyO3/maturin 的 abi3 方案时，wheel 仍须按操作系统、CPU 架构和 native runtime 构建；不得再假设 `py3-none-any`。

## 特殊行为基线

- 有线逻辑保留 drawing 可见性、clip、背景色、type3 glyph、矩形边去重、图表区域屏蔽及 page index 415 的柱状图过滤行为。PDF 读取仍在 Python。
- 中文/混合无线逻辑保持 native-span 新结构：Span 到 atom/text run 阶段完成同字段组合并保留来源连续性；列带和网格阶段不得调用 `page.get_text("words")`；不得走 `extract_zebra()` 或 legacy words 重建。
- 中文/混合无线逻辑按当前几何/拓扑规则恢复叶子列、`rowspan`、`colspan`、冲突与空槽位；不加入业务文字特判，不把同候选槽位当作合并理由。
- 英文路径保持斑马纹优先级、general wireless、text-alignment candidate 与 legacy callback 的现有先后和回退行为。
- 有线与无线对外的 table/cell 排序和输出顺序不变。

## 固定验证输入

- 合成输入：每个纯函数的常规、空输入、边界、排序、重叠/不重叠和失败语义向量；Python pytest 与 Rust `cargo test` 使用相同的结构化向量。
- 仓库小型 PDF：`tests/fixtures/page_000_vector.pdf`、`tests/fixtures/page_437_wireless.pdf`、`tests/fixtures/page_705_scanned.pdf`，按路径适用性选择。
- 本机回归 PDF：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`，约 1023 页，不进入 Git；通过显式路径读取，结果写入新的 `output/pdf_rust_migration_*` 目录。
- 页面级抽查至少覆盖索引 185（白名单字距）、196（有线区域/局部线网）、415（柱状图屏蔽），并按无线结构变化补充 1002/1014 等现有回归页。

## 验收

- Rust 函数测试、Python binding/DTO 测试、既有相关 pytest 和路由/兼容测试通过。
- 每条完整提取路径对结构化 JSON 与 PNG 完成对照；确认表格数量、source、行列数、文字、顺序、bbox、跨度、空槽位和边界。
- 最终对 `fix/zh_all_table_pages.pdf` 全量解析到独立输出目录；不得覆盖或复用旧输出。
- 失败须区分迁移缺陷、基线环境失败和待产品决策差异；未经用户批准不放宽合同。
