# 个人征信 Rust 专用提取入口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 保持 Python 公开接口和输出严格不变，将个人征信表格检测、查询记录恢复和结构处理迁移到 Rust，并用 个人信用报告 目录下全部 PDF 端到端对照。

**Architecture:** Python 继续读取 PDF、做页面采集和结果装配；Rust 新增个人征信专用 DTO、算法入口和 PyO3 binding。Python 通过独立 personal-credit 路由支持 python、shadow、rust 模式，适配 Rust 输出回现有 Table/Cell。全部样本严格匹配后才允许切换个人征信默认路由。

**Tech Stack:** Rust 2021、PyO3 0.22.6/abi3、maturin 1.8.7、Python 3.13 venv、PyMuPDF、pytest。

## Global Constraints

- Python 当前 parse_personal_credit_report() 是唯一行为 oracle；签名、返回结构、schema、source、bbox、行列、文字和跨度必须不变。
- oracle 来自当前 feature-dev 提交 771e6e43819c5788c074b770d3adfd7208527125；dev-rust 的部分通用表格 Python 模块已与 feature-dev 不同，因此最终接受性比较必须分别运行 feature-dev checkout 和 Rust worktree，不能只依赖 Rust worktree 内部 shadow 模式。
- Rust 只接收 owned DTO；不得接收 fitz.Page；中文/混合无线表格结构阶段不得回读 page.get_text("words")。
- 中文/混合无线路径继续使用 native-span 新结构，不回退 extract_zebra() 或 legacy words 重建。
- 通用 PDF 默认路由保持 Python；未满足零差异和零 fallback 前，个人征信默认路由也保持 Python。
- 每个新行为先写并实际运行失败测试，再实现；不得用 broad ignore、放宽容差或吞掉 occupancy conflict 制造 parity。
- 所有 PDF 输出写入全新独立目录；说明和 changes.md 用中文记录命令、计数、差异和路径。

---

### Task 1: 个人征信 DTO 和 binding 契约

**Files:**
- Create: tests/test_pdf_fast_personal_credit.py
- Modify: rust/types.rs
- Modify: rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py

**Interfaces:**
- Consumes: PageSnapshotDto、TableCandidateDto、CellDto、DiagnosticDto。
- Produces: recover_personal_credit_tables(input_dto: Mapping[str, Any]) -> Mapping[str, Any]，输出含 schema_version、tables、diagnostics。

- [ ] **Step 1: 写入口缺失和 DTO 校验失败测试**

~~~
def test_personal_credit_binding_rejects_missing_snapshot():
    from hexai_pdf_parser import rust_adapter
    with pytest.raises((TypeError, ValueError)):
        rust_adapter.recover_personal_credit_tables({"schema_version": 1})


def test_personal_credit_binding_returns_versioned_empty_output():
    from hexai_pdf_parser import rust_adapter
    result = rust_adapter.recover_personal_credit_tables({
        "schema_version": 1,
        "snapshot": _minimal_snapshot_dto(),
        "wired_line_tolerance": 2.2,
    })
    assert result["schema_version"] == 1
    assert result["tables"] == []
    assert result["diagnostics"] == []
~~~

- [ ] **Step 2: 确认测试以预期原因失败**

~~~
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_pdf_fast_personal_credit.py -q
~~~

Expected: FAIL because the Rust entry point is missing.

- [ ] **Step 3: 定义 owned DTO**

在 rust/types.rs 中定义 PersonalCreditInput（schema_version、snapshot、wired_line_tolerance）和 PersonalCreditOutput（schema_version、tables、diagnostics），实现 from_py/to_py。验证版本、有限且非负的容差、必需字段与项目中现有 DTO 的类型约束。

- [ ] **Step 4: 建立 Rust 模块与 PyO3 binding**

在 rust/lib.rs 注册 personal_credit 模块和 recover_personal_credit_tables 函数。初始 Rust 算法只返回合法空输出，用于通过绑定契约；不要把它接入生产路由。

- [ ] **Step 5: 实现适配层并确认 GREEN**

