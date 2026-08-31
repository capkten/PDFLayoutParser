# Span 到 atom 字段边界修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 修复中文/混合语言无线表格中独立中文 Span 与数值 Span 被误合并、以及金额/比例/占位符被打包在单一 Span 内的问题，使 page 192 的三张表都能恢复正确列结构。

**架构：** 在现有 `NativeSpan -> region_spans -> build_text_runs` 数据流内修正字段边界。`span_chain` 只依据 `char_boxes` 拆分单个 packed Span，`text_runs` 阻止独立中文字段与后续完整数值字段跨列连接；后续行列和单元格逻辑保持不变。

**技术栈：** Python 3.12、pytest、PyMuPDF 原生 Span/字符盒、现有 wireless structure recovery。

## 全局约束

- 中文和 mixed 页面只使用新的 native-span 结构恢复。
- Span 规范化完成后不重新读取 page words。
- 不增加 page 192、公司名或具体表头关键字规则。
- 保留工作区中与本任务无关的已有修改。

---

### 任务 1：独立 Span 的连接边界

**文件：**
- 修改：`tests/test_wireless_structure_text_runs.py`
- 修改：`src/hexai_pdf_parser/tables/wireless_structure/text_runs.py`

**接口：**
- 消费：`build_text_runs(spans: Sequence[dict[str, Any]]) -> list[dict[str, Any]]`
- 产出：中文字段 Span 后的完整数值/比例字段 Span 保持为独立 atom。

- [ ] **步骤 1：添加失败测试**

增加一个同原生行的“广东锦龙发展股份有限公司”与“304,623,048.00”用例，断言返回两个 text run；保留现有“1”与“年以内”连接用例作为反例保护。

- [ ] **步骤 2：确认测试因错误连接而失败**

运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_text_runs.py
```

预期：新增测试失败，实际得到单个拼接后的 text run。

- [ ] **步骤 3：实现最小连接保护**

增加数值字段判定，并在 `_can_join()` 的普通同原生行连接前拒绝“左侧含 CJK、右侧为完整数值/比例/短占位符”的独立 Span 组合。上标连接和“数字 + 中文”连接不变。

- [ ] **步骤 4：确认 text run 测试通过**

运行同一步骤 2，预期全部通过。

### 任务 2：packed Span 的多字段拆分

**文件：**
- 修改：`tests/test_wireless_structure_span_chain.py`
- 修改：`src/hexai_pdf_parser/tables/wireless_structure/span_chain.py`

**接口：**
- 消费：`region_spans(spans: Sequence[NativeSpan], region: BBox) -> list[dict[str, Any]]`
- 产出：一个原生 Span 可按多个显著字符间距生成多个带稳定来源引用的 atom。

- [ ] **步骤 1：添加失败测试**

使用真实形式的字符盒分别构造 `5,100,000.00  51%` 和 `---  5,100,000.00  51%`，断言拆为 2 段和 3 段；增加普通中文数字混合 Span 不拆分的保护用例。

- [ ] **步骤 2：确认测试因百分号或仅拆一处而失败**

运行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_span_chain.py
```

预期：两个 packed-field 用例失败，旧实现返回原 Span 或只拆为两段。

- [ ] **步骤 3：实现多边界拆分**

扩展允许字符集合以包含 `%`，遍历字符盒收集所有达到 `max(3.0, font_size * 0.45)` 的空白边界，生成任意数量的非空片段，并统一设置片段计数、索引、bbox、字符盒和来源位置。

- [ ] **步骤 4：确认 span chain 测试通过**

运行同一步骤 2，预期全部通过。

### 任务 3：最低层表头擦边保护

**文件：**
- 修改：`tests/test_wireless_structure_header_topology.py`
- 修改：`src/hexai_pdf_parser/tables/wireless_structure/header_topology.py`

**接口：**
- 消费：`refine_leaf_bands(atoms, bands) -> tuple[list[dict], float | None]`
- 产出：邻列标题轻微擦边不再证明当前 band 存在第二个叶子列。

- [ ] **步骤 1：添加失败测试并确认 2 列被误拆成 3 列**

构造目标 band 与稳定邻带重叠 1.4pt、邻列标题同样只擦边的多级表头，断言细化后仍为 2 个 band。

- [ ] **步骤 2：复用有效重叠判定**

在 `_split_by_lowest_header_children()` 中用 `_meaningful_header_band_overlap()` 收集最低层候选，替换任意相交判定。

- [ ] **步骤 3：运行表头拓扑测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_header_topology.py
```

预期：新增擦边保护和既有真实拆列测试全部通过。

### 任务 4：页面级验证与变更记录

**文件：**
- 修改：`changes.md`
- 生成：`output/page_192_span_atom_boundary_fix/` 下的单页结构化结果和可视化图片。

**接口：**
- 消费：`fix/zh_all_table_pages.pdf`，0-based page index `192`，language `mixed`。
- 产出：三张表及其 5、9、5 个叶子列结构。

- [ ] **步骤 1：运行相关模块回归测试**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q tests/test_wireless_structure_*.py tests/test_financial_header_normalizer.py
```

- [ ] **步骤 2：单页重跑并检查结构化输出**

调用项目 `PDFParser.parse(page_indices=[192])`，输出到独立目录；确认表格数为 3，叶子列分别为 5、9、5，且真实候选没有 occupancy conflict 拒绝。

- [ ] **步骤 3：视觉检查**

检查新生成的 `tables/page-192.png`，确认三个候选区域都被绘制，表格边界不吸收标题，相邻表格不合并，文字归属和空单元格合理。

- [ ] **步骤 4：更新中文变更说明**

在 `changes.md` 记录日期、根因、Span/atom 设计约束、实现方式、反例保护和实际验证结果。

- [ ] **步骤 5：最终校验并提交**

```powershell
git diff --check
git status --short
```

只暂存本任务相关源文件、测试、文档和 `changes.md`，保留其他工作区修改。
