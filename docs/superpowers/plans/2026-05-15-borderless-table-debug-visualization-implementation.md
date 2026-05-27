# 无线表格调试可视化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CLI / `Pipeline` 增加 `--debug` 开关，在命中 `text_alignment` 表格的页面输出“候选区域 bbox + 行框 + 列导线”的无线表格调试图，同时不改变默认输出和现有 JSON / Markdown 结果。

**Architecture:** 在 `cli.py` 与 `pipeline.py` 增加 `debug` 开关和输出目录管理；在 `table_extractor.py` 内部维护每页 `_last_text_alignment_debug` 快照；新增一个轻量级调试渲染器模块，只消费页对象、调试快照和输出路径，绘制区域框、行框与列导线。主 `extract()` 仍只返回 `List[Table]`。

**Tech Stack:** Python 3.10+, PyMuPDF, pytest, 现有 `hexai_pdf_parser` 模块。

---

## File Map

**Create**
- `src/hexai_pdf_parser/text_alignment_debug.py`
- `tests/test_text_alignment_debug.py`

**Modify**
- `src/hexai_pdf_parser/cli.py`
- `src/hexai_pdf_parser/pipeline.py`
- `src/hexai_pdf_parser/table_extractor.py`
- `tests/test_table_extractor.py`
- `tests/test_pipeline.py`

**Reference Only**
- `src/hexai_pdf_parser/text_visual_debug.py`
- `docs/superpowers/specs/2026-05-15-borderless-table-debug-visualization-design.md`

## 实施约束

- 默认不启用 debug，关闭时行为必须与当前版本一致
- 不修改 `output.json` / `output.md` schema
- 不修改 `LayoutBuilder`
- 不改变 `TableExtractor.extract()` 的公开返回值
- 第一版只画候选区域 bbox、行框、列导线，不画 cell / token
- 只为命中 `source="text_alignment"` 的页面输出调试图

## Task 1: 先锁定 CLI / Pipeline 调试输出行为

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `src/hexai_pdf_parser/cli.py`
- Modify: `src/hexai_pdf_parser/pipeline.py`

- [ ] **Step 1: 写失败测试，定义 Pipeline 在 `debug=False` 时不产出调试目录**

在 `tests/test_pipeline.py` 中新增测试，验证默认运行不生成 `debug/text-alignment` 目录：

```python
def test_pipeline_without_debug_does_not_create_text_alignment_debug_dir(tmp_dir):
    pdf_path = Path(tmp_dir) / "plain_table.pdf"
    output_dir = Path(tmp_dir) / "out"
    make_synthetic_text_alignment_pdf(
        pdf_path,
        [
            (30.0, [(20.0, "A"), (150.0, "10")]),
            (48.0, [(20.0, "B"), (150.0, "20")]),
        ],
    )

    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
    ).run()

    debug_dir = output_dir / "debug" / "text-alignment"
    assert debug_dir.exists() is False
```

- [ ] **Step 2: 再写失败测试，定义 `debug=True` 且命中无线表格时会输出调试图**

继续在 `tests/test_pipeline.py` 新增测试，验证 debug 输出文件存在：

```python
def test_pipeline_with_debug_writes_text_alignment_debug_image(tmp_dir):
    pdf_path = Path(tmp_dir) / "text_alignment.pdf"
    output_dir = Path(tmp_dir) / "out"
    make_synthetic_text_alignment_pdf(
        pdf_path,
        [
            (30.0, [(20.0, "项目A"), (180.0, "10"), (300.0, "20")]),
            (48.0, [(20.0, "项目B"), (180.0, "11"), (300.0, "21")]),
        ],
        page_size=(360.0, 220.0),
    )

    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
        debug=True,
    ).run()

    image_path = output_dir / "debug" / "text-alignment" / "page-000.png"
    assert image_path.exists()
    assert image_path.stat().st_size > 0
```

- [ ] **Step 3: 再写失败测试，定义纯线框表格页不输出无线表格调试图**

继续在 `tests/test_pipeline.py` 新增测试：

```python
def test_pipeline_with_debug_skips_pages_without_text_alignment_tables(tmp_dir):
    pdf_path = Path(tmp_dir) / "line_table.pdf"
    output_dir = Path(tmp_dir) / "out"
    make_pdf_with_table(pdf_path)

    Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(output_dir),
        render_dpi=120,
        debug=True,
    ).run()

    image_path = output_dir / "debug" / "text-alignment" / "page-000.png"
    assert image_path.exists() is False
```

- [ ] **Step 4: 运行测试，确认当前实现失败**

Run:

```bash
pytest tests/test_pipeline.py -k "text_alignment_debug" -v
```

