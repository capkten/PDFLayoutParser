# Text Alignment Boundary Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 `text_alignment` 分支的候选误判、结构区间边界错误和表头丢失问题，同时保持线框表格链路稳定。

**Architecture:** 以 `src/hexai_pdf_parser/table_extractor.py` 为唯一主改动点，按“回归测试锁定 -> 候选发现收紧 -> 结构区间裁剪 -> 表头回并 -> 全量验证”顺序实施。所有行为变更优先用 `tests/test_table_extractor.py` 的 synthetic PDF 用例覆盖，避免直接依赖生产 PDF 做自动化断言。

**Tech Stack:** Python 3.10+, PyMuPDF (`fitz`), pytest

---

## 执行与审计配置

- 执行模型：`gpt-5.4-mini`，`medium`
- 审计模型：`gpt-5.4-mini`，`high`
- 执行方式建议：每完成一个 Task 就运行该 Task 对应测试，不跨 Task 混改
- 审计方式建议：每完成一个 Task 后做一次差异审阅，确认“新增逻辑只落在计划范围内”

## 文件结构

- 修改：`src/hexai_pdf_parser/table_extractor.py`
- 修改：`tests/test_table_extractor.py`
- 只读参考：`docs/superpowers/specs/2026-05-13-text-alignment-boundary-design.md`

## 审计重点

每个 Task 完成后，都要重点检查以下内容：

1. 是否误改 `line_projection` 主流程
2. 是否把 PDF 个例规则硬编码进通用逻辑
3. 是否新增了无法被单元测试覆盖的隐式分支
4. 是否让原有 text-only table 用例退化

### Task 1: 先补回归测试，锁定四类目标行为

**Files:**
- Modify: `tests/test_table_extractor.py`
- Read: `src/hexai_pdf_parser/table_extractor.py`

- [ ] **Step 1: 新增 synthetic PDF 构造辅助函数**

在 `tests/test_table_extractor.py` 中追加一个面向文本对齐场景的辅助函数，专门按给定行文本与坐标写入 PDF：

```python
def make_pdf_with_positioned_lines(
    path: str | Path,
    lines: list[list[tuple[float, float, str]]],
    width: float = 595,
    height: float = 842,
) -> None:
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    for row in lines:
        for x, y, text in row:
            page.insert_text((x, y), text)
    doc.save(path)
    doc.close()
```

- [ ] **Step 2: 增加”长标签 text-only table 不应被误判为 prose”的失败测试**

> **为什么需要这个测试：** Task 2 的 `looks_prose_with_fragments` 判定会把”长标签 + 数值”的 2 列 text-only table 误判为 prose fragment。这个测试在 Task 2 实现前应该通过（当前实现已包含此场景），修正 Task 2 时必须保持通过。

```python
def test_extract_via_text_alignment_keeps_long_label_text_only_table(
    tmp_path: Path,
):
    pdf_path = tmp_path / “long_label_table.pdf”
    make_pdf_with_positioned_lines(
        pdf_path,
        [
            [(90, 120, “房屋建筑物”), (270, 120, “20-100”), (380, 120, “5”), (470, 120, “0.95-4.75”)],
            [(90, 138, “机器设备”), (280, 138, “10-15”), (380, 138, “5”), (470, 138, “6.33-9.50”)],
            [(90, 156, “运输工具”), (290, 156, “8”), (380, 156, “5”), (470, 156, “11.88”)],
            [(90, 174, “电子设备”), (280, 174, “3-10”), (380, 174, “5”), (470, 174, “9.50-31.67”)],
        ],
    )

    doc = fitz.open(pdf_path)
    page = doc[0]
    extractor = TableExtractor()

    tables = extractor._extract_via_text_alignment(page)

    doc.close()
    assert len(tables) == 1
    assert tables[0].rows == 4
    assert tables[0].cols == 4
```

- [ ] **Step 3: 增加”正文带重复数字碎片不应成表”的失败测试**

> **为什么需要这个测试：** 与 Step 2 对称——确保真 prose（带数字碎片）被正确拒绝，不会因 Step 2 的修正而放松。

把下面测试追加到 `tests/test_table_extractor.py`：

