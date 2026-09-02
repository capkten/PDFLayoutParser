# 中文无线表格规则候选召回信号实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 为中文/混合页面增加只消费 native span 几何的页面级表格候选信号，召回页面 `983` 这类首列换行导致现有无线结构恢复为空的页面，同时保持候选页门控和模型精确检测流程不变。

**架构：** `recover_wireless_tables()` 在已有 native span -> text strip 数据上计算独立的数值行/列锚点信号，并把证据写入 diagnostics；它不改变 `_table_runs()` 或最终 Cell 恢复。`TableExtractor._detect_rule_candidates()` 仅在中文/混合页的结构候选为空而页面信号命中时追加 `wireless_page_signal` 标记，现有 `extract()` 仍只依据候选非空决定是否调用模型，最终只消费模型框。

**技术栈：** Python、PyMuPDF、pytest、现有 `BBox`/`Table`/`TextStrip` 模型。

## 全局约束

- 规则阶段只负责候选页召回，不负责精确表格区域和最终单元格结构。
- 继续使用“规则候选页 -> ML 整页检测 -> 模型框区域级 native-span 恢复”的 pipeline。
- 中文/混合页面不调用 `extract_zebra()`，不回读 `page.get_text("words")`，不回退 legacy 文本重建。
- 页面信号只消费 native span、text strip 和几何；不硬编码业务文字，不恢复 `rowspan`/`colspan`。
- `wireless_page_signal` 不能进入最终表格列表，也不能被当作 `line_projection` 有线结果。
- 保留工作区中与本任务无关的用户改动。

---

### 任务 1：先添加页面信号和候选标记的失败测试

**文件：**

- 修改：`tests/test_wireless_table_recovery.py`
- 修改：`tests/test_rule_first_table_detection.py`
- 参考：`src/hexai_pdf_parser/tables/wireless_table_recovery.py`
- 参考：`src/hexai_pdf_parser/tables/table_extractor.py`

**接口：**

- 新的纯几何辅助函数签名为：

```python
def _detect_native_span_page_signal(
    strips: Sequence[TextStrip],
) -> Optional[NativeSpanPageSignal]:
```

- `NativeSpanPageSignal` 至少暴露 `bbox`、`numeric_row_count`、`stable_column_count` 和 `labeled_row_count`。

- 测试文件在新增用例前提供以下确定性的 strip 构造辅助函数：

```python
def _make_strip(text, x0, y0, x1, y1, order):
    span = NativeSpan(text, BBox(x0, y0, x1, y1), "Helvetica", 10.0, order)
    return TextStrip(text, BBox(x0, y0, x1, y1), [span])
```

- [ ] **步骤 1：添加首列换行、六列数字的正例。**

构造三条以上数值 visual row；数值条的中心线相同，左侧标签条分别位于数值行上方或下方，且标签可以是同一字段的换行片段。断言信号命中、稳定列不少于四列、数值行不少于三条，并且 bbox 覆盖数字和左侧标签。

```python
def test_native_span_page_signal_accepts_wrapped_label_rows():
    rows = []
    order = 0
    for row_index in range(3):
        label_y = 20.0 + row_index * 32.0
        number_y = label_y + (5.8 if row_index % 2 == 0 else -4.0)
        rows.append([
            _make_strip("公司名称片段", 20.0, label_y, 115.0, label_y + 10.0, order),
            *[
                _make_strip(
                    str(1000 + row_index * 10 + column),
                    150.0 + column * 82.0,
                    number_y,
                    205.0 + column * 82.0,
                    number_y + 12.0,
                    order + column + 1,
                )
                for column in range(6)
            ],
        ])
        order += 8

    strips = [strip for row in rows for strip in row]
    signal = _detect_native_span_page_signal(strips)

    assert signal is not None
    assert signal.numeric_row_count == 3
    assert signal.stable_column_count >= 4
    assert signal.bbox.x0 == 20.0
    assert signal.bbox.x1 >= 615.0
```

- [ ] **步骤 2：添加普通正文反例。**