在 rust_adapter.py 增加输入包装和扩展调用，验证返回类型、schema_version、tables、diagnostics。重建 binding 并运行 Task 1 测试。

~~~
$env:VIRTUAL_ENV="D:\codes\PDFLayoutParser\.venv"
maturin develop --release
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_pdf_fast_personal_credit.py -q
~~~

- [ ] **Step 6: 提交 DTO/binding**

~~~
git add tests/test_pdf_fast_personal_credit.py rust/types.rs rust/lib.rs rust/personal_credit.rs src/hexai_pdf_parser/rust_adapter.py
git commit -m "feat: add personal credit Rust DTO binding"
~~~

---

### Task 2: 迁移个人征信 wired、wireless 和查询表算法

**Files:**
- Create: rust/personal_credit.rs
- Modify: rust/types.rs、rust/lib.rs
- Test: tests/test_pdf_fast_personal_credit.py

**Interfaces:**
- Consumes: 页面几何、drawings、native spans、words 的采集快照和 wired 容差。
- Produces: PersonalCreditOutput，表格结构复用 TableCandidateDto/CellDto，保留 Python 的 source。

- [ ] **Step 1: 为查询记录正例和编号正文反例写失败测试**

~~~
def test_rust_personal_credit_recovers_four_query_columns_and_title_span():
    table = _run_rust(_query_snapshot_fixture())["tables"][0]
    assert table["source"] == "personal_query_recovery"
    assert table["rows"] == 3
    assert table["cols"] == 4
    assert table["cells"][0]["text"] == "本人查询记录明细"
    assert table["cells"][0]["colspan"] == 4


def test_rust_personal_credit_rejects_numbered_prose_candidate():
    assert _run_rust(_numbered_prose_snapshot_fixture())["tables"] == []
~~~

夹具覆盖 native spans、source positions、四列边界、记录续行；反例复现 Python 拒绝的“明细如下”编号正文。

- [ ] **Step 2: 运行 RED 测试**

~~~
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_pdf_fast_personal_credit.py -k "query or prose" -q
~~~

Expected: FAIL because the Rust output is empty.

- [ ] **Step 3: 复用已有 Rust wired/native-span 核心**

检查 rust/wired.rs、rust/native_span.rs、rust/wireless_structure.rs 的真实导出函数后，在 personal_credit::recover 中组合已存在的纯算法。不得照计划里的假设函数名直接调用不存在的符号。只消费页面快照和 owned DTO，不新增 PyMuPDF/page words 访问。

- [ ] **Step 4: 移植查询表恢复行为**

按 Python _query_rows、_make_query_table、_make_query_tables 的判定顺序实现：按 source/native flow 聚合行；识别机构/个人/本人查询标题和四个 header；按 header 中心计算列边界，缺失 header 时使用 [105.0, 240.0, 440.0]；记录识别、无编号续行并入、空槽位物化、标题 colspan=4、source personal_query_recovery、confidence 0.95 和 bbox union。

- [ ] **Step 5: 移植个人征信过滤与拆分**

覆盖 _is_numbered_prose_candidate、_is_report_metadata_candidate、_is_wired_table、_split_repeated_record_table；拆分起始字段为“处罚机构”“立案法院”“执行法院”。每次 rowspan/colspan 变化后运行 occupancy 检查；冲突必须诊断并拒绝输出。

- [ ] **Step 6: 重建并运行 focused tests**

~~~
$env:VIRTUAL_ENV="D:\codes\PDFLayoutParser\.venv"
maturin develop --release
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_pdf_fast_personal_credit.py -q
cargo test --lib personal_credit
~~~

Expected: all focused Python and Rust tests pass.

- [ ] **Step 7: 提交算法迁移**

~~~
git add rust/personal_credit.rs rust/types.rs rust/lib.rs tests/test_pdf_fast_personal_credit.py
git commit -m "feat: migrate personal credit table recovery to Rust"
~~~

---

### Task 3: 接入 Python 入口和三模式路由

