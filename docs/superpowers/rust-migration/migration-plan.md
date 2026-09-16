# PDF 表格逻辑 Rust 迁移总计划

## 目标

按已确认的精确行为合同，将有线、中文/混合无线、英文无线的纯计算逻辑逐函数迁入一个 PyO3/maturin 扩展。Python 保留 PDF 解析与提取、API、路由、项目对象和序列化；每个函数以相同结构化输入向量锁定输出。

## 阶段顺序

1. **构建基础与有线逻辑**：[有线阶段计划](../plans/2026-09-16-rust-wired-table-logic.md)。先建立可安装的 abi3 扩展和 DTO，再从线段合并推进到区域/网格/Cell 几何及 Python words 适配。
2. **共享 native-span 无线核心**：[native-span 阶段计划](../plans/2026-09-16-rust-native-span-wireless-core.md)。包含 `wireless_structure` 中文/混合表格恢复，以及 `recover_wireless_tables` 共享候选路径；英文候选入口复用同一核心。
3. **英文专属无线算法**：[英文阶段计划](../plans/2026-09-16-rust-english-wireless.md)。在共享候选层已稳定后，迁移 drawing 背景、斑马纹、general wireless 和其 words 算法。

每一阶段可独立评审和验收；生产路由只在相应阶段所有纯函数与 facade 测试通过后切换。尚未迁移的路径继续走现有 Python 实现。

## 通用执行规则

- 每个待迁函数先从 Python 基线构造相同输入/预期输出的失败测试；Rust 单测和 pytest binding 测试引用同一组小型 JSON/fixture 向量。
- Rust DTO 持有 `f64` 坐标、`String`、有序 `Vec` 和显式来源索引；将 `fitz.Rect`、Python `Cell` 等对象留在适配层之外。
- 每次 PyO3 调用按页或区域传递完整批次；长计算阶段释放 GIL，不逐 token/Cell 往返 FFI。
- 有线 drawing 与 words、无线 native span、英文 background/words 都由 Python/PyMuPDF 采集；纯规则在 Rust 执行。
- 每次阶段完成运行 Rust 单测、模块 pytest、相关 facade/API 测试、页面端测、`git diff --check`；验证记录写入 `changes.md` 和 sprint evaluation。
- 不运行 benchmark，不以速度为通过标准。端到端耗时只作为运行记录，不比较或宣称收益。
- 不将主工作区未提交内容、295 MB 本地 PDF 或输出产物提交到迁移分支。

## 交付顺序

- Sprint 001：建立最小 abi3 PyO3 扩展并迁移一个纯函数 `_merge_h_lines`；验证 cargo、pytest、wheel 元数据与 Python 3.7 下限。
- Sprint 002 及后续：逐函数完成有线与 Python words 适配；每个函数单独有输入/输出合同。
- 下一阶段：完成 native-span 采集边界及共享候选内核，再完成中文/混合 `wireless_structure`。
- 最后一阶段：迁移英文专属 zebra/general/legacy 规则并完成路由回归。
- 最终验收：相关 pytest 与端到端 `fix/zh_all_table_pages.pdf` 全页解析，输出至全新目录并审查结构化 JSON 与 PNG。

## 进度

- [x] 设计与行为基线经用户确认。
- [x] 创建有线、共享 native-span、英文专属三个阶段计划。
- [ ] 用户选择执行方式后开始 Sprint 001；当前尚未改生产代码。