用少于四列数字、只有两条重复数字行或数字右边界不稳定的 strips 调用同一函数，断言返回 `None`。该测试必须只证明候选信号的召回门槛，不调用模型。

```python
def test_native_span_page_signal_rejects_sparse_or_unstable_body_numbers():
    sparse = [
        [_make_strip(str(value), 40.0 + value * 20.0, row * 20.0, 55.0 + value * 20.0, row * 20.0 + 10.0, row * 4 + value)
         for value in range(3)]
        for row in range(4)
    ]
    assert _detect_native_span_page_signal([strip for row in sparse for strip in row]) is None

    unstable = [
        [_make_strip(str(100 + row + column), 40.0 + column * 80.0 + row * 9.0, row * 20.0,
                     55.0 + column * 80.0 + row * 9.0, row * 20.0 + 10.0, row * 4 + column)
         for column in range(4)]
        for row in range(3)
    ]
    assert _detect_native_span_page_signal([strip for row in unstable for strip in row]) is None
```

- [ ] **步骤 3：添加候选页门控回归测试。**

在 `TableExtractor` 的中文/混合候选路径中预置一个命中的 `page_signal` diagnostics，模型 fake 返回一个 sentinel 表格；断言模型被调用且最终结果是模型表格。再覆盖一个命中的 page signal 不会被作为最终表格直接返回，`source` 不会是 `wireless_page_signal`。

- [ ] **步骤 4：运行新增测试确认旧实现失败。**

运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wireless_table_recovery.py::test_native_span_page_signal_accepts_wrapped_label_rows tests/test_wireless_table_recovery.py::test_native_span_page_signal_rejects_sparse_or_unstable_body_numbers tests/test_rule_first_table_detection.py
```

预期：新增信号测试因符号不存在或返回 `None` 失败；既有规则门控测试保持可执行。只修正测试构造错误，不提前写生产实现。

### 任务 2：实现 native-span 页面信号并写入 diagnostics

**文件：**

- 修改：`src/hexai_pdf_parser/tables/wireless_table_recovery.py`
- 测试：`tests/test_wireless_table_recovery.py`

**接口：**

- 新增 `NativeSpanPageSignal` dataclass。
- 新增 `_detect_native_span_page_signal(strips)`。
- `recover_wireless_tables()` 的 diagnostics 新增 `page_signal` 对象；未命中时 `matched` 为 `False`，读取异常仍沿用当前异常处理。

- [ ] **步骤 1：定义最小信号数据结构。**

在 `NativeSpan`/`TextStrip` 附近添加：

```python
@dataclass
class NativeSpanPageSignal:
    bbox: BBox
    numeric_row_count: int
    stable_column_count: int
    labeled_row_count: int
```

- [ ] **步骤 2：实现纯 strip 信号计算。**

实现逻辑固定为：筛出 `_is_number()` 条带；用 `_row_cluster()` 分成数值 visual row；保留至少四个数值条带的行；使用数值条带右边界聚类列锚点，锚点容差为 `min(24.0, max(10.0, median_width * 0.35))`；保留至少三条数值行支持的锚点；至少三行能映射到四个稳定锚点才命中。向左侧寻找与数值行垂直相邻的非数值 strip，只用于 `labeled_row_count` 和 bbox 扩展，不设为硬门槛。

每个信号对象的 bbox 由命中的数值行和相邻左侧条带并集得到；没有左侧条带时仍以数值行并集作为 bbox。函数不得访问 `fitz.Page`，不得调用任何 `get_text`。

- [ ] **步骤 3：在恢复 diagnostics 中记录信号。**

`recover_wireless_tables()` 在现有 `strips = merge_text_strips(spans)` 后计算信号，并将以下结构加入 diagnostics：

```python
"page_signal": {
    "matched": signal is not None,
    "bbox": signal.bbox.__dict__ if signal else None,
    "numeric_row_count": signal.numeric_row_count if signal else 0,
    "stable_column_count": signal.stable_column_count if signal else 0,
    "labeled_row_count": signal.labeled_row_count if signal else 0,
}
```

这一步不改变 `candidate_runs`、`tagged_runs`、`_build_table()` 或最终 `recovery.tables`。

- [ ] **步骤 4：运行信号单元测试确认通过。**

运行同任务 1 的两个新增测试；预期均 PASS。若反例误命中，只调整信号门槛或几何条件，不放宽到最终结构恢复。

### 任务 3：接入 `_detect_rule_candidates()` 的页面门控

**文件：**

- 修改：`src/hexai_pdf_parser/tables/table_extractor.py`
- 修改：`tests/test_rule_first_table_detection.py`

**接口：**

- 候选标记使用已有 `Table` 类型，`source="wireless_page_signal"`、`rows=0`、`cols=0`、`cells=[]`。
- `_extract_model_tables()` 的 `wired_tables` 过滤继续只接受 `source == "line_projection"`。

- [ ] **步骤 1：在文本对齐候选为空且信号命中时追加标记。**

保留现有 `line_tables`、英文 zebra 和 `_extract_via_text_alignment()` 顺序，在其后增加等价逻辑：

```python
alignment_tables = self._extract_via_text_alignment(
    page,
    excluded_regions=wired_regions,
)
candidates.extend(alignment_tables)