Expected:

```text
FAILED tests/test_pipeline.py::test_pipeline_with_debug_writes_text_alignment_debug_image
FAILED tests/test_pipeline.py::test_pipeline_with_debug_skips_pages_without_text_alignment_tables
```

失败原因应为 `Pipeline.__init__()` 不接受 `debug` 参数，或主流程尚未创建/写出调试输出。

- [ ] **Step 5: 提交测试基线**

```bash
git add tests/test_pipeline.py
git commit -m "test: define text alignment debug pipeline behavior"
```

## Task 2: 实现页面级无线表格调试渲染器

**Files:**
- Create: `src/hexai_pdf_parser/text_alignment_debug.py`
- Create: `tests/test_text_alignment_debug.py`

- [ ] **Step 1: 写失败测试，定义 renderer 最小 API**

在 `tests/test_text_alignment_debug.py` 中新增测试，定义独立渲染器的最小行为：

```python
from pathlib import Path

import fitz

from hexai_pdf_parser.text_alignment_debug import render_text_alignment_debug_page


def test_render_text_alignment_debug_page_creates_png(tmp_dir):
    pdf_path = Path(tmp_dir) / "debug_page.pdf"
    output_path = Path(tmp_dir) / "page-000.png"

    doc = fitz.open()
    try:
        page = doc.new_page(width=360, height=220)
        page.insert_text((20, 40), "项目A")
        page.insert_text((180, 40), "10")
        page.insert_text((300, 40), "20")
        doc.save(str(pdf_path))
    finally:
        doc.close()

    doc = fitz.open(str(pdf_path))
    try:
        render_text_alignment_debug_page(
            page=doc[0],
            debug_payload={
                "page_index": 0,
                "regions": [
                    {
                        "bbox": {"x0": 20.0, "y0": 30.0, "x1": 320.0, "y1": 60.0},
                        "rows": [
                            {"x0": 20.0, "y0": 30.0, "x1": 320.0, "y1": 42.0},
                        ],
                        "column_guides": [20.0, 180.0, 300.0],
                    }
                ],
            },
            output_path=str(output_path),
            dpi=120,
        )
    finally:
        doc.close()

    assert output_path.exists()
    assert output_path.stat().st_size > 0
```

- [ ] **Step 2: 运行测试，确认当前实现失败**

Run:

```bash
pytest tests/test_text_alignment_debug.py -v
```

Expected:

```text
FAILED tests/test_text_alignment_debug.py::test_render_text_alignment_debug_page_creates_png
```

失败原因应为模块或函数尚不存在。

- [ ] **Step 3: 实现最小 renderer**

创建 `src/hexai_pdf_parser/text_alignment_debug.py`，先写一个最小实现：

```python
import os

import fitz


def render_text_alignment_debug_page(
    page: fitz.Page,
    debug_payload: dict,
    output_path: str,
    dpi: int,
) -> None:
    for region in debug_payload.get("regions", []):
        bbox = region["bbox"]
        page.draw_rect(
            fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"]),
            color=(0.62, 0.20, 0.89),
            width=2.0,
            overlay=True,
        )

        for row in region.get("rows", []):
            page.draw_rect(
                fitz.Rect(row["x0"], row["y0"], row["x1"], row["y1"]),
                color=(0.95, 0.34, 0.14),
                width=1.3,
                overlay=True,
            )

        for guide_x in region.get("column_guides", []):
            page.draw_line(
                p1=(guide_x, bbox["y0"]),
                p2=(guide_x, bbox["y1"]),
                color=(0.05, 0.55, 0.95),
                width=1.0,
                overlay=True,
            )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(output_path)
```

- [ ] **Step 4: 运行测试，确认 renderer 通过**

Run:

```bash
pytest tests/test_text_alignment_debug.py -v
```

Expected:

```text
PASSED tests/test_text_alignment_debug.py::test_render_text_alignment_debug_page_creates_png
```

- [ ] **Step 5: 提交 renderer**

```bash
git add src/hexai_pdf_parser/text_alignment_debug.py tests/test_text_alignment_debug.py
git commit -m "feat: add text alignment debug renderer"
```

## Task 3: 在 `TableExtractor` 记录调试快照

**Files:**
- Modify: `src/hexai_pdf_parser/table_extractor.py`
- Modify: `tests/test_table_extractor.py`

- [ ] **Step 1: 写失败测试，定义 `_last_text_alignment_debug` 快照结构**

在 `tests/test_table_extractor.py` 中新增测试：

