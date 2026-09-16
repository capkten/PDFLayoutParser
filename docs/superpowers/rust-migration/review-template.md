# Sprint 独立评审模板

## 评审输入包

Generator 提供只读 worktree、允许文件清单、feature-dev 完整 SHA、DTO schema、能力矩阵、结构化输出样例、测试输出、git diff --check 输出和变更文件清单。包中不得有 PDF、PNG、output、target 或未列文件；Evaluator 使用独立的 gpt-5.6-luna 只读 worktree。

## 评审命令

git status --short --branch
git diff --check
git diff --name-only feature-dev...HEAD
python scripts/audit_rust_migration_capability.py --root src/hexai_pdf_parser/tables --root src/hexai_pdf_parser/tables/normalizers --output temporary-matrix.md
python -m py_compile scripts/audit_rust_migration_capability.py
pytest -q focused-checks

评审者还要核对 DTO 是否注册、Python/Rust 边界、中文 native-span 是否禁止 words/zebra/legacy 回退、输出 equality、P95/no-regression 证据和 Sprint 范围。

## 输出与门禁

最终结果只能是 PASS、REPAIR 或 BLOCKED，必须附证据、失败项、P1/P2、疑虑和文件清单。未注册 DTO、unknown/not checked、虚构 benchmark、提前切 Rust primary、越界文件或静默吞掉 mismatch 直接 BLOCKED。

- P1：合同、数据正确性、基线 SHA、未注册 DTO、越界文件或阻断测试；修复后重新打包并完整评审。
- P2：文档、可复现性、调用位置或非阻断映射；修复后重跑受影响检查并重新评审。
- 未得到 PASS 不得开始下一 Sprint。