signal = self._last_wireless_recovery or {}
page_signal = signal.get("page_signal")
if (
    page_language in {"zh", "mixed"}
    and not alignment_tables
    and isinstance(page_signal, dict)
    and page_signal.get("matched")
):
    bbox_data = page_signal.get("bbox") or {}
    candidates.append(
        Table(
            bbox=BBox(
                float(bbox_data["x0"]),
                float(bbox_data["y0"]),
                float(bbox_data["x1"]),
                float(bbox_data["y1"]),
            ),
            rows=0,
            cols=0,
            cells=[],
            source="wireless_page_signal",
        )
    )
```

生产代码应在 bbox 字段不完整或类型异常时把标记视为未命中，不让诊断数据异常绕过候选门控；这个保护只包围标记转换，不改变已有恢复异常处理。

- [ ] **步骤 2：验证标记只触发模型，不进入最终结果。**

让 fake detector 返回一个 `model` 表格，断言 `extract()` 调用模型一次、返回模型表格；再让 fake detector 返回空列表，断言结果为空而不是 `wireless_page_signal`。保留既有 `test_rule_miss_does_not_call_model` 和 wired 优先测试。

- [ ] **步骤 3：运行规则候选和无线相关测试。**

运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rule_first_table_detection.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py
```

预期：新增测试和已有相关测试全部通过；失败时先定位是 page signal 判定、diagnostics 传递还是候选标记转换，不同时修改多个层次。

### 任务 4：页面回归、文档和最终核验

**文件：**

- 修改：`changes.md`
- 检查：`fix/zh_all_table_pages.pdf` 页面索引 `983`
- 输出：新的独立目录 `output/page_983_rule_candidate_signal_20260902/`

- [ ] **步骤 1：运行目标页面候选与模型回归。**

使用项目单页解析入口只处理 0-based 索引 `983`，输出到上述新目录；检查候选不为空、模型确实执行，最终表格数量为两张，`source` 为 `wireless_span_recovery`，而不是 `wireless_page_signal`。

- [ ] **步骤 2：同时检查结构化 JSON 和最终 PNG。**

核对页面 JSON 中两张表的 bbox、行列和 Cell 数量，确认上下两张表未误并；核对最终 PNG 中模型框/表格边界未吸收页眉、续页文字或底部孤立数字。候选标记本身不应出现在最终表格 JSON。

- [ ] **步骤 3：更新中文 changes.md。**

在 `2026-09-02` 下追加根因、调用位置、判定条件、无 `words` 回读约束、测试命令、页面输出路径和最终表格 source/数量；不改写已有条目。

- [ ] **步骤 4：运行完整相关回归并检查差异。**

运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_rule_first_table_detection.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_pipeline_debug.py
git diff --check
git status --short
```

预期：相关测试 0 failures，`git diff --check` 无输出；工作区中用户已有的结构恢复、`test_single.py`、`fix/` 和 `.codegraph/daemon.pid` 改动保持存在。
