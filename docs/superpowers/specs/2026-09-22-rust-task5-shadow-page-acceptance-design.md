# Rust Task 5 Shadow 与真实页面验收设计

> 日期：2026-09-22
> Worktree：`D:\codes\PDFLayoutParser-Fast\.worktrees\rust-migration-replan`
> 分支：`codex/rust-migration-replan`

## 目标

在不改变默认 Python 路由的前提下，对真实 PDF 的代表性中文/混合无线表格页面运行 `python`、`shadow`、`rust` 三种 mode，覆盖两条高层入口，生成可复核的结构化 JSON、PNG 和字段级差异报告。

代表性页面使用 `D:\codes\PDFLayoutParser\fix\zh_all_table_pages.pdf` 的 0-based 索引：`184、188、189、191、192`。这些页面覆盖空槽位、多级表头、稀疏列、相邻表格和换行字段。

## 非目标

- 不切换默认生产路由到 Rust。
- 不把 `shadow` 的返回值改为 Rust；shadow 始终返回 Python 结果。
- 不在没有字段级证据时修改 `recoverer.py` 或 `wireless_table_recovery.py`。
- 不用全量 1023 页结果替代代表性页面验收。
- 不回读 `page.get_text("words")`，不调用 `extract_zebra()` 或 legacy `_rebuild_text_aligned_table()` 处理中文/混合无线表格。

## 现有入口与 mode 合同

Task 5 复用现有高层入口：

- `recover_cells_from_region()`：区域级 Cell 恢复入口；
- `recover_wireless_tables()`：页面级无线表格恢复入口；
- `PDF_RUST_MODE=python|shadow|rust`：选择 Python、shadow 或 Rust 行为。

合同固定如下：

- `python` 不调用 Rust；
- `shadow` 执行 Rust 观测但返回 Python 结果；
- `rust` 只有在输入 DTO、Rust 输出和最终 Cell 合同全部通过时才返回 Rust 结果；
- Rust 异常、DTO 解析失败、输出校验失败和 occupancy/fallback 诊断必须保留，不能静默当作 parity 通过；
- Python fallback 仍然可用，默认 Python route 不变。

## 方案与选择

选择“真实页面三模式对照 + 字段级报告”：每个 mode 在独立输出目录写入页面 JSON、页面 PNG 和 manifest；测试 normalizer 再比较两条入口的 Python/Rust 结果。这样既保留可视化证据，也能把差异定位到 table、Cell、span、empty slot、occupancy 或 diagnostic 字段。

不采用只人工比较 JSON/PNG 的方案，因为它不能稳定确认两条高层入口的 mode 合同；不先做全量 1023 页，因为代表性页面更适合先收敛结构差异，避免把环境或历史页面差异混入首轮验收。

## 数据流

```text
代表性 PDF + page indices
        |
        v
  python / shadow / rust mode
        |
        +--> page JSON + manifest
        +--> page PNG
        |
        v
 field-level normalizer
        |
        v
 comparison report + mismatch classification
```

输出根目录固定为：

```text
output/rust_migration_task5_20260922/
  python/
  shadow/
  rust/
  comparison/
```

每个 mode 的 manifest 必须记录输入 PDF 绝对路径、输入 SHA256、mode、commit、0-based page index、语言、表格数量、source、rows、cols、bbox、JSON 相对路径、PNG 相对路径、occupancy conflict、fallback 和 diagnostics 摘要。

## 字段级比较

normalizer 不比较根对象字符串，也不使用 broad ignore。至少比较：

- page：index、status、language、table count；
- table：source、bbox、rows、cols、table order；
- Cell：row/column position、text、bbox、ordering、source reference、`rowspan/colspan`；
- empty slots：槽位坐标、数量、空文本、`1x1` span；
- occupancy：每个逻辑槽位的 owner、覆盖次数和冲突；
- diagnostics：status、path、field、message、fallback 类型；
- mode contract：shadow 返回值与 Python 结果等价，Rust mismatch 不丢失。

每条 mismatch 记录 fixture/page、entry、layer、field、Python 值、Rust 值、classification 和 source mode。分类只允许 `accepted`、`requires_adaptation`、`defect`、`unsupported`；未分类差异阻止 Task 5 通过。

## JSON 与 PNG 验收

结构化检查必须确认：

- 页面索引和页码映射正确；
- 表格数量与 source 合理；
- 表格 bbox 没有吸收页眉、正文或相邻表格；
- 行列数、Cell 文本归属和 Cell bbox 合理；
- 多级表头的 `rowspan/colspan` 与空槽位符合逻辑网格；
- 每个逻辑槽位恰好由一个 Cell 占用，occupancy conflict 为零；
- shadow 返回结果与 Python 结果一致，Rust 诊断仍可追踪。

PNG 检查使用独立输出目录，逐页确认：

- 表格边界没有吸收外部内容；
- 相邻表格没有误合并；
- 组内竖线、组间边界和多级表头横线连续；
- 空槽位仍有独立线框；
- 换行字段没有产生伪行或错误拆列。

## 测试与失败策略

实现遵循 RED → GREEN → focused regression：

1. 新增两条入口的 field-level shadow differential 测试，先确认当前缺少报告/合同时失败；
2. 添加最小 normalizer、manifest 和比较报告实现；
3. 运行代表性页面三模式导出；
4. 运行结构化检查和 PNG 视觉核对；
5. 若 mismatch 指向明确、局部且已有 Task 4 合同的 Rust/适配缺陷，才增加回归测试并修改对应生产代码；
6. 若差异是未确认的 Python 行为、输入环境或产品语义选择，保留报告并暂停，不修改测试来接受差异。

生产代码只允许在差异报告明确证明 bounded defect 时修改，并且修改范围限定为 `src/hexai_pdf_parser/tables/wireless_structure/recoverer.py` 或 `src/hexai_pdf_parser/tables/wireless_table_recovery.py`。

## 完成标准

Task 5 只有在以下条件全部满足时才可标记完成：

1. 两条高层入口的 `python`、`shadow`、`rust` mode 均有独立输出；
2. shadow mismatch/fallback 为零，或每条差异都有显式 classification、decision record 和 regression fixture；
3. 五个代表性页面的结构化 JSON 和 PNG 均已核对；
4. 每个逻辑槽位的 occupancy 恰好一次覆盖，没有未解释冲突；
5. 默认 Python route、fallback 和用户已有 dirty 文件保持不变；
6. 测试、`cargo check`、`git diff --check` 和输出路径记录齐全。
