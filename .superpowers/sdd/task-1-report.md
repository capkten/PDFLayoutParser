# Task 1 报告：分类纯函数

## 状态

分类纯函数已完成并通过 7 个分类测试。完整测试文件中 `build_review` 用例仍失败；该生成器属于后续任务，本 Task 1 仅提供导入占位，不实现生成器逻辑。

## 实现

- 新增 `scripts/pdf_diff_review.py`。
- 实现 `parse_markdown`、`detect_signals`、`build_classification` 和 `classify_markdown`。
- 支持表数量、行列形状、`rowspan`/`colspan`、表格单元格文本、表格外正文、可见文本顺序及纯格式差异证据。
- 未修改测试、原始 PDF、输出目录或标签。

## 测试命令与原始输出摘要

红灯确认：

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q
ImportError while importing test module
ModuleNotFoundError: No module named 'scripts.pdf_diff_review'
```

分类定向测试：

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q -k 'classify'
7 passed, 1 deselected, 5 warnings in 0.06s
```

完整测试：

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q
1 failed, 7 passed, 5 warnings in 0.23s
失败：test_build_review_writes_json_images_and_html
原因：build_review 尚未实现（后续任务范围）。
```

自检与静态检查：

```text
python -m py_compile scripts/pdf_diff_review.py       # 通过
git diff --check                                      # 通过
```

## Commit

`feat: classify PDF markdown differences`

## 审阅修复

- 按 I-1 将 `scripts/pdf_diff_review.py` 的类型注解改为 `typing.List`、`Dict`、`Tuple` 和 `Optional`，消除 Python 3.7 导入阶段对 PEP 585/604 注解的依赖；七个分类规则和返回字段未改变。
- 按 I-2 将已有的 `tests/test_pdf_diff_review.py` 纳入本次修复提交。
- 未修改原始 PDF、标签或输出目录。当前环境提供 Python 3.8/3.12，没有 Python 3.7；已通过 Python 3.8 导入验证及 Python 3.12 分类测试，且注解扫描确认不再使用不兼容写法。

## 审阅修复测试

Python 3.8 导入验证：

```text
py -3.8 -c "import scripts.pdf_diff_review"
exit code 0
```

分类定向测试：

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q -k 'classify'
7 passed, 1 deselected, 5 warnings in 0.11s
```

完整当前测试文件：

```text
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; pytest tests/test_pdf_diff_review.py -q
1 failed, 7 passed, 5 warnings in 0.43s
失败：test_build_review_writes_json_images_and_html；`build_review` 是后续任务占位，抛出 `NotImplementedError`。
```

附加检查：

```text
python -m py_compile scripts/pdf_diff_review.py       # 通过
git diff --check                                      # 通过；报告文件末尾已有空行提示，不影响脚本/测试改动
```

## 修复 Commit

修复实现已提交：`7ff5d21 fix: make PDF diff classifier Python 3.7 compatible`。