**Files:**
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/extractors/personal_credit_report.py
- Test: tests/test_personal_credit_report.py
- Test: tests/test_rust_migration_routing.py

**Interfaces:**
- Consumes: 页面快照、PersonalCreditInput 和现有 run_python_or_rust。
- Produces: rust 模式返回 Rust 适配后的 Table 列表；shadow 返回 Python 结果并记录字段级差异；默认仍为 Python。

- [ ] **Step 1: 写默认和显式 Rust 路由失败测试**

~~~
def test_personal_credit_default_route_stays_python(monkeypatch):
    monkeypatch.delenv("PDF_RUST_MODE_PERSONAL_CREDIT", raising=False)
    extractor = PersonalCreditReportTableExtractor(use_ml_table_detector=False)
    assert extractor._personal_credit_mode() == "python"


def test_personal_credit_rust_route_uses_rust_adapter(monkeypatch):
    monkeypatch.setenv("PDF_RUST_MODE_PERSONAL_CREDIT", "rust")
    calls = []
    monkeypatch.setattr(
        "hexai_pdf_parser.extractors.personal_credit_report.rust_adapter.recover_personal_credit_tables",
        lambda dto: calls.append(dto) or {
            "schema_version": 1, "tables": [], "diagnostics": []
        },
    )
    extractor = PersonalCreditReportTableExtractor(use_ml_table_detector=False)
    extractor._extract_personal_credit_tables(_minimal_page())
    assert calls
~~~

- [ ] **Step 2: 确认 RED**

~~~
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_personal_credit_report.py tests/test_rust_migration_routing.py -k "personal_credit" -q
~~~

Expected: FAIL because no personal-credit route exists.

- [ ] **Step 3: 实现输入和输出适配**

在 rust_adapter.py 复用 page_snapshot_to_rust_input，新增 personal_credit_snapshot_to_rust_input 和 personal_credit_tables_to_project。输出必须显式校验 schema、table/cell 字段、rows/cols、bbox、span 和 occupancy，再构造现有 Table/Cell。

- [ ] **Step 4: 接入 PersonalCreditReportTableExtractor**

将当前 Python 提取主体保留为 _extract_personal_credit_tables_python；增加 Rust route helper，通过 rust_adapter.get_rust_mode("personal-credit") 和 run_python_or_rust 选择实现。保持 parse_personal_credit_report、_document_result、compact result 和默认 Python 行为不变。

- [ ] **Step 5: 运行路由及相关回归**

~~~
$env:VIRTUAL_ENV="D:\codes\PDFLayoutParser\.venv"
maturin develop --release
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_personal_credit_report.py tests/test_table_extractor.py tests/test_rust_migration_routing.py -q
~~~

Expected: existing tests pass; default remains Python; shadow returns Python output.

- [ ] **Step 6: 提交 Python 路由**

~~~
git add src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/extractors/personal_credit_report.py tests/test_personal_credit_report.py tests/test_rust_migration_routing.py
git commit -m "feat: route personal credit extraction through Rust modes"
~~~

---

### Task 4: 全部 PDF 端到端差分验证

**Files:**
- Create: scripts/verify_personal_credit_rust_e2e.py
- Create: tests/test_personal_credit_rust_e2e.py

**Interfaces:**
- Consumes: D:\codes\PDFLayoutParser\个人信用报告 下所有 PDF、feature-dev Python oracle checkout 和当前 Rust worktree。
- Produces: 独立 output/personal_credit_rust_e2e_<timestamp>/manifest.json、Python/Rust 输出、差分和诊断汇总。

- [ ] **Step 1: 写全量差分测试**

~~~
def test_personal_credit_rust_matches_python_for_all_fixture_pdfs(tmp_path):
    report = run_personal_credit_e2e(
        python_root=Path(r"D:\codes\PDFLayoutParser"),
        rust_root=find_rust_checkout(),
        fixture_root=Path(r"D:\codes\PDFLayoutParser\个人信用报告"),
        output_root=tmp_path / "personal-credit-rust",
    )
    assert report["pdf_count"] == 12
    assert report["mismatch_count"] == 0
    assert report["rust_fallback_count"] == 0
