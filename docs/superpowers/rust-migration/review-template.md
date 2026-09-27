# Sprint 独立评审模板

## 评审输入包

Generator 提供只读 worktree、允许文件清单、feature-dev 完整 SHA、DTO schema、能力矩阵、结构化输出样例、测试输出、git diff --check 输出和变更文件清单。包中不得有 PDF、PNG、output、target 或未列文件；Evaluator 使用独立的 gpt-5.6-luna 只读 worktree。

## 评审命令

git status --short --branch
git diff --check
git diff --name-only feature-dev...HEAD
python scripts/audit_rust_migration_capability.py --root src/hexai_pdf_parser/tables --root src/hexai_pdf_parser/tables/normalizers --output docs/superpowers/rust-migration/capability-matrix.md
python -m py_compile scripts/audit_rust_migration_capability.py
`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'`
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_rust_migration_benchmark.py tests/test_wired_table_extractor.py tests/test_wireless_structure_columns.py tests/test_wireless_structure_grid.py tests/test_wireless_structure_header_topology.py tests/test_wireless_structure_merges.py tests/test_wireless_structure_recoverer.py tests/test_wireless_structure_span_chain.py tests/test_wireless_structure_text_runs.py tests/test_financial_header_normalizer.py`

评审者还要核对 DTO 是否注册、Python/Rust 边界、中文 native-span 是否禁止 words/zebra/legacy 回退、输出 equality、P95/no-regression 证据和 Sprint 范围。

Windows PowerShell 等价写法为 `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest -q ...`。PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 用于避免本机 pytest 插件自动加载造成环境漂移；不得把解释器或 pytest 绑定到任何本机绝对路径。

## 输出与门禁

最终结果只能是 PASS、REPAIR 或 BLOCKED，必须附证据、失败项、P1/P2、疑虑和文件清单。未注册 DTO、unknown/not checked、虚构 benchmark、提前切 Rust primary、越界文件或静默吞掉 mismatch 直接 BLOCKED。

- P1：合同、数据正确性、基线 SHA、未注册 DTO、越界文件或阻断测试；修复后重新打包并完整评审。
- P2：文档、可复现性、调用位置或非阻断映射；修复后重跑受影响检查并重新评审。
- 未得到 PASS 不得开始下一 Sprint。
