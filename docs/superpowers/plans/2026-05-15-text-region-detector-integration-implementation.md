# Text Region Detector 接入实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `text_region_detector` 接入 `_extract_via_text_alignment()`，把无线表格流程拆成“区域发现”和“区域内建格”两段，同时保持现有有线表格路径不变。

**Architecture:** 改动集中在 `src/pdflayoutparser/table_extractor.py`。新增 `_detect_text_regions(rows, page)` 作为适配层，把当前 row dict 转为 detector 所需的轻量 row/fragment 视图，再把 `CandidateRegion` 映射回原始 row span，并复用现有 `_infer_column_guides()` 产出兼容的 `column_guides`。`_extract_via_text_alignment()` 只替换候选区域来源，后续 header merge、trim、guide、cell 构建逻辑不动。

**Tech Stack:** Python 3.10+, PyMuPDF, pytest, 现有 `pdflayoutparser` 数据模型与 `text_region_detector`。

---

## File Map

**Modify**
- `src/pdflayoutparser/table_extractor.py`
- `tests/test_table_extractor.py`

**Reference Only**
- `src/pdflayoutparser/text_region_detector.py`
- `tests/test_text_region_detector.py`
- `docs/superpowers/specs/2026-05-15-text-region-detector-integration-design.md`

## 实施约束

- 不修改 `pipeline.py`
- 不修改 `layout_builder.py`
- 不改变 `_extract_via_lines()`、`_extract_via_pymupdf()`、`_extract_via_ml()` 的行为
- 不删除旧的 `_collect_text_candidate_regions()`，第一步只让 `_extract_via_text_alignment()` 不再依赖它
- 所有文本文件保持 UTF-8

## Task 1: 先锁定适配层接口与主链路切换的失败测试

**Files:**
- Modify: `tests/test_table_extractor.py`
- Modify: `src/pdflayoutparser/table_extractor.py`

- [ ] **Step 1: 写失败测试，定义 `_detect_text_regions()` 的返回契约**

在 `tests/test_table_extractor.py` 里新增一个直接针对适配层的测试，要求：

- `_detect_text_regions()` 返回的 region 使用原始 row dict 对象
- `bbox` 来自命中行的 union
- `column_guides` 仍然由现有 `_infer_column_guides()` 计算并返回

加入下面的测试代码：

```python
    def test_detect_text_regions_maps_detector_rows_back_to_original_rows(self, monkeypatch):
        extractor = TableExtractor()
        rows = [
            {
                "tokens": [
                    {"text": "A", "x0": 20.0, "y0": 30.0, "x1": 40.0, "y1": 42.0},
                    {"text": "10", "x0": 150.0, "y0": 30.0, "x1": 170.0, "y1": 42.0},
                ],
                "x0": 20.0,
                "y0": 30.0,
                "x1": 170.0,
                "y1": 42.0,
            },
            {
                "tokens": [
                    {"text": "B", "x0": 20.0, "y0": 48.0, "x1": 40.0, "y1": 60.0},
                    {"text": "20", "x0": 150.0, "y0": 48.0, "x1": 170.0, "y1": 60.0},
                ],
                "x0": 20.0,
                "y0": 48.0,
                "x1": 170.0,
                "y1": 60.0,
            },
        ]

        captured = {}

        def fake_detect_candidate_regions(visual_rows, horizontal_separators=None):
            captured["row_count"] = len(visual_rows)
            captured["separator_count"] = len(horizontal_separators or [])
            return [
                CandidateRegion(
                    rows=visual_rows,
                    bbox=CandidateRegion.bbox_union([row.bbox for row in visual_rows]),
                    features={"kind": "test"},
                    score=1.0,
                )
            ]

        monkeypatch.setattr(
            "pdflayoutparser.table_extractor.detect_candidate_regions",
            fake_detect_candidate_regions,
        )

        page = SimpleNamespace(
            rect=fitz.Rect(0, 0, 300, 200),
            get_drawings=lambda: [],
        )

        regions = extractor._detect_text_regions(rows, page)

        assert captured["row_count"] == 2
        assert captured["separator_count"] == 0
        assert len(regions) == 1
        assert regions[0]["rows"][0] is rows[0]
        assert regions[0]["rows"][1] is rows[1]
        assert regions[0]["bbox"].x0 == 20.0
        assert regions[0]["bbox"].y0 == 30.0
        assert regions[0]["bbox"].x1 == 170.0
        assert regions[0]["bbox"].y1 == 60.0
        assert regions[0]["column_guides"] == [20.0, 150.0]
```

- [ ] **Step 2: 再写失败测试，锁定 `_extract_via_text_alignment()` 已切换到新入口**

继续在 `tests/test_table_extractor.py` 里新增一个集成测试，要求 `_extract_via_text_alignment()` 使用 `_detect_text_regions()`，而不是继续调用 `_collect_text_candidate_regions()`：

