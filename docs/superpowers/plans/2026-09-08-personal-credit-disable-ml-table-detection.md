# 个人征信 Pipeline 禁用 ML 表格检测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让 PersonalCreditReportPipeline 默认不创建、不调用 MLTableDetector，直接使用有线和语言感知的无线候选完成表格恢复；通用 Pipeline 保持现有默认模型行为，并允许个人征信入口显式重新启用模型。

**Architecture:** 在 TableExtractor 增加 use_ml_table_detector 开关；开启时保留现有候选门控和模型 bbox 路径，关闭时将规则候选直接去占位、去重并优先保留有线结果，然后复用同一套表头规范化和页面裁剪。Pipeline 负责把配置传入线程和进程 worker，PersonalCreditReportPipeline 和 parse_personal_credit_report 仅改变专用入口的默认值。

**Tech Stack:** Python 3.7+、PyMuPDF、pytest、现有 Table/Cell 模型、native-span wireless recovery。

## Global Constraints

- 中文/混合无线表格继续使用 native-span 新结构恢复；不得回退到 extract_zebra()、legacy _rebuild_text_aligned_table() 或 page words 二次表格重建。
- 禁用模型时不得通过无效模型路径、提高置信度或捕获模型异常来模拟禁用；必须不创建、不预处理、不调用 MLTableDetector。
- wireless_page_signal 只能作为候选信号，不能进入最终 page.tables。
- 有线 line_projection 结果优先于重叠的无线候选；最终表格不得重复输出。
- 通用 Pipeline 和既有 TableExtractor 默认行为保持不变；只有个人征信专用入口默认关闭模型。
- 修复必须测试先行；页面级交付必须同时核对结构化结果、source 标签、表格数量和最终 PNG/输出目录。
- 说明文档和 changes.md 使用中文，并记录根因、判定条件、调用位置和验证结果。

## 变更文件地图

- Modify: src/hexai_pdf_parser/tables/table_extractor.py — 保存开关；在规则候选直出和 ML 输出之间分流；实现占位信号过滤、混合候选去重和有线优先。
- Modify: src/hexai_pdf_parser/core/pipeline.py — 传递开关到 extractor factory、进程 worker 和单页 pipeline。
- Modify: src/hexai_pdf_parser/extractors/personal_credit_report.py — 专用 Pipeline 默认关闭模型；公开函数增加显式开关。
- Test: tests/test_rule_first_table_detection.py — 禁用模型的候选直出、信号过滤、重叠优先和默认 ML 兼容性。
- Test: tests/test_pipeline.py — Pipeline 配置传递和线程/进程路径。
- Test: tests/test_table_extractor.py — 个人征信默认值和 native-span source。
- Modify: changes.md — 根因、调用位置、约束和验证结果。

---

### Task 1: 添加 TableExtractor 禁用模型的失败测试

**Files:**
- Modify: tests/test_rule_first_table_detection.py

**Interfaces:**
- Consumes: TableExtractor(use_ml_table_detector=False)、现有 _page()、_table() 和候选注入辅助函数。
- Produces: 后续实现必须满足的候选直出和占位信号过滤行为。

- [ ] **Step 1: Write the failing tests**

新增以下三个测试；检测器被调用时立即失败：

~~~python
def test_model_disabled_uses_wireless_candidates_without_detector(monkeypatch):
    extractor = TableExtractor(use_ml_table_detector=False)
    wireless = _table("wireless_span_recovery", 20)
    _configure_rule_candidates(extractor, [])
    extractor._extract_via_text_alignment = (
        lambda page, excluded_regions=None: [wireless]
    )

    class FailDetector:
        def detect_with_scores(self, page):
            raise AssertionError("ML detector must not run when disabled")

    extractor._ml_detector = FailDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == [wireless]