```python
def test_extract_via_text_alignment_rejects_prose_with_repeated_numeric_fragments(
    tmp_path: Path,
):
    pdf_path = tmp_path / "prose_numeric.pdf"
    make_pdf_with_positioned_lines(
        pdf_path,
        [
            [(90, 120, "（1）本公司自2022"), (205, 120, "年1"), (230, 120, "月1"), (250, 120, "日起执行解释第"), (390, 120, "15"), (405, 120, "号")],
            [(90, 138, "相关规定根据累计影响数调整年初留存收益及其他相关财务报表项目")],
            [(90, 156, "表项目对可比期间信息不予调整本期无影响")],
            [(90, 182, "（2）本公司自2022"), (205, 182, "年1"), (230, 182, "月1"), (250, 182, "日起执行解释第"), (390, 182, "16"), (405, 182, "号")],
            [(90, 200, "相关规定根据累计影响数调整年初留存收益及其他相关财务报表项目")],
            [(90, 218, "表项目对可比期间信息不予调整本期无影响")],
        ],
    )

    doc = fitz.open(pdf_path)
    page = doc[0]
    extractor = TableExtractor()

    tables = extractor._extract_via_text_alignment(page)

    doc.close()
    assert tables == []
```

- [ ] **Step 4: 增加”说明段 + 真表格应裁掉前缀”的失败测试**

```python
def test_extract_via_text_alignment_trims_prose_prefix_before_real_table(
    tmp_path: Path,
):
    pdf_path = tmp_path / "prefix_trim.pdf"
    make_pdf_with_positioned_lines(
        pdf_path,
        [
            [(110, 100, "（1）自用固定资产")],
            [(110, 118, "自用固定资产折旧方法如下：")],
            [(160, 160, "项目"), (260, 160, "折旧年限"), (360, 160, "净残值率"), (450, 160, "年折旧率")],
            [(90, 178, "房屋建筑物"), (270, 178, "20-100"), (380, 178, "5"), (470, 178, "0.95-4.75")],
            [(90, 196, "机器设备"), (280, 196, "10-15"), (380, 196, "5"), (470, 196, "6.33-9.50")],
            [(90, 214, "运输工具"), (290, 214, "8"), (380, 214, "5"), (470, 214, "11.88")],
        ],
    )

    doc = fitz.open(pdf_path)
    page = doc[0]
    extractor = TableExtractor()

    tables = extractor._extract_via_text_alignment(page)

    doc.close()
    assert len(tables) == 1
    assert tables[0].bbox.y0 >= 150
```

- [ ] **Step 5: 增加”短表头 + 表体应合并”的失败测试**

```python
def test_extract_via_text_alignment_merges_short_header_span_into_body(
    tmp_path: Path,
):
    pdf_path = tmp_path / "header_merge.pdf"
    make_pdf_with_positioned_lines(
        pdf_path,
        [
            [(100, 110, "1．前期会计差错更正情况")],
            [(60, 150, "所属单位"), (160, 150, "更正内容"), (320, 150, "影响数"), (430, 150, "调整后余额")],
            [(60, 190, "甲公司"), (160, 190, "应付账款重分类"), (340, 190, "20,136,924.05"), (450, 190, "3,517,428,689.10")],
            [(60, 208, "乙公司"), (160, 208, "应付账款重分类"), (340, 208, "20,136,924.05"), (450, 208, "14,538,588,616.87")],
        ],
    )

    doc = fitz.open(pdf_path)
    page = doc[0]
    extractor = TableExtractor()

    tables = extractor._extract_via_text_alignment(page)

    doc.close()
    assert len(tables) == 1
    texts = [cell.text for cell in tables[0].cells]
    assert "所属单位" in texts
    assert "更正内容" in texts
```

- [ ] **Step 6: 增加”表体上方标题不应混入表格”的失败测试**

```python
def test_extract_via_text_alignment_excludes_heading_rows_above_body(
    tmp_path: Path,
):
    pdf_path = tmp_path / "heading_exclude.pdf"
    make_pdf_with_positioned_lines(
        pdf_path,
        [
            [(95, 110, "（二）重要税收优惠政策及其依据")],
            [(95, 128, "以下项目适用优惠税率，详见下表：")],
            [(80, 170, "税种"), (250, 170, "计税依据"), (430, 170, "税率")],
            [(80, 188, "增值税"), (250, 188, "销售额"), (430, 188, "13、9、6")],
            [(80, 206, "房产税"), (250, 206, "房产原值或租金"), (430, 206, "1.2 或 12")],
            [(80, 224, "教育费附加"), (250, 224, "实缴流转税税额"), (430, 224, "3")],
        ],
    )

    doc = fitz.open(pdf_path)
    page = doc[0]
    extractor = TableExtractor()

    tables = extractor._extract_via_text_alignment(page)

    doc.close()
    assert len(tables) == 1
    assert tables[0].bbox.y0 >= 160
```