~~~

先运行并保存预期失败结果；失败报告需要每个 PDF 的相对路径、页数、表格数、diff 路径和诊断路径。

- [ ] **Step 2: 实现可重现 runner**

递归发现 D:\codes\PDFLayoutParser\个人信用报告 中的 12 个 PDF 并按相对路径排序，记录每份 PDF 的 SHA-256。使用独立子进程分别从 feature-dev oracle checkout 和当前 Rust worktree 导入源码，验证 Python checkout 的 HEAD 为 771e6e43819c5788c074b770d3adfd7208527125。Python/Rust 使用彼此独立的输出目录，canonical compare 全量 output.json 和 compact JSON，比较表格数量/source/行列/单元格文本/坐标/跨度/空槽位；保存 PNG 对照证据，不覆盖已有结果。Rust worktree 自身的 shadow 结果只作诊断，不能替代 feature-dev 对照。

- [ ] **Step 3: 全量运行并逐类修复差异**

~~~
$env:VIRTUAL_ENV="D:\codes\PDFLayoutParser\.venv"
maturin develop --release
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" scripts/verify_personal_credit_rust_e2e.py --python-root "D:\codes\PDFLayoutParser" --rust-root (Get-Location).Path --fixture-root "D:\codes\PDFLayoutParser\个人信用报告" --output-root "D:\codes\PDFLayoutParser\output\personal_credit_rust_e2e_20260927"
~~~

Expected: all PDFs listed, zero JSON/table mismatch, zero fallback. 每种差异先增加 focused RED 测试再修复，然后重跑全量 PDF。

- [ ] **Step 4: 运行既有全量征信 smoke tests**

~~~
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_all_personal_credit_reports.py -q
~~~

- [ ] **Step 5: 提交 runner 和测试**

只提交脚本、测试及小型 manifest 摘要；PDF/PNG/JSON 运行产物留在独立 ignored output 目录。

---

### Task 5: 最终验收和迁移记录

**Files:**
- Modify: changes.md
- Modify: docs/superpowers/rust-migration/current-status.md（仅当该文件在当前分支可提交）
- Test: 新增和既有征信/Rust tests

- [ ] **Step 1: 运行完整验证矩阵**

~~~
$env:VIRTUAL_ENV="D:\codes\PDFLayoutParser\.venv"
maturin develop --release
$env:PYTHONPATH="src"
& "D:\codes\PDFLayoutParser\.venv\Scripts\python.exe" -m pytest tests/test_pdf_fast_personal_credit.py tests/test_personal_credit_report.py tests/test_table_extractor.py tests/test_rust_migration_routing.py tests/test_personal_credit_rust_e2e.py -q
cargo test --lib
cargo check
~~~

- [ ] **Step 2: 逐项核对验收契约**

检查 API、默认路由、通用路径、征信 compact JSON、表格数量/source/行列/文本/bbox/span/空槽位、diagnostics、PNG 和输入 hash。任何失败都保持个人征信默认 Python 并记录未决差异。

- [ ] **Step 3: 仅在门禁全通过后切换个人征信默认值**

仅当所有 PDF mismatch_count=0、rust_fallback_count=0、occupancy_conflict_count=0，才将 personal-credit 的默认模式改为 rust；新增测试确认通用路径仍默认为 python。未过门禁不切换。

- [ ] **Step 4: 用中文更新 changes.md**

记录根因和迁移边界、binding/route 名称、调用位置、不回读 words 约束、测试计数、cargo/maturin 结果、PDF 数量、manifest、JSON/PNG 对照和未通过门禁。

- [ ] **Step 5: 提交验收记录**

~~~
git add changes.md docs/superpowers/rust-migration/current-status.md tests
git commit -m "docs: record personal credit Rust parity verification"
~~~

## 执行顺序与回滚边界

按 Task 1 → Task 2 → Task 3 → Task 4 → Task 5 执行。每个 Task 独立提交。差异回到 DTO/算法测试修复，不修改 Python oracle、不放宽比较器。
