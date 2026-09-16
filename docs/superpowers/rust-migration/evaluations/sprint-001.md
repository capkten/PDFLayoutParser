# Sprint 001 独立评估（修复后）

## 结论

**Recommendation: pass**

评估范围为 `064f84b031dced24201099ba73a1845086152ec0..a8a3e1c`，当前 HEAD 为 `a8a3e1cfeb4f2b503adcef047c455fa0b7aebb4d`。指定 Rust/Python 检查通过；六组固定输入与 Python oracle 输出一致；wheel 和 sdist 满足本 sprint 的 ABI、metadata、入口、源码/包数据与排除项要求。NaN 排序缺陷已由测试先行提交修复，生产表格路由仍未切换。

首次实现的历史 RED 输出没有持久化，且首次实现与测试同在 `a58d04e`，因此无法追溯证明那些最初测试先于首次实现。本次 NaN 修复的 TDD 证据则足够持久：测试-only commit `eb45b5618704ea531aba1ed5b911a8074e14cc36` 是修复 commit 的祖先，且在该未修复提交上独立重跑仍得到预期失败。此评估确认修复后的 sprint 状态，不追认首次实现的 TDD 历史。

## 范围与验收

| 验收项 | 结果 | 证据 |
|---|---|---|
| Sprint 所有权与生产路由 | PASS | 范围内 13 个文件；未改 `wired_table_extractor.py`，原 Python 调用仍在，Rust adapter 未接入生产路径。无超出本 sprint 的生产行为改动。 |
| Rust 行为与固定向量 | PASS | Rust 单测 6 passed；与 `WiredTableExtractor._merge_h_lines` 直接差分的六组归一化输出全部匹配：近邻合并、间隙分段、空输入、1.15、2.25、NaN 稳定顺序。无容差放宽。 |
| Rust 格式 | PASS | `cargo fmt --check` exit 0，无输出。 |
| Python binding 与有线回归 | PASS | 指定 Python 3.12 pytest 执行器：69 passed、5 warnings、exit 0。警告为既有 PyMuPDF SWIG 类型弃用警告；进程退出另有同类警告。 |
| NaN 修复 TDD chronology | PASS | 测试-only commit `eb45b5618704ea531aba1ed5b911a8074e14cc36`（19:30）先于修复 commit `a8a3e1cfeb4f2b503adcef047c455fa0b7aebb4d`（19:49），并为其祖先。前者只在 Rust 测试模块和 pytest 文件增加断言，没有生产实现改动。未修复 worktree 的两项重跑均按预期失败。 |
| 首次实现 TDD chronology | LIMITATION | `records/merge-h-lines.md` 明确记录原始 RED 输出未保存；`a58d04e` 同时加入实现和测试。首次实现的 test-first 顺序无法由现有提交历史独立证明。 |
| Wheel ABI、metadata、入口 | PASS | `target/wheels-sprint001-repair/hexai_pdf_parser-1.1.1-cp37-abi3-win_amd64.whl`；文件名/tag 为 `cp37-abi3-win_amd64`；`Version: 1.1.1`；`Requires-Python: >=3.7`；console entry point 为 `hexai_pdf_parser=hexai_pdf_parser.cli:main`。 |
| Wheel package data | PASS | 包含 3 个 table template JSON 和 `best.onnx`，共 4 个要求的运行时包数据文件。 |
| sdist 源码与 package data | PASS | `target/sdist-sprint001-repair/hexai_pdf_parser-1.1.1.tar.gz` 有 278 个文件；含 `Cargo.toml`、`Cargo.lock`、`rust/lib.rs`、Python `src/`，以及 3 个 template JSON 和 1 个 ONNX 模型。 |
| sdist 排除项 | PASS | 归档路径段中均未出现 `output`、`target`、`.venv`、`.codegraph`、`.cursor`、`.gemini`、`.superpowers`、`.devops`；没有 `zh_all_table_pages.pdf`。 |
| 差异检查 | PASS | `git diff --check 064f84b031dced24201099ba73a1845086152ec0..a8a3e1c --check` exit 0，无输出。 |

## 独立命令与证据

以下 profiling-worktree 命令均先执行 `Set-Location 'D:\codes\PDFLayoutParser\.worktrees\codex-pdf-fast-profiling'`：

```powershell
cargo test
```