```python
    def test_extract_via_text_alignment_uses_detect_text_regions(self, tmp_dir, monkeypatch):
        pdf_path = Path(tmp_dir) / "detect_text_regions_entry.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "A"), (150.0, "10")]),
                (48.0, [(20.0, "B"), (150.0, "20")]),
                (66.0, [(20.0, "C"), (150.0, "30")]),
            ],
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            page = doc[0]
            rows = extractor._collect_text_rows(page.get_text("words"))

            monkeypatch.setattr(
                extractor,
                "_collect_text_candidate_regions",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    AssertionError("legacy collector should not be called")
                ),
            )
            monkeypatch.setattr(
                extractor,
                "_detect_text_regions",
                lambda passed_rows, passed_page: [
                    {
                        "rows": rows,
                        "bbox": extractor._rows_bbox(rows),
                        "column_guides": extractor._infer_column_guides(rows),
                    }
                ],
            )

            tables = extractor._extract_via_text_alignment(page)

            assert len(tables) == 1
            assert tables[0].rows == 3
            assert tables[0].cols == 2
        finally:
            doc.close()
```

- [ ] **Step 3: 运行测试，确认当前实现失败**

Run:

```bash
pytest tests/test_table_extractor.py -k "detect_text_regions" -v
```

Expected:

```text
FAILED tests/test_table_extractor.py::TestTableExtractor::test_detect_text_regions_maps_detector_rows_back_to_original_rows
FAILED tests/test_table_extractor.py::TestTableExtractor::test_extract_via_text_alignment_uses_detect_text_regions
```

失败原因应为 `_detect_text_regions` 不存在，或 `_extract_via_text_alignment()` 仍然调用旧的 `_collect_text_candidate_regions()`。

- [ ] **Step 4: 提交测试基线**

```bash
git add tests/test_table_extractor.py
git commit -m "test: define text region integration behavior"
```

## Task 2: 实现 `_detect_text_regions()` 适配层

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Test: `tests/test_table_extractor.py`

- [ ] **Step 1: 在 `table_extractor.py` 顶部补齐 detector 依赖和轻量视图类型**

在 `src/pdflayoutparser/table_extractor.py` 的 import 区域补充：

```python
from dataclasses import dataclass
from types import SimpleNamespace

from pdflayoutparser.text_region_detector import (
    CandidateRegion,
    HorizontalSeparator,
    detect_candidate_regions,
)
```

如果最终没有用到 `SimpleNamespace`，删除它，避免脏 import。

紧接着在 `TableExtractor` 类定义前加入轻量视图类型，避免生产代码依赖 `text_visual_debug.py`：

```python
@dataclass
class _RegionFragmentView:
    text: str
    bbox: BBox


@dataclass
class _RegionRowView:
    fragments: list[_RegionFragmentView]
    bbox: BBox
```

- [ ] **Step 2: 实现水平分隔线提取 helper**

在 `TableExtractor` 内新增一个私有 helper，尽量复用当前原型的保守规则：

```python
    def _extract_text_region_separators(
        self,
        page: fitz.Page,
    ) -> list[HorizontalSeparator]:
        separators: list[HorizontalSeparator] = []
        try:
            drawings = page.get_drawings()
        except Exception:
            return separators

        for drawing in drawings:
            for item in drawing.get("items", []):
                if item[0] != "re":
                    continue
                rect = item[1]
                width = rect.x1 - rect.x0
                height = rect.y1 - rect.y0
                if width < 200 or height > 1.5:
                    continue
                separators.append(
                    HorizontalSeparator(
                        x0=float(rect.x0),
                        x1=float(rect.x1),
                        y=float((rect.y0 + rect.y1) / 2.0),
                    )
                )

        separators.sort(key=lambda item: (item.y, item.x0))
        deduped: list[HorizontalSeparator] = []
        for separator in separators:
            if (
                deduped
                and abs(separator.y - deduped[-1].y) <= 1.0
                and separator.x0 <= deduped[-1].x1 + 2.0
            ):
                prev = deduped[-1]
                deduped[-1] = HorizontalSeparator(
                    x0=min(prev.x0, separator.x0),
                    x1=max(prev.x1, separator.x1),
                    y=(prev.y + separator.y) / 2.0,
                )
            else:
                deduped.append(separator)
        return deduped
```

- [ ] **Step 3: 实现 `_detect_text_regions(rows, page)`**

在 `_collect_text_candidate_regions()` 前新增 `_detect_text_regions()`，要求：

- 把每个 row dict 转为 `_RegionRowView`
- 用 `id(view_row) -> original_row` 做回映射
- 调用 `detect_candidate_regions(...)`
- 把返回结果转回原始 row dict span
- 用 `_rows_bbox()` 和 `_infer_column_guides()` 生成兼容的 region dict

加入下面的实现：

