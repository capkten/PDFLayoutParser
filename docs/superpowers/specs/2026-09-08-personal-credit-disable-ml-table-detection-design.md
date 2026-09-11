# 个人征信 Pipeline 默认禁用模型表格检测设计

## 目标

让个人征信报告专用 Pipeline 默认跳过 ML 表格区域检测，同时继续使用现有的有线表格、native-span 无线表格、征信专用查询记录恢复和表头规范化逻辑。通用 `Pipeline` 的默认行为保持不变；需要模型时由调用方显式开启。

## 公开接口

在 `parse_personal_credit_report` 增加 `use_ml_table_detector` 参数，个人征信入口默认值为 `False`：

```python
document = parse_personal_credit_report(
    pdf_path="征信解析样例.pdf",
    use_ml_table_detector=False,
)
```

传入 `True` 时恢复当前的模型检测路径。`ml_model_path=None` 仍表示解析默认模型路径，不能作为禁用开关。

`PersonalCreditReportPipeline` 直接实例化时也使用 `False` 作为默认值。通用 `Pipeline` 继续默认使用模型，以避免影响已有调用方。

## 页面数据流

### 默认禁用模型

```text
页面
  -> 语言检测和规则候选检测
       -> 英文 zebra 候选（适用时）
       -> 有线线段/网格候选
       -> 语言分流的文本对齐候选
          -> zh/mixed 使用 native-span 结构恢复
  -> 去除 wireless_page_signal 等非表格占位候选
  -> 解决有线与无线候选重叠，优先保留可信有线结果
  -> 表头规范化、页面 bbox 裁剪、排序
  -> 页面布局构建和输出
```

禁用模型时不得创建或调用 `MLTableDetector`，也不得通过传入无效模型路径来模拟禁用。规则候选直接作为后续规范化和布局构建的输入；没有候选的页面保持空表格结果。

### 显式启用模型

传入 `use_ml_table_detector=True` 时保留现有流程：规则候选只负责触发模型，模型 bbox 再驱动无线区域结构恢复，并优先复用重叠的有线结果。

## 组件边界

### `Pipeline`

- 保存并传递 `use_ml_table_detector` 配置。
- 默认值保持为 `True`，兼容通用 Pipeline。
- 线程和进程并行路径都必须传递同一配置，不能只修复默认线程路径。

### `TableExtractor`

- 增加模型检测开关。
- `True` 时调用现有 `_extract_model_tables`。
- `False` 时使用规则候选结果，不触发模型初始化、页面预处理或推理。
- 禁用模型路径需要统一处理候选去重和重叠关系：有线 `line_projection` 结果优先，native-span/文本对齐结果保留为无线结果，`wireless_page_signal` 只作为信号不能进入最终表格。
- 两种路径都继续执行现有 layout rules、中文表头规范化、表格 bbox 裁剪和排序。

### `PersonalCreditReportPipeline`

- 默认将模型检测开关设为 `False`。
- 复用 `TableExtractor` 的共享逻辑，不复制页面处理和输出流程。
- 保留个人征信专用的查询记录恢复、元数据过滤、编号说明段过滤和重复记录表拆分。

## 兼容与错误处理

- 通用 `Pipeline`、现有 `TableExtractor` 调用和 CLI 默认行为不变。
- `parse_personal_credit_report(..., use_ml_table_detector=True)` 可以显式恢复模型检测。
- `output_dir`、渲染、Markdown/JSON 输出和调试输出不因本设计改变。
- 扫描页仍按当前扫描页分支处理，不额外引入模型检测。
- 模型禁用时不应触发模型文件缺失、ONNX Runtime 或模型推理相关异常。

## 测试要求

- 专用入口默认不会实例化或调用 `MLTableDetector`。
- 专用入口显式传入 `True` 时仍会调用模型检测器。
- 禁用模型后，有线表格候选仍能进入最终结果。
- `zh/mixed` 页面仍能通过 native-span 路径恢复无线表格，并保留空槽位、跨度和冲突检查结果。
- `wireless_page_signal` 不会被错误物化为最终表格。
- 有线与无线候选重叠时，有线结果优先且不重复输出。
- 线程和进程后端都能正确传播开关。
- 运行新增测试、相关表格/Pipeline 测试和 `git diff --check`。