```python
    def test_extract_via_text_alignment_records_debug_snapshot(self, tmp_dir):
        pdf_path = Path(tmp_dir) / "debug_snapshot.pdf"
        make_synthetic_text_alignment_pdf(
            pdf_path,
            [
                (30.0, [(20.0, "项目A"), (180.0, "10"), (300.0, "20")]),
                (48.0, [(20.0, "项目B"), (180.0, "11"), (300.0, "21")]),
            ],
            page_size=(360.0, 220.0),
        )

        doc = fitz.open(str(pdf_path))
        try:
            extractor = TableExtractor()
            tables = extractor._extract_via_text_alignment(doc[0])
            assert len(tables) == 1

            snapshot = extractor._last_text_alignment_debug
            assert snapshot is not None
            assert snapshot["page_index"] == 0
            assert len(snapshot["regions"]) == 1
            region = snapshot["regions"][0]
            assert "bbox" in region
            assert "rows" in region
            assert "column_guides" in region
            assert len(region["rows"]) >= 2
            assert len(region["column_guides"]) >= 2
        finally:
            doc.close()
```

- [ ] **Step 2: 运行测试，确认当前实现失败**

Run:

```bash
pytest tests/test_table_extractor.py -k "records_debug_snapshot" -v
```

Expected:

```text
FAILED tests/test_table_extractor.py::TestTableExtractor::test_extract_via_text_alignment_records_debug_snapshot
```

失败原因应为 `_last_text_alignment_debug` 尚未建立或为空。

- [ ] **Step 3: 在 `TableExtractor` 中实现调试快照**

在 `TableExtractor.__init__()` 中初始化：

```python
        self._last_text_alignment_debug: dict | None = None
```

在 `_extract_via_text_alignment()` 开头先清空：

```python
        self._last_text_alignment_debug = None
```

在最终生成 `tables` 后，基于最终参与建格的区域信息记录快照：

```python
        if tables:
            self._last_text_alignment_debug = {
                "page_index": page.number,
                "regions": [
                    {
                        "bbox": {
                            "x0": region_bbox.x0,
                            "y0": region_bbox.y0,
                            "x1": region_bbox.x1,
                            "y1": region_bbox.y1,
                        },
                        "rows": [
                            {
                                "x0": row["x0"],
                                "y0": row["y0"],
                                "x1": row["x1"],
                                "y1": row["y1"],
                            }
                            for row in region_rows
                        ],
                        "column_guides": list(guides),
                    }
                    for ... in ...
                ],
            }
```

实现时不要用伪代码里的 `for ... in ...`，要把当前循环中真正用于建格的 region 数据收集到一个 `debug_regions` 列表里，再统一赋值给 `_last_text_alignment_debug`。

- [ ] **Step 4: 运行测试，确认快照通过**

Run:

```bash
pytest tests/test_table_extractor.py -k "records_debug_snapshot" -v
```

Expected:

```text
PASSED tests/test_table_extractor.py::TestTableExtractor::test_extract_via_text_alignment_records_debug_snapshot
```

- [ ] **Step 5: 提交快照支持**

```bash
git add src/hexai_pdf_parser/table_extractor.py tests/test_table_extractor.py
git commit -m "feat: record text alignment debug snapshot"
```

## Task 4: 在 Pipeline 中接入 `--debug` 输出

**Files:**
- Modify: `src/hexai_pdf_parser/cli.py`
- Modify: `src/hexai_pdf_parser/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: 在 CLI 中增加 `--debug` 参数**

在 `src/hexai_pdf_parser/cli.py` 中增加：

```python
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Export debug overlays for text-aligned tables",
    )
```

并在 `Pipeline(...)` 初始化时透传：

```python
        debug=args.debug,
```

- [ ] **Step 2: 在 Pipeline 构造函数中接收并保存 `debug`**

在 `src/hexai_pdf_parser/pipeline.py` 的 `__init__()` 参数中加入：

```python
        debug: bool = False,
```

并保存：

```python
        self.debug = debug
```

- [ ] **Step 3: 在逐页处理中读取 extractor 的 debug 快照并按条件输出**

在 `Pipeline.run()` 中，不要再把 `TableExtractor(...)` 直接写在 lambda 里。改成先构造 extractor，再调用：

```python
                table_extractor = TableExtractor(
                    use_ml=self.use_ml,
                    ml_model_path=self._ml_model_path,
                    ml_confidence=self._ml_confidence,
                )
                page.tables, _ = self._time_stage(
                    "table_extract",
                    lambda: table_extractor.extract(page_handle),
                )
```

在输出目录准备阶段增加：

```python
        text_alignment_debug_dir = os.path.join(
            self.output_dir,
            "debug",
            "text-alignment",
        )
        if self.debug:
            os.makedirs(text_alignment_debug_dir, exist_ok=True)
