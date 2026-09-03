# Task 1 报告：等宽多样文本列的合并否决

## 结论

已完成。`build_text_runs` 在对齐走廊 veto 中补入了“文本值多样性”证据，避免把 Page 979 这种“右侧固定宽度、左侧多样金额”的列误合并；同时保留了固定单位场景的原有合并行为。

## RED

命令：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py -k 'fixed_width_diverse or varying_amounts_with_fixed_unit'
```

预期失败摘要：

- `test_build_text_runs_vetoes_fixed_width_diverse_aligned_column_join` 失败
- 实际结果把三组“金额+地点”错误合并成了 `金额+地点`
- `test_build_text_runs_keeps_varying_amounts_with_fixed_unit_joined` 通过，说明反例方向正确

## GREEN

命令：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_structure_text_runs.py -k 'fixed_width_diverse or varying_amounts_with_fixed_unit'
```

通过摘要：

- 2 passed
- 仅保留既有的 PyMuPDF / SWIG DeprecationWarning

## 相关回归

命令：

```powershell
$env:PYTHONPATH=(Resolve-Path 'src').Path
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_output_order.py tests/test_wireless_structure_text_runs.py tests/test_wireless_structure_recoverer.py
```

结果：

- 56 passed
- 仅保留既有的 PyMuPDF / SWIG DeprecationWarning

## 改动文件

- `tests/test_wireless_structure_text_runs.py`
- `src/hexai_pdf_parser/tables/wireless_structure/text_runs.py`

## 自审

- 修改是最小化的，只加了一个文本多样性辅助判断，并且只挂在 alignment corridor veto 路径上。
- 新增测试覆盖了目标误合并场景和固定单位反例，能证明这次改动没有把原本该保留的合并打坏。
- 相关回归通过，说明对现有文本拼接路径没有明显回归。

## 顾虑

- 目前的多样性阈值是 `>= 3` 个去空白后的不同文本值，和任务说明保持一致；如果后续 Page 979 周边还有更复杂的低样本结构，可能需要再补更具体的几何证据。
- 回归里仍有既有的 SwigPy* 弃用警告，但它们不影响本次修复结论。