```python
    def _detect_text_regions(
        self,
        rows: List[dict],
        page: fitz.Page,
    ) -> List[dict]:
        if not rows:
            return []

        visual_rows: list[_RegionRowView] = []
        original_rows_by_view_id: dict[int, dict] = {}
        for row in rows:
            fragments = [
                _RegionFragmentView(
                    text=token["text"],
                    bbox=BBox(
                        token["x0"],
                        token["y0"],
                        token["x1"],
                        token["y1"],
                    ),
                )
                for token in row["tokens"]
            ]
            visual_row = _RegionRowView(
                fragments=fragments,
                bbox=BBox(row["x0"], row["y0"], row["x1"], row["y1"]),
            )
            visual_rows.append(visual_row)
            original_rows_by_view_id[id(visual_row)] = row

        separators = self._extract_text_region_separators(page)
        candidate_regions = detect_candidate_regions(
            visual_rows,
            horizontal_separators=separators,
        )

        mapped_regions: List[dict] = []
        for region in candidate_regions:
            mapped_rows = [
                original_rows_by_view_id[id(view_row)]
                for view_row in region.rows
                if id(view_row) in original_rows_by_view_id
            ]
            if not mapped_rows:
                continue
            bbox = self._rows_bbox(mapped_rows)
            guides = self._infer_column_guides(mapped_rows, bbox)
            if len(guides) < 2:
                continue
            mapped_regions.append(
                {
                    "rows": mapped_rows,
                    "bbox": bbox,
                    "column_guides": guides,
                }
            )

        return mapped_regions
```

- [ ] **Step 4: 运行测试，确认适配层通过**

Run:

```bash
pytest tests/test_table_extractor.py -k "detect_text_regions" -v
```

Expected:

```text
PASSED tests/test_table_extractor.py::TestTableExtractor::test_detect_text_regions_maps_detector_rows_back_to_original_rows
PASSED tests/test_table_extractor.py::TestTableExtractor::test_extract_via_text_alignment_uses_detect_text_regions
```

- [ ] **Step 5: 提交适配层实现**

```bash
git add src/pdflayoutparser/table_extractor.py tests/test_table_extractor.py
git commit -m "feat: add text region detector adapter"
```

## Task 3: 切换无线表格入口并跑回归

**Files:**
- Modify: `src/pdflayoutparser/table_extractor.py`
- Modify: `tests/test_table_extractor.py`

- [ ] **Step 1: 修改 `_extract_via_text_alignment()` 使用新入口**

把这段旧代码：

```python
        page_bbox = None
        if hasattr(page, "rect"):
            rect = page.rect
            page_bbox = BBox(rect.x0, rect.y0, rect.x1, rect.y1)

        candidate_regions = self._collect_text_candidate_regions(rows, page_bbox)
```

替换为：

```python
        candidate_regions = self._detect_text_regions(rows, page)
```

并把上方注释同步改成明确的新语义：

```python
        # Identify spans rejected by _detect_text_regions so we can
        # attempt to merge them as headers with the next candidate region.
```

- [ ] **Step 2: 补一组现有无线表格用例回归断言**

在 `tests/test_table_extractor.py` 中确认并保留下面这些现有测试，必要时只收紧断言，不重写语义：

```python
    def test_extract_via_text_alignment_keeps_long_label_text_only_table(self, tmp_dir):
        ...

    def test_extract_via_text_alignment_keeps_chinese_financial_table(self, tmp_dir):
        ...

    def test_extract_via_text_alignment_trims_prose_prefix(self, tmp_dir):
        ...

    def test_extract_via_text_alignment_merges_short_header_span(self, tmp_dir):
        ...

    def test_extract_via_text_alignment_excludes_heading_rows(self, tmp_dir):
        ...
```

如果其中任一用例因 region 边界更合理而需要更新预期，只允许调整：

- `bbox` 的上下边界容差
- 行数断言中与 header merge 明确相关的部分

不允许放宽为“只要有表就行”。

- [ ] **Step 3: 运行无线表格与 detector 相关测试**

Run:

```bash
pytest tests/test_table_extractor.py -k "text_alignment or detect_text_regions" -v
pytest tests/test_text_region_detector.py -q
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 4: 运行有线路径安全性回归**

Run:

```bash
pytest tests/test_table_extractor.py -k "find_tables or no_crash_on_text_only or extract_cells_from_region" -v
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: 提交主链路切换**

```bash
git add src/pdflayoutparser/table_extractor.py tests/test_table_extractor.py
git commit -m "refactor: route text alignment through region detector"
```

## Self-Review

### Spec 覆盖检查

- “每次进入 `_extract_via_text_alignment()` 都让 detector 参与区域发现”：Task 3 Step 1
- “只替换区域发现，不动后半段建格逻辑”：Task 3 Step 1 + 现有回归测试
- “适配层负责 row/fragment 转换和回映射”：Task 2 Step 3
- “分隔线提示可选且保守”：Task 2 Step 2
- “有线路径行为保持不变”：Task 3 Step 4

未发现 spec 漏项。

### 占位符检查

- 没有 `TODO` / `TBD`
- 每个代码修改步骤都给出了明确代码片段
- 每个测试步骤都给出了具体命令和期望

### 类型与命名一致性检查

- 新 helper 名统一为 `_detect_text_regions`
- separator helper 名统一为 `_extract_text_region_separators`
- region 返回结构统一包含 `rows`、`bbox`、`column_guides`

