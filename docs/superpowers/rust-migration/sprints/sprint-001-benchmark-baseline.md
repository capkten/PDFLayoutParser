# Sprint 001：基准基线

## 范围

本 Sprint 只建立确定性的 Python 基准和 Python/Rust 结果规范化、差异比较基础设施。没有修改 Rust 算法、公共 `Table`/`Cell` schema、PDF 提取逻辑或生产路由默认值。

## 基准约定

- 支持模式严格为 `python`、`shadow`、`rust`；未识别模式抛出 `ValueError`。
- 未设置 `PDF_RUST_MODE` 时默认为 `python`。
- Sprint 001 的三种模式都记录请求模式，但实际执行 route 固定为 `python_baseline`；因此不会提前引入生产切换。
- timing 使用 count、total、mean、min、max、P50、P95、P99，百分位数采用线性插值。
- 表格按原表顺序、单元格按 `(row_index, col_index, text)` 稳定排序，并保留 source、confidence、bbox、行列索引、rowspan、colspan 和空文本。

## 输出

fixture 基准输出：

`output/rust_migration_benchmark/sprint-001/fixture-python.json`

输入 `tests/fixtures/page_000_vector.pdf`，页 `0`，warmups `1`，runs `2`，结果为 1 个表格、8 行、2 列；JSON 使用排序键且只包含可序列化值。
