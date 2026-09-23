# 迁移决策

## D-001：Python 作为候选行为基线

本轮以现有 Python 输出作为差分基线，但不自动保留已确认的静默丢弃和无诊断回退。任何 intentional difference 都必须在 sprint 评估中写出字段、原因和回归夹具。

## D-005：Stage 1 能力审计以仓库根为唯一基准

审计 CLI 接受仓库根或源码子目录；两者都必须向上解析到包含 `rust/` 的仓库根，再以相对路径读取 Rust、Python、测试、迁移记录和 `output/` 证据。否则源码子目录会把真实 Rust 路由误报为 `adapter_only`。

## D-006：能力状态必须按证据分层

Rust symbol、生产 route、行为测试、迁移记录、页面/差分证据和 DTO schema 分别判定。仅有 Rust symbol 的单元状态为 `adapter_only`；脚本、测试、benchmark、CLI、I/O、debug、页面读取、绘图和公开对象装配不作为生产 owned 算法迁移目标。

## D-007：owned DTO 合同固定为 schema_version=1

公开 `roundtrip_dto` 入口必须拒绝缺失或错误 schema，以及 NaN/Inf 坐标。现有 `rust/types.rs` 已提供统一校验，本阶段只补真实公开入口的回归合同测试，不重写 DTO 或 Rust 算法。

## D-008：AST 与 evidence 也必须以仓库根为基准

CLI 的 `collect`、`render`、能力评估和输出标题统一使用向上解析后的仓库根；不能只修复 capability 单元。`evidence_globs` 仅接受 `is_file()` 的真实文件，并输出相对仓库根的 POSIX 路径；空目录、目录命中和绝对机器路径都不是证据。

## D-009：页面分类依赖访问语义而非参数名

普通名为 `page` 的数值或 DTO 参数不触发页面范围外分类；只有 `fitz`/`Page`/绘图语义或真实 `get_text`、`get_drawings`、`get_textbox` 属性调用才标为页面读取。normalizer 中公开 Table/Cell/BBox 装配属于 Python `out_of_scope`。

## D-002：Rust 只接收 owned DTO

Rust 不持有 PyMuPDF 对象。页面访问和对象转换留在 Python，纯几何/文本/网格规则在 Rust 执行。

## D-003：中文/混合 wireless 不回读 words

native span 组合为 atom 后，结构恢复阶段只消费 span、atom、列带、物理 Cell 和逻辑 Cell；禁止通过 `page.get_text("words")` 重新推断文本。

## D-004：缺少 fix 夹具不能伪造页面验收

用户已明确指定 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf`。代码测试和差分基准可以在 worktree 中执行，最终报告必须给出该 PDF 的 JSON/PNG 输出路径，并和 `D:\codes\PDFLayoutParser` 中的历史结果比较。
