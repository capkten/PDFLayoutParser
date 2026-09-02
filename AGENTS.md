Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. 中文无线表格结构恢复约束

处理 `zh`/`mixed` 页面的无线表格时，默认遵循以下不变量：

- 使用 native-span 新结构恢复；除非任务明确要求验证旧路径，否则不得回退到 `extract_zebra()`、legacy `_rebuild_text_aligned_table()` 或其他基于 page words 的二次重建。
- Span 到 atom 阶段负责完成视觉上属于同一字段的文本组合。进入 atom、列带和逻辑 Cell 处理后，不得再次调用 `page.get_text("words")` 读取表格文字。
- 结构恢复阶段只消费 native span、atom、列带、物理 Cell 和逻辑 Cell；后续职责仅包括行列划分、`rowspan/colspan` 恢复、冲突检查和空单元格物化。
- 不得仅因两个 atom/span 位于同一候选槽位就合并它们。独立字段默认保留为独立叶子列；同一单元格包含多个 span 的文本组合应在更早阶段完成并保留来源连续性证据。
- 多级表头必须依据几何和拓扑关系推断，不得硬编码“年初数”“金额”“比例”“坏账准备”等业务文字。二叶子列父表头只在同层父标题与下一层连续叶子列形成完整、无重叠的 `1:2` 配对时恢复 `colspan=2`；任一组不成立时放弃整层推断。
- `rowspan` 只能在物理行压缩并生成逻辑网格之后、空单元格物化之前恢复。只有父标题与叶子标题之间的覆盖槽位均为空时才能向下扩展；存在非空标题时必须拒绝合并。
- 表格中的空槽位也是结构的一部分。所有未被现有 `rowspan/colspan` 覆盖的槽位都生成独立 `text=""`、`1x1` Cell；按推断网格边界直接切分，不合并相邻空单元格。
- 最终每个逻辑槽位必须恰好被一个 Cell 占用。任何跨度调整后都要重新执行 occupancy conflict 检查，冲突结果不得进入最终表格。
- 修复必须测试先行：先添加最小失败用例，再做最小实现；至少覆盖目标正例、拒绝误合并的反例以及既有相关测试。
- 页面级交付必须重跑到新的独立输出目录，同时核对结构化结果和最终 PNG。检查表格数量、source、行列数、跨度、空槽位、占位冲突、表格边界、组内/组间线框以及相邻表格是否误并。
- 说明文档、设计文档和 `changes.md` 使用中文，并记录根因、判定条件、调用位置、不回读 words 的约束、测试结果和页面输出路径。

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Project development workflow

For PDF table debugging, single-page runs, CodeGraph usage, visual verification, language-aware extraction, testing, and commit conventions, load [DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md) when needed.

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->