- [ ] **Step 7: 运行新增测试，确认当前版本至少有目标失败**

Run:

```bash
pytest tests/test_table_extractor.py -k "long_label_text_only_table or repeated_numeric_fragments or trims_prose_prefix or merges_short_header_span or excludes_heading_rows" -v
```

Expected:

- `long_label_text_only_table` 和 `repeated_numeric_fragments` 应**通过**（当前实现已正确处理这两个场景）
- 至少 2 个以上其余新增用例失败
- 失败原因应与误判、边界或表头缺失直接相关，而不是测试构造错误

### Task 2: 实现按行结构打分和候选收紧

**Files:**
- Modify: `src/hexai_pdf_parser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [ ] **Step 1: 在 `TableExtractor` 中新增行级结构打分辅助函数**

在 `src/hexai_pdf_parser/table_extractor.py` 中、`_collect_text_candidate_regions()` 之前加入：

```python
def _score_row_against_guides(self, row: dict, guides: List[float]) -> dict:
    hits = sorted(self._row_guide_hits(row, guides))
    token_count = len(row["tokens"])
    row_width = max(row["x1"] - row["x0"], 0.0)
    guide_span = guides[-1] - guides[0] if len(guides) >= 2 else 0.0
    full_width = guide_span > 0 and row_width >= guide_span * 0.8
    long_text_tokens = sum(
        1
        for token in row["tokens"]
        if not token["is_numeric"] and len(token["text"].strip()) >= 8
    )
    numeric_tokens = sum(1 for token in row["tokens"] if token["is_numeric"])
    separated_hit_count = 0
    if hits:
        separated_hit_count = 1
        for left, right in zip(hits, hits[1:]):
            if guides[right] - guides[left] >= 24:
                separated_hit_count += 1

    return {
        "hit_count": len(hits),
        "separated_hit_count": separated_hit_count,
        "token_count": token_count,
        "numeric_tokens": numeric_tokens,
        "long_text_tokens": long_text_tokens,
        "full_width": full_width,
        "looks_prose_with_fragments": full_width and len(hits) <= 2 and separated_hit_count < 2 and numeric_tokens <= 2 and long_text_tokens >= 1,
        "is_structured": separated_hit_count >= 2 or len(hits) >= 3,
    }
