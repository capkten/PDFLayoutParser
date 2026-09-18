# Stage 1：owned DTO 清单、合同与审计口径

## 目标与范围

本阶段固定能力矩阵和 owned DTO 合同，修复审计从 `src/hexai_pdf_parser/tables` 子目录启动时的根目录误判。未修改英文/中文 wireless、wired 或 normalizer 的 Rust 生产算法；这些属于后续 Stage 2–6。

## 根因与判定条件

- 根因：审计原实现只检查传入路径本身是否含 `rust/`，源码子目录没有该目录时直接以子目录为项目根，所有 Rust 文件、路由、记录和 `output/` 证据均读取失败。
- 修复：沿传入路径向上查找包含 `rust/` 的目录作为项目根；仓库根和源码子目录调用共享同一能力结果。
- 能力单元分别检查 `rust_symbol`、`production_route`、`behavior_test`、`migration_record`、`page_or_diff_evidence` 和 `dto_schema`。缺少 route 为 `adapter_only`，其余缺项为 `blocked`；固定 Python 编排/范围外单元不伪装为 migrated。
- AST 分类将脚本、测试、benchmark、CLI/I/O/debug、页面/绘图/文字采集和公开对象装配保留在 Python；纯 owned DTO 函数可分类为 `exact`，不等于已完成生产迁移。

## TDD 记录

- RED：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 C:\Users\23662\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q tests/test_audit_rust_migration_capability.py`，源码子目录断言失败，且 `schema_markers` 缺失导致合同测试失败。
- GREEN：同命令最终 `5 passed`；`tests/test_owned_dto_contract.py` 最终 `8 passed`。

## 验证命令

- `python scripts/audit_rust_migration_capability.py --root . --output 迁移记录/capability-matrix.md`：登记 2716 个 AST 节点，能力状态 9 migrated、1 python_orchestration、1 out_of_scope。
- 同脚本以 `src/hexai_pdf_parser/tables` 为 `--root`：登记 779 个 AST 节点，能力状态相同，证明根解析一致。
- `cargo test --lib`：43 passed、0 failed。
- `git diff --check`：提交前执行。

## 未迁移边界

页面访问、PyMuPDF 文字/绘图采集、模型推理、渲染、CLI/I/O、debug、公开 Python Table/Cell/BBox 装配和未具备生产 route 的 Rust symbol 不在本阶段迁移；算法行为迁移留给后续 Stage 2–6。
