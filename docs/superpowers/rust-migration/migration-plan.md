# PDF 表格逻辑 Rust 迁移总计划（历史索引）

> 状态：superseded。执行入口是 [2026-09-16-rust-extreme-migration.md](../plans/2026-09-16-rust-extreme-migration.md)；本文件保留历史阶段索引，不再作为独立执行计划。

完整执行计划见：[2026-09-16-rust-extreme-migration.md](../plans/2026-09-16-rust-extreme-migration.md)。本文件保留能力矩阵入口和阶段索引。

## 目标

按已确认的精确行为合同，将有线、中文/混合无线、英文无线的纯计算逻辑逐函数迁入一个 PyO3/maturin 扩展。Python 保留 PDF 解析与提取、API、路由、项目对象和序列化；每个函数以相同结构化输入向量锁定输出。

## 阶段顺序

1. **基线与 benchmark**：先建立五层计时、输出 canonicalize、差异报告和运行环境记录。
2. **Rust DTO/FFI 核心**：扩展已有 abi3 模块，形成统一 owned DTO 和批量接口。
3. **有线逻辑**：[有线阶段计划](../plans/2026-09-16-rust-wired-table-logic.md)，并以极限迁移计划中的 Sprint 003-004 为准。
4. **共享几何与 native-span**：[native-span 阶段计划](../plans/2026-09-16-rust-native-span-wireless-core.md)，并以 Sprint 005-008 为准。
5. **英文无线**：[英文阶段计划](../plans/2026-09-16-rust-english-wireless.md)，并以 Sprint 009 为准。
6. **表头后处理、逐路径切换和最终全量 benchmark**：执行 Sprint 010-012。

每一阶段可独立评审和验收；生产路由只在相应阶段所有纯函数与 facade 测试通过后切换。尚未迁移的路径继续走现有 Python 实现。

## 通用执行规则

- 每个待迁函数先从 Python 基线构造相同输入/预期输出的失败测试；Rust 单测和 pytest binding 测试引用同一组小型 JSON/fixture 向量。
- Rust DTO 持有 `f64` 坐标、`String`、有序 `Vec` 和显式来源索引；将 `fitz.Rect`、Python `Cell` 等对象留在适配层之外。
- 每次 PyO3 调用按页或区域传递完整批次；长计算阶段释放 GIL，不逐 token/Cell 往返 FFI。
- 有线 drawing 与 words、无线 native span、英文 background/words 都由 Python/PyMuPDF 采集；纯规则在 Rust 执行。
- 每次阶段完成运行 Rust 单测、模块 pytest、相关 facade/API 测试、页面端测、`git diff --check`；验证记录写入 `changes.md` 和 sprint evaluation。
- 每个 Sprint 都必须运行对应层级 benchmark；输出一致性是硬门槛，性能结果必须同时拆分算法、FFI/adapter 和端到端耗时，不得只凭 Rust 函数耗时宣称收益。
- 不将主工作区未提交内容、295 MB 本地 PDF 或输出产物提交到迁移分支。

## 交付顺序

- Sprint 001：建立可复现 benchmark harness；当前迁移分支的 benchmark 基础设施已实现，但生产路由仍为 Python。Rust DTO/算法迁移以极限执行计划的 Sprint 002 起步。
- Sprint 002 及后续：逐函数完成有线与 Python words 适配；每个函数单独有输入/输出合同。
- 下一阶段：完成 native-span 采集边界及共享候选内核，再完成中文/混合 `wireless_structure`。
- 最后一阶段：迁移英文专属 zebra/general/legacy 规则并完成路由回归。
- 最终验收：相关 pytest 与端到端 `fix/zh_all_table_pages.pdf` 全页解析，输出至全新目录并审查结构化 JSON 与 PNG。

## 进度

- [x] 设计与行为基线经用户确认。
- [x] 创建有线、共享 native-span、英文专属三个阶段计划。
- [x] 用户确认极限迁移边界、完整 benchmark 方案和 Superpowers 执行流程。
- [ ] 按极限迁移执行计划开始 Sprint 000，随后逐 Sprint 通过独立 Evaluator。
