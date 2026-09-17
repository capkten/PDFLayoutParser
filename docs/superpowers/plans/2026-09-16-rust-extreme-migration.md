# PDF 表格逻辑 Rust 极限迁移实施计划

> For agentic workers: REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，逐任务执行并在任务间评审。每步用 - [ ] 跟踪。若使用 subagent，model 只能是 gpt-5.6-luna。

**Goal:** 在保持 Python/PyMuPDF 输入边界、公开 API 和输出完全兼容的前提下，将所有可表达为 owned DTO 的表格纯算法尽可能迁移到 Rust，并用函数级、FFI 级、区域级、页面级和全量 PDF benchmark 给出真实前后对比。

**Architecture:** Python 负责 PDF/PyMuPDF 数据采集、ML 推理、语言路由、公开 API、Table/Cell 构造和序列化；Rust 通过 PyO3 接收按页或区域批量传入的 owned DTO，执行几何、线网、span、网格、跨度和表格候选算法，再把 owned result DTO 交给 Python 适配。生产路径支持 python、shadow、rust 三种模式，默认保持 Python，单模块通过输出和性能门禁后才切换。

**Tech Stack:** Rust 2021、PyO3 0.22.6、maturin、abi3 cp37、Python 3.7+、PyMuPDF、pytest、现有 PDFParser 流水线。

## Global Constraints

- Python 最低版本保持 >=3.7；wheel 使用 cp37-abi3，仍按 OS、CPU 架构、glibc 和 native runtime 分别构建。
- 以 feature-dev@dc00211fe0cf95bc8c3412c883311fe86f8d8357 作为行为基线；执行前只允许同步已确认的 feature-dev 提交，不覆盖主工作树改动。
- Python/PyMuPDF 独占 Page、drawing、words、rawdict、native span 和渲染；Rust 不接收或持有 fitz.Page，不回调 Python。
- 所有纯算法按函数粒度执行 RED → GREEN → differential → benchmark → 路由验收；组合入口测试不能替代叶子函数合同测试。
- 顺序、文本、bbox、source、confidence、行列索引、rowspan、colspan、空槽位、异常和空结果按 Python 基线精确保持；不得用宽泛浮点容差隐藏差异。
- 中文/混合无线只消费 native span 派生 DTO；结构恢复不得回读 page.get_text("words")，不得回退 extract_zebra() 或 legacy words 重建。
- 每次 PyO3 调用按页或表格区域批量传输；Rust 无 Python 回调的长计算阶段释放 GIL。
- Benchmark 是强制验收项：没有前后数据的模块不能宣称完成或切换 Rust primary。
- 本机 PDF、页面 PNG、benchmark 原始明细和构建目录不提交 Git；报告只提交小型 summary、差异结论和可复现命令。
- 每个任务完成后运行 git diff --check，并提交一个只包含本任务文件的 commit。

## 执行前强制门禁

以下门禁在 Sprint 000 完成前必须全部满足；任何一项未满足都不得开始 Rust 算法迁移：

- **唯一基线：** 每个 Sprint 开始前重新读取 `feature-dev` 的完整 SHA。若 `feature-dev` 已前进，先在本 worktree 创建同步提交并重新生成 baseline manifest；不得在主工作树执行 merge/rebase，不得覆盖其他 worktree 的改动。
- **模式合同：** 生产路由和 benchmark runner 的 `--mode` 只接受 `python`、`shadow`、`rust`，不定义也不使用 `both`。需要比较时执行两次明确命令，并把两次输出交给 comparator。
- **真实迁移前基线：** 必须在 `feature-dev` 基线状态运行 Python，保存输入 SHA256、环境、页数、输出 manifest、阶段计时、P50/P95/P99、峰值 RSS 和命令；迁移分支上的 `python` 只是兼容回归，不得替代该基线。
- **DTO 合同：** 所有跨 FFI 类型必须先进入 `docs/superpowers/rust-migration/dto-schema.md`，写明字段、单位、坐标系、顺序、空值、NaN/Inf、错误语义和 schema version；未登记 DTO 不得进入 Rust 接口。
- **差异与回退：** `python` 永远只跑 Python；`shadow` 执行 Python 与 Rust 但永远返回 Python，并记录差异；`rust` 成功时返回 Rust，Rust 异常时只允许带 `rust_fallback` 诊断后回退 Python，输出差异不能静默回退，必须在 shadow/验收阶段阻断。
- **性能门槛：** 只有输出 equality、完整回归和 benchmark 都通过的模块才允许切换 Rust primary；纯算法 P95 必须相对 feature-dev Python 基线有可复现提升，端到端 P95 不得回退超过 5%，否则保留 Rust 实现但不切 primary，并记录原因。
- **独立评审：** 每个 Sprint 都必须生成 review package，由独立的 `gpt-5.6-luna` reviewer 在只读 worktree 执行；结果只能是 `pass`、`repair` 或 `blocked`。`repair` 的 P1/P2 修复后必须重新评审，未 `pass` 不得进入下一 Sprint。
- **端到端证据：** fix PDF 的直接 parser 入口使用 `test_single.py`/`PDFParser`，必须同时保存 JSON、PNG、manifest 和差异报告；若仓库已有服务端端测入口，另执行同一输入并保存请求/响应摘要，不以单元测试代替端测。

### 路由诊断合同

路由只允许以下状态转换：

~~~text
python  -> python_result
shadow  -> compare(python_result, rust_result) -> python_result
rust    -> rust_result
rust exception -> python fallback -> python_result + rust_fallback diagnostic
shadow difference -> python_result + rust_output_mismatch diagnostic (阻断 primary)
~~~

`rust_fallback` 和 `rust_output_mismatch` 都必须实例化为上面定义的 `DiagnosticDto`：前者填 `{status="rust_fallback", path, error_type, message, traceback_id?}`，后者填 `{status="rust_output_mismatch", path, field, python_value, rust_value, classification}`。比较器内部可以使用 `difference_kind`（`missing_key`、`extra_key`、`list_length`、`text`、`bbox`、`span`、`order`、`value`）作为内部分类；`missing_key`、`extra_key`、`list_length`、`text`、`bbox`、`span`、`order`、`value` 统一映射为 `classification="defect"`，只有显式记录的非迁移路径才映射为 `unsupported`，不得把 `difference_kind` 冒充 `classification`。`field` 的确定规则是：路径最后一个对象键作为字段名；路径以列表下标结束时使用 `__list_length__`；根级差异使用 `__root__`。两者都必须进入结构化 `Vec<DiagnosticDto>` 和 Sprint report。`rust` primary 不自动执行 Python 以发现差异；因此运行期没有“静默 mismatch fallback”，不一致只能由 shadow/differential 阶段发现并阻断切换。若产品要求把 mismatch 变成线上异常或降级，必须先由用户确认，不得在实现中自行选择。

## 文件地图

已有并继续使用：

- rust/lib.rs：PyO3 模块入口和兼容导出。
- src/hexai_pdf_parser/rust_adapter.py：Python DTO 转换、模式选择和结果适配。
- src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py：有线 PDF drawing 提取与 facade。
- src/hexai_pdf_parser/tables/extractors/english_table_extractor.py：英文 drawing/words 提取与 facade。
- src/hexai_pdf_parser/tables/wireless_table_recovery.py：native span 采集与共享恢复 facade。
- src/hexai_pdf_parser/tables/wireless_structure/：中文/混合结构规则的 Python 行为 oracle。
- src/hexai_pdf_parser/core/pipeline.py：现有阶段计时和 timings.json 输出。

计划新增：

- rust/types.rs、rust/geometry.rs、rust/wired.rs、rust/native_span.rs、rust/wireless_structure.rs、rust/english_wireless.rs、rust/table_normalization.rs。
- scripts/benchmark_rust_migration.py、scripts/compare_rust_migration.py（当前仓库只有最小 Python-only harness；完整三路 runner/comparator 是 Sprint 001 的交付物）。
- scripts/export_rust_migration_e2e.py：按页导出 JSON、PNG 和 manifest，供结构/视觉 comparator 使用。
- src/hexai_pdf_parser/debug/rust_migration_benchmark.py。
- scripts/audit_rust_migration_capability.py：静态枚举目标目录中的函数、方法、私有 helper 和嵌套函数，输出逐符号迁移矩阵。
- tests/test_rust_migration_benchmark.py、tests/test_pdf_fast_dto.py、tests/test_pdf_fast_wired.py、tests/test_pdf_fast_wireless.py、tests/test_pdf_fast_wireless_structure.py、tests/test_pdf_fast_english_wireless.py、tests/test_pdf_fast_table_normalization.py。
- tests/fixtures/rust_migration/ 下的 JSON 输入向量。
- docs/superpowers/rust-migration/sprints/ 下的 Sprint handoff 和 evaluations/ 下的独立评估记录。
- docs/superpowers/rust-migration/dto-schema.md：所有 FFI DTO 的版本化字段合同。
- docs/superpowers/rust-migration/review-template.md：每个 Sprint 复用的独立评审输入、输出和 repair 规则。

计划修改：