def test_model_disabled_drops_wireless_page_signal(monkeypatch):
    extractor = TableExtractor(use_ml_table_detector=False)
    extractor._wireless_extractor.extract_zebra = lambda page: []
    extractor._wired_extractor.extract = lambda page: []

    def signal_alignment(page, excluded_regions=None):
        extractor._last_wireless_recovery = {
            "page_signal": {
                "matched": True,
                "bbox": {"x0": 20.0, "y0": 40.0, "x1": 380.0, "y1": 180.0},
            }
        }
        return []

    extractor._extract_via_text_alignment = signal_alignment

    class FailDetector:
        def detect_with_scores(self, page):
            raise AssertionError("ML detector must not run for signal-only page")

    extractor._ml_detector = FailDetector()
    monkeypatch.setattr(
        "hexai_pdf_parser.extractors.language_detector.detect_page_language",
        lambda page: "mixed",
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == []


def test_model_disabled_prefers_wired_overlapping_wireless_candidate(monkeypatch):
    extractor = TableExtractor(use_ml_table_detector=False)
    wired = _table("line_projection", 10)
    wireless = _table("wireless_span_recovery", 20)
    extractor._wireless_extractor.extract_zebra = lambda page: []
    extractor._wired_extractor.extract = lambda page: [wired]
    extractor._extract_via_text_alignment = (
        lambda page, excluded_regions=None: [wireless]
    )
    monkeypatch.setattr(
        "hexai_pdf_parser.tables.table_extractor.normalize_page_rotation",
        lambda page: None,
        raising=False,
    )

    assert extractor.extract(_page()) == [wired]
~~~

- [ ] **Step 2: Run the focused tests and verify they fail**

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q tests/test_rule_first_table_detection.py -k "model_disabled"
~~~

Expected: collection succeeds and the new tests fail because the constructor does not yet accept use_ml_table_detector.

### Task 2: 实现 TableExtractor 的直接候选路径

**Files:**
- Modify: src/hexai_pdf_parser/tables/table_extractor.py:101-136, 581-631

**Interfaces:**
- Consumes: use_ml_table_detector: bool = True and _detect_rule_candidates() output.
- Produces: extract(page) 在开关关闭时不触摸 MLTableDetector，直接返回清理后的规则/native-span 表格。

- [ ] **Step 1: Add the constructor flag and helper**

保存 _use_ml_table_detector，增加直接候选 helper。其核心语义如下：

~~~python
def _extract_rule_tables(self, page, candidates, page_language):
    wired_tables = [
        self._recover_hybrid_wired_table(page, table, page_language)
        for table in candidates
        if table.source == "line_projection"
    ]
    tables = list(wired_tables)
    for candidate in candidates:
        if candidate.source in {"line_projection", "wireless_page_signal"}:
            continue
        if any(self._bbox_overlaps(candidate.bbox, table.bbox) for table in tables):
            continue
        tables.append(candidate)
    return tables
~~~

- [ ] **Step 2: Branch before model invocation**

将现有无条件的 _extract_model_tables() 改为：

~~~python
if self._use_ml_table_detector:
    tables = self._extract_model_tables(
        page, wired_tables=wired_tables, page_language=page_language
    )
else:
    tables = self._extract_rule_tables(
        page, candidates=candidates, page_language=page_language
    )
~~~

保留两条路径后面的 layout rules、中文表头规范化、bbox 裁剪、debug snapshot 和排序逻辑不变。

- [ ] **Step 3: Run focused tests**

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q tests/test_rule_first_table_detection.py -k "model_disabled or rule_hit_calls_model or rule_miss_does_not_call_model or native_page_signal"
~~~

Expected: 新测试和既有默认 ML 路径测试通过。

### Task 3: 贯通 Pipeline 和个人征信公开入口

**Files:**
- Modify: src/hexai_pdf_parser/core/pipeline.py:108-186, 333-385, 402-445, 628-668
- Modify: src/hexai_pdf_parser/extractors/personal_credit_report.py:513-537
- Test: tests/test_pipeline.py、tests/test_table_extractor.py

**Interfaces:**
- Consumes: use_ml_table_detector from Pipeline and personal-credit API.
- Produces: generic Pipeline default True；personal-credit default False；thread/process worker 使用同一值。

- [ ] **Step 1: Add failing propagation tests**

覆盖以下约束：

~~~python
def test_personal_credit_pipeline_disables_ml_by_default():
    pipeline = PersonalCreditReportPipeline(pdf_path="unused.pdf")
    assert pipeline._create_table_extractor()._use_ml_table_detector is False


def test_personal_credit_pipeline_can_enable_ml():
    pipeline = PersonalCreditReportPipeline(
        pdf_path="unused.pdf",
        use_ml_table_detector=True,
    )
    assert pipeline._create_table_extractor()._use_ml_table_detector is True


def test_generic_pipeline_keeps_ml_enabled_by_default():
    pipeline = Pipeline(pdf_path="unused.pdf")
    assert pipeline._create_table_extractor()._use_ml_table_detector is True
~~~

- [ ] **Step 2: Run propagation tests and verify they fail**

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q tests/test_pipeline.py tests/test_table_extractor.py -k "personal_credit_pipeline or table_config"
~~~

Expected: the new assertions fail before constructor/API propagation is implemented.

- [ ] **Step 3: Propagate the flag**

在 Pipeline.__init__ 增加 use_ml_table_detector: bool = True；_create_table_extractor() 将其传给 TableExtractor。进程 worker 和 ProcessPoolExecutor.submit() 同样传递该值，再交给 _run_page_pipeline()；线程路径通过 extractor factory 继承该值。

- [ ] **Step 4: Set specialized default and public argument**

为 PersonalCreditReportPipeline 增加默认 False 的构造参数，并在 parse_personal_credit_report() 增加同名 keyword，默认 False，显式传入 True 时恢复模型。不得改变 _document_result() 输出结构。

- [ ] **Step 5: Run propagation and existing tests**

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q tests/test_pipeline.py tests/test_rule_first_table_detection.py -k "pipeline or model or rule"
~~~

### Task 4: 补充个人征信 native-span 回归测试

**Files:**
- Modify: tests/test_table_extractor.py

**Interfaces:**
- Consumes: PersonalCreditReportTableExtractor、parse_personal_credit_report、现有 native-span wireless tests。
- Produces: no-model personal path 保留 wireless_span_recovery source、Cell 和专用后处理。

- [ ] **Step 1: Add no-model native-span test**

注入一个 wireless_span_recovery 候选，安装会抛错的 detector，固定 page_language="mixed"，断言返回的 source、rows、cols 和 cells 与候选一致。

- [ ] **Step 2: Add explicit API forwarding test**

monkeypatch PersonalCreditReportPipeline.__init__/run，分别调用 parse_personal_credit_report() 和显式 use_ml_table_detector=True，断言构造参数分别为 False 和 True。

- [ ] **Step 3: Run focused table tests**

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q tests/test_table_extractor.py -k "personal_credit or native_span or wireless_extractor"
~~~

Expected: selected tests pass，且中文/混合 native-span 路径没有新增 words fallback 或 zebra 调用。

### Task 5: 更新变更说明并做静态检查

**Files:**
- Modify: changes.md

- [ ] **Step 1: Add dated Chinese change note**

记录 ml_model_path=None 不是禁用开关；个人征信 Pipeline 默认 use_ml_table_detector=False；无线 native-span 候选直接进入后处理；通用 Pipeline 不变；注明不回读 words、不进入 zebra/legacy 无线重建的约束。测试和页面输出结果只写入实际完成的数据。

- [ ] **Step 2: Run syntax and diff checks**

~~~powershell
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m compileall -q src tests/test_rule_first_table_detection.py tests/test_pipeline.py tests/test_table_extractor.py
git diff --check
~~~

### Task 6: 对 fix PDF 做端到端 source 标签验证

**Input:** D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf

**Output:** D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_personal_no_ml_20260908\

- [ ] **Step 1: Run the complete fix PDF**

~~~powershell
$env:PYTHONPATH='D:\codes\PDFLayoutParser\.worktrees\codex-disable-personal-credit-ml\src'
python -c "from collections import Counter; from pathlib import Path; from hexai_pdf_parser.extractors.personal_credit_report import PersonalCreditReportPipeline; pdf=Path(r'D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf'); out=Path(r'D:\codes\PDFLayoutParser\output\fix_zh_all_table_pages_personal_no_ml_20260908'); doc=PersonalCreditReportPipeline(pdf_path=str(pdf), output_dir=str(out), use_ml_table_detector=False).run(); counts=Counter(table.source for page in doc.pages for table in page.tables); print({'pages': doc.page_count, 'tables': sum(counts.values()), 'sources': dict(counts)}); assert 'wireless_page_signal' not in counts; assert counts.get('wireless_span_recovery', 0) > 0; assert (out / 'tables').exists(); assert list((out / 'tables').glob('*.png'))"

Expected: 完整 PDF 成功处理，不触发模型推理；最终 source 中含 wireless_span_recovery，且不含 wireless_page_signal，并生成表格 PNG。

- [ ] **Step 2: Inspect structured labels and representative PNG**

检查生成的 page/table JSON：source、bbox、rows/cols、相邻表格是否重复；视觉检查代表性 tables/page-*.png，确认表格边界、相邻表格分隔和文字归属。

- [ ] **Step 3: Record actual counts and output path**

把实际页数、表格总数、source 计数、输出目录和验证结论写入 changes.md，不预填期望值。

### Task 7: 运行 demo.py

**Script:** D:\codes\PDFLayoutParser\demo.py

**Input:** D:\codes\PDFLayoutParser\征信解析样例.pdf

**Output:** D:\codes\PDFLayoutParser\征信解析样例.json

- [ ] **Step 1: Run demo with worktree source**

~~~powershell
$env:PYTHONPATH='D:\codes\PDFLayoutParser\.worktrees\codex-disable-personal-credit-ml\src'
python 'D:\codes\PDFLayoutParser\demo.py'
~~~

Expected: exit code 0，无模型推理错误，输出 JSON 包含 document 和 pages。

- [ ] **Step 2: Validate output shape**

~~~powershell
$result = Get-Content -Raw 'D:\codes\PDFLayoutParser\征信解析样例.json' | ConvertFrom-Json
if (-not $result.document) { throw 'demo JSON missing document' }
if (-not $result.pages) { throw 'demo JSON missing pages' }
"pages=$($result.pages.Count)"
~~~

### Task 8: Final verification and commit

- [ ] **Step 1: Run relevant test suite**

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q tests/test_rule_first_table_detection.py tests/test_pipeline.py tests/test_table_extractor.py
~~~

若仍有与本次无关的旧模块/缺失 fixture collection failure，单独记录，不能宣称全部通过。

- [ ] **Step 2: Inspect diff**

~~~powershell
git status --short
git diff --stat
git diff --check
~~~

只保留本次 worktree 相关修改；根 checkout 中用户已有改动保持不动。

- [ ] **Step 3: Commit**

~~~powershell
git add src tests changes.md
git commit -m "feat: disable ML table detection for personal reports"
~~~

