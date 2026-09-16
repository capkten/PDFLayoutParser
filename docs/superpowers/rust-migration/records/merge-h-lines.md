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
- 理由：函数只计算确定性的数值 DTO；5 组 Python/Rust 输入输出完全相同，包括 1.15 和 2.25 的 round/sort 边界。
- 未支持或未穷举：尚未对全部 IEEE-754 值、NaN/无穷值及任意极端坐标做性质/模糊测试；不据此声称对所有可能 `f64` 输入已形式化证明等价。Python 3.7 运行时未直接测试，验证的是 cp37-abi3 构建标签和元数据。
- 接受差异：无已观察差异；无容差放宽。

## 验证

- 固定向量：近邻线段归并；间隔超过 3.0 时分段；空输入；`round(1.15, 1)` 排序边界；`round(2.25, 1) == 2.2` 排序边界。
- TDD RED：原始三组向量先写入 Rust/pytest 测试，再实现函数；实现缺失时 Rust 测试不能通过、扩展不可导入。其后 `1.15` 排序回归先以缩放后整数舍入实现验证，目标断言 RED：该算法把 1.15 排序键算成 1.2，令 x0 较小的另一条线排到前面。
- TDD GREEN：改用一位小数格式化生成排序键后，`cargo test` 原有 4 项通过；本次新增的 2.25 边界在修改前直接调用现有 binding 已输出 Python 期望顺序，随后将该向量固化到 Rust 与 pytest。
- Python/Rust 差分：以 `WiredTableExtractor._merge_h_lines` 对照 Rust adapter，5/5 向量逐项完全相同；`2.25` 案例中 Python `round(2.25, 1)` 为 `2.2`，2.25 线段保持在 2.3 线段之前。
- 最终 Rust：`cargo test`，5 passed、0 failed；doc-tests 0。
- 最终 Python：Python 3.12，`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_pdf_fast_binding.py tests/test_wired_table_extractor.py`，68 passed、5 warnings。警告为既有 PyMuPDF SWIG `SwigPyPacked`、`SwigPyObject`、`swigvarlink` 的 `__module__` 弃用警告；pytest 结束另有一条同类 `swigvarlink` 进程退出警告。
- 构建/打包：Wheel `cp37-abi3-win_amd64`、Version `1.1.1`、Requires-Python `>=3.7`、规范化入口 `hexai_pdf_parser=hexai_pdf_parser.cli:main`；3 个 JSON 模板及 1 个 ONNX 模型均在 wheel 内。最终 sdist 含 Cargo manifest/lock、Rust/Python 源码及同一组包数据；无 `output/`、`target/`、`.venv/`、本机 PDF 或旧 egg-info 元数据。
- 差异分类：5 组核验向量均为精确匹配；未观察到迁移差异。
- 回归测试：`tests/test_pdf_fast_binding.py` 固化以上 5 组函数/binding 测试，`tests/test_wired_table_extractor.py` 保持生产 Python 路径回归。

## 决策与后续

- 未决项：无需新增产品决策；独立 Evaluator 尚待复核，本记录不代表 sprint 评估通过。
- 限制：本地验证环境为 Windows x64；其他平台需各自生成 abi3 wheel。未切换生产路由，未运行 benchmark，也不宣称性能收益。
- 下一步：交由独立 Evaluator 按 Sprint 001 合同复跑并审阅差异。
