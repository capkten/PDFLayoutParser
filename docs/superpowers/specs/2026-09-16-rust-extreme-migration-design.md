# PDF 表格逻辑 Rust 极限迁移设计

状态：已确认（2026-09-16）

Python 行为基线：`feature-dev@dc00211fe0cf95bc8c3412c883311fe86f8d8357`

实现分支：`codex/pdf-fast-rust-migration`

## 目标

在保持当前 Python/PyMuPDF 输入边界、公开 API、Table/Cell 输出和业务路由行为不变的前提下，将有线表格、中文/混合无线表格、英文无线表格以及其他能够表达为 owned DTO 的纯 Python 表格算法尽可能完整地迁移到 Rust，并用同一输入的输出对照和前后 benchmark 证明结果与收益。

## 已确认的边界

Python 保留：

- PDF 打开、页面访问、旋转和 PyMuPDF/MuPDF 调用；
- `drawing`、`words`、native span、字符 bbox、背景矩形和 underlines 的读取；
- YOLO/ONNX/ML 推理、页面语言识别、服务编排和公开 API；
- Python `Table`/`Cell` 构造、JSON/Markdown 序列化和最终输出。

Rust 负责：

- owned DTO 上的几何、bbox、排序、聚类、线段和交点处理；
- 有线表格区域、网格、Cell、文字归属和开放边界算法；
- native span、atom、text run、列带、行列网格和候选表恢复；
- 中文/混合表格的 header topology、rowspan、colspan、occupancy 和空槽位；
- 英文 zebra、general wireless、text-alignment 和 legacy callback 内部纯算法；
- 能从 Python 对象边界剥离出来的表头和结构后处理。

如果一个函数只消费普通数值、字符串和列表并返回同类结构化数据，默认必须迁移；如果它仍依赖 PyMuPDF、公开 Python 对象、服务状态或不可替代的业务语义，必须在能力矩阵中记录保留理由。

## 总体架构

```text
Python / PyMuPDF / ONNX
        │
        │  按页或区域提取并转换为 owned DTO
        ▼
Rust pdf_fast
        │
        ├── geometry / ordering
        ├── wired table
        ├── native span / atom / text run
        ├── wireless grid / header topology
        ├── rowspan / colspan / occupancy
        └── English zebra / alignment
        │
        │  返回 owned result DTO
        ▼
Python adapter
        │
        ├── Table / Cell 构造
        ├── 公开 API 和语言路由
        └── JSON / Markdown / 页面输出
```

每个 Rust 入口以页或表格区域为批处理边界；纯计算阶段释放 GIL，不在 Cell 或 token 级别往返 FFI。生产路由支持 `python`、`shadow`、`rust` 三种模式，默认一直保持 Python，直到对应阶段通过所有门禁。

## 迁移阶段

1. **基线和 benchmark**：固定输入、环境、输出规范和前后计时协议。
2. **Rust DTO/FFI 核心**：扩展已有 abi3 PyO3 模块，形成统一输入输出结构。
3. **有线表格**：线段、区域、网格、Cell、文字归属和开放边界。
4. **共享几何与候选逻辑**：供有线和无线共用的排序、overlap、聚类和区域筛选。
5. **native-span 核心**：span、atom、text run、候选恢复和输出顺序。
6. **中文/混合无线**：列带、物理行、逻辑网格、header topology、跨度和空槽位。
7. **英文无线**：zebra、general wireless、text-alignment、legacy 内部算法。
8. **结构后处理**：可 DTO 化的表头、跨行跨列和结构规范化。
9. **shadow、切换和全量验收**：逐路径切换，完成全量 PDF、benchmark 和发布物检查。

## Benchmark 设计

Benchmark 必须覆盖五层：

- **纯函数**：同一 DTO 的 Python/Rust 算法耗时；
- **FFI**：DTO 构造、传输、Rust 计算、结果转换和 Python 装配分别计时；
- **表格区域**：同一表格区域的完整 wired/wireless 计算；
- **单页**：PDF 提取、ML、adapter、Rust、对象装配、输出和页面总耗时；
- **全量 PDF**：`D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf` 的总耗时、阶段耗时和页分布。

每次运行记录：

- Git commit、PDF SHA-256、模型路径和 SHA-256；
- Python/Rust/PyMuPDF/PyO3 版本、OS、CPU、线程数和 DPI；
- warmup、正式运行次数、cold/warm 标识；
- mean、min、max、P50、P95、P99、吞吐和峰值内存；
- 表格数、Cell 数、失败页数以及结构化输出 manifest。

推荐协议：函数级 warmup 3 次、正式 10 次；页面级 warmup 1 次、正式 5 次；全量 warmup 1 次、正式 3 次，均使用独立进程。

比较规则：结构化输出先 canonicalize，再逐字段比较；不使用宽泛 ignore。差异必须记录 fixture、page、table、field、Python 值、Rust 值、容差、分类和处理结论。目标热点争取达到 `1.5x`，但在基线测得前不假设收益；Rust 路径不得造成明显端到端回退。

## 兼容性不变量

- Python/PyMuPDF 不被 Rust 重新实现或持有；
- 公开 Python API、CLI、JSON/Markdown schema、异常和空结果保持不变；
- 线段、文字、Cell、Table 的顺序、bbox、文本、source、confidence、rowspan、colspan 和空槽位保持不变；
- 中文/混合路径不回读 `page.get_text("words")`，不走 zebra 或 legacy words 重建；
- span 到 atom/text run 阶段完成同字段文字组合并保留来源连续性；
- 每次跨度变化都重新检查 occupancy，未覆盖槽位单独生成空 `1x1` Cell；
- 不用业务文字硬编码推断多级表头；
- 不用增加浮点容差掩盖 Python/Rust 差异；
- Rust 迁移失败时保留 Python fallback，并明确记录未迁移原因。

## 交付和评估

每个 Sprint 必须经历 Planner → Generator → Evaluator：

1. Planner 写明函数清单、DTO、测试向量、benchmark 和验收门槛；
2. Generator 先写 RED，再实现最小 GREEN，最后写 migration record；
3. Evaluator 独立运行单测、回归、differential、页面和性能检查；
4. `pass` 才进入下一 Sprint；`repair` 只处理当前 Sprint；语义差异进入 `decisions.md`，未经确认不静默改变合同。

如使用 subagent，模型固定为 `gpt-5.6-luna`。

## 最终完成条件

- capability matrix 中所有纯 Python 表格算法均已迁移，或有明确的 Python 保留原因；
- wired、中文/混合 wireless、英文 wireless 都通过 Rust primary 路径验收；
- Python fallback 仍可用；
- 函数、FFI、区域、页面、全量 PDF 五层 benchmark 均有前后数据；
- 结构化 JSON、Table/Cell 和 PNG 视觉输出一致；
- 全量 PDF 完成到独立输出目录；
- Rust wheel、sdist、abi3、版本、入口和 Python 版本下限检查通过；
- 独立 Evaluator 给出 `pass`，最终报告明确实际性能变化。