```

在 `page.tables` 产出后，插入以下逻辑：

```python
                if self.debug:
                    debug_payload = table_extractor._last_text_alignment_debug
                    has_text_alignment = any(
                        table.source == "text_alignment" for table in page.tables
                    )
                    if debug_payload and has_text_alignment:
                        debug_path = os.path.join(
                            text_alignment_debug_dir,
                            f"page-{page.index:03d}.png",
                        )
                        self._time_stage(
                            "write_text_alignment_debug",
                            lambda: render_text_alignment_debug_page(
                                page=page_handle,
                                debug_payload=debug_payload,
                                output_path=debug_path,
                                dpi=self.render_dpi,
                            ),
                        )
```

同时在文件顶部补上：

```python
from hexai_pdf_parser.text_alignment_debug import render_text_alignment_debug_page
```

- [ ] **Step 4: 运行 Pipeline 相关测试**

Run:

```bash
pytest tests/test_pipeline.py -k "text_alignment_debug" -v
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 5: 提交主流程接入**

```bash
git add src/hexai_pdf_parser/cli.py src/hexai_pdf_parser/pipeline.py src/hexai_pdf_parser/table_extractor.py tests/test_pipeline.py
git commit -m "feat: export text alignment debug overlays"
```

## Task 5: 跑回归并确认 debug 不影响主输出

**Files:**
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_table_extractor.py`
- Test: `tests/test_text_alignment_debug.py`

- [ ] **Step 1: 补一个回归测试，验证开启 debug 不改变表格来源**

在 `tests/test_pipeline.py` 中新增测试：

```python
def test_pipeline_debug_does_not_change_text_alignment_table_sources(tmp_dir):
    pdf_path = Path(tmp_dir) / "same_tables.pdf"
    out_plain = Path(tmp_dir) / "plain"
    out_debug = Path(tmp_dir) / "debug"
    make_synthetic_text_alignment_pdf(
        pdf_path,
        [
            (30.0, [(20.0, "项目A"), (180.0, "10"), (300.0, "20")]),
            (48.0, [(20.0, "项目B"), (180.0, "11"), (300.0, "21")]),
        ],
        page_size=(360.0, 220.0),
    )

    doc_plain = Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(out_plain),
        render_dpi=120,
        debug=False,
    ).run()
    doc_debug = Pipeline(
        pdf_path=str(pdf_path),
        output_dir=str(out_debug),
        render_dpi=120,
        debug=True,
    ).run()

    plain_sources = [table.source for table in doc_plain.pages[0].tables]
    debug_sources = [table.source for table in doc_debug.pages[0].tables]
    assert plain_sources == debug_sources
```

- [ ] **Step 2: 跑聚合验证**

Run:

```bash
pytest tests/test_text_alignment_debug.py -v
pytest tests/test_table_extractor.py -k "records_debug_snapshot or detect_text_regions or text_alignment" -v
pytest tests/test_pipeline.py -k "text_alignment_debug or change_text_alignment_table_sources" -v
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 3: 跑一次手工 CLI 验证**

Run:

```bash
python -m hexai_pdf_parser.cli 152590_20230428_N7ZK_0.pdf -o out_debug_demo --dpi 120 --debug
```

Expected:

```text
Success! Output written to: out_debug_demo
```

并确认目录存在：

```bash
Get-ChildItem out_debug_demo\\debug\\text-alignment
```

至少应看到若干 `page-XXX.png` 文件。

- [ ] **Step 4: 提交回归与验证结果**

```bash
git add tests/test_pipeline.py tests/test_table_extractor.py tests/test_text_alignment_debug.py
git commit -m "test: cover text alignment debug output"
```

## Self-Review

### Spec 覆盖检查

- `--debug` 经 CLI / Pipeline 打开：Task 4 Step 1-2
- 只对命中 `text_alignment` 页输出调试图：Task 4 Step 3
- 图中包含区域 bbox、行框、列导线：Task 2 Step 3
- 不改变主输出 schema：Task 3 + Task 5
- `TableExtractor.extract()` 返回值保持不变：Task 3 采用实例级 `_last_text_alignment_debug`

未发现 spec 漏项。

### 占位符检查

- 无 `TODO` / `TBD`
- 所有代码步骤均给出明确代码骨架
- 所有验证步骤均给出命令和预期结果

### 类型与命名一致性检查

- CLI / Pipeline 参数统一为 `debug`
- renderer 函数统一命名为 `render_text_alignment_debug_page`
- extractor 快照字段统一为 `_last_text_alignment_debug`
- 调试目录统一为 `debug/text-alignment`

