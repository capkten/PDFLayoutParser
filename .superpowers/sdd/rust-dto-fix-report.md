# Rust DTO 边界复核修复报告

## 范围

本次继续处理 `dd9c187` 的同一 Rust DTO bounded slice，只修改 `rust/types.rs` 和本报告。没有修改 Python bridge、transition tests、无线结构算法、默认 route 或其他用户改动。

## Reviewer findings

1. 新增 DTO 测试直接调用 `Python::with_gil`，而 PyO3 0.22.6 的本项目依赖未启用 `auto-initialize`，导致测试运行时 panic。该版本实际没有可用的 `Python::initialize()`；测试代码使用 `std::sync::Once` 包装 `pyo3::prepare_freethreaded_python()`，再进入 `Python::with_gil`，保证并行测试只初始化一次。
2. `NativeRegionInput::from_py` 对 `region`、`atoms`、`bands`、`config` 及列表元素使用裸 `downcast`/`extract`，错误容器会返回 `PyTypeError`。现改用现有 `required_dict`/`required_list`，并将 atoms/bands 元素 downcast 显式映射为 `PyValueError`；新增覆盖五类错误容器的反例测试。
3. `AtomDto::from_py` 的 `rect` 裸 downcast，以及 `StructureConfig::from_py` 的 `schema_version` 裸 extract，会分别将错误容器和 bool/字符串数字暴露为 `PyTypeError`。现分别改用 `required_dict` 和 `required_i64`，并新增 malformed 反例。

## TDD 验证

- 当前基线 RED：`cargo test --lib` 为 48 tests，44 passed、4 failed；4 个失败均为 Python interpreter 未初始化。
- 容器反例 RED：新增测试在只加入测试封装后运行，1 failed、0 passed、48 filtered out；实际错误类型为 `TypeError`，预期为 `ValueError`。
- 容器反例 GREEN：目标测试 1 passed、0 failed、48 filtered out。
- 完整 GREEN：`cargo test --lib` 为 49 passed、0 failed、0 ignored。
- 本轮 focused RED：`cargo test --lib types::tests::atom_rect_and_config_schema_reject_wrong_types_as_value_error -- --exact` 为 0 passed、1 failed、49 filtered out；atom rect 实际返回 `TypeError`。
- 本轮 focused GREEN：同一命令为 1 passed、0 failed、49 filtered out。
- 本轮完整 GREEN：`cargo test --lib` 为 50 passed、0 failed、0 ignored。
- `git diff --check`：通过。

## 前置提交

- `dd9c187 Fix Rust DTO test compile blockers`

## 本次提交

- Subject：`Fix Rust DTO boundary review findings`
- 修改：`rust/types.rs`、本报告。

## 本轮提交

- Subject：`Fix nested Rust DTO validation`
- 修改：`rust/types.rs`、本报告。
