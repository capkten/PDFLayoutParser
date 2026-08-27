# 中文无线表格新结构恢复分流设计

## 目标

中文和中英混合页面（`zh`、`mixed`）的无线表格默认只使用 native-span 结构恢复。新恢复结果不得再进入旧的 `_rebuild_text_aligned_table()` 做基于 page words 的二次重建。

## 根因

`WirelessTableExtractor` 已对 `zh`、`mixed` 调用 `recover_cells_from_region()`，但产出的 `Table.source` 仍为 `text_alignment`。后续 `normalize_table_headers()` 仅凭该 source 判断是否调用 `_rebuild_text_aligned_table()`，因此无法区分新旧恢复路径，并覆盖已经组合好的 span 网格。

## 设计

- native-span 恢复生成的表使用独立 source：`native_span_recovery`。
- `_rebuild_text_aligned_table()` 继续只处理 legacy `text_alignment` 表，不改变旧路径兼容性。
- native-span 表仍经过通用及财务表头语义规范化，但不再从 page words 重建行列。
- 英文无线表格、有线表格及其他 source 的行为保持不变。

## 验证

- 单元测试证明 `zh`、`mixed` 调用 native-span 恢复并返回 `native_span_recovery`。
- 单元测试证明 native-span 表经过 `normalize_table_headers()` 时不调用 page word 重建，并保留原始网格和“比例”“坏账准备”等独立 span 文本。
- 保留 legacy `text_alignment` 重建测试，防止兼容路径被误删。
- 重跑 `fix/zh_all_table_pages.pdf` 第 184 页，检查语言、source、行列数、结构化 JSON 和可视化 PNG。

## 范围外问题

仅阻止旧重建覆盖新结构，不在本次分流修复中调整 native-span 的表头下界、列带推断、槽位冲突、分隔线处理或多行首列合并。这些问题需要依据第 184 页的新恢复原始输出分别修复。
