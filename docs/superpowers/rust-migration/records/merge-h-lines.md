# 函数级迁移记录：横线段归并

## 身份

- Python 函数：`WiredTableExtractor._merge_h_lines(lines)`
- Rust 函数：`merge_h_lines(Vec<Line4>, f64) -> Vec<Line4>`，绑定入口 `_pdf_fast.merge_h_lines`
- 层级：纯逻辑、PyO3 binding 与 Python DTO adapter
- 负责人：Sprint 001 Generator

## 行为合同

- 用途：按 y 排序并分组水平线段，求组内平均 y，并按 x 起点归并间隔不超过 3.0 的线段。
- 输入/输出：owned `list[tuple[float, float, float, float]]` 与 `merge_group_tol: float`；输出同形状、有序元组列表。
- 排序和精度：排序键为 `(round(y, 1), x0)`；归组比较每条线与组首线 y 的绝对差；组内 y 使用算术平均；线段按 x0 排序，间隔 `<= 3.0` 合并。
- 错误和副作用：adapter 仅转换 Python 数字为 owned tuple 并调用批量 binding；不传递 PDF/PyMuPDF 对象。输入转换错误沿用 PyO3 类型提取错误，无新增自定义异常策略。
- 已批准基线：行为基线为 `feature-dev@dc00211fe0cf95bc8c3412c883311fe86f8d835b`；本 sprint 不切生产路由。包版本 `1.1.1`、`Requires-Python >=3.7`、`abi3-py37` 与 `hexai_pdf_parser.cli:main` 入口均按用户确认值验收。

## 分类

- 分类：精确复现（已批准并实测的 DTO 向量范围内）。
- 理由：函数只计算确定性的数值 DTO；当前六个边界/行为向量的 Python/Rust 输出一致，包括 1.15、2.25 舍入键及 NaN 稳定排序。
- 未支持或未穷举：尚未对全部 IEEE-754 值、正负无穷和任意极端坐标做性质/模糊测试；不据此声称对所有可能 `f64` 输入已形式化证明等价。Python 3.7 运行时未直接测试，验证的是 cp37-abi3 构建标签和元数据。
- 接受差异：无已观察差异；无容差放宽。

## 验证

- 固定向量：近邻线段归并；间隔超过 3.0 时分段；空输入；`round(1.15, 1)` 排序边界；`round(2.25, 1) == 2.2` 排序边界；NaN 排序键稳定性。
- 初始实现 TDD 记录：先前 Generator 报告称原始测试先于实现并观察到 RED，但当时没有把原始失败输出保存到迁移记录；初始实现与测试同在 `a58d04e`，因此目前无法仅凭提交历史独立证明其先后顺序。不得将该历史说明冒充为本次可复核的 RED 证据。
- NaN 修复 TDD RED：仅含新 Rust/pytest 测试的提交 `eb45b5618704ea531aba1ed5b911a8074e14cc36` 先于比较器修复。该提交的隔离 worktree 上 `cargo test` 为 5 passed、1 failed；`preserves_input_order_when_rounded_y_comparison_is_nan` 失败，实际首项 `x0=0.0`、期望 `x0=10.0`。在同一未修复实现上，焦点 pytest 为 1 failed，断言实际 `0.0`、期望 `10.0`。两次失败均由 NaN 比较返回 unordered 后错误使用 `x0` 次级排序导致。
- NaN 修复 TDD GREEN：比较器仅在舍入 y 明确相等时比较 `x0`；unordered 比较返回相等，使稳定排序保留输入顺序。修复后 `cargo test` 为 6 passed、0 failed；`maturin develop --release` 成功；binding 和有线回归为 69 passed、5 warnings。
- Python/Rust 差分：原有五个固定向量逐项精确一致；新增 NaN 案例以 Python `WiredTableExtractor._merge_h_lines` 为 oracle，保持输入顺序，修复后的 Rust binding 输出相同顺序。未观察到容差放宽。
- 既有弃用警告：5 条 PyMuPDF SWIG `SwigPyPacked`、`SwigPyObject`、`swigvarlink` `__module__` 弃用警告；pytest 退出时另有同类 `swigvarlink` 进程警告。
- Wheel：`target/wheels-sprint001-repair/hexai_pdf_parser-1.1.1-cp37-abi3-win_amd64.whl`；Tag `cp37-abi3-win_amd64`、Version `1.1.1`、Requires-Python `>=3.7`、入口 `hexai_pdf_parser=hexai_pdf_parser.cli:main`；包含 3 个 JSON 模板和 1 个 ONNX 模型。
- sdist：`target/sdist-sprint001-repair/hexai_pdf_parser-1.1.1.tar.gz`，278 个成员、未压缩 48,753,810 字节；包含 Cargo manifest/lock、Rust/Python 源码和 3 个 JSON 模板/1 个 ONNX。未包含 `output/`、`target/`、`.venv/`、`.codegraph/`、`.cursor/`、`.gemini/`、`.superpowers/`、`.devops/` 或本机 PDF。Cargo 对可选 crate 描述/license/homepage/repository 元数据发出警告，构建成功。
- 差异分类：NaN 次级排序缺陷已修复；所有六个核验向量精确匹配。尚待独立 Evaluator 复核。
- 回归测试：`tests/test_pdf_fast_binding.py` 固化以上六组函数/binding 测试，`tests/test_wired_table_extractor.py` 保持生产 Python 路径回归。

## 决策与后续

- 未决项：无需新增产品决策；独立 Evaluator 尚待复核，本记录不代表 sprint 评估通过。
- 限制：本地验证环境为 Windows x64；其他平台需各自生成 abi3 wheel。未切换生产路由，未运行 benchmark，也不宣称性能收益。
- 下一步：交由独立 Evaluator 按 Sprint 001 合同复跑并审阅差异。
