# Sprint 011：Shadow 模式、逐路径切换和回归门禁

## 目标与范围

构建端到端统一路由仲裁、差分诊断、优雅降级和路径特征门禁（feature gate）体系：
1. **统一路由接口**: 在 `src/hexai_pdf_parser/rust_adapter.py` 提供 `get_rust_mode(path)`、`run_python_or_rust` 与 `assert_equivalent`。
2. **模式合同实现**:
   - `python`: 仅执行纯 Python 算子，不调用 Rust。
   - `rust`: 优先执行 Rust 算子；若遇到异常，记录 `rust_fallback` 诊断并安全降级至 Python，保证系统高可用。
   - `shadow`: 同时执行 Python 与 Rust 算子，若发生结果不一致，记录 `rust_output_mismatch` 诊断，但永远向调用方返回 Python 权威结果。
   - 非法模式严格拦截并抛出 `ValueError`。
3. **路径级特征门禁**: 支持通过 `PDF_RUST_MODE_<PATH>` 对有线、无线、英文等不同提取路径进行独立灰度开关配置。
4. **端到端代表页验收**: 通过 `scripts/export_rust_migration_e2e.py` 在 `zh_all_table_pages.pdf` 代表页（185, 196, 347, 415, 437, 1002, 1014）上完成 Python、Shadow、Rust 三路解析与全字段对比。

## 拥有的文件与变更清单

- `src/hexai_pdf_parser/rust_adapter.py`: 增加全局路由管理、诊断收集、优雅降级和特征门禁函数。
- `tests/test_rust_migration_routing.py`: 9 个针对各运行模式、异常 fallback、mismatch 诊断记录及 path 专用开关的单元测试。
- `scripts/export_rust_migration_e2e.py`: 升级为消费完整 `PDFParser` 流水线并输出规范 `manifest.json`、页面 JSON 与 PNG 渲染图的端到端导出工具。
- `docs/superpowers/rust-migration/evaluations/sprint-011-fix-e2e.md`: 真实代表页三路端到端对比报告。
- `docs/superpowers/rust-migration/sprints/sprint-011-routing.md`: 本总结文档。
- `docs/superpowers/rust-migration/evaluations/sprint-011.md`: 独立评估报告。

## 验证与测试结果

- **路由与全量回归测试**:
  - `pytest tests/test_rust_migration_routing.py`: 9 passed, 0 failed.
  - 全链路测试套件（9 个核心文件）: 95 passed, 0 failed.
  - `git diff --check`: 0 警告。
- **代表页端到端对比**:
  - 输入: `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf` (pages 185, 196, 347, 415, 437, 1002, 1014)。
  - 对比结果: `equal: True`，`differences_count: 0`。
  - 所有表格无重叠/无槽位占用冲突（`occupancy_conflicts: 0`），结构化结果完全一致。