结果：6 passed、0 failed；doc-tests 0 passed、0 failed。

```powershell
cargo fmt --check
```

结果：exit 0，无输出。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_pdf_fast_binding.py tests/test_wired_table_extractor.py
```

结果：69 passed、5 warnings，4.29s，exit 0；进程退出时有一条同类 SWIG 弃用警告。

```powershell
git diff --check 064f84b031dced24201099ba73a1845086152ec0..a8a3e1c --check
```

结果：exit 0，无输出。

按要求在 `D:\codes\PDFLayoutParser\.worktrees\codex-pdf-fast-nan-red-check` 独立重跑，没有修改或删除该 worktree：

```powershell
cargo test
```

结果：5 passed、1 failed。`preserves_input_order_when_rounded_y_comparison_is_nan` 失败，实际首项 `x0=0.0`、期望 `x0=10.0`，exit 1。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:\Users\23662\AppData\Local\Programs\Python\Python312\Scripts\pytest.exe' -q tests/test_pdf_fast_binding.py -k nan
```

结果：1 failed、5 deselected。`test_merge_h_lines_preserves_input_order_when_rounded_y_is_nan` 实际首项 `x0=0.0`、期望 `x0=10.0`，exit 1。red worktree HEAD 仍为 `eb45b5618704ea531aba1ed5b911a8074e14cc36`，`git status --short` 无改动。

Python 3.12 只读差分分别调用 Python oracle 和 Rust adapter，将 NaN 归一化后比较；六组均输出 `MATCH`，最后结果 `ALL_SIX_MATCH True`。本探针不把 NaN 当普通相等值比较。

使用 Python 3.12 `zipfile`、`email.parser` 与 `tarfile` 检查上述指定目录中的归档，逐字段读取 wheel metadata/entrypoint 和 sdist 成员。Wheel package data 为 `best.onnx` 与三个模板 JSON；sdist 所有必需 Rust/Python 成员与四个 package data 文件均存在，指定排除目录命中数为 0，本机 PDF 命中数为 0。

## 差异分类

| 差异 | 分类 | 依据 |
|---|---|---|
| 修复前 NaN y 排序时误以 `x0` 次级排序 | defect，已修复 | red worktree 两类测试均复现顺序差异；修复后稳定排序与 Python oracle 一致。 |
| 通用 `py3-none-any` 改为平台相关 `cp37-abi3` wheel | accepted | 用户确认的 abi3-py37 与按平台构建要求；实际 wheel tag 符合。 |
| 扩展发行版本为 1.1.1，与历史 setuptools 版本文件 1.1.0 不同 | accepted | decisions.md 已确认 1.1.1 为 Sprint 001 包版本；实际 wheel metadata 符合。 |
| adapter 将数值 DTO 显式转换为 float tuple | accepted | 符合接口合同；六组结构化结果中的数值、顺序和 tuple 结构匹配。 |
| Cargo 可选 crate 发布字段缺失警告 | accepted | sdist/build 检查不以这些可选 crate 字段为验收条件；本次归档已成功生成。 |

没有发现尚未处置的行为差异或 scope violation。sdist 另包含两个 `simple_test_50` JSON 文件；它们不在题定排除项中，也不是 wheel 运行时 package data，本次未发现其影响本 sprint 合同的证据。

## 限制与风险

- 原始首次实现的 TDD RED 证据不足以追溯证明先测后实现；本次新增 NaN 缺陷的修复 chronology 有独立测试-only commit 和可复跑的 RED 结果支撑。
- 仅在 Windows x64、Python 3.12 验证；未在 Python 3.7 运行时或其他操作系统/架构导入 wheel。abi3 tag 和 `Requires-Python` metadata 已验证，但不能替代这些运行时覆盖。
- 未运行整份 PDF 的 JSON/PNG 对照或 benchmark。该 sprint 不切生产路由，只新增独立纯 DTO adapter；本次不据此声明端到端等价或性能收益。
- `codegraph explore` 在该环境返回 `unknown command 'explore'`，且没有 CodeGraph MCP 工具可用；已按指定提交范围直接审阅完整 diff、迁移记录及调用点。此项没有阻碍本次窄范围验证。

## 有界后续

本 sprint 无阻塞修复项；继续其他函数迁移前，保持逐函数测试、差分与平台构建验证，不把本次单函数通过扩展解释为全路径迁移完成。