```

- [ ] **Step 2: 新增 span 级误判过滤辅助函数**

继续在 `TableExtractor` 中加入：

```python
def _is_textual_false_positive_span(self, rows: List[dict], guides: List[float]) -> bool:
    if not rows or len(guides) < 2:
        return True

    row_scores = [self._score_row_against_guides(row, guides) for row in rows]
    structured_rows = sum(1 for score in row_scores if score["is_structured"])
    strong_rows = sum(1 for score in row_scores if score["hit_count"] >= 3)
    prose_fragment_rows = sum(1 for score in row_scores if score["looks_prose_with_fragments"])

    if structured_rows < 2:
        return True
    if len(rows) >= 4 and structured_rows < max(2, len(rows) // 2):
        return True
    if len(guides) >= 3 and strong_rows == 0:
        return True
    if prose_fragment_rows >= max(2, len(rows) - 1):
        return True
    return False
```

- [ ] **Step 3: 把误判过滤接入 `_collect_text_candidate_regions()`**

把该函数中的接受逻辑从：

```python
guides = self._infer_column_guides(span, bbox)
if len(guides) < 2:
    continue
if not self._has_repeated_column_structure(span, guides):
    continue
```

改为：

```python
guides = self._infer_column_guides(span, bbox)
if len(guides) < 2:
    continue
if not self._has_repeated_column_structure(span, guides):
    continue
if self._is_textual_false_positive_span(span, guides):
    continue
```

- [ ] **Step 4: 运行候选相关测试**

Run:

```bash
pytest tests/test_table_extractor.py -k “long_label_text_only_table or repeated_numeric_fragments or collect_text_candidate_regions or text_alignment_handles_text_only_tables” -v
```

Expected:

- 新增长标签 text-only table 测试**通过**（`separated_hit_count < 2` 条件不会误伤结构化行）
- 新增”正文带重复数字碎片不应成表”测试通过
- 现有 `collect_text_candidate_regions` 与 `text_only_tables` 相关测试继续通过

- [ ] **Step 5: 审计本 Task 改动**

审计检查：

- 只新增了按行评分和 span 过滤，没有进入裁边和表头回并逻辑
- 未改动 `_extract_via_lines()` 相关实现
- 未引入与特定 PDF 页码相关的字符串判断
- `looks_prose_with_fragments` 包含 `separated_hit_count < 2` 条件，确保 2 列结构化行不被误判为 prose
- `long_label_text_only_table` 测试通过，证明修正不会误伤合法表格

### Task 3: 实现结构区间裁剪，并接入 `text_alignment` 输出链路

**Files:**
- Modify: `src/hexai_pdf_parser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [ ] **Step 1: 新增结构区间裁剪辅助函数**

在 `TableExtractor` 中加入：

```python
def _trim_span_to_structured_rows(
    self, rows: List[dict], guides: List[float]
) -> List[dict]:
    if not rows:
        return []

    labels = []
    for row in rows:
        score = self._score_row_against_guides(row, guides)
        if score["is_structured"]:
            labels.append("structured")
        elif score["hit_count"] >= 1:
            labels.append("weak")
        else:
            labels.append("prose")

    best_start = 0
    best_end = -1
    best_score = -1
    start = None
    structured_count = 0
    weak_count = 0

    for idx, label in enumerate(labels):
        if label == "prose":
            if start is not None:
                interval_score = structured_count * 3 + weak_count
                if structured_count >= 2 and interval_score > best_score:
                    best_start = start
                    best_end = idx - 1
                    best_score = interval_score
            start = None
            structured_count = 0
            weak_count = 0
            continue

        if start is None:
            start = idx
        if label == "structured":
            structured_count += 1
        else:
            weak_count += 1

    if start is not None:
        interval_score = structured_count * 3 + weak_count
        if structured_count >= 2 and interval_score > best_score:
            best_start = start
            best_end = len(labels) - 1

    if best_end < best_start:
        return []
    return rows[best_start : best_end + 1]
```

- [ ] **Step 2: 在 `_extract_via_text_alignment()` 中接入裁边**

把：

```python
region_rows = region["rows"]
guides = region["column_guides"]
```

改为：

```python
region_rows = self._trim_span_to_structured_rows(
    region["rows"], region["column_guides"]
)
if not region_rows:
    continue
guides = self._infer_column_guides(region_rows, self._rows_bbox(region_rows))
if len(guides) < 2:
    continue
```

同时，把最终 `Table.bbox` 的来源调整为裁边后的 `region_rows`：

```python
region_bbox = self._rows_bbox(region_rows)
```

并在创建 `Table` 时使用 `region_bbox`。

- [ ] **Step 3: 运行裁边相关测试**

Run:

```bash
pytest tests/test_table_extractor.py -k "trims_prose_prefix or excludes_heading_rows_above_body or text_alignment_handles_text_only_tables" -v
```

Expected:

- “说明段 + 真表格应裁掉前缀”测试通过
- “表体上方标题不应混入表格”测试通过
- 原有 text-only table 测试仍通过

- [ ] **Step 4: 审计本 Task 改动**

审计检查：

- 裁边逻辑只发生在 `text_alignment` 已通过候选之后（即 Task 2 的误判过滤已通过）
- `Table.bbox` 已切换为裁边后的 bbox，而不是原 span bbox
- 任何返回空区间的候选都被安全丢弃，没有产生空表
- 裁边依赖 `is_structured` 分类，不受 `looks_prose_with_fragments` 影响（两者独立）

### Task 4: 实现表头回并，并完成全量回归验证

**Files:**
- Modify: `src/hexai_pdf_parser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [ ] **Step 1: 新增表头回并辅助函数**

在 `TableExtractor` 中加入：

```python
def _merge_header_like_span(
    self,
    previous_rows: List[dict],
    body_rows: List[dict],
    body_guides: List[float],
) -> List[dict]:
    if not previous_rows or not body_rows:
        return body_rows

    prev_bbox = self._rows_bbox(previous_rows)
    body_bbox = self._rows_bbox(body_rows)
    vertical_gap = body_bbox.y0 - prev_bbox.y1
    horizontal_overlap = min(prev_bbox.x1, body_bbox.x1) - max(prev_bbox.x0, body_bbox.x0)
    overlap_ratio = horizontal_overlap / max(min(prev_bbox.x1 - prev_bbox.x0, body_bbox.x1 - body_bbox.x0), 1.0)

    if len(previous_rows) > 3:
        return body_rows
    if vertical_gap < 0 or vertical_gap > 24:
        return body_rows
    if overlap_ratio < 0.6:
        return body_rows
    if self._looks_like_paragraph_region(previous_rows):
        return body_rows

    aligned_rows = 0
    for row in previous_rows:
        score = self._score_row_against_guides(row, body_guides)
        if score["hit_count"] >= 1:
            aligned_rows += 1

    if aligned_rows == 0:
        return body_rows
    return previous_rows + body_rows
```

- [ ] **Step 2: 在 `_extract_via_text_alignment()` 中接入前置 span 回并**

在遍历 `candidate_regions` 时，把当前单表循环改成带索引的循环，并在裁边前尝试取前一段：

```python
for idx, region in enumerate(candidate_regions):
    region_rows = region["rows"]
    guides = region["column_guides"]

    if idx > 0:
        previous_rows = candidate_regions[idx - 1]["rows"]
        merged_rows = self._merge_header_like_span(previous_rows, region_rows, guides)
        region_rows = merged_rows

    region_rows = self._trim_span_to_structured_rows(region_rows, guides)
```

为了避免把前一候选重复输出，新增一个集合记录“已被后继表体吸收的 span index”，并在主循环顶部跳过它：

```python
consumed_region_indexes: set[int] = set()
```

在回并成功时：

```python
if merged_rows is not region["rows"]:
    consumed_region_indexes.add(idx - 1)
```

主循环起始处：

```python
if idx in consumed_region_indexes:
    continue
```

- [ ] **Step 3: 运行目标回归和全文件测试**

Run:

```bash
pytest tests/test_table_extractor.py -v
```

Expected:

- 新增四个回归测试全部通过
- 现有 `tests/test_table_extractor.py` 全部通过

- [ ] **Step 4: 运行主流程相关测试，确认没有破坏外围行为**

Run:

```bash
pytest tests/test_pipeline.py tests/test_markdown_writer.py tests/test_json_writer.py -v
```

Expected:

- 三个测试文件全部通过
- 不出现因表格 bbox 或 cell 结构变化导致的外围序列化异常

- [ ] **Step 5: 高强度审计**

使用 `gpt-5.4-mini` `high` 审计以下内容：

- 新增 helper 是否职责清晰，是否有重复逻辑可以抽并
- `consumed_region_indexes` 是否会错误跳过非回并场景
- 回并后再裁边的顺序是否正确
- 新增测试是否真正覆盖了四类目标现象，而不是偶然通过

审计结论必须至少覆盖：

1. 是否还存在”正文数字碎片伪列”漏网风险
2. 是否还存在”表头被切断”但当前 merge 条件覆盖不到的边界
3. 是否有可能误伤原有文本表格用例（特别关注：`looks_prose_with_fragments` 的 `separated_hit_count < 2` 条件是否正确放行所有结构化 2 列表格）

### Task 5: 交付审阅材料

**Files:**
- Read: `src/hexai_pdf_parser/table_extractor.py`
- Read: `tests/test_table_extractor.py`

- [x] **Step 1: 整理变更摘要**

交付说明必须明确分成三部分：

- 候选收紧：新增了哪些判定
- 结构裁边：bbox 与输出区间如何变化
- 表头回并：何时合并、何时不合并

- [x] **Step 2: 整理验证证据**

至少保留以下命令结果摘要：

```bash
pytest tests/test_table_extractor.py -v
pytest tests/test_pipeline.py tests/test_markdown_writer.py tests/test_json_writer.py -v
```

摘要要求：

- 哪些新增测试覆盖了哪类历史问题
- 哪些原有测试证明没有破坏外围行为

- [x] **Step 3: 形成最终审阅清单**

最终人工审阅时，按以下清单逐项核对：

1. `text_alignment` 误判是否明显减少
2. `text_alignment` 真实表格的 bbox 是否更收敛
3. 表头回并是否只影响短 span、紧邻、重合高的场景
4. `line_projection` 逻辑是否完全未改
