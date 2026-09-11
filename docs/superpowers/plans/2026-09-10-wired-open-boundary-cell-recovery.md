# 有线开放边界单元格恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** 在不放宽整张表的外部区域过滤、不读取额外业务规则的前提下，恢复 PDF 有线表格的部分缺失外边界，使带文字和纯空的逻辑 Cell 都完整输出。

**Architecture:** 在 \`WiredTableExtractor._build_cells_for_region()\` 中，网格坐标 snap 完成后、flood-fill 计算前，依据同一线网的正交完整横线和网格端点证据补齐部分水平/垂直外边界。内部缺线继续用于推导 rowspan/colspan；恢复后的 Cell 仍由现有 \`_assign_text_to_line_cells()\` 绑定页面文本。

**Tech Stack:** Python 3.7+、PyMuPDF、pytest、现有 \`WiredTableExtractor\`。

## Global Constraints

- 只修改有线 \`line_projection\` 路径，不修改中文/混合无线 native-span 结构恢复路径。
- 只补 \`bbox\` 四条外边界的连续缺段，绝不把内部缺线硬编码为分隔线。
- 结构恢复不根据页码、公司名、金额或其他业务文字做特殊分支。
- 带文字的恢复槽位必须保留原始文字；未覆盖文字的恢复槽位必须保留 \`text=""\` 的独立 Cell，除非被合法跨度覆盖。
- 每次代码变更先添加失败测试并确认失败，再实现最小修复。
- 页面级验证使用新的独立输出目录，同时检查结构化 JSON、Cell 文本/跨度、占位冲突和 PNG。
- 说明文档和 \`changes.md\` 使用中文；不修改黄金标签作为本次修复的依据。

---

### Task 1: 为部分外边界增加失败测试

**Files:**
- Modify: \`tests/test_wired_table_extractor.py\`

**Interfaces:**
- 现有 \`WiredTableExtractor._build_cells_for_region(bbox, h_lines, v_lines) -> List[Cell]\` 保持不变。
- 新测试只通过几何线段和 \`SimpleNamespace\` 页面验证真实提取行为，不添加测试专用生产 API。

- [ ] **Step 1: 添加部分底边的空槽和带文字失败测试**

追加以下测试。第一个测试证明仅有几何空槽也不能丢失；第二个测试证明恢复的 Cell 在文本绑定后必须接收右下角文字。

~~~python
def test_build_cells_keeps_empty_cell_behind_partial_bottom_boundary():
    extractor = WiredTableExtractor()

    cells = extractor._build_cells_for_region(
        BBox(0.0, 0.0, 100.0, 30.0),
        h_lines=[
            (0.0, 0.0, 100.0, 0.0),
            (0.0, 10.0, 100.0, 10.0),
            (0.0, 20.0, 100.0, 20.0),
            (0.0, 30.0, 50.0, 30.0),
        ],
        v_lines=[
            (0.0, 0.0, 0.0, 30.0),
            (50.0, 0.0, 50.0, 30.0),
            (100.0, 0.0, 100.0, 20.0),
        ],
    )

    assert len(cells) == 6
    assert any(
        cell.row_index == 2
        and cell.col_index == 1
        and cell.text == ""
        and cell.bbox == BBox(50.0, 20.0, 100.0, 30.0)
        for cell in cells
    )


def test_extract_binds_text_inside_partial_bottom_boundary_cell():
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                "color": (0.0, 0.0, 0.0),
                "fill": None,
                "items": [
                    ("l", fitz.Point(0.0, 0.0), fitz.Point(100.0, 0.0)),
                    ("l", fitz.Point(0.0, 10.0), fitz.Point(100.0, 10.0)),
                    ("l", fitz.Point(0.0, 20.0), fitz.Point(100.0, 20.0)),
                    ("l", fitz.Point(0.0, 30.0), fitz.Point(50.0, 30.0)),
                    ("l", fitz.Point(0.0, 0.0), fitz.Point(0.0, 30.0)),
                    ("l", fitz.Point(50.0, 0.0), fitz.Point(50.0, 30.0)),
                    ("l", fitz.Point(100.0, 0.0), fitz.Point(100.0, 20.0)),
                ],
            }
        ],
        get_fonts=lambda **_kwargs: [],
        get_image_info=lambda **_kwargs: [],
        get_text=lambda kind: (
            [(65.0, 22.0, 90.0, 28.0, "right-value", 0, 0, 0)]
            if kind == "words"
            else {"blocks": []}
        ),
    )

    tables = WiredTableExtractor().extract(page)

    assert len(tables) == 1
    recovered = next(
        cell
        for cell in tables[0].cells
        if cell.row_index == 2 and cell.col_index == 1
    )
    assert recovered.text == "right-value"
~~~

- [ ] **Step 2: 添加部分右边界的合并表头失败测试**

追加以下测试，模拟 Page 605 的四列四行拓扑：顶层日期没有内部竖线，第一列跨两行，右外框只从第三行开始。当前实现会把顶部开放区域标为 outside，因此预期先失败。

~~~python
def test_build_cells_closes_partial_right_boundary_without_breaking_header_span():
    extractor = WiredTableExtractor()

    cells = extractor._build_cells_for_region(
        BBox(0.0, 0.0, 100.0, 40.0),
        h_lines=[
            (0.0, 0.0, 100.0, 0.0),
            (25.0, 10.0, 100.0, 10.0),
            (0.0, 20.0, 100.0, 20.0),
            (0.0, 30.0, 100.0, 30.0),
            (0.0, 40.0, 100.0, 40.0),
        ],
        v_lines=[
            (25.0, 0.0, 25.0, 40.0),
            (50.0, 10.0, 50.0, 40.0),
            (75.0, 10.0, 75.0, 40.0),
            (100.0, 20.0, 100.0, 40.0),
        ],
    )

    assert len(cells) == 13
    date_cell = next(
        cell for cell in cells if cell.row_index == 0 and cell.col_index == 1
    )
    assert date_cell.colspan == 3
    assert any(cell.row_index == 1 and cell.col_index == 3 for cell in cells)
~~~

- [ ] **Step 3: 运行新增测试确认是预期失败**

运行：

~~~powershell
$env:PYTHONPATH = "src"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wired_table_extractor.py -k "partial_bottom_boundary or partial_right_boundary"
~~~

预期：新增测试失败，现状分别缺少右下角 Cell、右下角文字以及 Page 605 顶部合并表头；失败原因必须来自断言，不是测试收集或导入错误。

- [ ] **Step 4: 提交失败测试**

~~~powershell
git add tests/test_wired_table_extractor.py
git commit -m "test: 覆盖有线开放边界单元格"
~~~

### Task 2: 实现外边界连续性恢复

**Files:**
- Modify: \`src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py:839-920\`
- Test: \`tests/test_wired_table_extractor.py\`

**Interfaces:**
- Add private method \`_complete_partial_outer_boundaries(bbox, h_lines, v_lines, h_ys, v_xs) -> Tuple[List[Tuple[float, float, float, float]], List[Tuple[float, float, float, float]]]\` inside \`WiredTableExtractor\`.
- \`_build_cells_for_region()\` continues to return \`List[Cell]\`; all callers remain compatible.

- [ ] **Step 1: 实现最小线段覆盖工具和边界判定**

在 \`_snap_coordinates()\` 之后、\`_build_cells_for_region()\` 之前增加私有方法。该方法复制输入线段列表，合并同一坐标的区间覆盖率，只对四条外边界作补全：

~~~python
def _complete_partial_outer_boundaries(
    self,
    bbox,
    h_lines,
    v_lines,
    h_ys,
    v_xs,
):
    tol = self.line_tolerance
    effective_h = list(h_lines)
    effective_v = list(v_lines)

    def coverage(intervals, start, end):
        clipped = sorted(
            (max(start, min(left, right)), min(end, max(left, right)))
            for left, right in intervals
            if min(end, max(left, right)) > max(start, min(left, right))
        )
        total = 0.0
        current = None
        for left, right in clipped:
            if current is None:
                current = [left, right]
            elif left <= current[1] + tol:
                current[1] = max(current[1], right)
            else:
                total += current[1] - current[0]
                current = [left, right]
        if current is not None:
            total += current[1] - current[0]
        return total

    def touches(value, anchors):
        return any(abs(value - anchor) <= tol for anchor in anchors)

    width = v_xs[-1] - v_xs[0]
    height = h_ys[-1] - h_ys[0]
    full_width = max(width - tol, width * 0.9)
    full_height = max(height - tol, height * 0.9)

    def horizontal_segments(y):
        return [
            (line[0], line[2])
            for line in h_lines
            if abs(line[1] - y) <= tol
        ]

    full_width_levels = [
        y
        for y in h_ys
        if coverage(horizontal_segments(y), v_xs[0], v_xs[-1]) >= full_width
    ]

    for y in (h_ys[0], h_ys[-1]):
        boundary = [line for line in h_lines if abs(line[1] - y) <= tol]
        boundary_coverage = coverage(
            [(line[0], line[2]) for line in boundary],
            v_xs[0],
            v_xs[-1],
        )
        if boundary and boundary_coverage < full_width:
            supported = sum(abs(level - y) > tol for level in full_width_levels) >= 2
            covers_grid_column = any(
                coverage([(line[0], line[2])], left, right)
                >= max(right - left - tol, (right - left) * 0.9)
                and (touches(line[0], v_xs) or touches(line[2], v_xs))
                for line in boundary
                for left, right in zip(v_xs, v_xs[1:])
            )
            if supported and covers_grid_column:
                effective_h.append((v_xs[0], y, v_xs[-1], y))

    for x in (v_xs[0], v_xs[-1]):
        boundary = [line for line in v_lines if abs(line[0] - x) <= tol]
        boundary_coverage = coverage(
            [(line[1], line[3]) for line in boundary],
            h_ys[0],
            h_ys[-1],
        )
        if boundary and boundary_coverage < full_height:
            supported = len(full_width_levels) >= 2
            covers_grid_row = any(
                coverage([(line[1], line[3])], top, bottom)
                >= max(bottom - top - tol, (bottom - top) * 0.9)
                and (touches(line[1], h_ys) or touches(line[3], h_ys))
                for line in boundary
                for top, bottom in zip(h_ys, h_ys[1:])
            )
            if supported and covers_grid_row:
                effective_v.append((x, h_ys[0], x, h_ys[-1]))

    return effective_h, effective_v
~~~

- [ ] **Step 2: 将恢复结果接入现有边缘计算**

在 \`_build_cells_for_region()\` 计算 \`h_ys\`、\`v_xs\` 并确认至少两条坐标后，先调用：

~~~python
effective_h_lines, effective_v_lines = (
    self._complete_partial_outer_boundaries(
        bbox, h_lines, v_lines, h_ys, v_xs
    )
)
~~~

随后保留现有的“完全没有对应外边界线时合成整条边界”逻辑，并让 \`h_edges\`/\`v_edges\` 继续消费 \`effective_h_lines\` 和 \`effective_v_lines\`。不得改变内部线段的 \`has_h_segment\`、\`has_v_segment\` 判定和 Union-Find 合并规则。

- [ ] **Step 3: 运行新增测试确认通过**

~~~powershell
$env:PYTHONPATH = "src"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wired_table_extractor.py -k "partial_bottom_boundary or partial_right_boundary"
~~~

预期：新增测试全部通过，带文字测试必须看到 \`right-value\` 进入 \`(row_index=2, col_index=1)\`。

- [ ] **Step 4: 运行有线提取器完整回归**

~~~powershell
$env:PYTHONPATH = "src"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wired_table_extractor.py
~~~

预期：原基线 33 个测试加新增测试全部通过；若失败，先修正实现或测试，不继续页面级运行。

- [ ] **Step 5: 提交生产修复**

~~~powershell
git add src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py tests/test_wired_table_extractor.py
git commit -m "fix: 恢复有线表格开放边界单元格"
~~~

### Task 3: 真实页面验证、记录变更并检查回归范围

**Files:**
- Modify: \`changes.md\`
- Create: \`output/fix_wired_open_boundary_cells_20260910/\`（仅生成验证产物，不提交）

**Interfaces:**
- 真实输入：\`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf\`。
- 目标页：599、600、605、609；页索引与项目输出保持一致。
- 黄金比较脚本：\`scripts/markdown_golden_testset.py\`；本次不自动更新 labels。

- [ ] **Step 1: 运行四个目标页的真实 PDF 提取**

使用项目已有的页面级入口，仅选择页索引 599、600、605、609，输出到全新目录 \`output/fix_wired_open_boundary_cells_20260910/single_pages/\`。记录每页表格数量、目标表格 \`source\`、bbox、行列数和 Cell 列表，确认：

~~~text
599 / Table 3 -> R8C6 = 903,152.90
600 / Table 5 -> R3C4 = 9,656.85
605 / Table 2 -> R1C2 colspan=3 且文本为 2016 年3 月31 日；R2C4 = 账面价值
609 / Table 5 -> R4C5 = ---
~~~

- [ ] **Step 2: 检查结构占用和渲染图**

对四个目标表格运行现有结构可视化/占用检查，确认每个逻辑槽位恰好由一个 Cell 占用，没有冲突；同时打开新目录中的原始页面 PNG 和表格 PNG，确认没有吸收相邻表格、页眉、页脚或正文。

- [ ] **Step 3: 更新中文变更记录**

在 \`changes.md\` 增加日期、根因、调用位置、只恢复外边界的判定条件、文本恢复结果、测试命令和页面输出路径。明确说明原始 PDF 的缺线仍保留在原图中，解析器只在结构输出中恢复逻辑边界，不修改 PDF。

- [ ] **Step 4: 运行相关模块回归和差异检查**

~~~powershell
$env:PYTHONPATH = "src"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_wired_table_extractor.py tests/test_table_extractor.py tests/test_pipeline.py
git diff --check
~~~

记录真实失败数量及原因；不能把未运行或受环境影响的测试描述为通过。

- [ ] **Step 5: 运行全量 E2E 到新目录并独立比较**

将 1,023 页分块运行到新目录 \`output/fix_wired_open_boundary_cells_20260910/e2e/\`，逐块确认 \`skipped=0\`，确认 \`pages/\` 覆盖 0-1022，检查目标页 JSON/PNG，再运行 \`scripts/markdown_golden_testset.py\`。若新结果比旧标签多出原始 PDF 中真实存在的文本，只报告差异，不重建标签。

- [ ] **Step 6: 提交变更记录**

~~~powershell
git add changes.md
git commit -m "docs: 记录有线开放边界恢复验证"
~~~
