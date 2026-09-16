# Rust 迁移决策记录

| 日期 | 决策 | 状态 |
|---|---|---|
| 2026-09-16 | 基线事实：普通 setuptools 动态版本元数据来自仓库 `version` 文件，当前为 `1.1.0`；该事实不代表本 sprint 的 Rust 扩展版本决策 | 基线记录 |
| 2026-09-16 | 以 `feature-dev@dc00211fe0cf95bc8c3412c883311fe86f8d835b` 为行为基线 | 用户确认 |
| 2026-09-16 | Python/PyMuPDF 保留 PDF 读取与公开 API；Rust 只接 owned DTO 并执行纯算法 | 用户确认 |
| 2026-09-16 | 有线、中文/混合无线、英文无线按函数级逐步迁移，输入输出等价测试先行 | 用户确认 |
| 2026-09-16 | 不做独立 benchmark；现阶段不设时间性能门槛 | 用户确认 |
| 2026-09-16 | 保持 API、JSON、source、顺序、bbox、cell 文本/跨度、错误/空结果及浮点规则一致 | 用户确认 |
| 2026-09-16 | 保留 Python 最低版本 `>=3.7`；目标使用 PyO3/maturin 的 abi3 wheel，按平台分别构建 | 用户确认的约束 |
| 2026-09-16 | Sprint 001 的 Maturin/Cargo 包版本设为 `1.1.1`，与当前 `build.sh` release `VER` 一致；保留 `Requires-Python >=3.7`、`abi3-py37` wheel tag 和有效 console entry point `hexai_pdf_parser.cli:main` | 用户确认 |
| 2026-09-16 | 中文/混合无线使用 native-span 新路径，不回读 words、不回退 zebra/legacy；空格、span 来源和 occupancy 合同继续生效 | 用户确认的项目约束 |

## 实施时的停止条件

- 选定 PyO3/maturin 版本不能同时满足 Python 3.7 和当前 Rust 工具链时，停止构建改动并提交版本取舍，不提高 `requires-python`。
- 函数输入/输出字段缺少证据、Python 行为不确定或出现非精确差异时，先增加最小复现向量并判明差异；不得先改规则。
- 修改公开 schema、异常策略、坐标约定、浮点容差、支持平台或系统依赖前，回到用户确认。
- 任一路径的 Python/Rust 输出未精确匹配或 `fix` 页面结构/PNG 有回归时，不切换其生产入口。

## 当前未决项

- 首次实施时，核对选定的 Maturin/PyO3 组合与当前 Rust 工具链能否生成所需 wheel 和 metadata；这是构建可行性核验，不授权改变已决版本 `1.1.1`、Python 最低版本、ABI tag 或 entry point。
- 本地 `fix/zh_all_table_pages.pdf` 不在迁移分支中；需要从原主工作区显式读取，不能复制或加入提交。