- Cargo.toml、rust/lib.rs、pyproject.toml、build.sh：扩展模块、ABI 和发布配置。
- rust_adapter.py、三类 extractor、wireless_table_recovery.py、wireless_structure/*.py：只替换已验收的纯计算调用点。
- src/hexai_pdf_parser/debug/benchmark_utils.py：保留 legacy `summarize_timings` 的五键结果，并提供供迁移 benchmark 使用的显式 `summarize_timings_with_percentiles`（含 p50/p95/p99）。
- tests/、changes.md、迁移记录和 .gitignore：记录每个 Sprint 的结果和输出约束。
- docs/superpowers/rust-migration/decisions.md、migration-plan.md、baseline.md：同步 benchmark、Sprint 状态和唯一基线；旧计划必须明确标记为 superseded。

## Sprint 000：确认基线、分支和迁移矩阵

Files:

- Read: docs/superpowers/specs/2026-09-16-rust-extreme-migration-design.md
- Read: docs/superpowers/rust-migration/baseline.md
- Read: docs/superpowers/rust-migration/capability-matrix.md
- Read: docs/superpowers/rust-migration/decisions.md
- Read: docs/superpowers/rust-migration/migration-plan.md
- Modify: docs/superpowers/rust-migration/baseline.md
- Modify: docs/superpowers/rust-migration/capability-matrix.md
- Modify: docs/superpowers/rust-migration/decisions.md
- Modify: docs/superpowers/rust-migration/migration-plan.md
- Create: scripts/audit_rust_migration_capability.py
- Create: docs/superpowers/rust-migration/dto-schema.md
- Create: docs/superpowers/rust-migration/review-template.md
- Create: docs/superpowers/rust-migration/sprints/sprint-000-benchmark-baseline.md

Interfaces:

- Consumes: 当前分支 codex/pdf-fast-rust-migration、基线 commit dc00211、已有 Sprint 001 benchmark harness。
- Produces: 每个 Python 纯函数的 exact reproduction、semantic reproduction 或 redesign 分类；每个函数对应的输入 DTO、输出 DTO、测试文件和 benchmark suite。

- [ ] Step 1: 验证隔离工作树和基线 commit。

~~~powershell
git status --short --branch
git branch --show-current
git merge-base HEAD feature-dev
git show -s --format=%H feature-dev
git show -s --format=%H HEAD
~~~

Expected: 当前分支为 codex/pdf-fast-rust-migration；feature-dev 为 dc00211fe0cf95bc8c3412c883311fe86f8d8357；主工作树未提交改动不出现在本 worktree。

先运行 `git rev-parse --git-common-dir`，将其解析为仓库 common dir 的绝对路径 `commonRoot`，再将 baseline worktree 固定为 `commonRoot/../.worktrees/feature-dev-baseline` 的规范化绝对路径；不得相对当前迁移 worktree 拼接 `.worktrees`。按以下命令解析并验证路径：

~~~powershell
$commonRoot = (Resolve-Path (git rev-parse --git-common-dir)).Path
$baselinePath = [System.IO.Path]::GetFullPath((Join-Path $commonRoot '..\.worktrees\feature-dev-baseline'))
if (-not (Test-Path -LiteralPath $baselinePath)) { git worktree add --detach $baselinePath feature-dev }
if ((git -C $baselinePath rev-parse HEAD) -ne (git rev-parse feature-dev)) { throw "feature-dev baseline worktree is stale: $baselinePath" }
~~~

同步 feature-dev 时只在迁移 worktree 中执行 `git merge --no-ff feature-dev`，冲突时保留迁移 worktree 未提交内容并暂停给用户处理；不在主工作树执行同步，不删除其他 agent worktree。

- [ ] Step 2: 先完成文档决策收敛，不保留相互矛盾的旧结论。

将 `decisions.md` 中早期关于暂不做 benchmark 和暂不设时间门槛的结论改为：benchmark 是每个迁移单元的强制证据；只有输出一致、P95 满足门槛且无回归时才允许 Rust primary。将 `migration-plan.md` 标记为 `superseded by docs/superpowers/plans/2026-09-16-rust-extreme-migration.md`，保留历史内容但禁止作为执行入口。`baseline.md` 写入唯一 feature-dev SHA、输入 hash、环境和 baseline artifact 路径。

- [ ] Step 3: 生成完整 capability audit，不只盘点公开函数。

~~~powershell
python scripts/audit_rust_migration_capability.py `
  --root src/hexai_pdf_parser/tables `
  --root src/hexai_pdf_parser/tables/normalizers `
  --output docs/superpowers/rust-migration/capability-matrix.md
~~~

脚本必须枚举公开函数、方法、私有 helper、嵌套函数和 lambda 的调用位置；每行写入符号、caller、依赖边界、输入字段、输出字段、exact/semantic/redesign 分类、Rust 目标、测试、benchmark、状态和 Python 保留理由。每个 AST function/lambda 节点必须在矩阵中出现；不参与表格逻辑的节点标记 `out_of_scope` 并写理由。只有第三方对象、公开 Python object 装配、服务状态或未批准业务策略可以保留 Python；“暂未检查”不允许作为状态。

- [ ] Step 4: 逐文件人工核对 capability matrix 和保留理由。

逐一盘点以下目录中被调用的纯函数：

~~~text
src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py
src/hexai_pdf_parser/tables/table_extractor.py
src/hexai_pdf_parser/tables/wireless_table_recovery.py
src/hexai_pdf_parser/tables/wireless_structure/*.py
src/hexai_pdf_parser/tables/extractors/english_table_extractor.py
src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py
src/hexai_pdf_parser/tables/normalizers/financial_header_handler.py
~~~

每行必须包含 Python 符号、调用者、输入字段、输出字段、分类、Rust 文件、测试文件、benchmark suite、当前状态和 Python 保留理由（若保留）。

- [ ] Step 5: 建立 Sprint 000 记录并确认旧 Sprint 001 结论。

记录已有 benchmark harness 已实现但生产路由仍为 Python；记录任何早期 `unknown`、旧 benchmark 或旧迁移结论只是历史证据，后续所有性能结论必须来自包含 feature-dev baseline 的新 runner。

- [ ] Step 6: 建立 DTO、评审和路由合同。

`dto-schema.md` 必须登记所有 Rust API 签名中的类型，包括但不限于 `PageDto`、`Rect4`、`Line4`、`LineDto`、`DrawingDto`、`WordDto`、`CharacterDto`、`NativeSpanDto`、`TextRunDto`、`AtomDto`、`OrderedRectDto`、`ColumnBandDto`、`RegionDto`、`WiredRegionInput/Output`、`RowClusterDto`、`ColumnClusterDto`、`OutputOrderMode`、`TableCandidateDto`、`GridDto`、`LogicalGridDto`、`PhysicalCell`、`CellDto`、`NativeRecoveryInput/Output`、`StructureConfig`、`NativeRegionInput/Output`、`WirelessRecoveryInput/Output`、`BackgroundDto`、`BackgroundGroupDto`、`RowBandDto`、`ZebraInput`、`EnglishGridInput`、`GeneralWirelessInput`、`LegacyAlignmentInput`、`HeaderGridInput/Output`、`HeaderTokenInput/Output`、`DiagnosticValueDto` 和 `DiagnosticDto`。每个 DTO 写明 `schema_version=1`、PDF point 单位、左上角坐标、旋转归一化规则、稳定排序键、可空字段、禁止 NaN/Inf、错误映射和 ownership；`review-template.md` 写明 reviewer 输入 commit/package、命令、结果分类和 P1/P2 repair 规则。任何计划函数签名引用未登记 DTO 时，评审必须判 `FAIL`。

为避免只列名称而没有可实现合同，`dto-schema.md` 使用以下字段分组；未列出的字段不得通过“动态字典”偷偷跨 FFI：

~~~text
PageDto = {schema_version=1, width, height, rotation}
Rect4 = {schema_version=1, x0, y0, x1, y1}; Line4 = {schema_version=1, x0, y0, x1, y1}
LineDto = {schema_version=1, rect, width?, color?, source_order}
DrawingDto = {schema_version=1, kind, lines, rect, fill?, stroke?, clip?, source_order}
OrderedRectDto = {schema_version=1, id, rect, order}; WordDto = {schema_version=1, text, rect, order, block?, line?}
CharacterDto = {schema_version=1, text, rect, order}
NativeSpanDto = {schema_version=1, text, rect, font?, size?, flags?, order, characters, source_position, block, line}
TextRunDto = {schema_version=1, text, rect, span_refs, source_start, source_end, order}
AtomDto = {schema_version=1, text, rect, run_refs, row_hint?, col_hint?, order}
ColumnBandDto = {schema_version=1, x0, x1, source_atoms, order}
RegionDto = {schema_version=1, rect, source_order, allowed}
GridDto = {schema_version=1, rows, cols, row_edges, col_edges, occupancy}
PhysicalCell = {schema_version=1, text, rect, row, col, source_refs}; CellDto = {schema_version=1, text, row, col, rect, rowspan, colspan, source?}
LogicalGridDto = {schema_version=1, grid, cells, empty_slots}; TableCandidateDto = {schema_version=1, rect, source, confidence?, rows, cols, cells}
WiredRegionInput = {schema_version=1, page, h_lines, v_lines, words, tolerance}
WiredRegionOutput = {schema_version=1, regions, grids, cells, diagnostics}
RowClusterDto = {schema_version=1, row_index, y0, y1, item_indices}; ColumnClusterDto = {schema_version=1, col_index, x0, x1, item_indices}
OutputOrderMode = {schema_version=1, value: stable string label from Python oracle}
StructureConfig = {schema_version=1, line_tolerance, row_tolerance, column_tolerance, span_tolerance, numeric_tolerance}
NativeRecoveryInput = {schema_version=1, page, spans, region, config}; NativeRecoveryOutput = {schema_version=1, candidates, atoms, diagnostics}
NativeRegionInput = {schema_version=1, region, atoms, bands, config}; NativeRegionOutput = {schema_version=1, grid, cells, diagnostics}
WirelessRecoveryInput = {schema_version=1, page, spans, regions, config}; WirelessRecoveryOutput = {schema_version=1, candidates, diagnostics}
BackgroundDto = {schema_version=1, rect, color?, opacity?, source_order}; BackgroundGroupDto = {schema_version=1, rect, row_index, source_indices}
RowBandDto = {schema_version=1, rect, row_index, source_backgrounds, words, cells}; ZebraInput = {schema_version=1, page, backgrounds, words, region, config}
EnglishGridInput = {schema_version=1, region, words, backgrounds, config}; GeneralWirelessInput = {schema_version=1, region, atoms, bands, config}
LegacyAlignmentInput = {schema_version=1, region, words, config}; HeaderGridInput = {schema_version=1, grid, config}; HeaderGridOutput = {schema_version=1, grid, cells, diagnostics}
HeaderTokenInput = {schema_version=1, cells, config}; HeaderTokenOutput = {schema_version=1, cells, diagnostics}
~~~

`DiagnosticValueDto = {schema_version=1, kind: "null"|"bool"|"number"|"string"|"json", text: String}`；`DiagnosticDto = {schema_version=1, status, path, error_type?, message?, traceback_id?, field?, python_value?, rust_value?, classification?}`，其中 `python_value`/`rust_value` 为 `DiagnosticValueDto`，所有 DTO 的 `diagnostics` 字段均为 `Vec<DiagnosticDto>`，不得使用未约定的动态字典。`status` 只允许 `rust_fallback`、`rust_output_mismatch`、`invalid_input`、`unsupported`、`info`；`classification` 只允许 `accepted`、`adaptation`、`defect`、`unsupported`。除标记 `?` 的字段外，所有字段均为必填；所有省略字段以 `null` 显式编码，不由 Rust 猜测默认值；所有 `config` 数值也必须由 Python adapter 显式传入，Rust 不提供隐式默认值。所有集合的稳定排序键、`source_refs` 的零基索引语义、`rotation ∈ {0,90,180,270}`、坐标单位和每个 `config` 的实际值必须在 Sprint 000 的 schema review 中逐字段列出；其中当前 oracle 已知默认值记录为 wired `line_tolerance=2.3`、`merge_group_tol=0.3`，wireless extractor `line_tolerance=2.0`、`color_tolerance=0.05`、`row_merge_tolerance=2.0`，其余自适应 tolerance 必须作为 fixture 中的显式派生值保存。若调用点需要额外字段，先补 schema 和 fixture，再写 Rust 签名。`OutputOrderMode.value` 只允许 oracle 已出现的字符串，未知值原样保留并进入 differential report。

- [ ] Step 7: 准备 benchmark baseline 的固定输入和环境清单（此时不声称已有分段性能基线）。

记录固定 PDF 的 `input_sha256`、页集、模型 hash、dpi、操作系统和 CPU 信息；这些输入在 Sprint 001 生成完整 baseline artifact。真实 benchmark 只能在 runner 支持分段计时、来源 checkout 和 OS peak RSS 后采集。

统一 runner 命令合同：`scripts/benchmark_rust_migration.py --mode {python|shadow|rust} --suite <suite> --pdf <pdf> --pages <all|comma-separated-0-based-pages> --warmups <n> --runs <n> --source-root <checkout> --baseline-id <id> --output-dir <directory>`；fixture suite 将 `--pdf` 替换为 `--fixture <json>`。统一 benchmark comparator 合同：`scripts/compare_rust_migration.py --baseline <feature-dev/<suite>-python.json> --python <migration/<suite>-python.json> --rust <migration/<suite>-rust.json> [--shadow <migration/<suite>-shadow.json>] --report <report.md>`。页面 comparator 合同：`scripts/compare_rust_migration.py --manifests <python>/manifest.json <rust>/manifest.json [--shadow <shadow>/manifest.json] --report <report.md>`。所有 runner 输出文件固定为 `<suite>-<mode>.json`；shadow 只做行为差异证据，不计入 speedup 或性能分母。

- [ ] Step 8: 验证文档一致性并提交。

~~~powershell
git diff --check
git add -- docs/superpowers/rust-migration/baseline.md docs/superpowers/rust-migration/capability-matrix.md docs/superpowers/rust-migration/decisions.md docs/superpowers/rust-migration/migration-plan.md docs/superpowers/rust-migration/dto-schema.md docs/superpowers/rust-migration/review-template.md docs/superpowers/rust-migration/sprints/sprint-000-benchmark-baseline.md scripts/audit_rust_migration_capability.py
git commit -m "docs: define Rust migration benchmark baseline and gates"
~~~

Expected: 文档 commit 成功，未加入 PDF、PNG、output/ 或 target/。

## 每个 Sprint 的固定收尾和独立评审协议

以下步骤是 Sprint 001–012 的组成部分，不得因为某个 Sprint 的代码量小而省略：

Sprint 000 使用相同协议，但 review package 由 capability audit、文档一致性 diff、feature-dev SHA、固定输入 hash 和 DTO schema 构成；Evaluator 核对 AST audit 覆盖率并验证 baseline 输入可读取，不声称 Sprint 000 已有性能测量。Sprint 001 完成 runner 后生成真正的 baseline artifact，并由 Sprint 001 Evaluator 复现测量命令。Sprint 000 `PASS` 后进入 Sprint 001。

- [ ] Generator 只修改该 Sprint `Files` 中的文件，先运行 RED，再最小实现，再运行 focused tests、differential tests、benchmark 和 `git diff --check`。每个实现 commit 只暂存该 Sprint 的明确文件；对应的 `evaluations/sprint-NNN.md` 在独立 Evaluator 完成后作为单独的评审记录提交，不借助宽泛目录暂存隐藏越界文件。
- [ ] 生成 `docs/superpowers/rust-migration/sprints/sprint-NNN.md`，记录目标、owned files、输入 fixture、命令、实际输出、兼容差异、benchmark segments、未解决问题和 commit SHA。
- [ ] 生成 review package：目标 commit 的 patch、测试日志、适用的 feature-dev baseline JSON、migration Python JSON、Rust JSON，以及在该 Sprint 修改/启用路由时的 shadow JSON、comparator 报告、页面 JSON/PNG（只保存 manifest 和报告索引，不提交大文件）。Sprint 001 生成并固定 feature-dev baseline；Sprint 002–010 的 function/fixture benchmark 必须使用同一 suite/fixture 在该 baseline checkout 生成对应 baseline JSON，或在 review package 中链接已存在的同 hash artifact；未改路由的纯 kernel Sprint 不重复生成 shadow。所有 benchmark JSON 统一命名为 `<suite>-<mode>.json`，目录名只用于分组，comparator 参数始终传入这些 JSON 文件的精确路径。
- [ ] 独立 `gpt-5.6-luna` Evaluator 在只读 worktree 执行 `cargo test`、focused pytest、fixture differential、结构/视觉 manifest 检查和 benchmark sanity check；Evaluator 不得修改代码或放宽断言。
- [ ] Evaluator 在 `docs/superpowers/rust-migration/evaluations/sprint-NNN.md` 按每个 acceptance criterion 写 `PASS`/`FAIL`、复现命令、差异分类（accepted / adaptation / defect / unsupported）和下一步。
- [ ] `PASS` 才能继续；`FAIL` 中的 P1/P2 必须由新的 Generator repair loop 修复并重新评审；P0、产品语义决策、输出 schema、误差容忍度、依赖/平台变化必须暂停并请求用户确认。

## Sprint 001：建立可复现 Benchmark 基础设施

Files:

- Modify: scripts/benchmark_rust_migration.py (扩展已有 Python-only runner)
- Modify: scripts/compare_rust_migration.py (扩展为三路/可选 shadow comparator)
- Modify: src/hexai_pdf_parser/debug/rust_migration_benchmark.py
- Modify: tests/test_rust_migration_benchmark.py
- Modify: src/hexai_pdf_parser/debug/benchmark_utils.py
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: .gitignore
- Create: docs/superpowers/rust-migration/sprints/sprint-001-benchmark-baseline.md

Interfaces:

~~~python
# src/hexai_pdf_parser/debug/rust_migration_benchmark.py
def summarize_timings(values: Sequence[float]) -> Dict[str, float]: ...
def summarize_timings_with_percentiles(values: Sequence[float]) -> Dict[str, float]: ...
def canonicalize_tables(tables: Sequence[object]) -> List[Dict[str, object]]: ...
def compare_canonical_tables(python_tables, rust_tables) -> Dict[str, object]: ...
def write_benchmark_run(path: Path, payload: Mapping[str, object]) -> None: ...

# scripts/benchmark_rust_migration.py
def run_suite(mode: str, suite: str, input_path: str, pages: Sequence[int],
              warmups: int, runs: int, output_dir: str,
              source_root: Optional[str] = None,
              baseline_id: Optional[str] = None) -> Dict[str, object]: ...

# scripts/compare_rust_migration.py
def compare_runs(baseline_run: str, migration_python_run: str,
                 rust_run: str, shadow_run: Optional[str] = None) -> Dict[str, object]: ...
def compare_manifests(migration_python_manifest: str, rust_manifest: str,
                      shadow_manifest: Optional[str] = None) -> Dict[str, object]: ...
~~~

`hexai_pdf_parser.benchmark_utils.summarize_timings` 是 legacy public API，结果严格保持 `count`、`total`、`mean`、`min`、`max` 五个键；迁移 benchmark 必须调用显式的 `summarize_timings_with_percentiles`，不得通过扩展 legacy 返回值来获取百分位统计。

Modes are exactly python、shadow、rust；unknown modes raise ValueError；default mode remains python。`both` 永远不是合法 mode；比较由两个独立 runner invocation 和 `compare_runs()` 完成。

- [x] Step 1: Write failing percentile and canonicalization tests。

测试空 timings、单值、奇偶数量、稳定表格顺序、稳定 Cell 顺序、float 序列化、empty slots 和 deliberate missing-key、extra-key、list-length、text、bbox、span、order、value differences。断言每个 difference 都包含按路径规则提取的 `field`、`python_value`、`rust_value`、`difference_kind` 和映射后的 `classification`；所有已知输出差异的 classification 必须为 `defect`。

- [x] Step 2: Run the new tests and confirm RED。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_benchmark.py
~~~

Expected: collection 或 assertion failure 明确指出 benchmark functions 尚未实现，而不是环境失败。

- [x] Step 3: Implement deterministic statistics and output manifests。

实现 percentile interpolation、Table/Cell canonicalize 和 sorted-key JSON。canonicalizer 必须保留 Python 输出的 Table 顺序和每个 Table 内原始 Cell 顺序；不得按 `(row, col, text)` 重排来掩盖顺序差异。每次运行至少写入以下字段；`segment_samples` 保存每次 measured run 的原始样本，`segments` 对每个阶段分别计算 `count/p50/p95/p99`，不得只保存一个平均值：

~~~json
{
  "commit": "...",
  "mode": "python",
  "suite": "...",
  "input_sha256": "...",
  "warmups": 3,
  "runs": 10,
  "timings": {"count": 10, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0},
  "segment_samples": {"extract": [0.0], "dto": [0.0], "ffi": [0.0], "algorithm": [0.0], "adapt": [0.0], "total": [0.0]},
  "segments": {"extract": {"count": 1, "p50": 0.0, "p95": 0.0, "p99": 0.0}, "dto": {"count": 1, "p50": 0.0, "p95": 0.0, "p99": 0.0}, "ffi": {"count": 1, "p50": 0.0, "p95": 0.0, "p99": 0.0}, "algorithm": {"count": 1, "p50": 0.0, "p95": 0.0, "p99": 0.0}, "adapt": {"count": 1, "p50": 0.0, "p95": 0.0, "p99": 0.0}, "total": {"count": 1, "p50": 0.0, "p95": 0.0, "p99": 0.0}},
  "memory": {"peak_rss_samples_bytes": [0], "peak_rss_p50_bytes": 0, "peak_rss_p95_bytes": 0},
  "environment": {"python": "", "rust_extension": "", "os": "", "cpu": "", "threads": 1, "dpi": 72, "cold_start": false},
  "diagnostics": [],
  "output_manifest": {"pages": 0, "tables": 0, "cells": 0, "failures": 0}
}
~~~

- [x] Step 4: Add runner CLI and mode routing without changing the default。

Runner 接受 `--mode`、`--suite`、`--pdf` 或 `--fixture`（二选一）、`--pages`（fixture 可不传）、`--warmups`、`--runs`、`--output-dir`、`--source-root` 和可选 `--baseline-id`。它通过隔离子进程从 `source-root/src` 导入目标 Python 代码，工具代码与目标源代码分别记录 SHA；`--mode python` 下绝不导入或调用 Rust binding。它记录命令、环境、PDF/fixture hash、模型 hash（可用时）和现有 pipeline stage timings，并在每次 measured run 记录以下互不重叠的阶段样本：`extract` 从第一次 PyMuPDF 页面/ drawing/word/span 读取前到 Python primitive extraction 完成；`dto` 从 primitive 数据转换成 FFI 输入前到完成；`ffi` 为 PyO3 调用 wall time 减去 Rust 内部 `algorithm` timer（含入参解码、跨边界传递和返回值编码）；`algorithm` 在 Python baseline 中是被迁移纯函数集合的包围计时，在 Rust 中只计 owned DTO 内核；`adapt` 为 Rust 返回后至 Python Table/Cell/output DTO 完成；`total` 为 `PDFParser.parse()` 的完整 wall time（含打开文件、pipeline 与序列化，不含进程启动）。Python 模式的 `ffi` 固定为 0；Rust 模式的 `algorithm`、`ffi` 和 `adapt` 由同一调用边界产生。`memory.peak_rss_samples_bytes` 以独立子进程的 OS high-water mark 采集（Windows `PeakWorkingSetSize`，Linux `ru_maxrss` 归一化为 bytes），并计算 `memory.peak_rss_p50_bytes` 与 `memory.peak_rss_p95_bytes`。每个阶段都保存原始样本并分别产生 `count/p50/p95/p99`。migration Python、shadow 和 Rust 必须使用相同 source commit、PDF hash、pages、机器、DPI、模型和 run 参数。Rust algorithm speedup 使用 `feature-dev baseline segments.algorithm.p95 / rust segments.algorithm.p95`；端到端 speedup 使用 `feature-dev baseline segments.total.p95 / rust segments.total.p95`；若 Python baseline 的迁移纯函数包围计时不可插入，Sprint 001 直接判定为失败，不得用 total 代替 algorithm。PDF_RUST_MODE 只由迁移 facade 读取，默认 python。

**采样和算法计时的优先合同（覆盖本段中与之不一致的简写）：** 每个 `runs` repetition 都使用全新 worker process，worker 内先执行指定 warmups，然后只记录一个 measured run；cold 的 warmups 固定为 0。Python baseline `algorithm` 必须用 capability matrix 中的迁移函数集合做 exclusive-call 计时（函数总时长扣除被调用子函数时长），Rust `algorithm` 使用同一函数边界内部的内核计时；若任何目标函数无法采样，Sprint 001 baseline 不得验收通过，不能用 `unavailable` 代替。`segment_samples` 保存每阶段每次运行值，`segments` 为每阶段分别计算 `count/p50/p95/p99`。memory 保存 `peak_rss_samples_bytes` 和 `peak_rss_p50_bytes/peak_rss_p95_bytes`。基线 function suites 与 full-PDF suite 都必须生成 `segments.algorithm.p95` 和 `segments.total.p95`，比较公式在两端完全同名。

`--pages` 的解析合同是：`all` 展开为输入 PDF 中所有 0-based 页索引；显式列表按输入顺序保留。Runner 产物固定写入 `<output-dir>/<suite>-<mode>.json`，同一个 suite/mode 的重复运行须先使用独立目录，禁止覆盖原始测量。

- [x] Step 5: Verify RED → GREEN and capture the feature-dev pre-migration baseline。

必须先完成 runner 的 `--fixture`、`--source-root`、`--baseline-id`、`--pages all`、独立 worker、分段计时、peak RSS 和 mode routing，以及 comparator 的 `--baseline/--python/--rust/--shadow/--report` 和 `--manifests` CLI；这些合同对应的测试全部 GREEN 后，才允许执行下面的 feature-dev baseline 命令。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_benchmark.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
python scripts/benchmark_rust_migration.py --mode python --suite fixture --pdf tests/fixtures/page_000_vector.pdf --pages 0 --warmups 1 --runs 2 --output-dir output/rust_migration_benchmark/sprint-001
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite full-pdf --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages all --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/baselines/feature-dev-dc00211
git diff --check
~~~

Expected: source commit 在 baseline JSON 中是 `dc00211fe0cf95bc8c3412c883311fe86f8d8357`；输入 hash、1023 页列表、分段原始样本、P50/P95/P99、peak RSS、输出结构 manifest 均保存。baseline 原始 JSON 留在 ignored `output/`；只把小型摘要、命令、环境和 SHA256 写入 Sprint record。

- [x] Step 6: Commit Sprint 001 implementation and report。

~~~powershell
git diff --check
git add -- scripts/benchmark_rust_migration.py scripts/compare_rust_migration.py src/hexai_pdf_parser/debug/benchmark_utils.py src/hexai_pdf_parser/debug/rust_migration_benchmark.py src/hexai_pdf_parser/rust_adapter.py tests/test_rust_migration_benchmark.py .gitignore docs/superpowers/rust-migration/sprints/sprint-001-benchmark-baseline.md
git commit -m "feat: add Rust migration benchmark harness"
~~~

Expected: tests pass；summary JSON 写入；output/ 保持 ignored；python 模式不调用 Rust 路径。

- [x] Step 7: 生成 Sprint 001 review package 并通过独立评审。

将 commit SHA、测试输出、baseline JSON 小型摘要、source/input hash、sample benchmark JSON、`git diff --check` 和 compatibility notes 写入 `docs/superpowers/rust-migration/evaluations/sprint-001.md`，按 `review-template.md` 交给只读的 `gpt-5.6-luna` reviewer。reviewer 必须确认 legacy 五键 API、显式 percentile API、cwd-independent provenance、默认 Python route、true feature-dev baseline 复现和 no-production-route-change；输出 `pass`/`repair`/`blocked`。若为 `repair`，只修复报告或实现中明确的问题并重新评审，未 `pass` 不得进入 Sprint 002。

## Sprint 002：扩展统一 DTO 和 PyO3 批量边界

Files:

- Create: rust/types.rs
- Modify: rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Create: tests/fixtures/rust_migration/dto/basic.json
- Create: tests/test_pdf_fast_dto.py
- Create: docs/superpowers/rust-migration/sprints/sprint-002-rust-core.md

Interfaces:

~~~rust
pub const DTO_SCHEMA_VERSION: u16 = 1;
pub struct PageDto { pub schema_version: u16, pub width: f64, pub height: f64, pub rotation: i32 }
pub struct Rect4 { pub schema_version: u16, pub x0: f64, pub y0: f64, pub x1: f64, pub y1: f64 }
pub struct Line4 { pub schema_version: u16, pub x0: f64, pub y0: f64, pub x1: f64, pub y1: f64 }
pub struct LineDto { pub schema_version: u16, pub rect: Line4, pub width: Option<f64>, pub color: Option<[f64; 3]>, pub source_order: usize }
pub struct DrawingDto { pub schema_version: u16, pub kind: String, pub lines: Vec<LineDto>, pub rect: Rect4, pub fill: Option<[f64; 3]>, pub stroke: Option<[f64; 3]>, pub clip: Option<Rect4>, pub source_order: usize }
pub struct WordDto { pub schema_version: u16, pub text: String, pub rect: Rect4, pub order: usize, pub block: Option<usize>, pub line: Option<usize> }
pub struct CharacterDto { pub schema_version: u16, pub text: String, pub rect: Rect4, pub order: usize }
pub struct NativeSpanDto { pub schema_version: u16, pub text: String, pub rect: Rect4, pub font: Option<String>, pub size: Option<f64>, pub flags: Option<u32>, pub order: usize, pub characters: Vec<CharacterDto>, pub source_position: usize, pub block: usize, pub line: usize }
pub struct TextRunDto { pub schema_version: u16, pub text: String, pub rect: Rect4, pub span_refs: Vec<usize>, pub source_start: usize, pub source_end: usize, pub order: usize }
pub struct AtomDto { pub schema_version: u16, pub text: String, pub rect: Rect4, pub run_refs: Vec<usize>, pub row_hint: Option<usize>, pub col_hint: Option<usize>, pub order: usize }
pub struct ColumnBandDto { pub schema_version: u16, pub x0: f64, pub x1: f64, pub source_atoms: Vec<usize>, pub order: usize }
pub struct RegionDto { pub schema_version: u16, pub rect: Rect4, pub source_order: usize, pub allowed: bool }
pub struct TableCandidateDto { pub schema_version: u16, pub rect: Rect4, pub source: String, pub confidence: Option<f64>, pub rows: usize, pub cols: usize, pub cells: Vec<CellDto> }
pub struct GridDto { pub schema_version: u16, pub rows: usize, pub cols: usize, pub row_edges: Vec<f64>, pub col_edges: Vec<f64>, pub occupancy: Vec<Option<usize>> }
pub struct LogicalGridDto { pub schema_version: u16, pub grid: GridDto, pub cells: Vec<CellDto>, pub empty_slots: usize }
pub struct CellDto { pub schema_version: u16, pub text: String, pub row: usize, pub col: usize, pub rect: Rect4, pub rowspan: usize, pub colspan: usize, pub source: Option<String> }
~~~

- [x] Step 1: 按 `dto-schema.md` 添加 round-trip fixtures 和 failing binding tests。覆盖 normal、empty、非 ASCII、缺失 font/size、字符框、NaN、Inf、负坐标、页面旋转、颜色/clip、source order、空 span、empty slots 和 malformed values；任何 NaN/Inf 必须返回可断言的 `PyValueError`，不得静默转换。
- [x] Step 2: Run DTO tests RED。

~~~powershell
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_dto.py
~~~

Expected: 新 DTO binding tests 失败；已有 Sprint 001 测试仍可区分。
- [x] Step 3: Implement DTO structs and conversion errors。使用显式字段提取和 `PyResult`；禁止 `unwrap`、静默默认值和 Python object 引用。Python 只在页面级一次性构造 DTO，Rust 只消费 owned DTO；所有 field mapping 必须与 `dto-schema.md` 一致。
- [x] Step 4: Release the GIL only around owned Rust computation。Python extraction 和 result adaptation 在 allow_threads 外部执行。
- [x] Step 5: Verify package and commit。

~~~powershell
cargo fmt --check
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_dto.py tests/test_pdf_fast_binding.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite dto --fixture tests/fixtures/rust_migration/dto/basic.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-002/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite dto --fixture tests/fixtures/rust_migration/dto/basic.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-002/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite dto --fixture tests/fixtures/rust_migration/dto/basic.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-002/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite dto --fixture tests/fixtures/rust_migration/dto/basic.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-002/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-002/baseline/dto-python.json --python output/rust_migration_benchmark/sprint-002/python/dto-python.json --rust output/rust_migration_benchmark/sprint-002/rust/dto-rust.json --shadow output/rust_migration_benchmark/sprint-002/shadow/dto-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-002-benchmark.md
git diff --check
git add -- rust/types.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py tests/fixtures/rust_migration/dto/basic.json tests/test_pdf_fast_dto.py docs/superpowers/rust-migration/sprints/sprint-002-rust-core.md
git commit -m "feat: add owned DTO boundary for Rust table kernels"
~~~

## Sprint 003：迁移有线几何和线网区域算法

Files:

- Create: rust/geometry.rs
- Create: rust/wired.rs
- Modify: rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py
- Modify: tests/test_wired_table_extractor.py、tests/test_table_extractor.py
- Create: tests/test_pdf_fast_wired.py
- Create: tests/fixtures/rust_migration/wired/geometry.json
- Create: docs/superpowers/rust-migration/sprints/sprint-003-wired-geometry.md

Interfaces:

~~~rust
pub fn merge_h_lines(lines: Vec<Line4>, merge_group_tol: f64) -> Vec<Line4>;
pub fn merge_v_lines(lines: Vec<Line4>, h_lines: Vec<Line4>, line_tolerance: f64) -> Vec<Line4>;
pub fn merge_region_line_coordinates(lines: Vec<Line4>, horizontal: bool, tolerance: f64) -> Vec<Line4>;
pub fn lines_intersect(a: Line4, b: Line4, tolerance: f64) -> bool;
pub fn find_table_regions(h_lines: Vec<Line4>, v_lines: Vec<Line4>, tolerance: f64) -> Vec<RegionDto>;
pub fn snap_coordinates(values: Vec<f64>, anchors: Vec<f64>, tolerance: f64) -> Vec<f64>;
pub fn snap_grid_coordinates(region: RegionDto, tolerance: f64) -> GridDto;
pub fn complete_partial_outer_boundaries(grid: GridDto, tolerance: f64) -> GridDto;
~~~

- [x] Step 1: 从 Python oracle 复制测试向量。覆盖空输入、equal coordinates、Python rounding/NaN ordering、tolerance 边界、端点接触、断开组件、相邻表格 gap、partial lines 和 open boundaries。
- [x] Step 2: 确认 RED。

~~~powershell
cargo test wired
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py
~~~

- [x] Step 3: 先实现 shared geometry，再实现 wired region。保留 comparison ordering、arithmetic order、tolerance inclusivity 和输出顺序。
- [x] Step 4: 在 wired adapter 增加 shadow 比较；同一 extracted drawing DTO 同时执行 Python 和 Rust，差异必须生成诊断。
- [x] Step 5: 验证和提交。

~~~powershell
cargo fmt --check
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_table_extractor.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite wired-geometry --fixture tests/fixtures/rust_migration/wired/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-003/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-003/baseline/wired-geometry-python.json --python output/rust_migration_benchmark/sprint-003/python/wired-geometry-python.json --rust output/rust_migration_benchmark/sprint-003/rust/wired-geometry-rust.json --shadow output/rust_migration_benchmark/sprint-003/shadow/wired-geometry-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-003-benchmark.md
git diff --check
git add -- rust/geometry.rs rust/wired.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py tests/test_wired_table_extractor.py tests/test_table_extractor.py tests/test_pdf_fast_wired.py tests/fixtures/rust_migration/wired/geometry.json docs/superpowers/rust-migration/sprints/sprint-003-wired-geometry.md
git commit -m "feat: migrate wired table geometry kernels to Rust"
~~~

## Sprint 004：迁移有线 Cell、文字归属和区域装配

Files:

- Modify: rust/wired.rs、rust/types.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py
- Modify: tests/test_pdf_fast_wired.py、tests/test_wired_table_extractor.py、tests/test_table_extractor.py
- Create: tests/fixtures/rust_migration/wired/cells.json
- Create: scripts/export_rust_migration_e2e.py (JSON/PNG/manifest 导出器)
- Modify: changes.md
- Create: docs/superpowers/rust-migration/sprints/sprint-004-wired-cells.md

Interfaces:

~~~rust
pub fn build_cells_for_region(region: RegionDto, grid: GridDto) -> Vec<CellDto>;
pub fn trim_ghost_edge_rows(cells: Vec<CellDto>, lines: Vec<Line4>, tolerance: f64) -> Vec<CellDto>;
pub fn merge_oversegmented_line_columns(cells: Vec<CellDto>, grid: GridDto, tolerance: f64) -> Vec<CellDto>;
pub fn assign_text_to_line_cells(cells: Vec<CellDto>, words: Vec<WordDto>, tolerance: f64) -> Vec<CellDto>;
pub fn extract_wired_region(input: WiredRegionInput) -> WiredRegionOutput;
~~~

- [x] Step 1: 添加 Cell topology failing tests。覆盖 partial line、non-rectangular component、open boundary、physical empty row、ghost row、独立 empty column、colspan recompute、word crossing boundary、Cell order 和 line metadata。
- [x] Step 2: 使用 page spy 验证 words 只在 Python 获取一次，Rust 只收到 WordDto。
- [x] Step 3: 实现 Cell DTO 和 occupancy checks。每个槽位恰好被占用一次；任何 span 调整都重新检查冲突。
- [x] Step 4: 仅在 rust 模式接入 wired extraction；shadow 模式比较完整 region result；保留 drawing、chart mask、clip、type3 glyph 和 Python Table/Cell。
- [x] Step 5: 运行页面对比并提交。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_table_extractor.py tests/test_wireless_extractor_split.py
$env:PDF_RUST_MODE='python'
python scripts/export_rust_migration_e2e.py --mode python --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --dpi 200 --output-dir output/pdf_rust_migration_wired_python_20260916
$env:PDF_RUST_MODE='rust'
python scripts/export_rust_migration_e2e.py --mode rust --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 196,415 --dpi 200 --output-dir output/pdf_rust_migration_wired_rust_20260916
python scripts/compare_rust_migration.py --manifests output/pdf_rust_migration_wired_python_20260916/manifest.json output/pdf_rust_migration_wired_rust_20260916/manifest.json --report docs/superpowers/rust-migration/evaluations/sprint-004-pages.md
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite wired-cells --fixture tests/fixtures/rust_migration/wired/cells.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-004/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-004/baseline/wired-cells-python.json --python output/rust_migration_benchmark/sprint-004/python/wired-cells-python.json --rust output/rust_migration_benchmark/sprint-004/rust/wired-cells-rust.json --shadow output/rust_migration_benchmark/sprint-004/shadow/wired-cells-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-004-benchmark.md
git diff --check
git add -- rust/wired.rs rust/types.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py tests/test_pdf_fast_wired.py tests/test_wired_table_extractor.py tests/test_table_extractor.py tests/fixtures/rust_migration/wired/cells.json scripts/export_rust_migration_e2e.py changes.md docs/superpowers/rust-migration/sprints/sprint-004-wired-cells.md
git commit -m "feat: route wired cell assembly through Rust"
~~~

Expected: comparison equal true；page 415 chart filtering 和 page 196 table boundaries unchanged。

## Sprint 005：抽取共享几何、排序和候选算法

Files:

- Modify: rust/geometry.rs、rust/types.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/table_extractor.py、src/hexai_pdf_parser/tables/wireless_table_recovery.py
- Create: tests/test_pdf_fast_shared_geometry.py
- Create: tests/fixtures/rust_migration/shared/geometry.json
- Create: docs/superpowers/rust-migration/sprints/sprint-005-shared-geometry.md

Interfaces:

~~~rust
pub fn rect_overlap(a: Rect4, b: Rect4, strict: bool) -> bool;
pub fn filter_regions(regions: Vec<Rect4>, excluded: Vec<Rect4>, allowed: Vec<Rect4>) -> Vec<Rect4>;
pub fn cluster_rows(items: Vec<OrderedRectDto>, tolerance: f64) -> Vec<RowClusterDto>;
pub fn cluster_columns(items: Vec<OrderedRectDto>, tolerance: f64) -> Vec<ColumnClusterDto>;
pub fn stable_output_order(tables: Vec<TableCandidateDto>) -> Vec<TableCandidateDto>;
~~~

- [x] Step 1: 为 overlap、region exclusion、row/column clustering 和 output order 增加直接 vectors。
- [x] Step 2: 运行 focused tests RED。
- [x] Step 3: 实现共享 kernels；wired 和 wireless 不再保留重复实现。
- [x] Step 4: 在 TableExtractor 和 wireless candidate boundary 做 shadow compare。
- [x] Step 5: 运行回归、benchmark 和提交。

~~~powershell
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_shared_geometry.py tests/test_table_extractor.py tests/test_wireless_table_recovery.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite shared-geometry --fixture tests/fixtures/rust_migration/shared/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-005/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite shared-geometry --fixture tests/fixtures/rust_migration/shared/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-005/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite shared-geometry --fixture tests/fixtures/rust_migration/shared/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-005/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite shared-geometry --fixture tests/fixtures/rust_migration/shared/geometry.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-005/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-005/baseline/shared-geometry-python.json --python output/rust_migration_benchmark/sprint-005/python/shared-geometry-python.json --rust output/rust_migration_benchmark/sprint-005/rust/shared-geometry-rust.json --shadow output/rust_migration_benchmark/sprint-005/shadow/shared-geometry-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-005-benchmark.md
git diff --check
git add -- rust/geometry.rs rust/types.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/table_extractor.py src/hexai_pdf_parser/tables/wireless_table_recovery.py tests/test_pdf_fast_shared_geometry.py tests/fixtures/rust_migration/shared/geometry.json docs/superpowers/rust-migration/sprints/sprint-005-shared-geometry.md
git commit -m "feat: share Rust geometry kernels across table paths"
~~~

## Sprint 006：迁移 Native Span、Atom 和 Text Run

Files:

- Create: rust/native_span.rs
- Modify: rust/types.rs、rust/lib.rs、src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/wireless_table_recovery.py
- Modify: src/hexai_pdf_parser/tables/wireless_structure/span_chain.py、text_runs.py
- Create: tests/test_pdf_fast_wireless.py
- Create: tests/fixtures/rust_migration/wireless/native_span.json
- Create: docs/superpowers/rust-migration/sprints/sprint-006-native-span.md

Interfaces:

~~~rust
pub fn build_text_runs(spans: Vec<NativeSpanDto>, region: Rect4) -> Vec<TextRunDto>;
pub fn build_atoms(runs: Vec<TextRunDto>, region: Rect4) -> Vec<AtomDto>;
pub fn merge_wrapped_rows(atoms: Vec<AtomDto>, tolerance: f64) -> Vec<AtomDto>;
pub fn infer_output_order_mode(atoms: Vec<AtomDto>) -> OutputOrderMode;
pub fn recover_native_candidates(input: NativeRecoveryInput) -> NativeRecoveryOutput;
~~~

- [x] Step 1: 增加 source continuity 和 text composition failing vectors。覆盖 ASCII、CJK、mixed text、missing font/size、character bboxes、source positions、wrapped fields、currency separators、whitelisted spaced CJK words 及男/女不合并反例。
- [x] Step 2: 用 page spy 确认 native-span adapter 不调用 get_text("words")。
- [x] Step 3: 实现 span → run → atom；保留 source refs、text order、bbox witness、flow range 和 merge kind。
- [x] Step 4: 添加 text、bbox、source position、span refs、order mode 和 field boundary 的 differential report。
- [x] Step 5: 测试、benchmark 和提交。

~~~powershell
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wireless.py tests/test_wireless_structure_span_chain.py tests/test_wireless_structure_text_runs.py tests/test_wireless_output_order.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite native-span --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-006/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite native-span --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-006/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite native-span --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-006/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite native-span --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-006/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-006/baseline/native-span-python.json --python output/rust_migration_benchmark/sprint-006/python/native-span-python.json --rust output/rust_migration_benchmark/sprint-006/rust/native-span-rust.json --shadow output/rust_migration_benchmark/sprint-006/shadow/native-span-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-006-benchmark.md
git diff --check
git add -- rust/native_span.rs rust/types.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/wireless_table_recovery.py src/hexai_pdf_parser/tables/wireless_structure/span_chain.py src/hexai_pdf_parser/tables/wireless_structure/text_runs.py tests/test_pdf_fast_wireless.py tests/fixtures/rust_migration/wireless/native_span.json docs/superpowers/rust-migration/sprints/sprint-006-native-span.md
git commit -m "feat: migrate native span and text run kernels to Rust"
~~~

## Sprint 007：迁移中文/混合无线结构恢复

Files:

- Create: rust/wireless_structure.rs
- Modify: rust/native_span.rs、rust/types.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/wireless_structure/{columns,continuations,grid,header_topology,hybrid_body,logical_grid,merged_cells,recoverer}.py
- Modify: src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py
- Modify: tests/test_wireless_structure_span_chain.py、tests/test_wireless_structure_text_runs.py、tests/test_wireless_table_recovery.py、tests/test_wireless_extractor_split.py
- Create: tests/test_pdf_fast_wireless_structure.py
- Create: tests/fixtures/rust_migration/wireless/chinese_structure.json
- Modify: changes.md
- Create: docs/superpowers/rust-migration/sprints/sprint-007-chinese-structure.md

Interfaces:

~~~rust
pub fn infer_column_bands(atoms: Vec<AtomDto>, region: Rect4, config: StructureConfig) -> Vec<ColumnBandDto>;
pub fn build_logical_grid(atoms: Vec<AtomDto>, bands: Vec<ColumnBandDto>, config: StructureConfig) -> LogicalGridDto;
pub fn infer_header_topology(grid: LogicalGridDto, config: StructureConfig) -> LogicalGridDto;
pub fn resolve_exact_slot_conflicts(grid: LogicalGridDto) -> LogicalGridDto;
pub fn materialize_empty_cells(grid: LogicalGridDto) -> Vec<CellDto>;
pub fn recover_cells_from_region(input: NativeRegionInput) -> NativeRegionOutput;
~~~

- [x] Step 1: 增加 independent leaf columns、incomplete 1:2 header pairs、non-empty rowspan blockers、exact slot conflicts、empty slots、wrapped leaf headers、paired CJK artifacts、sparse alignment artifacts 和 continuation rows 的 RED vectors。
- [x] Step 2: 运行完整 structure tests，确认 Rust entry points 尚未实现时按预期失败。
- [x] Step 3: 按 columns → rows → logical grid → header topology → spans → empty slots 的顺序实现；进入结构层后只允许 Atom、ColumnBand、PhysicalCell 和 LogicalGrid DTO。
- [x] Step 4: 每次 colspan/rowspan 调整后重算 occupancy；冲突 span 拒绝；未覆盖槽位生成独立空 1x1 Cell。
- [x] Step 5: 增加 Chinese facade shadow/rust；测试 get_text("words")、zebra 和 legacy 在 zh/mixed 路径中一旦被请求就失败。
- [x] Step 6: 测试、benchmark 和提交。

~~~powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_wireless_structure.py tests/test_wireless_structure_*.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_wireless_output_order.py tests/test_unify_wireless_recovery.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite chinese-wireless --fixture tests/fixtures/rust_migration/wireless/chinese_structure.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-007/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite chinese-wireless --fixture tests/fixtures/rust_migration/wireless/chinese_structure.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-007/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite chinese-wireless --fixture tests/fixtures/rust_migration/wireless/chinese_structure.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-007/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite chinese-wireless --fixture tests/fixtures/rust_migration/wireless/chinese_structure.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-007/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-007/baseline/chinese-wireless-python.json --python output/rust_migration_benchmark/sprint-007/python/chinese-wireless-python.json --rust output/rust_migration_benchmark/sprint-007/rust/chinese-wireless-rust.json --shadow output/rust_migration_benchmark/sprint-007/shadow/chinese-wireless-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-007-benchmark.md
git diff --check
git add -- rust/wireless_structure.rs rust/native_span.rs rust/types.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/wireless_structure/columns.py src/hexai_pdf_parser/tables/wireless_structure/continuations.py src/hexai_pdf_parser/tables/wireless_structure/grid.py src/hexai_pdf_parser/tables/wireless_structure/header_topology.py src/hexai_pdf_parser/tables/wireless_structure/hybrid_body.py src/hexai_pdf_parser/tables/wireless_structure/logical_grid.py src/hexai_pdf_parser/tables/wireless_structure/merged_cells.py src/hexai_pdf_parser/tables/wireless_structure/recoverer.py src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py tests/test_wireless_structure_span_chain.py tests/test_wireless_structure_text_runs.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_pdf_fast_wireless_structure.py tests/fixtures/rust_migration/wireless/chinese_structure.json changes.md docs/superpowers/rust-migration/sprints/sprint-007-chinese-structure.md
git commit -m "feat: migrate Chinese wireless structure recovery to Rust"
~~~

## Sprint 008：迁移共享 Native Recovery 和候选选择

Files:

- Modify: rust/native_span.rs、rust/wireless_structure.rs、rust/lib.rs
- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/wireless_table_recovery.py
- Modify: src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py、wireless_table_extractor.py
- Modify: tests/test_wireless_table_recovery.py、tests/test_wireless_extractor_split.py、tests/test_unify_wireless_recovery.py
- Modify: changes.md
- Create: docs/superpowers/rust-migration/sprints/sprint-008-shared-recovery.md

Interfaces:

~~~rust
pub fn recover_wireless_tables(input: WirelessRecoveryInput) -> WirelessRecoveryOutput;
pub fn select_candidates(candidates: Vec<TableCandidateDto>, excluded: Vec<Rect4>, allowed: Vec<Rect4>) -> Vec<TableCandidateDto>;
pub fn table_quality(candidate: &TableCandidateDto) -> f64;
~~~

- [ ] Step 1: 为 row clustering、column tracks、candidate runs 和 quality selection 增加 RED vectors。
- [ ] Step 2: 基于已验证的 native-span 和 structure DTO 实现共享 Rust recovery batch。
- [ ] Step 3: Python 保留 diagnostics、excluded/allowed filtering、empty result、exception mapping 和 monkeypatch surface。
- [ ] Step 4: 运行 differential tests 和 shared-wireless benchmark。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_unify_wireless_recovery.py tests/test_wireless_output_order.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite shared-wireless --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/sprint-008/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite shared-wireless --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/sprint-008/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite shared-wireless --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/sprint-008/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite shared-wireless --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/sprint-008/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-008/baseline/shared-wireless-python.json --python output/rust_migration_benchmark/sprint-008/python/shared-wireless-python.json --rust output/rust_migration_benchmark/sprint-008/rust/shared-wireless-rust.json --shadow output/rust_migration_benchmark/sprint-008/shadow/shared-wireless-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-008-benchmark.md
~~~

- [ ] Step 5: 只有 zh/mixed 输出和 no-words tests 通过后提交。

~~~powershell
git diff --check
git add -- rust/native_span.rs rust/wireless_structure.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/wireless_table_recovery.py src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py tests/test_wireless_table_recovery.py tests/test_wireless_extractor_split.py tests/test_unify_wireless_recovery.py changes.md docs/superpowers/rust-migration/sprints/sprint-008-shared-recovery.md
git commit -m "feat: migrate shared wireless candidate recovery to Rust"
~~~

## Sprint 009：迁移英文 Zebra、General Wireless 和 Legacy 纯算法

Files:

- Create: rust/english_wireless.rs
- Modify: rust/types.rs、rust/lib.rs、src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/extractors/english_table_extractor.py、wireless_table_extractor.py
- Modify: src/hexai_pdf_parser/tables/table_extractor.py only at legacy pure-rule adapter boundary
- Create: tests/test_pdf_fast_english_wireless.py
- Create: tests/fixtures/rust_migration/english/english_wireless.json
- Modify: tests/test_page_347_structure.py、test_rule_first_table_detection.py、test_table_extractor.py
- Modify: changes.md
- Create: docs/superpowers/rust-migration/sprints/sprint-009-english-wireless.md

Interfaces:

~~~rust
pub fn group_backgrounds(backgrounds: Vec<BackgroundDto>, tolerance: f64) -> Vec<BackgroundGroupDto>;
pub fn detect_zebra_rows(input: ZebraInput) -> Vec<RowBandDto>;
pub fn assign_words_to_zebra_rows(rows: Vec<RowBandDto>, words: Vec<WordDto>) -> Vec<RowBandDto>;
pub fn infer_english_columns(input: EnglishGridInput) -> Vec<ColumnBandDto>;
pub fn build_english_cells(input: EnglishGridInput) -> Vec<CellDto>;
pub fn build_general_wireless_cells(input: GeneralWirelessInput) -> Vec<CellDto>;
pub fn build_legacy_text_alignment(input: LegacyAlignmentInput) -> Vec<CellDto>;
~~~

- [ ] Step 1: 增加 drawing/background/words DTO fixtures 和 RED tests。覆盖 empty drawings、white/colored bands、separated tables、header rows、boundary words、dollar signs、pure amounts、metric tokens、continuation rows、sparse rowspans、empty columns 和 legacy flags。
- [ ] Step 2: 保持 extraction 和 routing 在 Python；Rust 只接 normalized background/word DTO；保留 zebra → general wireless → text-alignment/fallback 顺序。
- [ ] Step 3: 实现 Rust English kernels；currency 和 financial token rules 必须有直接 vectors，不增加 Python oracle 之外的业务特例。
- [ ] Step 4: 运行英文回归和 benchmark。

~~~powershell
cargo test
maturin develop --release
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_english_wireless.py tests/test_page_347_structure.py tests/test_rule_first_table_detection.py tests/test_wireless_extractor_split.py tests/test_wireless_output_order.py tests/test_table_extractor.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite english-wireless --fixture tests/fixtures/rust_migration/english/english_wireless.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-009/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite english-wireless --fixture tests/fixtures/rust_migration/english/english_wireless.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-009/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite english-wireless --fixture tests/fixtures/rust_migration/english/english_wireless.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-009/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite english-wireless --fixture tests/fixtures/rust_migration/english/english_wireless.json --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/sprint-009/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-009/baseline/english-wireless-python.json --python output/rust_migration_benchmark/sprint-009/python/english-wireless-python.json --rust output/rust_migration_benchmark/sprint-009/rust/english-wireless-rust.json --shadow output/rust_migration_benchmark/sprint-009/shadow/english-wireless-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-009-benchmark.md
git diff --check
git add -- rust/english_wireless.rs rust/types.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/extractors/english_table_extractor.py src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py src/hexai_pdf_parser/tables/table_extractor.py tests/test_pdf_fast_english_wireless.py tests/fixtures/rust_migration/english/english_wireless.json tests/test_page_347_structure.py tests/test_rule_first_table_detection.py tests/test_table_extractor.py changes.md docs/superpowers/rust-migration/sprints/sprint-009-english-wireless.md
git commit -m "feat: migrate English wireless kernels to Rust"
~~~

Expected: page 347 preserves English recovery；page 415 chart masking unchanged；zh/mixed still do not request words/zebra/legacy。

## Sprint 010：迁移可 DTO 化的表头和结构后处理

Files:

- Create: rust/table_normalization.rs
- Modify: rust/types.rs、rust/lib.rs、src/hexai_pdf_parser/rust_adapter.py
- Inspect and modify only tested pure sections of src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py and financial_header_handler.py
- Modify: tests/test_financial_header_normalizer.py、test_header_upward_merge.py、test_header_wrapping_page_347_169.py、test_wrapped_leaf_headers.py、test_wrapped_field_font_and_witness.py
- Create: tests/test_pdf_fast_table_normalization.py
- Modify: docs/superpowers/rust-migration/capability-matrix.md
- Modify: changes.md
- Create: docs/superpowers/rust-migration/sprints/sprint-010-table-normalization.md

Interfaces:

~~~rust
pub fn infer_header_structure(input: HeaderGridInput) -> HeaderGridOutput;
pub fn merge_header_spans(input: HeaderGridInput) -> HeaderGridOutput;
pub fn normalize_financial_header_tokens(input: HeaderTokenInput) -> HeaderTokenOutput;
~~~

- [ ] Step 1: 审计每个 normalizer function 并写入 capability matrix。只消费 DTO 的函数必须排入 Rust；构造公开 Python object、调用外部服务或编码未批准 domain policy 的函数保留 Python 并记录理由。
- [ ] Step 2: 为 header topology、wrapped labels、witness、financial tokens 和 rejection cases 增加 RED vectors。
- [ ] Step 3: 实现已分类纯 kernel，Python 保留公开对象装配。
- [ ] Step 4: 运行 normalizer tests 和 benchmark。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_pdf_fast_table_normalization.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_header_wrapping_page_347_169.py tests/test_wrapped_leaf_headers.py tests/test_wrapped_field_font_and_witness.py
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite table-normalization --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-010/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite table-normalization --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-010/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite table-normalization --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-010/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite table-normalization --fixture tests/fixtures/rust_migration/wireless/native_span.json --warmups 3 --runs 10 --output-dir output/rust_migration_benchmark/sprint-010/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/sprint-010/baseline/table-normalization-python.json --python output/rust_migration_benchmark/sprint-010/python/table-normalization-python.json --rust output/rust_migration_benchmark/sprint-010/rust/table-normalization-rust.json --shadow output/rust_migration_benchmark/sprint-010/shadow/table-normalization-shadow.json --report docs/superpowers/rust-migration/evaluations/sprint-010-benchmark.md
~~~

- [ ] Step 5: 提交时附上 Python-retained functions 清单。

~~~powershell
git diff --check
git add -- rust/table_normalization.rs rust/types.rs rust/lib.rs src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/tables/normalizers/table_header_normalizer.py src/hexai_pdf_parser/tables/normalizers/financial_header_handler.py tests/test_financial_header_normalizer.py tests/test_header_upward_merge.py tests/test_header_wrapping_page_347_169.py tests/test_wrapped_leaf_headers.py tests/test_wrapped_field_font_and_witness.py tests/test_pdf_fast_table_normalization.py changes.md docs/superpowers/rust-migration/sprints/sprint-010-table-normalization.md docs/superpowers/rust-migration/capability-matrix.md
git commit -m "feat: migrate DTO-compatible table normalization to Rust"
~~~

## Sprint 011：Shadow 模式、逐路径切换和回归门禁

Files:

- Modify: src/hexai_pdf_parser/rust_adapter.py
- Modify: src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py、src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py、src/hexai_pdf_parser/tables/extractors/english_table_extractor.py、src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py、src/hexai_pdf_parser/tables/wireless_table_recovery.py
- Modify: src/hexai_pdf_parser/core/pipeline.py only for stable stage labels if required
- Modify: scripts/export_rust_migration_e2e.py
- Create: tests/test_rust_migration_routing.py
- Modify: changes.md
- Create: docs/superpowers/rust-migration/sprints/sprint-011-routing.md

Interfaces:

~~~python
def get_rust_mode() -> str: ...
def run_python_or_rust(mode: str, python_fn, rust_fn, input_dto): ...
def assert_equivalent(path: str, python_value, rust_value) -> None: ...
~~~

- [ ] Step 1: 为 python、shadow、rust、Rust exception 和 invalid mode 增加 routing tests。无环境变量时必须为 python；`shadow` 比较后永远返回 Python；`rust` 成功时返回 Rust；Rust exception 记录 `rust_fallback` 后返回 Python；invalid mode 抛出清晰配置错误。
- [ ] Step 2: 写明并测试 output-difference policy。生产 `rust` 路由不隐式运行第二次 Python，也不把不一致静默降级；任何不一致必须由 shadow/differential comparator 报告并阻断 primary 切换。只有运行期 Rust exception 可以按诊断字段回退 Python。
- [ ] Step 3: 添加 path-specific feature gates。已验证 wired 可独立启用，native-span/English 可保持 Python；不改变公开 API 或 CLI flags。
- [ ] Step 4: 对代表页运行 shadow。

~~~powershell
$env:PDF_RUST_MODE='shadow'
python scripts/export_rust_migration_e2e.py --mode shadow --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --dpi 200 --output-dir output/pdf_rust_migration_shadow_20260916
~~~

Expected: no unclassified difference；没有 Chinese/mixed words access；没有 chart/table boundary regression；输出目录包含 JSON、PNG、manifest、segments 和 peak RSS。
- [ ] Step 5: 按 wired → shared geometry → native-span → Chinese/mixed → English → normalization 的顺序逐路径切换，每次复跑该路径测试和 benchmark；每一路径都必须比较 feature-dev Python、迁移分支 Python 和 Rust 三份结果。
- [ ] Step 6: 运行 fix 端到端验收。

~~~powershell
$env:PDF_RUST_MODE='python'
python scripts/export_rust_migration_e2e.py --mode python --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --dpi 200 --output-dir output/fix_rust_migration_e2e_python_20260916
$env:PDF_RUST_MODE='shadow'
python scripts/export_rust_migration_e2e.py --mode shadow --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --dpi 200 --output-dir output/fix_rust_migration_e2e_shadow_20260916
$env:PDF_RUST_MODE='rust'
python scripts/export_rust_migration_e2e.py --mode rust --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --dpi 200 --output-dir output/fix_rust_migration_e2e_rust_20260916
python scripts/compare_rust_migration.py --manifests output/fix_rust_migration_e2e_python_20260916/manifest.json output/fix_rust_migration_e2e_rust_20260916/manifest.json --shadow output/fix_rust_migration_e2e_shadow_20260916/manifest.json --report docs/superpowers/rust-migration/evaluations/sprint-011-fix-e2e.md
~~~

`export_rust_migration_e2e.py` 必须调用现有 `PDFParser`，对每个 page index 写 `pages/page-<index>.json`（使用 `JSONWriter.write_page`）、`tables/page-<index>.png`（固定 `dpi`、`alpha=False`）和根目录 `manifest.json`。manifest schema 固定为 `{schema_version: 1, mode, commit, input_sha256, pages, dpi, model, environment, segment_samples: {extract: [], dto: [], ffi: [], algorithm: [], adapt: [], total: []}, segments: {extract: {count, p50, p95, p99}, dto: {count, p50, p95, p99}, ffi: {count, p50, p95, p99}, algorithm: {count, p50, p95, p99}, adapt: {count, p50, p95, p99}, total: {count, p50, p95, p99}}, memory: {peak_rss_samples_bytes: [], peak_rss_p50_bytes, peak_rss_p95_bytes}, page_results: [{page_index, status, table_count, json, png, table_sources, rows, cols, bbox, occupancy_conflicts, segments, memory, error}]}`；时间单位统一为秒、RSS 单位统一为 bytes，`page_results[].segments` 使用同样的六阶段结构，失败页仍写 `status=failed` 和 error，不得让单页失败被静默跳过。逐页断言 table count、source、rows/cols、bbox、text、Cell 顺序、rowspan/colspan、empty slots、occupancy、chart masking、相邻表格边界和失败页列表；若仓库端测服务入口已在 Sprint 000 发现，则用同一 PDF/页集重复请求并把 HTTP/响应 manifest 附在同一报告中。
- [ ] Step 7: 通过独立 Evaluator 后提交。

~~~powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q tests/test_rust_migration_routing.py tests/test_pdf_fast_binding.py tests/test_pdf_fast_dto.py tests/test_pdf_fast_wired.py tests/test_pdf_fast_wireless.py tests/test_pdf_fast_wireless_structure.py tests/test_pdf_fast_english_wireless.py tests/test_wireless_extractor_split.py tests/test_rule_first_table_detection.py
git diff --check
git add -- src/hexai_pdf_parser/rust_adapter.py src/hexai_pdf_parser/core/pipeline.py src/hexai_pdf_parser/tables/extractors/wired_table_extractor.py src/hexai_pdf_parser/tables/extractors/chinese_table_extractor.py src/hexai_pdf_parser/tables/extractors/english_table_extractor.py src/hexai_pdf_parser/tables/extractors/wireless_table_extractor.py src/hexai_pdf_parser/tables/wireless_table_recovery.py scripts/export_rust_migration_e2e.py tests/test_rust_migration_routing.py changes.md docs/superpowers/rust-migration/sprints/sprint-011-routing.md
git commit -m "feat: add differential routing for Rust table paths"
~~~

## Sprint 012：完整前后 Benchmark、页面视觉验证和发布物

Files:

- Modify: scripts/benchmark_rust_migration.py、scripts/compare_rust_migration.py
- Create: docs/superpowers/rust-migration/benchmarks/wired-geometry-final.md、wired-cells-final.md、shared-geometry-final.md、native-span-final.md、chinese-wireless-final.md、shared-wireless-final.md、english-wireless-final.md、table-normalization-final.md、page-final.md、final-pages-visual.md、benchmark-2026-09-16.md
- Create: docs/superpowers/rust-migration/sprints/sprint-012-final-evaluation.md
- Modify: changes.md
- Inspect: Cargo.toml、pyproject.toml、build.sh、setup.py、version

- [ ] Step 1: 运行函数级 benchmark suites。

~~~powershell
$migrationRoot = (Resolve-Path '.').Path
$functionSuites = @(
  @{Name='wired-geometry'; Fixture='tests/fixtures/rust_migration/wired/geometry.json'; Baseline='output/rust_migration_benchmark/sprint-003/baseline/wired-geometry-python.json'; Warmups=3; Runs=10},
  @{Name='wired-cells'; Fixture='tests/fixtures/rust_migration/wired/cells.json'; Baseline='output/rust_migration_benchmark/sprint-004/baseline/wired-cells-python.json'; Warmups=3; Runs=10},
  @{Name='shared-geometry'; Fixture='tests/fixtures/rust_migration/shared/geometry.json'; Baseline='output/rust_migration_benchmark/sprint-005/baseline/shared-geometry-python.json'; Warmups=3; Runs=10},
  @{Name='native-span'; Fixture='tests/fixtures/rust_migration/wireless/native_span.json'; Baseline='output/rust_migration_benchmark/sprint-006/baseline/native-span-python.json'; Warmups=3; Runs=10},
  @{Name='chinese-wireless'; Fixture='tests/fixtures/rust_migration/wireless/chinese_structure.json'; Baseline='output/rust_migration_benchmark/sprint-007/baseline/chinese-wireless-python.json'; Warmups=1; Runs=5},
  @{Name='shared-wireless'; Fixture='tests/fixtures/rust_migration/wireless/native_span.json'; Baseline='output/rust_migration_benchmark/sprint-008/baseline/shared-wireless-python.json'; Warmups=1; Runs=5},
  @{Name='english-wireless'; Fixture='tests/fixtures/rust_migration/english/english_wireless.json'; Baseline='output/rust_migration_benchmark/sprint-009/baseline/english-wireless-python.json'; Warmups=1; Runs=5},
  @{Name='table-normalization'; Fixture='tests/fixtures/rust_migration/wireless/native_span.json'; Baseline='output/rust_migration_benchmark/sprint-010/baseline/table-normalization-python.json'; Warmups=3; Runs=10}
)
foreach ($suite in $functionSuites) {
  if (-not (Test-Path -LiteralPath $suite.Baseline)) { throw "missing saved feature-dev baseline: $($suite.Baseline)" }
  python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite $suite.Name --fixture $suite.Fixture --warmups $suite.Warmups --runs $suite.Runs --output-dir "output/rust_migration_benchmark/final/$($suite.Name)/python"
  $env:PDF_RUST_MODE='shadow'
  python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite $suite.Name --fixture $suite.Fixture --warmups $suite.Warmups --runs $suite.Runs --output-dir "output/rust_migration_benchmark/final/$($suite.Name)/shadow"
  $env:PDF_RUST_MODE='rust'
  python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-dc00211 --suite $suite.Name --fixture $suite.Fixture --warmups $suite.Warmups --runs $suite.Runs --output-dir "output/rust_migration_benchmark/final/$($suite.Name)/rust"
  python scripts/compare_rust_migration.py --baseline $suite.Baseline --python "output/rust_migration_benchmark/final/$($suite.Name)/python/$($suite.Name)-python.json" --rust "output/rust_migration_benchmark/final/$($suite.Name)/rust/$($suite.Name)-rust.json" --shadow "output/rust_migration_benchmark/final/$($suite.Name)/shadow/$($suite.Name)-shadow.json" --report "docs/superpowers/rust-migration/benchmarks/$($suite.Name)-final.md"
}
~~~

- [ ] Step 2: 运行区域和页面 benchmark。

~~~powershell
$baselineRoot = (Resolve-Path ((git rev-parse --git-common-dir) + '/../.worktrees/feature-dev-baseline')).Path
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --source-root $baselineRoot --baseline-id feature-dev-dc00211 --suite page --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/final/pages/baseline
python scripts/benchmark_rust_migration.py --mode python --source-root $migrationRoot --baseline-id migration-python-dc00211 --suite page --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/final/pages/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite page --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/final/pages/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-primary-dc00211 --suite page --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --warmups 1 --runs 5 --output-dir output/rust_migration_benchmark/final/pages/rust
python scripts/compare_rust_migration.py --baseline output/rust_migration_benchmark/final/pages/baseline/page-python.json --python output/rust_migration_benchmark/final/pages/python/page-python.json --rust output/rust_migration_benchmark/final/pages/rust/page-rust.json --shadow output/rust_migration_benchmark/final/pages/shadow/page-shadow.json --report docs/superpowers/rust-migration/benchmarks/page-final.md
~~~

- [ ] Step 3: 运行全量 PDF Python 和 Rust 测量。

~~~powershell
# 复用 Sprint 001 保存的 feature-dev baseline artifact，不重新测量或覆盖它；三次迁移分支运行必须共用同一输入 hash、页集、DPI 和模型。
$savedBaseline = 'output/rust_migration_benchmark/baselines/feature-dev-dc00211/full-pdf-python.json'
if (-not (Test-Path -LiteralPath $savedBaseline)) { throw "missing Sprint 001 baseline artifact: $savedBaseline" }
$migrationRoot = (Resolve-Path '.').Path
python scripts/benchmark_rust_migration.py --mode python --suite full-pdf --source-root $migrationRoot --baseline-id migration-python-dc00211 --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/final/python
$env:PDF_RUST_MODE='shadow'
python scripts/benchmark_rust_migration.py --mode shadow --source-root $migrationRoot --baseline-id shadow-dc00211 --suite full-pdf --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/final/shadow
$env:PDF_RUST_MODE='rust'
python scripts/benchmark_rust_migration.py --mode rust --source-root $migrationRoot --baseline-id rust-primary-dc00211 --suite full-pdf --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --warmups 1 --runs 3 --output-dir output/rust_migration_benchmark/final/rust
python scripts/compare_rust_migration.py --baseline $savedBaseline --python output/rust_migration_benchmark/final/python/full-pdf-python.json --rust output/rust_migration_benchmark/final/rust/full-pdf-rust.json --shadow output/rust_migration_benchmark/final/shadow/full-pdf-shadow.json --report docs/superpowers/rust-migration/benchmarks/benchmark-2026-09-16.md
~~~

报告必须同时列出 `feature-dev Python baseline`、`migration Python` 和 `Rust` 三列；每个 suite 计算 `baseline.segments.algorithm.p95 / rust.segments.algorithm.p95` 与 `baseline.segments.total.p95 / rust.segments.total.p95`，并列出 DTO/FFI/adaptation 开销、`memory.peak_rss_p50_bytes`、`memory.peak_rss_p95_bytes`、throughput、warm/cold 差异和失败页。纯算法无提升或端到端回退超过 5% 的路径不得切换 Rust primary，但可以保留已完成的 Rust 实现供后续优化。

- [ ] Step 4: 运行结构和视觉页面验证。

~~~powershell
$env:PDF_RUST_MODE='python'
python scripts/export_rust_migration_e2e.py --mode python --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --dpi 200 --output-dir output/pdf_rust_migration_final_python_20260916
$env:PDF_RUST_MODE='shadow'
python scripts/export_rust_migration_e2e.py --mode shadow --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --dpi 200 --output-dir output/pdf_rust_migration_final_shadow_20260916
$env:PDF_RUST_MODE='rust'
python scripts/export_rust_migration_e2e.py --mode rust --pdf D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf --pages 185,196,347,415,437,1002,1014 --dpi 200 --output-dir output/pdf_rust_migration_final_rust_20260916
python scripts/compare_rust_migration.py --manifests output/pdf_rust_migration_final_python_20260916/manifest.json output/pdf_rust_migration_final_rust_20260916/manifest.json --shadow output/pdf_rust_migration_final_shadow_20260916/manifest.json --report docs/superpowers/rust-migration/benchmarks/final-pages-visual.md
~~~

Inspect both JSON and PNG for table count, source, rows/cols, bbox, text, Cell order, spans, empty slots, frame boundaries, chart masking and neighboring-table separation。

- [ ] Step 5: 运行 Rust 全量输出到新目录。

~~~powershell
$env:PDF_RUST_MODE='rust'
python -c "from hexai_pdf_parser.core.pdf_parser import PDFParser; p=PDFParser(r'D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf'); r=p.parse(output_dir=r'output/pdf_rust_migration_final_full_20260916'); assert r.code == 1, r.message; assert r.data.page_count == 1023"
~~~

确认所有页覆盖、timings.json 存在、输出目录不是旧目录。

- [ ] Step 6: 验证测试、构建和发布物。

~~~powershell
cargo fmt --check
cargo test
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q
maturin build --release
maturin sdist
git diff --check
~~~

追加平台责任边界：当前 Windows/Python 3.12 必须完成 wheel 安装/import smoke；CI 或发布机必须完成 Linux/manylinux 对应 wheel 构建和 import smoke；至少用 Python 3.7 与当前 Python 3.12 验证 `cp37-abi3` wheel 可导入。若当前环境不能构建 Linux/manylinux，只记录为发布阻塞，不得以 Windows 通过替代。

检查生成物：

- wheel tag 含 cp37-abi3，不能是 py3-none-any；
- metadata version 为 1.1.1；
- Requires-Python 为 >=3.7；
- console entry point 为 hexai_pdf_parser=hexai_pdf_parser.cli:main；
- sdist 含 Cargo.toml、rust/ 和 Python src/；
- sdist 排除 output/、target/、.venv/、本机 PDF 和开发目录。

- [ ] Step 7: 写最终评估并提交小型报告。

最终报告包含 Python total、Rust total、pure algorithm time、FFI/adapter time、P50/P95/P99、speedup/regression、output equality、page coverage、failed pages 和所有明确保留 Python 的函数。

~~~powershell
git diff --check
git add -- scripts/benchmark_rust_migration.py scripts/compare_rust_migration.py changes.md docs/superpowers/rust-migration/benchmarks/wired-geometry-final.md docs/superpowers/rust-migration/benchmarks/wired-cells-final.md docs/superpowers/rust-migration/benchmarks/shared-geometry-final.md docs/superpowers/rust-migration/benchmarks/native-span-final.md docs/superpowers/rust-migration/benchmarks/chinese-wireless-final.md docs/superpowers/rust-migration/benchmarks/shared-wireless-final.md docs/superpowers/rust-migration/benchmarks/english-wireless-final.md docs/superpowers/rust-migration/benchmarks/table-normalization-final.md docs/superpowers/rust-migration/benchmarks/page-final.md docs/superpowers/rust-migration/benchmarks/final-pages-visual.md docs/superpowers/rust-migration/benchmarks/benchmark-2026-09-16.md docs/superpowers/rust-migration/sprints/sprint-012-final-evaluation.md
git commit -m "docs: record Rust migration benchmark and final evaluation"
~~~

## 最终验收清单

- [ ] capability-matrix.md 没有未分类的纯 Python 表格算法。
- [ ] 每个迁移函数都有直接输入/输出测试，执行记录包含 RED → GREEN。
- [ ] cargo test、相关 pytest、完整 pytest、cargo fmt --check 和 git diff --check 通过。
- [ ] wired、中文/混合 wireless、英文 wireless 和表头后处理均有 Rust/Python differential report。
- [ ] Python、shadow、Rust 三种模式均可运行，默认模式和公开 API 兼容。
- [ ] 中文/混合路径没有 words 回读、zebra 或 legacy 回退。
- [ ] 函数、FFI、区域、页面、全量 PDF 五层 benchmark 已保存。
- [ ] benchmark 明确区分 feature-dev Python baseline、迁移 Python、shadow 和 Rust；报告含 pure algorithm、DTO、FFI、adaptation、total、peak RSS、吞吐和 P50/P95/P99。
- [ ] 最终结构化 JSON 和 PNG 逐页核验无未分类差异。
- [ ] 全量 PDF 解析输出位于新目录，覆盖 1023 页，未覆盖旧结果。
- [ ] wheel、sdist、abi3、版本、入口和 Python 下限检查通过。
- [ ] Evaluator 报告为 pass；否则只报告 repair 或待决策状态，不宣称完成。
